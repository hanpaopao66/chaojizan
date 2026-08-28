"""到店排队:取号 → 叫号 → 过号顺延 → 恢复 → 入座,以及公平性那几条。

## 这条守什么

功能本身(号能取、能叫、能坐)当然要走通,但真正值得一条 e2e 的是
**规则在跑起来的服务上也成立**:

- 买券的人不会被排到前面去;
- 商家叫完号不能立刻标过号;
- 过号是顺延不是作废,两次才转待恢复,而且恢复不作废;
- 放号上限真的会拦人;
- 号的完整流水对**当事人自己**开放 —— 公示里写着「可以自己查」,
  那它就得真的查得到。

在 server/ 目录下运行:python -m tests.e2e_queue
"""
import time

from tests.util import call, demo_shop, login, register_fresh_customer

customer = login("13800000001")
merchant = login("13800000002")
shop = demo_shop()
sid = shop["id"]


def clear_live(token) -> None:
    """把这个账号今天还活着的号全取消。

    **不清的话这条用例只能跑一次**:第二次跑,演示账号在这家店已经有号了,
    第一步取号就撞「一人一店一号」。前提要用例自己造齐,
    不能指望库是干净的(这一批已经在别处栽过)。
    """
    for t in call("GET", "/queue/tickets/mine", token):
        if t["status"] in ("waiting", "called", "pending_restore"):
            call("POST", f"/queue/tickets/{t['ticket_no']}/cancel", token)


def setup_queue(defer=3, cap_mult=3, tables=2, turn=45) -> int:
    """把这家店的排队配好,返回桌型 id。

    桌型用一个**很窄的人数区间**,避开演示库里可能已经存在的桌型 ——
    否则 pick_table_type 挑到别的档,后面的断言全在看另一条队。
    """
    call("PUT", "/queue/settings", merchant, {
        "enabled": True, "cap_multiplier": cap_mult,
        "defer_tables": defer, "notify_ahead": 3})
    existing = call("GET", "/queue/table-types", merchant)
    for t in existing:                      # 清场:历次跑动留下的桌型全停用
        if t["is_active"]:
            call("PATCH", f"/queue/table-types/{t['id']}", merchant,
                 {**{k: t[k] for k in ("name", "seats_min", "seats_max",
                                       "table_count", "turn_minutes")},
                  "is_active": False})
    tt = call("POST", "/queue/table-types", merchant, {
        "name": "四人桌", "seats_min": 3, "seats_max": 4,
        "table_count": tables, "turn_minutes": turn})
    return tt["id"]


