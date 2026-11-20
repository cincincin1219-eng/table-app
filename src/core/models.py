"""資料結構：餐廳、建物、使用者條件、推薦結果。"""
from __future__ import annotations

from dataclasses import dataclass, field

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# 飲食標籤（餐廳「有」這個特性）
TAG_LABELS = {
    "vegetarian": "素食可",
    "vegan": "全素",
    "not_spicy": "有不辣選項",
    "high_protein": "高蛋白",
}

# 過敏原（餐廳餐點「含有」這個成分）
ALLERGEN_LABELS = {
    "peanut": "花生",
    "shellfish": "甲殼類",
    "dairy": "乳製品",
    "egg": "蛋",
    "gluten": "麩質",
}


@dataclass
class Restaurant:
    id: str
    name: str
    area: str
    lat: float
    lng: float
    price: int                      # 一般一餐的價格（元）
    seats: int                      # 大約座位數
    tags: set[str]
    allergens: set[str]
    # 星期 -> [(開門分鐘, 打烊分鐘)]，分鐘從 00:00 起算；跨夜打烊會 > 1440
    hours: dict[str, list[tuple[int, int]]]
    popular: bool                   # 尖峰時段是否常排隊
    last_checked: str               # 資料最後確認日期


@dataclass
class Building:
    id: str
    name: str
    lat: float
    lng: float


@dataclass
class Query:
    building_id: str
    minutes_available: int = 60     # 可用的總時間（含來回走路與用餐）
    budget: int = 150               # 每人預算上限
    party_size: int = 1
    required_tags: set[str] = field(default_factory=set)
    avoid_allergens: set[str] = field(default_factory=set)
    recent_ids: set[str] = field(default_factory=set)   # 最近吃過，降低排名


@dataclass
class Recommendation:
    restaurant: Restaurant
    walk_minutes: int
    minutes_until_close: int
    crowd_hint: str
    score: float
    reasons: list[str]
