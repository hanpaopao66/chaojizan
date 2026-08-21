"""建库/迁移的启动动作 —— 从 main.py 的 lifespan 里抽出来单独一份。

抽出来是为了让**同一段逻辑**能被三个地方调用而不是抄三遍:

  1. 本地开发:`uvicorn app.main:app` 起来时 lifespan 自己跑(零配置,起服务即最新);
  2. 生产:独立的一次性 `migrate` 容器跑完退出,api 和 sweeper 都不跑;
  3. 运维手动:`python -m app.startup`。

## 为什么生产要单拎出来

原先 api 以 `--workers 4` 启动,而 lifespan 是**每个 worker 各跑一遍**的。
四个进程同时 `alembic upgrade head` 会一起去读写 `alembic_version`:
运气好是三个白等,运气不好是有人读到了半途的版本号然后重复执行迁移。
这种事故只在"恰好这次部署带了迁移"时发生,平时怎么重启都风平浪静。

现在双保险:进程模型上只有一个地方会跑(migrate 容器),
再加一把 PostgreSQL 咨询锁 —— 万一将来谁又把 workers 调回去了,
或者部署脚本手滑同时起了两个 migrate,锁会让他们排队而不是打架。
"""
import asyncio
import logging
from pathlib import Path

from sqlalchemy import text

from .db import engine

logger = logging.getLogger("superz.startup")

SERVER_DIR = Path(__file__).resolve().parent.parent

# Alembic 基线版本号:老库(有表但没有 alembic_version)启动时 stamp 到这里,
# 之后的结构变更一律走 alembic revision --autogenerate,不再手写 ALTER
BASELINE_REV = "0001"

# 迁移用的咨询锁 ID(任意常量,只要全库唯一即可)。
# pg_advisory_lock 是会话级的:连接一断锁自动释放,进程被 kill 也不会留死锁 ——
# 这正是我们要的,自己造一张锁表反而要处理"上锁的进程死了怎么办"
_MIGRATION_LOCK_ID = 8_147_230_951


def _run_alembic_upgrade(stamp_baseline: bool) -> None:
    """在工作线程里跑(alembic env.py 内部 asyncio.run,不能嵌在事件循环里)。"""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    if stamp_baseline:
        command.stamp(cfg, BASELINE_REV)
    command.upgrade(cfg, "head")


async def prepare_database() -> None:
    """建扩展 + 认老库 + upgrade head。幂等,重复跑没有副作用。"""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        # 老库识别:建过表(users 存在)但从没跑过 alembic → 先 stamp 基线
        has_users = await conn.scalar(text("SELECT to_regclass('public.users')"))
        has_alembic = await conn.scalar(
            text("SELECT to_regclass('public.alembic_version')"))
    stamp_baseline = has_users is not None and has_alembic is None

    # 咨询锁全程握在这**一条**连接上;alembic 自己在另一条连接上干活。
    # 用 engine.connect() 而不是 begin():锁要跨越整个 upgrade 存活,
    # 不能被事务提交顺手放掉
    # ⚠️ 这个连接必须走 AUTOCOMMIT。
    #
    # pg_advisory_lock 是**会话级**的,不靠事务兜住它;而普通 connect()
    # 会在第一次 execute 时隐式开一个事务并一直挂着(pg_stat_activity
    # 里就是 `idle in transaction`)。下面的迁移里有
    # CREATE INDEX CONCURRENTLY,而 CONCURRENTLY **要等所有先于它开始的
    # 事务结束** —— 等的正是这个持锁连接自己。
    #
    # 表现:启动永远停在 "Waiting for application startup",
    # 而且失败会在库里留下一个 INVALID 索引(要 DROP INDEX CONCURRENTLY
    # 清掉才能重跑)。踩过一次。
    async with engine.connect() as lock_conn:
        await lock_conn.execute(
            text("SELECT pg_advisory_lock(:k)"), {"k": _MIGRATION_LOCK_ID})
        # ⚠️ 拿完锁**必须立刻结束事务**。pg_advisory_lock 是会话级的,
        # commit 不会把它释放掉,而不 commit 的话这个连接会一直
        # `idle in transaction` —— 下面的迁移里有 CREATE INDEX CONCURRENTLY,
        # 它要等所有先于它开始的事务结束,等的正是这个持锁连接自己。
        #
        # 表现:启动永远停在 "Waiting for application startup",
        # 失败还会在库里留下 INVALID 索引(要 DROP INDEX CONCURRENTLY 清掉
        # 才能重跑)。踩过一次。
        await lock_conn.commit()
        try:
            await asyncio.to_thread(_run_alembic_upgrade, stamp_baseline)
        finally:
            await lock_conn.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": _MIGRATION_LOCK_ID})


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info("开始迁移数据库…")
    try:
        await prepare_database()
        logger.info("迁移完成,已到 head")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
