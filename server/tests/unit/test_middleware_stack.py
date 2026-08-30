"""中间件那一层:纯 ASGI,顺序不能乱(#302)。

## 这组测试守什么

三端每一个请求都要穿过这一层,所以它的开销要**乘以总请求数**。原先三个
中间件都用 `@app.middleware("http")`,那个装饰器背后是 Starlette 的
BaseHTTPMiddleware —— 给每个请求起一个 anyio task group 加两条内存对象流,
好处是能拿到 Request/Response 对象。而这三件事一件都用不上:
两个只读请求头,一个只包一层 try。

改成纯 ASGI 之后,框架地板(`/auth/me`)从 2.88ms 降到 1.23ms;
`/orders/{no}/rider-location` 这类 5 秒一刷的轮询从 4.03ms 降到 1.69ms。

改这一层最容易悄悄弄坏的是**顺序**和**行为**,所以都锁住:

1. 顺序变了 = 语义变了。异常留痕必须在最外(不然中间件自己抛的异常没人记),
   门店选择必须在最内(ContextVar 要盖住整个路由);
2. 三件事的行为一件都不能少;
3. 别再退回 BaseHTTPMiddleware —— 那是这次要甩掉的东西。
"""
import asyncio

import httpx
import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app.main import (AdminConsoleMiddleware, LogUnhandledErrorsMiddleware,
                      ObserveAppBuildMiddleware, RecordApiCallMiddleware,
                      SelectShopMiddleware, app)


class Test中间件顺序:
    def test_由外到内(self):
        """`user_middleware` 是外→内。异常留痕在门店选择外面 ——
        反过来的话门店选择自己抛的异常就没人记了。"""
        names = [m.cls.__name__ for m in app.user_middleware]
        assert names == ["CORSMiddleware", "LogUnhandledErrorsMiddleware",
                         "ObserveAppBuildMiddleware", "SelectShopMiddleware",
                         "AdminConsoleMiddleware",
                         "RecordApiCallMiddleware"], \
            f"中间件顺序变了:{names}"

    def test_调用日志在最内(self):
        """它要贴着路由,才量得准**路由自己**花了多久 ——
        套在外面量出来的是「路由 + 外面几层」,那个数指导不了任何优化。

        代价是路由抛未处理异常时它拿不到状态码,所以那一支里
        显式记 500(见 RecordApiCallMiddleware 的 try/except)。
        """
        names = [m.cls.__name__ for m in app.user_middleware]
        assert names[-1] == "RecordApiCallMiddleware"

    def test_后台页面拦在调用日志外面(self):
        """打开一个后台页面**不是一次 API 调用**。

        放在调用日志里面的话,每次刷新后台都会往里记一条 ——
        把开发者控制台那份「我的集成调了什么」冲得没法看。
        而且调用日志必须贴着路由才量得准,见上一条。
        """
        names = [m.cls.__name__ for m in app.user_middleware]
        assert names.index("AdminConsoleMiddleware") \
            < names.index("RecordApiCallMiddleware")

    def test_不再用BaseHTTPMiddleware(self):
        """这是这次改动的全部意义。有人图省事加一个
        `@app.middleware(\"http\")` 就把地板加回去了。"""
        bad = [m.cls.__name__ for m in app.user_middleware
               if m.cls is BaseHTTPMiddleware]
        assert not bad, (
            "又出现了 BaseHTTPMiddleware —— 它给每个请求起 task group 加内存流,"
            "而三端每个请求都要穿过这一层")


def _drive(mw_cls, headers=None, inner=None):
    """把一个纯 ASGI 中间件单独跑起来,不经过整个应用。"""
    seen = {}

    async def default_inner(scope, receive, send):
        from app.services.staff import current_shop_id
        seen["shop_id"] = current_shop_id.get()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    scope = {"type": "http", "method": "GET", "path": "/x",
             "headers": [(k.lower().encode(), v.encode())
                         for k, v in (headers or {}).items()]}

    async def receive(): return {"type": "http.request", "body": b""}
    async def send(msg): seen.setdefault("sent", []).append(msg)

    asyncio.run(mw_cls(inner or default_inner)(scope, receive, send))
    return seen


class Test门店选择:
    def test_头里的数字进了ContextVar(self):
        assert _drive(SelectShopMiddleware,
                      {"X-Shop-Id": "42"})["shop_id"] == 42

    def test_没有头时不设(self):
        assert _drive(SelectShopMiddleware, {})["shop_id"] is None

    def test_非数字不设也不报错(self):
        """伪造的头只该被忽略,绝不能把请求打挂。"""
        assert _drive(SelectShopMiddleware,
                      {"X-Shop-Id": "'; DROP TABLE--"})["shop_id"] is None

    def test_请求结束后要还原(self):
        """不还原的话 ContextVar 会漏到复用同一个上下文的下一个请求上 ——
        那是"我看到了别人家的店"这种最难查的串号。"""
        from app.services.staff import current_shop_id
        _drive(SelectShopMiddleware, {"X-Shop-Id": "42"})
        assert current_shop_id.get() is None

    def test_路由抛异常也要还原(self):
        from app.services.staff import current_shop_id

        async def boom(scope, receive, send):
            raise RuntimeError("x")
        with pytest.raises(RuntimeError):
            _drive(SelectShopMiddleware, {"X-Shop-Id": "42"}, inner=boom)
        assert current_shop_id.get() is None


