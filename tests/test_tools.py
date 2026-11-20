import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

import build_restaurants  # noqa: E402
from fetch_osm import build_query, to_row  # noqa: E402
from osm_hours import parse_osm_hours  # noqa: E402


def test_osm_hours_common_forms():
    h = parse_osm_hours("Mo-Fr 11:00-14:00,17:00-20:00; Sa 11:00-14:00; Su off")
    assert h["mon"] == "11:00-14:00|17:00-20:00"
    assert h["fri"] == "11:00-14:00|17:00-20:00"
    assert h["sat"] == "11:00-14:00"
    assert h["sun"] == ""


def test_osm_hours_every_day_and_247_and_wraparound():
    assert parse_osm_hours("11:00-21:00")["wed"] == "11:00-21:00"
    assert parse_osm_hours("24/7")["sun"] == "00:00-24:00"
    h = parse_osm_hours("Fr-Mo 18:00-02:00")
    assert h["sat"] == "18:00-02:00" and h["tue"] == ""
    assert parse_osm_hours("Mo-Fr 7:30-9:00")["mon"] == "07:30-09:00"


def test_osm_hours_unknown_returns_none():
    assert parse_osm_hours("Jan-Mar Mo 10:00-12:00") is None
    assert parse_osm_hours("") is None


def test_to_row_handles_way_center_and_diet():
    el = {"type": "way", "id": 1, "center": {"lat": 25.015, "lon": 121.534},
          "tags": {"name": "測試素食", "diet:vegetarian": "yes", "opening_hours": "Mo-Su 11:00-20:00"}}
    row = to_row(el)
    assert row["area"] == "公館"
    assert row["tags"] == "vegetarian"
    assert row["mon"] == "11:00-20:00"
    assert to_row({"type": "node", "id": 2, "lat": 25, "lon": 121, "tags": {}}) is None


def test_query_covers_bbox():
    q = build_query()
    assert '"amenity"="restaurant"' in q and "out center tags" in q


def _write(path, rows):
    cols = list(rows[0].keys())
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _base(**kw):
    row = {"verified": "是", "name": "A店", "area": "公館", "lat": "25.01", "lng": "121.53",
           "price": "100", "seats": "20", "tags": "vegetarian", "allergens": "",
           "mon": "11:00-14:00", "tue": "", "wed": "", "thu": "", "fri": "", "sat": "", "sun": "",
           "popular": ""}
    row.update(kw)
    return row


def test_build_only_verified_rows(tmp_path, monkeypatch):
    out = tmp_path / "restaurants.csv"
    monkeypatch.setattr(build_restaurants, "OUT", out)
    src = tmp_path / "in.csv"
    _write(src, [_base(), _base(name="B店", verified="")])
    build_restaurants.main(str(src))
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert [r["name"] for r in rows] == ["A店"]
    assert rows[0]["id"] == "r001"


def test_build_accepts_chinese_tags(tmp_path, monkeypatch):
    out = tmp_path / "restaurants.csv"
    monkeypatch.setattr(build_restaurants, "OUT", out)
    src = tmp_path / "in.csv"
    _write(src, [_base(tags="素食、不辣", allergens="花生；蛋")])
    build_restaurants.main(str(src))
    row = next(csv.DictReader(open(out, encoding="utf-8")))
    assert row["tags"] == "vegetarian;not_spicy"
    assert row["allergens"] == "peanut;egg"


def test_build_reports_errors_and_does_not_write(tmp_path, monkeypatch, capsys):
    out = tmp_path / "restaurants.csv"
    monkeypatch.setattr(build_restaurants, "OUT", out)
    src = tmp_path / "in.csv"
    _write(src, [_base(price="大概100", tags="spicy")])
    try:
        build_restaurants.main(str(src))
    except SystemExit:
        pass
    text = capsys.readouterr().out
    assert "price" in text and "spicy" in text
    assert not out.exists()


def test_osm_hours_holiday_rules_and_after_midnight():
    h = parse_osm_hours("PH,Mo-Su 07:00-21:30")
    assert h["mon"] == "07:00-21:30" and h["sun"] == "07:00-21:30"
    h = parse_osm_hours("Mo-Fr 12:00-14:30,17:30-21:00; PH,Sa-Su 11:30-21:00")
    assert h["sat"] == "11:30-21:00" and h["mon"] == "12:00-14:30|17:30-21:00"
    assert parse_osm_hours("Mo-Su 11:30-14:30,17:00-26:00")["fri"] == "11:30-14:30|17:00-02:00"
    h = parse_osm_hours("Mo-Fr 11:00-20:00, Sa-Su 09:00-20:00")
    assert h["fri"] == "11:00-20:00" and h["sat"] == "09:00-20:00"
    assert parse_osm_hours("Tu-Su 09:00-15:00、17:00-21:00")["mon"] == ""


def test_prioritize_categories_and_flags():
    from prioritize import category, prioritize
    assert category("50嵐", "bubble_tea") == "飲料甜點"
    assert category("池記燒臘茶餐廳", "") == "正餐"
    assert category("三時午咖哩屋", "curry") == "正餐"
    assert category("路易莎咖啡", "coffee_shop") == "咖啡輕食"
    assert category("瑪德蓮小酒館", "") == "酒館"
    base = {"name": "", "lat": "25.0150", "lng": "121.5340", "osm_cuisine": "", "osm_opening_hours": "",
            **{d: "" for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}}
    rows = [dict(base, name="公館麵店"), dict(base, name="公館麵店"),
            dict(base, name="韓國時間（即將開幕）"), dict(base, name="遠方餐廳", lat="25.0290")]
    out = {(r["name"], r["提醒"][:2]): r["優先"] for r in prioritize(rows, 2)}
    assert out[("公館麵店", "沒有")] == "A"
    assert out[("公館麵店", "和上")] == "C"
    assert out[("韓國時間（即將開幕）", "疑似")] == "C"
    assert out[("遠方餐廳", "沒有")] == "C"


def test_starter_estimates_price_and_marks_it(tmp_path, monkeypatch):
    import make_starter
    out = tmp_path / "restaurants.csv"
    monkeypatch.setattr(make_starter, "OUT", out)
    src = tmp_path / "verify.csv"
    head = "優先,類型,走路分鐘,name,area,lat,lng,price,seats,tags,allergens,mon,tue,wed,thu,fri,sat,sun,popular,osm_id,osm_cuisine\n"
    src.write_text(head +
        "A,正餐,2,麥當勞,公館,25.0145,121.5335,,,,,06:00-24:00,,,,,,,,111,burger\n"
        "A,正餐,2,沒時間的店,公館,25.0145,121.5335,,,,,,,,,,,,,222,\n"
        "C,飲料,2,50嵐,公館,25.0145,121.5335,,,,,10:00-22:00,,,,,,,,333,bubble_tea\n", encoding="utf-8")
    make_starter.main(str(src))
    import csv
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert [r["name"] for r in rows] == ["麥當勞"]
    assert rows[0]["id"] == "osm111" and rows[0]["price"] == "150" and "估" in rows[0]["last_checked"]
