"""小程序身份协议 v2(#321,DEV-PROMPTS-39 §5.1–§5.3)。

v1(services/mini_app.py)是全平台一把 HMAC 密钥 + 全局 user_id:给了 A 开发者验签能力,
就等于给了他伪造 B 小程序身份包的能力,第三方之间还能串联同一个人。
v2 照 Telegram Mini Apps 的算法,换两个东西:

- **一应用一密钥**:HMAC 的密钥由每个应用自己的 AppSecret 派生;
- **按应用隔离的 open_id**:同一个人在不同应用里是不同的 open_id(表映射、随机生成)。

另外加一份**平台 Ed25519 签名**,开发者后端可以不碰任何密钥、只用公开的平台公钥验签 ——
和公开账本同一种信任观:不用相信我们,自己验。

## 协议(一旦有第三方接入就改不动;实现、文档、测试向量三处逐字一致)

initData 是一段 querystring,字段(除 hash、signature 外全部参与签名):
app_id、auth_date、launch_id、user(紧凑 JSON)、start_param(可无)、env(可无)、sig_kid。

    data_check_string = 除 hash、signature 外的字段,按键名字典序排序,
                        每个写成 key=value(value 为 URL 解码后的原文),用 \\n 连接
    secret_key = HMAC_SHA256(key = "SuperZWebAppData", msg = AppSecret)
    hash       = hex(HMAC_SHA256(key = secret_key, msg = data_check_string))
    signature  = base64url(Ed25519_sign(平台私钥[sig_kid],
                     "<app_id>:SuperZWebAppData\\n" + data_check_string))   # 无填充

测试向量锁在 tests/unit/test_mini_app_v2.py,文档 docs/miniapp/server.md 抄同一组数。
"""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import parse_qsl, quote, urlencode

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from ..config import settings

logger = logging.getLogger("superz.miniapp")

HMAC_KEY = b"SuperZWebAppData"
SIGN_TAG = "SuperZWebAppData"
#: 文档建议开发者后端拒绝超过这个秒数的包(和 v1 同一个窗口)
MAX_AGE_SECONDS = 600
SIGNED_FIELDS = ("app_id", "auth_date", "env", "launch_id", "sig_kid", "start_param", "user")


# ---------------- 标识 ----------------

def new_appid() -> str:
    """sz + 16 位小写十六进制:公开标识,同时是托管子域名(DNS label 安全)。"""
    return "sz" + secrets.token_hex(8)


def new_app_secret() -> str:
    """32 字节随机数的 base64url(43 字符,无填充)。只在创建/轮换时明文显示一次。"""
    return _b64url(secrets.token_bytes(32))


def new_open_id() -> str:
    """o_ + 26 位 base32(128 位随机数)。不从 user_id 派生(I2)。"""
    return "o_" + base64.b32encode(secrets.token_bytes(16)).decode().rstrip("=").lower()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ---------------- 平台签名钥 ----------------

def _signing_seed() -> bytes:
    if settings.mini_app_signing_key:
        seed = _b64url_decode(settings.mini_app_signing_key.strip())
        if len(seed) != 32:
            raise RuntimeError("MINI_APP_SIGNING_KEY 必须是 32 字节种子的 base64url")
        return seed
    if not settings.is_dev:
        # 生产不配就不签:签名钥从 jwt_secret 派生的话,换 JWT_SECRET 会让全部第三方的
        # 公钥验签一起失败,而且这把钥没有离线备份
        raise RuntimeError("小程序签名密钥未配置(MINI_APP_SIGNING_KEY)")
    global _warned
    if not _warned:
        _warned = True
        logging.getLogger("superz.miniapp").warning(
            "MINI_APP_SIGNING_KEY 未配置,开发环境从 jwt_secret 派生签名钥 —— 生产必须单独配置并离线备份")
    return hashlib.sha256(f"superz-miniapp-ed25519:{settings.jwt_secret}".encode()).digest()


_warned = False


def signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_signing_seed())


def public_key_raw(key: Ed25519PrivateKey | None = None) -> bytes:
    k = key or signing_key()
    return k.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def key_id(pub_raw: bytes) -> str:
    """公钥 id:公钥原始字节 SHA-256 的前 8 位十六进制。确定性,方便对照。"""
    return hashlib.sha256(pub_raw).hexdigest()[:8]


