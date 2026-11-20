"""C2 營業中過濾、C3 飲食標籤過濾、步行時間、人潮提示。"""
from __future__ import annotations

import math
from datetime import datetime

from .models import DAYS, Building, Query, Restaurant

WALK_METERS_PER_MIN = 75      # 一般步行速度
DETOUR_FACTOR = 1.3           # 直線距離換成實際路線的繞路係數
PEAK_WINDOWS = [(11 * 60 + 50, 12 * 60 + 40), (17 * 60 + 30, 18 * 60 + 30)]


def walking_minutes(b: Building, r: Restaurant) -> int:
    """用 haversine 直線距離 × 繞路係數，換算步行分鐘。"""
    R = 6_371_000
    p1, p2 = math.radians(b.lat), math.radians(r.lat)
    dp = p2 - p1
    dl = math.radians(r.lng - b.lng)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    meters = 2 * R * math.asin(math.sqrt(a)) * DETOUR_FACTOR
    return max(1, math.ceil(meters / WALK_METERS_PER_MIN))


def minutes_until_close(r: Restaurant, now: datetime) -> int | None:
    """營業中回傳距離打烊還有幾分鐘；沒開回傳 None。會處理跨夜營業。"""
    day = DAYS[now.weekday()]
    yesterday = DAYS[(now.weekday() - 1) % 7]
    m = now.hour * 60 + now.minute
    for start, end in r.hours.get(day, []):
        if start <= m < end:
            return end - m
    # 昨天開到今天凌晨的時段
    for start, end in r.hours.get(yesterday, []):
        if end > 1440 and m + 1440 < end:
            return end - (m + 1440)
    return None


def passes_diet(r: Restaurant, q: Query) -> bool:
    return q.required_tags <= r.tags and not (q.avoid_allergens & r.allergens)


def crowd_hint(r: Restaurant, now: datetime) -> str:
    m = now.hour * 60 + now.minute
    in_peak = any(s <= m < e for s, e in PEAK_WINDOWS)
    if r.popular and in_peak:
        return "尖峰時段，可能要排隊"
    if in_peak:
        return "尖峰時段，人可能稍多"
    return "目前應該不用排隊"
