"""M3 资金闭环验证:退款流水 → 售后冲账 → 审计恒等 → 对账单 → 批量打款。

场景:
  1. 完整跑一单到完成(结算入账)
  2. 售后退款(退餐费,配送费已履约不退)→ refunds 流水(模拟通道即时成功)+
     商家冲账负数行,骑手配送费不追回(平台原则)
  3. 审计 7 条恒等式全绿(退款一致性/冲账齐全/全局恒等)
  4. 商家对账单 CSV 含入账和冲账两行
  5. 骑手提现 → 管理员批量打款(凭证号留痕)+ T+1 批次只收昨日前申请
在 server/ 目录下运行:python -m tests.e2e_reversal_audit
"""
import asyncio
import time
import urllib.request

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import EarningKind, MerchantEarning, Order, Refund, RefundStatus, RiderEarning
from tests.util import BASE, call, login, register_fresh_customer

customer = register_fresh_customer()
merchant = login("13800000002")
rider = login("13800000003")
admin = login("13800000000")
print("✓ 四个角色登录成功")

# 历史数据补录(幂等):M3 上线前的退款没有流水/冲账,先补齐再验恒等式
call("POST", "/admin/audit/backfill", admin)

shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
sid = next(m for m in shops if m["name"] == "张记面馆")["id"]
tag = str(int(time.time()))
dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"冲账测试菜-{tag}", "price_cents": 2000, "stock": 50})

call("POST", "/riders/online", rider, {"is_online": True})
call("POST", "/riders/location", rider, {"lat": 30.6605, "lng": 104.0815})


def run_full_order() -> dict:
    """一单跑到完成(已结算)。"""
    order = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "冲账测试地址", "lat": 30.6612, "lng": 104.0823,
    })
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    return call("POST", f"/orders/{no}/transition", customer, {"to_status": "completed"})


order = run_full_order()
no = order["order_no"]
print(f"✓ 订单 {no} 完成并结算,合计 ¥{order['total_cents'] / 100}")


async def db_fetch():
    # 每次新建引擎(NullPool):asyncio.run 每次开新事件循环,复用连接池会跨循环报错
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with AsyncSession(engine) as db:
        o = await db.scalar(select(Order).where(Order.order_no == no))
        earnings = (await db.scalars(
            select(MerchantEarning).where(MerchantEarning.order_id == o.id)
        )).all()
        rider_rows = (await db.scalars(
            select(RiderEarning).where(RiderEarning.order_id == o.id)
        )).all()
        refunds = (await db.scalars(
            select(Refund).where(Refund.order_id == o.id)
        )).all()
        result = (o, earnings, rider_rows, refunds)
    await engine.dispose()
    return result


_, earnings, _, _ = asyncio.run(db_fetch())
assert [e.kind for e in earnings] == [EarningKind.earning], "完成后应只有一条入账行"
net_before = earnings[0].net_cents
print(f"✓ 商家入账 {net_before} 分(净额 = 菜价 - 5% 佣金)")

# ---- 售后退款(退餐费,配送费不退)→ 冲账 ----
after_sale = call("POST", f"/orders/{no}/after-sale", customer,
    {"reason": "菜品有异物,要求退款", "images": ["/uploads/demo-evidence.jpg"]})
call("POST", f"/after-sales/{after_sale['id']}/accept", merchant, {"reply": "非常抱歉,退您餐费"})

o, earnings, rider_rows, refunds = asyncio.run(db_fetch())
assert o.refund_cents == o.total_cents - o.delivery_fee_cents, \
    "售后应退餐费部分(配送费已履约不退)"
kinds = sorted(e.kind.value for e in earnings)
assert kinds == ["earning", "reversal"], f"应有入账+冲账两行,实际 {kinds}"
reversal = next(e for e in earnings if e.kind == EarningKind.reversal)
assert reversal.net_cents == -net_before, "冲账负数行应与入账相加归零"
assert sum(e.net_cents for e in earnings) == 0, "商家该单净额应归零"
print("✓ 商家冲账:入账+负数行相加归零,账本只追加未修改")

