"""小程序 e2e 的公共件:开发者账号、打包、上传、走完发布流程(DEV-PROMPTS-39 #338)。

跑法同其它 e2e:先起服务,再 `SUPERZ_API=http://127.0.0.1:8013 python -m tests.e2e_miniapp_xxx`。
直连库的助手读 DATABASE_URL,和服务端要指向同一个库。
"""
import base64
import hashlib
import hmac
import io
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from tests.util import ADMIN, BASE, call, fresh_phone, login

_ADMIN_TOKEN = None


def admin_token() -> str:
    global _ADMIN_TOKEN
    if _ADMIN_TOKEN is None:
        _ADMIN_TOKEN = login(ADMIN)
    return _ADMIN_TOKEN


def sms_login(phone: str, role: str = "customer", expect_error: bool = False):
    """验证码登录。同一个号 60 秒内要登第二次(换角色、测闸门)时,先清掉重发冷却 ——
    冷却是防刷短信的,不是这里要测的东西。"""
    try:
        import redis as _redis

        from app.config import settings as _settings
        r = _redis.Redis.from_url(_settings.redis_url)
        r.delete(f"sms:cd:{phone}")
        r.close()
    except Exception:
        pass
    code = call("POST", "/auth/sms-code", body={"phone": phone})["dev_code"]
    return call("POST", "/auth/sms-login", body={"phone": phone, "code": code, "role": role},
                expect_error=expect_error)


def customer(prefix: str = "138") -> tuple[str, str]:
    phone = fresh_phone(prefix)
    return sms_login(phone)["token"], phone


def invite(phone: str) -> None:
    r = call("POST", "/admin/mini-apps/invites", admin_token(), {"phone": phone},
             expect_error=True)
    assert "_error" not in r or r["_error"] == 409, r


def developer(*, verified: bool = True, accept_rules: bool = True) -> tuple[str, str]:
    """邀请 → 短信登录注册 developer →(可选)个人实名 → 接受开发者规则。"""
    phone = fresh_phone("139")
    invite(phone)
    token = sms_login(phone, "developer")["token"]
    if verified:
        call("POST", "/dev/v1/me/verify/individual", token,
             {"real_name": "测试开发者", "id_no": id_number()})
    if accept_rules:
        rev = call("GET", "/dev/v1/me", token)["agreement"]["required"]
        call("POST", "/dev/v1/me/agreement", token, {"revision": rev})
    return token, phone


def id_number(birth: str = "19900101") -> str:
    """造一个校验位正确的身份证号(GB 11643)。开发环境没配二要素核验,本地校验过了就算过。"""
    body = "610102" + birth + f"{random.randint(0, 999):03d}"
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check = "10X98765432"[sum(int(a) * b for a, b in zip(body, weights)) % 11]
    return body + check


