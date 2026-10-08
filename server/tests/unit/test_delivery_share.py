"""商家承担配送费(2026-10-08):商家出多少、顾客少付多少,骑手拿的不变。"""
from app.services.pricing import merchant_delivery_share_cents as share

PARTS = {"base": 500, "night": 200, "weather": 0, "door": 200, "hardship": 100}


def test_none_set_means_customer_pays_all():
    assert share(PARTS) == 0


def test_fixed_amount():
    assert share(PARTS, fixed_cents=300) == 300


def test_fixed_capped_at_shareable_parts():
    # 只摊距离 / 夜间 / 天气(500 + 200),爬楼费和难度费仍由顾客付
    assert share(PARTS, fixed_cents=5000) == 700


def test_percent_of_shareable_parts():
    assert share(PARTS, pct=50) == 350
    assert share(PARTS, pct=100) == 700
    assert share(PARTS, pct=150) == 700, "比例超过 100 也只能全包,不能倒贴"


def test_fixed_wins_over_percent():
    assert share(PARTS, fixed_cents=100, pct=50) == 100


def test_door_and_hardship_never_shared():
    only_door = {"base": 0, "night": 0, "weather": 0, "door": 300, "hardship": 200}
    assert share(only_door, fixed_cents=500) == 0
    assert share(only_door, pct=100) == 0


def test_empty_parts_for_pickup_or_append():
    assert share({}, fixed_cents=300, pct=50) == 0
