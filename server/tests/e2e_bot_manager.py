"""机器人管家 @guanjia_bot e2e(services/bot_manager.py;对标 Telegram 的 @BotFather)。

全走真接口,管家的回复由服务端的投递循环在进程里处理(webhook 地址 internal:guanjia),所以这里发完消息要等它回:
- 管家本身:@guanjia_bot 找得到;bot-info 标 official、带命令列表和「命令」菜单;普通人起带 guanjia 的名字被拒;
- 没有开发者账号的人发 /newbot → 叫他去开发者后台;
- 开发者(同一个手机号登录的顾客账号)/newbot → 起名 → 起用户名(先故意起一个不以 bot 结尾的,状态不丢)→ 建好;
  **回复里、消息表里都没有 token 原文**;点「查看 token」→ 回调应答里是 token、getMe 能用;按钮当场收掉,老按钮再点 400;
- /setcommands 发「命令 - 说明」:格式不对的提示、状态还在;对了之后开发者后台看到的命令一样;
- /token 确认重置 → 旧 token 401、新的能用;
- /mybots 只列自己的机器人;
- /deletebot 用户名没对上不删;对上了删掉、token 401。

跑法:SUPERZ_API=… DATABASE_URL=… python -m tests.e2e_bot_manager(在 server/ 下跑:先用子进程把官方开发者和管家 seed 出来)
"""
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from tests.chat_util import Person, person, sql
from tests.miniapp_util import developer, sms_login
from tests.util import call

SERVER = Path(__file__).resolve().parents[1]
#: token 长这样:`<机器人 id>:<35 位>`(services/bots.new_token)。
#: **两头都不加 \b。** 结尾那个曾经加过,于是 token 正好以 `-` 收尾时
#: (1/64,约 1.7%)两处都静默失灵:
#: `fullmatch` 那条随机红一次,而「token 不许发成消息」那条是 `search` ——
#: 它找不到就当没泄露,**一个真的泄露会被判成通过**。
#: `-` 不是单词字符,串尾又没有字符,那个位置构不成单词边界。
TOKEN_RE = re.compile(r"\d+:[A-Za-z0-9_-]{35}")


def seed() -> None:
    """官方开发者(官方小程序的种子里建)+ 管家。子进程跑:和运维一样的命令,也不在这个进程里开数据库连接池。"""
    for mod in ("scripts.seed_official_miniapps", "scripts.seed_bot_manager"):
        r = subprocess.run([sys.executable, "-m", mod, "--apply"], cwd=SERVER, capture_output=True, text=True)
        assert r.returncode == 0, f"{mod} 失败:{r.stdout}\n{r.stderr}"


def wait_reply(p: Person, cid: int, after: int, mgr: int, *, contains: str = "", timeout: float = 15) -> dict:
    """等管家在 [after] 之后的回复(投递循环是异步的)。给了 contains 就等到带这句话的那条。"""
    deadline = time.time() + timeout
    seen: list[str] = []
    while time.time() < deadline:
        msgs = p.get(f"/chat/v1/chats/{cid}/messages?limit=30")["messages"]
        mine = sorted((m for m in msgs if m["seq"] > after and (m.get("sender") or {}).get("id") == mgr),
                      key=lambda m: m["seq"])
        seen = [m.get("text", "") for m in mine]
        hit = [m for m in mine if contains in (m.get("text") or "")]
        if hit:
            return hit[-1]
        time.sleep(0.2)
    raise AssertionError(f"{timeout} 秒内没等到管家回复「{contains}」,收到的是:{seen}")


def say(p: Person, cid: int, text: str, mgr: int, expect: str) -> dict:
    sent = p.send(cid, text)
    return wait_reply(p, cid, sent["seq"], mgr, contains=expect)


def buttons(msg: dict) -> list[dict]:
    return [b for row in ((msg.get("markup") or {}).get("inline_keyboard") or []) for b in row]


def press(p: Person, cid: int, msg: dict, *, text: str = "", data: str = "") -> dict:
    """点管家消息上的按钮(按按钮上的字或 callback_data 找)。"""
    b = next(b for b in buttons(msg) if (text and text in b["text"]) or (data and b.get("callback_data") == data))
    return p.post(f"/chat/v1/chats/{cid}/messages/{msg['seq']}/callback", {"data": b["callback_data"]})


