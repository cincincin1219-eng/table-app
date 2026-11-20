"""預覽用：還沒人工確認前，先用 OSM 資料看看 App 推薦的效果。

執行（在專案資料夾）：
    python3 tools/make_preview.py data_work/verify_list_日期.csv

會把 A、B 級的正餐放進 App。因為資料還沒確認：
  - 沒有營業時間的店，先套用常見時段 11:00-14:00|17:00-20:30
  - 價格先留 0（＝未填，App 不做預算篩選）、座位 20
  - 卡片上會顯示「預覽資料，未確認」
原本的資料會備份成 src/data/restaurants_backup.csv。
正式資料請用 tools/build_restaurants.py 匯入，會覆蓋預覽資料。
"""
from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "src" / "data" / "restaurants.csv"
BACKUP = ROOT / "src" / "data" / "restaurants_backup.csv"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DEFAULT_HOURS = "11:00-14:00|17:00-20:30"
COLUMNS = ["id", "name", "area", "lat", "lng", "price", "seats", "tags", "allergens",
           *DAYS, "popular", "last_checked"]


def main(path: str, include_b: bool = True):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    keep = {"A", "B"} if include_b else {"A"}
    picked = [r for r in rows if r.get("優先") in keep and r.get("類型") == "正餐"]

    if DATA.exists() and not BACKUP.exists():
        shutil.copy(DATA, BACKUP)

    real_hours = 0
    with open(DATA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for n, r in enumerate(picked, start=1):
            has_hours = any((r.get(d) or "").strip() for d in DAYS)
            real_hours += has_hours
            w.writerow({
                "id": f"p{n:03d}", "name": r["name"], "area": r["area"],
                "lat": r["lat"], "lng": r["lng"], "price": 0, "seats": 20,
                "tags": r.get("tags", ""), "allergens": "",
                **{d: (r.get(d) or "") if has_hours else DEFAULT_HOURS for d in DAYS},
                "popular": "false",
                "last_checked": "預覽資料，未確認" if has_hours else "預覽資料，營業時間未確認",
            })
    print(f"預覽資料完成：{len(picked)} 家（{real_hours} 家有真實營業時間，其餘套用常見時段）")
    print("執行 python3 src/demo_cli.py 或 flet run --web src/main.py 看效果。")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python3 tools/make_preview.py data_work/verify_list_日期.csv")
        sys.exit(1)
    main(sys.argv[1], include_b="--only-a" not in sys.argv)
