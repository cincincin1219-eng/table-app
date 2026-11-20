"""步驟 1：自動抓 —— 從 OpenStreetMap 抓台大周邊的餐廳，產生「待確認清單」。

執行（在專案資料夾）：
    python3 tools/fetch_osm.py        # 預設 5 位組員
    python3 tools/fetch_osm.py 4      # 指定 4 位組員

結果：
    data_work/osm_candidates_日期.csv   原始清單（全部）
    data_work/verify_list_日期.csv      篩選＋排好優先順序＋分好負責人的確認清單
接著把 verify_list 匯入 Google 試算表，讓組員確認（見 README「資料流程」）。

只用 Python 內建功能，不用另外安裝套件。
資料來源：© OpenStreetMap contributors，ODbL 授權。
"""
from __future__ import annotations

import csv
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from osm_hours import OUR_DAYS, parse_osm_hours  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data_work"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# 範圍：台大校總區＋公館＋溫州街＋科技大樓一帶（南, 西, 北, 東）
BBOX = (25.0090, 121.5270, 25.0290, 121.5480)
AMENITIES = ["restaurant", "fast_food", "cafe", "food_court"]

# 用來自動判斷「區域」的參考點，人工確認時可再修改
AREA_ANCHORS = {
    "校內": (25.0170, 121.5395),
    "公館": (25.0145, 121.5340),
    "溫州街": (25.0215, 121.5330),
    "科技大樓": (25.0262, 121.5435),
}

COLUMNS = [
    "verified", "name", "area", "lat", "lng", "price", "seats", "tags", "allergens",
    *OUR_DAYS, "popular", "notes",
    "osm_id", "osm_type", "osm_amenity", "osm_cuisine", "osm_opening_hours",
]


def build_query() -> str:
    s, w, n, e = BBOX
    parts = "".join(
        f'node["amenity"="{a}"]({s},{w},{n},{e});way["amenity"="{a}"]({s},{w},{n},{e});'
        for a in AMENITIES
    )
    return f"[out:json][timeout:60];({parts});out center tags;"


def fetch() -> list[dict]:
    body = urllib.parse.urlencode({"data": build_query()}).encode()
    req = urllib.request.Request(
        OVERPASS_URL, data=body,
        headers={"User-Agent": "ntu-meal-picker student project"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.load(resp)["elements"]


def nearest_area(lat: float, lng: float) -> str:
    return min(AREA_ANCHORS, key=lambda k: math.dist((lat, lng), AREA_ANCHORS[k]))


def to_row(el: dict) -> dict | None:
    tags = el.get("tags", {})
    name = tags.get("name:zh") or tags.get("name") or tags.get("name:en")
    if not name:
        return None                                   # 沒名字的點無法確認，略過
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lng = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None or lng is None:
        return None

    diet = []
    if tags.get("diet:vegetarian") in {"yes", "only"}:
        diet.append("vegetarian")
    if tags.get("diet:vegan") in {"yes", "only"}:
        diet.append("vegan")

    raw_hours = tags.get("opening_hours", "")
    hours = parse_osm_hours(raw_hours)
    notes = []
    if not raw_hours:
        notes.append("OSM 沒有營業時間，請補")
    elif hours is None:
        notes.append("OSM 營業時間格式複雜，請看 osm_opening_hours 手動填")
    notes.append("請填價格、座位、不辣/高蛋白、過敏原")

    row = {
        "verified": "",
        "name": name,
        "area": nearest_area(lat, lng),
        "lat": f"{lat:.6f}",
        "lng": f"{lng:.6f}",
        "price": "",
        "seats": "",
        "tags": ";".join(diet),
        "allergens": "",
        "popular": "",
        "notes": "；".join(notes),
        "osm_id": el.get("id"),
        "osm_type": el.get("type"),
        "osm_amenity": tags.get("amenity", ""),
        "osm_cuisine": tags.get("cuisine", ""),
        "osm_opening_hours": raw_hours,
    }
    for d in OUR_DAYS:
        row[d] = (hours or {}).get(d, "")
    return row


def main():
    print("正在從 OpenStreetMap 抓資料，約需 10～60 秒…")
    try:
        elements = fetch()
    except Exception as exc:  # 網路問題、伺服器忙碌
        print(f"抓取失敗：{exc}\n請稍等一兩分鐘再試一次。")
        sys.exit(1)

    rows = [r for r in (to_row(el) for el in elements) if r]
    rows.sort(key=lambda r: (r["area"], r["name"]))

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"osm_candidates_{date.today():%Y%m%d}.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:   # utf-8-sig：Excel 開中文不會亂碼
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    with_hours = sum(1 for r in rows if any(r[d] for d in OUR_DAYS))
    print(f"抓取完成！共 {len(rows)} 家，其中 {with_hours} 家已自動帶入營業時間。")
    print(f"原始清單：{out}\n")

    # 自動接著做篩選與分配
    import subprocess
    members = sys.argv[1] if len(sys.argv) > 1 else "5"
    subprocess.run([sys.executable, str(Path(__file__).parent / "prioritize.py"),
                    str(out), "--members", members], check=False)
    print("\n下一步：把 verify_list 檔案匯入 Google 試算表，請組員依「負責人」欄確認（README 第 5 節）。")


if __name__ == "__main__":
    main()
