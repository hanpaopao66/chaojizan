"""实际起送价 = max(商家自设, 平台起送下限),店铺接口直接给这个数。

原来客户端只拿到商家自设的起送价:设成 0 的店,页面上不写起送(首页卡片甚至
写「起送 ¥0」),凑了 ¥12 的单到结算才被 409 顶回来。现在店铺接口给
effective_min_order_cents,下单也按它拦 —— 客户端显示的「¥15 起送」、
「差 ¥3 起送」和服务端拦的是同一个数。

在 server/ 目录下运行:python -m tests.e2e_min_order_floor
"""
import time

from app.config import settings
from tests.util import call, demo_shop, login, register_fresh_customer

merchant = login("13800000002")
sid = demo_shop()["id"]
FLOOR = settings.min_order_floor_cents


def main() -> None:
    original = call("GET", "/merchants/me", merchant)["min_order_cents"]
    cheap = call("POST", "/merchants/me/dishes", merchant, {
        "name": f"起送测试菜-{int(time.time())}", "price_cents": 500, "stock": 50})
    customer = register_fresh_customer("起送")
    try:
        # 1) 商家没设起送价:接口给平台下限,下单按它拦,拦的话里说的也是这个数
        call("PATCH", "/merchants/me", merchant, {"min_order_cents": 0})
        shop = call("GET", f"/merchants/{sid}")
        assert shop["min_order_cents"] == 0
        assert shop["effective_min_order_cents"] == FLOOR, shop["effective_min_order_cents"]
        listed = [m for m in call("GET", "/merchants?lat=30.6612&lng=104.0823")
                  if m["id"] == sid]
        assert not listed or listed[0]["effective_min_order_cents"] == FLOOR, \
            "列表接口也要带实际起送价(首页卡片按它写「起送 ¥15」)"
        err = call("POST", "/orders", customer, {
            "merchant_id": sid, "items": [{"dish_id": cheap["id"], "quantity": 2}],
            "address": "起送测试地址", "lat": 30.66, "lng": 104.08}, expect_error=True)
        assert err["_error"] == 409 and f"¥{FLOOR / 100:.0f}" in err["detail"], err
        print(f"✓ 起送价设 0:接口给 ¥{FLOOR / 100:.0f}(平台下限),¥10 的单被拒,拒的话里是同一个数")

        # 2) 商家设得比下限高:按商家的
        call("PATCH", "/merchants/me", merchant, {"min_order_cents": FLOOR + 500})
        shop = call("GET", f"/merchants/{sid}")
        assert shop["effective_min_order_cents"] == FLOOR + 500
        print("✓ 商家设得比下限高:实际起送价就是商家设的")
    finally:
        call("PATCH", "/merchants/me", merchant, {"min_order_cents": original})
        call("PATCH", f"/merchants/me/dishes/{cheap['id']}", merchant,
             {"is_on_sale": False})

    print("\ne2e_min_order_floor 全部通过 ✅")


if __name__ == "__main__":
    main()