class Test版本上报:
    def test_合法的记(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="superz.appbuild"):
            _drive(ObserveAppBuildMiddleware,
                   {"X-App-Build": "2054", "X-App-Platform": "android"})
        assert "app_build=2054" in caplog.text
        assert "platform=android" in caplog.text

    def test_空的不记(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="superz.appbuild"):
            _drive(ObserveAppBuildMiddleware, {})
        assert "app_build" not in caplog.text, "空头也记的话日志会被刷屏"

    def test_非数字不记也不报错(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="superz.appbuild"):
            _drive(ObserveAppBuildMiddleware, {"X-App-Build": "abc"})
        assert "app_build" not in caplog.text

    def test_health不记(self, caplog):
        """高频探活,记了日志里全是它。"""
        import logging
        scope_patch = {"X-App-Build": "2054"}
        seen = {}

        async def inner(scope, receive, send):
            await send({"type": "http.response.start", "status": 200,
                        "headers": []})
            await send({"type": "http.response.body", "body": b""})
        s = {"type": "http", "method": "GET", "path": "/health",
             "headers": [(b"x-app-build", b"2054")]}

        async def rcv(): return {"type": "http.request", "body": b""}
        async def snd(m): seen.setdefault("s", []).append(m)
        with caplog.at_level(logging.INFO, logger="superz.appbuild"):
            asyncio.run(ObserveAppBuildMiddleware(inner)(s, rcv, snd))
        assert "app_build" not in caplog.text


class Test异常留痕:
    def test_记方法路径和traceback然后原样抛出(self, caplog):
        """**要原样抛出** —— 这里只负责留痕,吞掉的话客户端会拿到
        一个没有状态码的空响应。"""
        import logging

        async def boom(scope, receive, send):
            raise RuntimeError("故意炸一个")
        with caplog.at_level(logging.ERROR, logger="superz.error"):
            with pytest.raises(RuntimeError):
                _drive(LogUnhandledErrorsMiddleware, {}, inner=boom)
        assert "未处理异常" in caplog.text
        assert "GET" in caplog.text and "/x" in caplog.text
        assert "故意炸一个" in caplog.text, "没带 traceback,等于没记"

    def test_不记请求体和查询串(self):
        """里面有手机号、收货地址、订单内容。日志会被复制、转发、进备份,
        而且不受 /files 那套判权保护。"""
        import inspect
        src = inspect.getsource(LogUnhandledErrorsMiddleware)
        for leak in ("query_string", "body", "receive()"):
            assert leak not in src, f"异常留痕里出现了 {leak} —— 会把用户数据写进日志"


class Test非http的连接直接放行:
    @pytest.mark.parametrize("mw", [SelectShopMiddleware,
                                    ObserveAppBuildMiddleware,
                                    LogUnhandledErrorsMiddleware])
    def test_websocket不受影响(self, mw):
        """订单状态推送走 WebSocket。中间件按 http 的假设去处理它
        会把推送打断,而那种故障只在真机上才看得见。"""
        got = {}

        async def inner(scope, receive, send): got["type"] = scope["type"]
        async def rcv(): return {}
        async def snd(m): pass
        asyncio.run(mw(inner)({"type": "websocket", "headers": []}, rcv, snd))
        assert got["type"] == "websocket"


class Test调用日志必须在响应之前写:
    """**「我明明调了,日志里没有」是这个功能要消灭的困惑,不是它的症状。**

    中间件原先在 `await self.app(...)` 之后才写日志 —— 那时响应早就发给
    客户端了。客户端拿到响应立刻回头读日志,而那条 INSERT 还没提交。
    表现是 e2e_api_console 在同一台机器上有时过有时不过,而业务侧完全
    看不出任何异常。

    写在 `_send` 收到 http.response.start 时、**转发之前**,
    这个顺序就成立了:客户端看见响应的那一刻,日志已经在库里。
    """

    def test_在转发响应之前记(self):
        import inspect

        from app.main import RecordApiCallMiddleware
        src = inspect.getsource(RecordApiCallMiddleware)
        send_body = src[src.index("async def _send"):src.index("try:")]
        assert "_record" in send_body, (
            "日志没在 _send 里写 —— 那就是响应先出去、日志后落库,"
            "客户端读得到响应却读不到日志")
        i = send_body.index("_record")
        j = send_body.index("await send(message)")
        assert i < j, "_record 必须在 await send(message) **之前**"

    def test_一条响应都没发出去时仍然要记(self):
        """最难查的那一类:请求进来了但什么都没发生。
        日志里是空白的话,连"它到底有没有进来"都答不了。"""
        import inspect

        from app.main import RecordApiCallMiddleware
        src = inspect.getsource(RecordApiCallMiddleware)
        assert 'if not done["recorded"]:' in src

