"""骑手接单偏好 + 消息中心 + 同店批量取餐(AQ′·AP′·AR)。

## 这一批守的三条

1. **偏好只改他自己看到什么,不改订单本身。** 被挡掉的单还在池子里等
   别人抢,所以要把「被你自己的设置挡掉了几单」摆出来 ——
   悄悄过滤会变成"今天怎么没单",骑手不会想到是自己两个月前设的开关。
2. **消息中心的分类口径按角色分开。** 同一个词对两端含义相反:
   "配送异常"对商家是订单动态,对骑手是要他处理的事;照抄商家的
   排除表,"申诉成立""提现已打款"能不能活下来纯属运气。
3. **批量操作不整体回滚。** 三单里一单状态不对,不该把另外两单打回。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from .util import CUSTOMER, MERCHANT, RIDER, call, login  # noqa: E402
from .util import DEMO_SHOP_ID  # noqa: E402

customer = login(CUSTOMER)
merchant = login(MERCHANT)
rider = login(RIDER)

NEAR = {"lat": 30.6612, "lng": 104.0823}


def set_prefs(**kw):
    return call("PATCH", "/riders/me/preferences", rider, kw)


def pool(with_meta=False):
    q = "?with_meta=true" if with_meta else ""
    return call("GET", f"/riders/available-orders{q}", rider)


def make_order(dish_id, tip_cents=0):
    o = call("POST", "/orders", customer, {
        "merchant_id": DEMO_SHOP_ID,
        "items": [{"dish_id": dish_id, "quantity": 1}],
        "address": "偏好测试地址", **NEAR})
    call("POST", f"/orders/{o['order_no']}/pay/mock", customer)
    call("POST", f"/orders/{o['order_no']}/transition", merchant,
         {"to_status": "accepted"})
    return o["order_no"]


def main():
    # 收尾用:不管断言走到哪一步,偏好都要恢复成不限 ——
    # 演示账号是全套 e2e 共用的,留一个 10 块的下限会让后面
    # 十几个用例的抢单池莫名其妙空掉
    try:
        run()
    finally:
        set_prefs(grab_radius_km=None, grab_min_fee_cents=0,
                  grab_same_way_only=False, grab_avoid_alcohol=False)


def run():
    # ---- 偏好读写与校验 ----
    got = call("GET", "/riders/me/preferences", rider)
    assert set(got) == {"grab_radius_km", "grab_min_fee_cents",
                        "grab_same_way_only", "grab_avoid_alcohol"}, got
    for bad in ({"grab_min_fee_cents": 5000}, {"grab_min_fee_cents": -1},
                {"grab_radius_km": 99}, {"grab_same_way_only": "yes"}):
        err = call("PATCH", "/riders/me/preferences", rider, bad,
                   expect_error=True)
        assert err["_error"] == 422, (bad, err)
    print("✓ 偏好可读可改;越界与类型错一律 422")

    # 单价下限封顶 2000 分是有意的:再高等于"我不接单了",
    # 那该用下线开关,而不是一个看不见的过滤器
    assert set_prefs(grab_min_fee_cents=2000)["grab_min_fee_cents"] == 2000
    print("✓ 单价下限封顶 ¥20 —— 再高就该用下线开关而不是隐形过滤器")

    # ---- 过滤生效,且**挡掉几单要说出来** ----
    dish = [d for d in call("GET", f"/merchants/{DEMO_SHOP_ID}/dishes")
            if d.get("stock", 0) > 3][0]
    no = make_order(dish["id"])

    set_prefs(grab_min_fee_cents=0)
    assert any(o["order_no"] == no for o in pool()), "先确认这单本来看得见"

    set_prefs(grab_min_fee_cents=2000)
    assert not any(o["order_no"] == no for o in pool()), \
        "配送费低于下限的单不该出现在池子里"
    meta = pool(with_meta=True)
    assert meta["filtered_by_prefs"] >= 1, meta
    assert meta["prefs"]["grab_min_fee_cents"] == 2000, meta["prefs"]
    print(f"✓ 单价下限生效,并回报「被你的设置挡掉 {meta['filtered_by_prefs']} 单」")

    # 裸数组这条路不能变形 —— 老版本客户端拿到对象会直接崩
    assert isinstance(pool(), list), "不传 with_meta 必须还是数组"
    print("✓ 不传 with_meta 仍是裸数组(老客户端不炸)")

    set_prefs(grab_min_fee_cents=0)
    assert any(o["order_no"] == no for o in pool()), \
        "把下限关掉,单子应当回到池子里 —— 它从来没有真的消失过"
    print("✓ 关掉偏好订单立刻回来:过滤只影响我看到什么,不影响单本身")

    # ---- 消息中心:角色分开的分类口径 ----
    msgs = call("GET", "/riders/me/messages", rider)
    assert set(msgs) >= {"announcements", "messages", "unread", "page_size"}
    # 允许的分类从**服务端那份定义**里取,不在这里另抄一份 ——
    # 抄一份的下场:服务端加一类,这条断言就红,而它红得毫无意义
    from app.services.message_center import ROLE_RULES
    allowed = set(ROLE_RULES["rider"].categories) | {"system"}
    kinds = {m["kind"] for m in msgs["messages"]}
    assert kinds <= allowed, (kinds, allowed)
    # 订单类不进消息中心:订单页本身就是它们的家
    assert not any("新单" in m["title"] or "催单" in m["title"]
                   for m in msgs["messages"]), \
        [m["title"] for m in msgs["messages"]]
    print(f"✓ 骑手消息中心可读({len(msgs['messages'])} 条),订单类不混进来")

    read = call("POST", "/riders/me/messages/read", rider)
    assert read["ok"] in (True, False)   # Redis 挂了也不该报错
    after = call("GET", "/riders/me/messages", rider)
    assert after["unread"] == 0, f"标记已读后未读该归零:{after['unread']}"
    print("✓ 已读水位落库,未读归零")

    # 商家的水位不能被骑手的覆盖(同一手机号可以两个角色都注册)
    m_msgs = call("GET", "/merchants/me/messages", merchant)
    assert "announcements" in m_msgs, m_msgs
    print("✓ 商家侧消息中心搬到共用实现后照常工作")

    # ---- 同店批量到店 / 批量取餐 ----
    a, b = make_order(dish["id"]), make_order(dish["id"])
    for n in (a, b):
        call("POST", f"/riders/grab/{n}", rider)

    err = call("POST", "/riders/orders/batch-arrived", rider,
               {"merchant_id": 99999999}, expect_error=True)
    assert err["_error"] == 404, err

    r = call("POST", "/riders/orders/batch-arrived", rider,
             {"merchant_id": DEMO_SHOP_ID})
    assert r["ok_count"] >= 2, r
    print(f"✓ 一次到店标记 {r['ok_count']} 单(同一个到店时刻才是事实)")

    # 出餐后批量取餐
    for n in (a, b):
        call("POST", f"/orders/{n}/transition", merchant,
             {"to_status": "ready"})
    r = call("POST", "/riders/orders/batch-picked", rider,
             {"merchant_id": DEMO_SHOP_ID})
    assert r["ok_count"] >= 2, r
    for n in (a, b):
        assert call("GET", f"/orders/{n}", rider)["status"] == "picked_up"
    print(f"✓ 一次取餐 {r['ok_count']} 单,状态各自流转到已取餐")

    # 逐单执行不整体回滚:再点一次,已取餐的那些逐条报原因而不是整批 409
    again = call("POST", "/riders/orders/batch-picked", rider,
                 {"merchant_id": DEMO_SHOP_ID})
    assert isinstance(again.get("items"), list), again
    assert all(not i["ok"] and i.get("reason") for i in again["items"]), again
    print("✓ 重复批量取餐逐单报原因,不整批失败(骑手要的是「哪单还得点」)")

    for n in (a, b):
        call("POST", f"/orders/{n}/transition", rider,
             {"to_status": "delivered"}, expect_error=True)
    call("POST", f"/orders/{no}/transition", customer,
         {"to_status": "cancelled"}, expect_error=True)

    print("\ne2e_rider_prefs 全部通过 ✅")


if __name__ == "__main__":
    main()
