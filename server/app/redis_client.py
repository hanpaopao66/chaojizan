import redis.asyncio as redis

from .config import settings

pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> redis.Redis:
    return redis.Redis(connection_pool=pool)


RIDER_LOC_KEY = "rider:loc:{rider_id}"  # hash: lat, lng, ts
