"""值日改班：点击划掉/恢复值日生与班长，补值休学用户，应用或回滚当日改班。"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional, Set

from loguru import logger
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    isDarkTheme,
)

from duty import WEEKDAY_NAMES, get_duty_manager

_active_adjust: Optional["DutyAdjustDialog"] = None


def _chip_style() -> str:
    """按当前主题返回芯片样式（Windows 7 强制浅色主题时保持可读）。"""
    if isDarkTheme():
        return (
            "QPushButton {"
            "background-color: rgba(255, 255, 255, 22);"
            "border: 1px solid rgba(255, 255, 255, 40);"
            "border-radius: 8px;"
            "padding: 10px 18px;"
            "color: rgba(255, 255, 255, 230);"
            "} QPushButton:hover { background-color: rgba(255, 255, 255, 45); }"
        )
    return (
        "QPushButton {"
        "background-color: rgba(0, 0, 0, 12);"
        "border: 1px solid rgba(0, 0, 0, 60);"
        "border-radius: 8px;"
        "padding: 10px 18px;"
        "color: rgba(0, 0, 0, 210);"
        "} QPushButton:hover { background-color: rgba(0, 0, 0, 25); }"
    )


def _struck_style() -> str:
    if isDarkTheme():
        return "QPushButton { color: rgba(255, 255, 255, 100); border-color: rgba(255, 255, 255, 20); }"
    return "QPushButton { color: rgba(0, 0, 0, 110); border-color: rgba(0, 0, 0, 25); }"


class DutyAdjustDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("值日改班"))
        self.setMinimumSize(620, 560)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.manager = get_duty_manager()
        self.today = dt.date.today()
        self.base_day = self.manager.get_base_day(self.today)
        adj = self.manager.get_adjustment(self.today.isoformat())
        self.struck: Set[str] = set(adj.struck) if adj else set()
        self.added: List[str] = list(adj.added) if adj else []
        self._build_ui()
        self._refresh()

    # -- UI --------------------------------------------------------------- #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(12)

        self.title_label = StrongBodyLabel()
        self.title_label.setFont(QFont("Microsoft YaHei UI", 14, QFont.Bold))
        root.addWidget(self.title_label)

        self.hint_label = CaptionLabel(
            self.tr("点击姓名可划掉（取消今日值日），再次点击恢复。应用后今日值日自动顺延补齐。")
        )
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)

        self.monitor_title = StrongBodyLabel(self.tr("值日班长"))
        root.addWidget(self.monitor_title)
        self.monitor_grid = QGridLayout()
        self.monitor_grid.setSpacing(8)
        root.addLayout(self.monitor_grid)

        self.students_title = StrongBodyLabel(self.tr("值日生"))
        root.addWidget(self.students_title)
        self.students_grid = QGridLayout()
        self.students_grid.setSpacing(8)
        root.addLayout(self.students_grid)

        self.added_title = StrongBodyLabel(self.tr("补值名单"))
        self.added_title.setVisible(False)
        root.addWidget(self.added_title)
        self.added_grid = QGridLayout()
        self.added_grid.setSpacing(8)
        root.addLayout(self.added_grid)

        fill_row = QHBoxLayout()
        self.line_fill = LineEdit()
        self.line_fill.setPlaceholderText(self.tr("补栏：输入学号，为休学用户补今日值日"))
        self.line_fill.setClearButtonEnabled(True)
        self.btn_fill = PushButton(self.tr("补值"))
        self.btn_fill.clicked.connect(self._fill_duty)
        fill_row.addWidget(self.line_fill, 1)
        fill_row.addWidget(self.btn_fill)
        root.addLayout(fill_row)

        root.addStretch(1)

        btns = QHBoxLayout()
        self.btn_rollback = PushButton(self.tr("回滚今日修改"))
        self.btn_rollback.clicked.connect(self._rollback)
        btns.addWidget(self.btn_rollback)
        btns.addStretch(1)
        self.btn_close = PushButton(self.tr("关闭"))
        self.btn_close.clicked.connect(self.close)
        self.btn_apply = PrimaryPushButton(self.tr("应用"))
        self.btn_apply.clicked.connect(self._apply)
        btns.addWidget(self.btn_close)
        btns.addWidget(self.btn_apply)
        root.addLayout(btns)

    # -- 状态 -------------------------------------------------------------- #
    def _is_struck(self, key: str) -> bool:
        return key in self.struck

    def _make_chip(self, text: str, key: str, monitor: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        font = QFont("Microsoft YaHei UI", 11)
        if self._is_struck(key):
            font.setStrikeOut(True)
            btn.setStyleSheet(_chip_style() + _struck_style())
            btn.setToolTip(self.tr("点击恢复该成员今日值日"))
        else:
            btn.setStyleSheet(_chip_style())
            btn.setToolTip(self.tr("点击划掉该成员（取消今日值日）"))
        btn.setFont(font)
        btn.clicked.connect(lambda: self._toggle(key, monitor))
        return btn

    def _toggle(self, key: str, monitor: bool = False) -> None:
        if key in self.struck:
            self.struck.discard(key)
        else:
            self.struck.add(key)
        self._refresh()

    def _refresh(self) -> None:
        self.title_label.setText(
            self.tr("{date} {weekday} · 值日改班").format(
                date=self.today.strftime("%Y-%m-%d"),
                weekday=WEEKDAY_NAMES[self.today.weekday()],
            )
        )
        # 班长
        while self.monitor_grid.count():
            item = self.monitor_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        monitor = self.base_day.monitor
        if monitor is not None:
            self.monitor_grid.addWidget(self._make_chip(monitor.label, monitor.key, monitor=True), 0, 0)
        else:
            self.monitor_grid.addWidget(QLabel(self.tr("（未安排值日班长）")), 0, 0)
        # 值日生
        while self.students_grid.count():
            item = self.students_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self.base_day.students:
            for idx, student in enumerate(self.base_day.students):
                self.students_grid.addWidget(self._make_chip(student.label, student.key), idx // 4, idx % 4)
        else:
            self.students_grid.addWidget(QLabel(self.tr("（今日未安排值日生）")), 0, 0)
        # 补值名单
        while self.added_grid.count():
            item = self.added_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.added_title.setVisible(bool(self.added))
        for idx, key in enumerate(self.added):
            student = self.manager.student_by_key(key)
            text = f"{student.label}（补）" if student else f"{key}（补）"
            chip = QPushButton(text)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(_chip_style())
            chip.setToolTip(self.tr("点击移除补值"))
            chip.clicked.connect(lambda _, k=key: self._remove_added(k))
            self.added_grid.addWidget(chip, idx // 4, idx % 4)

    # -- 行为 -------------------------------------------------------------- #
    def _toast(self, text: str, error: bool = False) -> None:
        try:
            factory = InfoBar.error if error else InfoBar.success
            factory(
                title="",
                content=text,
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self,
            )
        except Exception as e:
            logger.error(f"值日改班提示失败: {e}")

    def _fill_duty(self) -> None:
        key = self.line_fill.text().strip()
        if not key:
            self._toast(self.tr("请先输入学号"), error=True)
            return
        student = self.manager.student_by_key(key)
        if student is None:
            self._toast(self.tr("未找到学号 {key} 对应的学生").format(key=key), error=True)
            return
        existing = {s.key for s in self.base_day.students} | set(self.added)
        if student.key in existing:
            self._toast(self.tr("{name} 已在今日值日或补值名单中").format(name=student.name), error=True)
            return
        self.added.append(student.key)
        self.line_fill.clear()
        self._refresh()
        if self.manager.is_suspended(student.key):
            self._toast(
                self.tr("已为休学用户 {name} 补今日值日（仅当天，休学身份不变）").format(name=student.name)
            )
        else:
            self._toast(self.tr("已加入 {name} 今日补值").format(name=student.name))

    def _remove_added(self, key: str) -> None:
        if key in self.added:
            self.added.remove(key)
        self._refresh()

    def _apply(self) -> None:
        try:
            base_keys = [s.key for s in self.base_day.students]
            if self.base_day.monitor is not None:
                base_keys.append(self.base_day.monitor.key)
            struck = [k for k in base_keys if k in self.struck]
            self.manager.apply_adjustment(self.today.isoformat(), struck, list(self.added))
            self._toast(self.tr("已应用今日值日改班，后续提醒将按新名单执行"))
            self._refresh()
        except Exception as e:
            logger.error(f"应用值日改班失败: {e}")
            self._toast(self.tr("应用失败，详情请查看日志"), error=True)

    def _rollback(self) -> None:
        try:
            self.manager.remove_adjustment(self.today.isoformat())
            self.struck = set()
            self.added = []
            self._refresh()
            self._toast(self.tr("已回滚：今日值日恢复为未修改前的安排"))
        except Exception as e:
            logger.error(f"回滚值日改班失败: {e}")
            self._toast(self.tr("回滚失败，详情请查看日志"), error=True)


def open_duty_adjust(parent: Optional[QWidget] = None) -> None:
    global _active_adjust
    try:
        if _active_adjust is not None and _active_adjust.isVisible():
            _active_adjust.raise_()
            _active_adjust.activateWindow()
            return
        _active_adjust = DutyAdjustDialog(parent)
        _active_adjust.show()
        _active_adjust.raise_()
        _active_adjust.activateWindow()
    except Exception as e:
        logger.error(f"打开值日改班失败: {e}")
