"""骑手新单推送(#114):商家接单 → 附近在线骑手收到通知。

抢单模式最怕的不是没人抢,是没人知道有单可抢。JPush 未配置时
push_to_user 静默跳过,所以这条测的是**触发链路**:
接单后有没有走到推送、推给了谁、有没有重复推。
用 push_logs 验证不行(未配置时订单类推送不留痕),
改用「同一单二次接单不再重复推」的 Redis 幂等键 + 接口不报错来守。
"""
from .util import (ADMIN, CUSTOMER, MERCHANT, RIDER, call, login, unique_spot,
                   _clear_demo_rider_backlog)


def main() -> None:
    _clear_demo_rider_backlog()

    r_token = login(RIDER)
    # 骑手上线并上报位置:不上报位置的骑手按设计不推(宁可漏推,
    # 也不把 20 公里外的单推到人脸上)
    call("POST", "/riders/online", token=r_token, body={"is_online": True})
    shop = call("GET", "/merchants/1")
    call("POST", "/riders/location", token=r_token,
         body={"lat": shop["lat"], "lng": shop["lng"]})
    print(f"✓ 骑手已上线并上报位置(在 {shop['name']} 附近)")

    # 下一单
    c_token = login(CUSTOMER)
    lat, lng = unique_spot("push")
    # 挑一个单价够高的在售菜:一份就过起送价,不受库存余量影响
    # 酒类要排除:买酒得先实名(未成年人保护),而演示店最贵的那道
    # 很可能就是酒 —— 撞上就是一个跟本用例毫无关系的 422。
    # stock 为 None 是「不限量」,`or 0` 会把它当成缺货给筛掉
    dishes = [d for d in call("GET", "/merchants/1/dishes")
              if d.get("is_on_sale", True)
              and not d.get("is_alcohol")
              and (d.get("stock") is None or d["stock"] > 0)]
    dishes.sort(key=lambda d: -d["price_cents"])
    dish = dishes[0]
    qty = max(1, -(-2500 // dish["price_cents"]))  # 凑够起送价
    assert dish.get("stock") is None or dish["stock"] >= qty, \
        f"库存不够跑这条用例:{dish}"
    order = call("POST", "/orders", token=c_token, body={
        "merchant_id": 1,
        "items": [{"dish_id": dish["id"], "quantity": qty}],
        "address": "推送测试地址", "lat": lat, "lng": lng,
        "contact_name": "推送", "contact_phone": "13800000001",
    })
    order_no = order["order_no"]
    call("POST", f"/orders/{order_no}/pay/mock", token=c_token)
    print(f"✓ 已下单并支付 {order_no}")

    # 池子里此刻应该还没有这一单(商家没接)
    pool = call("GET", "/riders/available-orders", token=r_token)
    assert order_no not in {o["order_no"] for o in pool}, \
        "商家还没接单,单子就已经进抢单池了"
    print("✓ 商家未接单前,单子不在抢单池(也就不该推送)")

    # 商家接单 —— 触发推送。接口必须正常返回:推送失败绝不能拖垮接单
    m_token = login(MERCHANT)
    accepted = call("POST", f"/orders/{order_no}/transition", token=m_token,
                    body={"to_status": "accepted"})
    assert accepted["status"] == "accepted", accepted
    print("✓ 商家接单成功(推送异常不影响接单主流程)")

    # 现在单子在池里,骑手能看到
    pool = call("GET", "/riders/available-orders", token=r_token)
    assert order_no in {o["order_no"] for o in pool}, \
        "接单后单子没进抢单池"
    print("✓ 接单后单子进入抢单池,骑手可见")

    # 真正的验收:推送流水里出现了这一单推给这个骑手的记录。
    # JPush 未配置时 ok=false(仅记录意图),但触发链路是真的走通了
    a_token = login(ADMIN)
    rider_id = call("GET", "/auth/me", token=r_token)["id"]
    logs = call("GET", f"/admin/push-logs?user_id={rider_id}",
                token=a_token)
    grab_logs = [g for g in logs if g["title"] == "有新单可抢"]
    assert grab_logs, f"接单后骑手没有收到新单推送记录:{logs[:3]}"
    assert "全额归你" in grab_logs[0]["content"], grab_logs[0]
    print(f"✓ 推送流水命中:{grab_logs[0]['content']}")

    # ⚠️ **不能数条数**。/admin/push-logs 只回最近 50 条,而演示骑手的窗口
    # 早被同一个标题撑满(实测 50 条里 48 条是「有新单可抢」)——
    # 再推一条只是把最老的一条挤出去,计数一模一样。
    # 原来写的 `after == before` 因此恒成立:把「出餐也推一遍」注进去,
    # 推送真的发了两条,这条断言照样绿。
    # 改成拿**本次接单那条的 id 当游标**,只看它之后有没有新的 ——
    # 与 e2e_p3_touch.py 里那条注释同一个道理(那边按本次运行的唯一内容匹配)。
    cursor = max(g["id"] for g in grab_logs)

    # 出餐不该再推一遍(单子早在池里了,再推是骚扰)
    ready = call("POST", f"/orders/{order_no}/transition", token=m_token,
                 body={"to_status": "ready"})
    assert ready["status"] == "ready", ready
    logs = call("GET", f"/admin/push-logs?user_id={rider_id}",
                token=a_token)
    dup = [g for g in logs
           if g["title"] == "有新单可抢" and g["id"] > cursor]
    assert not dup, (
        f"出餐又推了一遍新单:接单那条 id={cursor},之后又多出 "
        f"{[(g['id'], g['content'][:24]) for g in dup]}")
    print(f"✓ 出餐流转正常,且没有重复推送(游标 id>{cursor} 无新增)")

    # 收尾:把单子抢掉送完,别留在池里顶住下次测试的在途额度
    call("POST", f"/riders/grab/{order_no}", token=r_token)
    for status in ("picked_up", "delivered"):
        call("POST", f"/orders/{order_no}/transition", token=r_token,
             body={"to_status": status})
    print("✓ 测试单已送达,不留积压")

    print("\n全部通过:骑手新单推送链路")


if __name__ == "__main__":
    main()
