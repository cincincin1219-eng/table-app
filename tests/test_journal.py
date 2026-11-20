import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.journal import (  # noqa: E402
    dumps, in_month, loads, monthly_stats, new_entry, recent_restaurant_ids, sort_newest_first,
)


def sample():
    t = datetime(2026, 11, 3, 12, 10)
    return [
        new_entry(t, "公館麵店", area="公館", restaurant_id="r1", walk_minutes=5),
        new_entry(t + timedelta(days=1), "公館麵店", area="公館", restaurant_id="r1", walk_minutes=5),
        new_entry(t + timedelta(days=2, hours=10), "溫州街咖哩", area="溫州街", restaurant_id="r2",
                  walk_minutes=4, surprise=True, has_photo=True),
        new_entry(datetime(2026, 10, 30, 19, 0), "十月的店", area="校內", walk_minutes=2),
    ]


def test_roundtrip_and_bad_input():
    entries = sample()
    again = loads(dumps(entries))
    assert [e.name for e in again] == [e.name for e in entries]
    assert again[2].surprise and again[2].has_photo
    assert loads(None) == [] and loads("壞掉的資料") == [] and loads('[{"x":1}]') == []


def test_new_entry_strips_timezone():
    e = new_entry(datetime(2026, 11, 19, 12, 0, 5, 123, tzinfo=timezone(timedelta(hours=8))), "A")
    assert e.at == "2026-11-19T12:00:05"


def test_monthly_stats():
    s = monthly_stats(sample(), 2026, 11)
    assert s["meals"] == 3 and s["places"] == 2
    assert (s["favorite_name"], s["favorite_count"]) == ("公館麵店", 2)
    assert s["top_area"] == "公館" and s["top_area_share"] == 67
    assert s["km"] == round(14 * 75 * 2 / 1000, 1)
    assert s["surprises"] == 1 and s["photos"] == 1 and s["days_logged"] == 3
    assert s["late_night"] == 1                      # 22:10 那餐
    assert len(in_month(sample(), 2026, 10)) == 1


def test_empty_month():
    s = monthly_stats([], 2026, 11)
    assert s["meals"] == 0 and s["favorite_name"] == "" and s["top_area_share"] == 0


def test_recent_and_sorting():
    entries = sample()
    now = datetime(2026, 11, 5, 23, 0)
    assert recent_restaurant_ids(entries, now, days=2) == {"r1", "r2"}
    assert recent_restaurant_ids(entries, now, days=1) == {"r2"}
    assert sort_newest_first(entries)[0].name == "溫州街咖哩"


def test_new_fields_roundtrip_and_old_data_still_loads():
    from datetime import datetime
    from core.journal import dumps, loads, new_entry
    e = new_entry(datetime(2026, 11, 19, 19, 30), "巷尾麵舖", note="清湯", tags=["一人食", "宵夜"], price=120, party=2)
    back = loads(dumps([e]))[0]
    assert back.tags == ["一人食", "宵夜"] and back.price == 120 and back.party == 2
    old = '[{"at": "2026-11-01T12:00:00", "name": "學餐", "area": "校內"}]'   # 舊版存的資料
    assert loads(old)[0].tags == [] and loads(old)[0].price == 0
