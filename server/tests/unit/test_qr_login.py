"""扫码登录 / 一键登录(services/qr_login.py、routers/qr_login.py):不起服务、不连库。

## 这一组守什么

- 确认页上那行设备描述**只从固定的词里拼**,UA 里写什么都放不上去(骗子不能让确认页替他说话);
- IP、昵称打码的样子;「同一个网络」不放宽(手机流量的大 NAT 里全是陌生人);
- 会话的几条硬规矩:只有 secret 的人能看状态、token 只交付一次、扫码的人才能确认、
  别人扫过的码再扫 409、商家账号和网页会话不能扫码;
- 带 `ld` 的 token(扫码登录签给网页 / 电脑的):那台设备被移除了就 401;续期时原样带上;
- 这些接口不在 AI 助手令牌的白名单里;
- 日志里不出现 token、device_key、secret。

跑起来的服务上走一遍在 tests/e2e_qr_login.py。
"""
import ast
import asyncio
import inspect
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app import security
from app.config import settings
from app.models import LoginDevice, User, UserRole
from app.routers import auth as auth_router
from app.routers import qr_login as router
from app.security import AGENT_SCOPES, agent_can, create_token
from app.services import qr_login as qr

CHROME_MAC = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
EDGE_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36 Edg/128.0.2739.42")
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
SAFARI_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 "
                 "(KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1")
WECHAT_ANDROID = ("Mozilla/5.0 (Linux; Android 14; V2309A) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/116.0 Mobile Safari/537.36 MicroMessenger/8.0.50")


class Test设备描述:
    @pytest.mark.parametrize("ua,want", [
        (CHROME_MAC, "Chrome · macOS"),
        (EDGE_WIN, "Edge · Windows"),            # Edge 的 UA 里也有 Chrome,要先认出 Edge
        (FIREFOX_LINUX, "Firefox · Linux"),
        (SAFARI_IPHONE, "Safari · iPhone"),      # iPhone 的 UA 里有 "like Mac OS X"
        (WECHAT_ANDROID, "微信内置浏览器 · Android"),  # 安卓的 UA 里有 Linux
        ("", "浏览器"),
        ("curl/8.4.0", "浏览器"),
    ])
    def test_网页版按_UA_认(self, ua, want):
        assert qr.describe_device(ua) == want

    def test_UA_里写什么都放不到确认页上(self):
        """确认页那行字只能是固定词拼出来的。原文照搬的话,骗子把 UA 写成
        「超级赞官方领券活动」,确认页就替他说了这句话。"""
        for ua in ("超级赞官方领券活动", "Mozilla/5.0 (官方客服) 平台安全中心", "<b>x</b>" * 50):
            d = qr.describe_device(ua)
            assert "官方" not in d and "客服" not in d and "<" not in d, d
            assert len(d) <= 30

    @pytest.mark.parametrize("platform,want", [
        ("macos", "超级赞电脑版 · macOS"), ("Windows", "超级赞电脑版 · Windows"),
        ("linux", "超级赞电脑版 · Linux"), ("", "超级赞电脑版"), ("官方", "超级赞电脑版"),
    ])
    def test_桌面版按自己报的系统(self, platform, want):
        assert qr.describe_device(CHROME_MAC, "desktop", platform) == want


