"""步驟 1.5：把 OSM 抓到的清單「篩選＋排優先順序＋分配負責人」。

執行（在專案資料夾）：
    python3 tools/prioritize.py data_work/osm_candidates_日期.csv
    python3 tools/prioritize.py data_work/osm_candidates_日期.csv --members 4   # 指定組員人數

產生 data_work/verify_list_日期.csv，匯入 Google 試算表後，每人照「負責人」欄確認。

規則（可依需要調整下面的常數）：
  A 先確認：正餐，從最近的台大建物或公館站走路 4 分鐘內（約 150 家）
  B 有空再確認：正餐 5～8 分鐘；或早餐、咖啡輕食 4 分鐘內
  C 先不用管：飲料甜點、酒館、超過 8 分鐘、疑似歇業或非餐廳、重複
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from core.data import load_buildings  # noqa: E402
from core.filters import walking_minutes  # noqa: E402
from core.models import Restaurant  # noqa: E402
from osm_hours import OUR_DAYS, parse_osm_hours  # noqa: E402

A_MAX_WALK = 4
B_MAX_WALK = 8

# 每個區域可以有好幾個參考點；店家歸到「最近的參考點」所屬的區域
AREA_ANCHORS = {
    "校內": [(25.0172, 121.5395), (25.0159, 121.5446), (25.0194, 121.5394), (25.0185, 121.5360)],
    "公館": [(25.0145, 121.5335)],
    "溫州街": [(25.0195, 121.5315)],
    "師大商圈": [(25.0240, 121.5290)],
    "台科大/基隆路": [(25.0128, 121.5420)],
    "科技大樓/和平東路": [(25.0245, 121.5430)],
}

DRINK = re.compile(
    r"(茶(?!餐廳|食)|飲|豆花|甘蔗|果汁|優格|檸檬|柠檬|愛玉|湯圓|甜品|紅豆餅|冰品|鬆餅|可麗餅|"
    r"50嵐|COMEBUY|迷客夏|清心福全|可不可|龜記|得正|德正|烏弄|大茗|天仁|麻古|自然褂|堅果奶|水果吧)",
    re.I,
)
CAFE = re.compile(r"(咖啡|coffee|cafe|café|珈琲|kohee|甜點|pâtisserie|bakery|麵包|烘焙)", re.I)
BREAKFAST = re.compile(r"(早餐|早午餐|美而美|豆漿|飯糰|brunch)", re.I)
BAR = re.compile(r"(小酒館|酒館|酒吧|居酒屋|小酌|酒場|\bbar\b|vino)", re.I)
NOT_FOOD = re.compile(r"(即將開幕|頂讓|歇業|停業|有限公司|residential|書店|書房|會館|廣場|文創|中保|藝集)", re.I)

DRINK_CUISINE = {"bubble_tea", "tea", "juice", "ice_cream"}
CAFE_CUISINE = {"coffee_shop", "coffee", "cake", "pancake", "waffle"}
BREAKFAST_CUISINE = {"breakfast", "brunch"}

EXTRA = ["優先", "負責人", "類型", "走路分鐘", "提醒"]


def category(name: str, cuisine: str) -> str:
    cuisines = set(cuisine.split(";")) if cuisine else set()
    if BAR.search(name):
        return "酒館"
    if cuisines & DRINK_CUISINE or DRINK.search(name):
        return "飲料甜點"
    if cuisines & BREAKFAST_CUISINE or BREAKFAST.search(name):
        return "早餐"
    if cuisines & CAFE_CUISINE or CAFE.search(name):
        return "咖啡輕食"
    return "正餐"


def nearest_area(lat: float, lng: float) -> str:
    return min(AREA_ANCHORS, key=lambda k: min(math.dist((lat, lng), p) for p in AREA_ANCHORS[k]))


def walk_from_campus(lat: float, lng: float, buildings) -> int:
    dummy = Restaurant("", "", "", lat, lng, 0, 0, set(), set(), {}, False, "")
    return min(walking_minutes(b, dummy) for b in buildings)


def prioritize(rows: list[dict], members: int) -> list[dict]:
    buildings = load_buildings()
    seen: list[tuple[str, float, float]] = []
    out = []
    for r in rows:
        lat, lng = float(r["lat"]), float(r["lng"])
        name = r["name"]
        cat = category(name, r.get("osm_cuisine", ""))
        walk = walk_from_campus(lat, lng, buildings)
        notes = []

        # 用改良版解析器重新解析營業時間（修正舊版的國定假日 bug）
        raw = r.get("osm_opening_hours", "")
        hours = parse_osm_hours(raw) if raw else None
        if hours:
            for d in OUR_DAYS:
                r[d] = hours[d]
        if not raw:
            notes.append("沒有營業時間")
        elif hours is None:
            notes.append("營業時間要手動填")

        dup = any(n == name and math.dist((lat, lng), (a, b)) < 0.0012 for n, a, b in seen)
        seen.append((name, lat, lng))
        flagged = bool(NOT_FOOD.search(name))
        if flagged:
            notes.insert(0, "疑似歇業或不是餐廳，確認後可刪")
        if dup:
            notes.insert(0, "和上面同名的店重複，確認後可刪")

        if dup or flagged or cat in ("飲料甜點", "酒館") or walk > B_MAX_WALK:
            prio = "C"
        elif cat == "正餐" and walk <= A_MAX_WALK:
            prio = "A"
        elif cat == "正餐" or walk <= A_MAX_WALK:
            prio = "B"
        else:
            prio = "C"

        r.update({
            "優先": prio, "類型": cat, "走路分鐘": walk, "提醒": "；".join(notes),
            "area": nearest_area(lat, lng),
            "notes": "請填價格、座位、不辣/高蛋白、過敏原",
        })
        out.append(r)

    # 依區域把 A、B 平均分給組員（同一區盡量給同一人，方便實地走訪）
    area_order = list(AREA_ANCHORS)
    for prio in ("A", "B"):
        group = sorted((r for r in out if r["優先"] == prio),
                       key=lambda r: (area_order.index(r["area"]), r["走路分鐘"], r["name"]))
        per = math.ceil(len(group) / members) if group else 0
        for i, r in enumerate(group):
            r["負責人"] = f"組員{i // per + 1}" if per else ""
    for r in out:
        r.setdefault("負責人", "")

    out.sort(key=lambda r: (r["優先"], r["負責人"], area_order.index(r["area"]), r["走路分鐘"]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--members", type=int, default=5, help="組員人數（預設 5）")
    args = ap.parse_args()

    with open(args.csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        base_cols = reader.fieldnames
        rows = list(reader)

    out = prioritize(rows, args.members)
    cols = EXTRA + [c for c in base_cols if c not in EXTRA]
    dest = ROOT / "data_work" / f"verify_list_{date.today():%Y%m%d}.csv"
    dest.parent.mkdir(exist_ok=True)
    with open(dest, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    prio = Counter(r["優先"] for r in out)
    print(f"共 {len(out)} 家 → A 先確認 {prio['A']} 家、B 有空再確認 {prio['B']} 家、C 先不用管 {prio['C']} 家")
    per_member = Counter(r["負責人"] for r in out if r["優先"] == "A")
    print("A 級每人分配：" + "、".join(f"{k} {v} 家" for k, v in sorted(per_member.items())))
    print(f"檔案位置：{dest}")


if __name__ == "__main__":
    main()
