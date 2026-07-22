"""酒类销售限制验证:未实名 422 引导、未成年 422 拒绝、成年通过、
非酒商品不受影响、快照带标记、小票提示行、禁售时段开关。

在 server/ 目录下运行:python -m tests.e2e_alcohol
"""
import time

from tests.util import call, login, register_fresh_customer
from tests.e2e_identity import make_id

merchant = login("13800000002")
admin = login("13800000000")

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]

beer = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"精酿啤酒-{int(time.time())}", "price_cents": 2000,
             "stock": 50, "is_alcohol": True})
assert beer["is_alcohol"] is True
noodle = call("POST", "/merchants/me/dishes", merchant,
              {"name": f"素面-{int(time.time())}", "price_cents": 2000,
               "stock": 50})


def order_body(dish):
    return {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    }


def main():
    # 1) 未实名购酒 422,文案引导实名;非酒商品照常下单
    user = register_fresh_customer()
    err = call("POST", "/orders", user, order_body(beer), expect_error=True)
    assert err["_error"] == 422 and "实名认证" in err["detail"], err
    ok = call("POST", "/orders", user, order_body(noodle))
    assert ok["order_no"]
    print("✓ 未实名购酒 422 引导实名,非酒商品不受影响")

    # 2) 未成年实名后购酒:明确拒绝
    call("POST", "/auth/verify-identity", user,
         {"real_name": "李小朋", "id_no": make_id("20150601", "321")})
    err = call("POST", "/orders", user, order_body(beer), expect_error=True)
    assert err["_error"] == 422 and "未成年人" in err["detail"], err
    print("✓ 未成年实名用户购酒 422:依法不向未成年人售酒")

    # 3) 成年实名:下单成功,快照带 is_alcohol,小票含查验提示行
    adult = register_fresh_customer()
    call("POST", "/auth/verify-identity", adult,
         {"real_name": "王成年", "id_no": make_id("19950505", "456")})
    order = call("POST", "/orders", adult, order_body(beer))
    alcohol_items = [i for i in order["items"] if i.get("is_alcohol")]
    assert alcohol_items, "快照应带酒类标记"

    from app.models import Order as OrderModel
    from app.services.cloud_print import build_ticket
    fake = OrderModel(order_no=order["order_no"], items=order["items"],
                      food_cents=order["food_cents"], packing_fee_cents=0,
                      discount_cents=0, delivery_fee_cents=300,
                      total_cents=order["total_cents"], address="测试地址",
                      lat=0, lng=0, contact_name="王成年",
                      contact_phone="13800000001", pickup=False,
                      pickup_code="", parent_order_no="", remark="",
                      privacy_phone="", scheduled_at=None)
    from datetime import datetime, timezone
    fake.created_at = datetime.now(timezone.utc)
    ticket = build_ticket(fake, "张记面馆")
    assert "查验收件人年龄" in ticket, "小票应含酒类查验提示行"
    ticket_normal = build_ticket(
        type(fake)(order_no="x", items=[{"name": "素面", "price_cents": 2000,
                                         "quantity": 1}],
                   food_cents=2000, packing_fee_cents=0, discount_cents=0,
                   delivery_fee_cents=300, total_cents=2300, address="a",
                   lat=0, lng=0, contact_name="a", contact_phone="1",
                   pickup=False, pickup_code="", parent_order_no="",
                   remark="", privacy_phone="", scheduled_at=None,
                   created_at=fake.created_at), "张记面馆")
    assert "查验收件人年龄" not in ticket_normal
    print("✓ 成年实名购酒成功,快照带标记,小票含查验提示(非酒票无)")

    # 4) 禁售时段:开启全天窗口 → 购酒 409,非酒不受影响;关闭恢复
    call("POST", "/admin/flags/alcohol_curfew_hours", admin,
         {"value": "00:00-23:59"})
    call("POST", "/admin/flags/alcohol_curfew", admin, {"value": "on"})
    try:
        err = call("POST", "/orders", adult, order_body(beer),
                   expect_error=True)
        assert err["_error"] == 409 and "暂停销售酒类" in err["detail"], err
        ok = call("POST", "/orders", adult, order_body(noodle))
        assert ok["order_no"]
    finally:
        call("POST", "/admin/flags/alcohol_curfew", admin, {"value": "off"})
    order = call("POST", "/orders", adult, order_body(beer))
    assert order["order_no"]
    print("✓ 禁售时段:窗口内购酒 409、非酒照常;关闭后恢复")

    print("\ne2e_alcohol 全部通过 ✅")


if __name__ == "__main__":
    main()
