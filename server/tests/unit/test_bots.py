"""机器人平台的纯函数和守卫(DEV-PROMPTS-40 #355,docs/BOT-API.md)。

守的是几条不能悄悄变的东西:
- token 不进日志:路径在最外层就打码,异常留痕、uvicorn 访问日志拿到的都只有前 6 位;
- 隐私模式的投递真值表;
- 内联键盘的校验(每个按钮恰好一个动作、callback_data 按字节数、只许 http/https、回复键盘不做);
- webhook 地址:生产只许 https 公网;重试节奏 1 / 2 / 4 / 8 分钟;
- 文档第 3 节的方法表、第 6 节的限流数字和实现一致;开关缺省生产关。
"""
import asyncio
import logging
import re
from pathlib import Path

import pytest

from app.services import bots
from app.services.bots import BotError

DOC = Path(__file__).resolve().parents[3] / "docs" / "BOT-API.md"
TOKEN = "123456:" + "Ab3_-" * 7          # 35 位密钥


# ---------------------------------------------------------------- token

def test_token_shape_hash_prefix():
    t = bots.new_token(42)
    assert bots.TOKEN_RE.fullmatch(t) and t.startswith("42:") and len(t.split(":")[1]) == 35
    assert bots.token_hash(t) != bots.token_hash(bots.new_token(42))     # 每次都是新的随机
    assert re.fullmatch(r"[0-9a-f]{64}", bots.token_hash(t))
    assert bots.token_prefix(t) == t[:6] and bots.mask_token(t) == t[:6] + "***"


def test_mask_tokens_anywhere_in_text():
    text = f"calling /bot/{TOKEN}/getMe failed; token={TOKEN}."
    masked = bots.mask_tokens(text)
    assert TOKEN.split(":")[1] not in masked
    assert masked.count("123456***") == 2, masked
    assert bots.mask_tokens("没有 token 的一句话 12:34") == "没有 token 的一句话 12:34"


def test_mask_path():
    assert bots.mask_path(f"/bot/{TOKEN}/sendMessage") == ("/bot/123456***/sendMessage", TOKEN)
    assert bots.mask_path(f"/bot/{TOKEN}") == ("/bot/123456***", TOKEN)
    assert bots.mask_path("/bot/") == ("/bot/", None)
    assert bots.mask_path("/chat/v1/dialogs") == ("/chat/v1/dialogs", None)


def test_token_never_reaches_logs_even_when_the_route_blows_up(caplog):
    """故意让一次调用在路由里炸掉:异常留痕中间件记下的路径、uvicorn 访问日志读的路径都只剩前 6 位。

    守卫先弄红过:把 services/bots.mask_path 改成原样返回路径(不打码),这条在
    「日志里出现了 token 的密钥部分」上红;e2e_bots 最后的日志检查同样红在这句上。
    """
    from uvicorn.protocols.utils import get_path_with_query_string

    from app.main import BotTokenPathMiddleware, LogUnhandledErrorsMiddleware

    seen = {}

    async def boom(scope, receive, send):
        seen["path"] = scope["path"]
        seen["token"] = scope.get(bots.SCOPE_KEY)
        raise RuntimeError("路由里出错了")

    app = BotTokenPathMiddleware(LogUnhandledErrorsMiddleware(boom))
    scope = {"type": "http", "method": "POST", "path": f"/bot/{TOKEN}/sendMessage",
             "raw_path": f"/bot/{TOKEN}/sendMessage".encode(), "query_string": b"",
             "headers": []}

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(msg):
        pass

    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError):
            asyncio.run(app(scope, receive, send))
    secret = TOKEN.split(":")[1]
    assert "路由里出错了" in caplog.text, "异常留痕没记下来,下面的断言等于没查"
    assert secret not in caplog.text, "日志里出现了 token 的密钥部分"
    assert "/bot/123456***/sendMessage" in caplog.text
    # uvicorn 在响应开始时读的是同一个 scope:它记的访问日志也只有打过码的路径
    assert secret not in get_path_with_query_string(scope)
    assert secret.encode() not in scope["raw_path"]
    # 路由拿得到真 token(在 scope 的私有键里),拿到的路径是打过码的
    assert seen == {"path": "/bot/123456***/sendMessage", "token": TOKEN}, seen


