"""Alembic 迁移环境(async)。

数据库地址与应用同源(app.config.settings.database_url),不在 alembic.ini 里维护第二份。
应用启动时自动执行 upgrade head(见 app/main.py 的 lifespan),
手动运维:cd server && alembic upgrade head / alembic revision --autogenerate -m "..."
"""
import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db import Base
from app import models  # noqa: F401  确保所有模型注册进 Base.metadata

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """只管我们模型里声明的表;PostGIS(spatial_ref_sys/tiger/topology)一概不碰。

    代价:删表/改表名不会被 autogenerate 检测,需要手写迁移——
    对账本类系统这反而是护栏(删表必须是显式决定)。
    """
    if type_ == "table":
        return name in target_metadata.tables
    return True


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


def run_migrations_offline():
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
