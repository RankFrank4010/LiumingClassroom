"""值日改班逻辑测试（无 PyQt 依赖）。"""
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from duty import DutyManager, DutyConfig, Student, IdRotation, MonitorConfig, DayDuty

tmp = Path(tempfile.mkdtemp()) / "duty.json"
mgr = DutyManager(tmp)
mgr.config = DutyConfig(
    enabled=True,
    students=[Student(name=f"学生{i:02d}", id=str(101 + i)) for i in range(10)],
    mode="id_rotation",
    id_rotation=IdRotation(count_per_day=3, start_key="101"),
    monitor=MonitorConfig(enabled=True, mode="weekly", weekly=["101"]),
    anchor_date="2026-09-21",  # 周一
)
mgr.save()

today = dt.date.today()
today = today - dt.timedelta(days=today.weekday())  # 用本周周一测试（今天可能是周末）
key = lambda i: str(101 + i)
name = lambda s: s.name

day = mgr.get_day(today)
base = [s.key for s in day.students]
print("基础排班:", base, "班长:", day.monitor.key if day.monitor else None)
assert len(base) == 3
assert day.monitor.key == "101"

# 1) 划掉两人（含班长）→ 顺延 2+1
mgr.apply_adjustment(today.isoformat(), struck=[base[0], base[1]], added=[])
adj_day = mgr.get_day(today)
after = [s.key for s in adj_day.students]
print("改班后:", after)
assert base[0] not in after and base[1] not in after
assert len(after) == 4  # 3 - 2 + 2(补齐) + 1(班长顺延规则) = 4
assert set(after).isdisjoint({base[0], base[1]})
# 缺席者累计待补值
assert mgr.config.missed.get(base[0]) == 1 and mgr.config.missed.get(base[1]) == 1

# 2) 回滚 → 恢复原样，missed 清零
assert mgr.remove_adjustment(today.isoformat())
back = mgr.get_day(today)
assert [s.key for s in back.students] == base
assert not mgr.config.missed
print("回滚 OK")

# 3) 再次改班 + 次日优先补值
mgr.apply_adjustment(today.isoformat(), struck=[base[0]], added=[])
next_day = mgr.get_day(today + dt.timedelta(days=1))
nkeys = [s.key for s in next_day.students]
print("次日:", nkeys, "missed:", mgr.config.missed)
assert nkeys[0] == base[0], "缺席者应优先排在次日最前"
assert mgr.config.missed.get(base[0], 0) == 0, "优先名额应被消费"
# 重复 get_day 幂等
assert [s.key for s in mgr.get_day(today + dt.timedelta(days=1)).students] == nkeys

# 4) 休学用户不参与排班，补值后仅当日出现
mgr.set_suspended([key(9)])
day2 = mgr.get_day(today)
assert key(9) not in [s.key for s in day2.students]
# 用回滚前的 today 改班来补值
mgr.apply_adjustment(today.isoformat(), struck=[], added=[key(9)])
day3 = mgr.get_day(today)
assert key(9) in [s.key for s in day3.students], "补值应让休学用户当日参与"
# 次日仍不参与
assert key(9) not in [s.key for s in mgr.get_day(today + dt.timedelta(days=1)).students]
print("休学与补值 OK")

# 5) 序列化往返
data = json.loads(json.dumps(json.load(open(tmp, encoding="utf-8"))))
assert "suspended" in data and "adjustments" in data and "missed" in data
from duty import config_from_dict

cfg2 = config_from_dict(data)
assert cfg2.suspended == [key(9)]
assert cfg2.adjustments[today.isoformat()].added == [key(9)]
print("序列化 OK")

# 6) get_base_day 不含改班影响
base_day = mgr.get_base_day(today)
assert key(9) not in [s.key for s in base_day.students]
assert [s.key for s in base_day.students] == base
print("get_base_day OK")

print("\n全部测试通过 ✔")
