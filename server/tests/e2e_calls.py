"""通话信令 e2e(DEV-PROMPTS-40 §5.12,#354)。

不跑真的音视频(那要浏览器 / 手机),只验证服务端这一段:
呼叫 → 响铃 → 接听(被叫的其他设备收到 taken)→ 双向转 ICE → 挂断 → 记录与聊天里的 kind=call;
拒接、45 秒没人接(未接,主叫被叫都收到)、忙线、隐私不让打、拉黑按忙线、一方掉线 20 秒判中断;
TURN 临时凭据的格式。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_calls
"""
import base64
import secrets
import time

from tests.chat_util import WS, person


def cf(a: str, call_id: str | None = None):
    return lambda f: f.get("t") == "call" and f.get("a") == a and (
        call_id is None or f.get("call_id") == call_id)


def ready(w: WS) -> WS:
    w.wait_for(lambda f: f.get("t") == "ready")
    return w


def invite(w: WS, to: int, video: bool = False) -> str:
    call_id = secrets.token_hex(8)
    w.send({"t": "call", "a": "invite", "call_id": call_id, "to": to, "video": video,
            "sdp": "v=0\r\no=- fake offer\r\n"})
    return call_id


def last_call_message(p, other) -> dict:
    chat = p.private_with(other)
    msgs = p.get(f"/chat/v1/chats/{chat['id']}/messages?limit=5")["messages"]
    calls = [m for m in msgs if m["kind"] == "call"]
    assert calls, f"聊天里没有通话记录:{[m['kind'] for m in msgs]}"
    return calls[-1]


def main():
    a, b, c, d = person(), person(), person(), person()
    print(f"  账号:A={a.id} B={b.id} C={c.id} D={d.id}")
    wa, wb, wb2, wc, wd = (ready(WS(x.token)) for x in (a, b, b, c, d))

    # ---- TURN 临时凭据 ----
    ice = a.get("/chat/v1/calls/ice-servers")
    assert ice["ttl"] == 3600 and isinstance(ice["ice_servers"], list), ice
    for s in ice["ice_servers"]:
        if "username" in s:
            exp, uid = s["username"].split(":")
            assert int(uid) == a.id and int(exp) > time.time(), s
            base64.b64decode(s["credential"])
    print("  ✓ ice-servers:有 TURN 时给临时用户名(到期时间:用户)和 HMAC 密码")

    # ---- 打通、挂断 ----
    cid = invite(wa, b.id, video=True)
    inc = wb.wait_for(cf("incoming", cid))
    wb2.wait_for(cf("incoming", cid))
    assert inc["from"]["id"] == a.id and inc["video"] is True and "fake offer" in inc["sdp"], inc
    wb.send({"t": "call", "a": "ringing", "call_id": cid})
    wa.wait_for(cf("ringing", cid))
    wb.send({"t": "call", "a": "accept", "call_id": cid, "sdp": "v=0\r\no=- fake answer\r\n"})
    acc = wa.wait_for(cf("accept", cid))
    assert "fake answer" in acc["sdp"], acc
    wb2.wait_for(cf("taken", cid))
    wa.send({"t": "call", "a": "ice", "call_id": cid, "candidate": {"candidate": "cand-a", "sdpMid": "0"}})
    assert wb.wait_for(cf("ice", cid))["candidate"]["candidate"] == "cand-a"
    wb.send({"t": "call", "a": "ice", "call_id": cid, "candidate": {"candidate": "cand-b", "sdpMid": "0"}})
    assert wa.wait_for(cf("ice", cid))["candidate"]["candidate"] == "cand-b"
    time.sleep(1.2)
    wa.send({"t": "call", "a": "hangup", "call_id": cid})
    wb.wait_for(cf("hangup", cid))
    time.sleep(0.5)
    m = last_call_message(a, b)
    assert m["call"]["call_id"] == cid and m["call"]["state"] == "ended" and m["call"]["video"], m["call"]
    assert m["call"]["duration"] >= 1, m["call"]
    h = b.get("/chat/v1/calls")["items"][0]
    assert h["call_id"] == cid and not h["outgoing"] and h["state"] == "ended" and h["peer"]["id"] == a.id, h
    print("  ✓ 打通:响铃 → 接听(被叫另一台设备收到 taken)→ ICE 双向 → 挂断;聊天里一条通话记录带时长")

    # ---- 拒接 ----
    cid = invite(wa, b.id)
    wb.wait_for(cf("incoming", cid))
    wb.send({"t": "call", "a": "decline", "call_id": cid})
    wa.wait_for(cf("declined", cid))
    wb2.wait_for(cf("taken", cid))
    time.sleep(0.5)
    assert last_call_message(a, b)["call"]["state"] == "declined"
    print("  ✓ 拒接:主叫收到 declined,被叫其他设备停止响铃,记录是「已拒绝」")

    # ---- 忙线 ----
    cid = invite(wa, b.id)
    wb.wait_for(cf("incoming", cid))
    wb.send({"t": "call", "a": "accept", "call_id": cid, "sdp": "answer"})
    wa.wait_for(cf("accept", cid))
    cid2 = invite(wc, b.id)
    wc.wait_for(cf("busy", cid2))
    wb.drain(0.5)
    assert all(f.get("call_id") != cid2 for f in wb.seen), "忙线时被叫不该收到第二通来电"
    time.sleep(0.5)
    assert last_call_message(c, b)["call"]["state"] == "busy"
    wb.send({"t": "call", "a": "hangup", "call_id": cid})
    wa.wait_for(cf("hangup", cid))
    print("  ✓ 忙线:正在通话的人再被呼叫,主叫直接收到 busy,被叫那边不响")

    # ---- 隐私、拉黑 ----
    b.patch("/social/v1/me", {"privacy": {"calls": "nobody"}})
    cid = invite(wc, b.id)
    err = wc.wait_for(cf("error", cid))
    assert err["reason"] == "privacy", err
    b.patch("/social/v1/me", {"privacy": {"calls": "everyone"}})
    b.post("/social/v1/blocks", {"user_id": d.id})
    cid = invite(wd, b.id)
    wd.wait_for(cf("busy", cid))
    b.delete(f"/social/v1/blocks/{d.id}")
    print("  ✓ 隐私「谁能给我打电话」拦得住;被拉黑的人打过来一律忙线(不暴露拉黑)")

    # ---- 未接(45 秒)----
    cid = invite(wc, b.id)
    wb.wait_for(cf("incoming", cid))
    t0 = time.time()
    wc.wait_for(cf("missed", cid), timeout=52)
    wb.wait_for(cf("missed", cid), timeout=5)
    assert 43 <= time.time() - t0 <= 52, time.time() - t0
    time.sleep(0.5)
    assert last_call_message(c, b)["call"]["state"] == "missed"
    print("  ✓ 未接:45 秒没人接,两边都收到 missed,聊天里一条「未接」")

    # ---- 掉线 ----
    cid = invite(wc, b.id)
    wb.wait_for(cf("incoming", cid))
    wb.send({"t": "call", "a": "accept", "call_id": cid, "sdp": "answer"})
    wc.wait_for(cf("accept", cid))
    wc.close()
    wb.wait_for(cf("hangup", cid), timeout=30)
    time.sleep(0.5)
    assert last_call_message(b, c)["call"]["state"] == "ended"
    print("  ✓ 掉线:一方所有连接都断了,20 秒没回来就判通话结束,对方收到 hangup")

    for w in (wa, wb, wb2, wd):
        w.close()
    print("e2e_calls 全部通过 ✅")


if __name__ == "__main__":
    main()
