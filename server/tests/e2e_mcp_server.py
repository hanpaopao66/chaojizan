"""MCP 服务(mcp-server/server.py)对着真服务端走一遍:起一个 MCP 子进程,按 AI 客户端的方式
在 stdio 上说 JSON-RPC,点餐、发视频、发布小游戏三条链路各走到头。

单测(mcp-server/test_server.py)只管 MCP 自己的逻辑;这里管的是 **MCP 和服务端之间的约定** ——
服务端改了字段名或路径,MCP 那边不会报错,只会在用户叫助手干活的那一刻才坏。

    SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_mcp_server
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from tests.miniapp_util import CHECKLIST_ALL, HELLO, LISTING, admin_token, developer
from tests.util import BASE, call, demo_shop, register_fresh_customer
from tests.video_util import ffmpeg_clip, uploader

SERVER = Path(__file__).resolve().parents[2] / "mcp-server" / "server.py"


class Mcp:
    """一个 MCP 子进程。一问一答,按 id 对上。"""

    def __init__(self, token: str):
        env = {**os.environ, "SUPERZ_API": BASE, "SUPERZ_AGENT_TOKEN": token}
        self.p = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, env=env, text=True, bufsize=1)
        self.n = 0
        r = self.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                    "clientInfo": {"name": "e2e", "version": "0"}})
        assert r["result"]["serverInfo"]["name"] == "superz", r
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
                           + "\n")

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method,
                                       "params": params or {}}, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        assert line, "MCP 进程没回话就退出了"
        msg = json.loads(line)
        assert msg.get("id") == self.n, msg
        return msg

    def tools(self) -> set[str]:
        return {t["name"] for t in self.rpc("tools/list")["result"]["tools"]}

    def call(self, tool: str, /, **args):
        r = self.rpc("tools/call", {"name": tool, "arguments": args})["result"]
        text = r["content"][0]["text"]
        if r.get("isError"):
            return {"_error": text}
        return json.loads(text)

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)


def main() -> None:
    # ---- 点餐:只勾点餐的令牌只看得到点餐的工具;算价 → 下待支付单,付不了款 ----
    # 自己注册一个顾客,不用演示号:CI 分组并行时同一组前面的套件也在拿演示号下单,
    # 同一分钟里撞上「每人每分钟 20 单」的限流,而 MCP 这一路不会像测试工具那样自动重试
    cust = register_fresh_customer()
    m = Mcp(call("POST", "/auth/agent-tokens", cust, {"name": "MCP 点餐"})["token"])
    tools = m.tools()
    assert "create_pending_order" in tools and "publish_video" not in tools, tools
    who = m.call("whoami")
    assert who["scope_labels"] == ["点餐"], who
    shop = demo_shop()
    dishes = [d for d in m.call("get_menu", merchant_id=shop["id"])
              if d.get("is_on_sale", True) and not d.get("sold_out_today") and not d.get("options")]
    dish = max(dishes, key=lambda d: d["price_cents"])
    qty = max(1, -(-2000 // dish["price_cents"]))          # 凑过起送价
    q = m.call("quote_order", merchant_id=shop["id"], lat=30.66, lng=104.08,
               items=[{"dish_id": dish["id"], "quantity": qty}])
    assert q["food_cents"] == dish["price_cents"] * qty and "delivery" in q, q
    o = m.call("create_pending_order", merchant_id=shop["id"],
               items=[{"dish_id": dish["id"], "quantity": qty}],
               address="MCP 测试地址", lat=30.66, lng=104.08)
    assert "order" in o, f"下待支付单失败:{o}"
    no = o["order"]["order_no"]
    assert o["order"]["status"] == "pending_payment" and "还没付钱" in o["next_step"], o
    assert m.call("get_order_status", order_no=no)["order_no"] == no
    r = m.call("publish_video", file_path="/tmp/x.mp4", title="t", zone="tech")
    assert "没有「发视频」权限" in r["_error"], r        # 没权限的工具不发请求,说清去哪签
    m.close()
    call("POST", f"/orders/{no}/transition", cust, {"to_status": "cancelled", "reason": "测试清场"})
    print("✓ 点餐:只列点餐工具;算价 → 待支付单,停在付款前;没权限的工具说清去哪签")

    # ---- 发视频:一句话从本机文件投到「审核中」----
    up = uploader("139")
    m = Mcp(call("POST", "/auth/agent-tokens", up.token,
                 {"name": "MCP 投稿", "scopes": ["video"]})["token"])
    assert {"publish_video", "get_video_status"} <= m.tools()
    assert "create_pending_order" not in m.tools()
    with tempfile.TemporaryDirectory() as d:
        clip = Path(d) / "旅行.mp4"
        clip.write_bytes(ffmpeg_clip(640, 360, 3))
        bad = Path(d) / "id_rsa"                        # 私钥文件的样子:没有扩展名
        bad.write_bytes(b"ssh key stand-in, not a real key")
        r = m.call("publish_video", file_path=str(bad), title="t", zone="tech")
        assert "_error" in r and "不传" in r["_error"], r   # 别的文件在发请求之前就拦下
        out = m.call("publish_video", file_path=str(clip), title="MCP 投的稿", zone="tech",
                     description="一句话发出去的", tags=["MCP"])
    vid = out["vid"]
    assert "审核" in out["next_step"], out
    deadline = time.time() + 240
    while (st := m.call("get_video_status", vid=vid))["status"] != "reviewing":
        assert time.time() < deadline, f"四分钟没进审核:{st['status']}"
        time.sleep(1)
    assert st["title"] == "MCP 投的稿", st
    m.close()
    print("✓ 发视频:本机文件 → 建稿 → 分片传片 → 提审,停在「审核中」;私钥文件在发请求前被拦下")

    # ---- 发布小游戏:给一个构建好的文件夹,打包 → 传 → 提审 → 平台审过 → 发布上线 ----
    dev_token, _ = developer()
    m = Mcp(call("POST", "/auth/agent-tokens", dev_token, {"name": "MCP 发布"})["token"])
    assert {"upload_miniapp_version", "release_miniapp_version"} <= m.tools()
    app = m.call("create_miniapp", name=f"MCP小游戏{uuid.uuid4().hex[:4]}", kind="game",
                 category="casual", tagline="MCP 发布的小游戏")
    appid = app["app"]["appid"]
    m.call("update_miniapp_listing", appid=appid, description=LISTING["description"],
           privacy_policy=LISTING["privacy_policy"])
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for name, body in HELLO.items():
            (root / name).write_text(body, encoding="utf-8")
        (root / "superz.json").write_text(json.dumps(
            {"sdk": "2", "kind": "game", "orientation": "portrait",
             "background_color": "#F0EEE6", "spa_fallback": False}), encoding="utf-8")
        (root / ".env").write_text("SECRET=不该进包", encoding="utf-8")
        v = m.call("upload_miniapp_version", appid=appid, path=str(root), version="1.0.0",
                   changelog="MCP 传的第一版")
    assert ".env" in v["skipped_files"], v
    vid_ = v["version"]["id"]
    files = {f["path"] for f in call("GET", f"/dev/v1/apps/{appid}/versions/{vid_}", dev_token)["files"]}
    assert ".env" not in files and "index.html" in files, files
    r = m.call("release_miniapp_version", appid=appid, version_id=vid_)
    assert "_error" in r, f"没过审的版本发布上线了:{r}"
    m.call("submit_miniapp_review", appid=appid, version_id=vid_, review_note="打开就是首页")
    call("POST", f"/admin/mini-apps/reviews/{vid_}/decide", admin_token(),
         {"approve": True, "checklist": CHECKLIST_ALL})        # 审核是平台的人做的
    live = m.call("release_miniapp_version", appid=appid, version_id=vid_)
    assert (live.get("current_version") or {}).get("id") == vid_, live
    assert any(x["id"] == vid_ for x in m.call("list_miniapp_versions", appid=appid)["items"])
    m.close()
    print("✓ 发布小游戏:文件夹打包(.env 没进包)→ 传 → 提审 → 平台审过 → 发布上线;没过审的发不了")

    for tok in (cust, up.token, dev_token):
        for x in call("GET", "/auth/agent-tokens", tok):
            if not x["revoked"]:
                call("DELETE", f"/auth/agent-tokens/{x['id']}", tok)
    print("e2e_mcp_server 全部通过 ✅")


if __name__ == "__main__":
    main()
