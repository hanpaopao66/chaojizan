"""商家端出餐时长闭环与经营趋势/诊断(#150-#152)。

验三件事:

1. **闭环通了**:商家看得到自己的实测出餐时长和与承诺值的差距 ——
   在这之前平台替他的慢出餐掏钱赔付,而他零反馈,闭着眼填承诺值;
2. **趋势按周聚合且空周补齐**:空周不补,折线图会把两个空周连成一条直线,
   商家读成"生意平稳",实际是一单没有;
3. **红线钉死在数据结构层**:响应里不许出现任何排名/评分/等级字段 ——
   排名进不了响应,就不可能被界面渲染出来。

在 server/ 目录下运行:python -m tests.e2e_merchant_insight
"""
import asyncio
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from tests.util import call, login, register_fresh_customer

admin = login("13800000000")
ts = int(time.time())

#: 排名类词根。出现在响应的任何一个 key 里都算越线 ——
#: 商家一旦看到排名就会为数字经营,动作从"把菜做好"变成"把数字做好看"
RANK_WORDS = ("rank", "score", "level", "tier", "star", "grade", "badge")


def fresh_merchant(name):
    phone = f"139{random.randrange(10**8, 10**9) % 10**8:08d}"
    call("POST", "/auth/register", body={
        "phone": phone, "password": "123456", "role": "merchant", "name": name})
    # 现注册的账号用**它自己的**密码登录。
    # login() 不传密码时用的是 DEMO_PASSWORD —— 那是给 seed 演示账号
    # (13800000001 等)准备的,CI 里会被随机化。拿它去登一个刚用
    # "123456" 注册出来的账号,必然 401。
    token = login(phone, "123456")
    shop = call("POST", "/merchants", token, {
        "name": name, "address": "洞察测试地址", "lat": 30.66, "lng": 104.08,
        "license_no": f"JY{ts}", "license_image_url": "https://x/lic.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    call("PATCH", "/merchants/me", token, {"is_open": True})
    return token, shop["id"]


async def inject(merchant_id, customer_id, *, days_ago, prep_minutes=None,
                 cents=2000):
    """落一笔完成单;给了 prep_minutes 就补 accepted→ready 两条事件。

    出餐时长是从 OrderEvent 的 accepted→ready 算的(prep_time.py),
    所以要造实测数据就得造事件,不能只造订单。
    """
    from app.db import SessionLocal
    from app.models import Order, OrderEvent
    from app.services.settlement import settle_order
    from app.state_machine import OrderStatus

    created = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=2)
    async with SessionLocal() as db:
        order = Order(
            order_no=uuid.uuid4().hex[:20],
            customer_id=customer_id, merchant_id=merchant_id,
            status=OrderStatus.COMPLETED,
            items=[{"dish_id": 0, "name": "测试面", "options": [],
                    "price_cents": cents, "quantity": 1}],
            food_cents=cents, packing_fee_cents=0, discount_cents=0,
            subsidy_cents=0, promo_note="", delivery_fee_cents=0,
            tip_cents=0, total_cents=cents,
            commission_cents=int(cents * 0.05),
            address="到店自取", lat=30.66, lng=104.08,
            pickup=True, pickup_code="0000",
        )
        db.add(order)
        await db.flush()
        order.created_at = created
        if prep_minutes is not None:
            acc = OrderEvent(order_id=order.id, from_status="paid",
                             to_status="accepted", actor_role="merchant",
                             actor_id=0)
            rdy = OrderEvent(order_id=order.id, from_status="accepted",
                             to_status="ready", actor_role="merchant",
                             actor_id=0)
            db.add_all([acc, rdy])
            await db.flush()
            acc.created_at = created
            rdy.created_at = created + timedelta(minutes=prep_minutes)
        await settle_order(db, order)
        await db.commit()


def walk_keys(obj, out):
    """把响应里所有的 key 摊平 —— 嵌套里藏一个 rank 也要能查出来。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(k)
            walk_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            walk_keys(v, out)


async def main():
    merchant, sid = fresh_merchant(f"洞察测试店-{ts}")
    cust = call("GET", "/auth/me", register_fresh_customer())["id"]

    # ---------- 1. 样本不足时不给假装精确的数 ----------
    for i in range(3):
        await inject(sid, cust, days_ago=1, prep_minutes=20)
    p = call("GET", "/merchants/me/prep-time", merchant)
    assert p["enough"] is False, p
    assert p["p80"] is None, "样本不足还给分位数,就是给假装精确的数"
    assert p["samples"] == 3, p["samples"]
    print(f"✓ 样本 3 < 下限 {p['min_samples']},不给分位数(明说样本还少)")

    # ---------- 2. 样本够了给实测值,且与承诺值的差距算得对 ----------
    # 再补 12 单,出餐时长 10~34 分钟(P80 落在 30 分钟附近)
    for m in (10, 12, 14, 16, 18, 20, 22, 24, 26, 30, 32, 34):
        await inject(sid, cust, days_ago=2, prep_minutes=m)

    call("PATCH", "/merchants/me", merchant, {"promise_ready_minutes": 15})
    p = call("GET", "/merchants/me/prep-time", merchant)
    assert p["enough"] is True, p
    assert p["samples"] == 15, p["samples"]
    assert p["p50"] is not None and p["p80"] is not None
    assert p["p50"] <= p["p80"] <= p["p95"], (p["p50"], p["p80"], p["p95"])
    assert p["promised_minutes"] == 15
    # 差距 = 实测 P80 − 承诺。这是商家最该看到的一个数
    assert abs(p["gap_minutes"] - (p["p80"] - 15)) < 0.01, p
    assert p["gap_minutes"] > 0, "实测普遍慢于 15 分钟,差距该是正的"
    print(f"✓ 实测 P50/P80/P95 = {p['p50']}/{p['p80']}/{p['p95']},"
          f"承诺 15 分,差距 {p['gap_minutes']} 分钟")

    # ---------- 3. 红线:响应里不许有任何排名字段 ----------
    keys = []
    walk_keys(p, keys)
    bad = [k for k in keys for w in RANK_WORDS if w in k.lower()]
    assert not bad, f"出餐时长响应里出现排名类字段:{bad}"
    assert "never_used_for" in p, "红线说明必须随响应下发,界面才能原样显示"
    for word in ("排名", "扣分", "曝光"):
        assert word in p["never_used_for"], p["never_used_for"]
    print(f"✓ 无任何排名字段;红线随响应下发:{p['never_used_for'][:28]}…")

    # 同品类中位数是**参照系不是排名**:给的是中位数,不是"你排第几"
    assert "peer_median_p50" in p
    assert "peer_rank" not in p and "percentile" not in p
    print("✓ 同品类只给中位数(参照系),不给名次")

    # ---------- 4. 趋势:按周聚合,空周补齐不画平线 ----------
    # 造一个中间隔着空周的分布:本周 3 单、3 周前 2 单(中间两周 0 单)
    for _ in range(2):
        await inject(sid, cust, days_ago=21, cents=3000)

    t = call("GET", "/merchants/me/trend", merchant)
    weeks = t["weeks"]
    assert len(weeks) >= 3, weeks
    # 相邻两项必须正好差 7 天 —— 差得多说明中间的空周没补上
    days = [datetime.fromisoformat(weeks[i + 1]["week"])
            - datetime.fromisoformat(weeks[i]["week"])
            for i in range(len(weeks) - 1)]
    assert all(d == timedelta(days=7) for d in days), \
        f"周序列有断档,折线图会把空周连成直线:{[w['week'] for w in weeks]}"
    empty = [w for w in weeks if w["orders"] == 0]
    assert empty, "这组数据本该有空周,一个都没有说明补齐逻辑没生效"
    for w in empty:
        # 0 单的那周客单价必须是 None 而不是 0 ——
        # 0 会被读成"客单价跌到零",实际是"这周没单,无从谈起"
        assert w["avg_cents"] is None, w
    print(f"✓ {len(weeks)} 周连续无断档,其中 {len(empty)} 个空周"
          f"(单量 0、客单价 None 而非 0)")

    # ---------- 5. 趋势也不许有排名 ----------
    keys = []
    walk_keys(t, keys)
    bad = [k for k in keys for w in RANK_WORDS if w in k.lower()]
    assert not bad, f"趋势响应里出现排名类字段:{bad}"
    print("✓ 趋势响应无排名字段(不做同行对比、不做区域榜单)")

    # ---------- 6. 环比只拿完整周比 ----------
    #
    # 这条最容易被改回去:直接 series[-1] vs series[-2] 看着更简单,
    # 但 series[-1] 是本周、还没过完。周二拿两天比上周整七天,
    # 商家每个周一都会看到「单量暴跌」然后白慌一场。
    partial = [w for w in weeks if w["partial"]]
    assert len(partial) == 1 and partial[0] is weeks[-1], \
        f"本周(且只有本周)该标 partial:{[(w['week'], w['partial']) for w in weeks]}"

    if t["compare"]:
        for k in ("orders", "food_cents", "avg_cents", "customers"):
            c = t["compare"][k]
            assert set(c) == {"cur", "prev", "pct"}, c
        # 比较的两周必须都是完整周
        full_weeks = {w["week"] for w in weeks if not w["partial"]}
        assert t["compare"]["week"] in full_weeks, \
            f"环比用了未完成的周:{t['compare']['week']}"
        assert t["compare"]["prev_week"] in full_weeks, t["compare"]
        assert t["compare"]["week"] != weeks[-1]["week"], \
            "环比拿本周(进行中)去比,每个周一都会得出「暴跌」的假结论"
        print(f"✓ 环比用完整周 {t['compare']['prev_week']} → "
              f"{t['compare']['week']},本周(进行中)不参与")

    # ---------- 7. 诊断:估算的必须标估算 ----------
    for c in t["causes"]:
        assert "estimated" in c, f"流失原因没标是否估算:{c}"
        assert "hint" in c and c["hint"], f"只给数字不给「该改什么」:{c}"
    assert "estimate_note" in t
    print(f"✓ 流失诊断 {len(t['causes'])} 项,每项都标了是否估算并给了动作建议")

    # ---------- 8. 权限 ----------
    cust_token = register_fresh_customer()
    for path in ("/merchants/me/prep-time", "/merchants/me/trend"):
        err = call("GET", path, cust_token, expect_error=True)
        assert err["_error"] in (403, 404), (path, err)
    print("✓ 非商家访问被拒")

    print("\n出餐时长闭环 + 经营趋势/诊断 全部通过")


if __name__ == "__main__":
    asyncio.run(main())
