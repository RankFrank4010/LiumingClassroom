"""远程配置（WebSocket）设置页。

让用户无需手改 config.ini 即可配置远程后端：启用开关、服务器地址、令牌、
自动重连与重连间隔，并提供「发送测试通知」「保存并重连」。
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from PyQt5.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SmoothScrollArea,
    SpinBox,
    StrongBodyLabel,
    SwitchButton,
    TitleLabel,
)

from file import config_center


class RemoteSettingsPage(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("remoteInterface")
        self._build_ui()
        self.load_config()

    # -- 构建 --------------------------------------------------------------- #
    def _card(self, layout: QVBoxLayout, title: str, desc: str = "") -> QVBoxLayout:
        card = CardWidget()
        body = QVBoxLayout(card)
        body.setContentsMargins(18, 14, 18, 16)
        body.setSpacing(8)
        head = QVBoxLayout()
        head.setSpacing(0)
        head.addWidget(StrongBodyLabel(title, card))
        if desc:
            caption = CaptionLabel(desc, card)
            caption.setWordWrap(True)
            head.addWidget(caption)
        body.addLayout(head)
        layout.addWidget(card)
        return body

    def _row(self, label: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(StrongBodyLabel(label))
        row.addStretch(1)
        row.addWidget(widget)
        return row

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = SmoothScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 18, 24, 40)
        layout.setSpacing(14)
        layout.addWidget(TitleLabel(self.tr("远程配置"), content))

        body = self._card(
            layout,
            self.tr("WebSocket 远程后端"),
            self.tr(
                "连接远程服务器后，服务器可随时读取/修改本机配置，并可下发 OTA 更新与特别通知。"
            ),
        )

        self.switch_enabled = SwitchButton()
        body.addLayout(self._row(self.tr("启用远程配置"), self.switch_enabled))

        url_box = QVBoxLayout()
        url_box.setSpacing(4)
        url_box.addWidget(StrongBodyLabel(self.tr("服务器地址")))
        self.line_url = LineEdit()
        self.line_url.setPlaceholderText("ws://127.0.0.1:8765/ws")
        url_box.addWidget(self.line_url)
        body.addLayout(url_box)

        token_box = QVBoxLayout()
        token_box.setSpacing(4)
        token_box.addWidget(StrongBodyLabel(self.tr("令牌 (token)")))
        self.line_token = LineEdit()
        self.line_token.setEchoMode(QLineEdit.Password)
        self.line_token.setPlaceholderText(self.tr("可选，用于鉴权"))
        token_box.addWidget(self.line_token)
        body.addLayout(token_box)

        self.switch_reconnect = SwitchButton()
        body.addLayout(self._row(self.tr("断线自动重连"), self.switch_reconnect))

        self.spin_interval = SpinBox()
        self.spin_interval.setRange(1, 600)
        body.addLayout(self._row(self.tr("重连间隔（秒）"), self.spin_interval))

        self.status_label = CaptionLabel(self.tr("未连接"))
        self.status_label.setWordWrap(True)
        body.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.test_btn = PushButton(self.tr("发送测试通知"))
        self.test_btn.clicked.connect(self._test_notify)
        self.save_btn = PrimaryPushButton(self.tr("保存并重连"))
        self.save_btn.clicked.connect(self.save_config)
        actions.addWidget(self.test_btn)
        actions.addStretch(1)
        actions.addWidget(self.save_btn)
        body.addLayout(actions)

        layout.addStretch(1)

    # -- 配置 --------------------------------------------------------------- #
    def load_config(self) -> None:
        read = config_center.read_conf
        self.switch_enabled.setChecked(str(read('Remote', 'enabled') or '0') == '1')
        self.line_url.setText(str(read('Remote', 'url') or ''))
        self.line_token.setText(str(read('Remote', 'token') or ''))
        self.switch_reconnect.setChecked(str(read('Remote', 'auto_reconnect') or '1') == '1')
        try:
            self.spin_interval.setValue(int(float(read('Remote', 'reconnect_interval') or 5)))
        except (TypeError, ValueError):
            self.spin_interval.setValue(5)
        self._refresh_status()

    def save_config(self) -> None:
        write = config_center.write_conf
        write('Remote', 'enabled', '1' if self.switch_enabled.isChecked() else '0')
        write('Remote', 'url', self.line_url.text().strip())
        write('Remote', 'token', self.line_token.text().strip())
        write('Remote', 'auto_reconnect', '1' if self.switch_reconnect.isChecked() else '0')
        write('Remote', 'reconnect_interval', str(self.spin_interval.value()))
        self._restart_client()
        self._refresh_status()

    # -- 行为 --------------------------------------------------------------- #
    def _restart_client(self) -> None:
        try:
            import main

            main._stop_remote_client()
            main._start_remote_client()
        except Exception as e:
            logger.error(f"重启远程配置客户端失败: {e}")

    def _refresh_status(self) -> None:
        try:
            import main

            if getattr(main, 'remote_client', None) is None:
                self.status_label.setText(self.tr("未连接（未启用或未连接）"))
            else:
                self.status_label.setText(self.tr("已启用，客户端已启动"))
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
