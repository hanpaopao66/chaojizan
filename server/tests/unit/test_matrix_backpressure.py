"""午高峰的抢单池:节流锁不许把骑手堵住(#301)。

## 这组测试守什么

腾讯的距离矩阵按**每秒**限流,而且这个 key 严到 0.35 秒的间隔都会撞
(见 routing._RATE_LIMIT_PAUSE)。所以矩阵调用之间强制隔 1.1 秒,
一把进程级的锁串起来。这个设计本身是对的 —— 撞一次限流的代价是
整批回退直线。

问题出在**谁在等这把锁**。缓存格 111 米,骑手骑行大约 20 秒换一格、
换格就要重新问一次;锁全局只放行 0.9 次/秒,大约 18 个移动中的骑手
就能占满。实测 10 个骑手各在不同格,一轮刷新要 **8.3 秒** —— 而客户端
的轮询间隔是 5 秒,请求会越堆越多。

关键的想法是:**路网距离对抢单池只是个更准的数字,不是正确性。**
拿不到就用直线(本来就是既有的兜底口径,前端也一直显示来源),
下一轮再热。让骑手多等 8 秒去换一个更准的距离,这笔账怎么算都不划算。

四件事锁住:

1. 等锁有上限,超了抛 MatrixBusy,不排队;
2. 预热放弃之后,**下游也必须停手**。一屏 42 单是 84 次不受节流约束的
   单点请求,一发就把限流坐实 —— 那比慢更糟;
3. 锁在任何取消路径上都要释放。漏一次就是全体骑手永久退直线,
   而且完全不报错、不自愈;
4. 瞬时失败(限流/超时)不许按持久失败记 30 分钟的负缓存。
"""
import asyncio

import pytest

from app.services import routing


def _run(coro):
    return asyncio.run(coro)


def _fresh_gate(monkeypatch):
    """在**当前**事件循环里新建一把锁替掉模块级那把。

    模块级的 asyncio.Lock 会绑定到第一个碰它的循环,而每个 asyncio.run
    都是新循环 —— 不换的话第二个用到锁的测试就报
    「bound to a different event loop」。生产里进程只有一个循环,
    没这个问题,纯粹是测试隔离。
    """
    gate = asyncio.Lock()
    monkeypatch.setattr(routing, "_matrix_gate", gate)
    return gate


class Test等锁有上限:
    def test_有预算常量且短于轮询间隔(self):
        """骑手 5 秒一刷。等锁比这还久的话,请求只会越堆越多。"""
        assert 0 < routing._MATRIX_WAIT_BUDGET < 1.0

    def test_锁被占住时抛MatrixBusy而不是干等(self, monkeypatch):
        """**必须把 key 和缓存都打桩**,否则这条用例在 CI 上是假绿。

        `route_matrix` 里有两条在碰锁**之前**就返回的路:没配
        `tencent_map_key` 时整批退直线,以及全部命中缓存时直接回
        (那句"别去碰那把锁"正是这次要守的优化)。两条都会让
        `todo` 空掉,于是锁根本没人等,MatrixBusy 自然不抛。

        本地开发机配了 key、缓存又恰好没命中,所以一直是绿的;
        CI 不配 key(那是花钱的外部接口,也不该配),第一次跑就红。
        这条用例要守的是**锁的行为**,不该依赖环境里有没有 key。
        """
        class _NoCache:
            async def get(self, *a, **k): return None
            async def set(self, *a, **k): return None

        class _Boom:
            def __init__(self, *a, **k):
                raise AssertionError("抛 MatrixBusy 之前不该发请求")

        monkeypatch.setattr(routing, "get_redis", lambda: _NoCache())
        monkeypatch.setattr(routing.settings, "tencent_map_key", "x" * 20)
        monkeypatch.setattr(routing.httpx, "AsyncClient", _Boom)

        async def go():
            _fresh_gate(monkeypatch)
            await routing._matrix_gate.acquire()
            try:
                t0 = asyncio.get_event_loop().time()
                with pytest.raises(routing.MatrixBusy):
                    await routing.route_matrix(
                        (30.66, 104.08), [(30.67, 104.09)], "bike")
                return asyncio.get_event_loop().time() - t0
            finally:
                routing._matrix_gate.release()

        waited = _run(go())
        assert waited < routing._MATRIX_WAIT_BUDGET + 0.3, (
            f"等了 {waited:.2f}s —— 说明没按预算放弃,骑手要排队")


class Test锁一定要还回去:
    def test_并发争抢加随机超时不会死锁(self, monkeypatch):
        """这条是防最坏的情况:锁泄漏一次,之后**每个**骑手都拿不到,
        路网距离永久变直线,而且没有任何报错。"""
        import random

        async def go():
            _fresh_gate(monkeypatch)
            async def contend(budget):
                try:
                    await asyncio.wait_for(
                        routing._matrix_gate.acquire(), budget)
                except (asyncio.TimeoutError, TimeoutError):
                    return
                try:
                    await asyncio.sleep(0.002)
                finally:
                    routing._matrix_gate.release()

            rnd = random.Random(20260826)   # 固定种子,失败可复现
            for _ in range(20):
                await asyncio.gather(*[
                    contend(rnd.choice([0.0, 0.001, 0.002, 0.003, 0.01]))
                    for _ in range(50)])
                assert not routing._matrix_gate.locked(), "锁没还回去 —— 死锁"

        _run(go())

    def test_外层预算取消也不泄漏(self, monkeypatch):
        """抢单池给整段预热还套了一层 _PREWARM_BUDGET。
        取消发生在锁**里面**时,finally 必须跑到。"""
        async def go():
            _fresh_gate(monkeypatch)
            async def holder():
                await routing._matrix_gate.acquire()
                try:
                    await asyncio.sleep(10)
                finally:
                    routing._matrix_gate.release()
            for _ in range(50):
                try:
                    await asyncio.wait_for(holder(), 0.001)
                except (asyncio.TimeoutError, TimeoutError):
                    pass
            assert not routing._matrix_gate.locked()
        _run(go())


