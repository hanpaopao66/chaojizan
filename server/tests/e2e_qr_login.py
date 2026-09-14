"""扫码登录 / 一键登录(用户端网页版、桌面版),真接口走一遍。

- 扫码 → 手机确认 → 网页轮询拿到 token(**只拿一次**)→ token 能用;
- 只有二维码(sid)没有 secret 的人看不到状态、拿不到 token;二维码链接被别的扫码工具打开,
  只看到一张「请用超级赞 App 扫」的说明页,没有任何会话信息;
- 手机上取消;过期;别人扫过的码再扫 409、别人来确认 403;商家账号、网页会话扫码 403;
- 一键登录:带 device_key 建会话 → 手机 App 查得到待确认(App 不在前台:记了推送)→ 确认 → 拿到 token;
  device_key 用一次换一把,旧的立刻作废;
- 在手机上移除这台设备 → 一键登录被拒,那台设备手里的 token 下一次请求就 401;
- AI 助手令牌调 scan / confirm / cancel / pending / 设备列表都是 403。

**自己造数据**:两个新注册的用户端账号、一个新注册的商家账号,不依赖别的套件留下的任何东西。

    SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_qr_login
"""
import asyncio
import base64
import json
import time
import urllib.parse

import redis as _redis
from sqlalchemy import text

from app.config import settings
from app.db import SessionLocal
from tests.util import call, register_user, request_raw

CHROME_MAC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def create(body=None, ua=CHROME_MAC, expect_error=False):
    return call("POST", "/auth/qr/sessions", body=body or {"client": "web"},
                headers={"User-Agent": ua}, expect_error=expect_error)


def poll(s, state="", wait=0, secret=None):
    """网页端的轮询。wait=0 立刻返回;带 secret(默认用建会话时给的那个)"""
    q = urllib.parse.urlencode({"state": state, "wait": wait})
    return call("GET", f"/auth/qr/sessions/{s['sid']}?{q}",
                headers={"X-QR-Secret": s["secret"] if secret is None else secret},
                expect_error=True)


def claims(token: str) -> dict:
    """只看 token 里写了什么(不验签:验签是服务端的事,这里不需要知道密钥)"""
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def status_of(r) -> str:
    assert isinstance(r, dict) and "_error" not in r, r
    return r["status"]


def age_session(sid: str) -> None:
    """把会话的有效期拨到已经过去(模拟 120 秒到了),Redis 里的键和剩余时长不动"""
    r = _redis.Redis.from_url(settings.redis_url, decode_responses=True)
    key = f"qr:s:{sid}"
    d = json.loads(r.get(key))
    d["expires_at"] = time.time() - 1
    r.set(key, json.dumps(d), px=max(1000, r.pttl(key)))
    r.close()


async def db_scalar(q, **p):
    async with SessionLocal() as db:
        return await db.scalar(text(q), p)


