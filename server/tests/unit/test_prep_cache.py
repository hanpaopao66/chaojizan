"""出餐分位数的缓存(#301)。

## 这组测试守什么

`prep_time.stats_for` 扫 30 天的 order_events 再在内存里按单配对,
单次 23ms —— 而它**占了抢单池接口 85% 的 CPU**。抢单池是每个骑手
每 5 秒调一次的接口,午高峰几十个骑手嘎嘎刷,这一处就把整个接口
串成一条队(实测 15.7 次/秒;加缓存后 149 次/秒)。

缓存本身不难,难的是**别用错键**。三件事锁住:

1. **必须按单个商家存,不能按商家集合存**。按集合看着更省事,但
   骑手是散在城里的,每人看到的店集合都不一样,键就各不相同,
   缓存等于没有 —— 而且这个错误在测试里最难发现:压测时所有
   假骑手都在同一个点,集合相同,命中率虚高得很好看;
2. **部分命中要只补差集**,不能因为少一家店就整批重算 ——
   否则骑手多看到一家新店,前面几十家的缓存就白热了;
3. **商家改了自报出餐时长要立刻失效**。分位数晚一分钟没人察觉,
   但自报值是商家刚亲手改的,看不到变化会被当成没保存成功。
"""
import inspect

import app.services.prep_time as prep_time


class Test缓存键按单个商家:
    def test_键里只有一个商家id(self):
        """键的形状就是结论:`prep:v1:{id}`。

        一旦有人改成把 id 列表拼进键(或 hash 一下),这条就红 ——
        那正是"按集合存"的写法,压测数据会好看,线上没有命中。
        """
        src = inspect.getsource(prep_time.stats_for)
        assert 'f"{_CACHE_PREFIX}{i}"' in src, "缓存键必须按单个商家算"
        assert "hashlib" not in src, (
            "对 id 列表做 hash = 按集合存;骑手散在城里时命中率为零")

    def test_读缓存用mget批量(self):
        """几十家店逐个 GET 就是几十次 Redis 往返,
        把省下来的 23ms 又还回去一半。"""
        assert "mget" in inspect.getsource(prep_time.stats_for)

    def test_写缓存用pipeline(self):
        assert "pipeline" in inspect.getsource(prep_time.stats_for)


class Test部分命中只补差集:
    def test_命中的从ids里剔除(self):
        src = inspect.getsource(prep_time.stats_for)
        assert "ids = [i for i in ids if i not in cached]" in src, (
            "少一家店就整批重算的话,骑手每看到一家新店,"
            "前面几十家的缓存就白热了")

    def test_全命中直接返回不查库(self):
        src = inspect.getsource(prep_time.stats_for)
        assert "if not ids:\n        return cached" in src

    def test_结果要把缓存的并回去(self):
        """只补了差集,返回时忘了 update 就会漏掉命中的那些 ——
        表现是骑手卡片上一部分店没有出餐预估,不报错。"""
        assert "out.update(cached)" in inspect.getsource(prep_time.stats_for)


class Test商家改自报值立刻失效:
    def test_有失效函数(self):
        assert callable(prep_time.invalidate)

    def test_删的是同一个键(self):
        """失效和写入必须是同一套键。这条是防手滑改了一边 ——
        键一旦对不上,失效就是个空操作,而且完全不报错。

        所以两边都必须走 `_CACHE_PREFIX` 这个常量,不许各写各的字面量。"""
        for fn in (prep_time.invalidate, prep_time.stats_for):
            assert "_CACHE_PREFIX" in inspect.getsource(fn), (
                f"{fn.__name__} 没走共用的键前缀常量")

    def test_口径变了要升版号(self):
        """缓存里存的是**算好的**分位数。`true_ready_at` 的口径一改,
        旧值就不该再被回答 —— 而 TTL 是 60 秒,不升版号的话
        部署后这一分钟里新旧口径混着发。"""
        assert prep_time._CACHE_PREFIX.startswith("prep:v")
        ver = int(prep_time._CACHE_PREFIX.removeprefix("prep:v").rstrip(":"))
        assert ver >= 2, "引入骑手时刻校准之后,版本号至少是 2"

    def test_改自报值的路由会调它(self):
        import app.routers.merchants as m
        src = inspect.getsource(m.update_my_shop)
        assert "prep_time.invalidate" in src
        assert "payload.promise_ready_minutes is not None" in src, (
            "只在真的改了这个字段时才失效;每次 PATCH 都打掉缓存"
            "等于没有缓存")


class TestTTL:
    def test_不能太长(self):
        """这是 30 天的分位数,多一单少一单挪不动它,所以可以缓存;
        但也不该长到商家一整个中午的改善都看不出来。"""
        assert 30 <= prep_time._CACHE_TTL_SECONDS <= 300


class Test缓存挂了也要能出结果:
    def test_读写都包了异常(self):
        """Redis 抖一下不该让骑手看不到单。缓存是加速,不是依赖。"""
        src = inspect.getsource(prep_time.stats_for)
        assert src.count("except Exception:") >= 2
