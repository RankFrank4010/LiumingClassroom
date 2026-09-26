"""节假日/调休数据模块（timor.tech 免费节假日 API + 本地缓存）。

提供按日期查询「工作日 / 周末 / 法定节假日 / 调休补班日」的能力，
并为调休补班日推导其对应的工作日星期（用于值日排班按对应周几执行）。

- 数据源：https://timor.tech/api/holiday/year/{year}（含法定节假日与调休补班）
- 缓存：CONFIG_HOME / holiday_cache.json（联网成功后写入，离线回退读缓存）
- 该模块不依赖 PyQt，可独立进行逻辑测试。
"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

try:  # 允许在没有第三方依赖时进行纯逻辑测试
    from loguru import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("holiday")

API_URL = "https://timor.tech/api/holiday/year/{year}"
FETCH_TIMEOUT = 8
FETCH_RETRY_INTERVAL = 6 * 3600  # 拉取失败后的重试间隔（秒）

# 日期类型
KIND_WORKDAY = "workday"  # 正常工作日（含工作日周末补班已换算）
KIND_WEEKEND = "weekend"  # 普通周末
KIND_HOLIDAY = "holiday"  # 法定节假日
KIND_MAKEUP = "makeup"  # 调休补班日（周末上班）


@dataclass
class DayInfo:
    """某一天的节假日信息。"""

    kind: str
    name: str = ""
    # 仅补班日有意义：该补班日按周几（0=周一）的课务/排班执行；None 表示无法推导
    effective_weekday: Optional[int] = None

    @property
    def is_holiday(self) -> bool:
        return self.kind == KIND_HOLIDAY

    @property
    def is_makeup(self) -> bool:
        return self.kind == KIND_MAKEUP


# --------------------------------------------------------------------------- #
# 缓存
# --------------------------------------------------------------------------- #
_year_cache: Dict[str, Dict[str, dict]] = {}  # "2026" -> {"01-01": entry}
_fetch_failed_at: Dict[str, float] = {}  # "2026" -> 上次拉取失败时间戳
_loaded = False


def _cache_path() -> Path:
    from basic_dirs import CONFIG_HOME

    return CONFIG_HOME / "holiday_cache.json"


def _load_cache() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        path = _cache_path()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            years = data.get("years", {})
            if isinstance(years, dict):
                _year_cache.update({str(k): v.get("days", {}) for k, v in years.items()})
    except Exception as e:  # noqa: BLE001
        logger.warning(f"节假日缓存读取失败: {e}")


def _save_cache() -> None:
    try:
        now = time.time()
        payload = {
            "years": {
                year: {"fetched_at": now, "days": days} for year, days in _year_cache.items()
            }
        }
        _cache_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=None), encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"节假日缓存写入失败: {e}")


def _parse_entry(entry: dict) -> Tuple[bool, bool, str]:
    """解析单条年份数据，返回 (是特殊日, 是假期?, 名称)。"""
    name = str(entry.get("name", "") or "")
    holiday_flag = entry.get("holiday")
    if holiday_flag is True:
        return True, True, name
    if holiday_flag is False:
        return True, False, name
    # 回退：type.type / status（0 工作日 1 周末 2 节假日 3 补班）
    for key in ("type", "status"):
        raw = entry.get(key)
        if isinstance(raw, dict):
            raw = raw.get("type")
        if raw is None:
            continue
        try:
            code = int(raw)
        except (TypeError, ValueError):
            continue
        if code == 2:
            return True, True, name
        if code == 3:
            return True, False, name
    return False, False, name


def _fetch_year(year: int) -> Optional[Dict[str, dict]]:
    """拉取某年节假日数据；成功返回 {"MM-DD": entry}，失败返回 None。"""
    try:
        import requests

        resp = requests.get(API_URL.format(year=year), timeout=FETCH_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            logger.warning(f"节假日 API 返回异常 code={payload.get('code')}")
            return None
        data = payload.get("data") or {}
        days: Dict[str, dict] = {}
        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            date_text = str(entry.get("date") or f"{year}-{key}")
            try:
                d = dt.date.fromisoformat(date_text)
            except ValueError:
                continue
            special, is_holiday, name = _parse_entry(entry)
            if special:
                days[d.strftime("%m-%d")] = {"holiday": is_holiday, "name": name}
        return days
    except Exception as e:  # noqa: BLE001
        logger.warning(f"节假日数据拉取失败（{year}）: {e}")
        return None


def _year_days(year: int) -> Dict[str, dict]:
    """获取某年的特殊日期表（含网络拉取与失败重试节流）。"""
    _load_cache()
    key = str(year)
    if key in _year_cache:
        return _year_cache[key]
    now = time.time()
    if now - _fetch_failed_at.get(key, 0) < FETCH_RETRY_INTERVAL:
        return {}
    days = _fetch_year(year)
    if days is not None:
        _year_cache[key] = days
        _save_cache()
        _fetch_failed_at.pop(key, None)
    else:
        _fetch_failed_at[key] = now
    return _year_cache.get(key, {})


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
def _holiday_blocks(days: Dict[str, dict], year: int) -> list:
    """把某年的假期聚合成连续区块，返回 [(start_date, end_date, ...)]。"""
    holiday_dates = sorted(
        dt.date(year, int(k[:2]), int(k[3:5]))
        for k, v in days.items()
        if v.get("holiday")
    )
    blocks: list = []
    for d in holiday_dates:
        if blocks and (d - blocks[-1][1]).days <= 1:
            blocks[-1][1] = d
        else:
            blocks.append([d, d])
    return blocks


def _makeup_weekday(d: dt.date, days: Dict[str, dict], year: int) -> Optional[int]:
    """推导补班日对应的周几。

    约定：补班日若紧邻某个连续假期区块（前/后 4 天内），
    - 补班日在区块之前 → 按区块内被假期覆盖的第一个工作日（周一~周五）执行；
    - 补班日在区块之后 → 按区块内最后一个工作日执行。
    推导不出则返回 None（按普通工作日处理）。
    """
    for start, end in _holiday_blocks(days, year):
        if start <= d <= end:
            continue
        before = dt.timedelta(0) <= (start - d) <= dt.timedelta(days=4)
        after = dt.timedelta(0) <= (d - end) <= dt.timedelta(days=4)
        if not before and not after:
            continue
        weekdays = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        weekdays = [x for x in weekdays if x.weekday() <= 4]
        if not weekdays:
            continue
        return weekdays[0].weekday() if before else weekdays[-1].weekday()
    return None


def get_day_info(d: dt.date) -> DayInfo:
    """查询某天的节假日信息（带本地缓存与离线回退）。"""
    days = _year_days(d.year)
    entry = days.get(d.strftime("%m-%d"))
    if entry is not None:
        if entry.get("holiday"):
            return DayInfo(kind=KIND_HOLIDAY, name=str(entry.get("name", "") or ""))
        eff = _makeup_weekday(d, days, d.year)
        return DayInfo(kind=KIND_MAKEUP, name=str(entry.get("name", "") or ""), effective_weekday=eff)
    if d.weekday() >= 5:
        return DayInfo(kind=KIND_WEEKEND)
    return DayInfo(kind=KIND_WORKDAY)


def is_school_off(d: dt.date) -> bool:
    """某天是否放假（法定节假日或普通周末）。"""
    info = get_day_info(d)
    return info.is_holiday or info.kind == KIND_WEEKEND


def reload_cache() -> None:
    """清空内存缓存（测试或手动刷新用）。"""
    global _loaded
    _year_cache.clear()
    _fetch_failed_at.clear()
    _loaded = False