async def main() -> None:
    a_token, _ = register_user("customer", prefix="136", name="扫码甲")
    b_token, _ = register_user("customer", prefix="136", name="扫码乙")
    m_token, _ = register_user("merchant", prefix="136", name="扫码商家")
    a_id = call("GET", "/auth/me", a_token)["id"]

    # ---------- 1) 扫码登录:扫码 → 确认 → 轮询拿到 token,只拿一次 ----------
    s = create()
    assert s["mode"] == "qr" and s["status"] == "pending", s
    assert s["qr"].endswith(f"/l/{s['sid']}") and s["qr"].startswith("http"), s
    assert s["secret"] not in s["qr"], "secret 进了二维码 —— 那样拍到二维码的人就能领 token"
    assert 110 <= s["ttl"] <= 120, s
    assert status_of(poll(s)) == "pending"
    for bad in ("", "x" * 43):
        r = poll(s, secret=bad)
        assert r.get("_error") == 403, f"没有 secret 也看得到会话状态:{r}"
    print("✓ 建会话:二维码里只有 sid;不带 secret 连状态都看不到")

    # 二维码被别的扫码工具(微信)打开:一张说明页,和会话一点关系都没有
    code, ctype, page = request_raw("GET", f"/l/{s['sid']}")
    code2, _, page2 = request_raw("GET", "/l/" + "Z" * 32)
    assert code == code2 == 200 and "text/html" in ctype, (code, ctype)
    assert page == page2, "说明页随 sid 变了 —— 它不该查、也不该显示任何会话信息"
    assert "扫一扫" in page and s["sid"] not in page and "Chrome" not in page
    print("✓ /l/{sid} 被别的扫码工具打开:只有「请用超级赞 App 扫一扫」,任何 sid 都一样")

    info = call("POST", f"/auth/qr/sessions/{s['sid']}/scan", a_token)
    assert info["device"] == "Chrome · macOS", info
    assert "*" in info["ip"] and info["same_network"] is True, info
    assert info["created_at"] and info["expires_at"], info
    r = poll(s, state="pending")
    assert status_of(r) == "scanned" and r["user"]["name"].startswith("扫") and "*" in r["user"]["name"], r
    print(f"✓ 扫码:手机上看到「{info['device']}」、IP {info['ip']}、同一网络;网页上是打过码的昵称")

    r = call("POST", f"/auth/qr/sessions/{s['sid']}/scan", b_token, {}, expect_error=True)
    assert r.get("_error") == 409, f"别人扫过的码还能再扫:{r}"
    r = call("POST", f"/auth/qr/sessions/{s['sid']}/confirm", b_token, {}, expect_error=True)
    assert r.get("_error") == 403, f"不是扫码的人也能确认:{r}"
    r = call("POST", f"/auth/qr/sessions/{s['sid']}/scan", m_token, {}, expect_error=True)
    assert r.get("_error") == 403, f"商家账号也能扫用户端的登录码:{r}"
    print("✓ 别人再扫 409、别人确认 403、商家账号扫码 403")

    assert call("POST", f"/auth/qr/sessions/{s['sid']}/confirm", a_token, {}) == {"ok": True}
    got = poll(s, state="scanned")
    assert status_of(got) == "confirmed", got
    web_token, key1, device_id = got["token"], got["device_key"], got["device_id"]
    assert got["user_id"] == a_id and got["role"] == "customer", got
    assert claims(web_token).get("ld") == device_id, "网页的 token 没带那台设备,手机上移除不了它"
    again = poll(s, state="scanned")
    assert again == {"status": "expired"}, f"token 交付了两次:{again}"
    assert call("GET", "/auth/me", web_token)["id"] == a_id
    devices = call("GET", "/auth/login-devices", a_token)["items"]
    assert [d["id"] for d in devices] == [device_id], devices
    assert devices[0]["device"] == "Chrome · macOS" and "*" in devices[0]["ip"], devices
    assert devices[0]["current"] is False, "手机上看列表,不该把哪台电脑标成「当前设备」"
    mine = call("GET", "/auth/login-devices", web_token)["items"]
    assert [d["current"] for d in mine] == [True], mine
    print("✓ 确认 → 轮询拿到 token 和 device_key(只给一次),token 能用;「已登录的网页和电脑」里有它")

    # 网页上的会话不能再去批准别的设备(偷到一个网页会话的人不能给自己批新电脑)
    s_web = create()
    r = call("POST", f"/auth/qr/sessions/{s_web['sid']}/scan", web_token, {}, expect_error=True)
    assert r.get("_error") == 403, f"网页会话能扫码批准别的设备:{r}"
    print("✓ 网页上扫码登录进来的会话,扫码 / 确认一律 403(只认手机 App)")

    # ---------- 2) 手机上取消 ----------
    s2 = create()
    call("POST", f"/auth/qr/sessions/{s2['sid']}/scan", a_token, {})
    assert call("POST", f"/auth/qr/sessions/{s2['sid']}/cancel", a_token, {}) == {"ok": True}
    assert status_of(poll(s2, state="scanned")) == "cancelled"
    r = call("POST", f"/auth/qr/sessions/{s2['sid']}/confirm", a_token, {}, expect_error=True)
    assert r.get("_error") == 409, f"取消了还能确认:{r}"
    print("✓ 手机上点取消:网页看到「已取消」,之后确认不了")

    # ---------- 3) 过期 ----------
    s3 = create()
    age_session(s3["sid"])
    assert status_of(poll(s3)) == "expired"
    r = call("POST", f"/auth/qr/sessions/{s3['sid']}/scan", a_token, {}, expect_error=True)
    assert r.get("_error") == 404, f"过期的码还能扫:{r}"
    s4 = create()
    call("POST", f"/auth/qr/sessions/{s4['sid']}/scan", a_token, {})
    call("POST", f"/auth/qr/sessions/{s4['sid']}/confirm", a_token, {})
    age_session(s4["sid"])
    late = poll(s4, state="scanned")
    assert late == {"status": "expired"}, f"过了有效期还能领 token:{late}"
    print("✓ 过期:扫不了;确认了但过了有效期才来领的,也不给 token")

    # ---------- 4) 一键登录 ----------
    one = create({"client": "web", "device_key": key1})
    assert one["mode"] == "oneclick" and one["status"] == "scanned" and one["qr"] == "", one
    pending = call("GET", "/auth/qr/pending", a_token)["items"]
    assert [p["sid"] for p in pending] == [one["sid"]], pending
    assert pending[0]["device"] == "Chrome · macOS" and "*" in pending[0]["ip"], pending
    assert call("GET", "/auth/qr/pending", b_token)["items"] == [], "别人查得到我的待确认登录"
    # App 没开着(没有实时连接):发了推送(没配极光时推送日志里记一条「仅记录意图」)
    pushed = 0
    for _ in range(30):
        pushed = await db_scalar(
            "SELECT count(*) FROM push_logs WHERE user_id = :u AND title = '登录确认'", u=a_id)
        if pushed:
            break
        await asyncio.sleep(0.1)
    assert pushed, "App 不在前台,一键登录请求没有推送"
    events = await db_scalar(
        "SELECT count(*) FROM user_events WHERE user_id = :u AND type = 'qr_login'", u=a_id)
    assert events, "一键登录请求没有发用户事件(App 在前台时靠它当场弹确认页)"
    r = call("POST", f"/auth/qr/sessions/{one['sid']}/confirm", b_token, {}, expect_error=True)
    assert r.get("_error") == 403, f"别人能确认我的一键登录:{r}"
    print("✓ 一键登录:手机 App 查得到待确认(设备、打码 IP),App 不在前台时推送了;别人确认 403")

    assert call("POST", f"/auth/qr/sessions/{one['sid']}/confirm", a_token, {}) == {"ok": True}
    got2 = poll(one, state="scanned")
    assert status_of(got2) == "confirmed", got2
    key2 = got2["device_key"]
    assert key2 != key1 and got2["device_id"] == device_id, got2
    assert call("GET", "/auth/me", got2["token"])["id"] == a_id
    assert call("GET", "/auth/qr/pending", a_token)["items"] == []
    r = create({"client": "web", "device_key": key1}, expect_error=True)
    assert r.get("_error") == 403, f"用过一次的 device_key 还能发起一键登录:{r}"
    devices = call("GET", "/auth/login-devices", a_token)["items"]
    assert [d["id"] for d in devices] == [device_id], f"一键登录多出了一台设备:{devices}"
    print("✓ 手机上确认 → 拿到 token;device_key 用一次换一把,旧的立刻作废;设备列表里还是那一台")

    # 同一台设备连点两次:旧的那条作废,手机上只留一条
    first = create({"client": "web", "device_key": key2})
    second = create({"client": "web", "device_key": key2})
    assert status_of(poll(first, state="scanned")) == "cancelled"
    pending = call("GET", "/auth/qr/pending", a_token)["items"]
    assert [p["sid"] for p in pending] == [second["sid"]], pending
    call("POST", f"/auth/qr/sessions/{second['sid']}/cancel", a_token, {})
    print("✓ 同一台设备连点两次一键登录:前一条作废,手机上只有一条待确认")

    # ---------- 5) 移除设备 ----------
    r = call("DELETE", f"/auth/login-devices/{device_id}", b_token, expect_error=True)
    assert r.get("_error") == 404, f"别人能移除我的设备:{r}"
    assert call("DELETE", f"/auth/login-devices/{device_id}", a_token) == {"ok": True}
    r = create({"client": "web", "device_key": key2}, expect_error=True)
    assert r.get("_error") == 403, f"移除之后还能一键登录:{r}"
    for t in (web_token, got2["token"]):
        r = call("GET", "/auth/me", t, expect_error=True)
        assert r.get("_error") == 401, f"移除之后那台设备的 token 还能用:{r}"
    assert call("GET", "/auth/login-devices", a_token)["items"] == []
    assert call("GET", "/auth/me", a_token)["id"] == a_id, "移除网页设备把手机也登出了"
    print("✓ 移除设备:一键登录被拒,那台设备手里的 token 立刻 401;手机上的登录不受影响")

    # ---------- 6) AI 助手令牌碰不了 ----------
    agent = call("POST", "/auth/agent-tokens", a_token,
                 {"name": "扫码测试", "scopes": ["order", "video"]})["token"]
    s6 = create()
    for method, path in (
        ("POST", f"/auth/qr/sessions/{s6['sid']}/scan"),
        ("POST", f"/auth/qr/sessions/{s6['sid']}/confirm"),
        ("POST", f"/auth/qr/sessions/{s6['sid']}/cancel"),
        ("GET", "/auth/qr/pending"),
        ("GET", "/auth/login-devices"),
        ("DELETE", f"/auth/login-devices/{device_id}"),
    ):
        r = call(method, path, agent, {} if method == "POST" else None, expect_error=True)
        assert r.get("_error") == 403, f"助手令牌能调 {method} {path}:{r}"
    assert status_of(poll(s6)) == "pending", "助手令牌碰过之后会话变了"
    print("✓ AI 助手令牌调扫码 / 确认 / 取消 / 待确认 / 设备列表,全部 403")

    print("\ne2e_qr_login 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
