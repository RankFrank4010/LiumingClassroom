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
class ChangeRules:
    """值日改班规则。"""

    carry_over_monitor: bool = True  # 值日班长被取消时，值日生自动顺延一人
    priority_missed: bool = True  # 被取消值日者后续优先补值（缺几次补几次）


@dataclass
class DayAdjustment:
    """某一天的值日改班记录：划掉 + 补值。"""

    struck: List[str] = field(default_factory=list)  # 被划掉的学生 key
    added: List[str] = field(default_factory=list)  # 补值学生 key（含休学用户）
    missed_delta: Dict[str, int] = field(default_factory=dict)  # 应用时对 missed 的增量（回滚用）


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
    holiday_aware: bool = True  # 根据节假日/调休自动调整排班
    change_rules: ChangeRules = field(default_factory=ChangeRules)
    suspended: List[str] = field(default_factory=list)  # 休学用户 key（名单中但不参与排班）
    adjustments: Dict[str, DayAdjustment] = field(default_factory=dict)  # 日期 -> 改班记录
    missed: Dict[str, int] = field(default_factory=dict)  # 学生 key -> 待优先补值次数
    missed_start: Dict[str, str] = field(default_factory=dict)  # 学生 key -> 最早缺值日期
    priority_served: Dict[str, List[str]] = field(default_factory=dict)  # 日期 -> 已消费优先的学生


