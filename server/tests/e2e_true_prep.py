"""出餐时长以「餐真正到手」为准,不以商家点的那一下为准(#303)。

## 为什么要盯这条链

「预计等餐 X 分钟」是骑手抢单卡上的一个数,骑手照着它决定接不接单。
它来自 `prep_time` 的 P80,而那个数原先是 `accepted → ready` ——
**两个端点都是商家在自己 App 上点的一下**。

也就是说:骑手在用一个由对方单方面生成的数,做一个后果全由自己承担的
决定 —— 到店干等的那段时间没有任何补偿(`flags.wait_comp_on` 现阶段是关的)。

这不是假想。`prep_time.OUTLIER_MIN_MINUTES` 的注释记着实测观察:
"很多店接单后先点出餐、等真做好了再叫骑手"。

现在改成用骑手的 `arrived_shop_at` / `picked_up_at` 校准商家的申报。
这条用例守的是**整条链真的通了**:骑手干等 → 统计变高 → 下一个骑手
在抢单卡上看到更长的等待预期。单测只能证明算法对,证不了这条链没断。

## 这里没有惩罚

不罚款、不扣分、不排名,不动任何一方的钱。君子协定:大家真诚出餐即可,
这个数只负责让"真诚"和"不真诚"看起来不一样。

在 server/ 目录下运行:python -m tests.e2e_true_prep
"""
import asyncio

from sqlalchemy import text

from tests.util import (call, drain_order_pool, login, orderable_dish,
                        register_fresh_rider)

customer = login("13800000001")
merchant = login("13800000002")

# 用一家**新店**,不用演示店 —— 演示店攒了几百单历史样本,
# 这里造的十几单会被稀释掉,P80 纹丝不动,断言就永远看不出差别
shop_name = f"出餐校准测试店-{__import__('time').time():.0f}"


def make_shop() -> int:
    me = call("GET", "/merchants/me", merchant)
    return me["id"]


sid = make_shop()
dish = orderable_dish(call("GET", f"/merchants/{sid}/dishes"))


def _run(coro):
    """跑一个协程,**跑完就 dispose 引擎**。

    引擎的连接绑在创建它的事件循环上,跨 `asyncio.run` 复用会报
    「attached to a different loop」。用例里每次直连库都是独立一轮,
    所以每次都收干净。
    """
    import sys
    sys.path.insert(0, ".")
    from app.db import engine

    async def go():
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(go())


async def _sql(*stmts):
    """一轮事务里跑若干条语句。合并是为了少几次 dispose。"""
    import sys
    sys.path.insert(0, ".")
    from app.db import SessionLocal
    async with SessionLocal() as db:
        for stmt, params in stmts:
            await db.execute(text(stmt), params)
        await db.commit()


def park_history():
    """把这家店已有的样本挪出 30 天窗口,只留这次造的。

    不删 —— 开发库里那些单还有别的用例在用。挪出窗口即可。
    """
    _run(_sql(
        ("""UPDATE order_events SET created_at = created_at - interval '400 days'
             WHERE order_id IN (SELECT id FROM orders WHERE merchant_id = :m)""",
         {"m": sid}),
        ("""UPDATE orders SET accepted_at = accepted_at - interval '400 days'
             WHERE merchant_id = :m AND accepted_at IS NOT NULL""",
         {"m": sid})))


def rider_wait_estimate(rider_token: str) -> float | None:
    """骑手抢单卡上这家店的「预计等餐」。"""
    pool = call("GET", "/riders/available-orders?with_meta=true", rider_token)
    for it in pool["items"]:
        if it.get("merchant_id") == sid:
            return it.get("est_wait_minutes")
    return None


