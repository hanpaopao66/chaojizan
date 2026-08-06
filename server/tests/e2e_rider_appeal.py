"""骑手申辩链路(第十三批 AL·AM·AN)。

## 这一批要守的是「不对等」

商家早就能对差评申诉,骑手不能 —— 被判超时、收到差评时**完全没有说话
的地方**,而超时的成因里商家出餐慢、地址填错占了相当一部分。

三条咬合:
- AL 到店等餐时长 = 申诉的**证据基础**(没有它,申诉出来也是各说各话);
- AM 申诉通道,证据由系统自动附上(让一个在马路上跑车的人去截图收集
  材料,这个通道就等于不存在);
- AN 楼层补时:爬 6 楼和 1 楼临街是两种活。

另外守两条口径:
- **等餐时长只记录不判罚**(有了它很容易顺手加"扣商家分",不做);
- **申诉成立不加分不补钱** —— 平台没有骑手评分体系,所以没有分可加。
"""
import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402

from .util import ADMIN, CUSTOMER, MERCHANT, call, login  # noqa: E402
from .util import DEMO_SHOP_ID  # noqa: E402

admin = login(ADMIN)
merchant = login(MERCHANT)
customer = login(CUSTOMER)


def new_rider(name: str):
    phone = f"1{random.choice('3589')}{random.randrange(10**8, 10**9)}"
    tok = call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "name": name,
        "role": "rider"})["token"]
    return tok, phone


async def verify_rider(tok):
    """把骑手直接标成已认证(走完整认证流程要传证件照,不是本用例的重点)。"""
    me = call("GET", "/auth/me", tok)
    # 用 ORM 建档:表上 NOT NULL 的列有七八个,裸 SQL 要逐个补,
    # 而且以后加一列这个用例就又挂了
    from datetime import datetime, timezone

    from sqlalchemy import select as _select

    from app.models import RiderProfile, VerifyStatus

    async with SessionLocal() as db:
        p = await db.scalar(_select(RiderProfile).where(
            RiderProfile.rider_id == me["id"]))
        if p is None:
            p = RiderProfile(rider_id=me["id"], real_name="测试骑手")
            db.add(p)
        p.status = VerifyStatus.approved
        p.id_verified_at = datetime.now(timezone.utc)
        await db.commit()
    return me["id"]


def check_floor_eta():
    """AN:楼层加时。**加进给顾客看的 ETA** ——

    平台本来就不因超时处罚骑手(eta_at 只用于给顾客的超时赔付与申诉证据),
    所以没有"骑手判定"可放宽。一个诚实的 35 分钟好过一个乐观的 28 分钟
    再超时赔付。
    """
    from app.services.labor_guard import floor_minutes

    assert floor_minutes(None, None) == 0, "没填就是不加时,我们不猜"
    assert floor_minutes(1, False) == 0, "一楼不算爬楼"
    assert floor_minutes(6, False) == 6, "无电梯 6 楼:每层 1 分钟"
    assert floor_minutes(6, True) == 2, "有电梯按固定 2 分钟"
    assert floor_minutes(20, True) == 2, \
        "20 楼有电梯并不比 5 楼有电梯慢多少"
    assert floor_minutes(99, False) == 30, \
        "填错的楼层不该把 ETA 撑到离谱(封顶 30 层)"
    print("✓ 楼层加时:没填不猜、一楼不算、无电梯按层、有电梯固定、封顶")


