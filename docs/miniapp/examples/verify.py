# 超级赞小程序 initData v2 验签(Python 3.10+)。两种验法任选其一:
#   verify_hash —— 持有 AppSecret 的后端用它;
#   verify_signature —— 不想碰密钥,用平台公钥(需要 pip install cryptography)。
# 这份代码被 server/tests/unit/test_miniapp_docs_examples.py 拿测试向量跑过,和文档里的一字不差。
import base64
import hashlib
import hmac
import time
from urllib.parse import parse_qsl

MAX_AGE = 600  # 秒:超过 10 分钟的包一律拒绝


def _fields(init_data: str) -> dict:
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("字段重复")
    return fields


def _check_string(fields: dict) -> str:
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields) if k not in ("hash", "signature"))


def _fresh(fields: dict, app_id: str, now: float | None) -> bool:
    if fields.get("app_id") != app_id:
        return False
    age = (time.time() if now is None else now) - int(fields.get("auth_date", "0"))
    return 0 <= age <= MAX_AGE


def verify_hash(init_data: str, app_id: str, app_secret: str, now: float | None = None) -> bool:
    try:
        fields = _fields(init_data)
        given = fields["hash"]
    except (ValueError, KeyError):
        return False
    secret_key = hmac.new(b"SuperZWebAppData", app_secret.encode(), hashlib.sha256).digest()
    want = hmac.new(secret_key, _check_string(fields).encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, given) and _fresh(fields, app_id, now)


def verify_signature(init_data: str, app_id: str, public_key_b64url: str, now: float | None = None) -> bool:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    def b64d(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    try:
        fields = _fields(init_data)
        message = f"{fields['app_id']}:SuperZWebAppData\n{_check_string(fields)}".encode()
        Ed25519PublicKey.from_public_bytes(b64d(public_key_b64url)).verify(b64d(fields["signature"]), message)
    except Exception:
        return False
    return _fresh(fields, app_id, now)