def run_one(rider_token: str, *, ready_after: int, wait_minutes: int) -> str:
    """跑完整一单。

    ready_after: 商家在接单后第几分钟点「已出餐」(往前推时间戳模拟)
    wait_minutes: 骑手到店后等了多久

    **要跑到 delivered**:骑手同时最多 3 单在途,停在 picked_up 造到
    第 4 单就 409(e2e_early_ready 踩过)。
    """
    no = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/riders/grab/{no}", rider_token)
    call("POST", f"/orders/{no}/transition", rider_token,
         {"to_status": "picked_up", "force": True})
    call("POST", f"/orders/{no}/transition", rider_token,
         {"to_status": "delivered", "handoff": "hand"})
    # 时间戳全部往回摆:接单在 T,出餐在 T+ready_after,
    # 骑手到店在取餐前 wait_minutes
    _run(_sql(
        ("""UPDATE orders SET
                accepted_at = picked_up_at - make_interval(mins => :span),
                arrived_shop_at = picked_up_at - make_interval(mins => :w)
             WHERE order_no = :no""",
         {"no": no, "w": wait_minutes,
          "span": max(ready_after, wait_minutes) + 5}),
        ("""UPDATE order_events e SET created_at =
                (SELECT o.accepted_at FROM orders o WHERE o.id = e.order_id)
                + make_interval(mins => CASE WHEN e.to_status = 'ready'
                                             THEN :r ELSE 0 END)
             WHERE e.order_id = (SELECT id FROM orders WHERE order_no = :no)
               AND e.to_status IN ('accepted', 'ready')""",
         {"no": no, "r": ready_after})))
    return no


def main() -> None:
    park_history()
    rider = _run(register_fresh_rider("出餐校准骑手"))

    # 12 单:商家全部**接单 1 分钟就点「已出餐」**(名义出餐 = 1 分钟),
    # 而骑手到店后实实在在等了 25 分钟。
    # MIN_SAMPLES=10,所以要凑够 10 条以上才会给点值
    for _ in range(12):
        run_one(rider, ready_after=1, wait_minutes=25)
    print("✓ 造了 12 单:商家接单 1 分钟就点出餐,骑手每单干等 25 分钟")

    stat = call("GET", "/merchants/me/prep-time", merchant)
    assert stat["samples"] >= 10, f"样本不够,后面的断言没意义:{stat}"
    assert stat["enough"], stat

    # 名义口径下这些单都是 1 分钟,而且会被 OUTLIER_MIN_MINUTES 全部丢掉,
    # 样本数会是 0。现在应当算出接近「25 − 交接耗时」的真实值
    # 造数时:接单在 T、取餐在 T+30、到店在取餐前 25 分钟。
    # 骑手等了 25 分钟 > 交接耗时,所以真实出餐 = 30 − 交接耗时
    from app.services.prep_time import HANDOVER_SECONDS
    want = 30 - HANDOVER_SECONDS / 60
    assert abs(stat["p80"] - want) < 0.6, (
        f"P80={stat['p80']},应当接近 {want:.1f} 分钟 —— "
        f"说明统计还在信商家点的那一下,骑手看到的等待预期是假的")
    print(f"✓ 商家自己那面镜子照出真相:P50={stat['p50']} P80={stat['p80']} "
          f"(名义口径下这些单都是 1 分钟)")

    # 这条才是终点:下一个骑手在抢单卡上看到的数。
    #
    # ⚠️ 抢单池取 200 条算分、**只返回前 50** —— 新单排在最后,
    # 库里池子一满就被截掉,断言会假失败。所以**先清场再下这一单**
    # (顺序反了的话会把自己刚造的单一起清掉,踩过)
    _run(drain_order_pool())
    no = call("POST", "/orders", customer, {
        "merchant_id": sid,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "测试地址", "lat": 30.66, "lng": 104.08,
    })["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    # ⚠️ `est_wait_minutes` **只在骑手有定位时才填**(riders.py 里它在
    # `if rider_pos and ...` 那个分支里)。新注册的骑手没有定位,
    # 不报位置的话这个字段恒为 None,断言会误判成"链子断了"
    call("POST", "/riders/location", rider, {"lat": 30.6605, "lng": 104.0805})
    est = rider_wait_estimate(rider)
    assert est is not None, "新单没进抢单池,拿不到骑手看到的数"
    assert abs(est - want) < 0.6, (
        f"抢单卡上显示「预计等餐 {est} 分钟」,而统计算出的是 {want:.1f} —— "
        f"链子断在统计到抢单卡这一段")
    print(f"✓ 下一个骑手在抢单卡上看到:预计等餐 {est} 分钟(而不是 1 分钟)")

    # 君子协定:没有任何一分钱因此易手
    assert "penalty" not in stat and "fine_cents" not in stat, stat
    assert stat["never_used_for"], "没有把「这个数不做什么」讲清楚"
    print("✓ 不罚款、不扣分、不排名 —— 只是把数说对")
    print("\ne2e_true_prep 全部通过")


main()
