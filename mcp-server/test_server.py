"""MCP 服务的协议层与工具清单。

## 这一组守什么

两件事,分开测:

1. **协议**:握手、列工具、调用、坏输入。这一层不碰网络 —— 喂 JSON-RPC 帧
   进去看回什么。协议错了的表现是「助手连不上」或者「用着用着没反应」,
   而那种故障从业务侧完全看不出来。
2. **能力边界**:工具清单里**不许出现任何能付钱的工具**。这是整个
   MCP 接入的支点,而它在这一层是可以静态断言的。

服务端那一侧另有一百多条单测 + 2 条 e2e 守着同一件事
(`server/tests/unit/test_agent_scope.py`、`e2e_agent_token`、`e2e_agent_scopes`)——
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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """协议层的测试不碰网络:默认「不知道这个令牌能做什么」(= 全列)"""
    monkeypatch.setattr(mcp, "current_scopes", lambda: None)


ORDER_TOOLS = {"search_merchants", "get_menu", "quote_order", "create_pending_order",
               "get_order_status", "list_my_orders", "get_transparency"}
VIDEO_TOOLS = {"list_video_zones", "publish_video", "submit_video", "update_video_info",
               "get_video_status", "list_my_videos"}
MINIAPP_TOOLS = {"get_developer_account", "list_developer_messages", "list_my_miniapps",
                 "create_miniapp", "update_miniapp_listing", "get_miniapp",
                 "upload_miniapp_version", "list_miniapp_versions", "set_trial_version",
                 "submit_miniapp_review", "cancel_miniapp_review", "release_miniapp_version",
                 "rollback_miniapp", "get_review_decisions"}


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
        assert names == {"whoami"} | ORDER_TOOLS | VIDEO_TOOLS | MINIAPP_TOOLS

    def test_每个工具都标了属于哪项权限(self):
        for t in mcp.TOOLS:
            assert t["scope"] in (None, "order", "video", "miniapp"), t["name"]
        assert {t["name"] for t in mcp.TOOLS if t["scope"] == "order"} == ORDER_TOOLS
        assert {t["name"] for t in mcp.TOOLS if t["scope"] == "video"} == VIDEO_TOOLS
        assert {t["name"] for t in mcp.TOOLS if t["scope"] == "miniapp"} == MINIAPP_TOOLS

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
        for bad in ("/pay", "/self-refund", "/refund-item", "/withdrawals",
                    "/payout", "/appeals", "/secret", "/domains", "/remove", "/verify",
                    "/agreement"):
            assert bad not in src, f"源码里出现了 {bad} —— 助手够不到这些"
        # 「/withdraw」只许出现在小程序的「撤回审核」上(/versions/{id}/withdraw)——
        # 提现是 /withdrawals,上面那条管着;这里别让它换个样子溜进来
        for m in re.finditer(r"/withdraw\b", src):
            line = src[src.rfind("\n", 0, m.start()) + 1:src.find("\n", m.start())]
            assert "/versions/" in line, f"撤回审核以外的地方出现了 /withdraw:{line.strip()}"

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
        """开源项目,少一个依赖少一份供应链风险。按解释器自带的「标准库清单」核,
        不维护一份手写的允许列表(手写的那份每用一个新的标准库模块都要改,改着改着就松了)。"""
        import re
        src = Path(mcp.__file__).read_text()
        mods = set(re.findall(r"^import (\w+)", src, re.M))
        mods |= set(re.findall(r"^from (\w+)", src, re.M))
        outside = {m for m in mods if m not in sys.stdlib_module_names}
        assert not outside, f"引入了标准库之外的东西:{outside}"


class Test按权限只列能用的工具:
    """列出来却调不通的工具,模型会一遍遍试。"""

    def test_只勾发视频的只看到发视频的工具(self, monkeypatch):
        monkeypatch.setattr(mcp, "current_scopes", lambda: {"video"})
        r = rpc({"jsonrpc": "2.0", "id": 20, "method": "tools/list"})
        assert {t["name"] for t in r["result"]["tools"]} == {"whoami"} | VIDEO_TOOLS

    def test_开发者令牌只看到发布小程序的工具(self, monkeypatch):
        monkeypatch.setattr(mcp, "current_scopes", lambda: {"miniapp"})
        r = rpc({"jsonrpc": "2.0", "id": 21, "method": "tools/list"})
        assert {t["name"] for t in r["result"]["tools"]} == {"whoami"} | MINIAPP_TOOLS

    def test_调没权限的工具不发请求并说清去哪签(self, monkeypatch):
        monkeypatch.setattr(mcp, "current_scopes", lambda: {"order"})
        monkeypatch.setattr(mcp, "api", lambda *a, **k: pytest.fail("不该发请求"))
        r = rpc({"jsonrpc": "2.0", "id": 22, "method": "tools/call",
                 "params": {"name": "list_my_videos", "arguments": {}}})
        text = r["result"]["content"][0]["text"]
        assert r["result"]["isError"] and "发视频" in text and "AI 助手" in text


class Test本机文件只认那几类:
    """MCP 跑在用户电脑上,读得到任何文件。被网页里的一句话诱导着把 ~/.ssh 传出去,
    这一层要在**发请求之前**就拦下。"""

    def _f(self, tmp_path, name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return str(p)

    def test_扩展名不对不传(self, tmp_path):
        for name in ("id_rsa", "notes.txt", "secret.pem", "data.zip.txt"):
            with pytest.raises(mcp.ToolError):
                mcp.local_file(self._f(tmp_path, name, b"\x00\x00\x00\x18ftypmp42"), "video")

    def test_改了扩展名的也不传(self, tmp_path):
        with pytest.raises(mcp.ToolError, match="文件头"):
            mcp.local_file(self._f(tmp_path, "fake.mp4", b"%PDF-1.7 not a video, renamed"), "video")
        with pytest.raises(mcp.ToolError, match="文件头"):
            mcp.local_file(self._f(tmp_path, "fake.zip", b"not a zip at all"), "zip")

    def test_真的视频图片和包放行(self, tmp_path):
        mcp.local_file(self._f(tmp_path, "a.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64), "video")
        mcp.local_file(self._f(tmp_path, "a.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 64), "video")
        mcp.local_file(self._f(tmp_path, "c.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64), "image")
        mcp.local_file(self._f(tmp_path, "p.zip", b"PK\x03\x04" + b"\x00" * 64), "zip")

    def test_空文件和找不到的文件(self, tmp_path):
        with pytest.raises(mcp.ToolError, match="空文件"):
            mcp.local_file(self._f(tmp_path, "e.mp4", b""), "video")
        with pytest.raises(mcp.ToolError, match="找不到"):
            mcp.local_file(str(tmp_path / "nope.mp4"), "video")


class Test打包文件夹:
    def test_根目录要有入口和清单(self, tmp_path):
        (tmp_path / "index.html").write_text("<h1>hi</h1>")
        with pytest.raises(mcp.ToolError, match="superz.json"):
            mcp.zip_dir(str(tmp_path))

    def test_只装允许的扩展名_点开头的和密钥进不了包(self, tmp_path):
        import zipfile
        (tmp_path / "index.html").write_text("<h1>hi</h1>")
        (tmp_path / "superz.json").write_text('{"sdk": "2"}')
        (tmp_path / "js").mkdir()
        (tmp_path / "js" / "app.js").write_text("1")
        (tmp_path / ".env").write_text("SECRET=1")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "x.js").write_text("1")
        (tmp_path / "server.pem").write_text("KEY")
        (tmp_path / "build.py").write_text("print(1)")
        (tmp_path / "link.js").symlink_to(tmp_path / ".env")
        data, skipped = mcp.zip_dir(str(tmp_path))
        names = set(zipfile.ZipFile(__import__("io").BytesIO(data)).namelist())
        assert names == {"index.html", "superz.json", "js/app.js"}, names
        for s in (".env", ".git/", "node_modules/", "server.pem", "build.py", "link.js"):
            assert s in skipped, (s, skipped)


class Test发视频一条龙:
    def test_顺序对_默认提交审核(self, tmp_path, monkeypatch):
        clip = tmp_path / "v.mp4"
        clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100)
        calls = []

        def fake(method, path, **kw):
            calls.append((method, path))
            if path == "/video/v1/uploads/videos":
                return {"vid": "sv2BcDeFgHiJ"}
            if path == "/media/v1/uploads":
                assert kw["body"]["purpose"] == "video" and kw["body"]["kind"] == "video_source"
                return {"id": "a" * 32, "chunk_size": 50, "chunks": 3}
            if path.endswith("/complete"):
                return {"id": 7}
            if path.endswith("/submit"):
                return {"status": "processing"}
            return {}
        monkeypatch.setattr(mcp, "api", fake)
        out = mcp.t_publish_video(str(clip), "标题", "tech")
        assert calls == [
            ("POST", "/video/v1/uploads/videos"),
            ("POST", "/media/v1/uploads"),
            ("PUT", f"/media/v1/uploads/{'a' * 32}/chunks/0"),
            ("PUT", f"/media/v1/uploads/{'a' * 32}/chunks/1"),
            ("PUT", f"/media/v1/uploads/{'a' * 32}/chunks/2"),
            ("POST", f"/media/v1/uploads/{'a' * 32}/complete"),
            ("POST", "/video/v1/videos/sv2BcDeFgHiJ/parts"),
            ("POST", "/video/v1/videos/sv2BcDeFgHiJ/submit"),
        ]
        assert out["vid"] == "sv2BcDeFgHiJ" and "审核" in out["next_step"]

    def test_不提交就停在草稿(self, tmp_path, monkeypatch):
        clip = tmp_path / "v.mp4"
        clip.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 10)
        paths = []

        def fake(method, path, **kw):
            paths.append(path)
            return {"vid": "sv2BcDeFgHiJ", "id": "b" * 32, "chunk_size": 100, "chunks": 1}
        monkeypatch.setattr(mcp, "api", fake)
        out = mcp.t_publish_video(str(clip), "标题", "tech", submit=False)
        assert not any(p.endswith("/submit") for p in paths)
        assert out["status"] == "draft" and "submit_video" in out["next_step"]

    def test_发布工具说清了审核由人做_只在用户要求时调用(self):
        d = mcp.BY_NAME["publish_video"]["description"]
        assert "审核" in d and "平台的人" in d and "明确要求" in d
        d = mcp.BY_NAME["release_miniapp_version"]["description"]
        assert "审核通过" in d and "明确要求" in d


class Test传小程序包:
    def test_给文件夹就打包再传(self, tmp_path, monkeypatch):
        (tmp_path / "index.html").write_text("<h1>hi</h1>")
        (tmp_path / "superz.json").write_text('{"sdk": "2"}')
        (tmp_path / ".env").write_text("SECRET=1")
        seen = {}

        def fake(method, path, **kw):
            seen.update(method=method, path=path, ctype=kw.get("content_type"), data=kw.get("data"))
            return {"version": {"id": 3}}
        monkeypatch.setattr(mcp, "api", fake)
        out = mcp.t_upload_miniapp_version("sz0123456789abcdef", str(tmp_path), "1.0.0", "首版")
        assert seen["method"] == "POST" and seen["path"] == "/dev/v1/apps/sz0123456789abcdef/versions"
        assert seen["ctype"].startswith("multipart/form-data")
        assert b"SECRET" not in seen["data"], "点开头的文件进了包"
        assert ".env" in out["skipped_files"] and "submit_miniapp_review" in out["next_step"]

