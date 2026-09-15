"""机器人平台 e2e(DEV-PROMPTS-40 #355,§5.13;接口文档 docs/BOT-API.md)。

从开发者建机器人到用户和它说话,全走真接口:
- 开发者后台建机器人拿 token(只显示一次)、详情不含 token、越权 404、每人最多 20 个;
- token 不对 401、方法不存在 404;getMe;
- 用户 @用户名 找到机器人、打开私聊;机器人主动发给没说过话的人 403;用户发 /start → getUpdates 收到
  (带 bot_command 实体),offset 确认后不再重复;
- 机器人发带内联键盘的消息 → 用户拉消息看到 markup(形状逐字对契约);键盘的各种不合法写法 400;
- 用户点回调按钮(开线程发请求)→ 机器人 getUpdates 拿到 callback_query → answerCallbackQuery →
  用户那边拿到 answered + text;伪造 callback_data 400;没人回话 10 秒后 answered=false;
- editMessageText / editMessageReplyMarkup / deleteMessage(只能删自己的);用户改消息 → edited_message;
- setMyCommands → bot-info 里有;菜单按钮:命令列表、指向未上架小程序 400、指向自己已上架的小程序;
- 群:拉进群有 my_chat_member;隐私模式下普通消息不投,/cmd、/cmd@bot、@bot、回复机器人的都投,
  /cmd@别的机器人不投;关掉隐私模式后普通消息也投;移出群有 my_chat_member;
- sendPhoto / sendDocument(multipart 上传、复用自己的 file_id;别的机器人的 file_id、URL 一律 400);
- 用户拉黑后 403 + my_chat_member(kicked);限流 429 带 retry_after;
- webhook:本地起一个 HTTP 服务先回 500 再回 200,用 SQL 把 next_try_at 拨到现在触发重试,
  断言第二次投成、带 secret 头、按 update_id 顺序;created_at 拨回 25 小时的更新被丢弃;
  设了 webhook 时 getUpdates 409;
- bots_enabled=off 时 Bot API、建机器人、回调、bot-info 全部 503;
- 服务端日志里没有完整 token(只认得出前 6 位);
- 删机器人:它发的消息对方看不到了、token 失效、用户名释放。

跑法:SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… [SUPERZ_API_LOG=服务端日志] python -m tests.e2e_bots
(日志那一项读 SUPERZ_API_LOG,没设时读 /tmp/api.log —— CI 就是把服务端输出重定向到那里)
"""
import http.server
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from tests.chat_util import person, sql
from tests.e2e_media import png_bytes
from tests.miniapp_util import admin_token, developer, multipart, new_app, publish
from tests.util import BASE, call

GROUP_BASE = 10 ** 12


# ---------------------------------------------------------------- Bot API 客户端

def bot_raw(token: str, method: str, params: dict | None = None, *, files: dict | None = None,
            get: bool = False, form: bool = False, timeout: float = 70) -> dict:
    """调一次 Bot API,不管成功失败都把响应体(加上 _status)还回来。"""
    params = {k: v for k, v in (params or {}).items() if v is not None}
    url = f"{BASE}/bot/{token}/{method}"
    data = None
    headers = {}
    if get:
        url += "?" + urllib.parse.urlencode(params)
    elif files is not None or form:
        fields = {k: (v if isinstance(v, str) else json.dumps(v)) for k, v in params.items()}
        if files is not None:
            data, ctype = multipart(fields, files)
        else:
            data, ctype = urllib.parse.urlencode(fields).encode(), "application/x-www-form-urlencoded"
        headers["Content-Type"] = ctype
    else:
        data = json.dumps(params).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method="GET" if get else "POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    body = json.loads(raw)
    body["_status"] = status
    # 和 Telegram 一样:HTTP 状态码 = error_code
    assert body["ok"] == (status == 200), body
    if not body["ok"]:
        assert body["error_code"] == status, body
    return body


class BotClient:
    def __init__(self, token: str):
        self.token = token
        self.offset: int | None = None
        self.seen: list[dict] = []

    @property
    def id(self) -> int:
        return int(self.token.split(":")[0])

    def call(self, method: str, params: dict | None = None, **kw) -> dict:
        return bot_raw(self.token, method, params, **kw)

    def ok(self, method: str, params: dict | None = None, **kw):
        r = self.call(method, params, **kw)
        assert r["ok"], f"{method} 失败:{r}"
        return r["result"]

    def err(self, method: str, params: dict | None = None, code: int = 400, **kw) -> dict:
        r = self.call(method, params, **kw)
        assert not r["ok"] and r["error_code"] == code, f"{method} 期望 {code},拿到 {r}"
        return r

    def poll(self, timeout: int = 0) -> list[dict]:
        res = self.ok("getUpdates", {"offset": self.offset, "timeout": timeout})
        if res:
            self.offset = res[-1]["update_id"] + 1
            self.seen.extend(res)
        return res

    def wait(self, pred, secs: float = 8) -> dict:
        deadline = time.time() + secs
        while True:
            for u in self.seen:
                if pred(u):
                    self.seen.remove(u)
                    return u
            left = deadline - time.time()
            if left <= 0:
                raise AssertionError(f"{secs}s 内没等到期望的更新;收到过:{self.seen[-8:]}")
            self.poll(timeout=max(1, min(3, int(left))))

    def quiet(self, pred, secs: float = 1.5) -> None:
        """一段时间内不该收到满足 pred 的更新。"""
        deadline = time.time() + secs
        while time.time() < deadline:
            self.poll(timeout=1)
        bad = [u for u in self.seen if pred(u)]
        assert not bad, f"不该收到的更新:{bad}"

    def drain(self) -> None:
        """取完并确认手上所有更新(确认 = 带着更大的 offset 再调一次,之前的就删了)。"""
        while self.poll():
            pass
        if self.offset is not None:
            self.ok("getUpdates", {"offset": self.offset})
        self.seen.clear()


