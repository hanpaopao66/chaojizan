"""券/住宿的退款必须落成**退款流水**,不能只改一个状态字段。

## 这条用例在盯什么

外卖那条线退款走 `services.wechat_pay.request_refund`:写一条 `refunds`
流水(金额对账的凭据),再向渠道发起。券和住宿以前**一条都没写** ——
`vouchers.py` 把 `status` 改成 `refunded`、`stays.py` 给 `refund_cents`
赋个值,就算退完了。

模拟支付期这歪打正着地自洽(钱没收也没退),但:
  - mock 通道下 `request_refund` 会正常写流水并置 success,接上就有账可查;
  - 真开微信支付那一刻,这两条线会直接变成「收了钱、标记已退款、钱没退」;
  - 对账自检的规则 5(Σ流水 == refund_cents)查的是 `orders`,
    结构上装不下券和住宿 —— 这两格在覆盖矩阵里是空的。

所以断言的是**流水行本身**,不是接口返回的状态字段:
状态字段正是那个「绿着但没在测」的东西。

## 顺带钉死两条容易反向改错的

1. **没收过的钱不许退。** 券/住宿的「支付超时自动关闭」走的是
   `pending_payment` / `created`(压根没付过),那条路上写退款流水
   等于凭空造一笔平台流出。这里断言它**没有**流水。
2. **到店无房的违约金不走退款通道。** 那条路上
   `refund_cents = 房费 + 首晚30%违约金`,**已经超过用户实付** ——
   微信退款 API 按「退款额 ≤ 原支付额」直接拒。流水只记房费,
   超出的违约金留给转账通道(未接入),自检按这个口径核。

在 server/ 目录下运行:python -m tests.e2e_refund_channels
"""
import asyncio
import random
import time
from datetime import date, timedelta

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from tests.util import ADMIN, call, login

admin_token = login(ADMIN)
today = date.today()
tag = str(int(time.time()))


async def db_all(sql, **params):
    async with SessionLocal() as db:
        return (await db.execute(text(sql), params)).all()


async def db_exec(sql, **params):
    async with SessionLocal() as db:
        await db.execute(text(sql), params)
        await db.commit()


async def flows(biz_no):
    """这笔业务的退款流水。

    **按 out_refund_no 前缀查,不按 biz 列查** —— 这样它在加列之前的
    老库上也跑得动,第一次运行给出的是「一条流水都没有」这种能读懂的红,
    而不是 UndefinedColumn。out_refund_no 的构成是 `{业务单号}-{8位随机}`,
    单号本身是 20 位随机串,不会串到别人头上。
    """
    return await db_all(
        "SELECT amount_cents, status, channel, order_id, reason FROM refunds "
        "WHERE out_refund_no LIKE :p ORDER BY id", p=f"{biz_no}-%")


async def paid_out(biz_no):
    """真的退出去了多少(失败流水不算 —— 钱没动就不能算已退)。"""
    return sum(r.amount_cents for r in await flows(biz_no)
               if r.status != "failed")


async def biz_tag(biz_no):
    """流水行上的业务归属列。加列之后才查得到,所以放在存在性断言之后。"""
    rows = await db_all(
        "SELECT DISTINCT biz_type, biz_id FROM refunds "
        "WHERE out_refund_no LIKE :p", p=f"{biz_no}-%")
    assert len(rows) == 1, rows
    return rows[0].biz_type, rows[0].biz_id


async def row_id(table, col, value):
    return (await db_all(f"SELECT id FROM {table} WHERE {col} = :v",
                         v=value))[0].id


# ---------------- 团购券 ----------------

boss = call("POST", "/auth/register", body={
    "phone": "131" + tag[-8:], "password": "123456", "name": "退款券老板",
    "role": "merchant"})["token"]
vshop = call("POST", "/merchants", boss, {
    "name": f"退款券店-{tag}", "address": "测试路 9 号",
    "lat": 30.6612, "lng": 104.0823, "license_no": "JY99900011188888",
    "license_image_url": "/uploads/license-demo.jpg"})
call("POST", f"/admin/merchants/{vshop['id']}/approve", admin_token)
deal = call("POST", "/vouchers", boss, {
    "title": "退款测试券", "sell_price_cents": 4500,
    "face_value_cents": 5000, "total_count": 10, "per_user_limit": 5})

vcust = call("POST", "/auth/register", body={
    "phone": "130" + tag[-8:], "password": "123456", "name": "退款券客",
    "role": "customer"})["token"]


# ---------------- 住宿 ----------------

hphone = "138" + "".join(str(random.randint(0, 9)) for _ in range(8))
mt = call("POST", "/auth/register", body={
    "phone": hphone, "password": "hotel123", "role": "merchant"})["token"]
