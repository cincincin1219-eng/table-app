"""步驟 3：把「人工確認過」的清單，轉成 App 使用的 src/data/restaurants.csv。

執行（在專案資料夾）：
    python3 tools/build_restaurants.py data_work/確認完的檔案.csv

只會收錄 verified 欄填了「是 / yes / v」的列；
格式有問題的列會列出第幾列、哪裡錯，修好再跑一次即可。
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from core.data import parse_hours  # noqa: E402
from core.models import ALLERGEN_LABELS, DAYS, TAG_LABELS  # noqa: E402

OUT = ROOT / "src" / "data" / "restaurants.csv"
YES = {"是", "yes", "y", "v", "true", "1", "ok", "✓"}
OUT_COLUMNS = ["id", "name", "area", "lat", "lng", "price", "seats", "tags", "allergens",
               *DAYS, "popular", "last_checked"]


# 組員可以直接寫中文，程式會自動轉成英文代號
CHINESE_ALIASES = {
    "素食": "vegetarian", "素食可": "vegetarian", "蛋奶素": "vegetarian",
    "全素": "vegan", "純素": "vegan",
    "不辣": "not_spicy", "有不辣選項": "not_spicy",
    "高蛋白": "high_protein",
    "花生": "peanut", "甲殼類": "shellfish", "蝦蟹": "shellfish",
    "乳製品": "dairy", "奶": "dairy", "蛋": "egg", "麩質": "gluten", "小麥": "gluten",
}


def _clean_list(text: str, allowed: dict, field: str, errors: list[str]) -> str:
    raw = (text or "").replace("；", ";").replace(",", ";").replace("，", ";").replace("、", ";")
    items = [CHINESE_ALIASES.get(t.strip(), t.strip()) for t in raw.split(";") if t.strip()]
    bad = [t for t in items if t not in allowed]
    if bad:
        names = "、".join(allowed.values())
        errors.append(f"{field} 有不認得的值 {bad}，可用：{names}")
    return ";".join(dict.fromkeys(t for t in items if t in allowed))


def validate(row: dict) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    out = {"name": (row.get("name") or "").strip(), "area": (row.get("area") or "").strip()}
    if not out["name"]:
        errors.append("缺店名")
    for key in ("lat", "lng"):
        try:
            out[key] = f"{float(row[key]):.6f}"
        except (KeyError, ValueError):
            errors.append(f"{key} 不是數字")
    for key in ("price", "seats"):
        try:
            out[key] = str(int(float(row[key])))
        except (KeyError, ValueError):
            errors.append(f"{key} 要填整數（目前是「{row.get(key, '')}」）")
    out["tags"] = _clean_list(row.get("tags", ""), TAG_LABELS, "tags", errors)
    out["allergens"] = _clean_list(row.get("allergens", ""), ALLERGEN_LABELS, "allergens", errors)
    open_days = 0
    for d in DAYS:
        value = (row.get(d) or "").strip().replace("｜", "|").replace("～", "-").replace("~", "-")
        try:
            if parse_hours(value):
                open_days += 1
            out[d] = value
        except Exception:
            errors.append(f"{d} 營業時間格式錯誤「{value}」，例：11:00-14:00|17:00-20:30")
    if open_days == 0 and not errors:
        errors.append("七天都沒有營業時間")
    out["popular"] = "true" if (row.get("popular") or "").strip().lower() in YES else "false"
    return (None if errors else out), errors


def main(path: str):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    good, problems, skipped = [], [], 0
    for i, row in enumerate(rows, start=2):            # 第 1 列是標題
        if (row.get("verified") or "").strip().lower() not in YES:
            skipped += 1
            continue
        clean, errors = validate(row)
        if clean:
            good.append(clean)
        else:
            problems.append((i, row.get("name", ""), errors))

    if problems:
        print(f"有 {len(problems)} 家格式需要修正（其餘 {len(good)} 家沒問題）：\n")
        for line, name, errors in problems:
            print(f"  第 {line} 列「{name}」")
            for e in errors:
                print(f"    - {e}")
        print("\n修正後再執行一次。這次沒有更新 App 資料。")
        sys.exit(1)

    today = f"{date.today():%Y-%m-%d}"
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        for n, row in enumerate(good, start=1):
            writer.writerow({"id": f"r{n:03d}", **row, "last_checked": today})
    print(f"完成！{len(good)} 家已寫入 App（{skipped} 家尚未確認，先不收錄）。")
    print("執行 flet run --web src/main.py 就能看到新資料。")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法：python3 tools/build_restaurants.py data_work/確認完的檔案.csv")
        sys.exit(1)
    main(sys.argv[1])
