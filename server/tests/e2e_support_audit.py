"""客服工单 + 每日账务自检验证。

工单:三端提交 → 平台回复/关闭 → 用户可见全部往来;开放工单限流。
自检:补账把缺账/未冲账清零;直连数据库篡改一条入账 → 必须被抓出来,
      而且全局恒等式同步报红;恢复后本次运行不留新问题。

**自检这半段对基线取差,不断言「问题数 == 0」** —— 理由写在 tests/util.py
末尾那段注释里,一句话是:挂账类检查只增不减,清库只能让它绿一天。

在 server/ 目录下运行:python -m tests.e2e_support_audit
"""
import asyncio

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import (ADMIN, CUSTOMER, MERCHANT, RIDER, audit_fingerprint,
                        audit_regressions, call, demo_shop, login,
                        orderable_dish)

#: 补账(/admin/audit/backfill)负责清零的三条 —— 这三条必须真的为 0
BACKFILLABLE = ("merchant_earning_missing", "rider_earning_missing",
                "reversal_missing")

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
err = call("POST", "/tickets", customer, {"content": "太短"}, expect_error=True, retry_429=False)
assert err["_error"] == 422
print("✓ 内容太短被拒(422)")

err = call("GET", "/admin/tickets", customer, expect_error=True, retry_429=False)
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
           {"reply": "再补一句"}, expect_error=True, retry_429=False)
assert err["_error"] == 409
print("✓ 关闭后不能再回复(409)")

# 开放工单限流:3 个未回复就不许再提
close_open_tickets()
for i in range(3):
    call("POST", "/tickets", customer, {"content": f"限流测试工单 {i},请忽略"})
err = call("POST", "/tickets", customer,
           {"content": "第 4 个应该被限流"}, expect_error=True, retry_429=False)
assert err["_error"] == 429
print("✓ 3 个开放工单后限流(429)")
close_open_tickets()

# ---------- 账务自检 ----------
err = call("POST", "/admin/audit/run", customer, expect_error=True, retry_429=False)
assert err["_error"] == 403
print("✓ 非管理员不能触发自检(403)")

# 结算功能上线前的老订单可能缺账,先补齐再要求恒等
call("POST", "/admin/audit/backfill", admin)
result = call("POST", "/admin/audit/run", admin)
left = [p for p in result["detail"] if p["check"] in BACKFILLABLE]
assert not left, f"补账后仍有缺账/未冲账:{left}"
baseline = audit_fingerprint(result["detail"])
baseline_checks = {c for c, _ in baseline}
print(f"✓ 补账后缺账与未冲账清零;存量基线 {len(baseline)} 条({sorted(baseline_checks)})")

# 走一遍完整订单,拿到一条真实的商家入账
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = demo_shop()
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


# 篡改一分钱 → 自检必须抓出来。
#
# **try/finally 不是装饰。** 中间任何一条断言挂掉,这一分钱就永久留在开发库里,
# 从此每次自检都多一条 merchant_earning_mismatch + 一条 global_identity_mismatch,
# 而下一个人看到的是"基线里本来就有这两条"—— 一次失败的运行污染所有后续运行
tamper(+1)
try:
    result = call("POST", "/admin/audit/run", admin)
    caught = [p for p in result["detail"] if no in p["detail"]]
    assert caught, result["detail"]
    delta = audit_fingerprint(result["detail"]) - baseline
    assert ("merchant_earning_mismatch", no) in delta, delta
    # 一行入账被改,Σ商家净额当然也就对不上了 —— 全局恒等式必须同步报红,
    # 否则说明规则 7 把这单从加总里摘出去了(那是最坏的一种"绿")。
    # 判"现在红着"而不是"这次新红的":基线里万一本来就有,那是另一件事,
    # 不该让这条断言跟着假红
    assert "global_identity_mismatch" in {p["check"] for p in result["detail"]}, \
        "改了一行商家入账,全局恒等式却没跟着不平 —— 这单被摘出加总了"
    print(f"✓ 篡改 1 分钱被抓出:{caught[0]['check']}(全局恒等式同步报红)")

    # 告警上看板红条
    dash = call("GET", "/admin/dashboard", admin)
    assert any(no in a["detail"] for a in dash["audit_alerts"])
    print("✓ 告警出现在看板 audit_alerts")
finally:
    tamper(-1)

# 恢复 → 再核对干净;清掉测试告警,不留红条
result = call("POST", "/admin/audit/run", admin)
assert not [p for p in result["detail"] if no in p["detail"]], result["detail"]
# 「没新增」按**检查项种类**判,不按逐条差集:后台清扫随时会把某张历史单
# 从 delivered 推到 completed,而逐单类检查只看 completed —— 一条与本用例
# 毫无关系的老单可能正好在基线和这里之间冒出来。判据见 util.audit_regressions
assert not audit_regressions(result["detail"], baseline_checks), \
    f"本次运行新增了自检问题:{audit_regressions(result['detail'], baseline_checks)}"
cleanup_alerts()
dash = call("GET", "/admin/dashboard", admin)
assert not any(no in a["detail"] for a in dash["audit_alerts"])
print("✓ 数据恢复后核对通过,测试告警已清理")

print("\ne2e_support_audit 全部通过 ✅")
