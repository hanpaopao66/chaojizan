"""公开页缓存的时长上限:生产不封顶,e2e 设 0 就等于不缓存。

## 为什么要有这个上限

`/transparency/fairness` 缓存 1 小时。e2e 要做的事是「改完数据立刻看公示」,
两件事对不上:干净库上第一次读把「隐藏 0 条」缓存住,之后这次运行里
隐藏多少条都读不出来。

而本地开发库积着历次跑出来的隐藏评价,所以 `assert hidden > 0` 一直是绿的——
**那条断言实际在断言历史残留**,跟用例自己做了什么没关系。CI 干净库上当场红。

上限压在 `_cache_put` 一个地方,十个调用点各自的 TTL 全都受它管。

## 判据

生产**不能**因为这个开关变得更慢或更容易被刷:默认值必须大到不起作用。
"""
from app.config import Settings
from app.routers import screen


def _bare(**kw) -> Settings:
    """不读 .env —— 本机 .env 里设了 0,直接读会把「默认值安全」测成真空。"""
    return Settings(_env_file=None, **kw)


class Test默认不封顶:
    def test_默认值大于所有调用点的_TTL(self):
        """各接口自己的 TTL 最大 3600(fairness / reports)。
        默认上限必须大于它,否则生产的缓存被悄悄改短,公开页每请求都打库。"""
        assert _bare().public_cache_max_seconds > 3600

    def test_生产不设这一项时缓存照旧(self, monkeypatch):
        monkeypatch.setattr(screen.settings, "public_cache_max_seconds",
                            _bare().public_cache_max_seconds)
        screen._cache.clear()
        screen._cache_put("ut:prod", {"v": 1}, 3600)
        assert screen._cache_get("ut:prod") == {"v": 1}
        expiry = screen._cache["ut:prod"][0]
        import time
        assert expiry - time.monotonic() > 3500, "3600s 的缓存被上限截短了"


class Test上限为零等于不缓存:
    def test_写进去就读不出来(self, monkeypatch):
        monkeypatch.setattr(screen.settings, "public_cache_max_seconds", 0)
        screen._cache.clear()
        screen._cache_put("ut:zero", {"v": 1}, 3600)
        assert screen._cache_get("ut:zero") is None, (
            "上限设成 0 还能读到缓存 —— e2e 会拿到改动之前的旧快照,"
            "而那正是「公示没在数隐藏评价」这类回归藏身的地方")

    def test_上限只压不抬(self, monkeypatch):
        """上限比调用点的 TTL 大时不起作用 —— 它是天花板不是设定值。"""
        monkeypatch.setattr(screen.settings, "public_cache_max_seconds", 86400)
        screen._cache.clear()
        screen._cache_put("ut:short", {"v": 1}, 5)
        import time
        assert screen._cache["ut:short"][0] - time.monotonic() < 6, (
            "5 秒的缓存被上限抬成了 86400 —— 大屏那几个短 TTL 就废了")
