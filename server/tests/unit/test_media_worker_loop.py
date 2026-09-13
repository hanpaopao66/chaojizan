"""独立转码 worker 的等任务循环(app/workers/media.py worker_main)。

2026-09-13 生产上第一次起独立的 media-worker:BLMOVE 阻塞 5 秒,而 redis-py 的读超时默认也是
5 秒 —— 队列一空,每一轮都在第 5 秒被客户端当成读超时掐断,进程崩掉、被 compose 拉起、再崩,
聊天视频全停在「处理中」。CI 和本地的转码在 api 进程里跑,不走这个循环,所以一直是绿的。
"""
import asyncio
import json

import pytest
from redis.exceptions import TimeoutError as RedisTimeout

from app.workers import media


def test_block_shorter_than_client_read_timeout():
    """阻塞时长必须小于 redis-py 的默认读超时,留出网络往返的余量"""
    try:
        from redis._defaults import DEFAULT_SOCKET_TIMEOUT
    except ImportError:  # 老版本没有这个常量:那时默认不设读超时
        pytest.skip("这个 redis-py 版本没有默认读超时")
    assert media.BLOCK_SECONDS < DEFAULT_SOCKET_TIMEOUT


class _Stop(Exception):
    pass


class _FakeRedis:
    def __init__(self, script):
        self.script = list(script)
        self.removed = []
        self.block = []

    async def lmove(self, *a):
        return None  # 没有上次没做完的

    async def blmove(self, src, dst, timeout, *a):
        self.block.append(timeout)
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    async def lrem(self, key, count, raw):
        self.removed.append(raw)


def test_read_timeout_does_not_kill_worker(monkeypatch):
    """等任务时读超时一次:接着等,下一个任务照样做完、从「进行中」里删掉"""
    job = {"type": "chat_video", "media_id": 7}
    fake = _FakeRedis([RedisTimeout("Timeout reading from redis:6379"), None, json.dumps(job), _Stop()])
    done = []

    async def run_job(j):
        done.append(j)

    monkeypatch.setattr(media, "get_redis", lambda: fake)
    monkeypatch.setattr(media, "run_job", run_job)
    with pytest.raises(_Stop):
        asyncio.run(media.worker_main())
    assert done == [job]
    assert fake.removed == [json.dumps(job)]
    assert set(fake.block) == {media.BLOCK_SECONDS}