def msg_text(text: str):
    return lambda u: (u.get("message") or {}).get("text") == text


def dev_call(token: str, method: str, path: str, body=None, expect_error: bool = False):
    return call(method, path, token, body, expect_error=expect_error, retry_429=False)


# ---------------------------------------------------------------- webhook 接收端

class Hook(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        srv = self.server
        with srv.lock:
            status = srv.statuses.pop(0) if srv.statuses else srv.default
            srv.hits.append({"secret": self.headers.get("X-Superz-Bot-Api-Secret-Token"),
                             "update": json.loads(body), "status": status})
        self.send_response(status)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *a):
        pass


def hook_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hook)
    srv.hits, srv.statuses, srv.default, srv.lock = [], [], 200, threading.Lock()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def wait_hits(srv, n: int, secs: float = 10) -> list[dict]:
    deadline = time.time() + secs
    while time.time() < deadline:
        with srv.lock:
            if len(srv.hits) >= n:
                return list(srv.hits)
        time.sleep(0.1)
    raise AssertionError(f"{secs}s 内 webhook 只收到 {len(srv.hits)} 次,期望 {n} 次:{srv.hits}")


def set_flag(value: str) -> None:
    call("POST", "/admin/flags/bots_enabled", admin_token(), {"value": value, "reason": "e2e_bots"})


def keyboard(appid: str) -> dict:
    return {"inline_keyboard": [
        [{"text": "好的", "callback_data": "ok"}, {"text": "官网", "url": "https://chaojizan.cc/"}],
        [{"text": "打开小程序", "web_app": {"app_id": appid}}],
        [{"text": "没人回话", "callback_data": "slow"}],
    ]}


