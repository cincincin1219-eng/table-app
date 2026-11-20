import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from core.data import load_buildings, load_restaurants, parse_hours  # noqa: E402
from core.filters import minutes_until_close  # noqa: E402
from core.models import Query  # noqa: E402
from core.recommend import explain_empty, recommend  # noqa: E402

R = load_restaurants(Path(__file__).resolve().parent / "fixtures" / "restaurants_sample.csv")  # 固定的範例店，正式資料更新也不影響測試
B = load_buildings()
by_id = {r.id: r for r in R}


def test_parse_hours_two_spans_and_overnight():
    assert parse_hours("11:00-14:00|17:00-20:30") == [(660, 840), (1020, 1230)]
    assert parse_hours("18:00-02:00") == [(1080, 1560)]
    assert parse_hours("") == []


def test_closed_on_sunday():
    assert minutes_until_close(by_id["r01"], datetime(2026, 11, 22, 12, 0)) is None


def test_overnight_still_open_after_midnight():
    # 週三 01:00，r06 從週二 18:00 開到週三 02:00
    assert minutes_until_close(by_id["r06"], datetime(2026, 11, 18, 1, 0)) == 60


def test_returns_at_most_three_sorted():
    picks = recommend(R, B, Query("general", budget=300, minutes_available=120),
                      datetime(2026, 11, 17, 13, 0))
    assert 1 <= len(picks) <= 3
    assert [p.score for p in picks] == sorted((p.score for p in picks), reverse=True)


def test_allergen_and_tags_are_hard_filters():
    q = Query("general", budget=300, minutes_available=120,
              required_tags={"vegetarian"}, avoid_allergens={"shellfish"})
    for p in recommend(R, B, q, datetime(2026, 11, 17, 12, 30), k=10):
        assert "vegetarian" in p.restaurant.tags
        assert "shellfish" not in p.restaurant.allergens


def test_budget_respected():
    for p in recommend(R, B, Query("general", budget=100), datetime(2026, 11, 17, 12, 0), k=10):
        assert p.restaurant.price <= 100


def test_empty_result_explains_why():
    q = Query("lib")
    now = datetime(2026, 11, 18, 3, 0)
    assert recommend(R, B, q, now) == []
    assert "現在沒開" in explain_empty(R, B, q, now)


def test_recent_restaurant_ranked_lower():
    now = datetime(2026, 11, 17, 14, 30)
    q = Query("general", budget=300, minutes_available=120)
    first = recommend(R, B, q, now)[0].restaurant.id
    q.recent_ids = {first}
    assert recommend(R, B, q, now)[0].restaurant.id != first


def test_unknown_price_is_not_filtered_by_budget():
    import copy
    r = copy.deepcopy(by_id["r04"])          # 範例拉麵 220 元
    r.price = 0                               # 0 = 價格未填
    picks = recommend([r], B, Query("general", budget=80, minutes_available=120),
                      datetime(2026, 11, 17, 12, 0))
    assert [p.restaurant.name for p in picks] == [r.name]
