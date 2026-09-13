"""定时消息(DEV-PROMPTS-40 #351):建、改时间、删、立即发;到点由清扫循环发出去;发不出去时告诉发的人。

「到点发出」这一步在生产由 sweeper 容器里的 social_tick_loop 每 5 秒调一次 send_due_scheduled;
开发实例一般以 AUTO_FLOW_ENABLED=false 起(见 e2e 前置条件),所以这里在测试进程里直接调同一个函数,
连的是同一个库和 Redis —— 发出的事件照样经实时总线推到在线的人。循环确实会调它,守卫是单测
tests/unit/test_social_sweep.py。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.e2e_chat_scheduled
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone

from tests.chat_util import WS, person


def at(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def due() -> int:
    """每次一个新事件循环:连接池绑在创建它的循环上,跑完要 dispose,不然下一次拿到的是上一个循环的连接。"""
    from app.db import engine
    from app.routers.chat import send_due_scheduled

    async def go():
        try:
            return await send_due_scheduled()
        finally:
            await engine.dispose()
    return asyncio.run(go())


def main():
    a, b, c = person(), person(), person()
    print(f"  账号:A={a.id} B={b.id} C={c.id}")
    cid = a.private_with(b)["id"]
    wb = WS(b.token)
    wb.wait_for(lambda f: f.get("t") == "ready")

    # ---- 建、列、改、删 ----
    r = a.post(f"/chat/v1/chats/{cid}/scheduled", {"kind": "text", "text": "过去的时间", "send_at": at(-5)},
               expect_error=True)
    assert r.get("_error") == 422, r
    s1 = a.post(f"/chat/v1/chats/{cid}/scheduled", {"kind": "text", "text": "三秒后见", "send_at": at(3)})
    s2 = a.post(f"/chat/v1/chats/{cid}/scheduled", {"kind": "text", "text": "要删掉的", "send_at": at(3600)})
    s3 = a.post(f"/chat/v1/chats/{cid}/scheduled", {"kind": "text", "text": "改到明天", "send_at": at(60)})
    items = a.get(f"/chat/v1/chats/{cid}/scheduled")["items"]
    assert [x["id"] for x in items] == [s1["id"], s3["id"], s2["id"]], items
    assert b.get(f"/chat/v1/chats/{cid}/scheduled")["items"] == [], "别人看不到我的定时消息"
    a.patch(f"/chat/v1/chats/{cid}/scheduled/{s3['id']}", {"send_at": at(86400)})
    a.delete(f"/chat/v1/chats/{cid}/scheduled/{s2['id']}")
    r = b.delete(f"/chat/v1/chats/{cid}/scheduled/{s3['id']}", expect_error=True)
    assert r.get("_error") == 404, "别人的定时消息删不了"
    print("  ✓ 定时消息:过去的时间 422;按时间排;只有自己看得到、删得了;改时间、删除")

    # ---- 没到点不发,到点发出去 ----
    assert due() == 0 or not any(m["text"] == "三秒后见"
                                 for m in b.get(f"/chat/v1/chats/{cid}/messages")["messages"])
    time.sleep(3.5)
    assert due() >= 1
    ev = wb.wait_for(lambda f: f.get("t") == "ev" and f.get("type") == "msg" and "三秒后见" in str(f),
                     timeout=10)
    assert ev
    msgs = b.get(f"/chat/v1/chats/{cid}/messages")["messages"]
    assert any(m["text"] == "三秒后见" and m["sender"]["id"] == a.id for m in msgs)
    left = [x["id"] for x in a.get(f"/chat/v1/chats/{cid}/scheduled")["items"]]
    assert left == [s3["id"]], left
    print("  ✓ 到点:清扫发出去,B 实时收到,发件人是 A;列表里只剩改到明天的那条")

    # ---- 立即发 ----
    m = a.post(f"/chat/v1/chats/{cid}/scheduled/{s3['id']}/send-now")
    assert m["text"] == "改到明天" and a.get(f"/chat/v1/chats/{cid}/scheduled")["items"] == []
    print("  ✓ 立即发送:马上出现在会话里,定时列表清空")

    # ---- 发不出去:到点时已经不在群里了 ----
    g = c.post("/chat/v1/chats", {"type": "group", "title": "定时测试群", "member_ids": [a.id]})
    s4 = a.post(f"/chat/v1/chats/{g['id']}/scheduled", {"kind": "text", "text": "等我被踢了再发", "send_at": at(2)})
    c.patch(f"/chat/v1/chats/{g['id']}/members/{a.id}", {"action": "ban"})
    time.sleep(2.5)
    due()
    gm = c.get(f"/chat/v1/chats/{g['id']}/messages")["messages"]
    assert not any(x["text"] == "等我被踢了再发" for x in gm), "被移出群之后定时消息不能再发进去"
    sync = a.post("/chat/v1/sync", {"user_pts": 0, "chats": {}})
    evs = [e for e in sync["user_events"] if e.get("type") == "scheduled_failed"]
    assert evs and evs[-1]["data"]["chat_id"] == g["id"], [e.get("type") for e in sync["user_events"]]
    assert "reason" in evs[-1]["data"] and s4["id"]
    print("  ✓ 发不出去(到点时已被移出群):不发,删掉这条,给 A 一个 scheduled_failed 用户事件说明原因")
    wb.close()


if __name__ == "__main__":
    main()
    print("e2e_chat_scheduled 通过")
