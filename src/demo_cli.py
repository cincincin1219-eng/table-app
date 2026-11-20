"""不用裝 Flet 也能測試推薦邏輯：python src/demo_cli.py"""
from datetime import datetime

from core.data import load_buildings, load_restaurants
from core.models import Query
from core.recommend import explain_empty, recommend

restaurants = load_restaurants()
buildings = load_buildings()

cases = [
    ("週二 12:10 普通教學館，一個人，50 分鐘，100 元",
     Query("general", minutes_available=50, budget=100), datetime(2026, 11, 17, 12, 10)),
    ("週四 18:30 新生教學館，4 人，有人吃素、不吃辣，150 元",
     Query("xinsheng", minutes_available=90, budget=150, party_size=4,
           required_tags={"vegetarian", "not_spicy"}), datetime(2026, 11, 19, 18, 30)),
    ("週一 21:15 博理館，高蛋白",
     Query("boli", minutes_available=60, budget=200, required_tags={"high_protein"}),
     datetime(2026, 11, 16, 21, 15)),
    ("週三 03:00 總圖（應該沒結果）",
     Query("lib"), datetime(2026, 11, 18, 3, 0)),
]

for title, q, now in cases:
    print(f"\n== {title}")
    picks = recommend(restaurants, buildings, q, now)
    if not picks:
        print("  " + explain_empty(restaurants, buildings, q, now))
    for p in picks:
        print(f"  {p.restaurant.name:<10} 分數 {p.score:>5}  步行 {p.walk_minutes} 分  "
              f"{p.crowd_hint}  | {'、'.join(p.reasons)}")
