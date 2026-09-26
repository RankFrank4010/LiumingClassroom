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
from typing import Any, Callable, Dict, List, Optional

from loguru import logger
from PyQt5.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt5.QtWebSockets import QWebSocket

from basic_dirs import CONFIG_HOME, CW_HOME, PLUGIN_HOME, SCHEDULE_DIR
from file import config_center, load_from_json, save_data_to_json

PROTOCOL_VERSION = 2
DEFAULT_RECONNECT_MS = 5000

WS_PATH = '/api/classroom/ws'
PAIR_PATH = '/api/classrooms/pair'


def normalize_server_address(text: str) -> tuple[str, str] | tuple[None, None]:
    """把用户输入的服务器地址规范化为 (ws_url, http_base)。

    支持以下输入（域名或 IP，可带端口，可带协议）：
    - ``example.com:8080`` / ``192.168.1.10``（默认按 http 处理）
    - ``https://example.com`` / ``http://127.0.0.1:3000``
    - ``ws://127.0.0.1:8765`` / ``wss://example.com``（也兼容旧的完整 ws 路径）
    """
    raw = str(text or '').strip().rstrip('/')
    if not raw:
        return None, None
    scheme = 'http'
    for prefix in ('https://', 'http://', 'wss://', 'ws://'):
        if raw.lower().startswith(prefix):
            scheme = {'https://': 'https', 'http://': 'http', 'wss://': 'wss', 'ws://': 'ws'}[prefix]
            raw = raw[len(prefix):]
            break
    host = raw.split('/')[0]
    if not host:
        return None, None
    if scheme == 'http':
        ws_scheme = 'ws'
    elif scheme == 'https':
        ws_scheme = 'wss'
    else:
        ws_scheme = scheme
        scheme = 'https' if scheme == 'wss' else 'http'
    return f'{ws_scheme}://{host}{WS_PATH}', f'{scheme}://{host}{PAIR_PATH}'