def main() -> None:
    clear_live(customer)
    setup_queue()
    print("✓ 商家配好排队:四人桌 2 张、翻台 45 分钟、顺延 3 桌")

    # ---------- 1) 公开可见:不登录也能看这家店排得怎么样 ----------
    pub = call("GET", f"/queue/merchants/{sid}")
    assert pub["enabled"] is True
    assert pub["no_priority"], "店铺页没有声明「不卖插队权」"
    assert pub["wait_basis"] and "向上取整" in pub["wait_basis"], (
        "没有把预计等待的算法说清楚 —— 那个数字就成了黑箱")
    assert pub["rules"]["call_grace_seconds"] > 0
    print(f"✓ 不登录也看得到:{pub['rules']['text'][:24]}…")

    # ---------- 2) 取号 ----------
    t1 = call("POST", f"/queue/merchants/{sid}/take", customer,
              {"party_size": 4})
    assert t1["status"] == "waiting"
    assert t1["table_type"] == "四人桌", f"挑错桌型了:{t1}"
    assert t1["ahead"] == 0, f"第一个取号却不是队头:{t1}"
    assert t1["wait_upper_minutes"] == 45, (
        f"2 张桌、队头,预计上限应该是一轮 45 分钟,实际 {t1['wait_upper_minutes']}")
    print(f"✓ 取号 {t1['ticket_no']}:前方 0 桌,最多等 "
          f"{t1['wait_upper_minutes']} 分钟")

    # 一人一店只能有一个号 —— 取号免费,不设这道闸门一个人能占满整条队
    err = call("POST", f"/queue/merchants/{sid}/take", customer,
               {"party_size": 4}, expect_error=True)
    assert err["_error"] == 409, f"同一个人在同一家店取到了第二个号:{err}"
    print("✓ 一人一店一号(取号免费,不拦就能被一个人占满)")

    # 人数超过最大桌 → 说人话,不是 500。
    # **要用新用户**:take_ticket 先查重再挑桌型,拿已经有号的人来试,
    # 撞上的是「你已经有号了」,测不到这一条
    big = register_fresh_customer("大桌")
    err = call("POST", f"/queue/merchants/{sid}/take", big,
               {"party_size": 40}, expect_error=True)
    assert err["_error"] == 409 and "坐不下" in err.get("detail", ""), (
        f"人数坐不下时给的不是人话:{err}")
    print("✓ 人数坐不下时给的是人话")

    # ---------- 3) 买券不能插队 ----------
    #
    # 这一条是整个功能的立场。别人先取号,买券的人后取号,
    # 那买券的人**就该在后面** —— 不管他买了多少张券。
    other = register_fresh_customer("排队乙")
    t2 = call("POST", f"/queue/merchants/{sid}/take", other, {"party_size": 4})
    assert t2["ahead"] == 1, f"后取号的人却不在后面:{t2}"

    deals = call("GET", f"/vouchers?merchant_id={sid}")
    if deals:
        d = deals[0]
        p = call("POST", f"/vouchers/{d['id']}/purchase", other, {})
        call("POST", f"/vouchers/purchases/{p['purchase_no']}/pay/mock", other)
        after = next(x for x in call("GET", "/queue/tickets/mine", other)
                     if x["ticket_no"] == t2["ticket_no"])
        assert after["ahead"] == 1, (
            f"买了券之后位置往前挪了({t2['ahead']} → {after['ahead']}) —— "
            f"这就是在卖插队权")
        print("✓ 买了团购券之后位置没变(券只代表钱先付了,与先来后到无关)")
    else:
        print("• 演示店没有在售券,跳过买券那一步(位置断言仍在上面)")

    # ---------- 4) 叫号,以及商家不能秒过号 ----------
    call("POST", f"/queue/tickets/{t1['ticket_no']}/call", merchant)
    err = call("POST", f"/queue/tickets/{t1['ticket_no']}/pass", merchant,
               expect_error=True)
    assert err["_error"] == 409, (
        f"叫号当场就能标过号 —— 客人还在往里走:{err}")
    print("✓ 叫号后立刻标过号被拒(用户过号有代价,商家秒过号也不能零成本)")

    # ---------- 5) 过号是顺延,不是作废 ----------
    #
    # 等过宽限期。这是这条用例里唯一真等的地方,而它等的正是那条规则本身
    grace = pub["rules"]["call_grace_seconds"]
    print(f"  (等 {grace} 秒宽限期 —— 等的就是被测的那条规则)")
    time.sleep(grace + 1)
    r = call("POST", f"/queue/tickets/{t1['ticket_no']}/pass", merchant)
    assert r["status"] == "waiting", f"过号之后号没了:{r}"
    assert r["passed_count"] == 1
    assert "顺延" in r["result"]
    mine = next(x for x in call("GET", "/queue/tickets/mine", customer)
                if x["ticket_no"] == t1["ticket_no"])
    assert mine["ahead"] >= 1, (
        f"顺延之后还在队头({mine['ahead']}) —— 顺延没生效")
    print(f"✓ 过号 → 顺延(号还在,前方变成 {mine['ahead']} 桌)")

    # ---------- 6) 第二次过号转待恢复,恢复不作废 ----------
    call("POST", f"/queue/tickets/{t1['ticket_no']}/call", merchant)
    time.sleep(grace + 1)
    r = call("POST", f"/queue/tickets/{t1['ticket_no']}/pass", merchant)
    assert r["status"] == "pending_restore", f"第二次过号没转待恢复:{r}"
    print("✓ 第二次过号 → 待恢复(不是作废)")

    r = call("POST", f"/queue/tickets/{t1['ticket_no']}/restore", merchant)
    assert r["status"] == "waiting", f"恢复之后号没回队列:{r}"
    print("✓ 到店可恢复,号回到队列")

    # ---------- 7) 入座 ----------
    call("POST", f"/queue/tickets/{t2['ticket_no']}/call", merchant)
    r = call("POST", f"/queue/tickets/{t2['ticket_no']}/seat", merchant)
    assert r["status"] == "seated" and r["seated_at"]
    print("✓ 入座")

    # ---------- 8) 流水对当事人开放 ----------
    #
    # 公示里写着「谁在什么时候动了这个号,你自己查得到」。
    # 这句话要是查不到,它就只是一句口号。
    evs = call("GET", f"/queue/tickets/{t1['ticket_no']}/events", customer)
    actions = [e["action"] for e in evs]
    assert actions[0] == "take"
    for a in ("call", "pass", "restore"):
        assert a in actions, f"流水里没有 {a}:{actions}"
    assert all(e["actor_role"] in ("customer", "merchant", "admin", "system")
               for e in evs)
    print(f"✓ 当事人查得到自己这个号的完整流水({len(evs)} 条:{'/'.join(actions)})")

    # 别人查不到
    err = call("GET", f"/queue/tickets/{t1['ticket_no']}/events", other,
               expect_error=True)
    assert err["_error"] == 403, f"别人也能翻这个号的流水:{err}"
    print("✓ 别人翻不到(流水只对当事人开放)")

    # ---------- 9) 放号上限真的拦人 ----------
    #
    # 桌数 1 × 倍数 1 = 只放 1 个号。不封顶的话队尾等两小时也坐不上
    setup_queue(cap_mult=1, tables=1)
    # `big` 刚才没取到号(人数坐不下),身上是干净的,不用再注册一个
    call("POST", f"/queue/merchants/{sid}/take", big, {"party_size": 4})
    capper = register_fresh_customer("上限乙")
    err = call("POST", f"/queue/merchants/{sid}/take", capper,
               {"party_size": 4}, expect_error=True)
    assert err["_error"] == 409 and "发完" in err.get("detail", ""), (
        f"上限是 1 个号,第 2 个人却取到了:{err}")
    print("✓ 放号上限(1 张桌 × 1 倍)拦住了第 2 个人")

    # ---------- 10) 公示 ----------
    spec = call("GET", "/transparency/queue")
    assert spec["no_priority"]["how_to_check"], "公示没说怎么自己查"
    assert spec["merchant_limits"]["call_grace_seconds"] == grace, (
        "公示里的宽限期和接口实际用的对不上 —— 公示是拿来对着查的")
    assert spec["platform_take"]["text"], "没说排队平台收不收钱"
    assert "pass_ratio" in spec["current"]
    print(f"✓ 公示齐了:过号率 {spec['current']['pass_ratio']:.1%}、"
          f"平均等位 {spec['current']['avg_wait_minutes']} 分钟")

    print("\ne2e_queue 全部通过 ✅")


if __name__ == "__main__":
    main()
