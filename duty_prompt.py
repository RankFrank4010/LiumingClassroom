"""值日生大型提示组件。

最后一节课结束时弹出，用于醒目提示值日生就位。支持三种样式：
- overlay：全屏半透明遮罩 + 居中大字卡片
- banner：屏幕顶部通栏大字横幅
- widget：屏幕中央的大号卡片（不遮罩）
"""

from __future__ import annotations

import html
import re
from typing import Iterable, Optional

from loguru import logger
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import isDarkTheme

from duty import DayDuty, DutyManager, PROMPT_BANNER, PROMPT_WIDGET, build_text
from file import config_center

_RED_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
_RED_COLOR = "#E53935"

_active_prompt: Optional["DutyPrompt"] = None
_AUTO_CLOSE_MS = 15000


def _rich(text: str, labels: Iterable[str] = ()) -> str:
    """把 ``**红字**`` 渲染为红色，并把出现的姓名加粗。"""
    safe = html.escape(text or "")
    safe = _RED_RE.sub(
        lambda m: f'<span style="color:{_RED_COLOR};font-weight:800;">{m.group(1)}</span>', safe
    )
    for lab in sorted({x for x in labels if x}, key=len, reverse=True):
        esc = html.escape(lab)
        safe = safe.replace(esc, f"<b>{esc}</b>")
    return safe.replace("\n", "<br>")


class DutyPrompt(QWidget):
    def __init__(self, day: DayDuty, manager: DutyManager) -> None:
        super().__init__()
        self.style_kind = manager.config.prompt_style
        self._closing = False
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint
            | Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)

        screen = QApplication.primaryScreen().geometry()
        dark = isDarkTheme()
        card_bg = "rgba(30, 30, 34, 246)" if dark else "rgba(252, 252, 253, 250)"
        title_color = "#FFFFFF" if dark else "#17171B"
        body_color = "#E7E7EF" if dark else "#3A3A42"
        hint_color = "rgba(255,255,255,90)" if dark else "rgba(0,0,0,80)"
        accent = str(config_center.read_conf('Color', 'attend_class') or "4C8DFF").lstrip('#')

        labels = [s.label for s in day.students]
        if day.monitor is not None:
            labels.append(day.monitor.label)
        for _name, people in day.assignments:
            labels.extend(s.label for s in people)

        title = build_text(manager.config.big_title, day) or self.tr("值日生就位！")
        body = build_text(manager.config.big_text, day)

        card = QFrame(self)
        card.setObjectName("duty_card")
        card.setStyleSheet(
            f"#duty_card {{ background-color: {card_bg};"
            f" border-radius: 24px; border: 3px solid #{accent}; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(52, 44, 52, 44)
        layout.setSpacing(22)

        title_label = QLabel(card)
        title_label.setTextFormat(Qt.RichText)
        title_label.setWordWrap(True)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(f"color: {title_color}; background: transparent;")
        title_label.setFont(QFont("Microsoft YaHei UI", self._title_size(), QFont.Bold))
        title_label.setText(_rich(title, labels))
        layout.addWidget(title_label)

        if body.strip():
            body_label = QLabel(card)
            body_label.setTextFormat(Qt.RichText)
            body_label.setWordWrap(True)
            body_label.setAlignment(Qt.AlignCenter)
            body_label.setStyleSheet(f"color: {body_color}; background: transparent;")
            body_label.setFont(QFont("Microsoft YaHei UI", self._body_size(), QFont.Medium))
            body_label.setText(_rich(body, labels))
            layout.addWidget(body_label)

        hint = QLabel(card)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color: {hint_color}; background: transparent;")
        hint.setFont(QFont("Microsoft YaHei UI", 11))
        hint.setText(self.tr("点击关闭"))
        layout.addWidget(hint)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignCenter)
        outer.addWidget(card)

        self._apply_geometry(screen, card)
        self.show()
        self.raise_()
        QTimer.singleShot(_AUTO_CLOSE_MS, self.close_prompt)

    def _title_size(self) -> int:
        return {PROMPT_BANNER: 54, PROMPT_WIDGET: 42}.get(self.style_kind, 48)

    def _body_size(self) -> int:
        return {PROMPT_BANNER: 30, PROMPT_WIDGET: 24}.get(self.style_kind, 26)

    def _apply_geometry(self, screen, card: QFrame) -> None:
        if self.style_kind == PROMPT_BANNER:
            height = min(380, max(240, int(screen.height() * 0.32)))
            self.setGeometry(screen.x(), screen.y(), screen.width(), height)
            card.setFixedWidth(max(640, screen.width() - 120))
        elif self.style_kind == PROMPT_WIDGET:
            width, height = min(780, screen.width() - 80), min(460, screen.height() - 80)
            self.setGeometry(
                screen.x() + (screen.width() - width) // 2,
                screen.y() + (screen.height() - height) // 2,
                width,
                height,
            )
            card.setFixedWidth(width - 20)
        else:  # overlay
            self.setGeometry(screen)
            card.setFixedWidth(min(1200, screen.width() - 200))

    def paintEvent(self, event) -> None:  # noqa: N802
        if self.style_kind == "overlay":
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 165))
            painter.end()

    def close_prompt(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.close()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.close_prompt()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        self.close_prompt()


def show_duty_prompt(day: DayDuty, manager: Optional[DutyManager] = None) -> None:
    global _active_prompt
    try:  # PPT 放映全屏期间不弹出任何事件提示
        import display_state

        if display_state.is_fullscreen():
            return
    except (ImportError, AttributeError):
        pass
    try:
        from duty import get_duty_manager

        manager = manager or get_duty_manager()
        if _active_prompt is not None:
            try:
                _active_prompt.close()
            except Exception:
                pass
        _active_prompt = DutyPrompt(day, manager)
    except Exception as e:
        logger.error(f"显示值日生提示失败: {e}")