def public_keys() -> list[dict]:
    """/.well-known/superz-webapp-keys.json 的内容。

    轮换时新旧 kid 并存:新钥配进 MINI_APP_SIGNING_KEY 开始签,旧钥的**公钥**放进
    MINI_APP_PREVIOUS_PUBLIC_KEYS(逗号分隔的 base64url)继续发布,等旧包全部过期(600 秒)
    再撤。验签方按包里的 sig_kid 挑公钥。
    """
    pub = public_key_raw()
    out = [{"kid": key_id(pub), "alg": "Ed25519", "public_key": _b64url(pub),
            "not_before": None, "not_after": None}]
    for item in settings.mini_app_previous_public_keys.split(","):
        item = item.strip()
        if not item:
            continue
        raw = _b64url_decode(item)
        if len(raw) == 32 and key_id(raw) != out[0]["kid"]:
            out.append({"kid": key_id(raw), "alg": "Ed25519", "public_key": _b64url(raw),
                        "not_before": None, "not_after": None, "retired": True})
    return out


# ---------------- 签发 ----------------

def user_json(user: dict) -> str:
    """user 字段的紧凑 JSON(键排序、无空格、不转义中文)。验签方拿到什么就验什么,
    这里定死只是为了测试向量可复现。"""
    return json.dumps(user, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def data_check_string(fields: dict[str, str]) -> str:
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields)
                     if k not in ("hash", "signature"))


def secret_key(app_secret: str) -> bytes:
    return hmac.new(HMAC_KEY, app_secret.encode(), hashlib.sha256).digest()


def compute_hash(fields: dict[str, str], app_secret: str) -> str:
    return hmac.new(secret_key(app_secret), data_check_string(fields).encode(),
                    hashlib.sha256).hexdigest()


def signature_message(fields: dict[str, str]) -> bytes:
    return f"{fields['app_id']}:{SIGN_TAG}\n{data_check_string(fields)}".encode()


def build_init_data(*, app_id: str, app_secret: str, user: dict,
                    start_param: str | None = None, env: str | None = None,
                    auth_date: int | None = None, launch_id: str | None = None,
                    key: Ed25519PrivateKey | None = None) -> str:
    """签发一份 initData(querystring 原串)。"""
    k = key or signing_key()
    fields: dict[str, str] = {
        "app_id": app_id,
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "launch_id": launch_id or _b64url(secrets.token_bytes(16)),
        "sig_kid": key_id(public_key_raw(k)),
        "user": user_json(user),
    }
    if start_param:
        fields["start_param"] = start_param
    if env:
        fields["env"] = env
    fields["hash"] = compute_hash(fields, app_secret)
    fields["signature"] = _b64url(k.sign(signature_message(fields)))
    ordered = [(k2, fields[k2]) for k2 in sorted(fields) if k2 not in ("hash", "signature")]
    ordered += [("hash", fields["hash"]), ("signature", fields["signature"])]
    return urlencode(ordered, quote_via=quote)


# ---------------- 验签(第三方照这两个函数用自己的语言重写即可) ----------------

def parse_init_data(init_data: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in parse_qsl(init_data, keep_blank_values=True, strict_parsing=False):
        if k in out:  # 同名字段出现两次:拒绝,不猜哪个算数
            raise ValueError("duplicate field")
        out[k] = v
    return out


def _fresh(fields: dict[str, str], max_age: int, now: int | None,
           expect_app_id: str | None) -> bool:
    try:
        auth_date = int(fields["auth_date"])
    except (KeyError, ValueError):
        return False
    if abs((now if now is not None else int(time.time())) - auth_date) > max_age:
        return False
    if expect_app_id is not None and fields.get("app_id") != expect_app_id:
        return False
    return True


def verify_hash(init_data: str, app_secret: str, *, max_age: int = MAX_AGE_SECONDS,
                now: int | None = None, expect_app_id: str | None = None) -> bool:
    """用 AppSecret 验 hash。缺字段、被改、过期、app_id 不符 —— 一律 False,不区分原因。"""
    try:
        fields = parse_init_data(init_data)
        given = fields["hash"]
    except (ValueError, KeyError):
        return False
    if not hmac.compare_digest(compute_hash(fields, app_secret), given):
        return False
    return _fresh(fields, max_age, now, expect_app_id)


def verify_signature(init_data: str, public_key_b64: str, *, max_age: int = MAX_AGE_SECONDS,
                     now: int | None = None, expect_app_id: str | None = None) -> bool:
    """用平台公钥验 signature —— 不持有任何密钥也能验。"""
    try:
        fields = parse_init_data(init_data)
        sig = _b64url_decode(fields["signature"])
        pub = Ed25519PublicKey.from_public_bytes(_b64url_decode(public_key_b64))
        pub.verify(sig, signature_message(fields))
    except Exception:
        return False
    return _fresh(fields, max_age, now, expect_app_id)