class Test放弃之后下游要停手:
    def test_cache_only时缓存没有就直接兜底不发请求(self, monkeypatch):
        called = []

        class Boom:
            def __init__(self, *a, **k): called.append(1)
            async def __aenter__(self): raise AssertionError("不该发请求")
            async def __aexit__(self, *a): return False

        monkeypatch.setattr(routing.httpx, "AsyncClient", Boom)
        monkeypatch.setattr(routing.settings, "tencent_map_key", "x" * 20)
        dist, dur, src = _run(routing.route(
            30.6598, 104.0810, 30.6900, 104.0900, cache_only=True))
        assert src == "straight" and dur is None
        assert not called, "cache_only 下仍然构造了 HTTP 客户端"

    def test_cache_only不写负缓存(self, monkeypatch):
        """这里根本没问过,不知道这个点对行不行 ——
        记下来的话会把一次拥堵变成半小时的降级。"""
        wrote = []

        class FakeRedis:
            async def get(self, *a, **k): return None
            async def set(self, *a, **k): wrote.append(a)
        monkeypatch.setattr(routing, "get_redis", lambda: FakeRedis())
        monkeypatch.setattr(routing.settings, "tencent_map_key", "x" * 20)
        _run(routing.route(30.66, 104.08, 30.69, 104.09, cache_only=True))
        assert not wrote, "cache_only 写了负缓存"

    def test_抢单池接住MatrixBusy并转成cache_only(self):
        import inspect

        from app.routers import riders
        src = inspect.getsource(riders.available_orders)
        assert "except MatrixBusy:" in src
        assert "cache_only = True" in src
        assert "cache_only=cache_only" in src, (
            "预热放弃了但下游照旧发请求 —— 42 单会打出 84 次不受节流的"
            "单点请求,把限流坐实")


class Test瞬时失败和持久失败分开记:
    def test_两个TTL相差一个量级(self):
        assert routing._NEG_TTL_TRANSIENT < routing._NEG_TTL_SECONDS / 10

    def test_限流按瞬时记(self, monkeypatch):
        seen = {}

        class FakeRedis:
            async def get(self, *a, **k): return None
            async def set(self, k, v, ex=None): seen["ex"] = ex

        class Resp:
            def json(self): return {"status": 120, "message": "每秒上限"}

        class Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, *a, **k): return Resp()

        monkeypatch.setattr(routing, "get_redis", lambda: FakeRedis())
        monkeypatch.setattr(routing.httpx, "AsyncClient", Client)
        monkeypatch.setattr(routing.settings, "tencent_map_key", "x" * 20)
        _run(routing.route(30.66, 104.08, 30.69, 104.09))
        assert seen["ex"] == routing._NEG_TTL_TRANSIENT, (
            "限流按 30 分钟记了 —— 午高峰手一抖,那对坐标半小时不自愈")

    def test_规划不出路线按持久记(self, monkeypatch):
        seen = {}

        class FakeRedis:
            async def get(self, *a, **k): return None
            async def set(self, k, v, ex=None): seen["ex"] = ex

        class Resp:
            def json(self): return {"status": 0, "result": {"routes": []}}

        class Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def get(self, *a, **k): return Resp()

        monkeypatch.setattr(routing, "get_redis", lambda: FakeRedis())
        monkeypatch.setattr(routing.httpx, "AsyncClient", Client)
        monkeypatch.setattr(routing.settings, "tencent_map_key", "x" * 20)
        _run(routing.route(30.66, 104.08, 30.69, 104.09))
        assert seen["ex"] == routing._NEG_TTL_SECONDS


class Test批量读缓存:
    def test_一次mget不是逐个get(self, monkeypatch):
        gets = []

        class FakeRedis:
            async def mget(self, keys): return [None] * len(keys)
            async def get(self, k): gets.append(k); return None
        monkeypatch.setattr(routing, "get_redis", lambda: FakeRedis())
        pairs = [((30.66, 104.08), (30.67, 104.09 + i * 0.01))
                 for i in range(40)]
        _run(routing.routes_cached(pairs))
        assert not gets, "还在逐个 GET —— 42 单就是 84 次串行往返"

    def test_负缓存和route口径一致退直线不是当没命中(self, monkeypatch):
        """当成没命中的话调用方又会去问一遍,负缓存就白记了。"""
        class FakeRedis:
            async def mget(self, keys):
                return [routing.dump_route_cache(0.0, None)] * len(keys)
        monkeypatch.setattr(routing, "get_redis", lambda: FakeRedis())
        p = ((30.66, 104.08), (30.69, 104.09))
        got = _run(routing.routes_cached([p]))
        assert p in got, "负缓存被当成没命中"
        assert got[p][2] == "straight" and got[p][0] > 0

    def test_缓存挂了返回空而不是抛(self, monkeypatch):
        class Dead:
            async def mget(self, keys): raise RuntimeError("redis down")
        monkeypatch.setattr(routing, "get_redis", lambda: Dead())
        assert _run(routing.routes_cached(
            [((30.66, 104.08), (30.69, 104.09))])) == {}
