"""实时事件的跨进程频道按 Redis 库号分开(app/realtime/bus.py)。

Redis 的发布订阅不分库号:两套实例共用一台 Redis、只靠库号隔开时,同一个频道名会把一套实例的
聊天事件推给另一套里 id 相同的人。2026-09-13 本地 4 组并行跑 e2e 撞见过(C 收到了别人私聊的事件)。
"""
import asyncio

from app.realtime import bus


class _Pool:
    def __init__(self, db):
        self.connection_kwargs = {"db": db} if db is not None else {}


class _FakeRedis:
    def __init__(self, db):
        self.connection_pool = _Pool(db)
        self.published = []

    async def publish(self, channel, data):
        self.published.append(channel)


def test_channel_differs_per_redis_db(monkeypatch):
    names = {}
    for db in (0, 5, 13):
        monkeypatch.setattr(bus, "get_redis", lambda db=db: _FakeRedis(db))
        names[db] = bus.channel()
    assert len(set(names.values())) == 3, names
    assert names[0] == "rt:frames:0"


def test_default_db_when_url_has_none(monkeypatch):
    monkeypatch.setattr(bus, "get_redis", lambda: _FakeRedis(None))
    assert bus.channel() == "rt:frames:0"


def test_publish_uses_db_channel(monkeypatch):
    fake = _FakeRedis(7)
    monkeypatch.setattr(bus, "get_redis", lambda: fake)
    monkeypatch.setattr(bus.settings, "realtime_bus", True)
    asyncio.run(bus.publish(direct=[[1, {"t": "x"}]]))
    assert fake.published == ["rt:frames:7"]
