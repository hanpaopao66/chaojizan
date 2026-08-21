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
    # 断开的连接(库重启、中间的隧道超时闲置断链)先探活再用,
    # 否则第一个拿到坏连接的请求必然 500
    pool_pre_ping=True,
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        yield session