def test_bot_token_middleware_is_outermost():
    from app.main import app
    assert app.user_middleware[0].cls.__name__ == "BotTokenPathMiddleware"


# ---------------------------------------------------------------- 谁能收到什么

def _deliver(**kw) -> bool:
    base = dict(chat_type="group", privacy_mode=True, bot_id=7, bot_username="menubot",
                text="随便说说", mentioned_names=set(), mentioned_ids=set(), reply_to_sender=None)
    base.update(kw)
    return bots.should_deliver(**base)


@pytest.mark.parametrize("kw,want", [
    ({"chat_type": "private"}, True),                             # 私聊全给
    ({"chat_type": "channel", "text": "/start"}, False),          # 频道什么都不给
    ({"chat_type": "saved"}, False),
    ({}, False),                                                  # 隐私模式:普通消息不给
    ({"privacy_mode": False}, True),                              # 关了隐私模式全给
    ({"text": "/menu"}, True),                                    # /命令(没 @ 谁)
    ({"text": "/menu 今天"}, True),
    ({"text": "/menu@MenuBot"}, True),                            # /命令@我(大小写不敏感)
    ({"text": "/menu@otherbot"}, False),                          # /命令@别的机器人
    ({"text": "说 /menu"}, False),                                # 不是开头
    ({"text": "https://a.cn/menu"}, False),
    ({"mentioned_names": {"menubot"}}, True),                     # @我
    ({"mentioned_ids": {7}}, True),                               # text_mention 我
    ({"reply_to_sender": 7}, True),                               # 回复我的消息
    ({"reply_to_sender": 8}, False),
    ({"text": "/menu@otherbot", "reply_to_sender": 7}, True),
])
def test_should_deliver_truth_table(kw, want):
    assert _deliver(**kw) is want, kw


def test_leading_command_and_command_entities():
    assert bots.leading_command("/start") == ("start", None)
    assert bots.leading_command("/Start@DianCan_Bot hi") == ("start", "diancan_bot")
    assert bots.leading_command("hi /start") is None
    assert bots.leading_command("/a/b") is None
    # 偏移按 UTF-16:👍 占 2 个码元
    assert bots.command_entities("👍 /menu", []) == [{"type": "bot_command", "offset": 3, "length": 5}]
    assert bots.command_entities("`/menu`", [(0, 7)]) == []          # 代码块里的不算


# ---------------------------------------------------------------- 标识

def test_chat_ids_look_like_telegram():
    assert bots.tg_group_id(31) == -1000000000031
    assert bots.parse_chat_ref(22) == ("user", 22)
    assert bots.parse_chat_ref("22") == ("user", 22)
    assert bots.parse_chat_ref(-1000000000031) == ("chat", 31)
    assert bots.parse_chat_ref("-1000000000031") == ("chat", 31)
    assert bots.parse_chat_ref("@Tejia_CN") == ("username", "tejia_cn")
    for bad in (0, -31, True, None, "abc", "@a", 2 ** 40, 1.5):
        with pytest.raises(BotError) as e:
            bots.parse_chat_ref(bad)
        assert e.value.code == 400 and e.value.description == "Bad Request: chat not found"


def test_file_id_is_signed_per_bot():
    fid = bots.file_id_for(88, bot_id=5)
    assert bots.parse_file_id(fid, 5) == 88
    assert bots.parse_file_id(fid, 6) is None, "别的机器人拿去用不了"
    assert bots.parse_file_id(fid[:-1] + ("0" if fid[-1] != "0" else "1"), 5) is None
    assert bots.parse_file_id("88", 5) is None
    assert bots.file_unique_id(88) == bots.file_unique_id(88) != bots.file_unique_id(89)


# ---------------------------------------------------------------- 实体