async def main():
    check_floor_eta()

    # ---- 地址可以带楼层 ----
    addr = call("POST", "/addresses", customer, {
        "contact_name": "张先生", "contact_phone": "13800001234",
        "address": "天府大道 1 号 3 栋", "lat": 30.6612, "lng": 104.0823,
        "floor": 6, "has_elevator": False})
    assert addr["floor"] == 6 and addr["has_elevator"] is False, addr
    plain = call("POST", "/addresses", customer, {
        "contact_name": "张先生", "contact_phone": "13800001234",
        "address": "科华路 2 号", "lat": 30.6612, "lng": 104.0823})
    assert plain["floor"] is None, "不填就是 null,不是 0"
    print("✓ 地址可填楼层与电梯,不填保持 null")

    # ---- 同一家店、同一个坐标,6 楼无电梯的 ETA 更长 ----
    dishes = call("GET", f"/merchants/{DEMO_SHOP_ID}/dishes")
    dish = [d for d in dishes if d.get("stock", 0) > 3][0]
    base = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "科华路 2 号", "lat": 30.6927, "lng": 104.0823})
    high = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "天府大道 1 号 3 栋", "lat": 30.6927, "lng": 104.0823,
        "floor": 6, "has_elevator": False})
    # ETA 在**支付时**算(payment_core.mark_order_paid → compute_eta),
    # 下单那一刻还没有
    base = call("POST", f"/orders/{base['order_no']}/pay/mock", customer)
    high = call("POST", f"/orders/{high['order_no']}/pay/mock", customer)
    assert base.get("eta_at") and high.get("eta_at"), (base, high)
    # 只断言"不更短"而不是"严格更长":ETA 还要过 clamp_eta_minutes
    # 与 ETA_MIN_MINUTES 两道下限,近距离单的楼层加时会被下限吞掉 ——
    # 那是对的(下限本来就是保护),楼层这一项本身的精确断言在
    # check_floor_eta 里对 floor_minutes 直接做
    assert high["eta_at"] >= base["eta_at"], \
        f"6 楼无电梯的 ETA 不该比平地短:{base['eta_at']} / {high['eta_at']}"
    print(f"✓ 6 楼无电梯 ETA({high['eta_at'][11:16]})不早于平地"
          f"({base['eta_at'][11:16]})—— 诚实的 ETA 好过乐观的再超时")

    for o in (base, high):
        call("POST", f"/orders/{o['order_no']}/transition", customer,
             {"to_status": "cancelled"})

    # ================= AL + AM:等餐时长与申诉 =================
    rider, _ = new_rider(f"申诉骑手{random.randrange(10**4)}")
    await verify_rider(rider)

    order = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "申诉测试地址", "lat": 30.6612, "lng": 104.0823})
    no = order["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)

    # 没到店就申诉? 先看到店标记本身
    early = call("POST", f"/riders/orders/{no}/arrived", rider,
                 {"lat": 31.9, "lng": 121.9}, expect_error=True)
    assert early["_error"] == 409 and "米" in early["detail"], \
        f"离店太远点「我到店了」该拒:{early}"
    print("✓ 离店太远不能标到店(防随手乱点把证据搞脏)")

    call("POST", f"/riders/orders/{no}/arrived", rider)
    again = call("POST", f"/riders/orders/{no}/arrived", rider)
    assert again["order_no"] == no, "重复点应幂等"
    print("✓ 到店已记录,重复点幂等(不刷新时间,否则多点一次就清零)")

    # 等餐几秒后取餐
    await asyncio.sleep(2)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})

    async with SessionLocal() as db:
        r = (await db.execute(text(
            "SELECT arrived_shop_at IS NOT NULL, picked_up_at IS NOT NULL, "
            "extract(epoch from (picked_up_at - arrived_shop_at)) "
            "FROM orders WHERE order_no = :n"), {"n": no})).first()
    assert r[0] and r[1], "到店与取餐时刻都该落库"
    assert r[2] >= 1, f"等餐时长该被算出来:{r[2]} 秒"
    print(f"✓ 等餐时长落库({r[2]:.0f} 秒)—— 申诉的证据基础")

    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})

    # ---- 申诉:说明太短、类型白名单、非本人的单 ----
    bad = call("POST", "/riders/appeals", rider,
               {"order_no": no, "kind": "late", "reason": "冤"},
               expect_error=True)
    assert bad["_error"] == 422, f"说明太短该拒(平台要靠它核实):{bad}"
    bad = call("POST", "/riders/appeals", rider,
               {"order_no": no, "kind": "拉黑商家", "reason": "商家出餐太慢了"},
               expect_error=True)
    assert bad["_error"] == 422, f"类型白名单:{bad}"

    other_rider, _ = new_rider(f"路人骑手{random.randrange(10**4)}")
    await verify_rider(other_rider)
    steal = call("POST", "/riders/appeals", other_rider,
                 {"order_no": no, "kind": "late", "reason": "这不是我的单"},
                 expect_error=True)
    assert steal["_error"] == 404, f"不能申诉别人的单:{steal}"
    print("✓ 申诉:说明必填、类型白名单、只能诉自己的单")

    # ---- 证据由系统自动附上 ----
    a = call("POST", "/riders/appeals", rider, {
        "order_no": no, "kind": "late",
        "reason": "到店后等餐,商家一直没出餐"})
    ev = a["evidence"]
    assert "wait_minutes" in ev, f"等餐时长要自动附上:{ev}"
    assert "distance_m" in ev, f"实际距离要自动附上:{ev}"
    assert "snapshot_at" in ev, "证据是快照,要有取样时刻"
    # 这段口径必须在返回体里 —— 不说清楚骑手会以为申诉能拿到钱
    assert "不加分也不补钱" in a["note"], a["note"]
    print(f"✓ 证据自动附上({', '.join(ev)}),且明说「不加分不补钱」")

    dup = call("POST", "/riders/appeals", rider,
               {"order_no": no, "kind": "late", "reason": "再诉一次试试"},
               expect_error=True)
    assert dup["_error"] == 409, f"一单一诉:{dup}"
    print("✓ 同一单不能重复申诉")

    mine = call("GET", "/riders/appeals", rider)
    assert len(mine["items"]) == 1 and mine["items"][0]["status"] == "pending"
    assert "没有骑手服务分" in mine["note"], mine["note"]
    print("✓ 申诉列表可查进度,口径一致")

    # ---- admin 核定:驳回路径必须真的能走到 ----
    queue = call("GET", "/admin/rider-appeals", admin)
    row = [x for x in queue if x["order_no"] == no][0]
    assert "****" in row["rider_phone"], f"队列里手机号要打码:{row}"
    assert row["evidence"].get("wait_minutes") is not None, \
        "审核员看到的是同一份系统证据,不用两边各说各话"

    call("POST", f"/admin/rider-appeals/{row['id']}/resolve", admin,
         {"accept": False, "note": "e2e:先驳回验证这条路径走得通"})
    after = call("GET", "/riders/appeals", rider)
    assert after["items"][0]["status"] == "rejected", \
        f"accept=false 必须真的驳回(复用无 accept 字段的 schema 会全判成立):{after}"
    print("✓ admin 核定:驳回路径可达(不是每条都判成立)")

    done = call("POST", f"/admin/rider-appeals/{row['id']}/resolve", admin,
                {"accept": True, "note": "重复处理"}, expect_error=True)
    assert done["_error"] == 404, f"已处理的不能重复核定:{done}"
    print("✓ 已核定的申诉不能重复处理")

    print("\ne2e_rider_appeal 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