class Test打码:
    @pytest.mark.parametrize("ip,want", [
        ("123.45.67.89", "123.45.*.*"),
        ("2408:8207:1234:5678::1", "2408:8207:*"),
        ("::ffff:10.1.2.3", "10.1.*.*"),
        ("unknown", "未知"),
        ("", "未知"),
    ])
    def test_ip(self, ip, want):
        assert qr.mask_ip(ip) == want

    def test_同一个网络不放宽(self):
        assert qr.same_network("123.45.67.89", "123.45.67.89")
        # IPv4 不放宽到 /24:手机流量走运营商的大 NAT,同一段里是成千上万个陌生人
        assert not qr.same_network("123.45.67.89", "123.45.67.90")
        assert qr.same_network("2408:8207:1:2::1", "2408:8207:1:2:abcd::9")
        assert not qr.same_network("2408:8207:1:2::1", "2408:8207:1:3::1")
        assert not qr.same_network("123.45.67.89", "2408:8207:1:2::1")
        assert not qr.same_network("unknown", "unknown")

    @pytest.mark.parametrize("name,want", [
        ("", ""), ("王", "*"), ("王五", "王*"), ("张三丰", "张*丰"), ("用户12345678", "用****8"),
    ])
    def test_昵称(self, name, want):
        assert qr.mask_name(name) == want


# ---------------------------------------------------------------------------
# 会话的几条规矩(Redis 换成假的,Lua 那一步在 Python 里照做)
# ---------------------------------------------------------------------------

class FakeRedis:
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set] = {}

    async def set(self, k, v, ex=None, px=None, nx=False):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def get(self, k):
        return self.kv.get(k)

    async def eval(self, script, numkeys, key, old, new, default_ttl):
        assert script == qr._SWAP_LUA
        if self.kv.get(key) != old:
            return 0
        if new == "":
            del self.kv[key]
        else:
            self.kv[key] = new
        return 1

    async def sadd(self, k, v):
        self.sets.setdefault(k, set()).add(v)

    async def smembers(self, k):
        return set(self.sets.get(k, set()))

    async def srem(self, k, v):
        self.sets.get(k, set()).discard(v)

    async def expire(self, k, s):
        return True


class FakeDB:
    """_hand_over 用到的那几样:按 id 取人、建设备记录、提交"""

    def __init__(self, users):
        self.users = {u.id: u for u in users}
        self.devices: list = []
        self.commits = 0

    async def get(self, model, pk):
        return self.users.get(pk) if model is User else None

    async def scalar(self, stmt):
        return None

    async def scalars(self, stmt):
        return []

    async def execute(self, stmt):
        return SimpleNamespace(rowcount=0)

    def add(self, row):
        row.id = 100 + len(self.devices)
        self.devices.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def person(uid, role=UserRole.customer, name="张三丰"):
    return SimpleNamespace(id=uid, role=role, name=name, avatar_url="", deleted_at=None,
                           phone=f"1380000{uid:04d}")


def req(ip="1.2.3.4", ua=CHROME_MAC, ld=None):
    state = SimpleNamespace()
    if ld is not None:
        state.login_device_id = ld
    return SimpleNamespace(headers={"user-agent": ua, "x-forwarded-for": ip},
                           client=SimpleNamespace(host=ip), state=state)


@pytest.fixture
def env(monkeypatch):
    fake = FakeRedis()
    a, b = person(1), person(2, name="李四")
    db = FakeDB([a, b])
    monkeypatch.setattr(qr, "get_redis", lambda: fake)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(router, "SessionLocal", lambda: db)
    return SimpleNamespace(redis=fake, a=a, b=b, db=db)


def run(coro):
    return asyncio.run(coro)


def new_session(ip="9.9.9.9"):
    return run(router.create_qr_session(router.QrSessionIn(client="web"), req(ip), db=None))


def poll(s, state="", secret=None):
    return run(router.poll_qr_session(s["sid"], req(), state=state, wait=0,
                                      x_qr_secret=s["secret"] if secret is None else secret))


def err(coro) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        run(coro)
    return e.value


