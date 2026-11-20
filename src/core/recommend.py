"""C1 條件式推薦：先過濾、再評分，回傳前 k 名與推薦理由。"""
from __future__ import annotations

import random
from collections import Counter
from datetime import datetime

from .filters import crowd_hint, minutes_until_close, passes_diet, walking_minutes
from .models import Building, Query, Recommendation, Restaurant

EAT_MINUTES_ALONE = 25
EAT_MINUTES_GROUP = 40
ORDER_BEFORE_CLOSE = 15   # 抵達時距離打烊至少要剩幾分鐘


def _eat_minutes(q: Query) -> int:
    return EAT_MINUTES_ALONE if q.party_size == 1 else EAT_MINUTES_GROUP


def _check(r: Restaurant, b: Building, q: Query, now: datetime):
    """回傳 (是否通過, 被淘汰原因, 步行分鐘, 剩餘營業分鐘)。"""
    if not passes_diet(r, q):
        return False, "飲食限制", 0, 0
    left = minutes_until_close(r, now)
    if left is None:
        return False, "現在沒開", 0, 0
    walk = walking_minutes(b, r)
    if left < walk + ORDER_BEFORE_CLOSE:
        return False, "走到時快打烊", walk, left
    if walk * 2 + _eat_minutes(q) > q.minutes_available:
        return False, "時間不夠", walk, left
    if r.price > 0 and r.price > q.budget:          # 價格 0 = 還沒填，先不篩
        return False, "超出預算", walk, left
    if r.seats < q.party_size:
        return False, "座位不夠", walk, left
    return True, "", walk, left


def _score(r: Restaurant, walk: int, left: int, q: Query, now: datetime) -> tuple[float, list[str]]:
    reasons = []
    max_walk = max(1, (q.minutes_available - _eat_minutes(q)) // 2)
    score = 40 * (1 - walk / max_walk)                # 越近越好
    reasons.append(f"步行約 {walk} 分鐘")

    if r.price > 0:
        score += 20 * (1 - r.price / max(q.budget, 1))    # 越省越好
    if 0 < r.price <= q.budget * 0.7:
        reasons.append(f"約 {r.price} 元，在預算內還有餘裕")

    hint = crowd_hint(r, now)
    if hint.startswith("尖峰時段，可能"):
        score -= 15
    elif hint.startswith("目前應該"):
        score += 5
        reasons.append("目前應該不用排隊")

    if left >= 90:
        score += 5
    if r.id in q.recent_ids:
        score -= 25
    elif q.recent_ids:
        reasons.append("最近沒吃過，換換口味")

    if q.required_tags:
        reasons.append("符合你的飲食需求")
    return round(score, 1), reasons


def recommend(
    restaurants: list[Restaurant],
    buildings: list[Building],
    q: Query,
    now: datetime,
    k: int = 3,
) -> list[Recommendation]:
    b = next(x for x in buildings if x.id == q.building_id)
    picks = []
    for r in restaurants:
        ok, _, walk, left = _check(r, b, q, now)
        if not ok:
            continue
        score, reasons = _score(r, walk, left, q, now)
        picks.append(
            Recommendation(r, walk, left, crowd_hint(r, now), score, reasons)
        )
    picks.sort(key=lambda p: p.score, reverse=True)
    return picks[:k]


def surprise(restaurants, buildings, q: Query, now: datetime) -> Recommendation | None:
    """C6「驚喜一下」：從所有符合條件的店中隨機抽一家。"""
    pool = recommend(restaurants, buildings, q, now, k=len(restaurants))
    return random.choice(pool) if pool else None


def explain_empty(restaurants, buildings, q: Query, now: datetime) -> str:
    """沒有結果時，告訴使用者是哪個條件刷掉最多店，建議放寬。"""
    b = next(x for x in buildings if x.id == q.building_id)
    # 飲食限制（尤其過敏）是使用者的硬需求，不優先建議放寬：
    # 先看「符合飲食條件的店」是被什麼條件刷掉的。
    diet_ok = [r for r in restaurants if passes_diet(r, q)]
    pool = diet_ok or restaurants
    counts = Counter(_check(r, b, q, now)[1] for r in pool)
    counts.pop("", None)
    if not counts:
        return "沒有符合的店。"
    reason, n = counts.most_common(1)[0]
    tips = {
        "飲食限制": "試著少勾一個飲食條件",
        "現在沒開": "這個時間大多店家沒開，可以考慮便利商店或晚點再吃",
        "走到時快打烊": "附近的店快打烊了，動作要快或換地點",
        "時間不夠": "把可用時間調長一點",
        "超出預算": "把預算調高一點",
        "座位不夠": "人數較多，可以考慮分兩桌",
    }
    return f"有 {n} 家因為「{reason}」被排除，建議：{tips[reason]}。"