def make_zip(files: dict[str, bytes | str], *, superz: dict | None = None,
             kind: str = "app", raw_entries: list | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if superz is not False:
            manifest = {"sdk": "2", "kind": kind, "orientation": "portrait",
                        "background_color": "#F0EEE6", "spa_fallback": False}
            manifest.update(superz or {})
            z.writestr("superz.json", json.dumps(manifest))
        for name, data in files.items():
            z.writestr(name, data)
        for info, data in raw_entries or []:
            z.writestr(info, data)
    return buf.getvalue()


HELLO = {
    "index.html": "<!doctype html><html><head><meta charset='utf-8'>"
                  "<script src='/_sdk/2/sz-webapp.js'></script>"
                  "<script src='app.js'></script></head><body><h1>hello</h1></body></html>",
    "app.js": "window.SuperZ && window.SuperZ.WebApp && window.SuperZ.WebApp.ready();",
    "style.css": "body{margin:0}",
}


def multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = "----sz" + uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n"
                  f"{v}\r\n".encode())
    for k, (fname, data, ctype) in files.items():
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                  f"filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
        out.write(data)
        out.write(b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def upload(token: str, appid: str, data: bytes, *, version: str = "1.0.0",
           changelog: str = "首个版本", expect_error: bool = False):
    body, ctype = multipart({"version": version, "changelog": changelog},
                            {"file": ("pkg.zip", data, "application/zip")})
    req = urllib.request.Request(f"{BASE}/dev/v1/apps/{appid}/versions", data=body,
                                 method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw).get("detail")
        except ValueError:
            detail = raw[:200]
        if expect_error:
            return {"_error": e.code, "detail": detail}
        raise SystemExit(f"FAIL 上传 {appid}: {e.code} {detail}")


def raw_get(url: str, headers: dict | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url if url.startswith("http") else BASE + url)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


CHECKLIST_ALL = {k: True for k in ("opens", "matches", "complete", "content", "no_offsite_trade",
                                   "privacy", "game_rules", "no_phishing", "no_malware",
                                   "domains")}

LISTING = {"tagline": "测试用的小程序", "description": "这是 e2e 测试建的应用,用来走发布流程。",
           "privacy_policy": "本应用不收集任何个人信息,数据只存在超级赞云存储里。"}


def new_app(token: str, *, name: str | None = None, kind: str = "app") -> dict:
    name = name or f"测试{uuid.uuid4().hex[:6]}"
    r = call("POST", "/dev/v1/apps", token, {"name": name, "kind": kind, "category": "tools"})
    call("PUT", f"/dev/v1/apps/{r['app']['appid']}", token, LISTING)
    return r


def publish(token: str, appid: str, data: bytes | None = None, *, version: str = "1.0.0",
            kind: str = "app") -> dict:
    """上传 → 提交 → 管理员按清单通过 → 开发者发布。返回版本。"""
    v = upload(token, appid, data or make_zip(HELLO, kind=kind), version=version)["version"]
    call("POST", f"/dev/v1/apps/{appid}/versions/{v['id']}/submit", token,
         {"review_note": "直接打开首页即可"})
    call("POST", f"/admin/mini-apps/reviews/{v['id']}/decide", admin_token(),
         {"approve": True, "checklist": CHECKLIST_ALL})
    call("POST", f"/dev/v1/apps/{appid}/versions/{v['id']}/release", token)
    return v


def parse_init(init_data: str) -> dict:
    return dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))


def verify_hash(init_data: str, secret: str, max_age: int = 600) -> bool:
    """文档里的 Python 验签示例(docs/miniapp/server.md)逐字搬过来:不 import 服务端代码。"""
    fields = parse_init(init_data)
    got = fields.pop("hash", "")
    fields.pop("signature", None)
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    key = hmac.new(b"SuperZWebAppData", secret.encode(), hashlib.sha256).digest()
    want = hmac.new(key, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, got):
        return False
    return time.time() - int(fields.get("auth_date", "0")) <= max_age


def verify_signature(init_data: str, public_key_b64: str, app_id: str, max_age: int = 600) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    fields = parse_init(init_data)
    sig = fields.pop("signature", "")
    fields.pop("hash", None)
    if fields.get("app_id") != app_id:
        return False
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    pad = "=" * (-len(public_key_b64) % 4)
    pub = Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(public_key_b64 + pad))
    try:
        pub.verify(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)),
                   f"{app_id}:SuperZWebAppData\n{dcs}".encode())
    except (InvalidSignature, ValueError):
        return False
    return time.time() - int(fields.get("auth_date", "0")) <= max_age


def sql(query: str, params: dict | None = None, *, fetch: str = "none"):
    """直连库跑一句 SQL(每次新建引擎、不用连接池 —— 多次 asyncio.run 共用池子会串事件循环)。

    fetch: none / scalar / all
    """
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.config import settings

    async def run():
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                res = await conn.execute(text(query), params or {})
                if fetch == "scalar":
                    return res.scalar()
                if fetch == "all":
                    return res.all()
                return None
        finally:
            await engine.dispose()

    return asyncio.run(run())