class Test会话:
    def test_二维码里只有_sid_领_token_要_secret(self, env):
        s = new_session()
        assert s["qr"].endswith(f"/l/{s['sid']}") and s["secret"] not in s["qr"]
        assert qr.SID_RE.match(s["sid"]) and len(s["secret"]) >= 40
        assert poll(s)["status"] == "pending"
        # 只拿着二维码(sid)的人:状态都不给看
        assert err(router.poll_qr_session(s["sid"], req(), state="", wait=0,
                                          x_qr_secret="")).status_code == 403
        assert err(router.poll_qr_session(s["sid"], req(), state="", wait=0,
                                          x_qr_secret="x" * 43)).status_code == 403
        # Redis 里存的是 secret 的哈希,不是原文
        assert s["secret"] not in json.dumps(env.redis.kv)

    def test_扫码_确认_领走_只交付一次(self, env):
        s = new_session(ip="9.9.9.9")
        info = run(router.scan_qr_session(s["sid"], req(ip="9.9.9.9"), user=env.a))
        assert info["device"] == "Chrome · macOS" and info["ip"] == "9.9.*.*"
        assert info["same_network"] is True
        got = poll(s, state="pending")
        assert got == {"status": "scanned", "mode": "qr",
                       "user": {"name": "张*丰", "avatar_url": ""}}
        assert run(router.confirm_qr_session(s["sid"], req(), user=env.a)) == {"ok": True}
        first = poll(s, state="scanned")
        assert first["status"] == "confirmed" and first["user_id"] == 1
        assert first["device_key"] and first["device_id"] == env.db.devices[0].id
        claims = jwt.decode(first["token"], settings.jwt_secret, algorithms=["HS256"])
        assert claims["sub"] == "1" and claims["ld"] == first["device_id"]
        # 设备记录只存 device_key 的哈希
        assert env.db.devices[0].key_hash == qr.hash_key(first["device_key"])
        assert first["device_key"] not in env.db.devices[0].key_hash
        # 第二次来:会话已经没了,token 不会再给
        again = poll(s, state="scanned")
        assert again == {"status": "expired"} and "token" not in again

    def test_两个轮询同时来只有一个拿得到(self, env):
        s = new_session()
        run(router.scan_qr_session(s["sid"], req(), user=env.a))
        run(router.confirm_qr_session(s["sid"], req(), user=env.a))

        async def both():
            return await asyncio.gather(*[
                router.poll_qr_session(s["sid"], req(), state="scanned", wait=0,
                                       x_qr_secret=s["secret"]) for _ in range(2)])
        results = run(both())
        assert sorted(r["status"] for r in results) == ["confirmed", "expired"]
        assert sum("token" in r for r in results) == 1

    def test_别人扫过的码再扫_409_别人确认_403(self, env):
        s = new_session()
        run(router.scan_qr_session(s["sid"], req(), user=env.a))
        assert err(router.scan_qr_session(s["sid"], req(), user=env.b)).status_code == 409
        assert err(router.confirm_qr_session(s["sid"], req(), user=env.b)).status_code == 403
        assert err(router.cancel_qr_session(s["sid"], req(), user=env.b)).status_code == 403
        # 同一个人重复扫是幂等的
        assert run(router.scan_qr_session(s["sid"], req(), user=env.a))["sid"] == s["sid"]

    def test_没扫就确认不行(self, env):
        s = new_session()
        assert err(router.confirm_qr_session(s["sid"], req(), user=env.a)).status_code == 403

    def test_取消之后确认不了(self, env):
        s = new_session()
        run(router.scan_qr_session(s["sid"], req(), user=env.a))
        assert run(router.cancel_qr_session(s["sid"], req(), user=env.a)) == {"ok": True}
        assert poll(s, state="scanned") == {"status": "cancelled"}
        assert err(router.confirm_qr_session(s["sid"], req(), user=env.a)).status_code == 409
        assert err(router.scan_qr_session(s["sid"], req(), user=env.a)).status_code == 409

    def test_过期(self, env):
        s = new_session()
        key = f"qr:s:{s['sid']}"
        d = json.loads(env.redis.kv[key])
        d["expires_at"] = time.time() - 1
        env.redis.kv[key] = json.dumps(d)
        assert poll(s) == {"status": "expired"}
        assert err(router.scan_qr_session(s["sid"], req(), user=env.a)).status_code == 404
        # 确认了但过了有效期才来领的,也不给
        s2 = new_session()
        run(router.scan_qr_session(s2["sid"], req(), user=env.a))
        run(router.confirm_qr_session(s2["sid"], req(), user=env.a))
        key2 = f"qr:s:{s2['sid']}"
        d2 = json.loads(env.redis.kv[key2])
        d2["expires_at"] = time.time() - 1
        env.redis.kv[key2] = json.dumps(d2)
        assert poll(s2, state="scanned") == {"status": "expired"}

    def test_不像_sid_的直接当不存在(self, env):
        assert run(router.poll_qr_session("../../etc", req(), state="", wait=0,
                                          x_qr_secret="x")) == {"status": "expired"}

    def test_商家账号和网页会话都不能扫码(self, env):
        s = new_session()
        merchant = person(3, role=UserRole.merchant)
        assert err(router.scan_qr_session(s["sid"], req(), user=merchant)).status_code == 403
        # 网页 / 电脑上扫码登录进来的会话(token 带 ld):不能再批准别的设备
        e = err(router.scan_qr_session(s["sid"], req(ld=5), user=env.a))
        assert e.status_code == 403 and "手机" in e.detail
        assert err(router.pending_qr_logins(req(ld=5), user=env.a)).status_code == 403

    def test_长轮询等到变化就回来(self, env):
        s = new_session()

        async def go():
            waiter = asyncio.create_task(router.poll_qr_session(
                s["sid"], req(), state="pending", wait=5, x_qr_secret=s["secret"]))
            await asyncio.sleep(0.05)
            assert not waiter.done()
            t0 = time.monotonic()
            await router.scan_qr_session(s["sid"], req(), user=env.a)
            r = await waiter
            return r, time.monotonic() - t0
        r, took = run(go())
        assert r["status"] == "scanned" and took < 1.0, (r, took)


