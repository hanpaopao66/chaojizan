"""送达段停留时长(#181) + 跑单热力图(#183)。

## 这一批只做一件事:记录

到店等餐时长早就在记(到店 → 取餐),**送达这一段一直是空白**。
而"这个小区难进""这栋写字楼电梯要等十分钟"全部发生在这一段里。

⚠️ 这一批**不产生任何后果**:不进 ETA、不进钱、不进考核。
先让数据跑两周,看分位数稳不稳。

## 用例要守住的三条

1. **幂等**:重复点「我到了」不刷新时间 —— 刷新的话多点一次
   就把停留时长清零了;
2. **不猜**:没点过「我到了」的单,drop_minutes 必须是 null,
   而不是拿别的时刻凑一个出来。凑出来的数会污染分位数,
   而分位数将来要拿去给别人补时;
3. **样本不足不给分位数**:必须能区分"这里确实快"和"我们还不知道"。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import CUSTOMER, MERCHANT, RIDER, call, login  # noqa: E402
from .util import DEMO_SHOP_ID  # noqa: E402
from .util import orderable_dish  # noqa: E402

customer = login(CUSTOMER)
merchant = login(MERCHANT)
rider = login(RIDER)

NEAR = {"lat": 30.6612, "lng": 104.0823}


def take_to_picked(dish_id, **extra):
    o = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish_id, "quantity": 1}],
        "address": "送达段测试地址", **NEAR, **extra})
    no = o["order_no"]
    call("POST", f"/orders/{no}/pay/mock", customer)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "accepted"})
    call("POST", f"/riders/grab/{no}", rider)
    call("POST", f"/orders/{no}/transition", merchant, {"to_status": "ready"})
    call("POST", f"/orders/{no}/transition", rider, {"to_status": "picked_up"})
    return no


def main():
    # ---- 聚合键:同一栋楼的两个人必须落到同一个键 ----
    from app.services.drop_time import MIN_SAMPLE, drop_key, floor_band

    assert floor_band(None) == "?", "没填楼层单独一段 —— 不猜"
    assert floor_band(1) == floor_band(3) != floor_band(6)
    assert floor_band(30) == "16+"
    a = drop_key(30.66120, 104.08230, 6)
    b = drop_key(30.66125, 104.08235, 7)   # 同一栋楼,楼层同段
    assert a == b == "30661:104082:4-8", (a, b)
    # 地址字符串不参与:同一栋楼十个人写十种地址,按字符串聚合永远攒不出样本
    assert drop_key(None, None, 6) is None, "没坐标就不进统计"
    far = drop_key(30.6712, 104.0823, 6)
    assert far != a, "隔一个网格必须是不同的键"
    print(f"✓ 聚合键按坐标网格+楼层段(不看地址字符串);样本门槛 {MIN_SAMPLE}")

    dishes = call("GET", f"/merchants/{DEMO_SHOP_ID}/dishes")
    dish = orderable_dish(dishes, min_stock=6)

    # ---- 没点「我到了」→ 不猜,drop_minutes 必须为空 ----
    no_skip = take_to_picked(dish["id"], floor=6, has_elevator=False)
    call("POST", f"/orders/{no_skip}/transition", rider,
         {"to_status": "delivered"})
    row = call("GET", f"/orders/{no_skip}", rider)
    assert row["arrived_drop_at"] is None, row["arrived_drop_at"]
    print("✓ 没点「我到了」的单不产生时长 —— 凑出来的数会污染分位数")

    # ---- 正常链路:到达 → 送达 → 落时长与聚合键 ----
    no = take_to_picked(dish["id"], floor=6, has_elevator=False)
    r = call("POST", f"/riders/orders/{no}/arrived-drop", rider, NEAR)
    first = r["arrived_drop_at"]
    assert first, r
    time.sleep(1.2)
    again = call("POST", f"/riders/orders/{no}/arrived-drop", rider, NEAR)
    assert again["arrived_drop_at"] == first, \
        "幂等:重复点不该刷新时间,否则多点一次就把时长清零了"
    print("✓ 到达收货点时刻落库,且重复点不刷新(幂等)")

    call("POST", f"/orders/{no}/transition", rider, {"to_status": "delivered"})
    done = call("GET", f"/orders/{no}", rider)
    assert done["drop_minutes"] is not None and done["drop_minutes"] >= 0, done
    print(f"✓ 送达时算出停留时长 {done['drop_minutes']} 分钟并存快照")

    # ---- 离收货点太远点了会被拒 —— 防随手乱点把数据搞脏 ----
    #
    # ⚠️ 必须用**一张没标过到达的新单**。围栏那段在
    # `if order.arrived_drop_at is None:` 里面 —— 拿上面那张已经标过的单
    # 来点,请求走幂等分支直接 200 返回,压根到不了围栏。
    # 这条断言原先写的是 `err.get("_error") in (409, None)`,
    # 把幂等返回的 None 当成通过,于是把围栏整段删掉测试照样全绿。
    far_no = take_to_picked(dish["id"], floor=6, has_elevator=False)
    err = call("POST", f"/riders/orders/{far_no}/arrived-drop", rider,
               {"lat": 31.5, "lng": 105.5}, expect_error=True)
    assert err["_error"] == 409 and "离收货点还有" in err.get("detail", ""), \
        f"围栏没生效:{err}"
    # 而且被拒的那一下**不能落时间戳** —— 落了的话围栏等于只挡了个提示
    assert call("GET", f"/orders/{far_no}", rider)["arrived_drop_at"] is None, \
        "被围栏拒掉却还是把到达时刻记上了"
    print(f"✓ 离收货点太远点不了:{err['detail']}")
    # 走到店内坐标就能点(证明上面拒的是距离,不是这张单本身有问题)
    ok = call("POST", f"/riders/orders/{far_no}/arrived-drop", rider, NEAR)
    assert ok["arrived_drop_at"], ok
    call("POST", f"/orders/{far_no}/transition", rider,
         {"to_status": "delivered"})

    # ---- 配送中才能点;没送到的单点不了 ----
    fresh = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish["id"], "quantity": 1}],
        "address": "送达段测试地址", **NEAR})
    err = call("POST", f"/riders/orders/{fresh['order_no']}/arrived-drop",
               rider, NEAR, expect_error=True)
    assert err["_error"] in (404, 409), err
    call("POST", f"/orders/{fresh['order_no']}/transition", customer,
         {"to_status": "cancelled"}, expect_error=True)
    print("✓ 非配送中的单点不了「我到了」")

    # ---- 样本不足时不给分位数(必须能区分"确实快"和"还不知道")----
    pool = call("GET", "/riders/available-orders", rider)
    for o in pool:
        if o.get("drop_sample", 0) < MIN_SAMPLE:
            assert o.get("drop_p75_minutes") is None, o
    print("✓ 样本不足的点位不给分位数,只给样本数(不拿噪音当结论)")

    # ---- 热力图(#183):只回答历史,样本不足的格子要自己承认 ----
    h = call("GET", "/riders/heatmap", rider)
    assert set(h) >= {"cells", "weekday", "hour", "weeks", "insufficient"}, h
    assert "不是预测" in h["note"], h["note"]
    for c in h["cells"]:
        assert c["enough"] == (c["orders"] >= h["weeks"]), c
        assert c["per_week"] == round(c["orders"] / h["weeks"], 1), c
    # "这里没单"和"我们不知道这里有没有单"是两件事,返回体必须分得开
    assert h["insufficient"] == sum(1 for c in h["cells"] if not c["enough"])
    print(f"✓ 热力图只给历史单量,{h['insufficient']} 个格子标注为数据不够")

    # 热力图和抢单池必须用**同一条**城市隔离规则 —— 热力图更严的话,
    # 图上是冷的、池子里其实有单,骑手会照着一张比现实更冷的图跑
    slot = call("GET", "/riders/heatmap?weekday=5&hour=2&weeks=4", rider)
    assert isinstance(slot["cells"], list)
    assert slot["weekday"] == 5 and slot["hour"] == 2, slot
    print("✓ 可按星期/小时查任意时段(北京时区口径)")

    print("\ne2e_drop_time 全部通过 ✅")


if __name__ == "__main__":
    main()
