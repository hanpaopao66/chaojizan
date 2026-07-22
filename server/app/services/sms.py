"""阿里云短信(验证码)。Dysmsapi SendSms,RPC 风格 HMAC-SHA1 签名(纯 httpx,无需 SDK)。

未配置时返回 False,调用方走开发模式(验证码直接返回给客户端)。
签名算法见阿里云《请求签名》文档,与官方 SDK 等价。
"""
import base64
import hashlib
import hmac
import json
import logging
import urllib.parse
import uuid
from datetime import datetime, timezone

import httpx

from ..config import settings

logger = logging.getLogger("superz.sms")

SMS_ENDPOINT = "https://dysmsapi.aliyuncs.com/"
SMS_VERSION = "2017-05-25"


def _percent_encode(s: str) -> str:
    """阿里云专用 URL 编码:标准 encode 后 + → %20、* → %2A、%7E → ~。"""
    encoded = urllib.parse.quote(str(s), safe="")
    return encoded.replace("+", "%20").replace("*", "%2A").replace("%7E", "~")


def _sign(params: dict) -> str:
    """RPC 签名:base64(HMAC-SHA1(AccessKeySecret + "&", StringToSign))。"""
    canonical = "&".join(
        f"{_percent_encode(k)}={_percent_encode(params[k])}"
        for k in sorted(params))
    string_to_sign = f"POST&{_percent_encode('/')}&{_percent_encode(canonical)}"
    digest = hmac.new(
        (settings.sms_secret_key + "&").encode("utf-8"),
        string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


async def send_verification_code(phone: str, code: str) -> bool:
    """发送验证码短信。True = 已发出,False = 未配置或发送失败。"""
    if not settings.sms_configured:
        return False
    params = {
        # 公共参数
        "AccessKeyId": settings.sms_secret_id,
        "Action": "SendSms",
        "Format": "JSON",
        "RegionId": settings.sms_region_id,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": SMS_VERSION,
        # 业务参数
        "PhoneNumbers": phone,
        "SignName": settings.sms_sign_name,
        "TemplateCode": settings.sms_template_id,
        "TemplateParam": json.dumps({settings.sms_template_param: code}),
    }
    params["Signature"] = _sign(params)
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                SMS_ENDPOINT, data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"})
        data = resp.json()
        if data.get("Code") == "OK":
            logger.info("短信已提交 尾号%s BizId=%s(下发回执见控制台发送记录)",
                        phone[-4:], data.get("BizId"))
            return True
        logger.warning("短信发送失败: %s", data)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("短信请求异常: %s", exc)
    return False