class Test一键登录:
    def test_会话绑在那台设备的主人身上(self, env, monkeypatch):
        row = SimpleNamespace(id=7, user_id=1, revoked_at=None,
                              last_used_at=datetime.now(timezone.utc))

        async def by_key(db, key):
            return row if key == "k-good" else None
        events = []

        async def event(db, uid, type_, data):
            events.append((uid, type_, data))
        pushed = []
        monkeypatch.setattr(qr, "live_device_by_key", by_key)
        monkeypatch.setattr(router, "append_user_event", event)
        monkeypatch.setattr(qr, "app_in_foreground", lambda uid: False)
        monkeypatch.setattr(router.push, "spawn", lambda coro, what="": (pushed.append(what), coro.close()))

        s = run(router.create_qr_session(router.QrSessionIn(device_key="k-good"), req(),
                                         db=env.db))
        assert s["mode"] == "oneclick" and s["status"] == "scanned" and s["qr"] == ""
        assert events and events[0][0] == 1 and events[0][1] == "qr_login"
        assert "token" not in json.dumps(events) and "k-good" not in json.dumps(events)
        assert pushed, "App 不在前台要推送"
        # 手机上查得到;别人查不到、确认不了
        mine = run(router.pending_qr_logins(req(), user=env.a))["items"]
        assert [x["sid"] for x in mine] == [s["sid"]] and mine[0]["device"] == "Chrome · macOS"
        assert run(router.pending_qr_logins(req(), user=env.b))["items"] == []
        assert err(router.confirm_qr_session(s["sid"], req(), user=env.b)).status_code == 403
        # 失效的 key:同一句话,不说是哪种失效
        e = err(router.create_qr_session(router.QrSessionIn(device_key="k-bad"), req(),
                                         db=env.db))
        assert e.status_code == 403 and "扫码" in e.detail

    def test_App_在前台就不推送(self, env, monkeypatch):
        row = SimpleNamespace(id=8, user_id=1, revoked_at=None,
                              last_used_at=datetime.now(timezone.utc))

        async def by_key(db, key):
            return row

        async def event(db, uid, type_, data):
            return None
        pushed = []
        monkeypatch.setattr(qr, "live_device_by_key", by_key)
        monkeypatch.setattr(router, "append_user_event", event)
        monkeypatch.setattr(qr, "app_in_foreground", lambda uid: True)
        monkeypatch.setattr(router.push, "spawn", lambda coro, what="": (pushed.append(what), coro.close()))
        run(router.create_qr_session(router.QrSessionIn(device_key="k"), req(), db=env.db))
        assert pushed == []

    def test_网页电脑的连接不算_App_在前台(self, monkeypatch):
        from app.realtime.hub import hub
        conns = [SimpleNamespace(foreground=True, closed=False, device="user-web"),
                 SimpleNamespace(foreground=True, closed=False, device="user-desktop"),
                 SimpleNamespace(foreground=False, closed=False, device="user-app")]
        monkeypatch.setitem(hub.conns, 424242, conns)
        assert not qr.app_in_foreground(424242)
        conns.append(SimpleNamespace(foreground=True, closed=False, device="user-app"))
        assert qr.app_in_foreground(424242)


