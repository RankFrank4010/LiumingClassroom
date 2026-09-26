"""值日生功能：数据模型、配置管理与排班计算。

该模块不依赖 PyQt，可独立进行逻辑测试。
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:  # 允许在没有第三方依赖时进行纯逻辑测试
    from loguru import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("duty")


WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
DUTY_WEEKDAYS = [0, 1, 2, 3, 4]  # 周一至周五
WEEKEND_DAYS = [5, 6]  # 周六、周日


def active_weekdays(include_weekend: bool) -> List[int]:
    """按配置返回参与排班的星期（0=周一）。"""
    return DUTY_WEEKDAYS + WEEKEND_DAYS if include_weekend else list(DUTY_WEEKDAYS)

MODE_ID_ROTATION = "id_rotation"
MODE_FIXED = "fixed"

MONITOR_WEEKLY = "weekly"
MONITOR_DAILY = "daily"

ASSIGN_FIXED = "fixed"
ASSIGN_ROTATE = "rotate"

PERIOD_DAY = "day"
PERIOD_WEEK = "week"

PROMPT_OVERLAY = "overlay"
PROMPT_BANNER = "banner"
PROMPT_WIDGET = "widget"

# 提示送达方式：弹窗 / 常驻小组件 / 两者
DELIVERY_POPUP = "popup"
DELIVERY_WIDGET = "widget"
DELIVERY_BOTH = "both"
DELIVERY_MODES = (DELIVERY_POPUP, DELIVERY_WIDGET, DELIVERY_BOTH)


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class Student:
    name: str
    id: str = ""

    @property
    def key(self) -> str:
        """稳定标识：优先学号，其次姓名。"""
        return self.id.strip() or self.name.strip()

    @property
    def label(self) -> str:
        """显示文本，例如：李明（101）。"""
        if self.id.strip():
            return f"{self.name}（{self.id}）"
        return self.name


@dataclass
class IdRotation:
    """学号排班规则。"""

    count_per_day: int = 4
    per_weekday: Dict[str, int] = field(default_factory=dict)  # "0".."4" 覆盖每日人数
    order: str = "id"  # id | roster
    weekly_reset: bool = False  # 每周重置（周一从起始开始）
    start_key: str = ""  # 起始学号/姓名

    def count_for(self, weekday: int) -> int:
        value = self.per_weekday.get(str(weekday))
        if value is None:
            return int(self.count_per_day)
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(self.count_per_day)


@dataclass
class MonitorConfig:
    """值日班长配置。"""

    enabled: bool = True
    mode: str = MONITOR_WEEKLY  # weekly | daily
    weekly: List[str] = field(default_factory=list)  # 按周轮换的班长 key 列表
    daily: Dict[str, str] = field(default_factory=dict)  # "0".."4" -> key


@dataclass
class Role:
    """职务（如拖地）。"""

    name: str
    people: List[str] = field(default_factory=list)  # 固定指派时的人员 key


@dataclass
class AssignConfig:
    """职务指派配置。"""

    enabled: bool = False
    mode: str = ASSIGN_FIXED  # fixed | rotate
    period: str = PERIOD_WEEK  # day | week（轮换周期）
    roles: List[Role] = field(
        default_factory=lambda: [Role("拖地"), Role("桌椅"), Role("扫地"), Role("擦黑板")]
    )


@dataclass
class DayOverride:
    """某一天的特别安排：完全覆盖当日排班。"""

    students: List[str] = field(default_factory=list)
    monitor: str = ""
    assignments: List[Tuple[str, List[str]]] = field(default_factory=list)
    note: str = ""


@dataclass
class DutyConfig:
    enabled: bool = False
    students: List[Student] = field(default_factory=list)
    mode: str = MODE_ID_ROTATION  # id_rotation | fixed
    id_rotation: IdRotation = field(default_factory=IdRotation)
    fixed: Dict[str, List[str]] = field(default_factory=dict)  # "0".."4" -> keys
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    assign: AssignConfig = field(default_factory=AssignConfig)
    prompt_style: str = PROMPT_OVERLAY  # overlay | banner | widget
    prompt_delivery: str = DELIVERY_POPUP  # popup | widget | both（widget=常驻小组件）
    include_weekend: bool = False  # 是否把周六、周日纳入排班
    big_title: str = "值日生就位！"
    big_text: str = "值日班长：{monitor}\n值日生：{students}\n**禁止逃跑！**"
    small_text: str = "今日值日生"
    anchor_date: str = ""  # 轮换锚点日期（YYYY-MM-DD），空表示今天
    overrides: Dict[str, DayOverride] = field(default_factory=dict)  # "YYYY-MM-DD" -> 特别安排


@dataclass
class DayDuty:
    date: dt.date
    students: List[Student] = field(default_factory=list)
    monitor: Optional[Student] = None
    assignments: List[Tuple[str, List[Student]]] = field(default_factory=list)
    is_weekend: bool = False


# --------------------------------------------------------------------------- #
# 序列化
# --------------------------------------------------------------------------- #
def _student_from(data: Any) -> Student:
    if isinstance(data, str):
        return Student(name=data)
    if isinstance(data, dict):
        return Student(name=str(data.get("name", "")).strip(), id=str(data.get("id", "")).strip())
    return Student(name=str(data))


def _student_to(student: Student) -> Dict[str, str]:
    return {"name": student.name, "id": student.id}


def config_to_dict(config: DutyConfig) -> Dict[str, Any]:
    return {
        "enabled": bool(config.enabled),
        "students": [_student_to(s) for s in config.students],
        "mode": config.mode,
        "id_rotation": asdict(config.id_rotation),
        "fixed": {str(k): list(v) for k, v in config.fixed.items()},
        "monitor": asdict(config.monitor),
        "assign": {
            "enabled": bool(config.assign.enabled),
            "mode": config.assign.mode,
            "period": config.assign.period,
            "roles": [{"name": r.name, "people": list(r.people)} for r in config.assign.roles],
        },
        "prompt_style": config.prompt_style,
        "prompt_delivery": config.prompt_delivery,
        "include_weekend": bool(config.include_weekend),
        "big_title": config.big_title,
        "big_text": config.big_text,
        "small_text": config.small_text,
        "anchor_date": config.anchor_date,
        "overrides": {
            day: {
                "students": list(ov.students),
                "monitor": ov.monitor,
                "assignments": [
                    {"name": name, "people": list(people)} for name, people in ov.assignments
                ],
                "note": ov.note,
            }
            for day, ov in config.overrides.items()
        },
    }


def config_from_dict(data: Dict[str, Any]) -> DutyConfig:
    if not isinstance(data, dict):
        return DutyConfig()
    config = DutyConfig()
    config.enabled = bool(data.get("enabled", False))
    config.students = [_student_from(s) for s in data.get("students", []) if _student_from(s).name]
    config.mode = str(data.get("mode", MODE_ID_ROTATION))
    if config.mode not in (MODE_ID_ROTATION, MODE_FIXED):
        config.mode = MODE_ID_ROTATION

    ir = data.get("id_rotation") or {}
    config.id_rotation = IdRotation(
        count_per_day=int(ir.get("count_per_day", 4) or 0),
        per_weekday={str(k): int(v) for k, v in (ir.get("per_weekday") or {}).items()},
        order=str(ir.get("order", "id")),
        weekly_reset=bool(ir.get("weekly_reset", False)),
        start_key=str(ir.get("start_key", "")),
    )

    fixed = data.get("fixed") or {}
    config.fixed = {str(k): [str(x) for x in v] for k, v in fixed.items() if isinstance(v, list)}

    mc = data.get("monitor") or {}
    config.monitor = MonitorConfig(
        enabled=bool(mc.get("enabled", True)),
        mode=str(mc.get("mode", MONITOR_WEEKLY)),
        weekly=[str(x) for x in (mc.get("weekly") or [])],
        daily={str(k): str(v) for k, v in (mc.get("daily") or {}).items()},
    )
    if config.monitor.mode not in (MONITOR_WEEKLY, MONITOR_DAILY):
        config.monitor.mode = MONITOR_WEEKLY

    ac = data.get("assign") or {}
    roles = []
    for r in ac.get("roles") or []:
        if isinstance(r, str):
            roles.append(Role(r))
        elif isinstance(r, dict):
            roles.append(Role(str(r.get("name", "")), [str(x) for x in r.get("people", [])]))
    config.assign = AssignConfig(
        enabled=bool(ac.get("enabled", False)),
        mode=str(ac.get("mode", ASSIGN_FIXED)),
        period=str(ac.get("period", PERIOD_WEEK)),
        roles=roles or AssignConfig().roles,
    )
    if config.assign.mode not in (ASSIGN_FIXED, ASSIGN_ROTATE):
        config.assign.mode = ASSIGN_FIXED
    if config.assign.period not in (PERIOD_DAY, PERIOD_WEEK):
        config.assign.period = PERIOD_WEEK

    style = str(data.get("prompt_style", PROMPT_OVERLAY))
    config.prompt_style = style if style in (PROMPT_OVERLAY, PROMPT_BANNER, PROMPT_WIDGET) else PROMPT_OVERLAY
    delivery = str(data.get("prompt_delivery", DELIVERY_POPUP))
    config.prompt_delivery = delivery if delivery in DELIVERY_MODES else DELIVERY_POPUP
    config.include_weekend = bool(data.get("include_weekend", False))
    config.big_title = str(data.get("big_title", config.big_title))
    config.big_text = str(data.get("big_text", config.big_text))
    config.small_text = str(data.get("small_text", config.small_text))
    config.anchor_date = str(data.get("anchor_date", "") or "")
    config.overrides = {}
    for day, ov in (data.get("overrides") or {}).items():
        if not isinstance(ov, dict):
            continue
        config.overrides[str(day)] = DayOverride(
            students=[str(x) for x in (ov.get("students") or [])],
            monitor=str(ov.get("monitor", "") or ""),
            assignments=[
                (str(a.get("name", "")), [str(x) for x in (a.get("people") or [])])
                for a in (ov.get("assignments") or [])
                if isinstance(a, dict)
            ],
            note=str(ov.get("note", "") or ""),
        )
    return config


# --------------------------------------------------------------------------- #
# 文本渲染（支持 **红字**）
# --------------------------------------------------------------------------- #
_RED_RE = re.compile(r"\*\*(.+?)\*\*", re.S)


def render_red_markup(text: str, color: str = "#E53935") -> str:
    """将 ``**文字**`` 渲染为红色加粗的 HTML。"""
    escaped = html.escape(text or "")
    return _RED_RE.sub(
        lambda m: f'<span style="color:{color};font-weight:700;">{m.group(1)}</span>', escaped
    )


def small_summary(day: DayDuty) -> str:
    """值日生小组件的简要正文。"""
    lines = ["、".join(s.label for s in day.students) or "（未安排）"]
    if day.monitor is not None:
        lines.append(f"班长：{day.monitor.label}")
    return "\n".join(lines)


def build_text(template: str, day: DayDuty) -> str:
    """用当天的值日信息填充自定义模板。"""
    students = "、".join(s.label for s in day.students) or "（未安排）"
    monitor = day.monitor.label if day.monitor else "（未安排）"
    assignments = "  ".join(
        f"{name}：{'、'.join(s.label for s in people) or '—'}" for name, people in day.assignments
    )
    values = defaultdict(
        str,
        {
            "students": students,
            "monitor": monitor,
            "assignments": assignments,
            "date": day.date.strftime("%Y-%m-%d"),
            "weekday": WEEKDAY_NAMES[day.date.weekday()],
        },
    )
    try:
        return (template or "").format_map(values)
    except Exception as e:  # 模板异常时退回原文
        logger.warning(f"值日文案模板解析失败: {e}")
        return template or ""


# --------------------------------------------------------------------------- #
# 管理器
# --------------------------------------------------------------------------- #
class DutyManager:
    def __init__(self, config_path: Path) -> None:
        self.config_path = Path(config_path)
        self.config = DutyConfig()
        self.load()

    # -- 配置 ------------------------------------------------------------- #
    def load(self) -> None:
        try:
            if self.config_path.exists():
                with open(self.config_path, encoding="utf-8") as f:
                    self.config = config_from_dict(json.load(f))
            else:
                self.save()
        except Exception as e:
            logger.error(f"加载值日配置失败: {e}")
            self.config = DutyConfig()

    def save(self) -> None:
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config_to_dict(self.config), f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"保存值日配置失败: {e}")

    # -- 名单 ------------------------------------------------------------- #
    def student_by_key(self, key: str) -> Optional[Student]:
        if not key:
            return None
        key = key.strip()
        for s in self.config.students:
            if s.key == key:
                return s
        return None

    def labels_for(self, keys: List[str]) -> List[Student]:
        return [s for s in (self.student_by_key(k) for k in keys) if s is not None]

    def ordered_students(self) -> List[Student]:
        students = list(self.config.students)
        if self.config.id_rotation.order == "id":
            def sort_key(s: Student) -> Tuple[int, Any]:
                digits = "".join(ch for ch in s.id if ch.isdigit())
                if digits:
                    return (0, int(digits))
                return (1, s.name)
            try:
                students.sort(key=sort_key)
            except Exception:
                pass
        return students

    def add_student(self, name: str, sid: str = "") -> bool:
        name = (name or "").strip()
        sid = (sid or "").strip()
        if not name:
            return False
        if self.student_by_key(sid or name) is not None:
            return False
        self.config.students.append(Student(name=name, id=sid))
        self.save()
        return True

    def update_student(self, old_key: str, name: str, sid: str = "") -> bool:
        student = self.student_by_key(old_key)
        if student is None:
            return False
        student.name = (name or student.name).strip()
        student.id = (sid or "").strip()
        self.save()
        return True

    def remove_student(self, key: str) -> bool:
        student = self.student_by_key(key)
        if student is None:
            return False
        self.config.students.remove(student)
        # 同步清理排班引用
        self.config.fixed = {
            d: [k for k in keys if k != key] for d, keys in self.config.fixed.items()
        }
        self.config.monitor.weekly = [k for k in self.config.monitor.weekly if k != key]
        self.config.monitor.daily = {d: k for d, k in self.config.monitor.daily.items() if k != key}
        for role in self.config.assign.roles:
            role.people = [k for k in role.people if k != key]
        self.save()
        return True

    def clear_students(self) -> None:
        self.config.students = []
        self.config.fixed = {}
        self.config.monitor.weekly = []
        self.config.monitor.daily = {}
        for role in self.config.assign.roles:
            role.people = []
        self.save()

    # -- 导入 / 导出 ------------------------------------------------------ #
    def import_csv(self, path: str) -> int:
        """CSV 每行 ``姓名,学号``（可含表头）。返回导入数量。"""
        count = 0
        try:
            with open(path, encoding="utf-8-sig", newline="") as f:
                for row in csv.reader(f):
                    if not row:
                        continue
                    name = (row[0] or "").strip()
                    sid = (row[1] if len(row) > 1 else "").strip()
                    if not name:
                        continue
                    if name.lower() in ("name", "姓名"):  # 跳过表头
                        continue
                    if self.student_by_key(sid or name) is None:
                        self.config.students.append(Student(name=name, id=sid))
                        count += 1
            self.save()
        except Exception as e:
            logger.error(f"导入 CSV 值日名单失败: {e}")
        return count

    def export_csv(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["姓名", "学号"])
                for s in self.config.students:
                    writer.writerow([s.name, s.id])
            return True
        except Exception as e:
            logger.error(f"导出 CSV 值日名单失败: {e}")
            return False

    def import_json(self, path: str) -> int:
        count = 0
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("students", data) if isinstance(data, dict) else data
            for item in items or []:
                student = _student_from(item)
                if not student.name:
                    continue
                if self.student_by_key(student.key) is None:
                    self.config.students.append(student)
                    count += 1
            self.save()
        except Exception as e:
            logger.error(f"导入 JSON 值日名单失败: {e}")
        return count

    def export_json(self, path: str) -> bool:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {"students": [_student_to(s) for s in self.config.students]},
                    f,
                    ensure_ascii=False,
                    indent=4,
                )
            return True
        except Exception as e:
            logger.error(f"导出 JSON 值日名单失败: {e}")
            return False

    # -- 特别安排 ---------------------------------------------------------- #
    def set_override(self, day: str, override: DayOverride) -> None:
        """设置某天（YYYY-MM-DD）的特别安排。"""
        self.config.overrides[str(day)] = override
        self.save()

    def remove_override(self, day: str) -> None:
        self.config.overrides.pop(str(day), None)
        self.save()

    def list_overrides(self) -> List[str]:
        return sorted(self.config.overrides)

    # -- 排班引擎 --------------------------------------------------------- #
    def _anchor(self) -> dt.date:
        raw = (self.config.anchor_date or "").strip()
        if raw:
            try:
                return dt.date.fromisoformat(raw)
            except ValueError:
                pass
        return dt.date.today()

    @staticmethod
    def _monday(d: dt.date) -> dt.date:
        return d - dt.timedelta(days=d.weekday())

    def _week_index(self, d: dt.date) -> int:
        return (self._monday(d) - self._monday(self._anchor())).days // 7

    def _school_day_index(self, d: dt.date) -> int:
        weeks = (self._monday(d) - self._monday(self._anchor())).days // 7
        return weeks * len(active_weekdays(self.config.include_weekend)) + d.weekday()

    def _ordered_index_of(self, key: str, students: List[Student]) -> Optional[int]:
        for i, s in enumerate(students):
            if s.key == key:
                return i
        return None

    def _id_rotation_students(self, d: dt.date) -> List[Student]:
        students = self.ordered_students()
        total = len(students)
        if total == 0:
            return []
        rule = self.config.id_rotation
        count = max(0, min(rule.count_for(d.weekday()), total))
        if count == 0:
            return []
        base = 0
        if rule.start_key:
            idx = self._ordered_index_of(rule.start_key.strip(), students)
            if idx is not None:
                base = idx
        if rule.weekly_reset:
            start = (base + d.weekday() * count) % total
        else:
            start = (base + self._school_day_index(d) * count) % total
        return [students[(start + i) % total] for i in range(count)]

    def _fixed_students(self, d: dt.date) -> List[Student]:
        keys = self.config.fixed.get(str(d.weekday()), [])
        return self.labels_for(keys)

    def _monitor(self, d: dt.date) -> Optional[Student]:
        mc = self.config.monitor
        if not mc.enabled:
            return None
        if mc.mode == MONITOR_DAILY:
            return self.student_by_key(mc.daily.get(str(d.weekday()), ""))
        if not mc.weekly:
            return None
        idx = self._week_index(d) % len(mc.weekly)
        return self.student_by_key(mc.weekly[idx])

    def _assignments(self, d: dt.date) -> List[Tuple[str, List[Student]]]:
        ac = self.config.assign
        if not ac.enabled or not ac.roles:
            return []
        if ac.mode == ASSIGN_FIXED:
            return [(role.name, self.labels_for(role.people)) for role in ac.roles]
        roster = self.ordered_students()
        roles = ac.roles
        role_count = len(roles)
        if not roster:
            return [(role.name, []) for role in roles]
        period = self._week_index(d) if ac.period == PERIOD_WEEK else self._school_day_index(d)
        block = max(1, (len(roster) + role_count - 1) // role_count)
        buckets: List[List[Student]] = [[] for _ in roles]
        for i, student in enumerate(roster):
            buckets[(i // block + period) % role_count].append(student)
        return [(roles[i].name, buckets[i]) for i in range(role_count)]

    def get_day(self, d: Optional[dt.date] = None) -> DayDuty:
        d = d or dt.date.today()
        day = DayDuty(date=d)
        override = self.config.overrides.get(d.isoformat())
        if override is not None:
            # 特别安排：完全覆盖当天的排班
            day.students = self.labels_for(override.students)
            day.monitor = (
                self.student_by_key(override.monitor)
                if override.monitor
                else self._monitor(d)
            )
            day.assignments = [
                (name, self.labels_for(people)) for name, people in override.assignments
            ]
            return day
        if d.weekday() in WEEKEND_DAYS and not self.config.include_weekend:
            day.is_weekend = True
            return day
        if self.config.mode == MODE_FIXED:
            day.students = self._fixed_students(d)
        else:
            day.students = self._id_rotation_students(d)
        day.monitor = self._monitor(d)
        day.assignments = self._assignments(d)
        return day

    def get_week(self, d: Optional[dt.date] = None) -> List[DayDuty]:
        """返回包含 ``d`` 的那一周（周一至周五）的值日安排。"""
        d = d or dt.date.today()
        monday = self._monday(d)
        return [self.get_day(monday + dt.timedelta(days=i)) for i in active_weekdays(self.config.include_weekend)]


_duty_manager: Optional[DutyManager] = None


def get_duty_manager() -> DutyManager:
    global _duty_manager
    if _duty_manager is None:
        from basic_dirs import CONFIG_HOME

        _duty_manager = DutyManager(CONFIG_HOME / "duty.json")
    return _duty_manager


def reset_duty_manager() -> None:
    """重新加载配置（设置保存后调用）。"""
    global _duty_manager
    if _duty_manager is not None:
        _duty_manager.load()