assert len(rider_rows) == 1 and rider_rows[0].kind == EarningKind.earning, \
    "骑手配送费不追回(配送已完成,平台原则)"
print(f"✓ 骑手配送费 {rider_rows[0].amount_cents} 分保留(用户不退这部分,平台零倒贴)")

assert len(refunds) == 1, "应有一条退款流水"
assert refunds[0].status == RefundStatus.success and refunds[0].channel == "mock"
assert refunds[0].amount_cents == o.refund_cents, "流水金额 == 订单退款汇总"
print(f"✓ 退款流水 {refunds[0].out_refund_no}(mock 通道,success)")

# ---- 售后不可重复处理 ----
err = call("POST", f"/after-sales/{after_sale['id']}/accept", merchant,
           {"reply": "再退一次"}, expect_error=True)
assert err["_error"] == 409
print("✓ 售后不可重复处理(409),不会重复退款/重复冲账")

# ---- 审计:7 条恒等式 ----
problems = call("POST", "/admin/audit/run", admin)["detail"]
mine = [p for p in problems if no in p.get("detail", "")]
assert not mine, f"审计发现本单问题:{mine}"
bad_checks = {p["check"] for p in problems} & {"refund_mismatch", "reversal_missing",
                                               "global_identity_mismatch"}
assert not bad_checks, f"审计新恒等式不平:{problems}"
print(f"✓ 审计通过(共 {len(problems)} 条历史告警,均与本单无关且非资金恒等类)")

# ---- 商家对账单 CSV ----
req = urllib.request.Request(f"{BASE}/merchants/me/finance/statement.csv?days=7")
req.add_header("Authorization", f"Bearer {merchant}")
csv_text = urllib.request.urlopen(req).read().decode()
lines = [ln for ln in csv_text.splitlines() if no in ln]
assert len(lines) == 2 and any("冲账" in ln for ln in lines), \
    f"对账单应含本单入账+冲账两行,实际 {lines}"
print("✓ 对账单 CSV:入账与冲账两行齐全,商家可下载核对")

# ---- 骑手提现 → 批量打款 ----
wallet = call("GET", "/riders/wallet", rider)
while wallet["balance_cents"] < 1000:  # 最低提现 ¥10,不够就再送几单
    run_full_order()
    wallet = call("GET", "/riders/wallet", rider)
w = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1000})
result = call("POST", "/admin/withdrawals/batch-paid", admin,
              {"ids": [w["id"]], "note": f"测试批次-{tag}"})
assert result["paid"] == 1
mine_w = next(x for x in call("GET", "/riders/withdrawals", rider) if x["id"] == w["id"])
assert mine_w["status"] == "paid" and mine_w["paid_note"] == f"测试批次-{tag}"
print(f"✓ 批量打款:凭证号「{mine_w['paid_note']}」骑手端可见")

# ---- T+1 批量打款:只处理昨天及更早的申请,今天刚提的不动(给财务留核对时间) ----
w2 = call("POST", "/riders/withdrawals", rider, {"amount_cents": 1000})
t1 = call("POST", "/admin/withdrawals/t1-batch-paid", admin, {})
assert "T+1批次-" in t1["note"]
mine_w2 = next(x for x in call("GET", "/riders/withdrawals", rider) if x["id"] == w2["id"])
assert mine_w2["status"] == "pending", "今天刚申请的提现不应进 T+1 批次"
print(f"✓ T+1 批量打款:今日新申请不动(本批 {t1['paid']} 笔均为昨日前),明日自动进批")
# 清场:退掉这笔测试提现,余额回到骑手账上
call("POST", f"/admin/withdrawals/{w2['id']}/reject", admin, {"reason": "T+1 测试清场"})

print("\nM3 资金闭环(退款/冲账/审计/对账单/打款)验证通过 🎉")
