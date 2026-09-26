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
    CardWidget,
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
    SmoothScrollArea,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TableWidget,
    TitleLabel,
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

        layout.addWidget(TitleLabel(self.tr("值日生"), content))

        self._build_general(layout, content)
        self._build_roster(layout, content)
        self._build_schedule(layout, content)
        self._build_monitor(layout, content)
        self._build_assign(layout, content)
        self._build_text(layout, content)
        self._build_overrides(layout, content)

        actions = QHBoxLayout()
        preview_btn = PushButton(self.tr("预览提示"), content)
        preview_btn.clicked.connect(self._preview_prompt)
        viewer_btn = PushButton(self.tr("打开查看器"), content)
        viewer_btn.clicked.connect(self._open_viewer)
        save_btn = PrimaryPushButton(self.tr("保存"), content)
        save_btn.clicked.connect(self.save_config)
        actions.addWidget(preview_btn)
        actions.addWidget(viewer_btn)
        actions.addStretch(1)
        actions.addWidget(save_btn)
        layout.addLayout(actions)
        layout.addStretch(1)

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

    def _build_general(self, layout: QVBoxLayout, parent: QWidget) -> None:
        body = self._card(layout, self.tr("总开关与提示样式"), self.tr("启用值日生功能，并选择最后一节课结束时的提示形式。"))
        row = QHBoxLayout()
        row.addWidget(StrongBodyLabel(self.tr("启用值日生功能")))
        row.addStretch(1)
        self.switch_enabled = SwitchButton()
        self.switch_enabled.setChecked(False)
        row.addWidget(self.switch_enabled)
        body.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(StrongBodyLabel(self.tr("大型提示样式")))
        row2.addStretch(1)
        self.combo_prompt = ComboBox()
        self.combo_prompt.addItems([self.tr("全屏遮罩"), self.tr("顶部横幅"), self.tr("中央大卡片")])
        row2.addWidget(self.combo_prompt)
        body.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(StrongBodyLabel(self.tr("提示送达方式")))
        row3.addStretch(1)
        self.combo_delivery = ComboBox()
        self.combo_delivery.addItems([self.tr("弹窗提示"), self.tr("常驻小组件"), self.tr("两者都显示")])
        row3.addWidget(self.combo_delivery)
        body.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(StrongBodyLabel(self.tr("包含周六、周日排班")))
        row4.addStretch(1)
        self.switch_weekend = SwitchButton()
        row4.addWidget(self.switch_weekend)
        body.addLayout(row4)

    def _build_roster(self, layout: QVBoxLayout, parent: QWidget) -> None:
        body = self._card(
            layout,
            self.tr("学生名单"),
            self.tr("录入姓名与学号（学号可留空）。排班支持“学号”排序或“录入顺序”。"),
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

    def _build_schedule(self, layout: QVBoxLayout, parent: QWidget) -> None:
        body = self._card(layout, self.tr("排班模式"), self.tr("学号排班：每天按顺序抽取若干学号；固定排班：周一至周五固定人员。"))
        row = QHBoxLayout()
        row.addWidget(StrongBodyLabel(self.tr("模式")))
        row.addStretch(1)
        self.combo_mode = ComboBox()
        self.combo_mode.addItems([self.tr("学号排班"), self.tr("固定排班")])
        self.combo_mode.currentIndexChanged.connect(self._update_mode_panels)
        row.addWidget(self.combo_mode)
        body.addLayout(row)

        self.id_panel = CardWidget()
        ip = QVBoxLayout(self.id_panel)
        ip.setContentsMargins(12, 10, 12, 12)
        ip.setSpacing(6)
        r1 = QHBoxLayout()
        r1.addWidget(StrongBodyLabel(self.tr("每日人数")))
        r1.addStretch(1)
        self.spin_count = SpinBox()
        self.spin_count.setRange(0, 99)
        r1.addWidget(self.spin_count)
        ip.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(StrongBodyLabel(self.tr("排序方式")))
        r2.addStretch(1)
        self.combo_order = ComboBox()
        self.combo_order.addItems([self.tr("按学号"), self.tr("按录入顺序")])
        r2.addWidget(self.combo_order)
        ip.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(StrongBodyLabel(self.tr("每周重置（周一从起始开始）")))
        r3.addStretch(1)
        self.switch_weekly_reset = SwitchButton()
        r3.addWidget(self.switch_weekly_reset)
        ip.addLayout(r3)

        r4 = QHBoxLayout()
        r4.addWidget(StrongBodyLabel(self.tr("起始学号/姓名")))
        r4.addStretch(1)
        self.line_start_key = LineEdit()
        self.line_start_key.setPlaceholderText(self.tr("留空表示从第一个开始"))
        self.line_start_key.setFixedWidth(220)
        r4.addWidget(self.line_start_key)
        ip.addLayout(r4)

        r5 = QHBoxLayout()
        r5.addWidget(StrongBodyLabel(self.tr("每日单独人数")))
        r5.addStretch(1)
        self.switch_per_weekday = SwitchButton()
        r5.addWidget(self.switch_per_weekday)
        ip.addLayout(r5)
        self.per_weekday_spins: List[SpinBox] = []
        pw_row = QHBoxLayout()
        for i, name in enumerate(["周一", "周二", "周三", "周四", "周五"]):
            pw_row.addWidget(CaptionLabel(self.tr(name)))
            spin = SpinBox()
            spin.setRange(0, 99)
            spin.setFixedWidth(70)
            self.per_weekday_spins.append(spin)
            pw_row.addWidget(spin)
        ip.addLayout(pw_row)

        self.fixed_panel = CardWidget()
        fp = QVBoxLayout(self.fixed_panel)
        fp.setContentsMargins(12, 10, 12, 12)
        fp.setSpacing(6)
        fp.addWidget(CaptionLabel(self.tr("输入学号或姓名（逗号分隔），也可点击“选择”从名单中挑选。")))
        self.fixed_edits: List[LineEdit] = []
        for name in ["周一", "周二", "周三", "周四", "周五"]:
            frow = QHBoxLayout()
            frow.addWidget(StrongBodyLabel(self.tr(name)))
            container, edit = self._make_key_row()
            self.fixed_edits.append(edit)
            frow.addWidget(container, 1)
            fp.addLayout(frow)

        self.id_panel.setVisible(True)
        self.fixed_panel.setVisible(False)
        body.addWidget(self.id_panel)
        body.addWidget(self.fixed_panel)

    def _build_monitor(self, layout: QVBoxLayout, parent: QWidget) -> None:
        body = self._card(layout, self.tr("值日班长"), self.tr("按周轮换：每周一位班长；按天：周一至周五分别指定。"))
        r0 = QHBoxLayout()
        r0.addWidget(StrongBodyLabel(self.tr("启用值日班长")))
        r0.addStretch(1)
        self.switch_monitor = SwitchButton()
        r0.addWidget(self.switch_monitor)
        body.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(StrongBodyLabel(self.tr("模式")))
        r1.addStretch(1)
        self.combo_monitor_mode = ComboBox()
        self.combo_monitor_mode.addItems([self.tr("按周轮换"), self.tr("按天指定")])
        self.combo_monitor_mode.currentIndexChanged.connect(self._update_monitor_panels)
        r1.addWidget(self.combo_monitor_mode)
        body.addLayout(r1)

        self.monitor_weekly_panel = QWidget()
        mw = QHBoxLayout(self.monitor_weekly_panel)
        mw.setContentsMargins(0, 0, 0, 0)
        mw.addWidget(StrongBodyLabel(self.tr("班长轮换列表")))
        container, self.line_monitor_weekly = self._make_key_row()
        mw.addWidget(container, 1)
        body.addWidget(self.monitor_weekly_panel)

        self.monitor_daily_panel = QWidget()
        md = QVBoxLayout(self.monitor_daily_panel)
        md.setContentsMargins(0, 0, 0, 0)
        self.daily_monitor_edits: List[LineEdit] = []
        for name in ["周一", "周二", "周三", "周四", "周五"]:
            drow = QHBoxLayout()
            drow.addWidget(StrongBodyLabel(self.tr(name)))
            container, edit = self._make_key_row()
            self.daily_monitor_edits.append(edit)
            drow.addWidget(container, 1)
            md.addLayout(drow)
        body.addWidget(self.monitor_daily_panel)
        self._update_monitor_panels()

    def _build_assign(self, layout: QVBoxLayout, parent: QWidget) -> None:
        body = self._card(layout, self.tr("职务指派（可选）"), self.tr("固定：每个职务指定人员；轮换：按周期自动轮转分配职务。"))
        r0 = QHBoxLayout()
        r0.addWidget(StrongBodyLabel(self.tr("启用职务指派")))
        r0.addStretch(1)
        self.switch_assign = SwitchButton()
        r0.addWidget(self.switch_assign)
        body.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(StrongBodyLabel(self.tr("指派方式")))
        r1.addStretch(1)
        self.combo_assign_mode = ComboBox()
        self.combo_assign_mode.addItems([self.tr("固定"), self.tr("轮换")])
        self.combo_assign_mode.currentIndexChanged.connect(self._update_assign_panels)
        r1.addWidget(self.combo_assign_mode)
        r1.addWidget(StrongBodyLabel(self.tr("轮换周期")))
        self.combo_assign_period = ComboBox()
        self.combo_assign_period.addItems([self.tr("按天"), self.tr("按周")])
        r1.addWidget(self.combo_assign_period)
        body.addLayout(r1)

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

    def _build_text(self, layout: QVBoxLayout, parent: QWidget) -> None:
        body = self._card(
            layout,
            self.tr("自定义文案"),
            self.tr("可用占位符：{monitor} {students} {assignments} {date} {weekday}。用 **文字** 表示标红，例如 **禁止逃跑！**"),
        )
        r1 = QHBoxLayout()
        r1.addWidget(StrongBodyLabel(self.tr("大提示标题")))
        r1.addStretch(1)
        self.line_big_title = LineEdit()
        self.line_big_title.setFixedWidth(420)
        r1.addWidget(self.line_big_title)
        body.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(StrongBodyLabel(self.tr("小组件标题")))
        r2.addStretch(1)
        self.line_small = LineEdit()
        self.line_small.setFixedWidth(420)
        r2.addWidget(self.line_small)
        body.addLayout(r2)

        body.addWidget(StrongBodyLabel(self.tr("大提示正文")))
        self.text_big = PlainTextEdit()
        self.text_big.setMinimumHeight(120)
        body.addWidget(self.text_big)

    # -- 辅助控件 --------------------------------------------------------- #
    def _build_overrides(self, layout: QVBoxLayout, parent: QWidget) -> None:
        body = self._card(
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
