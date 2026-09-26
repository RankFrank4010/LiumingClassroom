"""远程配置（WebSocket）设置页。

让用户无需手改 config.ini 即可配置远程后端：启用开关、服务器地址、令牌、
自动重连与重连间隔，并提供「发送测试通知」「保存并重连」。

版式与其余基于 .ui 的设置页保持一致（见 settings_widgets.py）。
"""

from __future__ import annotations

import threading
from typing import Optional

from loguru import logger
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    SwitchButton,
)

from file import config_center
from settings_widgets import (
    add_subtitle,
    add_title,
    block_card,
    build_scroll_page,
    new_section,
    setting_card,
)


class RemoteSettingsPage(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("remoteInterface")
        self._bound_client = None
        self._build_ui()
        self.load_config()
        self._bind_client()
        self.pair_finished.connect(self._on_pair_finished)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 事件名
        super().showEvent(event)
        self._bind_client()
        self._refresh_status()

    # -- 构建 --------------------------------------------------------------- #
    def _build_ui(self) -> None:
        layout, _content = build_scroll_page(self)
        add_title(layout, self.tr("远程配置"))

        sec = new_section(layout)
        add_subtitle(sec, self.tr("WebSocket 远程后端"))

        self.switch_enabled = SwitchButton()
        self.switch_enabled.setOnText(self.tr("启用"))
        self.switch_enabled.setOffText(self.tr("禁用"))
        sec.addWidget(
            setting_card(
                self.tr("启用远程配置"),
                self.tr(
                    "连接远程服务器后，服务器可随时读取/修改本机配置，并可下发 OTA 更新与特别通知。"
                ),
                self.switch_enabled,
            )
        )

        self.line_url = LineEdit()
        self.line_url.setPlaceholderText(self.tr("例如 example.com:8080 或 192.168.1.10:3000"))
        url_body = block_card(
            sec,
            self.tr("服务器地址"),
            self.tr("填服务端的域名或 IP（带端口），支持 http/https/ws 前缀。"),
        )
        url_body.addWidget(self.line_url)

        self.line_pair = LineEdit()
        self.line_pair.setPlaceholderText(self.tr("网页端「生成配对码」获得的 5 位数字"))
        self.pair_btn = PrimaryPushButton(self.tr("配对"))
        self.pair_btn.clicked.connect(self._do_pair)
        pair_row = QHBoxLayout()
        pair_row.setContentsMargins(0, 0, 0, 0)
        pair_row.addWidget(self.line_pair, 1)
        pair_row.addWidget(self.pair_btn)
        pair_body = block_card(
            sec,
            self.tr("配对码"),
            self.tr("在本校网页端校务页选中教室后点「生成配对码」，10 分钟内有效。配对成功后令牌自动保存，无需手动填写。"),
        )
        pair_body.addLayout(pair_row)

        self.switch_reconnect = SwitchButton()
        self.switch_reconnect.setOnText(self.tr("启用"))
        self.switch_reconnect.setOffText(self.tr("禁用"))
        sec.addWidget(
            setting_card(
                self.tr("断线自动重连"),
                self.tr("连接断开后自动尝试重新连接。"),
                self.switch_reconnect,
            )
        )

        self.spin_interval = SpinBox()
        self.spin_interval.setRange(1, 600)
        sec.addWidget(
            setting_card(self.tr("重连间隔（秒）"), '', self.spin_interval)
        )

        self.status_label = CaptionLabel(self.tr("未连接"))
        self.status_label.setWordWrap(True)
        status_body = block_card(sec, self.tr("连接状态"))
        status_body.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.test_btn = PushButton(self.tr("发送测试通知"))
        self.test_btn.clicked.connect(self._test_notify)
        self.reconnect_btn = PushButton(self.tr("立即重连"))
        self.reconnect_btn.clicked.connect(self._restart_client)
        self.save_btn = PrimaryPushButton(self.tr("保存并重连"))
        self.save_btn.clicked.connect(self.save_config)
        actions.addWidget(self.test_btn)
        actions.addWidget(self.reconnect_btn)
        actions.addStretch(1)
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)

        layout.addStretch(1)

    # -- 配置 --------------------------------------------------------------- #
    def load_config(self) -> None:
        read = config_center.read_conf
        self.switch_enabled.setChecked(str(read('Remote', 'enabled') or '0') == '1')
        self.line_url.setText(str(read('Remote', 'url') or ''))
        self.switch_reconnect.setChecked(str(read('Remote', 'auto_reconnect') or '1') == '1')
        try:
            self.spin_interval.setValue(int(float(read('Remote', 'reconnect_interval') or 5)))
        except (TypeError, ValueError):
            self.spin_interval.setValue(5)
        self._refresh_status()

    def save_config(self) -> None:
        write = config_center.write_conf
        write('Remote', 'enabled', '1' if self.switch_enabled.isChecked() else '0')
        from remote_config import normalize_server_address

        ws_url, _ = normalize_server_address(self.line_url.text())
        write('Remote', 'url', ws_url or self.line_url.text().strip())
        write('Remote', 'auto_reconnect', '1' if self.switch_reconnect.isChecked() else '0')
        write('Remote', 'reconnect_interval', str(self.spin_interval.value()))
        self._restart_client()
        self._refresh_status()

    # -- 配对 ---------------------------------------------------------------- #
    pair_finished = pyqtSignal(bool, str)  # (成功?, 信息)

    def _do_pair(self) -> None:
        from remote_config import normalize_server_address

        _, pair_url = normalize_server_address(self.line_url.text())
        code = self.line_pair.text().strip()
        if pair_url is None:
            InfoBar.warning(
                title=self.tr("无法配对"),
                content=self.tr("请先填写服务器地址。"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )
            return
        if not code.isdigit() or len(code) != 5:
            InfoBar.warning(
                title=self.tr("无法配对"),
                content=self.tr("配对码应为网页端生成的 5 位数字。"),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )
            return
        # 保存地址并启用，便于配对成功后直接连接
        config_center.write_conf('Remote', 'enabled', '1')
        config_center.write_conf('Remote', 'url', normalize_server_address(self.line_url.text())[0])
        self.switch_enabled.setChecked(True)
        self.pair_btn.setEnabled(False)
        self.pair_btn.setText(self.tr("配对中…"))
        threading.Thread(target=self._pair_worker, args=(pair_url, code), daemon=True).start()

    def _pair_worker(self, pair_url: str, code: str) -> None:
        try:
            import requests

            resp = requests.post(pair_url, json={'code': code}, timeout=8)
            data = resp.json() if resp.headers.get('content-type', '').startswith('application/json') else {}
            if resp.status_code == 200 and data.get('token'):
                config_center.write_conf('Remote', 'token', str(data['token']))
                name = str((data.get('classroom') or {}).get('name') or '')
                self.pair_finished.emit(True, name or pair_url)
            else:
                error_map = {
                    400: self.tr("配对码无效或已过期"),
                    429: self.tr("尝试过于频繁，请稍后再试"),
                }
                self.pair_finished.emit(False, error_map.get(resp.status_code, self.tr("配对失败，请检查地址与配对码")))
        except Exception as e:  # noqa: BLE001
            self.pair_finished.emit(False, self.tr("配对失败：{err}").format(err=e))

    def _on_pair_finished(self, ok: bool, message: str) -> None:
        self.pair_btn.setEnabled(True)
        self.pair_btn.setText(self.tr("配对"))
        self.line_pair.clear()
        if ok:
            InfoBar.success(
                title=self.tr("配对成功"),
                content=self.tr("已与「{name}」完成配对，正在连接…").format(name=message),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=6000,
                parent=self,
            )
            self._restart_client()
        else:
            InfoBar.error(
                title=self.tr("配对失败"),
                content=message,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=8000,
                parent=self,
            )

    # -- 行为 --------------------------------------------------------------- #
    def _restart_client(self) -> None:
        try:
            import main

            main._stop_remote_client()
            main._start_remote_client()
        except Exception as e:
            logger.error(f"重启远程配置客户端失败: {e}")
        self._bound_client = None  # 客户端已重建，需重新绑定
        self._bind_client()
        self._refresh_status()

    # -- 连接状态 ----------------------------------------------------------- #
    def _bind_client(self) -> None:
        """绑定远程客户端的状态信号（客户端重建后需重新绑定）。"""
        try:
            import main
        except Exception:
            return
        client = getattr(main, 'remote_client', None)
        if client is None or client is self._bound_client:
            return
        try:
            client.state_changed.connect(self._on_state)
            client.connection_error.connect(self._on_error)
        except Exception:
            return
        self._bound_client = client
        self._on_state(getattr(client, 'state', 'stopped'), getattr(client, 'last_error', ''))

    def _on_state(self, state: str, detail: str) -> None:
        try:
            from remote_config import RemoteConfigClient

            base = RemoteConfigClient.STATUS_TEXT.get(state, state)
        except Exception:
            base = state
        if detail and state in ('error', 'auth_failed', 'disconnected'):
            text = f'{base}：{detail}'
        elif detail and state == 'connecting':
            text = f'{base} {detail}'
        else:
            text = base
        if state == 'authed':
            color = '#16A34A'
        elif state in ('error', 'auth_failed'):
            color = '#DC2626'
        elif state in ('connecting', 'connected'):
            color = '#D97706'
        else:
            color = '#6B7280'
        self.status_label.setStyleSheet(f'color:{color};')
        self.status_label.setText(text)

    def _on_error(self, message: str) -> None:
        InfoBar.error(
            title=self.tr("远程连接出错"),
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=8000,
            parent=self,
        )

    def _refresh_status(self) -> None:
        try:
            import main

            client = getattr(main, 'remote_client', None)
            if client is None:
                self.status_label.setStyleSheet('color:#6B7280;')
                self.status_label.setText(self.tr("未启用或未启动（点「保存并重连」启动）"))
            else:
                self._on_state(getattr(client, 'state', 'stopped'), getattr(client, 'last_error', ''))
        except Exception:
            self.status_label.setText(self.tr("未连接"))

    def _test_notify(self) -> None:
        try:
            import main

            main._on_remote_notification(
                {
                    'state': 1,
                    'special': True,
                    'title': self.tr('特别通知'),
                    'subtitle': self.tr('来自远程后端的测试'),
                    'content': self.tr('如果你看到这条通知，说明远程特别通知功能正常。'),
                    'duration': 6000,
                }
            )
        except Exception as e:
            logger.error(f"测试通知失败: {e}")