# ---------------------------------------------------------------------------
# 带 ld 的 token:移除设备 = 立刻退出
# ---------------------------------------------------------------------------

class DB:
    def __init__(self, user, device=None):
        self.user, self.device, self.asked = user, device, []

    async def get(self, model, pk):
        self.asked.append(model.__name__)
        if model is User:
            return self.user
        if model is LoginDevice:
            return self.device if self.device is not None and self.device.id == pk else None
        return None

    async def execute(self, stmt):
        return None

    async def commit(self):
        pass


def _call_current_user(token, db, request=None):
    request = request or SimpleNamespace(method="GET", url=SimpleNamespace(path="/auth/me"),
                                         state=SimpleNamespace())
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    return request, asyncio.run(security.get_current_user(request=request, credentials=creds, db=db))


class Test网页会话的_token:
    def user(self):
        return SimpleNamespace(id=11, role=UserRole.customer, deleted_at=None, phone="13800000011")

    def test_设备还在就放行_并记下是哪台(self):
        u = self.user()
        dev = SimpleNamespace(id=5, user_id=11, revoked_at=None)
        request, got = _call_current_user(create_token(u, login_device_id=5), DB(u, dev))
        assert got is u and request.state.login_device_id == 5

    def test_设备移除了就_401(self):
        u = self.user()
        dev = SimpleNamespace(id=5, user_id=11, revoked_at=datetime.now(timezone.utc))
        with pytest.raises(HTTPException) as e:
            _call_current_user(create_token(u, login_device_id=5), DB(u, dev))
        assert e.value.status_code == 401

    def test_设备没了或者是别人的_401(self):
        u = self.user()
        with pytest.raises(HTTPException):
            _call_current_user(create_token(u, login_device_id=5), DB(u, None))
        other = SimpleNamespace(id=5, user_id=99, revoked_at=None)
        with pytest.raises(HTTPException):
            _call_current_user(create_token(u, login_device_id=5), DB(u, other))

    def test_手机上登录的_token_不查设备表(self):
        u = self.user()
        db = DB(u)
        request, got = _call_current_user(create_token(u), db)
        assert got is u and "LoginDevice" not in db.asked
        assert getattr(request.state, "login_device_id", None) is None

    def test_续期原样带上那台设备(self):
        """漏了的话续一次期,「手机上移除这台设备」就再也管不到它了"""
        u = SimpleNamespace(id=11, role=UserRole.customer, name="张三")
        request = SimpleNamespace(state=SimpleNamespace(login_device_id=5))
        out = asyncio.run(auth_router.refresh(request=request, user=u, db=DB(u)))
        assert jwt.decode(out.token, settings.jwt_secret, algorithms=["HS256"])["ld"] == 5
        plain = asyncio.run(auth_router.refresh(request=SimpleNamespace(state=SimpleNamespace()),
                                                user=u, db=DB(u)))
        assert "ld" not in jwt.decode(plain.token, settings.jwt_secret, algorithms=["HS256"])


