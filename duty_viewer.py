"""值日生查看器：查看今日/本周课表与值日生表，可切换上一周/下一周。"""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from loguru import logger
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from duty import WEEKDAY_NAMES, DayDuty, build_text, get_duty_manager, render_red_markup

_active_viewer: Optional["DutyViewer"] = None


def _week_monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def _week_parity(offset: int) -> int:
    try:
        import conf

        current = int(conf.get_week_type())
    except Exception:
        current = 0
    return (current + offset) % 2


def _week_schedule(parity: int) -> Dict[str, List[str]]:
    try:
        from file import schedule_center

        data = schedule_center.schedule_data or {}
    except Exception as e:
        logger.error(f"读取课表失败: {e}")
        return {}
    key = "schedule" if parity == 0 else "schedule_even"
    return data.get(key, {}) or {}


class DutyViewer(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("值日生"))
        self.setMinimumSize(880, 640)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.week_offset = 0
        self.manager = get_duty_manager()
        self._build_ui()
        self.refresh()

    # -- UI --------------------------------------------------------------- #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        self.prev_btn = QPushButton(self.tr("◀ 上一周"))
        self.prev_btn.clicked.connect(lambda: self._shift_week(-1))
        self.next_btn = QPushButton(self.tr("下一周 ▶"))
        self.next_btn.clicked.connect(lambda: self._shift_week(1))
        self.today_btn = QPushButton(self.tr("回到本周"))
        self.today_btn.clicked.connect(self._goto_current)
        self.week_label = QLabel()
        self.week_label.setFont(QFont("Microsoft YaHei UI", 12, QFont.Bold))
        self.week_label.setAlignment(Qt.AlignCenter)
        header.addWidget(self.prev_btn)
        header.addWidget(self.today_btn)
        header.addWidget(self.week_label, 1)
        header.addWidget(self.next_btn)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.today_tab = QWidget()
        self.schedule_tab = QWidget()
        self.duty_tab = QWidget()
        self.tabs.addTab(self.today_tab, self.tr("今日"))
        self.tabs.addTab(self.schedule_tab, self.tr("本周课表"))
        self.tabs.addTab(self.duty_tab, self.tr("本周值日"))
        root.addWidget(self.tabs, 1)

        # 今日
        today_layout = QVBoxLayout(self.today_tab)
        today_layout.setContentsMargins(12, 12, 12, 12)
        self.today_duty = QLabel()
        self.today_duty.setTextFormat(Qt.RichText)
        self.today_duty.setWordWrap(True)
        self.today_duty.setFont(QFont("Microsoft YaHei UI", 11))
        self.today_duty.setAlignment(Qt.AlignTop)
        today_layout.addWidget(self.today_duty)
        self.today_classes = QLabel()
        self.today_classes.setTextFormat(Qt.RichText)
        self.today_classes.setWordWrap(True)
        self.today_classes.setFont(QFont("Microsoft YaHei UI", 11))
        self.today_classes.setAlignment(Qt.AlignTop)
        today_layout.addWidget(self.today_classes)
        today_layout.addStretch(1)

        # 本周课表
        sched_layout = QVBoxLayout(self.schedule_tab)
        sched_layout.setContentsMargins(12, 12, 12, 12)
        self.schedule_table = QTableWidget()
        self.schedule_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        sched_layout.addWidget(self.schedule_table)

        # 本周值日
        duty_layout = QVBoxLayout(self.duty_tab)
        duty_layout.setContentsMargins(12, 12, 12, 12)
        self.duty_table = QTableWidget()
        self.duty_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        duty_layout.addWidget(self.duty_table)

    # -- 行为 ------------------------------------------------------------- #
    def _shift_week(self, delta: int) -> None:
        self.week_offset += delta
        self.refresh()

    def _goto_current(self) -> None:
        self.week_offset = 0
        self.refresh()

    def _target_monday(self) -> dt.date:
        return _week_monday(dt.date.today()) + dt.timedelta(weeks=self.week_offset)

    def refresh(self) -> None:
        monday = self._target_monday()
        friday = monday + dt.timedelta(days=4)
        tag = self.tr("（本周）") if self.week_offset == 0 else ""
        self.week_label.setText(
            f"{monday.strftime('%Y-%m-%d')} ~ {friday.strftime('%m-%d')}{tag}"
        )
        self._refresh_today()
        self._refresh_schedule(monday)
        self._refresh_duty(monday)

    def _refresh_today(self) -> None:
        today = dt.date.today()
        day = self.manager.get_day(today)
        student_text = "、".join(s.label for s in day.students) or "（未安排）"
        monitor_text = day.monitor.label if day.monitor else "（未安排）"
        lines = [
            f"<b>{today.strftime('%Y-%m-%d')} {WEEKDAY_NAMES[today.weekday()]}</b>",
            f"{self.tr('值日班长')}：{monitor_text}",
            f"{self.tr('值日生')}：{student_text}",
        ]
        if day.assignments:
            lines.append("<b>" + self.tr("职务指派") + "</b>")
            for name, people in day.assignments:
                people_text = "、".join(s.label for s in people) or "—"
                lines.append(f"　{name}：{people_text}")
        if not self.manager.config.enabled:
            lines = ["<b>" + self.tr("值日生功能未启用") + "</b>"]
        self.today_duty.setText("<br>".join(lines))

        parity = _week_parity(0)
        courses = [
            name for name in _week_schedule(parity).get(str(today.weekday()), []) if name and name.strip()
        ]
        course_text = "、".join(courses) if courses else self.tr("今日无课程")
        self.today_classes.setText(f"<b>{self.tr('今日课程')}</b>：{course_text}")

    def _refresh_schedule(self, monday: dt.date) -> None:
        parity = _week_parity(self.week_offset)
        schedule = _week_schedule(parity)
        columns = max(
            [len(schedule.get(str(d), []) or []) for d in range(5)] + [1]
        )
        self.schedule_table.clear()
        self.schedule_table.setRowCount(5)
        self.schedule_table.setColumnCount(columns)
        self.schedule_table.setHorizontalHeaderLabels(
            [self.tr("第{index}节").format(index=i + 1) for i in range(columns)]
        )
        self.schedule_table.setVerticalHeaderLabels([WEEKDAY_NAMES[d] for d in range(5)])
        for row in range(5):
            subjects = schedule.get(str(row), []) or []
            for col in range(columns):
                text = subjects[col] if col < len(subjects) else ""
                self.schedule_table.setItem(row, col, QTableWidgetItem(str(text)))
        header = self.schedule_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

    def _refresh_duty(self, monday: dt.date) -> None:
        week = self.manager.get_week(monday)
        headers = [self.tr("星期"), self.tr("值日班长"), self.tr("值日生"), self.tr("职务指派")]
        self.duty_table.clear()
        self.duty_table.setRowCount(5)
        self.duty_table.setColumnCount(len(headers))
        self.duty_table.setHorizontalHeaderLabels(headers)
        for row, day in enumerate(week):
            students = "、".join(s.label for s in day.students) or "—"
            monitor = day.monitor.label if day.monitor else "—"
            duties = "  ".join(
                f"{name}：{'、'.join(s.label for s in people) or '—'}" for name, people in day.assignments
            )
            values = [
                f"{WEEKDAY_NAMES[row]} {day.date.strftime('%m-%d')}",
                monitor,
                students,
                duties,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                self.duty_table.setItem(row, col, item)
        header = self.duty_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)


def open_duty_viewer(parent: Optional[QWidget] = None) -> None:
    global _active_viewer
    try:
        if _active_viewer is not None and _active_viewer.isVisible():
            _active_viewer.raise_()
            _active_viewer.activateWindow()
            return
        _active_viewer = DutyViewer(parent)
        _active_viewer.show()
        _active_viewer.raise_()
        _active_viewer.activateWindow()
    except Exception as e:
        logger.error(f"打开值日生查看器失败: {e}")
