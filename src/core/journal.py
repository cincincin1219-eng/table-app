"""飯紀錄：每一餐的紀錄、存取格式與每月統計。與介面無關，可單獨測試。"""
from __future__ import annotations

import json
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime

WALK_METERS_PER_MIN = 75          # 與 filters.py 相同的步行速度
WEEKDAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]


@dataclass
class MealEntry:
    at: str                         # ISO 時間，例如 2026-11-19T12:10:00
    name: str
    area: str = ""
    restaurant_id: str = ""         # 手動新增的店沒有
    walk_minutes: int = 0
    surprise: bool = False          # 是否來自「驚喜一下」
    has_photo: bool = False
    note: str = ""
    tags: list = field(default_factory=list)    # 例如 ["一人食", "深夜"]
    price: int = 0                  # 這一餐大約花多少（0 = 沒填）
    party: int = 0                  # 幾個人吃（0 = 沒填）
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def when(self) -> datetime:
        return datetime.fromisoformat(self.at)


def new_entry(now: datetime, name: str, **kw) -> MealEntry:
    return MealEntry(at=now.replace(tzinfo=None, microsecond=0).isoformat(), name=name, **kw)


def dumps(entries: list[MealEntry]) -> str:
    return json.dumps([asdict(e) for e in entries], ensure_ascii=False)


def loads(text: str | None) -> list[MealEntry]:
    if not text:
        return []
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return []
    known = set(MealEntry.__dataclass_fields__)
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and item.get("at") and item.get("name"):
            out.append(MealEntry(**{k: v for k, v in item.items() if k in known}))
    return out


def sort_newest_first(entries: list[MealEntry]) -> list[MealEntry]:
    return sorted(entries, key=lambda e: e.at, reverse=True)


def in_month(entries: list[MealEntry], year: int, month: int) -> list[MealEntry]:
    return [e for e in entries if e.when.year == year and e.when.month == month]


def months_with_entries(entries: list[MealEntry]) -> list[tuple[int, int]]:
    return sorted({(e.when.year, e.when.month) for e in entries}, reverse=True)


def recent_restaurant_ids(entries: list[MealEntry], now: datetime, days: int = 3) -> set[str]:
    """最近幾天吃過的店，推薦時會降低排名（C6）。"""
    cutoff = now.replace(tzinfo=None).timestamp() - days * 86400
    return {e.restaurant_id for e in entries if e.restaurant_id and e.when.timestamp() >= cutoff}


def monthly_stats(entries: list[MealEntry], year: int, month: int) -> dict:
    month_entries = in_month(entries, year, month)
    n = len(month_entries)
    names = Counter(e.name for e in month_entries)
    areas = Counter(e.area for e in month_entries if e.area)
    weekdays = Counter(e.when.weekday() for e in month_entries)
    hours = [e.when.hour for e in month_entries]

    favorite = names.most_common(1)[0] if names else ("", 0)
    top_area = areas.most_common(1)[0] if areas else ("", 0)
    meters = sum(e.walk_minutes for e in month_entries) * WALK_METERS_PER_MIN * 2  # 來回

    return {
        "year": year,
        "month": month,
        "meals": n,
        "places": len(names),
        "favorite_name": favorite[0],
        "favorite_count": favorite[1],
        "top_area": top_area[0],
        "top_area_share": round(top_area[1] / n * 100) if n and top_area[1] else 0,
        "km": round(meters / 1000, 1),
        "surprises": sum(1 for e in month_entries if e.surprise),
        "photos": sum(1 for e in month_entries if e.has_photo),
        "days_logged": len({e.when.date() for e in month_entries}),
        "top3": names.most_common(3),
        "busiest_weekday": WEEKDAYS[weekdays.most_common(1)[0][0]] if weekdays else "",
        "late_night": sum(1 for h in hours if h >= 21 or h < 4),
    }