def main():
    set_flag("on")
    dev_token, _ = developer()
    other_dev, _ = developer(verified=False, accept_rules=False)
    a, b, c = person(), person(), person()
    print(f"  账号:A={a.id} B={b.id} C={c.id}")

    # 小程序:一个已上架(菜单、web_app 按钮用),一个草稿(应当被拒)
    live_app = new_app(dev_token)["app"]["appid"]
    publish(dev_token, live_app)
    draft_app = new_app(dev_token)["app"]["appid"]

    # ---- 建机器人:token 只出现一次;详情里没有 ----
    uname = f"e2e{random.randint(100000, 999999)}bot"
    e = dev_call(dev_token, "POST", "/dev/v1/bots", {"name": "点餐助手", "username": "e2enotbotname"},
                 expect_error=True)
    assert e["_error"] == 422 and "bot" in e["detail"], e
    r = dev_call(dev_token, "POST", "/dev/v1/bots", {"name": "点餐助手", "username": uname})
    token = r["token"]
    assert re.fullmatch(r"\d+:[A-Za-z0-9_-]{35}", token), token
    bot = BotClient(token)
    assert r["bot"]["id"] == bot.id and r["bot"]["username"] == uname and \
        r["bot"]["token_prefix"] == token[:6], r["bot"]
    detail = dev_call(dev_token, "GET", f"/dev/v1/bots/{bot.id}")
    assert token not in json.dumps(detail) and token[6:] not in json.dumps(detail), "详情里不许有 token"
    lst = dev_call(dev_token, "GET", "/dev/v1/bots")
    assert any(x["id"] == bot.id for x in lst["items"]) and token not in json.dumps(lst)
    e = dev_call(dev_token, "POST", "/dev/v1/bots", {"name": "撞名", "username": uname.upper()},
                 expect_error=True)
    assert e["_error"] == 409, e
    print(f"  ✓ 开发者建机器人:token {token[:6]}… 只在这一次响应里;用户名要 bot 结尾、大小写不敏感查重")

    # ---- 越权:别的开发者看不到、改不了、删不掉 ----
    for method, path, body in (("GET", f"/dev/v1/bots/{bot.id}", None),
                               ("PUT", f"/dev/v1/bots/{bot.id}", {"about": "偷改"}),
                               ("POST", f"/dev/v1/bots/{bot.id}/token", {}),
                               ("PUT", f"/dev/v1/bots/{bot.id}/webhook", {"url": "https://example.com/x"}),
                               ("DELETE", f"/dev/v1/bots/{bot.id}", None)):
        e = dev_call(other_dev, method, path, body, expect_error=True)
        assert (e or {}).get("_error") == 404, f"别的开发者 {method} {path} 应当 404,拿到 {e}"
    assert all(x["id"] != bot.id for x in dev_call(other_dev, "GET", "/dev/v1/bots")["items"])
    print("  ✓ 越权:别的开发者对这个机器人的查看、修改、重置 token、设 webhook、删除一律 404")

    # ---- token 不对 401,方法不存在 404,getMe ----
    fake = f"{bot.id}:{'A' * 35}"
    assert bot_raw(fake, "getMe")["error_code"] == 401
    assert bot_raw("not-a-token", "getMe")["error_code"] == 401
    nonce = uuid.uuid4().hex[:8]
    r = bot_raw(token, f"noSuchMethod{nonce}")
    assert r["error_code"] == 404 and r["description"] == "Not Found", r
    me = bot.ok("getMe", get=True)
    assert me["id"] == bot.id and me["is_bot"] is True and me["username"] == uname \
        and me["can_read_all_group_messages"] is False, me
    print("  ✓ token 不对 401、方法不存在 404;getMe(GET 也收)")

    # ---- 用户 @用户名 找到它、打开私聊;没说过话的人发不了 ----
    found = a.get(f"/social/v1/resolve/{uname}")
    assert found["type"] == "user" and found["user"]["id"] == bot.id and found["user"]["is_bot"] is True
    assert a.get(f"/social/v1/users/{bot.id}")["is_bot"] is True
    chat = a.post("/chat/v1/chats/private", {"user_id": bot.id})
    cid = chat["id"]
    assert chat["peer"]["is_bot"] is True, chat["peer"]
    r = bot.err("sendMessage", {"chat_id": a.id, "text": "你好"}, 403)
    assert "can't initiate conversation" in r["description"], r
    bot.err("sendMessage", {"chat_id": c.id, "text": "广告"}, 403)
    bot.err("sendChatAction", {"chat_id": a.id, "action": "typing"}, 403)
    print("  ✓ 用户按 @用户名 找到机器人(is_bot)、打开私聊;机器人主动发给没说过话的人 403")

    # ---- /start → getUpdates;offset 确认后不再重复 ----
    a.send(cid, "/start")
    u = bot.wait(msg_text("/start"))
    m = u["message"]
    assert m["chat"] == {"id": a.id, "type": "private", "first_name": a.name} or \
        (m["chat"]["id"] == a.id and m["chat"]["type"] == "private"), m["chat"]
    assert m["from"]["id"] == a.id and m["from"]["is_bot"] is False, m["from"]
    assert m["entities"] == [{"type": "bot_command", "offset": 0, "length": 6}], m.get("entities")
    first_id = u["update_id"]
    assert bot.ok("getUpdates", {"offset": first_id + 1}) == []
    assert all(x["update_id"] > first_id for x in bot.ok("getUpdates")), "确认过的更新又回来了"
    n = sql("SELECT count(*) FROM bot_updates WHERE bot_id=:b AND update_id<=:u",
            {"b": bot.id, "u": first_id}, fetch="scalar")
    assert n == 0, f"offset 之前的更新应该删掉,还剩 {n} 条"
    print("  ✓ 用户发 /start → getUpdates 收到(chat.id = 用户 id,带 bot_command 实体);offset 确认后删掉不再重复")

    # ---- 内联键盘:发出去、用户看到的形状逐字对契约 ----
    kb = keyboard(live_app)
    sent = bot.ok("sendMessage", {"chat_id": a.id, "text": "要下单吗?", "reply_markup": kb})
    seq = sent["message_id"]
    assert sent["reply_markup"] == kb and sent["chat"]["id"] == a.id and sent["from"]["id"] == bot.id
    msgs = a.get(f"/chat/v1/chats/{cid}/messages?limit=10")["messages"]
    mine = next(x for x in msgs if x["seq"] == seq)
    assert mine["markup"] == kb, mine["markup"]
    assert mine["sender"]["is_bot"] is True and mine["text"] == "要下单吗?", mine["sender"]
    # 表单写法(reply_markup 是 JSON 字符串)也收
    sent2 = bot.ok("sendMessage", {"chat_id": str(a.id), "text": "表单也行", "reply_markup": kb},
                   form=True)
    assert sent2["reply_markup"] == kb
    bad_markups = [
        ({"keyboard": [[{"text": "回复键盘"}]]}, "回复键盘"),
        ({"inline_keyboard": [[{"text": "x", "callback_data": "a" * 65}]]}, "BUTTON_DATA_INVALID"),
        ({"inline_keyboard": [[{"text": "x", "callback_data": "a", "url": "https://a.cn"}]]}, "只有一个动作"),
        ({"inline_keyboard": [[{"text": "x"}]]}, "只有一个动作"),
        ({"inline_keyboard": [[{"text": "x", "url": "javascript:alert(1)"}]]}, "BUTTON_URL_INVALID"),
        ({"inline_keyboard": [[{"text": str(i), "callback_data": str(i)} for i in range(9)]]}, "8 个"),
        ({"inline_keyboard": [[{"text": "x", "callback_data": str(i)}] for i in range(101)]}, "100 个"),
        ({"inline_keyboard": [[{"text": "x", "web_app": {"app_id": draft_app}}]]}, "已上架"),
        ({"inline_keyboard": [[{"text": "x", "login_url": {"url": "https://a.cn"}}]]}, "不支持的按钮"),
    ]
    time.sleep(1.2)
    for mk, word in bad_markups:
        r = bot.err("sendMessage", {"chat_id": a.id, "text": "坏键盘", "reply_markup": mk}, 400)
        assert word in r["description"], (mk, r)
    r = bot.err("sendMessage", {"chat_id": a.id, "text": "<b>x</b>", "parse_mode": "HTML"}, 400)
    assert "parse_mode" in r["description"]
    print("  ✓ 内联键盘:用户拉到的 markup 和发的逐字相同;回复键盘、超长 callback_data、两个动作、"
          "javascript: 链接、一行 9 个、101 个、未上架小程序、别的按钮类型、parse_mode 全部 400")

    # ---- 回调:点按钮 → 机器人拿到 callback_query → 回话 → 用户拿到 ----
    out: dict = {}

    def press(data: str, key: str):
        out[key] = a.post(f"/chat/v1/chats/{cid}/messages/{seq}/callback", {"data": data})

    t = threading.Thread(target=press, args=("ok", "ok"))
    t0 = time.time()
    t.start()
    u = bot.wait(lambda x: "callback_query" in x)
    q = u["callback_query"]
    assert q["data"] == "ok" and q["from"]["id"] == a.id and q["message"]["message_id"] == seq, q
    assert q["message"]["reply_markup"] == kb and q["chat_instance"], q
    bot.ok("answerCallbackQuery", {"callback_query_id": q["id"], "text": "已为你下单",
                                   "show_alert": True})
    t.join(12)
    assert out["ok"] == {"answered": True, "text": "已为你下单", "show_alert": True, "url": None}, out
    assert time.time() - t0 < 9, "机器人回话之后客户端应该马上拿到"
    bot.err("answerCallbackQuery", {"callback_query_id": q["id"], "text": "再回一次"}, 400)
    e = a.post(f"/chat/v1/chats/{cid}/messages/{seq}/callback", {"data": "forged"}, expect_error=True)
    assert e["_error"] == 400, e
    e = c.post(f"/chat/v1/chats/{cid}/messages/{seq}/callback", {"data": "ok"}, expect_error=True)
    assert e["_error"] == 403, e
    bot.quiet(lambda x: (x.get("callback_query") or {}).get("data") == "forged")
    t0 = time.time()
    r = a.post(f"/chat/v1/chats/{cid}/messages/{seq}/callback", {"data": "slow"})
    assert r == {"answered": False} and 9 <= time.time() - t0 <= 13, (r, time.time() - t0)
    bot.wait(lambda x: (x.get("callback_query") or {}).get("data") == "slow")
    print("  ✓ 回调:点按钮 → callback_query → answerCallbackQuery → 用户拿到 answered + text + show_alert;"
          "同一个查询回两次 400;伪造 callback_data 400(机器人收不到);非成员 403;10 秒没回话 answered=false")

    # ---- 改、删 ----
    kb2 = {"inline_keyboard": [[{"text": "已下单", "callback_data": "done"}]]}
    ed = bot.ok("editMessageText", {"chat_id": a.id, "message_id": seq, "text": "已下单 **1** 份",
                                    "entities": [{"type": "bold", "offset": 4, "length": 5}],
                                    "reply_markup": kb2})
    assert ed["text"] == "已下单 **1** 份" and ed["reply_markup"] == kb2 and ed["edit_date"], ed
    m = next(x for x in a.get(f"/chat/v1/chats/{cid}/messages?limit=10")["messages"] if x["seq"] == seq)
    assert m["text"] == "已下单 **1** 份" and m["markup"] == kb2 and m["edited_at"], m
    assert {"type": "bold", "offset": 4, "length": 5} in m["entities"], m["entities"]
    bot.err("editMessageText", {"chat_id": a.id, "message_id": seq, "text": "已下单 **1** 份",
                                "entities": [{"type": "bold", "offset": 4, "length": 5}],
                                "reply_markup": kb2}, 400)
    ed = bot.ok("editMessageReplyMarkup", {"chat_id": a.id, "message_id": seq})
    assert "reply_markup" not in ed
    m = next(x for x in a.get(f"/chat/v1/chats/{cid}/messages?limit=10")["messages"] if x["seq"] == seq)
    assert m["markup"] is None, m["markup"]
    start_seq = next(x["seq"] for x in a.get(f"/chat/v1/chats/{cid}/messages?limit=20")["messages"]
                     if x["text"] == "/start")
    r = bot.err("deleteMessage", {"chat_id": a.id, "message_id": start_seq}, 400)
    assert "can't be deleted" in r["description"], r
    assert bot.ok("deleteMessage", {"chat_id": a.id, "message_id": sent2["message_id"]}) is True
    left = [x["seq"] for x in a.get(f"/chat/v1/chats/{cid}/messages?limit=20")["messages"]]
    assert sent2["message_id"] not in left and start_seq in left, left
    a.patch(f"/chat/v1/chats/{cid}/messages/{start_seq}", {"text": "/start again"})
    u = bot.wait(lambda x: (x.get("edited_message") or {}).get("text") == "/start again")
    assert u["edited_message"]["message_id"] == start_seq and u["edited_message"]["edit_date"]
    print("  ✓ editMessageText(带实体、换键盘)/ editMessageReplyMarkup(去掉键盘)用户都看到;没改动 400;"
          "deleteMessage 只能删自己的;用户改消息 → edited_message")

    # ---- 命令、菜单按钮 → bot-info ----
    cmds = [{"command": "start", "description": "开始"}, {"command": "menu", "description": "看菜单"}]
    assert bot.ok("setMyCommands", {"commands": cmds}) is True
    assert bot.ok("getMyCommands") == cmds
    bot.err("setMyCommands", {"commands": [{"command": "Bad-Cmd", "description": "x"}]}, 400)
    bot.err("setMyCommands", {"commands": [{"command": "ok", "description": ""}]}, 400)
    info = a.get(f"/chat/v1/chats/{cid}/bot-info")["bots"]
    assert len(info) == 1, info
    # official:只有官方开发者名下的(机器人管家)是 true,第三方的都是 false(docs/BOT-API.md 10.3)
    assert info[0] == {"id": bot.id, "name": "点餐助手", "username": uname, "avatar": "",
                       "about": "", "description": "", "commands": cmds, "menu_button": None,
                       "privacy_mode": True, "official": False}, info[0]
    bot.ok("setChatMenuButton", {"menu_button": {"type": "commands"}})
    assert a.get(f"/chat/v1/chats/{cid}/bot-info")["bots"][0]["menu_button"] == {"type": "commands"}
    r = bot.err("setChatMenuButton", {"menu_button": {"type": "web_app", "text": "点餐",
                                                      "web_app": {"app_id": draft_app}}}, 400)
    assert "已上架" in r["description"], r
    bot.err("setChatMenuButton", {"menu_button": {"type": "web_app", "text": "点餐",
                                                  "web_app": {"url": "https://evil.example"}}}, 400)
    bot.ok("setChatMenuButton", {"menu_button": {"type": "web_app", "text": "点餐",
                                                 "web_app": {"app_id": live_app}}})
    mb = a.get(f"/chat/v1/chats/{cid}/bot-info")["bots"][0]["menu_button"]
    assert mb["type"] == "web_app" and mb["text"] == "点餐" and mb["app_id"] == live_app \
        and mb["app"]["name"] and "icon" in mb["app"], mb
    assert bot.ok("getChatMenuButton") == {"type": "web_app", "text": "点餐",
                                           "web_app": {"app_id": live_app}}
    e = dev_call(dev_token, "PUT", f"/dev/v1/bots/{bot.id}/menu-button",
                 {"type": "web_app", "text": "x", "app_id": draft_app}, expect_error=True)
    assert e["_error"] == 422, e
    dev_call(dev_token, "PUT", f"/dev/v1/bots/{bot.id}",
             {"about": "帮你点外卖", "description": "发 /menu 看今天的菜"})
    got = a.get(f"/chat/v1/chats/{cid}/bot-info")["bots"][0]
    assert got["about"] == "帮你点外卖" and got["description"] == "发 /menu 看今天的菜"
    # 资料页(用户卡片)上也要有简介:机器人没有自己的社交签名,拿 about 当签名
    card = a.get(f"/social/v1/users/{bot.id}")
    assert card["is_bot"] is True and card["bio"] == "帮你点外卖", card
    print("  ✓ setMyCommands → bot-info 里有;菜单按钮:命令列表 / 未上架小程序 400 / 任意网址 400 / "
          "自己已上架的小程序(带名字和图标);简介、描述从后台改")

    # ---- 群:拉进群、隐私模式 ----
    other_uname = f"e2e{random.randint(100000, 999999)}bot"
    other = BotClient(dev_call(dev_token, "POST", "/dev/v1/bots",
                               {"name": "别的机器人", "username": other_uname})["token"])
    g = a.post("/chat/v1/chats", {"type": "group", "title": "机器人测试群", "member_ids": [b.id]})
    gid = g["id"]
    tg_gid = -(GROUP_BASE + gid)
    r = a.post(f"/chat/v1/chats/{gid}/members", {"user_ids": [bot.id, other.id]})
    assert sorted(r["added"]) == sorted([bot.id, other.id]), r
    u = bot.wait(lambda x: "my_chat_member" in x)
    mcm = u["my_chat_member"]
    assert mcm["chat"] == {"id": tg_gid, "type": "group", "title": "机器人测试群"}, mcm["chat"]
    assert mcm["from"]["id"] == a.id and mcm["old_chat_member"]["status"] == "left" \
        and mcm["new_chat_member"]["status"] == "member" \
        and mcm["new_chat_member"]["user"]["id"] == bot.id, mcm
    bots_here = a.get(f"/chat/v1/chats/{gid}/bot-info")["bots"]
    assert {x["id"] for x in bots_here} == {bot.id, other.id}, bots_here
    bot.drain()
    # 同一群每人每秒 1 条(§5.7):B 连着发要隔开
    base_seq = b.send(gid, "隐私模式下的普通消息")["seq"]
    time.sleep(1.1)
    b.send(gid, "/menu")
    time.sleep(1.1)
    b.send(gid, f"/menu@{uname}")
    time.sleep(1.1)
    b.send(gid, f"/menu@{other_uname}")
    time.sleep(1.1)
    b.send(gid, f"@{uname} 帮我点一份")
    gsent = bot.ok("sendMessage", {"chat_id": tg_gid, "text": "我在群里"})
    assert gsent["chat"]["id"] == tg_gid
    time.sleep(1.1)
    b.send(gid, "回复机器人", reply_to_seq=gsent["message_id"])
    got = set()
    deadline = time.time() + 8
    want = {"/menu", f"/menu@{uname}", f"@{uname} 帮我点一份", "回复机器人"}
    while time.time() < deadline and not want <= got:
        bot.poll(timeout=1)
        got |= {(x.get("message") or {}).get("text") for x in bot.seen}
    assert want <= got, got
    bot.quiet(lambda x: (x.get("message") or {}).get("text") in
              ("隐私模式下的普通消息", f"/menu@{other_uname}"), secs=1)
    rep = next(x["message"] for x in bot.seen if (x.get("message") or {}).get("text") == "回复机器人")
    assert rep["reply_to_message"]["message_id"] == gsent["message_id"] \
        and rep["chat"]["id"] == tg_gid, rep
    other.poll()
    other_got = {(x.get("message") or {}).get("text") for x in other.seen}
    assert f"/menu@{other_uname}" in other_got and "/menu" in other_got \
        and f"/menu@{uname}" not in other_got and "隐私模式下的普通消息" not in other_got, other_got
    assert base_seq > 0
    print("  ✓ 群(隐私模式):拉进群有 my_chat_member;普通消息、/cmd@别的机器人 不投;"
          "/cmd、/cmd@我、@我、回复我的消息 都投;群 chat.id = -(10¹²+会话 id)")
    dev_call(dev_token, "PUT", f"/dev/v1/bots/{bot.id}", {"privacy_mode": False})
    assert bot.ok("getMe")["can_read_all_group_messages"] is True
    time.sleep(1.1)
    b.send(gid, "关了隐私模式之后的普通消息")
    bot.wait(msg_text("关了隐私模式之后的普通消息"))
    dev_call(dev_token, "PUT", f"/dev/v1/bots/{bot.id}", {"privacy_mode": True})
    a.patch(f"/chat/v1/chats/{gid}/members/{other.id}", {"action": "kick"})
    u = other.wait(lambda x: (x.get("my_chat_member") or {}).get("new_chat_member", {})
                   .get("status") == "left")
    assert u["my_chat_member"]["old_chat_member"]["status"] == "member"
    other.err("sendMessage", {"chat_id": tg_gid, "text": "我被踢了还想说话"}, 403)
    print("  ✓ 关掉隐私模式后普通消息也投;移出群有 my_chat_member(left),之后往群里发 403")

    # ---- 图片、文件 ----
    time.sleep(1.2)
    pic = bot.ok("sendPhoto", {"chat_id": a.id, "caption": "今日菜单"},
                 files={"photo": ("menu.png", png_bytes(320, 240), "image/png")})
    fid = pic["photo"][-1]["file_id"]
    assert pic["caption"] == "今日菜单" and pic["photo"][-1]["width"] == 320, pic
    m = next(x for x in a.get(f"/chat/v1/chats/{cid}/messages?limit=10")["messages"]
             if x["seq"] == pic["message_id"])
    assert m["kind"] == "photo" and m["text"] == "今日菜单" and m["media"][0]["url"], m
    again = bot.ok("sendPhoto", {"chat_id": a.id, "photo": fid})
    assert again["photo"][-1]["file_unique_id"] == pic["photo"][-1]["file_unique_id"]
    time.sleep(1.2)
    doc = bot.ok("sendDocument", {"chat_id": a.id},
                 files={"document": ("菜单.txt", "宫保鸡丁 28 元\n".encode(), "text/plain")})
    assert doc["document"]["file_name"] == "菜单.txt" and doc["document"]["file_id"], doc
    r = other.err("sendPhoto", {"chat_id": a.id, "photo": fid}, 403)  # 它没和 A 说过话
    other_chat = b.post("/chat/v1/chats/private", {"user_id": other.id})
    b.send(other_chat["id"], "/start")
    other.wait(msg_text("/start"))
    r = other.err("sendPhoto", {"chat_id": b.id, "photo": fid}, 400)
    assert "wrong file identifier" in r["description"], r
    r = bot.err("sendPhoto", {"chat_id": a.id, "photo": "https://example.com/a.jpg"}, 400)
    assert "URL" in r["description"], r
    bot.err("sendPhoto", {"chat_id": a.id},
            files={"photo": ("fake.png", b"MZ\x90\x00not an image", "image/png")}, code=400)
    print("  ✓ sendPhoto / sendDocument:multipart 上传、复用自己的 file_id;别的机器人的 file_id、"
          "让服务端拉 URL、伪装成图片的文件都 400")

    # ---- 限流:同一会话每秒 1 条、突发 3 ----
    time.sleep(3.2)
    codes, retry = [], None
    for i in range(5):
        r = bot.call("sendMessage", {"chat_id": a.id, "text": f"连发 {i}"})
        codes.append(r["_status"])
        if r["_status"] == 429:
            retry = r
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:], codes
    assert retry["parameters"]["retry_after"] >= 1 and \
        retry["description"].startswith("Too Many Requests: retry after"), retry
    print(f"  ✓ 限流:同一会话连发 {codes},429 带 parameters.retry_after={retry['parameters']['retry_after']}")

    # ---- 拉黑 ----
    a.post("/social/v1/blocks", {"user_id": bot.id})
    u = bot.wait(lambda x: (x.get("my_chat_member") or {}).get("new_chat_member", {})
                 .get("status") == "kicked")
    assert u["my_chat_member"]["chat"]["id"] == a.id
    time.sleep(1.2)
    r = bot.err("sendMessage", {"chat_id": a.id, "text": "你还在吗"}, 403)
    assert r["description"] == "Forbidden: bot was blocked by the user", r
    a.delete(f"/social/v1/blocks/{bot.id}")
    bot.wait(lambda x: (x.get("my_chat_member") or {}).get("new_chat_member", {})
             .get("status") == "member")
    bot.ok("sendMessage", {"chat_id": a.id, "text": "欢迎回来"})
    print("  ✓ 用户拉黑机器人:它收到 my_chat_member(kicked),再发 403「bot was blocked by the user」;解除后恢复")

    # ---- webhook:先 500 再 200,拨 next_try_at 触发重试;按顺序;带 secret;24 小时丢弃 ----
    srv = hook_server()
    hook_url = f"http://127.0.0.1:{srv.server_address[1]}/hook"
    secret = "s3cr3t_" + uuid.uuid4().hex
    bot.err("setWebhook", {"url": "http://example.com/hook"}, 400)
    bot.err("setWebhook", {"url": hook_url, "secret_token": "带空格 不行"}, 400)
    bot.drain()
    assert bot.ok("setWebhook", {"url": hook_url, "secret_token": secret,
                                 "drop_pending_updates": True}) is True
    r = bot.err("getUpdates", {}, 409)
    assert r["description"].startswith("Conflict:"), r
    srv.statuses = [500]
    a.send(cid, "webhook 第一条")
    hits = wait_hits(srv, 1)
    assert hits[0]["status"] == 500 and hits[0]["update"]["message"]["text"] == "webhook 第一条"
    first_uid = hits[0]["update"]["update_id"]
    deadline = time.time() + 5
    while True:
        info = bot.ok("getWebhookInfo")
        if info.get("last_error_message") or time.time() > deadline:
            break
        time.sleep(0.2)
    assert info["url"] == hook_url and info["pending_update_count"] == 1 and \
        "500" in info["last_error_message"] and info["last_error_date"], info
    a.send(cid, "webhook 第二条")
    time.sleep(2.5)
    assert len(srv.hits) == 1, f"队头在退避,后面的不该先投:{srv.hits}"
    assert bot.ok("getWebhookInfo")["pending_update_count"] == 2
    dev_info = dev_call(dev_token, "GET", f"/dev/v1/bots/{bot.id}")["webhook"]
    assert dev_info["url"] == hook_url and dev_info["pending_update_count"] == 2 \
        and dev_info["has_secret"] and "500" in dev_info["last_error_message"], dev_info
    sql("UPDATE bot_updates SET next_try_at = now() WHERE bot_id=:b AND update_id=:u",
        {"b": bot.id, "u": first_uid})
    hits = wait_hits(srv, 3)
    assert [h["status"] for h in hits] == [500, 200, 200], hits
    assert [h["update"]["update_id"] for h in hits] == [first_uid, first_uid, first_uid + 1], hits
    assert [h["update"]["message"]["text"] for h in hits[1:]] == ["webhook 第一条", "webhook 第二条"]
    assert all(h["secret"] == secret for h in hits), [h["secret"] for h in hits]
    assert bot.ok("getWebhookInfo")["pending_update_count"] == 0
    # 满 24 小时没投成的丢掉
    srv.statuses = [500]
    a.send(cid, "这条会过期")
    hits = wait_hits(srv, 4)
    stale_uid = hits[3]["update"]["update_id"]
    sql("UPDATE bot_updates SET created_at = now() - interval '25 hours', next_try_at = now() "
        "WHERE bot_id=:b AND update_id=:u", {"b": bot.id, "u": stale_uid})
    deadline = time.time() + 15
    while sql("SELECT count(*) FROM bot_updates WHERE bot_id=:b AND update_id=:u",
              {"b": bot.id, "u": stale_uid}, fetch="scalar") and time.time() < deadline:
        time.sleep(0.3)
    assert not sql("SELECT count(*) FROM bot_updates WHERE bot_id=:b AND update_id=:u",
                   {"b": bot.id, "u": stale_uid}, fetch="scalar"), "满 24 小时的更新应该丢掉"
    a.send(cid, "过期之后的新消息")
    hits = wait_hits(srv, 5)
    assert hits[4]["status"] == 200 and hits[4]["update"]["message"]["text"] == "过期之后的新消息"
    assert sum(1 for h in hits if h["update"]["update_id"] == stale_uid) == 1, "过期的那条不该再投"
    assert bot.ok("deleteWebhook", {"drop_pending_updates": True}) is True
    assert bot.ok("getWebhookInfo")["url"] == ""
    bot.ok("getUpdates")
    srv.shutdown()
    print("  ✓ webhook:先 500(记下 last_error、后面的排队不插队)→ 拨 next_try_at 重试投成 → 按 update_id 顺序、"
          "都带 secret 头;满 24 小时的丢掉;设了 webhook 时 getUpdates 409")

    # ---- 重置 token ----
    r = dev_call(dev_token, "POST", f"/dev/v1/bots/{bot.id}/token", {})
    new_token = r["token"]
    assert new_token != token and r["bot"]["token_prefix"] == new_token[:6]
    assert bot_raw(token, "getMe")["error_code"] == 401
    old_token, bot.token = token, new_token
    assert bot.ok("getMe")["id"] == bot.id
    print("  ✓ 重置 token:旧的当场 401,新的能用")

    # ---- 开关:bots_enabled=off 时全部 503 ----
    set_flag("off")
    try:
        r = bot_raw(new_token, "getMe")
        assert r == {"ok": False, "error_code": 503, "description": "机器人功能暂未开放",
                     "_status": 503}, r
        assert bot_raw(new_token, "sendMessage", {"chat_id": a.id, "text": "x"})["error_code"] == 503
        assert bot_raw("garbage", "getMe")["error_code"] == 503
        e = dev_call(dev_token, "POST", "/dev/v1/bots",
                     {"name": "关闸时", "username": f"e2e{random.randint(100000, 999999)}bot"},
                     expect_error=True)
        assert e["_error"] == 503 and e["detail"] == "机器人功能暂未开放", e
        e = a.post(f"/chat/v1/chats/{cid}/messages/{seq}/callback", {"data": "ok"}, expect_error=True)
        assert e["_error"] == 503, e
        e = a.get(f"/chat/v1/chats/{cid}/bot-info", expect_error=True)
        assert e["_error"] == 503, e
        assert call("GET", "/config")["features"]["bots"] is False, "客户端要能据此收起入口"
    finally:
        set_flag("on")
    assert bot.ok("getMe")["id"] == bot.id
    assert call("GET", "/config")["features"]["bots"] is True
    print("  ✓ bots_enabled=off:Bot API(token 对不对都是)、建机器人、回调、bot-info 全部 503,"
          "/config 的 features.bots=false;开回来恢复")

    # ---- 每个开发者最多 20 个 ----
    many_dev, _ = developer(verified=False, accept_rules=False)
    for i in range(20):
        dev_call(many_dev, "POST", "/dev/v1/bots",
                 {"name": f"批量{i}", "username": f"e2e{random.randint(10 ** 7, 10 ** 8 - 1)}bot"})
    e = dev_call(many_dev, "POST", "/dev/v1/bots",
                 {"name": "第 21 个", "username": f"e2e{random.randint(10 ** 7, 10 ** 8 - 1)}bot"},
                 expect_error=True)
    assert e["_error"] == 409 and "20" in e["detail"], e
    print("  ✓ 每个开发者最多 20 个机器人,第 21 个 409")

    # ---- 日志里没有完整 token ----
    check_logs([old_token, new_token, other.token], nonce)

    # ---- 删机器人:它说过的话对方看不到了、token 失效、用户名释放 ----
    before = [x["seq"] for x in a.get(f"/chat/v1/chats/{cid}/messages?limit=50")["messages"]
              if (x.get("sender") or {}).get("id") == bot.id]
    assert before, "删之前应该能看到机器人发的消息"
    r = dev_call(dev_token, "DELETE", f"/dev/v1/bots/{bot.id}")
    assert r["deleted"] is True and r["messages"] >= len(before), r
    after = [x for x in a.get(f"/chat/v1/chats/{cid}/messages?limit=50")["messages"]
             if x["seq"] in before]
    assert not after, f"删掉的机器人发的消息还看得到:{after}"
    assert bot_raw(new_token, "getMe")["error_code"] == 401
    e = a.get(f"/social/v1/resolve/{uname}", expect_error=True)
    assert e["_error"] == 404, e
    assert a.get(f"/chat/v1/chats/{gid}/bot-info")["bots"] == []
    assert dev_call(dev_token, "GET", f"/dev/v1/bots/{bot.id}", expect_error=True)["_error"] == 404
    print("  ✓ 删机器人:它发的消息对方看不到了(和注销账号一样清空)、token 401、用户名释放、群里没有它了")

    print("e2e_bots 全部通过 ✅")