class Test助手令牌碰不了:
    """默认拒绝:这些接口不在白名单里。**别往白名单里加** ——
    一个能替你确认登录的助手,等于能把你的账号交给任何一台电脑。"""

    @pytest.mark.parametrize("method,path", [
        ("POST", "/auth/qr/sessions/AbCdEfGhIjKlMnOpQrStUvWxYz012345/scan"),
        ("POST", "/auth/qr/sessions/AbCdEfGhIjKlMnOpQrStUvWxYz012345/confirm"),
        ("POST", "/auth/qr/sessions/AbCdEfGhIjKlMnOpQrStUvWxYz012345/cancel"),
        ("GET", "/auth/qr/pending"),
        ("GET", "/auth/login-devices"),
        ("DELETE", "/auth/login-devices/1"),
    ])
    def test_全部拒绝(self, method, path):
        assert not agent_can(method, path, tuple(AGENT_SCOPES))


class Test日志不记凭据:
    """token、device_key、secret 任何一个进了日志,日志就成了登录凭据的备份"""

    #: 在日志参数里出现在哪儿都不行的名字(变量、属性都算:payload.device_key 也抓)
    ANYWHERE = {"token", "device_key", "secret", "x_qr_secret", "key_hash"}
    #: 整个对象直接塞进日志也不行(会话里有 secret 的哈希、请求体里有 device_key);取它的一个字段可以
    WHOLE = {"sess", "raw", "payload", "new", "first", "request"}

    @pytest.mark.parametrize("module", [router, qr])
    def test_logger_的参数里没有它们(self, module):
        tree = ast.parse(inspect.getsource(module))
        calls = 0
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
                calls += 1
                args = node.args[1:] + [k.value for k in node.keywords]
                used = {n.id for a in args for n in ast.walk(a) if isinstance(n, ast.Name)}
                used |= {n.attr for a in args for n in ast.walk(a) if isinstance(n, ast.Attribute)}
                whole = {a.id for a in args if isinstance(a, ast.Name)}
                bad = (used & self.ANYWHERE) | (whole & self.WHOLE)
                assert not bad, f"{module.__name__} 第 {node.lineno} 行的日志带了 {bad}"
        if module is router:
            assert calls >= 3, "路由里的日志一条都没扫到,这条测试可能扫错了地方"


class Test说明页:
    def test_任何链接看到的都一样_不带会话信息(self):
        from fastapi.testclient import TestClient

        from app.main import app
        c = TestClient(app)
        a = c.get("/l/AbCdEfGhIjKlMnOpQrStUvWxYz012345")
        b = c.get("/l/zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz")
        assert a.status_code == b.status_code == 200 and a.text == b.text
        assert "扫一扫" in a.text and "AbCdEfGh" not in a.text
        assert a.headers["referrer-policy"] == "no-referrer"
        assert "no-store" in a.headers["cache-control"]


def test_设备太久没用就不能一键登录():
    fresh = SimpleNamespace(last_used_at=datetime.now(timezone.utc) - timedelta(days=1))
    old = SimpleNamespace(last_used_at=datetime.now(timezone.utc)
                          - timedelta(days=qr.DEVICE_IDLE_DAYS + 1))
    assert not qr.device_idle(fresh) and qr.device_idle(old)


def test_status_of():
    now = time.time()
    assert qr.status_of({"status": "pending", "expires_at": now + 5}, now) == "pending"
    assert qr.status_of({"status": "scanned", "expires_at": now - 1}, now) == "expired"
    assert qr.status_of({"status": "confirmed", "expires_at": now - 1}, now) == "expired"
    assert qr.status_of({"status": "cancelled", "expires_at": now - 1}, now) == "cancelled"