def bot_get_me(token: str) -> tuple[int, dict]:
    import json
    import urllib.error
    import urllib.request

    from tests.util import BASE
    try:
        with urllib.request.urlopen(f"{BASE}/bot/{token}/getMe", timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> None:
    seed()
    mgr = sql("SELECT owner_id FROM usernames WHERE username_lc = 'guanjia_bot'", fetch="scalar")
    assert mgr, "管家没 seed 出来"

    # ---- 管家本身 ----
    stranger = person()
    found = stranger.get("/social/v1/resolve/guanjia_bot")
    assert found["type"] == "user" and found["user"]["is_bot"] is True and found["user"]["id"] == mgr, found
    cid0 = stranger.post("/chat/v1/chats/private", {"user_id": mgr})["id"]
    info = stranger.get(f"/chat/v1/chats/{cid0}/bot-info")["bots"][0]
    assert info["official"] is True and info["username"] == "guanjia_bot", info
    assert {"newbot", "setcommands", "token", "deletebot"} <= {c["command"] for c in info["commands"]}
    assert info["menu_button"] == {"type": "commands"}, info["menu_button"]
    e = stranger.put("/social/v1/me/username", {"username": f"guanjia{random.randint(100, 999)}"},
                     expect_error=True)
    assert "保留" in str(e), f"带 guanjia 的名字应该是保留的:{e}"
    print("  ✓ 管家:@guanjia_bot 找得到、标官方、带命令和菜单;普通人起带 guanjia 的名字被拒")

    r = say(stranger, cid0, "/newbot", mgr, "开发者")
    assert any("url" in b and b["url"].endswith("/dev") for b in buttons(r)), buttons(r)
    print("  ✓ 没有开发者账号:/newbot 叫他去开发者后台")

    # ---- 开发者用同一个手机号的顾客账号来建 ----
    dev_token, phone = developer()
    me = Person(sms_login(phone, "customer")["token"], phone)
    cid = me.post("/chat/v1/chats/private", {"user_id": mgr})["id"]
    say(me, cid, "/newbot", mgr, "起个名字")
    say(me, cid, "管家测试助手", mgr, "用户名")
    say(me, cid, f"notbot{random.randint(1000, 9999)}", mgr, "必须以 bot 结尾")
    uname = f"mgr{random.randint(10000, 99999)}_bot"
    done = say(me, cid, uname, mgr, "建好了")
    assert not TOKEN_RE.search(done["text"]), "token 不许发成消息"
    ans = press(me, cid, done, text="查看 token")
    assert ans.get("answered") is True and ans.get("show_alert") is True, ans
    token = ans["text"]
    assert TOKEN_RE.fullmatch(token), f"弹窗里应该只有 token:{token!r}"
    status, body = bot_get_me(token)
    assert status == 200 and body["result"]["username"] == uname, body
    leaked = sql("SELECT count(*) FROM chat_messages WHERE text LIKE :t", {"t": f"%{token}%"}, fetch="scalar")
    assert leaked == 0, "token 原文进了消息表"
    after = next(m for m in me.get(f"/chat/v1/chats/{cid}/messages?limit=30")["messages"] if m["seq"] == done["seq"])
    assert not any(str(b.get("callback_data", "")).startswith("tok:") for b in buttons(after)), "看过之后按钮要收掉"
    old = next(b for b in buttons(done) if "查看 token" in b["text"])["callback_data"]
    e = me.post(f"/chat/v1/chats/{cid}/messages/{done['seq']}/callback", {"data": old}, expect_error=True)
    assert "对不上" in str(e), e
    bot_id = int(token.split(":")[0])
    assert any(b["id"] == bot_id for b in call("GET", "/dev/v1/bots", dev_token)["items"]), "开发者后台里要看得到"
    print("  ✓ /newbot:起名、用户名不对照样接着问、建好;token 只在回调弹窗里出现一次,消息表里没有,getMe 能用")

    # ---- 改命令 ----
    pick = say(me, cid, "/setcommands", mgr, "改命令")
    press(me, cid, pick, text=uname)
    ask = wait_reply(me, cid, pick["seq"], mgr, contains="新命令列表")
    say(me, cid, "start 开始", mgr, "没看懂")
    say(me, cid, "Start - 开始\n/menu — 看今天的菜", mgr, "2 条")
    cmds = call("GET", f"/dev/v1/bots/{bot_id}", dev_token)["commands"]
    assert cmds == [{"command": "start", "description": "开始"}, {"command": "menu", "description": "看今天的菜"}], cmds
    assert ask["seq"] > pick["seq"]
    print("  ✓ /setcommands:格式不对提示、状态不丢;大写转小写、/ 和 — 都认;开发者后台看到的一样")

    # ---- 重置 token ----
    pick = say(me, cid, "/token", mgr, "重置哪个")
    press(me, cid, pick, text=uname)
    confirm = wait_reply(me, cid, pick["seq"], mgr, contains="旧的会立刻失效")
    press(me, cid, confirm, text="确定重置")
    again = wait_reply(me, cid, confirm["seq"], mgr, contains="重置了")
    new_token = press(me, cid, again, text="查看 token")["text"]
    assert TOKEN_RE.fullmatch(new_token) and new_token != token
    assert bot_get_me(token)[0] == 401 and bot_get_me(new_token)[0] == 200
    print("  ✓ /token:确认后重置,旧 token 当场 401,新的从弹窗拿、能用")

    # ---- 只列自己的 ----
    other_dev, other_phone = developer()
    other = Person(sms_login(other_phone, "customer")["token"], other_phone)
    ocid = other.post("/chat/v1/chats/private", {"user_id": mgr})["id"]
    r = say(other, ocid, "/mybots", mgr, "还没有机器人")
    assert uname not in r["text"]
    print("  ✓ /mybots 只列自己名下的")

    # ---- 删除 ----
    pick = say(me, cid, "/deletebot", mgr, "删除哪个")
    press(me, cid, pick, text=uname)
    wait_reply(me, cid, pick["seq"], mgr, contains="原样发它的用户名")
    say(me, cid, "@wrong_name_bot", mgr, "没对上")
    assert bot_get_me(new_token)[0] == 200, "没对上不能删"
    pick = say(me, cid, "/deletebot", mgr, "删除哪个")
    press(me, cid, pick, text=uname)
    wait_reply(me, cid, pick["seq"], mgr, contains="原样发它的用户名")
    say(me, cid, f"@{uname}", mgr, "删掉了")
    assert bot_get_me(new_token)[0] == 401
    assert not any(b["id"] == bot_id for b in call("GET", "/dev/v1/bots", dev_token)["items"])
    print("  ✓ /deletebot:用户名没对上不删,对上了删掉、token 失效")
    print("✓ e2e_bot_manager 全部通过")


if __name__ == "__main__":
    main()