hshop = call("POST", "/merchants", token=mt, body={
    "name": f"退款客栈{hphone[-4:]}", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel", "license_no": "91510100MA6TEST11",
    "license_image_url": "https://example.com/biz.jpg",
    "hotel": {"special_license_no": "川公治安 2026-011",
              "special_license_image_url": "https://example.com/sp.jpg"}})
call("POST", f"/admin/merchants/{hshop['id']}/approve", token=admin_token)
call("PATCH", "/merchants/me", token=mt, body={"is_open": True})

cphone = "137" + "".join(str(random.randint(0, 9)) for _ in range(8))
ct = call("POST", "/auth/register", body={
    "phone": cphone, "password": "guest123", "role": "customer"})["token"]


def make_rt(name, policy, until="18:00"):
    rt = call("POST", "/stays/me/room-types", token=mt,
              body={"name": name, "cancel_policy": policy,
                    "free_cancel_until": until})
    call("PUT", "/stays/me/calendar", token=mt, body={
        "room_type_ids": [rt["id"]], "from_date": str(today),
        "to_date": str(today + timedelta(days=30)),
        "price_cents": 10000, "total_qty": 5})
    return rt["id"]


def book(rt_id, ci, co, pay=True, confirm=False):
    o = call("POST", "/stays/orders", token=ct, body={
        "room_type_id": rt_id, "checkin_date": str(ci),
        "checkout_date": str(co), "rooms_qty": 1,
        "guest_name": "退款客", "guest_phone": "13700000011"})
    no = o["order_no"]
    if pay:
        call("POST", f"/stays/orders/{no}/pay/mock", token=ct)
    if confirm:
        call("POST", f"/stays/me/orders/{no}/confirm", token=mt)
    return no


