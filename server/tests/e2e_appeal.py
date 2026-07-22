"""判责申诉:售后改判(恢复商家净额)/配送异常改判(骑手消责)/差评改判(隐藏+评分回调)。
时限与防重、审计兼容(改判后规则 6 豁免口径认 platform)。
在 server/ 目录下运行:python -m tests.e2e_appeal
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal, engine
from tests.util import orderable_dish, call, login

merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")

# 新注册用户跑售后场景:演示用户有 30 天 3 次成功售后的风控上限,会挡住测试
customer = call("POST", "/auth/register",
                body={"phone": f"138{int(time.time()) % 100000000:08d}",
                      "password": "123456", "name": "申诉测试用户",
                      "role": "customer"})["token"]

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dishes = call("GET", f"/merchants/{shop['id']}/dishes")
main_dish = orderable_dish(dishes)


def run_order(to="completed"):
    order = call("POST", "/orders", customer, {
        "merchant_id": shop["id"],
        "items": [{"dish_id": main_dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    if to == "picked_up":
        return no
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})
    return no


# ---------- ① 售后判商家责 → 商家申诉 → 改判恢复净额 ----------
no1 = run_order()
after_sale = call("POST", f"/orders/{no1}/after-sale", customer,
                  {"reason": "汤洒了大半(申诉测试)", "images": ["/uploads/demo.jpg"]})
call("POST", f"/after-sales/{after_sale['id']}/accept", merchant, {"reply": "抱歉,退您餐费"})
w0 = call("GET", "/merchants/me/wallet", merchant)

# 用户不能申诉(角色错)
err = call("POST", "/appeals", customer,
           {"target_type": "after_sale", "target_id": after_sale["id"],
            "reason": "我也要申诉一下"}, expect_error=True)
assert err["_error"] == 403

appeal1 = call("POST", "/appeals", merchant,
               {"target_type": "after_sale", "target_id": after_sale["id"],
                "reason": "打包完好有出餐照片,泼洒非我责"})
err = call("POST", "/appeals", merchant,
           {"target_type": "after_sale", "target_id": after_sale["id"],
            "reason": "再申诉一次"}, expect_error=True)
assert err["_error"] == 409
print("✓ 售后申诉提交成功,重复申诉被拒")

rows = call("GET", "/admin/appeals?status=open", admin)
mine = next(x for x in rows if x["id"] == appeal1["id"])
assert "售后判商家责" in mine["target_summary"]
done = call("POST", f"/admin/appeals/{appeal1['id']}/resolve", admin,
            {"result": "overturned", "note": "出餐照片完好,认定配送环节问题"})
assert done["status"] == "overturned"
w1 = call("GET", "/merchants/me/wallet", merchant)
o1 = call("GET", f"/orders/{no1}", customer)
net = (o1["food_cents"] + o1["packing_fee_cents"]
       - o1["discount_cents"] - o1["commission_cents"])
assert w1["total_earned_cents"] == w0["total_earned_cents"] + net, (w0, w1, net)
assert o1["refund_cents"] > 0  # 用户退款不追回,平台认亏
print(f"✓ 售后改判:商家净额 +{net / 100:.2f} 恢复(调整行),用户退款不追回")

# 改判后不可再复核
err = call("POST", f"/admin/appeals/{appeal1['id']}/resolve", admin,
           {"result": "upheld", "note": "重复"}, expect_error=True)
assert err["_error"] == 409

# ---------- ② 配送异常判骑手责 → 骑手申诉 → 改判消责 ----------
no2 = run_order(to="picked_up")
issue = call("POST", "/riders/issues", rider,
             {"order_no": no2, "kind": "food_damaged",
              "note": "路面塌陷摔车(申诉测试)", "photo_url": "/uploads/demo.jpg"})
call("POST", f"/admin/delivery-issues/{issue['id']}/resolve", admin,
     {"action": "refund", "note": "餐损先行赔付"})
appeal2 = call("POST", "/appeals", rider,
               {"target_type": "delivery_issue", "target_id": issue["id"],
                "reason": "市政道路塌陷属不可抗力,有现场照片"})
call("POST", f"/admin/appeals/{appeal2['id']}/resolve", admin,
     {"result": "overturned", "note": "不可抗力,非骑手责任"})


async def check_fault():
    async with SessionLocal() as db:
        fault = await db.scalar(text(
            "SELECT fault FROM after_sales WHERE order_id ="
            " (SELECT id FROM orders WHERE order_no = :no)"), {"no": no2})
    # 多次 asyncio.run:释放连接池防事件循环串台
    await engine.dispose()
    return fault


fault = asyncio.run(check_fault())
assert fault == "platform", fault
print("✓ 配送异常改判:责任从骑手转平台(消责),先行赔付豁免口径保持")

# ---------- ③ 差评 → 商家申诉 → 改判隐藏 + 评分回调 ----------
no3 = run_order()
call("POST", f"/orders/{no3}/review", customer,
     {"merchant_rating": 1, "comment": "故意差评(申诉测试)"})
review_id = call("GET", f"/orders/{no3}/review", customer)["id"]
detail_before = call("GET", f"/merchants/{shop['id']}")
appeal3 = call("POST", "/appeals", merchant,
               {"target_type": "review", "target_id": review_id,
                "reason": "同行恶意差评,订单显示正常送达无投诉"})
call("POST", f"/admin/appeals/{appeal3['id']}/resolve", admin,
     {"result": "overturned", "note": "认定恶意差评"})
public = call("GET", f"/merchants/{shop['id']}/reviews")
assert all(r["id"] != review_id for r in public), "隐藏差评不应出现在公开列表"
own = call("GET", "/merchants/me/reviews", merchant)
hidden_one = next(r for r in own if r["id"] == review_id)
assert hidden_one["hidden"] is True
detail_after = call("GET", f"/merchants/{shop['id']}")
assert detail_after["rating_count"] == detail_before["rating_count"] - 1
print("✓ 差评改判:公开列表隐藏、商家自查可见标记、评分数回调")

# ---------- 时限:超过 72 小时不能申诉 ----------
no4 = run_order()
a4 = call("POST", f"/orders/{no4}/after-sale", customer,
          {"reason": "分量不够(时限测试)", "images": ["/uploads/demo.jpg"]})
call("POST", f"/after-sales/{a4['id']}/accept", merchant, {"reply": "抱歉,退您餐费"})


async def backdate_aftersale():
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE after_sales SET processed_at = now() - interval '4 days' "
            "WHERE id = :id"), {"id": a4["id"]})
        await db.commit()
    await engine.dispose()


asyncio.run(backdate_aftersale())
err = call("POST", "/appeals", merchant,
           {"target_type": "after_sale", "target_id": a4["id"],
            "reason": "超时了还想申诉一下"}, expect_error=True)
assert err["_error"] == 422 and "72" in err["detail"]
print(f"✓ 超过 72 小时被拒:{err['detail']}")

print("\n判责申诉验证通过 🎉(资金口径以 e2e_reversal_audit 回归为准)")