@dataclass
class DayDuty:
    date: dt.date
    students: List[Student] = field(default_factory=list)
    monitor: Optional[Student] = None
    assignments: List[Tuple[str, List[Student]]] = field(default_factory=list)
    is_weekend: bool = False
    is_holiday: bool = False
    holiday_name: str = ""  # 节假日名称（如「国庆节」）


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
        "change_rules": asdict(config.change_rules),
        "suspended": list(config.suspended),
        "adjustments": {
            day: {
                "struck": list(adj.struck),
                "added": list(adj.added),
                "missed_delta": dict(adj.missed_delta),
            }
            for day, adj in config.adjustments.items()
        },
        "missed": dict(config.missed),
        "missed_start": dict(config.missed_start),
        "priority_served": {k: list(v) for k, v in config.priority_served.items()},
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
    cr = data.get("change_rules") or {}
    config.change_rules = ChangeRules(
        carry_over_monitor=bool(cr.get("carry_over_monitor", True)),
        priority_missed=bool(cr.get("priority_missed", True)),
    )
    config.suspended = [str(x) for x in (data.get("suspended") or [])]
    config.adjustments = {}
    for day, adj in (data.get("adjustments") or {}).items():
        if not isinstance(adj, dict):
            continue
        config.adjustments[str(day)] = DayAdjustment(
            struck=[str(x) for x in (adj.get("struck") or [])],
            added=[str(x) for x in (adj.get("added") or [])],
            missed_delta={str(k): int(v) for k, v in (adj.get("missed_delta") or {}).items()},
        )
    config.missed = {
        str(k): max(0, int(v)) for k, v in (data.get("missed") or {}).items()
    }
    config.missed_start = {
        str(k): str(v) for k, v in (data.get("missed_start") or {}).items()
    }
    config.priority_served = {
        str(k): [str(x) for x in v]
        for k, v in (data.get("priority_served") or {}).items()
        if isinstance(v, list)
    }
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

    # -- 值日改班 ---------------------------------------------------------- #
    def is_suspended(self, key: str) -> bool:
        return bool(key) and key in self.config.suspended

    def set_suspended(self, keys: List[str]) -> None:
        self.config.suspended = [str(k) for k in keys if str(k).strip()]
        self.save()

    def apply_adjustment(self, day: str, struck: List[str], added: List[str]) -> DayAdjustment:
        """应用某天的值日改班：记录划掉与补值，并为被取消者累计待补值次数。"""
        struck = [k for k in struck if k]
        added = [k for k in added if k]
        old = self.config.adjustments.get(str(day))
        missed_delta: Dict[str, int] = {}
        if self.config.change_rules.priority_missed:
            old_delta = old.missed_delta if old else {}
            for k in struck:
                if k not in old_delta:  # 已累计过的不重复计
                    missed_delta[k] = 1
        adj = DayAdjustment(struck=struck, added=added, missed_delta=missed_delta)
        self.config.adjustments[str(day)] = adj
        for k, delta in missed_delta.items():
            self.config.missed[k] = self.config.missed.get(k, 0) + delta
            self.config.missed_start.setdefault(k, str(day))  # 优先补值从次日开始
        self.save()
        return adj

    def get_adjustment(self, day: str) -> Optional[DayAdjustment]:
        return self.config.adjustments.get(str(day))

    def remove_adjustment(self, day: str) -> bool:
        """回滚某天的改班记录，并撤销当日对待补值次数的影响。"""
        adj = self.config.adjustments.pop(str(day), None)
        if adj is None:
            return False
        for k, delta in adj.missed_delta.items():
            remain = self.config.missed.get(k, 0) - delta
            if remain > 0:
                self.config.missed[k] = remain
            else:
                self.config.missed.pop(k, None)
                self.config.missed_start.pop(k, None)
        self.config.priority_served.pop(str(day), None)
        self.save()
        return True

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

    # -- 节假日感知 -------------------------------------------------------- #
    def _day_info(self, d: dt.date):
        """节假日信息；关闭 holiday_aware 时返回普通工作日。"""
        if not self.config.holiday_aware:
            from holiday import DayInfo, KIND_WORKDAY

            return DayInfo(kind=KIND_WORKDAY)
        try:
            from holiday import get_day_info

            return get_day_info(d)
        except Exception as e:
            logger.warning(f"节假日查询失败，按普通工作日处理: {e}")
            from holiday import DayInfo, KIND_WORKDAY

            return DayInfo(kind=KIND_WORKDAY)

    def _effective_weekday(self, d: dt.date) -> int:
        """该日期排班时使用的周几：补班日映射到其对应工作日的周几。"""
        info = self._day_info(d)
        if info.is_makeup and info.effective_weekday is not None:
            return info.effective_weekday
        return d.weekday()

    def _is_school_day(self, d: dt.date) -> bool:
        """该日期是否到校上课（用于轮换顺延：假期不计入、补班日计入）。"""
        if self.config.overrides.get(d.isoformat()) is not None:
            return True  # 特别安排视同到校
        info = self._day_info(d)
        if info.is_holiday:
            return False
        if info.is_makeup:
            return True
        if d.weekday() in WEEKEND_DAYS and not self.config.include_weekend:
            return False
        return True

    def _school_day_index(self, d: dt.date) -> int:
        """从锚点起累计的「实际上课日」序号（假期跳过、补班日计入，轮换顺延）。"""
        anchor = self._anchor()
        if d < anchor:
            # 锚点之前的日期退回原公式（轮换不回溯历史）
            weeks = (self._monday(d) - self._monday(anchor)).days // 7
            return weeks * len(active_weekdays(self.config.include_weekend)) + d.weekday()
        count = 0
        cur = anchor
        while cur <= d:
            if self._is_school_day(cur):
                count += 1
            cur += dt.timedelta(days=1)
        return count - 1  # 锚点当天序号为 0，与原公式一致

    def _ordered_index_of(self, key: str, students: List[Student]) -> Optional[int]:
        for i, s in enumerate(students):
            if s.key == key:
                return i
        return None

    def _rotation_pool(self) -> List[Student]:
        """参与轮换的学生（按排班顺序，剔除休学用户）。"""
        return [s for s in self.ordered_students() if not self.is_suspended(s.key)]

    def _priority_students(self, d: dt.date, capacity: int) -> List[Student]:
        """当日应优先补值的学生（缺值日几次就几次优先分配），并按天消费优先次数。"""
        if capacity <= 0 or not self.config.change_rules.priority_missed:
            return []
        day_key = d.isoformat()
        served = self.config.priority_served.get(day_key)
        if served is not None:
            # 当天已消费过优先：固定返回当日名单，保证幂等
            pool = self._rotation_pool()
            seen = set()
            result = []
            for k in served:
                for s in pool:
                    if s.key == k and k not in seen:
                        seen.add(k)
                        result.append(s)
            return result
        # 仅补缺值日之后的值日（缺值日当天不算）
        pending = [
            k
            for k, v in self.config.missed.items()
            if v > 0 and self.config.missed_start.get(k, "") < day_key
        ]
        if not pending:
            return []
        pool = self._rotation_pool()
        candidates = [s for s in pool if s.key in pending]
        if not candidates:
            return []
        if d <= dt.date.today():
            # 到达当天首次计算：消费一次优先名额
            served = [s.key for s in candidates[:capacity]]
            self.config.priority_served[day_key] = served
            for k in served:
                remain = self.config.missed.get(k, 0) - 1
                if remain > 0:
                    self.config.missed[k] = remain
                else:
                    self.config.missed.pop(k, None)
            self.save()
        keys = list(served or [])
        picked = [s for k in keys for s in pool if s.key == k]
        # 去重
        seen = set()
        result = []
        for s in picked:
            if s.key not in seen:
                seen.add(s.key)
                result.append(s)
        return result

    def _carry_students(self, d: dt.date, n: int, exclude_keys: set) -> List[Student]:
        """从当日排班窗口之后顺延 n 名学生（跳过被排除者与休学用户）。"""
        if n <= 0:
            return []
        pool = self._rotation_pool()
        if not pool:
            return []
        if self.config.mode == MODE_FIXED:
            base = self._fixed_students(d)
        else:
            base = self._id_rotation_students(d)
        base = [s for s in base if s.key not in exclude_keys]
        start = 0
        if base:
            idx = self._ordered_index_of(base[-1].key, pool)
            if idx is not None:
                start = idx + 1
        out: List[Student] = []
        i = start
        guard = 0
        while len(out) < n and guard < len(pool) * 2:
            s = pool[i % len(pool)]
            if s.key not in exclude_keys and all(o.key != s.key for o in out):
                out.append(s)
            i += 1
            guard += 1
        return out

    def _id_rotation_students(self, d: dt.date) -> List[Student]:
        students = self._rotation_pool()
        total = len(students)
        if total == 0:
            return []
        rule = self.config.id_rotation
        weekday = self._effective_weekday(d)
        count = max(0, min(rule.count_for(weekday), total))
        if count == 0:
            return []
        base = 0
        if rule.start_key:
            idx = self._ordered_index_of(rule.start_key.strip(), students)
            if idx is not None:
                base = idx
        if rule.weekly_reset:
            start = (base + weekday * count) % total
        else:
            start = (base + self._school_day_index(d) * count) % total
        return [students[(start + i) % total] for i in range(count)]

    def _fixed_students(self, d: dt.date) -> List[Student]:
        keys = [
            k
            for k in self.config.fixed.get(str(self._effective_weekday(d)), [])
            if not self.is_suspended(k)
        ]
        return self.labels_for(keys)

    def _monitor(self, d: dt.date) -> Optional[Student]:
        mc = self.config.monitor
        if not mc.enabled:
            return None
        if mc.mode == MONITOR_DAILY:
            return self.student_by_key(mc.daily.get(str(self._effective_weekday(d)), ""))
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

    def _apply_day_changes(self, d: dt.date, day: DayDuty) -> None:
        """把优先补值与当日改班记录应用到位日结果上。"""
        # 1) 优先补值：缺值日者排在当日名单最前（占用当日名额）
        count_for_day = max(0, len(day.students))
        priority = self._priority_students(d, count_for_day)
        if priority:
            existing = {s.key for s in day.students}
            merged = [s for s in priority if s.key not in existing]
            rest = day.students[: max(0, count_for_day - len(merged))]
            day.students = merged + rest
        # 2) 当日改班记录：划掉 + 顺延 + 补值
        adj = self.config.adjustments.get(d.isoformat())
        if adj is None:
            return
        struck_set = set(adj.struck)
        if struck_set:
            day.students = [s for s in day.students if s.key not in struck_set]
            extra = 0
            if (
                self.config.change_rules.carry_over_monitor
                and day.monitor is not None
                and day.monitor.key in struck_set
            ):
                extra = 1  # 值日班长被取消：值日生自动顺延一人
            existing = {s.key for s in day.students} | struck_set | set(adj.added)
            day.students.extend(self._carry_students(d, len(adj.struck) + extra, existing))
        if adj.added:
            existing = {s.key for s in day.students}
            for k in adj.added:
                s = self.student_by_key(k)
                if s is not None and s.key not in existing:
                    day.students.append(s)

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
            self._apply_day_changes(d, day)
            return day
        if self.config.holiday_aware:
            info = self._day_info(d)
            if info.is_holiday:
                day.is_holiday = True
                day.holiday_name = info.name
                return day  # 法定节假日：无人值日，轮换已顺延
            if info.is_makeup:
                pass  # 调休补班日：正常排班（按对应周几执行），继续往下走
            elif d.weekday() in WEEKEND_DAYS and not self.config.include_weekend:
                day.is_weekend = True
                return day
        elif d.weekday() in WEEKEND_DAYS and not self.config.include_weekend:
            day.is_weekend = True
            return day
        if self.config.mode == MODE_FIXED:
            day.students = self._fixed_students(d)
        else:
            day.students = self._id_rotation_students(d)
        day.monitor = self._monitor(d)
        day.assignments = self._assignments(d)
        self._apply_day_changes(d, day)
        return day

    def get_week(self, d: Optional[dt.date] = None) -> List[DayDuty]:
        """返回包含 ``d`` 的那一周（周一至周五）的值日安排。"""
        d = d or dt.date.today()
        monday = self._monday(d)
        return [self.get_day(monday + dt.timedelta(days=i)) for i in active_weekdays(self.config.include_weekend)]

    def get_base_day(self, d: Optional[dt.date] = None) -> DayDuty:
        """计算未经改班/优先补值修饰的当日排班（用于改班界面展示原始名单）。"""
        import copy

        d = d or dt.date.today()
        config_backup = self.config
        try:
            self.config = copy.deepcopy(self.config)
            self.config.adjustments = {}
            self.config.missed = {}
            self.config.priority_served = {}
            day = DayDuty(date=d)
            override = self.config.overrides.get(d.isoformat())
            if override is not None:
                day.students = self.labels_for(override.students)
                day.monitor = (
                    self.student_by_key(override.monitor) if override.monitor else self._monitor(d)
                )
                day.assignments = [
                    (name, self.labels_for(people)) for name, people in override.assignments
                ]
                return day
            if self.config.holiday_aware:
                info = self._day_info(d)
                if info.is_holiday:
                    day.is_holiday = True
                    day.holiday_name = info.name
                    return day
                if info.is_makeup:
                    pass
                elif d.weekday() in WEEKEND_DAYS and not self.config.include_weekend:
                    day.is_weekend = True
                    return day
            elif d.weekday() in WEEKEND_DAYS and not self.config.include_weekend:
                day.is_weekend = True
                return day
            if self.config.mode == MODE_FIXED:
                day.students = self._fixed_students(d)
            else:
                day.students = self._id_rotation_students(d)
            day.monitor = self._monitor(d)
            day.assignments = self._assignments(d)
            return day
        finally:
            self.config = config_backup


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
