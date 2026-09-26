"""远程配置客户端。

通过 WebSocket 与服务端保持长连接，使服务端可以随时读取 / 修改本程序的配置。
协议（JSON 文本帧）详见 ``docs/remote_websocket.md``。

特性：
- 使用 ``PyQt5.QtWebSockets.QWebSocket``，运行在 Qt 事件循环中，无需额外线程；
- 可选的 token 鉴权与自动重连；
- 支持“仅允许远程修改”的锁定项（见 :class:`file.ConfigCenter`），
  被锁定的配置项将拒绝一切本地写入，只接受远程写入。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
from typing import Any, Callable, Dict, Optional

from loguru import logger
from PyQt5.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt5.QtWebSockets import QWebSocket

from file import config_center

PROTOCOL_VERSION = 1
DEFAULT_RECONNECT_MS = 5000


class RemoteConfigClient(QObject):
    """WebSocket 远程配置客户端。"""

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    auth_failed = pyqtSignal(str)
    applied = pyqtSignal(dict)
    notification = pyqtSignal(dict)
    ota_ready = pyqtSignal(str)  # 更新包已下载校验，待安装的本地路径

    def __init__(
        self,
        parent: Optional[QObject] = None,
        reload_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._reload_callback = reload_callback
        self._ws = QWebSocket()
        self._ws.connected.connect(self._on_connected)
        self._ws.disconnected.connect(self._on_disconnected)
        self._ws.textMessageReceived.connect(self._on_text_message)
        self._ws.error.connect(self._on_error)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._connect)
        self._started = False
        self.ota_ready.connect(self._install_and_restart)

    # -- 生命周期 ---------------------------------------------------------- #
    def start(self) -> None:
        if self._started:
            return
        if not self._enabled():
            logger.info('远程配置未启用（Remote.enabled=0），跳过连接')
            return
        if not self._url():
            logger.warning('远程配置已启用，但未配置 Remote.url，跳过连接')
            return
        self._started = True
        self._connect()

    def stop(self) -> None:
        self._started = False
        self._reconnect_timer.stop()
        try:
            self._ws.close()
        except Exception:  # noqa: S110 - 关闭失败无需处理
            pass

    # -- 配置读取 ---------------------------------------------------------- #
    def _enabled(self) -> bool:
        return str(config_center.read_conf('Remote', 'enabled') or '0') == '1'

    def _url(self) -> str:
        return str(config_center.read_conf('Remote', 'url') or '').strip()

    def _auto_reconnect(self) -> bool:
        return str(config_center.read_conf('Remote', 'auto_reconnect') or '1') == '1'

    def _reconnect_delay_ms(self) -> int:
        try:
            return max(1000, int(float(config_center.read_conf('Remote', 'reconnect_interval') or 5)) * 1000)
        except (TypeError, ValueError):
            return DEFAULT_RECONNECT_MS

    def _connect(self) -> None:
        if not self._started:
            return
        url = self._url()
        if not url:
            return
        logger.info(f'远程配置：正在连接 {url}')
        self._ws.open(QUrl(url))

    # -- 事件 -------------------------------------------------------------- #
    def _on_connected(self) -> None:
        logger.success('远程配置：已连接到服务端')
        self.send(
            {
                'type': 'hello',
                'protocol': PROTOCOL_VERSION,
                'app': 'LiumingClassroom',
                'token': str(config_center.read_conf('Remote', 'token') or ''),
            }
        )
        self.connected.emit()

    def _on_disconnected(self) -> None:
        logger.warning('远程配置：与服务端断开连接')
        self.disconnected.emit()
        if self._started and self._auto_reconnect():
            self._reconnect_timer.start(self._reconnect_delay_ms())

    def _on_error(self, _error: Any) -> None:
        logger.error(f'远程配置：WebSocket 错误：{self._ws.errorString()}')

    def _on_text_message(self, message: str) -> None:
        try:
            data = json.loads(message)
        except (ValueError, TypeError):
            logger.warning(f'远程配置：收到非法 JSON：{message[:200]}')
            return
        if isinstance(data, dict):
            self._dispatch(data)

    def send(self, payload: Dict[str, Any]) -> None:
        try:
            self._ws.sendTextMessage(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            logger.error(f'远程配置：发送消息失败：{e}')

    # -- 协议分发 ---------------------------------------------------------- #
    def _dispatch(self, data: Dict[str, Any]) -> None:
        action = data.get('action')
        msg_id = data.get('id')

        if action == 'auth':
            if data.get('ok', True):
                logger.success('远程配置：鉴权通过')
            else:
                reason = str(data.get('error', '鉴权失败'))
                logger.error(f'远程配置：{reason}')
                self.auth_failed.emit(reason)
                self.stop()
            return

        if action == 'notify':
            self.notification.emit(data)
            return

        if action == 'ping':
            self._reply(msg_id, ok=True, data={'pong': data.get('time')})
            return

        if action is None:
            return

        try:
            result = self._handle(action, data)
        except Exception as e:  # 单条请求失败不影响连接
            logger.error(f'远程配置：处理 {action} 失败：{e}')
            self._reply(msg_id, ok=False, error=str(e))
            return
        self._reply(msg_id, ok=result.get('ok', True), data=result.get('data'), error=result.get('error'))
        self.applied.emit({'action': action, 'request': data})

    def _handle(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if action == 'get':
            section = str(data.get('section', ''))
            key = str(data.get('key', ''))
            value = config_center.read_conf(section, key) if key else config_center.read_conf(section)
            return {'ok': True, 'data': value}

        if action == 'set':
            section = str(data.get('section', ''))
            key = str(data.get('key', ''))
            if not section or not key:
                return {'ok': False, 'error': '缺少 section/key'}
            ok = config_center.write_conf(section, key, data.get('value'), source='remote')
            self._reload()
            return {'ok': bool(ok)}

        if action == 'set_many':
            changed, failed = [], []
            for item in data.get('items') or []:
                if not isinstance(item, dict):
                    continue
                section = str(item.get('section', ''))
                key = str(item.get('key', ''))
                if not section or not key:
                    continue
                if config_center.write_conf(section, key, item.get('value'), source='remote'):
                    changed.append(f'{section}.{key}')
                else:
                    failed.append(f'{section}.{key}')
            self._reload()
            return {
                'ok': not failed,
                'data': {'changed': changed, 'failed': failed},
                'error': ('写入失败: ' + ', '.join(failed)) if failed else None,
            }

        if action == 'reload':
            self._reload()
            return {'ok': True}

        if action in ('lock', 'unlock'):
            locked = action == 'lock'
            keys = data.get('keys') or data.get('key') or []
            if isinstance(keys, str):
                keys = [keys]
            for lock_id in keys:
                lock_id = str(lock_id)
                if '.' not in lock_id:
                    continue
                section, _, key = lock_id.partition('.')
                config_center.set_locked(section, key, locked)
            return {'ok': True, 'data': {'locked': config_center.list_locks()}}

        if action == 'locks':
            return {'ok': True, 'data': {'locked': config_center.list_locks()}}

        if action == 'duty_get':
            from duty import config_to_dict, get_duty_manager

            return {'ok': True, 'data': config_to_dict(get_duty_manager().config)}

        if action == 'duty_set':
            from duty import config_from_dict, get_duty_manager

            manager = get_duty_manager()
            manager.config = config_from_dict(data.get('config') or {})
            manager.save()
            self._reload()
            return {'ok': True}

        if action == 'ota':
            return self._handle_ota(data)

        return {'ok': False, 'error': f'未知 action: {action}'}

    def _reply(self, msg_id: Any, ok: bool, data: Any = None, error: Any = None) -> None:
        if msg_id is None:
            return
        payload: Dict[str, Any] = {'id': msg_id, 'ok': ok}
        if data is not None:
            payload['data'] = data
        if error:
            payload['error'] = error
        self.send(payload)

    def _reload(self) -> None:
        if self._reload_callback is None:
            return
        try:
            self._reload_callback()
        except Exception as e:
            logger.error(f'远程配置：热重载失败：{e}')

    # -- OTA：静默下载、安装并重启 ----------------------------------------- #
    def _handle_ota(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """服务端下发 OTA：后台下载校验，完成后静默安装并重启。"""
        url = str(data.get('url') or '').strip()
        if not url:
            return {'ok': False, 'error': '缺少 url'}
        threading.Thread(target=self._run_ota, args=(dict(data),), daemon=True).start()
        return {'ok': True, 'data': {'started': True, 'version': data.get('version')}}

    def _run_ota(self, data: Dict[str, Any]) -> None:
        """在子线程中下载并校验更新包。"""
        try:
            url = str(data.get('url') or '').strip()
            sha = str(data.get('sha256') or '').strip().lower()
            filename = os.path.basename(url.split('?')[0]) or 'update.pkg'
            dest = os.path.join(tempfile.gettempdir(), filename)
            logger.info(f'OTA：正在下载 {url}')
            urllib.request.urlretrieve(url, dest)  # noqa: S310 - URL 由受信后端下发
            if sha:
                digest = hashlib.sha256()
                with open(dest, 'rb') as f:
                    for chunk in iter(lambda: f.read(1 << 20), b''):
                        digest.update(chunk)
                if digest.hexdigest().lower() != sha:
                    logger.error('OTA：SHA256 校验失败，已中止')
                    return
            logger.success('OTA：下载完成，准备静默安装并重启')
            self.ota_ready.emit(dest)  # 切回主线程执行安装
        except Exception as e:
            logger.error(f'OTA 失败：{e}')

    def _install_and_restart(self, path: str) -> None:
        """在主线程中静默安装更新包并重启程序。"""
        try:
            exe = sys.executable
            install_dir = os.path.dirname(exe)
            if path.lower().endswith('.zip'):
                bat = os.path.join(tempfile.gettempdir(), 'liuming_ota.bat')
                with open(bat, 'w', encoding='utf-8') as f:
                    f.write('@echo off\r\n')
                    f.write('timeout /t 2 /nobreak >nul\r\n')
                    f.write(
                        'powershell -NoProfile -Command "Expand-Archive -Path \'%s\' '
                        '-DestinationPath \'%s\' -Force"\r\n' % (path, install_dir)
                    )
                    f.write('start "" "%s"\r\n' % exe)
                    f.write('del "%s"\r\n' % path)
                subprocess.Popen(['cmd', '/c', bat], creationflags=0x00000008 | 0x00000200)
            else:
                subprocess.Popen([path], close_fds=True)  # noqa: S603 - 受信后端下发
        except Exception as e:
            logger.error(f'OTA：启动安装失败：{e}')
            return
        logger.info('OTA：即将退出以完成更新')
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication

        QTimer.singleShot(800, QApplication.quit)
