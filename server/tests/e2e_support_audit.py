"""客服工单 + 每日账务自检验证。

工单:三端提交 → 平台回复/关闭 → 用户可见全部往来;开放工单限流。
自检:补账后账目恒等 == 0 问题;直连数据库篡改一条入账 → 必须被抓出来。
在 server/ 目录下运行:python -m tests.e2e_support_audit
"""
import asyncio

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import orderable_dish, ADMIN, CUSTOMER, MERCHANT, RIDER, call, login

customer = login(CUSTOMER)
merchant = login(MERCHANT)
rider = login(RIDER)
admin = login(ADMIN)


def close_open_tickets():
    """把演示账号的历史开放工单清掉,保证限流断言可重复。"""
    for t in call("GET", "/admin/tickets?status=open", admin):
        call("POST", f"/admin/tickets/{t['id']}/close", admin)


close_open_tickets()

# ---------- 工单基本流 ----------
err = call("POST", "/tickets", customer, {"content": "太短"}, expect_error=True)
assert err["_error"] == 422
print("✓ 内容太短被拒(422)")

err = call("GET", "/admin/tickets", customer, expect_error=True)
assert err["_error"] == 403
print("✓ 非管理员不能看工单列表(403)")

ticket = call("POST", "/tickets", customer,
              {"content": "订单少送了一双筷子,商家不理我", "contact": ""})
assert ticket["status"] == "open"
assert ticket["contact"] == CUSTOMER, "联系方式默认用注册手机号"
print("✓ 用户提交工单,联系方式默认手机号")

# 三端角色都能提
t_m = call("POST", "/tickets", merchant, {"content": "对账单里有一笔看不懂,求解释"})
t_r = call("POST", "/tickets", rider, {"content": "健康证快到期了,怎么更新?"})
assert t_m["status"] == "open" and t_r["status"] == "open"
print("✓ 商家、骑手同样能提工单")

mine = call("GET", "/tickets/mine", customer)
assert mine[0]["id"] == ticket["id"]

opens = call("GET", "/admin/tickets?status=open", admin)
target = next(t for t in opens if t["id"] == ticket["id"])
assert target["user_phone"] == CUSTOMER and target["role"] == "customer"
print("✓ 管理端列表带手机号和角色快照")

# 看板待办 == 开放工单数
dash = call("GET", "/admin/dashboard", admin)
assert dash["pending"]["tickets"] == len(opens), \
    f"看板待办 {dash['pending']['tickets']} != 列表 {len(opens)}"
print("✓ 看板「待回复工单」与列表一致")

# 回复 → 用户可见;关闭 → 不能再回复
replied = call("POST", f"/admin/tickets/{ticket['id']}/reply", admin,
               {"reply": "已联系商家,补偿 3 元红包,抱歉!"})
assert replied["status"] == "replied" and replied["replied_at"]
mine = call("GET", "/tickets/mine", customer)
assert mine[0]["reply"].startswith("已联系商家")
print("✓ 平台回复,用户端可见")

call("POST", f"/admin/tickets/{ticket['id']}/close", admin)
err = call("POST", f"/admin/tickets/{ticket['id']}/reply", admin,
           {"reply": "再补一句"}, expect_error=True)
assert err["_error"] == 409
print("✓ 关闭后不能再回复(409)")

# 开放工单限流:3 个未回复就不许再提
close_open_tickets()
for i in range(3):
    call("POST", "/tickets", customer, {"content": f"限流测试工单 {i},请忽略"})
err = call("POST", "/tickets", customer,
           {"content": "第 4 个应该被限流"}, expect_error=True)
assert err["_error"] == 429
print("✓ 3 个开放工单后限流(429)")
close_open_tickets()

# ---------- 账务自检 ----------
err = call("POST", "/admin/audit/run", customer, expect_error=True)
assert err["_error"] == 403
print("✓ 非管理员不能触发自检(403)")

# 结算功能上线前的老订单可能缺账,先补齐再要求恒等
call("POST", "/admin/audit/backfill", admin)
result = call("POST", "/admin/audit/run", admin)
assert result["problems"] == 0, f"补账后仍有问题:{result['detail']}"
print("✓ 补账后全量核对通过:0 问题")

# 走一遍完整订单,拿到一条真实的商家入账
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
dishes = call("GET", f"/merchants/{shop['id']}/dishes")
main_dish = orderable_dish(dishes)
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
call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})


async def _exec(sql, params):
    # 每次用完释放连接池:连接池绑定事件循环,跨多个 asyncio.run 会串环
    from app.db import engine
    async with SessionLocal() as db:
        await db.execute(text(sql), params)
        await db.commit()
    await engine.dispose()


def tamper(delta):
    asyncio.run(_exec(
        "UPDATE merchant_earnings SET net_cents = net_cents + :d "
        "WHERE order_no = :no", {"d": delta, "no": no}))


def cleanup_alerts():
    asyncio.run(_exec(
        "DELETE FROM audit_alerts WHERE detail LIKE :p", {"p": f"%{no}%"}))


# 篡改一分钱 → 自检必须抓出来
tamper(+1)
result = call("POST", "/admin/audit/run", admin)
assert result["problems"] >= 1
assert any(no in p["detail"] for p in result["detail"]), result["detail"]
print(f"✓ 篡改 1 分钱被抓出:{result['detail'][0]['check']}")

# 告警上看板红条
dash = call("GET", "/admin/dashboard", admin)
assert any(no in a["detail"] for a in dash["audit_alerts"])
print("✓ 告警出现在看板 audit_alerts")

# 恢复 → 再核对干净;清掉测试告警,不留红条
tamper(-1)
result = call("POST", "/admin/audit/run", admin)
assert result["problems"] == 0
cleanup_alerts()
dash = call("GET", "/admin/dashboard", admin)
assert not any(no in a["detail"] for a in dash["audit_alerts"])
print("✓ 数据恢复后核对通过,测试告警已清理")

print("\ne2e_support_audit 全部通过 ✅")
