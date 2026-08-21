"""对称加密工具:收款账号等敏感字段加密落库,接口只回尾号。

密钥优先取 settings.crypto_key(.env 里配一串 ≥32 字符随机串);
未配置时从 jwt_secret 派生——开发期开箱即用。
注意:密钥一经使用不可更换,换了旧密文就解不开(要换必须先写迁移重加密);
生产环境请配置独立 crypto_key,避免与 jwt_secret 轮换互相牵连。
"""
import base64
import hashlib
import hmac

from cryptography.fernet import Fernet

from ..config import settings


def _fernet() -> Fernet:
    secret = settings.crypto_key or f"superz-derive:{settings.jwt_secret}"
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    """解不开(密钥变了/数据损坏)返回空串,调用方给"请联系申请人核对"级别的降级。"""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except Exception:
        return ""


def pseudonym(*parts: str) -> str:
    """不可逆假名:HMAC-SHA256 取前 32 位 hex。

    用来在**不留明文**的前提下,让注销后的账号还能被同一个人的
    再注册命中(见 RiskCarryover)。

    ⚠️ 必须是 **带密钥的** HMAC,不能用裸 sha256:中国手机号只有
    1.9e9 个可能值,裸哈希用一台笔记本几分钟就能建全表反查 ——
    那等于明文存手机号,而注销页答应过"账号将被匿名化删除"。

    密钥与 Fernet 同源(crypto_key,未配则从 jwt_secret 派生):
    换密钥的后果只是老的假名不再命中(风控标记不再跟随),
    不会像密文那样"解不开就丢数据"。
    """
    secret = settings.crypto_key or f"superz-derive:{settings.jwt_secret}"
    mac = hmac.new(secret.encode(), "\x1f".join(parts).encode(),
                   hashlib.sha256)
    return mac.hexdigest()[:32]
