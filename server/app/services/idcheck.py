"""身份证实名核验:本地格式/校验位校验 + 三方二要素核验桩。

照支付桩模式:idcheck_* 未配置时走「开发模式」——18 位格式、出生日期
合法性、GB 11643-1999 校验位都真实校验,通过即算实名;配置后再调
三方 API 核验「姓名与证号是否一致」。年龄判定统一从证号解析生日计算。
"""
import logging
from datetime import date, datetime, timedelta, timezone

import httpx

from ..config import settings

logger = logging.getLogger("superz.idcheck")

# GB 11643-1999:前 17 位加权求和模 11 查表得校验位
_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CHECK_CHARS = "10X98765432"


def validate_id_no(id_no: str) -> tuple[date | None, str]:
    """本地校验身份证号。返回 (出生日期, 错误信息);错误信息为空即通过。"""
    id_no = id_no.strip().upper()
    if len(id_no) != 18 or not id_no[:17].isdigit() or \
            not (id_no[17].isdigit() or id_no[17] == "X"):
        return None, "身份证号须为 18 位(末位可为 X)"
    try:
        birth = datetime.strptime(id_no[6:14], "%Y%m%d").date()
    except ValueError:
        return None, "身份证号中的出生日期不合法"
    today = _today_beijing()
    if birth > today or birth.year < 1900:
        return None, "身份证号中的出生日期不合法"
    checksum = sum(int(d) * w for d, w in zip(id_no[:17], _WEIGHTS)) % 11
    if _CHECK_CHARS[checksum] != id_no[17]:
        return None, "身份证号校验位不正确,请核对后重新输入"
    return birth, ""


def _today_beijing() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


def is_adult(birth: date) -> bool:
    """按北京时间的今天算周岁,满 18 为成年。"""
    today = _today_beijing()
    age = today.year - birth.year - (
        1 if (today.month, today.day) < (birth.month, birth.day) else 0)
    return age >= 18


async def verify_two_elements(real_name: str, id_no: str) -> bool:
    """三方二要素核验:姓名与身份证号是否一致。

    未配置 = 开发模式,本地校验通过即视为一致(返回 True);
    配置后调三方 API,服务异常抛 RuntimeError(调用方给中文降级提示)。
    """
    if not settings.idcheck_configured:
        return True
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                settings.idcheck_api_url,
                headers={"Authorization": f"APPCODE {settings.idcheck_app_code}"},
                data={"name": real_name, "idcard": id_no},
            )
        resp.raise_for_status()
        data = resp.json()
        # 常见云市场二要素接口口径:status/code 表示是否一致。
        # 真正接入时按所选服务商文档核对这里的取值映射
        result = str(data.get("status") or data.get("code")
                     or data.get("result", ""))
        return result in ("01", "1", "match", "true")
    except httpx.HTTPError as exc:
        logger.warning("二要素核验服务异常: %s", exc)
        raise RuntimeError("实名核验服务暂时不可用") from exc
