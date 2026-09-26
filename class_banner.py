"""上课模式矮横幅：上课且未全屏时，用一条很矮的一行横幅替代小组件。

显示内容：日期、周几、时间、当前课、下一节课。
- PPT 全屏时由 main.py 的状态机整体隐藏（display_state 驱动）。
- 退出上课/全屏后由状态机恢复小组件并隐藏本横幅。
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontMetrics
from PyQt5.QtWidgets import QLabel, QWidget

BANNER_HEIGHT = 26  # 很矮：单行高度


class ClassBanner(QWidget):
    """贴屏幕顶部的单行横幅（替代上课时的小组件尾巴）。"""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool  # 不进任务栏
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # 点击穿透，触屏不误触
        self.setFixedHeight(BANNER_HEIGHT)

        self.label = QLabel(self)
        font = QFont()
        font.setPointSize(10)
        self.label.setFont(font)
        self.label.setStyleSheet('color: rgba(255, 255, 255, 235); background: transparent;')
        self._theme_color = 'rgba(0, 120, 215, 200)'
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_theme_color(self, color: str) -> None:
        """跟随上课主题色（形如 '#RRGGBB'）。"""
        if color:
            self._theme_color = f'rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, 210)'

    def show_text(self, text: str) -> None:
        """显示横幅（宽度自适应内容，水平居中于主屏幕顶部）。"""
        if not text:
            self.hide_banner()
            return
        self.label.setText(text)
        fm = QFontMetrics(self.label.font())
        width = min(max(fm.horizontalAdvance(text) + 32, 240), self.screen_width() - 16)
        self.label.setGeometry(0, 0, width, BANNER_HEIGHT)
        self.label.setStyleSheet(
            f'color: rgba(255, 255, 255, 235); background: {self._theme_color};'
            f'border-radius: {BANNER_HEIGHT // 2}px; padding: 0 10px;'
        )
        self.setFixedWidth(width)
        screen = self.screen_width()
        self.move((screen - width) // 2, 2)
        if not self.isVisible():
            self.show()

    def hide_banner(self) -> None:
        if self.isVisible():
            self.hide()

    @staticmethod
    def screen_width() -> int:
        from PyQt5.QtWidgets import QGuiApplication

        geo = QGuiApplication.primaryScreen().availableGeometry()
        return geo.width()
