"""消息清扫的接线(DEV-PROMPTS-40 #351):定时消息写好了发送函数却没人调,存进去就再也发不出来 ——
这里守的是「清扫循环真的会调它」,发送本身的行为在 e2e_chat_scheduled。"""
import asyncio


def test_auto_flow_starts_the_social_tick(monkeypatch):
    from app.services import auto_flow, social_sweep

    started = []

    async def fake_tick():
        started.append(1)
        await asyncio.sleep(3600)

    async def fake_forever():
        await asyncio.sleep(0.01)

    monkeypatch.setattr(social_sweep, "social_tick_loop", fake_tick)
    monkeypatch.setattr(auto_flow, "_auto_flow_forever", fake_forever)
    asyncio.run(auto_flow.auto_flow_loop())
    assert started, "清扫主循环没把消息清扫带起来"


def test_social_tick_sends_due_scheduled_messages(monkeypatch):
    from app.routers import chat
    from app.services import social_sweep

    calls = []

    async def fake_send():
        calls.append("send")
        raise asyncio.CancelledError   # 跑一轮就停

    async def fake_uploads(now=None):
        calls.append("uploads")
        return 0

    monkeypatch.setattr(chat, "send_due_scheduled", fake_send)
    monkeypatch.setattr(social_sweep, "sweep_expired_uploads", fake_uploads)
    try:
        asyncio.run(social_sweep.social_tick_loop())
    except asyncio.CancelledError:
        pass
    assert calls == ["send"], calls
    assert social_sweep.TICK_SECONDS <= 5, "定时消息要准:一轮最多 5 秒"
