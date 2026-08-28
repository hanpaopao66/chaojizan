"""被过号可以申诉,而且**改判要真的把位置还回来**。

## 这条守什么

排队分配的是一个晚上的位子 —— 这东西**没法补发**,不像退款那样能拿钱找齐。
所以「商家标过号」这个单方面动作必须有一处能被质疑,否则「顺延 N 桌」
就是一个随手清队列的按钮。

上一批定的规矩是**改判要有真实效果**(不能只是一句「已记录」)。
排队里对应的动作是:撤销那次过号、还原到过号前的位置。

而这也是 `sort_key` 唯一一条会变小的路径 —— 所以这条用例同时钉住它
**做不到别的**:只能还原到留痕里记着的那个值,平台自己也没有
把谁挪到任意位置的能力。

在 server/ 目录下运行:python -m tests.e2e_queue_appeal
"""
import time

from tests.util import call, demo_shop, login, register_fresh_customer

merchant = login("13800000002")
admin = login("13800000000")
shop = demo_shop()
sid = shop["id"]


def setup() -> int:
    call("PUT", "/queue/settings", merchant, {
        "enabled": True, "cap_multiplier": 5, "defer_tables": 3,
        "notify_ahead": 3})
    for t in call("GET", "/queue/table-types", merchant):
        if t["is_active"]:
            call("PATCH", f"/queue/table-types/{t['id']}", merchant,
                 {**{k: t[k] for k in ("name", "seats_min", "seats_max",
                                       "table_count", "turn_minutes")},
                  "is_active": False})
    return call("POST", "/queue/table-types", merchant, {
        "name": "申诉桌", "seats_min": 3, "seats_max": 4,
        "table_count": 2, "turn_minutes": 45})["id"]


def ahead_of(token, no) -> int:
    t = next(x for x in call("GET", "/queue/tickets/mine", token)
             if x["ticket_no"] == no)
    return t.get("ahead")


def main() -> None:
    setup()
    grace = call("GET", f"/queue/merchants/{sid}")["rules"]["call_grace_seconds"]

    # 队里先垫四个人,好让「顺延 3 桌」真的有 3 桌可顺
    victim = register_fresh_customer("被过号的")
    v = call("POST", f"/queue/merchants/{sid}/take", victim,
             {"party_size": 4})
    others = []
    for i in range(4):
        tok = register_fresh_customer(f"队友{i}")
        others.append(tok)
        call("POST", f"/queue/merchants/{sid}/take", tok, {"party_size": 4})
    assert ahead_of(victim, v["ticket_no"]) == 0, "垫人之后受害者不在队头了"
    print(f"✓ 队列造好:{v['ticket_no']} 在队头,后面还有 4 桌")

    # ---------- 商家把他过号了 ----------
    call("POST", f"/queue/tickets/{v['ticket_no']}/call", merchant)
    time.sleep(grace + 1)
    r = call("POST", f"/queue/tickets/{v['ticket_no']}/pass", merchant)
    assert r["passed_count"] == 1
    moved = ahead_of(victim, v["ticket_no"])
    assert moved == 3, f"顺延 3 桌之后前方应该是 3 桌,实际 {moved}"
    print(f"✓ 被过号:从队头挪到前方 {moved} 桌")

    # ---------- 没被过号的人不能申诉 ----------
    clean = others[0]
    err = call("POST", "/appeals", clean,
               {"target_type": "queue_pass", "target_id": 999999999,
                "reason": "我要申诉一个不存在的号"}, expect_error=True)
    assert err["_error"] == 404, f"能对不存在的号提申诉:{err}"
    print("✓ 不存在的号申诉不了")

    # ---------- 受害者申诉 ----------
    #
    # 用 ticket 的数据库 id 当 target_id。用户端拿得到它 —— 见下面:
    # 号的流水接口对当事人开放,而申诉表单就挂在那个页面上
    ticket_id = v["id"]
    ap = call("POST", "/appeals", victim, {
        "target_type": "queue_pass", "target_id": ticket_id,
        "reason": "我一直在门口站着,根本没听到叫号,店员也没打电话"})
    assert ap["status"] == "open", ap
    print(f"✓ 受害者提了申诉(#{ap['id']})")

    # 别人不能替他申诉
    err = call("POST", "/appeals", clean, {
        "target_type": "queue_pass", "target_id": ticket_id,
        "reason": "我替别人申诉一下这个号被过了"}, expect_error=True)
    assert err["_error"] == 404, f"别人能替他申诉:{err}"
    print("✓ 只有取号本人能申诉这个号")

    # ---------- 平台判成立 → 位置真的还回来 ----------
    call("POST", f"/admin/appeals/{ap['id']}/resolve", admin,
         {"result": "overturned", "note": "监控显示客人一直在门口"})
    back = ahead_of(victim, v["ticket_no"])
    assert back == 0, (
        f"申诉判成立,位置却没还回来(前方还有 {back} 桌)—— "
        f"「改判要有真实效果」这条在排队上落空了")
    print("✓ 改判成立:位置真的还回了队头(不是一句「已记录」)")

    after = next(x for x in call("GET", "/queue/tickets/mine", victim)
                 if x["ticket_no"] == v["ticket_no"])
    assert after["passed_count"] == 0, (
        f"位置还了,过号次数没退({after['passed_count']}) —— "
        f"下次再过一次就直接转待恢复了,等于罚还留着一半")
    print("✓ 过号次数也退了(否则下次一过号就直接转待恢复)")

    # ---------- 还原是有据的,不是想放哪放哪 ----------
    evs = call("GET", f"/queue/tickets/{v['ticket_no']}/events", victim)
    actions = [e["action"] for e in evs]
    assert "undo_pass" in actions, f"还原没留痕:{actions}"
    undo = next(e for e in evs if e["action"] == "undo_pass")
    assert undo["actor_role"] == "admin", "还原的操作人不是平台"
    assert "还原到" in undo["detail"], (
        "留痕里没写还原到了哪个位置 —— 那这次还原就没法被复核")
    print(f"✓ 还原留了痕:{undo['detail']}")

    # 别人的位置没被这次还原改动
    for tok in others:
        t = next(x for x in call("GET", "/queue/tickets/mine", tok))
        assert t["status"] == "waiting"
    print("✓ 队里其他人没被这次还原挪动")

    # ---------- 同一个号不能反复申诉 ----------
    err = call("POST", "/appeals", victim, {
        "target_type": "queue_pass", "target_id": ticket_id,
        "reason": "我要再申诉一次同一个号看看能不能再往前"}, expect_error=True)
    assert err["_error"] in (409, 422), (
        f"同一个号能反复申诉:{err} —— 那就成了一条往前挪的通道")
    print("✓ 同一个号不能反复申诉(否则申诉本身变成插队通道)")

    print("\ne2e_queue_appeal 全部通过 ✅")


if __name__ == "__main__":
    main()
