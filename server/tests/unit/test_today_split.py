"""透明中心「今日逐单」每一行的三份钱,加起来必须等于用户实付。

页面上这张表是给怀疑我们的人看的:一行里商家 + 骑手 + 平台对不上用户付的钱,
比不公开还糟。平台补贴(首单立减)是平台自己掏的,所以平台那一份可以是负数。
纯函数,不连库。
"""
from app.routers.transparency import split_order_row


def order(**kw):
    base = {
        "total_cents": 2600, "food_cents": 2100, "packing_fee_cents": 0,
        "discount_cents": 0, "subsidy_cents": 0, "commission_cents": 105,
        "self_delivery": False, "pickup": False, "order_kind": "normal",
    }
    base.update(kw)
    return base


def check_sum(r):
    s = split_order_row(r)
    assert s["merchant"] + s["rider"] + s["platform"] == s["paid"], s
    return s


def test_普通外卖_设计稿那一单():
    # ¥21 的菜 + ¥5 配送费:商家 19.95、骑手 5、平台 1.05
    s = check_sum(order())
    assert (s["merchant"], s["rider"], s["platform"]) == (1995, 500, 105)


def test_商家满减_平台跟着少收():
    # 满 21 减 3:佣金按 18 的 5% = 90;用户付 2300
    s = check_sum(order(total_cents=2300, discount_cents=300, commission_cents=90))
    assert (s["merchant"], s["rider"], s["platform"]) == (1710, 500, 90)


def test_平台补贴_平台那份是佣金减补贴():
    # 首单立减 3 元平台出:商家照收 19.95,平台 1.05 - 3 = -1.95
    s = check_sum(order(total_cents=2300, subsidy_cents=300))
    assert s["merchant"] == 1995 and s["rider"] == 500
    assert s["platform"] == -195


def test_到店自取_没有骑手():
    s = check_sum(order(total_cents=2100, pickup=True))
    assert s["rider"] == 0 and s["merchant"] == 1995


def test_商家自送_配送费归商家():
    s = check_sum(order(self_delivery=True))
    assert s["rider"] == 0 and s["merchant"] == 2495


def test_跑腿单_没有商家_平台收跑腿费的2():
    s = check_sum(order(order_kind="errand_send", total_cents=1200,
                        food_cents=0, commission_cents=24))
    assert (s["merchant"], s["rider"], s["platform"]) == (0, 1176, 24)


def test_帮买_商品款全给骑手_平台只收跑腿费的2():
    # 跑腿费 12 + 预付商品款 30
    s = check_sum(order(order_kind="errand_buy", total_cents=4200,
                        food_cents=0, commission_cents=24))
    assert (s["merchant"], s["rider"], s["platform"]) == (0, 4176, 24)
