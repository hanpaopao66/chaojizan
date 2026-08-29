"""MCP 服务的协议层与工具清单。

## 这一组守什么

两件事,分开测:

1. **协议**:握手、列工具、调用、坏输入。这一层不碰网络 —— 喂 JSON-RPC 帧
   进去看回什么。协议错了的表现是「助手连不上」或者「用着用着没反应」,
   而那种故障从业务侧完全看不出来。
2. **能力边界**:工具清单里**不许出现任何能付钱的工具**。这是整个
   MCP 接入的支点,而它在这一层是可以静态断言的。

服务端那一侧另有 43 条单测 + 1 条 e2e 守着同一件事
(`server/tests/unit/test_agent_scope.py`、`e2e_agent_token`)——
两边都守是因为:这里少写一个工具不等于服务端不给,服务端不给也不等于
这里不会去调。少任何一边,「付不了钱」都只是半句话。

    python3 -m pytest mcp-server/test_server.py -q
"""
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import server as mcp  # noqa: E402


def rpc(msg: dict) -> dict | None:
    return mcp.handle(msg)


class Test协议:
    def test_握手(self):
        r = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {}})
        assert r["result"]["protocolVersion"] == mcp.PROTOCOL_VERSION
        assert r["result"]["serverInfo"]["name"] == "superz"
        assert "tools" in r["result"]["capabilities"]

    def test_initialized_是通知不该回(self):
        """通知没有 id,回一条带 null id 的响应会让严格的客户端报错。"""
        assert rpc({"jsonrpc": "2.0",
                    "method": "notifications/initialized"}) is None

    def test_ping(self):
        assert rpc({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}

    def test_列工具(self):
        r = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        names = {t["name"] for t in r["result"]["tools"]}
        assert names == {
            "search_merchants", "get_menu", "quote_order",
            "create_pending_order", "get_order_status", "list_my_orders",
            "get_transparency",
        }

    def test_每个工具都有描述和入参结构(self):
        r = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        for t in r["result"]["tools"]:
            assert t["description"].strip(), f"{t['name']} 没有描述"
            assert t["inputSchema"]["type"] == "object"

    def test_未知方法回错误码(self):
        r = rpc({"jsonrpc": "2.0", "id": 5, "method": "什么鬼"})
        assert r["error"]["code"] == -32601

    def test_未知工具回错误码(self):
        r = rpc({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                 "params": {"name": "pay_order", "arguments": {}}})
        assert r["error"]["code"] == -32602


class Test坏输入不能把连接弄死:
    def test_坏行被跳过而不是退出(self):
        """一条格式错的消息不该让整个助手连接断掉 ——
        那种故障的表现是「用着用着突然没反应了」,极难排查。"""
        out = io.StringIO()
        mcp.serve(io.StringIO(
            "这不是 json\n"
            "\n"
            '{"jsonrpc":"2.0","id":9,"method":"ping"}\n'), out)
        lines = [l for l in out.getvalue().splitlines() if l]
        assert len(lines) == 1, f"坏行没被跳过:{lines}"
        assert json.loads(lines[0])["id"] == 9

    def test_工具抛异常不会崩掉服务(self, monkeypatch):
        def boom(**kw):
            raise mcp.ApiError(409, "这家店打烊了")
        monkeypatch.setitem(mcp.BY_NAME["get_menu"], "fn", boom)
        r = rpc({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                 "params": {"name": "get_menu",
                            "arguments": {"merchant_id": 1}}})
        # 业务错误走 isError,不是协议错误 —— 模型要看到那句中文,
        # 才知道是「打烊了」而不是「服务挂了」
        assert r["result"]["isError"] is True
        assert "打烊" in r["result"]["content"][0]["text"]

    def test_参数不对给的是人话(self, monkeypatch):
        r = rpc({"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                 "params": {"name": "get_menu",
                            "arguments": {"完全不认识的参数": 1}}})
        assert r["result"]["isError"] is True
        assert "参数" in r["result"]["content"][0]["text"]


class Test没有任何能付钱的工具:
    """整个 MCP 接入的支点。这几条红了,「助手花不掉你的钱」就不成立。"""

    def test_工具名里没有支付类动作(self):
        names = " ".join(mcp.BY_NAME)
        for word in ("pay", "payment", "checkout", "refund", "withdraw",
                     "settle", "transfer"):
            assert word not in names, (
                f"工具清单里出现了 {word!r} —— 助手不该有任何动钱的能力")

    def test_没有工具去打支付路径(self):
        """光看工具名不够:一个叫 `finish_order` 的工具照样能 POST 到
        /pay。所以扫的是**源码里出现过的路径**。"""
        import re
        src = Path(mcp.__file__).read_text()
        src = re.sub(r'"""(?:.|\n)*?"""', "", src)     # 剥文档字符串
        src = "\n".join(l.split("#", 1)[0] for l in src.splitlines())
        for bad in ("/pay", "/self-refund", "/refund-item", "/withdraw",
                    "/payout", "/appeals"):
            assert bad not in src, f"源码里出现了 {bad} —— 助手够不到这些"

    def test_创建订单的工具明说了它不付款(self):
        d = mcp.BY_NAME["create_pending_order"]["description"]
        assert "不会付款" in d and "付不了" in d, (
            "创建订单的工具描述没说清它不付款 —— **读描述的是模型不是人**,"
            "说不清楚它会以为下完单就完事了,然后告诉用户「已下单」")

    def test_算价工具明说了不下单(self):
        d = mcp.BY_NAME["quote_order"]["description"]
        assert "不下单" in d, (
            "比价工具没说清它不下单,模型可能改用 create_pending_order 去比价 ——"
            "那会造出一串垃圾订单")


class Test算价:
    def test_餐费按原价估并且说清楚了(self, monkeypatch):
        """不说清楚的话,模型会把这个数当成最终应付报给用户,
        而实际有满减和优惠券 —— 报高了用户觉得被坑,报低了到付款页才发现。"""
        monkeypatch.setattr(mcp, "api", lambda *a, **k: {"total_cents": 500})
        monkeypatch.setitem(
            mcp.BY_NAME["get_menu"], "fn",
            lambda merchant_id: [{"id": 1, "price_cents": 2000}])
        monkeypatch.setattr(mcp, "t_get_menu",
                            lambda mid: [{"id": 1, "price_cents": 2000}])
        out = mcp.t_quote_order(1, 30.6, 104.0,
                                items=[{"dish_id": 1, "quantity": 2}])
        assert out["food_cents"] == 4000
        assert "不含满减" in out["note"]

    def test_菜不在菜单里会被指出来(self, monkeypatch):
        monkeypatch.setattr(mcp, "api", lambda *a, **k: {"total_cents": 500})
        monkeypatch.setattr(mcp, "t_get_menu", lambda mid: [])
        out = mcp.t_quote_order(1, 30.6, 104.0,
                                items=[{"dish_id": 999, "quantity": 1}])
        assert out["missing_dish_ids"] == [999], (
            "菜不存在却静默算成 0 元 —— 模型会拿一个偏低的价报给用户")


class Test没有第三方依赖:
    def test_只用标准库(self):
        """开源项目,少一个依赖少一份供应链风险。"""
        import re
        src = Path(mcp.__file__).read_text()
        mods = set(re.findall(r"^import (\w+)", src, re.M))
        mods |= set(re.findall(r"^from (\w+)", src, re.M))
        allowed = {"json", "os", "sys", "urllib", "__future__"}
        assert mods <= allowed, f"引入了标准库之外的东西:{mods - allowed}"