def test_entities_from_telegram():
    got = bots.entities_from_tg([
        {"type": "strikethrough", "offset": 0, "length": 2},
        {"type": "text_mention", "offset": 3, "length": 2, "user": {"id": 9, "first_name": "x"}},
        {"type": "bot_command", "offset": 0, "length": 5},      # 服务端自己认,丢掉
        {"type": "blockquote", "offset": 0, "length": 5},       # 我们没有,丢掉不报错
        {"type": "pre", "offset": 0, "length": 1, "language": "python"},
    ])
    assert got == [{"type": "strike", "offset": 0, "length": 2},
                   {"type": "text_mention", "offset": 3, "length": 2, "user_id": 9},
                   {"type": "pre", "offset": 0, "length": 1, "language": "python"}]
    with pytest.raises(BotError):
        bots.entities_from_tg("not a list")


# ---------------------------------------------------------------- 内联键盘

def test_markup_normalized():
    raw = {"inline_keyboard": [[{"text": "好", "callback_data": "ok"},
                                {"text": "网", "url": "https://chaojizan.cc/", "callback_data": ""}],
                               [{"text": "小程序", "web_app": {"app_id": "sz0123456789abcdef"}}]]}
    markup, texts, apps = bots.parse_markup(raw)
    assert markup == {"inline_keyboard": [[{"text": "好", "callback_data": "ok"},
                                           {"text": "网", "url": "https://chaojizan.cc/"}],
                                          [{"text": "小程序",
                                            "web_app": {"app_id": "sz0123456789abcdef"}}]]}
    assert texts == ["好", "网", "小程序"] and apps == {"sz0123456789abcdef"}
    import json
    assert bots.parse_markup(json.dumps(raw))[0] == markup           # 表单里是 JSON 字符串
    assert bots.parse_markup({"inline_keyboard": []}) == (None, [], set())
    assert bots.parse_markup(None) == (None, [], set())


@pytest.mark.parametrize("raw,word", [
    ({"keyboard": [[{"text": "x"}]]}, "回复键盘"),
    ({"remove_keyboard": True}, "回复键盘"),
    ({"force_reply": True}, "回复键盘"),
    ("{not json", "can't parse"),
    ({"inline_keyboard": [[{"text": "x", "callback_data": "好" * 22}]]}, "BUTTON_DATA_INVALID"),
    ({"inline_keyboard": [[{"text": "x", "callback_data": "a", "url": "https://a.cn"}]]}, "只有一个动作"),
    ({"inline_keyboard": [[{"text": "x"}]]}, "只有一个动作"),
    ({"inline_keyboard": [[{"text": "x", "url": "javascript:alert(1)"}]]}, "BUTTON_URL_INVALID"),
    ({"inline_keyboard": [[{"text": "x", "url": "ftp://a.cn/x"}]]}, "BUTTON_URL_INVALID"),
    ({"inline_keyboard": [[{"text": "x", "web_app": {"url": "https://a.cn"}}]]}, "app_id"),
    ({"inline_keyboard": [[{"text": "x", "login_url": {"url": "https://a.cn"}}]]}, "不支持的按钮"),
    ({"inline_keyboard": [[{"text": "", "callback_data": "a"}]]}, "按钮文字"),
    ({"inline_keyboard": [[]]}, "至少一个按钮"),
    ({"inline_keyboard": [[{"text": "x", "callback_data": str(i)} for i in range(9)]]}, "8 个"),
    ({"inline_keyboard": [[{"text": "x", "callback_data": str(i)}] for i in range(101)]}, "100 个"),
])
def test_markup_rejected(raw, word):
    with pytest.raises(BotError) as e:
        bots.parse_markup(raw)
    assert e.value.code == 400 and word in e.value.description, e.value.description


def test_callback_data_limit_is_bytes_not_characters():
    ok = {"inline_keyboard": [[{"text": "x", "callback_data": "好" * 21}]]}    # 63 字节
    assert bots.parse_markup(ok)[0] is not None
    assert bots.parse_markup({"inline_keyboard": [[{"text": "x", "callback_data": "a" * 64}]]})[0]
    assert bots.markup_has_callback(bots.parse_markup(ok)[0], "好" * 21)
    assert not bots.markup_has_callback(bots.parse_markup(ok)[0], "好")


# ---------------------------------------------------------------- webhook

