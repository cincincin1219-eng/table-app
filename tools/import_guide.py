"""把「台大美食圖鑑」的實測資料併進 App 的餐廳資料。

執行（在專案資料夾）：
    python3 tools/import_guide.py

讀兩個檔：
  data_work/guide_20261125.csv       圖鑑每一篇整理成一列（價格、出餐速度、要更新 / 新增 / 略過）
  data_work/verify_list_20261119.csv OpenStreetMap 的店家清單（拿座標和營業時間）
寫回 src/data/restaurants.csv。

規則：
  - 「更新」：App 裡已經有的店，價格改成圖鑑價格區間偏低的位置（40%）
  - 「新增」：OSM 找得到的用 OSM 座標；找不到但在校內餐廳 / 水源市場的，用地標座標（標「位置約略」）
  - 營業時間：OSM 有就用 OSM，沒有就依地點推估（標「時間待確認」）
  - 「歇業」和「略過」不會放進 App；略過的原因寫在 guide CSV 的 ref 欄
組員實地確認後，把 last_checked 改成確認日期，App 上的提醒就會消失。
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from build_restaurants import OUT, OUT_COLUMNS, validate  # noqa: E402
from osm_hours import parse_osm_hours  # noqa: E402

GUIDE = ROOT / "data_work" / "guide_20261125.csv"
OSM = ROOT / "data_work" / "verify_list_20261119.csv"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# 地標座標（OSM 沒收錄的攤位用這些，誤差約 50～100 公尺）
ANCHORS = {
    "大一女": (25.014956, 121.534988, "公館"),
    "女九": (25.019444, 121.539404, "校內"),
    "博雅餐車": (25.017800, 121.537200, "校內"),
    "水源市場": (25.014600, 121.533400, "公館"),
    "公館站": (25.014900, 121.534300, "公館"),
}
CAMPUS = {"mon": "10:30-14:00|16:30-19:30", "tue": "10:30-14:00|16:30-19:30", "wed": "10:30-14:00|16:30-19:30",
          "thu": "10:30-14:00|16:30-19:30", "fri": "10:30-14:00|16:30-19:30", "sat": "11:00-14:00", "sun": ""}
MARKET = {d: ("" if d == "mon" else "10:00-19:00") for d in DAYS}          # 水源市場週一公休
FOOD_TRUCK = {d: ("11:00-14:00" if d in DAYS[:5] else "") for d in DAYS}
STREET = {d: "11:00-14:00|17:00-20:30" for d in DAYS}
CAMPUS_WORDS = ("大一女", "女九", "活動中心", "活大", "禮賢樓", "小福")
# 圖鑑標題比較長的，App 上顯示短一點
SHORT_NAME = {"小旺號 - 公館店": "小旺號", "瑪莉珍比薩 台大店": "瑪莉珍比薩", "七品食堂丨越式美食專門店": "七品食堂",
              "延三溫體牛-黃記": "延三溫體牛 黃記", "熊霸 — 鍋物.咖哩.燴飯": "熊霸 鍋物咖哩燴飯",
              "御喜 自助餐": "御喜自助餐", "祥滿 速食餐坊": "祥滿速食餐坊"}
# OSM 營業時間寫法太特別、解析錯的，直接寫正確的
HOURS_FIX = {"至香園沙茶牛肉麵老店": {**{d: "11:30-14:00|17:30-20:30" for d in DAYS}, "tue": "17:30-20:30"}}
PRICE_IF_MISSING = {"自助餐": 100, "滷": 110}


def default_hours(loc: str, place: str, area: str) -> dict[str, str]:
    if place == "水源市場":
        return MARKET
    if place == "博雅餐車":
        return FOOD_TRUCK
    if place in ("大一女", "女九") or area == "校內" or any(k in loc for k in CAMPUS_WORDS):
        return CAMPUS
    return STREET


def mid_price(lo: str, hi: str) -> int | None:
    """圖鑑的價格區間 → 一個人一餐大約多少。

    區間上限常是「點最貴的套餐」，所以取區間 40% 的位置，不取正中間。"""
    if not lo:
        return None
    lo_i, hi_i = int(lo), int(hi or lo)
    return int(round((lo_i + (hi_i - lo_i) * 0.4) / 10) * 10)


def main():
    today = f"{date.today():%Y-%m-%d}"
    with open(OUT, encoding="utf-8-sig", newline="") as f:
        current = list(csv.DictReader(f))
    with open(OSM, encoding="utf-8-sig", newline="") as f:
        osm = {r["osm_id"]: r for r in csv.DictReader(f)}
    with open(GUIDE, encoding="utf-8-sig", newline="") as f:
        guide = list(csv.DictReader(f))

    by_id = {r["id"]: r for r in current}
    updated = added = 0
    for g in guide:
        price = mid_price(g["price_lo"], g["price_hi"])
        if g["status"] == "更新":
            row = by_id.get(g["ref"])
            if row and price:
                row["price"] = str(price)
                row["last_checked"] = f"{today} 圖鑑實測價·OSM時間"
                updated += 1
            continue
        if g["status"] != "新增":
            continue

        notes = []
        if g["match"] == "osm":
            o = osm[g["ref"]]
            rid, lat, lng, area = f"osm{g['ref']}", o["lat"], o["lng"], o["area"]
            hours = {d: o.get(d, "") for d in DAYS}
            if not any(hours.values()):
                hours = parse_osm_hours(o.get("osm_opening_hours", "")) or {}
            place = ""
        else:
            place = g["ref"]
            lat, lng, area = ANCHORS[place]
            rid, hours = f"guide{int(g['num']):03d}", {}
            notes.append("位置約略")
        if any(hours.values()):
            notes.insert(0, "OSM時間")
        else:
            hours = default_hours(g["loc"], place, area)
            notes.insert(0, "時間待確認")
        if g["name"] == "公館米粉湯":                  # 店家公告：週二～週日 10:00-19:00
            hours, notes[0] = MARKET, "店家公告時間"
        hours = HOURS_FIX.get(g["name"], hours)

        if price:
            stamp = f"{today} 圖鑑實測價"
        else:
            price = next((p for k, p in PRICE_IF_MISSING.items() if k in g["name"]), 150)
            stamp = f"{today} 估價"
        row = {"name": SHORT_NAME.get(g["name"], g["name"]), "area": area, "lat": lat, "lng": lng, "price": price, "seats": 20,
               "tags": "", "allergens": "", "popular": "", **hours}
        clean, errors = validate(row)
        if not clean:
            print(f"略過「{g['name']}」：{'；'.join(errors)}")
            continue
        if rid in by_id:
            continue
        clean["last_checked"] = "·".join([stamp, *notes])
        by_id[rid] = {"id": rid, **clean}
        current.append(by_id[rid])
        added += 1

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(current)
    print(f"完成！更新 {updated} 家價格、新增 {added} 家，App 現在共有 {len(current)} 家。")


if __name__ == "__main__":
    main()
