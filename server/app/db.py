import time

from sqlalchemy import event, exc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

# 池子大小走配置:**它乘上进程数必须小于 PG 的 max_connections**。
# 写死 10/20 的时候 api 是 --workers 4,4 × 30 = 120 > 默认的 100 ——
# 池子自己不知道库那边的上限,超出的部分不是排队而是连接被拒(随机 500)。
# 见 config.py 里 db_pool_size 的注释和 deploy/docker-compose.prod.yml
engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    # **不用 pool_pre_ping**,改成下面按闲置时长探活。原因见那段注释
    pool_pre_ping=False,
)

#: 连接闲置超过这么久,取用前先探一次活。
#:
#: ## 为什么不用 SQLAlchemy 自带的 pool_pre_ping
#:
#: `pool_pre_ping=True` 是**每次取用都探**,也就是每一个查库的请求都多打
#: 一个来回。实测(两版各起一个进程,ab 交替压):
#:
#:     /auth/me           1.008 → 0.615 ms   省 0.394ms(39%)
#:     /riders/me/fatigue 1.527 → 1.108 ms   省 0.419ms(27%)
#:
#: 区间完全不重叠。三端每一个查库的请求都在付这 0.4ms。
#:
#: ## 那它防的是什么
#:
#: 坏连接:库重启、PG 的 idle 超时、中间隧道闲置断链。实测代价是
#: **每次 db 重启恰好 1 个 500** —— SQLAlchemy 撞上第一条坏连接就把
#: 整代池子作废,后面的请求自动拿新连接,所以是自愈的,不是
#: "池子里有几条坏的就 500 几次"。
#:
#: ## 所以按闲置时长探
#:
#: 连接是**闲出来的坏**,不是用出来的坏。忙的时候同一条连接毫秒级就被
#: 复用一次,那时探活纯属浪费;闲置超过阈值再探,恰好卡在它真正可能
#: 掉线的时候。30 秒远低于 PG 默认的 idle 超时和常见的隧道超时。
#:
#: ## 阈值必须**明显小于**后台清扫的间隔,否则这段代码等于不存在
#:
#: 第一版写的是 30 秒,和 `settings.sweep_interval_seconds` 正好一样 ——
#: 结果是一次都没探到。auto_flow 每 30 秒查一次库,而连接池是 LIFO:
#: 它刚用完还回去的那条永远在栈顶,下一个请求拿到的就是它,闲置时长
#: 永远不到 30 秒。**掐掉全部后端连接后,请求照样 500** ——
#: 加了探活却一点保护都没多,只是多了一段死代码。
#:
#: 改成 5 秒之后实测:高负载 60 个请求里只探了 2 次(成本仍然约等于 0),
#: 而掐断连接后连打 6 次全部 200 —— 探针显示每次都探到了坏连接并换掉。
#:
#: 这个约束由 `tests/unit/test_pool_idle_ping.py` 守着:有人把清扫间隔
#: 调下来而没动这里,那条用例会红。
#:
#: 留一个已知缺口:**持续高负载中途 db 重启**时,连接都在 5 秒窗口内、
#: 不会被探到,那一批会走"撞断线 → 整代作废 → 自愈"那条路,可能漏几个
#: 500。换来的是平时每个请求省 0.4ms —— 这个取舍是明确选过的,不是疏漏。
POOL_PING_IDLE_SECONDS = 5


@event.listens_for(engine.sync_engine, "connect")
def _stamp_new_connection(dbapi_connection, connection_record):
    """刚建好的连接必然是活的,盖上时间戳免得第一次取用白探一次。"""
    connection_record.info["last_used"] = time.monotonic()


@event.listens_for(engine.sync_engine, "checkin")
def _stamp_checkin(dbapi_connection, connection_record):
    """还回池子的时刻 = 开始闲置的时刻。"""
    connection_record.info["last_used"] = time.monotonic()


@event.listens_for(engine.sync_engine, "checkout")
def _ping_if_idle(dbapi_connection, connection_record, connection_proxy):
    """闲置超过阈值才探活;探不通抛 DisconnectionError,由池子换一条重来。

    抛 `DisconnectionError` 是 SQLAlchemy 定义的口径:它会作废这条连接、
    透明地再取一条给调用方,请求本身察觉不到 —— 和 pool_pre_ping 的行为
    一致。**不能在这里吞掉异常**,吞了等于把坏连接交出去。
    """
    last_used = connection_record.info.get("last_used")
    if (last_used is not None
            and time.monotonic() - last_used < POOL_PING_IDLE_SECONDS):
        return
    try:
        engine.sync_engine.dialect.do_ping(dbapi_connection)
    except Exception as err:
        raise exc.DisconnectionError("连接闲置后已失效,换一条") from err
    connection_record.info["last_used"] = time.monotonic()


SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        yield session
