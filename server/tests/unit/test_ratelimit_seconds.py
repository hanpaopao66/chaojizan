"""按秒限流(§5.7):「3 秒一条」要真的是上一条之后满 3 秒。

原来一律按固定窗口(time // seconds)计数:两条只隔 0.1 秒、正好跨过窗口边界,
就落进两个窗口、都放过去了。e2e_danmaku 在全量回归里偶发失败就是这个 ——
不是测试不稳,是限流和它公开写的规则不一样。
"""
import asyncio

import pytest
from fastapi import HTTPException

from app import ratelimit


class _FakeRedis:
    """只实现限流用到的几个命令;时间由测试拨"""

    def __init__(self, clock):
        self.clock = clock
        self.store = {}  # key -> (value, 过期时刻 or None)

    def _alive(self, k):
        v = self.store.get(k)
        if v is None:
            return None
        if v[1] is not None and self.clock[0] >= v[1]:
            del self.store[k]
            return None
        return v

    async def set(self, k, v, nx=False, px=None, ex=None):
        if nx and self._alive(k) is not None:
            return None
        ttl = px / 1000 if px is not None else ex
        self.store[k] = (v, None if ttl is None else self.clock[0] + ttl)
        return True

    async def incr(self, k):
        cur = self._alive(k)
        n = (int(cur[0]) if cur else 0) + 1
        self.store[k] = (n, cur[1] if cur else None)
        return n

    async def expire(self, k, seconds):
        cur = self._alive(k)
        if cur:
            self.store[k] = (cur[0], self.clock[0] + seconds)


@pytest.fixture
def clock(monkeypatch):
    now = [3_000_000.0]
    fake = _FakeRedis(now)
    monkeypatch.setattr(ratelimit, "get_redis", lambda: fake)
    monkeypatch.setattr(ratelimit.time, "time", lambda: now[0])
    monkeypatch.setattr(ratelimit.settings, "rate_limit_enabled", True)
    return now


def _passes(scope, limit, seconds):
    try:
        asyncio.run(ratelimit.check_rate_limit_seconds(scope, "7", limit, seconds, "慢点"))
        return True
    except HTTPException as e:
        assert e.status_code == 429 and e.detail == "慢点"
        return False


def test_one_per_three_seconds_across_window_boundary(clock):
    """第一条在窗口末尾、第二条隔 0.1 秒落进下一个窗口:固定窗口会放过,冷却不放"""
    clock[0] = 3_000_002.95  # 3_000_000 能被 3 整除,这里离下一个窗口还差 0.05 秒
    assert _passes("danmaku", 1, 3)
    clock[0] += 0.1
    assert not _passes("danmaku", 1, 3), "跨过窗口边界的第二条也得拦下"
    clock[0] += 2.85  # 离第一条 2.95 秒
    assert not _passes("danmaku", 1, 3)
    clock[0] += 0.06  # 离第一条满 3 秒
    assert _passes("danmaku", 1, 3)


def test_rejected_attempt_does_not_extend_cooldown(clock):
    """被拦下的那次不重新计时:否则一直点就一直发不出去"""
    assert _passes("video_comment", 1, 5)
    for _ in range(4):
        clock[0] += 1
        assert not _passes("video_comment", 1, 5)
    clock[0] += 1.01
    assert _passes("video_comment", 1, 5)


def test_scopes_and_keys_do_not_share_cooldown(clock):
    assert _passes("danmaku", 1, 3)
    assert _passes("video_comment", 1, 3)
    asyncio.run(ratelimit.check_rate_limit_seconds("danmaku", "8", 1, 3))  # 另一个人不受影响


def test_limit_above_one_keeps_fixed_window(clock):
    """每秒 5 条仍按窗口数:同一秒第 6 条拦,下一秒重新数"""
    clock[0] = 3_000_000.1
    for _ in range(5):
        assert _passes("chat_send", 5, 1)
    assert not _passes("chat_send", 5, 1)
    clock[0] += 1
    assert _passes("chat_send", 5, 1)


def test_redis_down_lets_through(monkeypatch):
    """Redis 不可用时放行:限流是防护,不能反过来变成单点故障"""
    class _Down:
        async def set(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(ratelimit, "get_redis", lambda: _Down())
    monkeypatch.setattr(ratelimit.settings, "rate_limit_enabled", True)
    asyncio.run(ratelimit.check_rate_limit_seconds("danmaku", "7", 1, 3))