def check_logs(tokens: list[str], nonce: str) -> None:
    """服务端日志里只许有 token 的前 6 位。先认出这次跑的请求确实进了日志(否则等于没查)。"""
    path = os.environ.get("SUPERZ_API_LOG") or ("/tmp/api.log" if os.path.exists("/tmp/api.log")
                                               else "")
    if not path or not os.path.exists(path):
        print("  ⚠ 找不到服务端日志(设 SUPERZ_API_LOG 指向它),跳过日志检查")
        return
    time.sleep(0.5)
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 50 * 1024 * 1024))
        text = f.read().decode("utf-8", "replace")
    if f"noSuchMethod{nonce}" not in text:
        print(f"  ⚠ {path} 里没有这次跑的请求(不是这台服务的日志?),跳过日志检查")
        return
    for t in tokens:
        # 密钥部分只有 [A-Za-z0-9_-],URL 转义前后一个样:原样和转义过的日志都查得到
        assert t.split(":")[1] not in text, f"日志里出现了 token 的密钥部分({t[:6]}…)"
    masked = f"/bot/{tokens[0][:6]}***/noSuchMethod{nonce}"
    # uvicorn 的访问日志把路径 URL 转义过(: → %3A、* → %2A),异常留痕里是原样:两种都认
    assert masked in text or urllib.parse.quote(masked) in text, "日志里认不出打过码的路径"
    print(f"  ✓ 服务端日志({path})里有这次的请求,只出现 token 前 6 位(/bot/{tokens[0][:6]}***/…)")


if __name__ == "__main__":
    main()