class RemoteConfigClient(QObject):
    """WebSocket 远程配置客户端。"""

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    auth_failed = pyqtSignal(str)
    applied = pyqtSignal(dict)
    notification = pyqtSignal(dict)
    ota_ready = pyqtSignal(str)  # 更新包已下载校验，待安装的本地路径
    state_changed = pyqtSignal(str, str)  # (state, detail)
    connection_error = pyqtSignal(str)  # 连接/鉴权错误信息（用于界面提示）

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
        self.state = 'stopped'
        self.last_error = ''
        self._last_state_emit = None

    # -- 连接状态 ---------------------------------------------------------- #
    STATUS_TEXT = {
        'disabled': '未启用',
        'connecting': '连接中…',
        'connected': '已连接（鉴权中）',
        'authed': '已连接',
        'disconnected': '已断开',
        'auth_failed': '鉴权失败',
        'error': '连接错误',
        'stopped': '已停止',
    }

    def _set_state(self, state: str, detail: str = '') -> None:
        self.state = state
        if state in ('error', 'auth_failed') and detail:
            self.last_error = detail
        if state == 'authed':
            self.last_error = ''
        pair = (state, detail)
        if pair == self._last_state_emit:
            return
        self._last_state_emit = pair
        logger.debug(f'远程配置：状态 -> {state} {detail}'.rstrip())
        self.state_changed.emit(state, detail)

    def status_text(self) -> str:
        base = self.STATUS_TEXT.get(self.state, self.state)
        if self.state in ('error', 'auth_failed', 'disconnected') and self.last_error:
            return f'{base}：{self.last_error}'
        return base

    # -- 生命周期 ---------------------------------------------------------- #
    def start(self) -> None:
        if self._started:
            return
        if not self._enabled():
            logger.info('远程配置未启用（Remote.enabled=0），跳过连接')
            self._set_state('disabled', '未启用远程配置')
            return
        if not self._url():
            logger.warning('远程配置已启用，但未配置 Remote.url，跳过连接')
            self._set_state('error', '已启用，但未配置服务器地址')
            self.connection_error.emit('已启用远程配置，但未配置服务器地址')
            return
        self._started = True
        self._set_state('connecting', self._url())
        self._connect()

    def stop(self) -> None:
        self._started = False
        self._reconnect_timer.stop()
        try:
            self._ws.close()
        except Exception:  # noqa: S110 - 关闭失败无需处理
            pass
        self._set_state('stopped', '已停止')

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
        self._set_state('connecting', url)
        self._ws.open(QUrl(url))

    # -- 事件 -------------------------------------------------------------- #
    def _on_connected(self) -> None:
        logger.success('远程配置：已连接到服务端')
        self._set_state('connected', '已连接，正在鉴权…')
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
        detail = self.last_error or ('连接已断开，等待重连…' if self._auto_reconnect() else '连接已断开')
        self._set_state('disconnected', detail)
        self.disconnected.emit()
        if self._started and self._auto_reconnect():
            self._reconnect_timer.start(self._reconnect_delay_ms())

    def _on_error(self, _error: Any) -> None:
        detail = self._ws.errorString() or 'WebSocket 连接错误'
        logger.error(f'远程配置：WebSocket 错误：{detail}')
        self._set_state('error', detail)
        self.connection_error.emit(detail)

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
                self._set_state('authed', '已连接并鉴权通过')
            else:
                reason = str(data.get('error', '鉴权失败'))
                logger.error(f'远程配置：{reason}')
                self._set_state('auth_failed', reason)
                self.connection_error.emit(f'鉴权失败：{reason}')
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

        if action == 'snapshot':
            return self._handle_snapshot(data)

        if action == 'apply':
            return self._handle_apply(data)

        if action == 'ota':
            return self._handle_ota(data)

        return {'ok': False, 'error': f'未知 action: {action}'}

    # -- 全量快照 / 批量应用（协议 v2）------------------------------------- #

    @staticmethod
    def _read_json_file(path: Any, default: Any = None) -> Any:
        try:
            with open(path, encoding='utf-8') as file:
                return json.load(file)
        except Exception:
            return default

    @staticmethod
    def _write_json_file(path: Any, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as file:
            json.dump(payload, file, ensure_ascii=False, indent=4)

    @staticmethod
    def _safe_schedule_name(name: Any) -> bool:
        text = str(name or '')
        return (
            bool(text)
            and text.endswith('.json')
            and text != 'backup.json'
            and '/' not in text
            and '\\' not in text
            and len(text) <= 200
        )

    def _handle_snapshot(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """回传本机全部可远程管理的文档（config 节 / 全部课表 / 值日生 / 学科库 / 小组件 / 插件）。"""
        import list_ as list_mod

        # 配置节（排除 Remote，避免自断连）
        sections = set(config_center.config.sections()) | set(config_center.default_data.keys())
        config: Dict[str, Any] = {}
        for section in sorted(sections):
            if section == 'Remote':
                continue
            try:
                config[section] = config_center.read_conf(section)
            except Exception as e:
                logger.warning(f'远程配置：读取配置节 {section} 失败：{e}')

        # 课表文件
        schedules: Dict[str, Any] = {}
        try:
            names = list_mod.get_schedule_config()
        except Exception:
            names = []
        for name in names:
            try:
                content = load_from_json(name)
                if content:
                    schedules[name] = content
            except Exception as e:
                logger.warning(f'远程配置：读取课表 {name} 失败：{e}')

        # 值日生
        try:
            from duty import config_to_dict, get_duty_manager

            duty = config_to_dict(get_duty_manager().config)
        except Exception as e:
            logger.warning(f'远程配置：读取值日生失败：{e}')
            duty = None

        # 学科库
        subjects = self._read_json_file(CW_HOME / 'data' / 'subject.json')

        # 小组件
        try:
            widgets = list_mod.get_widget_config()
        except Exception:
            widgets = []

        # 插件（启用 / 已装）
        plugin_conf = self._read_json_file(CONFIG_HOME / 'plugin.json', {}) or {}
        installed_raw = self._read_json_file(PLUGIN_HOME / 'plugins_from_pp.json', {}) or {}
        installed: List[str] = []
        for item in (installed_raw.get('plugins') or []):
            if isinstance(item, dict):
                installed.append(str(item.get('name') or item.get('id') or ''))
            else:
                installed.append(str(item))
        plugins = {
            'enabled': [str(x) for x in (plugin_conf.get('enabled_plugins') or [])],
            'installed': [x for x in installed if x],
        }

        return {
            'ok': True,
            'data': {
                'config': config,
                'schedules': schedules,
                'active_schedule': config_center.read_conf('General', 'schedule'),
                'duty': duty,
                'subjects': subjects,
                'widgets': widgets,
                'plugins': plugins,
                'client_version': config_center.read_conf('Version', 'version'),
            },
        }

    def _handle_apply(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """批量落盘 bundle 并热重载（覆盖一切配置，含课表本体）。"""
        from data_model import Schedule, normalize_schedule_data

        bundle = request.get('bundle') or {}
        delete_schedules = request.get('delete_schedules') or []
        applied: List[str] = []
        failed: List[str] = []

        # 1) 配置节
        for section, key_values in (bundle.get('config') or {}).items():
            if section == 'Remote' or not isinstance(key_values, dict):
                continue
            for key, value in key_values.items():
                if config_center.write_conf(section, key, value, source='remote'):
                    applied.append(f'config.{section}.{key}')
                else:
                    failed.append(f'config.{section}.{key}')

        # 2) 课表文件（写入并规范化校验）
        for name, content in (bundle.get('schedules') or {}).items():
            if not self._safe_schedule_name(name):
                failed.append(f'schedule:{name}')
                continue
            try:
                normalized = normalize_schedule_data(dict(content))
                Schedule.model_validate(normalized)
                save_data_to_json(normalized, name)
                applied.append(f'schedule:{name}')
            except Exception as e:
                logger.error(f'远程配置：写入课表 {name} 失败：{e}')
                failed.append(f'schedule:{name}')

        # 3) 删除课表文件（跳过当前活动课表）
        active_now = config_center.read_conf('General', 'schedule')
        for name in delete_schedules:
            if not self._safe_schedule_name(name) or name == active_now:
                continue
            try:
                (SCHEDULE_DIR / name).unlink()
                applied.append(f'delete:{name}')
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.error(f'远程配置：删除课表 {name} 失败：{e}')
                failed.append(f'delete:{name}')

        # 4) 切换当前课表
        active = bundle.get('active_schedule')
        if active is not None:
            if self._safe_schedule_name(active) and (SCHEDULE_DIR / active).exists():
                config_center.write_conf('General', 'schedule', active, source='remote')
                applied.append('active_schedule')
            else:
                failed.append('active_schedule')

        # 5) 值日生
        if bundle.get('duty') is not None:
            try:
                from duty import config_from_dict, get_duty_manager

                manager = get_duty_manager()
                manager.config = config_from_dict(bundle['duty'])
                manager.save()
                applied.append('duty')
            except Exception as e:
                logger.error(f'远程配置：写入值日生失败：{e}')
                failed.append('duty')

        # 6) 学科库
        if bundle.get('subjects') is not None:
            try:
                self._write_json_file(CW_HOME / 'data' / 'subject.json', bundle['subjects'])
                applied.append('subjects')
            except Exception as e:
                logger.error(f'远程配置：写入学科库失败：{e}')
                failed.append('subjects')

        # 7) 小组件
        if bundle.get('widgets') is not None:
            try:
                from conf import save_widget_conf_to_json

                save_widget_conf_to_json({'widgets': [str(x) for x in bundle['widgets']]})
                applied.append('widgets')
            except Exception as e:
                logger.error(f'远程配置：写入小组件失败：{e}')
                failed.append('widgets')

        # 8) 插件启用
        plugins = bundle.get('plugins')
        if isinstance(plugins, dict) and 'enabled' in plugins:
            try:
                from conf import save_plugin_config

                save_plugin_config({'enabled_plugins': [str(x) for x in (plugins.get('enabled') or [])]})
                applied.append('plugins')
            except Exception as e:
                logger.error(f'远程配置：写入插件配置失败：{e}')
                failed.append('plugins')

        # 9) 热重载（apply_remote_reload 会重读配置、值日生、课表、小组件）
        self._reload()

        return {
            'ok': not failed,
            'data': {'applied': applied, 'failed': failed},
            'error': ('写入失败: ' + ', '.join(failed)) if failed else None,
        }

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
