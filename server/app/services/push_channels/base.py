"""各条推送通道共用的东西(#384)。

每条通道都长成同一个样子,上层(services/push.py)才不用认识谁是谁:

    configured() -> bool          配齐了没有
    send(token, title, content, extras, *, app=…) -> Result

**一律不抛异常。** 推送失败不该把调用方的流程带倒 —— 它是通知,不是业务。
"""
import asyncio
import logging

import httpx

logger = logging.getLogger("superz.push")


class Result:
    """一次发送的结果。

    `gone` 是最要紧的一位:**这个 token 永远不会再收到东西了**,调用方据此下线设备。
    判宽了会把好设备下线(用户从此收不到推送,而且没人会来报这个 bug),
    判窄了会一直往死 token 发。拿不准时**一律当成不 gone** —— 少下线一台设备
    只是多发几次无用的请求,下线错一台是真丢用户。
    """

    __slots__ = ("ok", "error", "gone")

    def __init__(self, ok: bool, error: str = "", gone: bool = False):
        self.ok = ok
        self.error = error
        self.gone = gone

    def __repr__(self) -> str:
        return f"Result(ok={self.ok}, error={self.error!r}, gone={self.gone})"


NOT_CONFIGURED = Result(False, "没配")


class TokenCache:
    """厂商的接口大多要先换一个短期令牌,再拿它发推送。

    两件事写在这里而不是各家各写一遍:

    1. **提前过期**:按对方给的有效期减去一段安全余量续期 —— 卡着点换会在路上过期;
    2. **同一时刻只换一次**:不加锁的话,一批推送同时发现令牌过期,
       会并发去换 N 次,有的厂商会因此把你限流甚至封一段时间。
    """

    def __init__(self, name: str, margin: float = 300.0):
        self.name = name
        self.margin = margin
        self._value: str = ""
        self._expire_at: float = 0.0
        self._lock = asyncio.Lock()

    def peek(self, now: float) -> str:
        return self._value if self._value and now < self._expire_at - self.margin else ""

    def put(self, value: str, ttl: float, now: float) -> None:
        self._value = value
        self._expire_at = now + ttl

    def clear(self) -> None:
        self._value = ""
        self._expire_at = 0.0

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock


_clients: dict[str, httpx.AsyncClient] = {}


async def client(name: str, **kw) -> httpx.AsyncClient:
    """每条通道一个共享连接池。

    **不是每推一条 new 一个**:那样每条推送都重做一次 TCP + TLS 握手,
    扇出的时候这个开销要乘以人数(push.py 里踩过一次)。
    """
    c = _clients.get(name)
    if c is None or c.is_closed:
        c = httpx.AsyncClient(timeout=10, **kw)
        _clients[name] = c
    return c


async def aclose_all() -> None:
    """进程退出时收掉(main.py 的 lifespan 调)。"""
    for c in list(_clients.values()):
        if not c.is_closed:
            await c.aclose()
    _clients.clear()


def set_client_for_test(name: str, c: httpx.AsyncClient) -> None:
    _clients[name] = c


def reset_clients_for_test() -> None:
    _clients.clear()
