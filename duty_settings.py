"""值日生设置页：名单管理、排班模式、值日班长、职务指派与自定义文案。"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from loguru import logger
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScroller,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    InfoBar,
    InfoBarIcon,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    SwitchButton,
    TableWidget,
)

from duty import (
    ASSIGN_FIXED,
    ASSIGN_ROTATE,
    MODE_FIXED,
    MODE_ID_ROTATION,
    MONITOR_DAILY,
    MONITOR_WEEKLY,
    PERIOD_DAY,
    PERIOD_WEEK,
    DELIVERY_BOTH,
    DELIVERY_POPUP,
    DELIVERY_WIDGET,
    PROMPT_BANNER,
    PROMPT_OVERLAY,
    PROMPT_WIDGET,
    DayOverride,
    Role,
    Student,
    get_duty_manager,
)
from settings_widgets import (
    add_subtitle,
    add_title,
    block_card,
    build_scroll_page,
    new_section,
    panel,
    setting_card,
)

_PROMPT_STYLES = [PROMPT_OVERLAY, PROMPT_BANNER, PROMPT_WIDGET]
_DELIVERY_MODES = [DELIVERY_POPUP, DELIVERY_WIDGET, DELIVERY_BOTH]


class DutySettingsPage(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("dutyInterface")
        self.manager = get_duty_manager()
        self._build_ui()
        self.load_config()

    # -- 构建界面 --------------------------------------------------------- #
    def _build_ui(self) -> None:
        layout, _content = build_scroll_page(self)
        add_title(layout, self.tr("值日生"))

        self._build_general(layout)
        self._build_roster(layout)
        self._build_schedule(layout)
        self._build_monitor(layout)
        self._build_assign(layout)
        self._build_change_rules(layout)
        self._build_text(layout)
        self._build_overrides(layout)

        actions = QHBoxLayout()
        preview_btn = PushButton(self.tr("预览提示"))
        preview_btn.clicked.connect(self._preview_prompt)
        viewer_btn = PushButton(self.tr("打开查看器"))
        viewer_btn.clicked.connect(self._open_viewer)
        save_btn = PrimaryPushButton(self.tr("保存"))
        save_btn.clicked.connect(self.save_config)
        actions.addWidget(preview_btn)
        actions.addWidget(viewer_btn)
        actions.addStretch(1)
        actions.addWidget(save_btn)
        layout.addLayout(actions)
        layout.addStretch(1)

    def _build_general(self, layout: QVBoxLayout) -> None:
        sec = new_section(layout)
        add_subtitle(sec, self.tr("总开关与提示样式"))

        self.switch_enabled = SwitchButton()
        self.switch_enabled.setOnText(self.tr("启用"))
        self.switch_enabled.setOffText(self.tr("禁用"))
        sec.addWidget(
            setting_card(
                self.tr("启用值日生功能"),
                self.tr("启用后将在最后一节课结束时提示今日值日生。"),
                self.switch_enabled,
            )
        )

        self.combo_prompt = ComboBox()
        self.combo_prompt.addItems([self.tr("全屏遮罩"), self.tr("顶部横幅"), self.tr("中央大卡片")])
        sec.addWidget(
            setting_card(
                self.tr("大型提示样式"),
                self.tr("最后一节课结束时大提示的呈现形式。"),
                self.combo_prompt,
            )
        )

        self.combo_delivery = ComboBox()
        self.combo_delivery.addItems([self.tr("弹窗提示"), self.tr("常驻小组件"), self.tr("两者都显示")])
        sec.addWidget(
            setting_card(
                self.tr("提示送达方式"),
                self.tr("弹窗、常驻小组件，或两者同时显示。"),
                self.combo_delivery,
            )
        )

        self.switch_weekend = SwitchButton()
        self.switch_weekend.setOnText(self.tr("启用"))
        self.switch_weekend.setOffText(self.tr("禁用"))
        sec.addWidget(
            setting_card(
                self.tr("包含周六、周日排班"),
                self.tr("开启后周六、周日也会参与排班。"),
                self.switch_weekend,
            )
        )

    def _build_roster(self, layout: QVBoxLayout) -> None:
        body = block_card(
            layout,
            self.tr("学生名单"),
            self.tr("录入姓名与学号（学号可留空）。排班支持“按学号”或“按录入顺序”。"),
        )
        self.table_students = TableWidget()
        self.table_students.setColumnCount(2)
        self.table_students.setHorizontalHeaderLabels([self.tr("姓名"), self.tr("学号")])
        self.table_students.horizontalHeader().setStretchLastSection(True)
        self.table_students.setMinimumHeight(240)
        body.addWidget(self.table_students)

        btns = QHBoxLayout()
        add_btn = PushButton(self.tr("添加一行"))
        add_btn.clicked.connect(self._add_student_row)
        remove_btn = PushButton(self.tr("删除选中"))
        remove_btn.clicked.connect(self._remove_student_row)
        clear_btn = PushButton(self.tr("清空"))
        clear_btn.clicked.connect(self._clear_students)
        import_btn = PushButton(self.tr("导入"))
        import_btn.clicked.connect(self._import_students)
        export_btn = PushButton(self.tr("导出"))
        export_btn.clicked.connect(self._export_students)
        for b in (add_btn, remove_btn, clear_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(import_btn)
        btns.addWidget(export_btn)
        body.addLayout(btns)

    def _build_schedule(self, layout: QVBoxLayout) -> None:
        sec = new_section(layout)
        add_subtitle(sec, self.tr("排班模式"))

        self.combo_mode = ComboBox()
        self.combo_mode.addItems([self.tr("学号排班"), self.tr("固定排班")])
        self.combo_mode.currentIndexChanged.connect(self._update_mode_panels)
        sec.addWidget(
            setting_card(
                self.tr("模式"),
                self.tr("学号排班：每天按顺序抽取若干学号；固定排班：周一至周五固定人员。"),
                self.combo_mode,
            )
        )

        self.id_panel, ip = panel(sec)

        self.spin_count = SpinBox()
        self.spin_count.setRange(0, 99)
        ip.addWidget(setting_card(self.tr("每日人数"), '', self.spin_count))

        self.combo_order = ComboBox()
        self.combo_order.addItems([self.tr("按学号"), self.tr("按录入顺序")])
        ip.addWidget(setting_card(self.tr("排序方式"), '', self.combo_order))

        self.switch_weekly_reset = SwitchButton()
        self.switch_weekly_reset.setOnText(self.tr("启用"))
        self.switch_weekly_reset.setOffText(self.tr("禁用"))
        ip.addWidget(
            setting_card(
                self.tr("每周重置（周一从起始开始）"),
                self.tr("开启后每周一都从起始学号/姓名重新开始。"),
                self.switch_weekly_reset,
            )
        )

        self.line_start_key = LineEdit()
        self.line_start_key.setPlaceholderText(self.tr("留空表示从第一个开始"))
        self.line_start_key.setFixedWidth(220)
        ip.addWidget(setting_card(self.tr("起始学号/姓名"), '', self.line_start_key))

        self.switch_per_weekday = SwitchButton()
        self.switch_per_weekday.setOnText(self.tr("启用"))
        self.switch_per_weekday.setOffText(self.tr("禁用"))
        ip.addWidget(
            setting_card(
                self.tr("每日单独人数"),
                self.tr("开启后可分别为周一至周五设定人数。"),
                self.switch_per_weekday,
            )
        )

        weekday_row = QWidget()
        pw_row = QHBoxLayout(weekday_row)
        pw_row.setContentsMargins(0, 0, 0, 0)
        pw_row.setSpacing(8)
        self.per_weekday_spins: List[SpinBox] = []
        for name in ["周一", "周二", "周三", "周四", "周五"]:
            pw_row.addWidget(CaptionLabel(self.tr(name)))
            spin = SpinBox()
            spin.setRange(0, 99)
            spin.setFixedWidth(70)
            self.per_weekday_spins.append(spin)
            pw_row.addWidget(spin)
        pw_row.addStretch(1)
        spins_body = block_card(ip)
        spins_body.addWidget(weekday_row)

        self.fixed_panel, fp = panel(sec)
        fixed_body = block_card(
            fp,
            self.tr("固定人员"),
            self.tr("输入学号或姓名（逗号分隔），也可点击“选择”从名单中挑选。"),
        )
        self.fixed_edits: List[LineEdit] = []
        for name in ["周一", "周二", "周三", "周四", "周五"]:
            frow = QHBoxLayout()
            label = StrongBodyLabel(self.tr(name))
            label.setMinimumWidth(48)
            frow.addWidget(label)
            container, edit = self._make_key_row()
            self.fixed_edits.append(edit)
            frow.addWidget(container, 1)
            fixed_body.addLayout(frow)

        self.id_panel.setVisible(True)
        self.fixed_panel.setVisible(False)

    def _build_monitor(self, layout: QVBoxLayout) -> None:
        sec = new_section(layout)
        add_subtitle(sec, self.tr("值日班长"))

        self.switch_monitor = SwitchButton()
        self.switch_monitor.setOnText(self.tr("启用"))
        self.switch_monitor.setOffText(self.tr("禁用"))
        sec.addWidget(
            setting_card(
                self.tr("启用值日班长"),
                self.tr("每天或每周指定一位值日班长。"),
                self.switch_monitor,
            )
        )

        self.combo_monitor_mode = ComboBox()
        self.combo_monitor_mode.addItems([self.tr("按周轮换"), self.tr("按天指定")])
        self.combo_monitor_mode.currentIndexChanged.connect(self._update_monitor_panels)
        sec.addWidget(
            setting_card(
                self.tr("模式"),
                self.tr("按周轮换：每周一位班长；按天指定：周一至周五分别指定。"),
                self.combo_monitor_mode,
            )
        )

        self.monitor_weekly_panel, mw = panel(sec)
        container, self.line_monitor_weekly = self._make_key_row()
        mw.addWidget(
            setting_card(self.tr("班长轮换列表"), '', container, expand_control=True)
        )

        self.monitor_daily_panel, md = panel(sec)
        self.daily_monitor_edits: List[LineEdit] = []
        for name in ["周一", "周二", "周三", "周四", "周五"]:
            container, edit = self._make_key_row()
            self.daily_monitor_edits.append(edit)
            md.addWidget(setting_card(self.tr(name), '', container, expand_control=True))
        self._update_monitor_panels()

    def _build_assign(self, layout: QVBoxLayout) -> None:
        sec = new_section(layout)
        add_subtitle(sec, self.tr("职务指派（可选）"))

        self.switch_assign = SwitchButton()
        self.switch_assign.setOnText(self.tr("启用"))
        self.switch_assign.setOffText(self.tr("禁用"))
        sec.addWidget(
            setting_card(
                self.tr("启用职务指派"),
                self.tr("为拖地、扫地等职务指定人员，或按周期自动轮换。"),
                self.switch_assign,
            )
        )

        self.combo_assign_mode = ComboBox()
        self.combo_assign_mode.addItems([self.tr("固定"), self.tr("轮换")])
        self.combo_assign_mode.currentIndexChanged.connect(self._update_assign_panels)
        self.combo_assign_period = ComboBox()
        self.combo_assign_period.addItems([self.tr("按天"), self.tr("按周")])
        assign_ctrl = QWidget()
        ac = QHBoxLayout(assign_ctrl)
        ac.setContentsMargins(0, 0, 0, 0)
        ac.setSpacing(8)
        ac.addWidget(CaptionLabel(self.tr("方式")))
        ac.addWidget(self.combo_assign_mode)
        ac.addWidget(CaptionLabel(self.tr("周期")))
        ac.addWidget(self.combo_assign_period)
        sec.addWidget(
            setting_card(
                self.tr("指派方式"),
                self.tr("固定：每个职务指定人员；轮换：按周期自动轮转分配。"),
                assign_ctrl,
            )
        )

        body = block_card(sec)
        self.table_roles = TableWidget()
        self.table_roles.setColumnCount(2)
        self.table_roles.setHorizontalHeaderLabels([self.tr("职务"), self.tr("固定人员（学号/姓名，逗号分隔）")])
        self.table_roles.horizontalHeader().setStretchLastSection(True)
        self.table_roles.setMinimumHeight(200)
        body.addWidget(self.table_roles)

        btns = QHBoxLayout()
        add_role = PushButton(self.tr("添加职务"))
        add_role.clicked.connect(lambda: self._add_role_row("", ""))
        del_role = PushButton(self.tr("删除选中"))
        del_role.clicked.connect(self._remove_role_row)
        btns.addWidget(add_role)
        btns.addWidget(del_role)
        btns.addStretch(1)
        body.addLayout(btns)
        self._update_assign_panels()

    def _build_change_rules(self, layout: QVBoxLayout) -> None:
        sec = new_section(layout)
        add_subtitle(sec, self.tr("值日改班规则"))

        self.switch_carry_monitor = SwitchButton()
        self.switch_carry_monitor.setOnText(self.tr("启用"))
        self.switch_carry_monitor.setOffText(self.tr("禁用"))
        sec.addWidget(
            setting_card(
                self.tr("值日班长被取消时顺延"),
                self.tr("改班时划掉值日班长，值日生自动多顺延一人补齐。"),
                self.switch_carry_monitor,
            )
        )

        self.switch_priority_missed = SwitchButton()
        self.switch_priority_missed.setOnText(self.tr("启用"))
        self.switch_priority_missed.setOffText(self.tr("禁用"))
        sec.addWidget(
            setting_card(
                self.tr("被取消值日者优先补值"),
                self.tr("因故被取消值日的成员，缺几次就在之后的值日中优先安排几次。"),
                self.switch_priority_missed,
            )
        )

        body = block_card(sec, self.tr("休学用户"), self.tr("休学用户在名单中但不参与排班；可在“值日改班”中临时补值一天。"))
        row = QHBoxLayout()
        self.line_suspend = LineEdit()
        self.line_suspend.setPlaceholderText(self.tr("输入学号或姓名"))
        self.line_suspend.setFixedWidth(220)
        self.line_suspend.setClearButtonEnabled(True)
        add_suspend = PushButton(self.tr("添加"))
        add_suspend.clicked.connect(self._add_suspended)
        remove_suspend = PushButton(self.tr("移除选中"))
        remove_suspend.clicked.connect(self._remove_suspended)
        row.addWidget(self.line_suspend)
        row.addWidget(add_suspend)
        row.addWidget(remove_suspend)
        row.addStretch(1)
        body.addLayout(row)

        self.list_suspended = QListWidget()
        self.list_suspended.setMaximumHeight(160)
        self.list_suspended.setAlternatingRowColors(True)
        body.addWidget(self.list_suspended)

    def _add_suspended(self) -> None:
        key = self.line_suspend.text().strip()
        if not key:
            return
        student = self.manager.student_by_key(key)
        if student is None:
            InfoBar.warning(
                title="",
                content=self.tr("未找到该学号/姓名对应的学生"),
                orient=Qt.Horizontal,
                position=InfoBarPosition.TOP,
                duration=2500,
                parent=self.window(),
            )
            return
        display = student.label
        if self.list_suspended.findItems(display, Qt.MatchExactly):
            self.line_suspend.clear()
            return
        item = QListWidgetItem(display)
        item.setData(Qt.UserRole, student.key)
        self.list_suspended.addItem(item)
        self.line_suspend.clear()

    def _remove_suspended(self) -> None:
        for item in self.list_suspended.selectedItems():
            self.list_suspended.takeItem(self.list_suspended.row(item))

    def _build_text(self, layout: QVBoxLayout) -> None:
        sec = new_section(layout)
        add_subtitle(sec, self.tr("自定义文案"))

        self.line_big_title = LineEdit()
        self.line_big_title.setFixedWidth(420)
        sec.addWidget(setting_card(self.tr("大提示标题"), '', self.line_big_title))

        self.line_small = LineEdit()
        self.line_small.setFixedWidth(420)
        sec.addWidget(setting_card(self.tr("小组件标题"), '', self.line_small))

        body = block_card(
            sec,
            self.tr("大提示正文"),
            self.tr(
                "可用占位符：{monitor} {students} {assignments} {date} {weekday}。用 **文字** 表示标红，例如 **禁止逃跑！**"
            ),
        )
        self.text_big = PlainTextEdit()
        self.text_big.setMinimumHeight(120)
        body.addWidget(self.text_big)

    # -- 辅助控件 --------------------------------------------------------- #
    def _build_overrides(self, layout: QVBoxLayout) -> None:
        body = block_card(
            layout,
            self.tr("特别安排"),
            self.tr(
                "为某一天（或多天）单独指定值日生/班长，覆盖自动排班。日期格式 YYYY-MM-DD；“按周批量”会填充该日期所在整周。"
            ),
        )
        self.table_overrides = TableWidget()
        self.table_overrides.setColumnCount(4)
        self.table_overrides.setHorizontalHeaderLabels(
            [self.tr("日期"), self.tr("值日生"), self.tr("值日班长"), self.tr("备注")]
        )
        self.table_overrides.horizontalHeader().setStretchLastSection(True)
        self.table_overrides.setMinimumHeight(180)
        body.addWidget(self.table_overrides)

        btns = QHBoxLayout()
        add_btn = PushButton(self.tr("添加一行"))
        add_btn.clicked.connect(lambda: self._add_override_row("", "", "", ""))
        remove_btn = PushButton(self.tr("删除选中"))
        remove_btn.clicked.connect(self._remove_override_row)
        week_btn = PushButton(self.tr("按周批量"))
        week_btn.clicked.connect(self._fill_week)
        for b in (add_btn, remove_btn, week_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        body.addLayout(btns)

    def _add_override_row(self, day: str, students: str, monitor: str, note: str) -> None:
        row = self.table_overrides.rowCount()
        self.table_overrides.insertRow(row)
        for col, value in enumerate([day, students, monitor, note]):
            self.table_overrides.setItem(row, col, QTableWidgetItem(value))

    def _remove_override_row(self) -> None:
        rows = sorted({i.row() for i in self.table_overrides.selectedItems()}, reverse=True)
        for r in rows:
            self.table_overrides.removeRow(r)

    def _fill_week(self) -> None:
        rows = {i.row() for i in self.table_overrides.selectedItems()}
        if not rows:
            self._toast_error(self.tr("请先选择一行并填写日期"))
            return
        row = min(rows)
        day_item = self.table_overrides.item(row, 0)
        try:
            base = dt.date.fromisoformat((day_item.text() if day_item else "").strip())
        except Exception:
            self._toast_error(self.tr("日期格式应为 YYYY-MM-DD"))
            return
        students = self.table_overrides.item(row, 1).text() if self.table_overrides.item(row, 1) else ""
        monitor = self.table_overrides.item(row, 2).text() if self.table_overrides.item(row, 2) else ""
        note = self.table_overrides.item(row, 3).text() if self.table_overrides.item(row, 3) else ""
        monday = base - dt.timedelta(days=base.weekday())
        existing = {
            (self.table_overrides.item(r, 0).text().strip() if self.table_overrides.item(r, 0) else "")
            for r in range(self.table_overrides.rowCount())
        }
        count = 7 if self.switch_weekend.isChecked() else 5
        for i in range(count):
            iso = (monday + dt.timedelta(days=i)).isoformat()
            if iso in existing:
                continue
            self._add_override_row(iso, students, monitor, note)

    def _collect_overrides(self):
        result = {}
        for r in range(self.table_overrides.rowCount()):
            day_item = self.table_overrides.item(r, 0)
            if day_item is None or not day_item.text().strip():
                continue
            students_item = self.table_overrides.item(r, 1)
            monitor_item = self.table_overrides.item(r, 2)
            note_item = self.table_overrides.item(r, 3)
            result[day_item.text().strip()] = DayOverride(
                students=self._parse_keys(students_item.text() if students_item else ""),
                monitor=(monitor_item.text().strip() if monitor_item else ""),
                note=(note_item.text().strip() if note_item else ""),
            )
        return result

    def _make_key_row(self):
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        edit = LineEdit()
        edit.setPlaceholderText(self.tr("学号/姓名，逗号分隔"))
        pick = PushButton(self.tr("选择"))
        pick.clicked.connect(lambda: self._pick_into(edit))
        lay.addWidget(edit, 1)
        lay.addWidget(pick)
        return container, edit

    def _pick_into(self, edit: LineEdit) -> None:
        keys = self._pick_students(edit.text())
        if keys is not None:
            edit.setText(keys)

    def _pick_students(self, current_text: str) -> Optional[str]:
        students = self.manager.config.students
        if not students:
            self._toast_error(self.tr("名单为空，请先在“学生名单”中添加。"))
            return None
        current = {k.strip() for k in (current_text or "").split(",") if k.strip()}
        dialog = QDialog(self)
        dialog.setWindowTitle(self.tr("选择学生"))
        dialog.setMinimumSize(360, 460)
        lay = QVBoxLayout(dialog)
        lst = QListWidget(dialog)
        lst.setSelectionMode(QAbstractItemView.MultiSelection)
        for s in students:
            item = QListWidgetItem(s.label, lst)
            item.setData(Qt.UserRole, s.key)
            if s.key in current:
                item.setSelected(True)
        lay.addWidget(lst)
        btns = QHBoxLayout()
        ok = PrimaryPushButton(self.tr("确定"), dialog)
        cancel = PushButton(self.tr("取消"), dialog)
        ok.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)
        if dialog.exec_() == QDialog.Accepted:
            return ",".join(item.data(Qt.UserRole) for item in lst.selectedItems())
        return None

    @staticmethod
    def _parse_keys(text: str) -> List[str]:
        parts: List[str] = []
        for chunk in (text or "").replace("，", ",").replace("、", ",").replace(" ", ",").split(","):
            chunk = chunk.strip()
            if chunk and chunk not in parts:
                parts.append(chunk)
        return parts

    def _toast_error(self, message: str) -> None:
        InfoBar.error(
            title=self.tr("提示"),
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def _toast_ok(self, message: str) -> None:
        InfoBar.success(
            title=self.tr("成功"),
            content=message,
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2500,
            parent=self,
        )

    # -- 面板联动 --------------------------------------------------------- #
    def _update_mode_panels(self) -> None:
        fixed = self.combo_mode.currentIndex() == 1
        self.id_panel.setVisible(not fixed)
        self.fixed_panel.setVisible(fixed)

    def _update_monitor_panels(self) -> None:
        daily = self.combo_monitor_mode.currentIndex() == 1
        self.monitor_weekly_panel.setVisible(not daily)
        self.monitor_daily_panel.setVisible(daily)

    def _update_assign_panels(self) -> None:
        rotate = self.combo_assign_mode.currentIndex() == 1
        self.combo_assign_period.setEnabled(rotate)

    # -- 名单表格 --------------------------------------------------------- #
    def _add_student_row(self, name: str = "", sid: str = "") -> None:
        row = self.table_students.rowCount()
        self.table_students.insertRow(row)
        self.table_students.setItem(row, 0, self._item(name))
        self.table_students.setItem(row, 1, self._item(sid))

    def _remove_student_row(self) -> None:
        row = self.table_students.currentRow()
        if row >= 0:
            self.table_students.removeRow(row)

    def _clear_students(self) -> None:
        box = MessageBox(self.tr("确认清空"), self.tr("将清空所有学生名单及排班引用，确定吗？"), self)
        if box.exec():
            self.table_students.setRowCount(0)

    def _import_students(self) -> None:
        from PyQt5.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self, self.tr("导入名单"), "", self.tr("CSV/JSON (*.csv *.json)")
        )
        if not path:
            return
        count = self.manager.import_csv(path) if path.lower().endswith(".csv") else self.manager.import_json(path)
        self.load_roster()
        self._toast_ok(self.tr("已导入 {count} 人").format(count=count))

    def _export_students(self) -> None:
        from PyQt5.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("导出名单"), "duty_students.csv", self.tr("CSV (*.csv);;JSON (*.json)")
        )
        if not path:
            return
        ok = self.manager.export_csv(path) if path.lower().endswith(".csv") else self.manager.export_json(path)
        if ok:
            self._toast_ok(self.tr("导出成功"))

    @staticmethod
    def _item(text: str):
        item = QTableWidgetItem(text or "")
        item.setTextAlignment(Qt.AlignCenter)
        return item

    # -- 角色/职务表格 ---------------------------------------------------- #
    def _add_role_row(self, name: str = "", people: str = "") -> None:
        row = self.table_roles.rowCount()
        self.table_roles.insertRow(row)
        self.table_roles.setItem(row, 0, self._item(name))
        self.table_roles.setItem(row, 1, self._item(people))

    def _remove_role_row(self) -> None:
        row = self.table_roles.currentRow()
        if row >= 0:
            self.table_roles.removeRow(row)

    # -- 载入 / 保存 ------------------------------------------------------ #
    def load_config(self) -> None:
        self.manager = get_duty_manager()
        cfg = self.manager.config
        self.switch_enabled.setChecked(cfg.enabled)
        self.combo_prompt.setCurrentIndex(
            _PROMPT_STYLES.index(cfg.prompt_style) if cfg.prompt_style in _PROMPT_STYLES else 0
        )
        self.combo_delivery.setCurrentIndex(
            _DELIVERY_MODES.index(cfg.prompt_delivery) if cfg.prompt_delivery in _DELIVERY_MODES else 0
        )
        self.switch_weekend.setChecked(cfg.include_weekend)
        self.table_overrides.setRowCount(0)
        for day in sorted(cfg.overrides):
            ov = cfg.overrides[day]
            self._add_override_row(day, ",".join(ov.students), ov.monitor, ov.note)
        self.load_roster()
        self.combo_mode.setCurrentIndex(1 if cfg.mode == MODE_FIXED else 0)

        self.spin_count.setValue(int(cfg.id_rotation.count_per_day))
        self.combo_order.setCurrentIndex(1 if cfg.id_rotation.order == "roster" else 0)
        self.switch_weekly_reset.setChecked(cfg.id_rotation.weekly_reset)
        self.line_start_key.setText(cfg.id_rotation.start_key)
        self.switch_per_weekday.setChecked(bool(cfg.id_rotation.per_weekday))
        for i, spin in enumerate(self.per_weekday_spins):
            spin.setValue(int(cfg.id_rotation.per_weekday.get(str(i), 0)))
        for i, edit in enumerate(self.fixed_edits):
            edit.setText(",".join(cfg.fixed.get(str(i), [])))

        self.switch_monitor.setChecked(cfg.monitor.enabled)
        self.combo_monitor_mode.setCurrentIndex(1 if cfg.monitor.mode == MONITOR_DAILY else 0)
        self.line_monitor_weekly.setText(",".join(cfg.monitor.weekly))
        for i, edit in enumerate(self.daily_monitor_edits):
            edit.setText(cfg.monitor.daily.get(str(i), ""))

        self.switch_assign.setChecked(cfg.assign.enabled)
        self.combo_assign_mode.setCurrentIndex(1 if cfg.assign.mode == ASSIGN_ROTATE else 0)
        self.combo_assign_period.setCurrentIndex(1 if cfg.assign.period == PERIOD_WEEK else 0)
        self.table_roles.setRowCount(0)
        for role in cfg.assign.roles:
            self._add_role_row(role.name, ",".join(role.people))

        self.switch_carry_monitor.setChecked(cfg.change_rules.carry_over_monitor)
        self.switch_priority_missed.setChecked(cfg.change_rules.priority_missed)
        self.list_suspended.clear()
        for key in cfg.suspended:
            student = self.manager.student_by_key(key)
            item = QListWidgetItem(student.label if student else key)
            item.setData(Qt.UserRole, key)
            self.list_suspended.addItem(item)

        self.line_big_title.setText(cfg.big_title)
        self.line_small.setText(cfg.small_text)
        self.text_big.setPlainText(cfg.big_text)
        self._update_mode_panels()
        self._update_monitor_panels()
        self._update_assign_panels()

    def load_roster(self) -> None:
        self.table_students.setRowCount(0)
        for s in self.manager.config.students:
            self._add_student_row(s.name, s.id)

    def _collect_students(self) -> List[Student]:
        students: List[Student] = []
        seen = set()
        for row in range(self.table_students.rowCount()):
            name_item = self.table_students.item(row, 0)
            id_item = self.table_students.item(row, 1)
            name = (name_item.text() if name_item else "").strip()
            sid = (id_item.text() if id_item else "").strip()
            if not name:
                continue
            key = sid or name
            if key in seen:
                continue
            seen.add(key)
            students.append(Student(name=name, id=sid))
        return students

    def save_config(self) -> None:
        cfg = self.manager.config
        cfg.enabled = self.switch_enabled.isChecked()
        cfg.prompt_style = _PROMPT_STYLES[max(0, self.combo_prompt.currentIndex())]
        cfg.students = self._collect_students()
        cfg.mode = MODE_FIXED if self.combo_mode.currentIndex() == 1 else MODE_ID_ROTATION

        cfg.id_rotation.count_per_day = self.spin_count.value()
        cfg.id_rotation.order = "roster" if self.combo_order.currentIndex() == 1 else "id"
        cfg.id_rotation.weekly_reset = self.switch_weekly_reset.isChecked()
        cfg.id_rotation.start_key = self.line_start_key.text().strip()
        if self.switch_per_weekday.isChecked():
            cfg.id_rotation.per_weekday = {
                str(i): spin.value() for i, spin in enumerate(self.per_weekday_spins)
            }
        else:
            cfg.id_rotation.per_weekday = {}
        cfg.fixed = {str(i): self._parse_keys(edit.text()) for i, edit in enumerate(self.fixed_edits)}

        cfg.monitor.enabled = self.switch_monitor.isChecked()
        cfg.monitor.mode = MONITOR_DAILY if self.combo_monitor_mode.currentIndex() == 1 else MONITOR_WEEKLY
        cfg.monitor.weekly = self._parse_keys(self.line_monitor_weekly.text())
        cfg.monitor.daily = {
            str(i): (self.daily_monitor_edits[i].text().strip())
            for i in range(len(self.daily_monitor_edits))
            if self.daily_monitor_edits[i].text().strip()
        }

        cfg.assign.enabled = self.switch_assign.isChecked()
        cfg.assign.mode = ASSIGN_ROTATE if self.combo_assign_mode.currentIndex() == 1 else ASSIGN_FIXED
        cfg.assign.period = PERIOD_WEEK if self.combo_assign_period.currentIndex() == 1 else PERIOD_DAY
        roles: List[Role] = []
        for row in range(self.table_roles.rowCount()):
            name_item = self.table_roles.item(row, 0)
            people_item = self.table_roles.item(row, 1)
            name = (name_item.text() if name_item else "").strip()
            if not name:
                continue
            roles.append(Role(name, self._parse_keys(people_item.text() if people_item else "")))
        if roles:
            cfg.assign.roles = roles

        cfg.prompt_delivery = _DELIVERY_MODES[max(0, self.combo_delivery.currentIndex())]
        cfg.include_weekend = self.switch_weekend.isChecked()
        cfg.overrides = self._collect_overrides()
        cfg.change_rules.carry_over_monitor = self.switch_carry_monitor.isChecked()
        cfg.change_rules.priority_missed = self.switch_priority_missed.isChecked()
        cfg.suspended = [
            self.list_suspended.item(i).data(Qt.UserRole) or self.list_suspended.item(i).text()
            for i in range(self.list_suspended.count())
        ]
        cfg.big_title = self.line_big_title.text()
        cfg.small_text = self.line_small.text()
        cfg.big_text = self.text_big.toPlainText()
        if not cfg.anchor_date:
            cfg.anchor_date = dt.date.today().isoformat()

        self.manager.save()
        self._toast_ok(self.tr("已保存至 config/duty.json"))

    # -- 预览 ------------------------------------------------------------- #
    def _preview_prompt(self) -> None:
        try:
            from duty import get_duty_manager
            from duty_prompt import show_duty_prompt

            manager = get_duty_manager()
            day = manager.get_day(dt.date.today())
            show_duty_prompt(day, manager)
        except Exception as e:
            logger.error(f"预览值日生提示失败: {e}")

    def _open_viewer(self) -> None:
        from duty_viewer import open_duty_viewer

        open_duty_viewer(self)
