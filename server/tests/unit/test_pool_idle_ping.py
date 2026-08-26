"""连接池按闲置时长探活:忙的时候不探,闲久了才探,探不通要换连接。

## 这组测试守什么

`pool_pre_ping=True` 是**每次取用都探**,三端每一个查库的请求都多打一个
来回。实测两版各起一个进程 ab 交替压:

    /auth/me           1.008 → 0.615 ms   省 0.394ms(39%)
    /riders/me/fatigue 1.527 → 1.108 ms   省 0.419ms(27%)

而它防的坏连接是**闲出来的**(库重启、PG idle 超时、隧道闲置断链),
不是用出来的。所以改成闲置超过阈值才探:忙的时候同一条连接毫秒级就被
复用,一次都不探;闲久了那一次探,恰好卡在它真可能掉线的时候。

这里锁三件事,少一件这个改动就白做或者变成隐患:

1. 窗口内**一次都不能探** —— 探了就等于没省;
2. 窗口外必须探 —— 不探等于把坏连接交出去;
3. 探不通必须抛 `DisconnectionError` —— 这是 SQLAlchemy 认的口径,
   它会作废这条连接并透明换一条。**吞掉异常是最坏的情况**:
   请求拿着一条死连接继续跑,报出来的错离真正的原因十万八千里。
"""
import time

import pytest
from sqlalchemy import exc

from app.db import POOL_PING_IDLE_SECONDS, _ping_if_idle, engine


class _Record:
    """冒充 SQLAlchemy 的 connection_record,只要一个 info 字典。"""

    def __init__(self, last_used=None):
        self.info = {} if last_used is None else {"last_used": last_used}


@pytest.fixture
def pings(monkeypatch):
    """把方言的 do_ping 换成计数器,返回值是"探了几次"的列表。"""
    calls = []

    def fake_ping(dbapi_connection):
        calls.append(dbapi_connection)
        return True

    monkeypatch.setattr(engine.sync_engine.dialect, "do_ping", fake_ping)
    return calls


def test_刚还回池子的连接不探活(pings):
    rec = _Record(last_used=time.monotonic())
    _ping_if_idle("conn", rec, None)
    assert pings == [], "窗口内探活了,那就没省下任何东西"


def test_忙碌复用全程一次都不探(pings):
    """模拟高负载:同一条连接被连续取用 100 次,间隔远小于阈值。"""
    rec = _Record(last_used=time.monotonic())
    for _ in range(100):
        _ping_if_idle("conn", rec, None)
    assert pings == [], f"100 次复用探了 {len(pings)} 次"


def test_闲置超过阈值就探一次(pings):
    rec = _Record(last_used=time.monotonic() - POOL_PING_IDLE_SECONDS - 1)
    _ping_if_idle("conn", rec, None)
    assert len(pings) == 1
    # 探完要重新盖时间戳,否则同一条连接会被反复探
    _ping_if_idle("conn", rec, None)
    assert len(pings) == 1, "探完没重新盖时间戳,下一次又探了一遍"


def test_没有时间戳的连接会探一次(pings):
    """兜底:拿不到 last_used 时宁可探一次,不能默认它是活的。"""
    _ping_if_idle("conn", _Record(), None)
    assert len(pings) == 1


def test_探不通抛DisconnectionError而不是吞掉(monkeypatch):
    def boom(dbapi_connection):
        raise OSError("connection reset by peer")

    monkeypatch.setattr(engine.sync_engine.dialect, "do_ping", boom)
    rec = _Record(last_used=time.monotonic() - POOL_PING_IDLE_SECONDS - 1)
    with pytest.raises(exc.DisconnectionError):
        _ping_if_idle("conn", rec, None)


def test_阈值必须明显小于后台清扫间隔():
    """**这条是整个改动能不能生效的前提。**

    第一版阈值写的 30 秒,和 `sweep_interval_seconds` 一样 —— 结果一次都
    没探到:auto_flow 每 30 秒查一次库,而连接池是 LIFO,它刚还回去的
    那条永远在栈顶,下一个请求拿到的就是它,闲置时长永远不到阈值。
    掐掉全部后端连接后请求照样 500,等于加了段死代码。

    所以阈值要留出余量。有人把清扫间隔调下来而没动这里,这条会红。
    """
    from app.config import settings
    assert POOL_PING_IDLE_SECONDS * 2 <= settings.sweep_interval_seconds, (
        f"探活阈值 {POOL_PING_IDLE_SECONDS}s 相对后台清扫间隔 "
        f"{settings.sweep_interval_seconds}s 太大 —— LIFO 池子里栈顶那条"
        f"连接会被清扫任务一直刷新,探活永远轮不到")
    assert POOL_PING_IDLE_SECONDS >= 1, "阈值太小就退化成每次都探了"


def test_没有退回每次都探的老写法():
    """有人把 pool_pre_ping 改回 True 的话,上面省下的 0.4ms 就回去了。"""
    assert engine.pool._pre_ping is False, \
        "pool_pre_ping 又开了 —— 那和闲置探活是重复的,每个请求白付 0.4ms"