async def main():
    order_nos = []

    # 1) 券:未使用全额退 → 一条 4500 分的成功流水
    p = call("POST", f"/vouchers/{deal['id']}/purchase", vcust)
    pno = p["purchase_no"]
    call("POST", f"/vouchers/purchases/{pno}/pay/mock", vcust)
    call("POST", f"/vouchers/purchases/{pno}/refund", vcust)
    rows = await flows(pno)
    assert len(rows) == 1, f"券退款必须落一条退款流水,实际 {len(rows)} 条"
    assert rows[0].amount_cents == 4500, rows
    assert rows[0].status == "success" and rows[0].channel == "mock", rows
    assert rows[0].order_id is None, "券的流水不属于任何外卖订单"
    assert await biz_tag(pno) == (
        "voucher", await row_id("voucher_purchases", "purchase_no", pno))
    print("✓ 券全额退 → 4500 分退款流水(mock 通道即时 success)")

    # 2) 券:支付超时关闭 —— 钱从来没进来过,一条流水都不该有
    p2 = call("POST", f"/vouchers/{deal['id']}/purchase", vcust)
    pno2 = p2["purchase_no"]
    await db_exec("UPDATE voucher_purchases SET created_at = now() - "
                  "interval '20 minutes' WHERE purchase_no = :n", n=pno2)
    await sweep_once()
    st = (await db_all("SELECT status FROM voucher_purchases "
                       "WHERE purchase_no = :n", n=pno2))[0].status
    assert st == "cancelled", st
    assert await flows(pno2) == [], "未支付关单不该有退款流水(没收过的钱不能退)"
    print("✓ 券支付超时关闭:没收过钱,不造退款流水")

    ci, co = today + timedelta(days=10), today + timedelta(days=12)  # 2 晚 20000
    rt_free = make_rt("退款免费房", "limited_free")
    rt_late = make_rt("退款过时限房", "limited_free", until="00:01")
    rt_strict = make_rt("退款不可退房", "strict")

    # 3) 住宿:时限内取消全额退
    no = book(rt_free, ci, co)
    order_nos.append(no)
    done = call("POST", f"/stays/orders/{no}/cancel", token=ct)
    assert done["refund_cents"] == 20000
    assert await paid_out(no) == 20000, await flows(no)
    assert await biz_tag(no) == ("stay",
                                 await row_id("stay_orders", "order_no", no))
    print("✓ 住宿时限内取消 → 20000 分退款流水")

    # 4) 住宿:过时限扣首晚,流水只记真退的那一半
    no = book(rt_late, today, today + timedelta(days=2))
    order_nos.append(no)
    done = call("POST", f"/stays/orders/{no}/cancel", token=ct)
    assert done["refund_cents"] == 10000 and done["net_cents"] == 10000
    assert await paid_out(no) == 10000, await flows(no)
    print("✓ 住宿过时限取消 → 只退 10000,扣下的首晚不进退款流水")

    # 5) 住宿:不可退档退 0 —— 不写一条 0 分的空流水
    no = book(rt_strict, ci, co)
    order_nos.append(no)
    done = call("POST", f"/stays/orders/{no}/cancel", token=ct)
    assert done["refund_cents"] == 0
    assert await flows(no) == [], "退 0 就不该有流水"
    print("✓ 住宿不可退档:退款额 0,不造空流水")

    # 6) 住宿:商家拒单全额退
    no = book(rt_free, ci, co)
    order_nos.append(no)
    rej = call("POST", f"/stays/me/orders/{no}/reject", token=mt,
               body={"reason": "临时停业"})
    assert rej["refund_cents"] == 20000
    assert await paid_out(no) == 20000, await flows(no)
    print("✓ 住宿商家拒单 → 20000 分退款流水")

    # 7) 住宿:noshow 扣首晚(清扫路径也要落流水)
    no = book(rt_free, ci, co, confirm=True)
    order_nos.append(no)
    await db_exec("UPDATE stay_orders SET checkin_date = :ci, "
                  "checkout_date = :co WHERE order_no = :n",
                  ci=today - timedelta(days=2), co=today, n=no)
    await sweep_once()
    o = call("GET", f"/stays/orders/{no}", token=ct)
    assert o["status"] == "noshow" and o["refund_cents"] == 10000, o
    assert await paid_out(no) == 10000, await flows(no)
    print("✓ 住宿 noshow(自动清扫)→ 10000 分退款流水")

    # 8) 住宿:未支付超时关单 —— 同样一条流水都不该有
    no = book(rt_free, ci, co, pay=False)
    order_nos.append(no)
    await db_exec("UPDATE stay_orders SET created_at = now() - interval "
                  "'20 minutes' WHERE order_no = :n", n=no)
    await sweep_once()
    o = call("GET", f"/stays/orders/{no}", token=ct)
    assert o["status"] == "closed", o
    assert await flows(no) == [], "未支付关单不该有退款流水"
    print("✓ 住宿支付超时关闭:没收过钱,不造退款流水")

    # 9) 到店无房:退款流水**只记房费**,违约金留给转账通道
    no = book(rt_free, today, today + timedelta(days=2), confirm=True)
    order_nos.append(no)
    a = call("POST", f"/stays/orders/{no}/aftersale", token=ct,
             body={"kind": "no_room", "note": "前台说满房"})
    acc = call("POST", f"/stays/me/aftersales/{a['id']}/respond", token=mt,
               body={"accept": True, "note": "超售了"})
    penalty = int(10000 * 0.3)
    assert acc["penalty_cents"] == penalty, acc
    o = call("GET", f"/stays/orders/{no}", token=ct)
    assert o["refund_cents"] == 20000 + penalty and o["net_cents"] == -penalty
    got = await paid_out(no)
    assert got == 20000, (
        f"到店无房只能原路退用户实付的 20000 分,流水却是 {got} —— "
        f"超出的 {penalty} 分违约金退款通道退不了(微信按「退款额 ≤ 原支付额」拒)")
    print(f"✓ 到店无房:流水 20000(房费),违约金 {penalty} 分不走退款通道")

    # 9b) 协商退:走的是同一个售后裁决入口,但金额由商家填 —— 流水按它退,
    #     不是按房费全额(这条分支和到店无房共用一次 refund_to_channel 调用,
    #     金额取错的话两条里只有一条会露馅)
    no = book(rt_strict, today + timedelta(days=5), today + timedelta(days=7))
    order_nos.append(no)
    a = call("POST", f"/stays/orders/{no}/aftersale", token=ct,
             body={"kind": "nego_refund", "note": "行程有变"})
    acc = call("POST", f"/stays/me/aftersales/{a['id']}/respond", token=mt,
               body={"accept": True, "refund_cents": 8000, "note": "退一部分"})
    assert acc["refund_cents"] == 8000, acc
    o = call("GET", f"/stays/orders/{no}", token=ct)
    assert o["refund_cents"] == 8000 and o["net_cents"] == 12000, o
    assert await paid_out(no) == 8000, await flows(no)
    print("✓ 协商退:流水按商家同意的 8000 走,不是房费全额")

    # 10) 自检:券/住宿的退款恒等式对上面每一笔都是绿的
    result = call("POST", "/admin/audit/run", token=admin_token)
    mine = [p for p in result["detail"]
            if any(n in p.get("detail", "") for n in order_nos + [pno, pno2])]
    assert not mine, mine
    print("✓ 自检:本用例造的券/住宿退款一条告警都没有")

    print("\nPASS e2e_refund_channels")


asyncio.run(main())
