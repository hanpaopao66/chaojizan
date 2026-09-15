"""实时通道的登录校验和 HTTP 是同一套判据(security.socket_user)。

以前 ws.py 的订单 / 商家两条老通道自己 `jwt.decode`:手机上「移除」了那台电脑、账号注销了、
拿的是助手令牌 —— HTTP 当场 401 / 403,这两条通道照连不误,一直连到令牌 30 天后过期。
移除设备要做到「立刻退出」,每个认令牌的入口都得认同一套判据,漏一个就是一台踢不掉的电脑。
"""
import asyncio
import inspect
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import jwt

from app.config import settings
from app.models import LoginDevice, User, UserRole
from app.security import create_token, socket_user


class _DB:
    """只认 db.get 的假会话 —— socket_user 只该用这一个方法(主键查询,每次连接一两次)。"""

    def __init__(self, *rows):
        self._rows = {(type(r), r.id): r for r in rows}

    async def get(self, model, key):
        return self._rows.get((model, key))


def _user(uid=1, **kw):
    kw.setdefault("phone", f"138{uid:08d}")
    kw.setdefault("role", UserRole.customer)
    return User(id=uid, name="测试", **kw)


def _raw(**claims):
    claims.setdefault("sub", "1")
    claims.setdefault("role", "customer")
    claims.setdefault("exp", int(time.time()) + 600)
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def _check(db, token):
    return asyncio.run(socket_user(db, token))


class Test和HTTP同一套判据:
    def test_手机上登录的令牌照常放行(self):
        u = _user()
        assert _check(_DB(u), create_token(u)) is u

    def test_签名不对_过期_乱写的都不认(self):
        u = _user()
        wrong_key = jwt.encode({"sub": "1", "role": "customer", "exp": int(time.time()) + 600},
                               "not-the-secret-" * 3, algorithm="HS256")
        for token in ("", "not-a-jwt", wrong_key, _raw(exp=int(time.time()) - 1), _raw(sub="abc")):
            assert _check(_DB(u), token) is None, token

    def test_助手令牌不许连(self):
        # 它能碰什么是按 HTTP 接口逐条放的白名单,实时通道不在里面
        u = _user()
        assert _check(_DB(u), _raw(scope="agent", jti="t1")) is None

    def test_扫码登录的设备移除了就连不上(self):
        u = _user()
        token = create_token(u, login_device_id=5)
        alive = LoginDevice(id=5, user_id=1, key_hash="h", revoked_at=None)
        assert _check(_DB(u, alive), token) is u, "设备还在,应当连得上"
        removed = LoginDevice(id=5, user_id=1, key_hash="h", revoked_at=datetime.now(timezone.utc))
        assert _check(_DB(u, removed), token) is None, "手机上移除了,这台设备还连得上"
        assert _check(_DB(u), token) is None, "设备那一行没了,还连得上"
        someone_else = LoginDevice(id=5, user_id=2, key_hash="h", revoked_at=None)
        assert _check(_DB(u, someone_else), token) is None, "拿别人的设备号也连得上"

    def test_注销了的账号连不上(self):
        gone = _user(deleted_at=datetime.now(timezone.utc))
        assert _check(_DB(gone), create_token(gone)) is None
        # 存量墓碑行(还没跑数据修复)只有手机号前缀,和 get_current_user 一样也要认
        tomb = _user(phone="del_1_13800000001")
        assert _check(_DB(tomb), create_token(tomb)) is None

    def test_库里没有这个人(self):
        assert _check(_DB(), create_token(_user(uid=99))) is None


class Test没有别处自己解登录令牌:
    def test_三条实时通道都走socket_user(self):
        from app import ws
        from app.realtime import gateway
        for fn in (ws.order_ws, ws.merchant_ws, gateway.user_from_token):
            assert "socket_user(" in inspect.getsource(fn), f"{fn.__name__} 没走 socket_user"

    def test_登录令牌只在security里解(self):
        """用登录密钥 jwt.decode 的只许 security.py 一个文件:get_current_user 和 socket_user。
        再有别处自己解,就是又一条不认「设备移除」「账号注销」的路。"""
        app_dir = Path(__file__).resolve().parents[2] / "app"
        pattern = re.compile(r"jwt\.decode\([^)]*jwt_secret")
        offenders = [str(p.relative_to(app_dir)) for p in app_dir.rglob("*.py")
                     if p.name != "security.py" and pattern.search(p.read_text(encoding="utf-8"))]
        assert offenders == [], f"这些地方自己解了登录令牌:{offenders}"
