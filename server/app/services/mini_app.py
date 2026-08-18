"""小程序 initData 签名:把「这是超级赞 App 里的这个用户」变成可验证的凭据。

抄的是 Telegram Mini Apps 的思路:登录 token **永远不进 WebView**。
页面拿到的是一份带 HMAC-SHA256 签名的身份包,小程序自己的后端
用同一密钥验签 + 校时间戳,即可确认用户身份,全程摸不到 JWT。

## 签名协议(一旦有第三方接入就改不动了,字段序在这里定死)

    payload = {"app_id": int, "auth_date": int(unix 秒), "name": str, "user_id": int}
    text    = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    sign    = HMAC_SHA256(key, text 的 UTF-8 字节).hexdigest()

- 规范化 JSON 与公开账本(services/ledger.py)同一套规则,全仓一个口径;
- auth_date 纳入签名防重放,验签方拒绝超过时效的包(默认 10 分钟)——
  和 webhooks.py 的 timestamp 思路一致;
- app_id 纳入签名,A 小程序的 initData 拿到 B 小程序后端去验必然失败;
- name 是展示名,不含手机号 —— initData 里没有任何联系方式。

## 密钥

settings.mini_app_secret,未配置时从 jwt_secret 带命名空间派生
(照 crypto.py 的惯例)。注意:换 JWT_SECRET 会连带换掉派生密钥,
已发出去的 initData 会集体失效 —— 时效只有分钟级,可接受。
"""
import hashlib
import hmac
import json
import time

from ..config import settings

# 验签方允许的最大时钟偏移 + 传输延迟。太短了正常打开都会失败,
# 太长了重放窗口就大;10 分钟是「页面打开后先干别的再登录」的余量
MAX_AGE_SECONDS = 600


def _key() -> bytes:
    secret = settings.mini_app_secret or f"superz-miniapp:{settings.jwt_secret}"
    return hashlib.sha256(secret.encode()).digest()


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_init_data(app_id: int, user_id: int, name: str, auth_date: int | None = None) -> dict:
    """签发 initData。返回 {"payload": {...}, "sign": hex} 整包给客户端透传。"""
    payload = {
        "app_id": app_id,
        "auth_date": auth_date if auth_date is not None else int(time.time()),
        "name": name,
        "user_id": user_id,
    }
    mac = hmac.new(_key(), _canonical(payload).encode(), hashlib.sha256)
    return {"payload": payload, "sign": mac.hexdigest()}


def verify_init_data(payload: dict, sign: str, *, app_id: int | None = None,
                     now: int | None = None) -> bool:
    """验签。第三方后端照本函数用自己语言重写即是对接文档。

    比较用 compare_digest 防时序侧信道;过期与 app_id 不符都算失败,
    不区分原因 —— 给攻击者的信息越少越好。
    """
    expect = hmac.new(_key(), _canonical(payload).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sign):
        return False
    auth_date = payload.get("auth_date")
    if not isinstance(auth_date, int):
        return False
    if abs((now if now is not None else int(time.time())) - auth_date) > MAX_AGE_SECONDS:
        return False
    if app_id is not None and payload.get("app_id") != app_id:
        return False
    return True
