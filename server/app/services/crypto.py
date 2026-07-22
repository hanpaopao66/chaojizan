"""对称加密工具:收款账号等敏感字段加密落库,接口只回尾号。

密钥优先取 settings.crypto_key(.env 里配一串 ≥32 字符随机串);
未配置时从 jwt_secret 派生——开发期开箱即用。
注意:密钥一经使用不可更换,换了旧密文就解不开(要换必须先写迁移重加密);
生产环境请配置独立 crypto_key,避免与 jwt_secret 轮换互相牵连。
"""
import base64
import hashlib

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
