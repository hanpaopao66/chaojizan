"""私聊与实时通道 e2e(DEV-PROMPTS-40 #343 #345 #348,不变量 S1 S10)。

两个账号各连一条 /ws/v2(A 再多连一台设备),验证:
收发 1 秒内到达、random_id 幂等、已读双勾、正在输入、回复、编辑与 48 小时窗口、表情回应上限、
只为自己删 / 为双方删(seq 占位不复用)、转发与「转发时附带我的链接」隐私、置顶、会话设置多设备同步、
断线补齐与 reset、并发发送 seq 连续、非成员什么都拿不到、token 不许放 URL。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_chat_private
"""
import json
import random
import threading
import time
from urllib.parse import quote

from tests.chat_util import WS, WS_BASE, ev, person, sql, uev


def main():
    a, b, c = person(), person(), person()
    print(f"  账号:A={a.id} B={b.id} C={c.id}")

    # ---- 连接鉴权:token 只能走第一帧 ----
    from websockets.sync.client import connect
    bad = connect(f"{WS_BASE}/ws/v2?token={a.token}", open_timeout=5)
    t0 = time.time()
    try:
        bad.recv(timeout=8)
        raise AssertionError("不发 auth 帧应该被关掉")
    except Exception:
        pass
    assert bad.close_code == 4401 and time.time() - t0 < 7.5, (bad.close_code, time.time() - t0)
    w = WS("not-a-token")
    time.sleep(0.5)
    assert w.closed_code == 4401 or w.conn.close_code == 4401, "错的 token 要 4401"
    print("  ✓ /ws/v2:URL 里带 token 不认,5 秒内没有 auth 帧就 4401;错 token 4401")

    wa, wa2, wb, wc = WS(a.token), WS(a.token), WS(b.token), WS(c.token)
    for w_ in (wa, wa2, wb, wc):
        w_.wait_for(lambda f: f.get("t") == "ready")

    # ---- 建私聊 ----
    chat = a.private_with(b)
    cid = chat["id"]
    assert chat["type"] == "private" and chat["peer"]["id"] == b.id, chat
    assert chat["title"] == b.name, chat["title"]
    wa.wait_for(uev("chat_join"))
    wb.wait_for(uev("chat_join"))
    assert all(d["id"] != cid for d in b.get("/chat/v1/dialogs")["items"]), \
        "对方还没收到消息时,这个私聊不该出现在他的列表里"

    # ---- 发一条:1 秒内到对方 ----
    t0 = time.time()
    rid = str(random.getrandbits(62))
    m1 = a.post(f"/chat/v1/chats/{cid}/messages", {"random_id": rid, "text": "你好 **B**"})
    got = wb.wait_for(ev("msg", cid), timeout=3)
    assert time.time() - t0 < 1.5, f"消息到达用了 {time.time() - t0:.2f}s"
    assert got["data"]["text"] == "你好 **B**" and got["data"]["sender"]["id"] == a.id
    wa2.wait_for(ev("msg", cid))  # A 的另一台设备也收到
    again = a.post(f"/chat/v1/chats/{cid}/messages", {"random_id": rid, "text": "你好 **B**"})
    assert again["seq"] == m1["seq"], "同一个 random_id 重发必须返回原来那条(§5.4)"
    n = sql("SELECT count(*) FROM chat_messages WHERE chat_id=:c AND random_id=:r",
            {"c": cid, "r": int(rid)}, fetch="scalar")
    assert n == 1, n
    d = next(x for x in b.get("/chat/v1/dialogs")["items"] if x["id"] == cid)
    assert d["unread"] == 1 and d["last_message"]["seq"] == m1["seq"], d
    print(f"  ✓ 发送:{time.time() - t0:.2f}s 内到对方,两台设备都收到;random_id 重发不产生第二条")

    # ---- 已读 ----
    b.post(f"/chat/v1/dialogs/{cid}/read", {"seq": m1["seq"]})
    r = wa.wait_for(ev("read", cid))
    assert r["data"] == {"user_id": b.id, "seq": m1["seq"]}, r
    assert a.get(f"/chat/v1/chats/{cid}")["peer_read_seq"] == m1["seq"]
    assert next(x for x in b.get("/chat/v1/dialogs")["items"] if x["id"] == cid)["unread"] == 0
    print("  ✓ 已读:对方读了之后 A 收到 read 事件(双勾),B 的未读清零")

    # ---- 正在输入 ----
    wb.send({"t": "typing", "chat_id": cid, "action": "typing"})
    t = wa.wait_for(lambda f: f.get("t") == "typing")
    assert t["user_id"] == b.id and t["chat_id"] == cid
    wc.drain(0.5)
    assert not [f for f in wc.seen if f.get("t") == "typing"], "S1:不在会话里的人收到了正在输入"
    print("  ✓ 正在输入:只到会话里的人")

    # ---- 回复 / 编辑 ----
    m2 = b.send(cid, "收到", reply_to_seq=m1["seq"])
    assert m2["reply_to"]["seq"] == m1["seq"] and "你好" in m2["reply_to"]["preview"], m2
    e = a.patch(f"/chat/v1/chats/{cid}/messages/{m1['seq']}", {"text": "你好呀"})
    assert e["text"] == "你好呀" and e["edited_at"], e
    got = wb.wait_for(ev("edit", cid))
    assert got["data"]["text"] == "你好呀"
    sql("UPDATE chat_messages SET created_at = now() - interval '49 hours' "
        "WHERE chat_id=:c AND seq=:s", {"c": cid, "s": m1["seq"]})
    r = a.patch(f"/chat/v1/chats/{cid}/messages/{m1['seq']}", {"text": "再改"}, expect_error=True)
    assert r.get("_error") == 403 and "48" in r["detail"], r
    r = b.patch(f"/chat/v1/chats/{cid}/messages/{m1['seq']}", {"text": "改别人的"},
                expect_error=True)
    assert r.get("_error") == 403
    print("  ✓ 回复带引用摘要;编辑实时同步,48 小时后不能改,别人的不能改")

    # ---- 回应 ----
    for emo in ("👍", "❤️", "🔥"):
        b.post(f"/chat/v1/chats/{cid}/messages/{m2['seq']}/reactions", {"emoji": emo})
    rr = wa.wait_for(ev("react", cid))
    assert rr["data"]["actor"] == b.id
    r = b.post(f"/chat/v1/chats/{cid}/messages/{m2['seq']}/reactions", {"emoji": "😁"},
               expect_error=True)
    assert r.get("_error") == 422 and "3" in r["detail"], r
    msg = a.get(f"/chat/v1/chats/{cid}/messages")["messages"][-1]
    assert {x["emoji"] for x in msg["reactions"]} == {"👍", "❤️", "🔥"}
    assert all(x["me"] is False for x in msg["reactions"]), "A 没点过,me 应该是 false"
    print("  ✓ 表情回应:实时推给对方,每人每条最多 3 个,me 按看的人算")

    # ---- 删除:只为自己 / 为双方 ----
    a.post(f"/chat/v1/chats/{cid}/messages/delete", {"seqs": [m2["seq"]], "revoke": False})
    assert m2["seq"] not in [x["seq"] for x in a.get(f"/chat/v1/chats/{cid}/messages")["messages"]]
    assert m2["seq"] in [x["seq"] for x in b.get(f"/chat/v1/chats/{cid}/messages")["messages"]]
    wa2.wait_for(uev("hide"))
    a.post(f"/chat/v1/chats/{cid}/messages/delete", {"seqs": [m1["seq"]], "revoke": True})
    got = wb.wait_for(ev("del", cid))
    assert got["data"]["seqs"] == [m1["seq"]]
    assert m1["seq"] not in [x["seq"] for x in b.get(f"/chat/v1/chats/{cid}/messages")["messages"]]
    row = sql("SELECT text, media::text FROM chat_messages WHERE chat_id=:c AND seq=:s",
              {"c": cid, "s": m1["seq"]}, fetch="all")[0]
    assert row[0] == "" and row[1] == "[]", f"为双方删除要清掉正文和媒体:{row}"
    m3 = a.send(cid, "新的一条")
    assert m3["seq"] == m2["seq"] + 1, "删掉的 seq 占位,不复用(S10)"
    print("  ✓ 删除:只为自己(我的其他设备同步隐藏)、为双方(对方立即消失、正文清空、seq 不复用)")

    # ---- 转发 + 隐私 ----
    saved = a.post("/chat/v1/chats/saved")
    m4 = b.send(cid, "转发我试试")
    a.post(f"/chat/v1/chats/{cid}/messages/forward",
           {"seqs": [m4["seq"]], "to_chat_ids": [saved["id"]]})
    fw = a.get(f"/chat/v1/chats/{saved['id']}/messages")["messages"][-1]
    assert fw["forward"]["from_user"]["id"] == b.id and fw["text"] == "转发我试试", fw
    b.patch("/social/v1/me", {"privacy": {"forwards": "nobody"}})
    a.post(f"/chat/v1/chats/{cid}/messages/forward",
           {"seqs": [m4["seq"]], "to_chat_ids": [saved["id"]]})
    fw2 = a.get(f"/chat/v1/chats/{saved['id']}/messages")["messages"][-1]
    assert "from_user" not in fw2["forward"] and fw2["forward"]["hidden_name"] == b.name, fw2
    print("  ✓ 转发:带来源;对方关了「转发时附带我的链接」后只剩名字")

    # ---- 置顶 ----
    a.post(f"/chat/v1/chats/{cid}/pins", {"seq": m4["seq"], "pinned": True})
    p = wb.wait_for(ev("pin", cid))
    assert p["data"] == {"seqs": [m4["seq"]], "pinned": True}
    assert [x["seq"] for x in b.get(f"/chat/v1/chats/{cid}/pins")["items"]] == [m4["seq"]]
    svc = [x for x in b.get(f"/chat/v1/chats/{cid}/messages")["messages"] if x["kind"] == "service"]
    assert svc and svc[-1]["service"]["action"] == "pin"
    print("  ✓ 置顶:两边都收到,置顶列表有它,会话里有一条服务消息")

    # ---- 会话设置:多设备同步 ----
    a.patch(f"/chat/v1/dialogs/{cid}", {"pinned": True, "muted_until": 3600,
                                        "draft": {"text": "还没写完"}})
    dd = wa2.wait_for(lambda f: f.get("t") == "uev" and f.get("type") == "dialog"
                      and f["data"].get("draft"))
    assert dd["data"]["draft"]["text"] == "还没写完" and dd["data"]["pinned"] is True, dd
    me_d = next(x for x in a.get("/chat/v1/dialogs")["items"] if x["id"] == cid)
    assert me_d["my"]["pinned"] and me_d["my"]["muted_until"] and me_d["my"]["draft"]
    b.patch(f"/chat/v1/dialogs/{cid}", {"marked_unread": True})
    assert next(x for x in b.get("/chat/v1/dialogs")["items"] if x["id"] == cid)["my"]["marked_unread"]
    b.post(f"/chat/v1/dialogs/{cid}/read", {"seq": 10**6})
    assert not next(x for x in b.get("/chat/v1/dialogs")["items"]
                    if x["id"] == cid)["my"]["marked_unread"]
    print("  ✓ 置顶会话 / 免打扰 / 草稿同步到我的另一台设备;标记未读打开即清除")

    # ---- 断线补齐 ----
    b_pts = b.get(f"/chat/v1/chats/{cid}")["pts"]
    user_pts = b.get("/chat/v1/dialogs")["user_pts"]
    wb.close()
    sent = []
    for i in range(30):
        sent.append(a.send(cid, f"离线第{i}条")["seq"])
        time.sleep(0.21)            # 每人每秒 5 条的限流之内
    s = b.post("/chat/v1/sync", {"user_pts": user_pts, "chats": {str(cid): b_pts}})
    evs = s["chats"][str(cid)]["events"]
    got_seqs = [e["data"]["seq"] for e in evs if e["type"] == "msg"]
    assert got_seqs == sent, (got_seqs[:5], sent[:5])
    assert [e["pts"] for e in evs] == list(range(b_pts + 1, b_pts + 1 + len(evs))), "pts 必须连续"
    # 事件被清理掉一段:回 reset,让客户端重拉
    sql("DELETE FROM chat_events WHERE chat_id=:c AND pts <= :p", {"c": cid, "p": b_pts + 5})
    s = b.post("/chat/v1/sync", {"user_pts": user_pts, "chats": {str(cid): b_pts}})
    assert s["chats"][str(cid)].get("reset") is True, s["chats"][str(cid)]
    print("  ✓ 断线补齐:30 条一条不少、顺序对、pts 连续;事件断档时回 reset")

    # ---- 并发发送:seq 连续 ----
    before = a.get(f"/chat/v1/chats/{cid}")["last_seq"]
    errs = []

    def burst(p_, n_):
        for i in range(n_):
            try:
                p_.send(cid, f"并发{i}")
            except BaseException as e:  # noqa: BLE001
                errs.append(e)
            time.sleep(0.21)            # 每人每秒 5 条的限流之内

    th = [threading.Thread(target=burst, args=(p_, 10)) for p_ in (a, b)]
    for t_ in th:
        t_.start()
    for t_ in th:
        t_.join()
    assert not errs, errs
    seqs = [r[0] for r in sql("SELECT seq FROM chat_messages WHERE chat_id=:c AND seq > :s "
                              "ORDER BY seq", {"c": cid, "s": before}, fetch="all")]
    assert seqs == list(range(before + 1, before + 21)), seqs
    print("  ✓ 两个人同时各发 10 条:seq 连续、不重、不空(S10)")

    # ---- S1:非成员 ----
    for path in (f"/chat/v1/chats/{cid}", f"/chat/v1/chats/{cid}/messages",
                 f"/chat/v1/chats/{cid}/pins", f"/chat/v1/chats/{cid}/search?q={quote('并发')}"):
        r = c.get(path, expect_error=True)
        assert r.get("_error") == 403, (path, r)
    r = c.send(cid, "我能发吗", expect_error=True)
    assert r.get("_error") == 403
    s = c.post("/chat/v1/sync", {"chats": {str(cid): 0}})
    assert s["chats"][str(cid)] == {"gone": True}, s
    leaked = [f for f in wc.drain(0.5) + wc.seen if f.get("chat_id") == cid]
    assert not leaked, f"S1:C 收到了别人私聊的事件:{leaked[:2]}"
    assert "并发" not in json.dumps(c.get(f"/chat/v1/search?q={quote('并发')}"), ensure_ascii=False)
    print("  ✓ S1:C 读、发、补齐、搜索、实时事件,一样都拿不到")

    # ---- 清空与删除会话 ----
    a.post(f"/chat/v1/dialogs/{cid}/clear", {"revoke": False})
    assert a.get(f"/chat/v1/chats/{cid}/messages")["messages"] == []
    assert b.get(f"/chat/v1/chats/{cid}/messages")["messages"], "只为自己清空,对方的还在"
    b.delete(f"/chat/v1/dialogs/{cid}")
    assert all(x["id"] != cid for x in b.get("/chat/v1/dialogs")["items"])
    a.send(cid, "你删了会话,我再发一条")
    assert any(x["id"] == cid for x in b.get("/chat/v1/dialogs")["items"]), \
        "删掉的私聊,对方再发消息要重新出现"
    a.post(f"/chat/v1/dialogs/{cid}/clear", {"revoke": True})
    assert b.get(f"/chat/v1/chats/{cid}/messages")["messages"] == []
    print("  ✓ 清空(只为自己 / 对双方)、删除会话后对方再发会重新出现")

    for w_ in (wa, wa2, wc):
        w_.close()
    print("e2e_chat_private 全部通过 ✅")


if __name__ == "__main__":
    main()