def test_webhook_url_shape_in_prod(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "app_env", "prod")
    bots.check_webhook_url_shape("https://bot.example.com/hook")
    bots.check_webhook_url_shape("https://bot.example.com:8443/hook")
    for bad, word in (("http://bot.example.com/hook", "HTTPS"),
                      ("http://127.0.0.1:9000/hook", "HTTPS"),      # 生产不给本机开口子
                      ("https://bot.example.com:9000/hook", "ports"),
                      ("https://u:p@bot.example.com/hook", "用户名和密码"),
                      ("", "1–300")):
        with pytest.raises(BotError) as e:
            bots.check_webhook_url_shape(bad)
        assert word in e.value.description, (bad, e.value.description)


def test_webhook_localhost_only_in_dev(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "app_env", "dev")
    bots.check_webhook_url_shape("http://127.0.0.1:9000/hook")
    bots.check_webhook_url_shape("http://localhost:9000/hook")
    with pytest.raises(BotError):
        bots.check_webhook_url_shape("http://10.0.0.5/hook")


@pytest.mark.parametrize("ip,ok", [
    ("8.8.8.8", True), ("2001:4860:4860::8888", True),
    ("127.0.0.1", False), ("10.1.2.3", False), ("172.20.0.5", False), ("fd00::1", False),
    ("169.254.169.254", False),   # 云厂商元数据:不在 is_private 里,最该拦
    ("100.64.0.1", False),        # 运营商 NAT
    ("0.0.0.0", False), ("::1", False), ("::ffff:127.0.0.1", False), ("224.0.0.1", False),
])
def test_webhook_ip_must_be_public(ip, ok):
    assert bots._ip_ok(ip) is ok


def test_webhook_retry_doubles_from_one_minute():
    from datetime import timedelta

    from app.services.bot_webhook import retry_delay
    assert [retry_delay(n) for n in (1, 2, 3, 4)] == [timedelta(minutes=m) for m in (1, 2, 4, 8)]
    assert bots.UPDATE_TTL == timedelta(hours=24)


# ---------------------------------------------------------------- 开关、文档

def test_bots_flag_default_off_in_prod_on_in_dev(monkeypatch):
    from app.config import settings
    from app.routers.admin import _KNOWN_FLAGS
    from app.services import flags

    monkeypatch.setattr(settings, "app_env", "prod")
    assert flags.bot_flag_default() == "off", "合规结论出来之前,生产上不能不经意地打开"
    monkeypatch.setattr(settings, "app_env", "staging")
    assert flags.bot_flag_default() == "off"
    monkeypatch.setattr(settings, "app_env", "dev")
    assert flags.bot_flag_default() == "on"
    assert set(flags.BOT_FLAGS) <= _KNOWN_FLAGS


def test_doc_method_table_matches_implementation():
    """文档第 3 节的方法表和实现的方法表逐个对上(多一个少一个都红)。"""
    from app.routers.bot_api import METHODS

    section = DOC.read_text().split("## 3. 方法", 1)[1].split("\n## ", 1)[0]
    documented = {m.lower() for m in re.findall(r"^\| `(\w+)` \|", section, re.MULTILINE)}
    assert len(documented) >= 15, documented
    assert documented == set(METHODS), (documented ^ set(METHODS))


def test_doc_rate_limits_match_constants():
    text = DOC.read_text()
    assert f"全局每秒 {bots.SEND_PER_SECOND} 条" in text
    assert f"每秒 {bots.CHAT_PER_SECOND} 条,允许突发 {bots.CHAT_BURST} 条" in text
    assert f"每分钟 {bots.GROUP_PER_MINUTE} 条" in text
    assert f"最多 {bots.MAX_BOTS_PER_DEVELOPER} 个" in text
    from app.routers.chat_bots import CALLBACKS_PER_SECOND
    assert f"每人每秒 {CALLBACKS_PER_SECOND} 次" in text
    assert f"最多等 {bots.CALLBACK_WAIT_SECONDS} 秒" in text.replace("**", "")
    dev_prompts = (DOC.parent / "DEV-PROMPTS-40.md").read_text()
    assert f"每个机器人全局每秒 {bots.SEND_PER_SECOND} 条" in dev_prompts, "§5.7 表格要有机器人限流"
