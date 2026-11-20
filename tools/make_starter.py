"""先讓 App 有真的餐廳可以用：從 prioritize.py 產生的確認清單裡，挑出
「台大附近、正餐、OpenStreetMap 上有營業時間」的店，直接寫進 App。

執行（在專案資料夾）：
    python3 tools/make_starter.py data_work/verify_list_日期.csv

和 build_restaurants.py 的差別：
  - 不需要組員先確認，馬上就能試用
  - 價格是「估計」：依店名或料理類型粗估一個人一餐大約多少，App 會標「（估）」
  - 營業時間來自 OpenStreetMap，可能過時
  - 過敏原一律空白（不知道，不代表沒有），App 會提醒向店家確認
組員確認完後，改用 build_restaurants.py 匯入正式資料，「估」的標記就會消失。
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from build_restaurants import OUT, OUT_COLUMNS, validate  # noqa: E402

# 已知店家的粗估（一個人一餐，元）。組員到 Google 地圖看到價格範圍後，可以直接改這裡。
PRICE_BY_NAME = {
    "麥當勞": 150, "摩斯漢堡": 150, "頂呱呱": 160, "CoCo壹番屋": 260, "壽司郎": 300, "大狗麵線": 70,
    "無鍋不樂": 280, "韓天閣": 220, "泰正點泰式餐坊": 220, "三川拉麵": 230, "劉記川味牛肉麵": 180,
    "食其家": 130, "石記牛肉麵": 170, "新馬辣經典麻辣鍋": 650, "龐德羅沙": 380, "威宇牛排": 260,
    "孫東寶台式牛排專賣店": 220, "酷必五星級牛排飯": 200, "味自慢": 280, "雞魯哥銅板美食": 60,
    "我家廚房快餐部": 90, "蛋白盒子": 120, "四海遊龍": 90, "Gia越式河粉": 130, "大福利排骨大王": 120,
    "全家喜湯包": 120, "三媽臭臭鍋": 160, "小蔬杭 絕對蔬食": 150, "鳳城燒臘": 130, "老哥雞肉飯 乾拌麵": 90,
    "小李子清粥小菜": 150, "Mr. Smile好吃雞排": 90, "芝加哥比薩": 250, "戰醬燒肉": 600, "靜壽司": 350,
    "上好魚翅燕窩": 600, "米澤製麵": 220, "京阪豚骨拉麵": 220, "初牛炭火直燒丼飯專賣店": 220,
    "埃及沙威瑪王": 150, "每日Gimbap韓式飯捲": 130, "JJ's Poké": 220, "bb.q Chicken": 300,
    "三米三現煲石鍋飯": 180, "赤神日式豬排": 260, "壹森泰食堂": 300, "泰品雲南泰式料理": 220,
    "湄賽雲泰料理": 200, "喜川麵館": 150, "麵屋壹の穴 ICHI": 230, "樂富冰室": 180, "蒸夠臭臭豆腐": 110,
    "家常清真小吃": 130, "峨嵋川菜": 220, "順園小館": 180, "豪香熱炒": 250, "嵐迪義大利麵館": 220,
}
PRICE_BY_CUISINE = [
    ("hotpot", 300), ("steak", 260), ("sushi", 320), ("ramen", 220), ("beef_noodle", 170),
    ("thai", 220), ("korean", 220), ("italian", 240), ("pizza", 250), ("japanese", 240),
    ("burger", 160), ("dumpling", 100), ("noodle", 140), ("taiwanese", 110), ("chinese", 180),
]
DEFAULT_PRICE = 180
TAG_BY_NAME = {"小蔬杭 絕對蔬食": "vegetarian;vegan"}
SKIP = {"玩逗樹", "耍性子", "法點法食", "挑豆院"}    # 桌遊店、時間太少或不是正餐


def estimate_price(name: str, cuisine: str) -> int:
    if name in PRICE_BY_NAME:
        return PRICE_BY_NAME[name]
    for key, price in PRICE_BY_CUISINE:
        if key in (cuisine or ""):
            return price
    return DEFAULT_PRICE


def main(path: str):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    picked, seen = [], set()
    for row in rows:
        if row.get("優先") not in ("A", "B") or row.get("類型") != "正餐" or row["name"] in SKIP:
            continue
        if not any((row.get(d) or "").strip() for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")):
            continue
        key = (row["name"], row["lat"][:7], row["lng"][:8])
        if key in seen:
            continue
        seen.add(key)
        row = dict(row)
        row["price"] = row.get("price") or str(estimate_price(row["name"], row.get("osm_cuisine", "")))
        row["seats"] = row.get("seats") or "20"
        row["tags"] = row.get("tags") or TAG_BY_NAME.get(row["name"], "")
        clean, errors = validate(row)
        if clean:
            picked.append((int(row.get("走路分鐘") or 9), row.get("osm_id", ""), clean))
        else:
            print(f"略過「{row['name']}」：{'；'.join(errors)}")

    picked.sort(key=lambda t: t[0])
    stamp = f"{date.today():%Y-%m-%d} OSM·估價"
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        for n, (_, osm_id, row) in enumerate(picked, start=1):
            rid = f"osm{osm_id}" if osm_id else f"s{n:03d}"
            writer.writerow({"id": rid, **row, "last_checked": stamp})
    print(f"完成！{len(picked)} 家寫入 {OUT}（營業時間來自 OSM，價格為估計）。")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法：python3 tools/make_starter.py data_work/verify_list_日期.csv")
        sys.exit(1)
    main(sys.argv[1])
