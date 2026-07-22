"""电话脱敏(隐私中间号):保护用户手机号不暴露给商家和骑手。

分层设计(照微信支付的桩模式):
  - 脱敏展示:不依赖任何外部服务,永远生效——商家/骑手侧接口里
    contact_phone 一律打码(138****0001),小票同样只印打码号;
  - 可拨号码:走 OrderOut.privacy_phone 字段。绑定了 AXB 中间号给 X 号;
    未接入时过渡期给真号(privacy_phone_strict=False,拨打体验不变),
    严格模式给空串(客户端隐藏拨打按钮);
  - AXB 中间号:阿里云号码隐私保护。config 未配置时 bind/unbind 直接返回,
    配置后在支付成功时绑定、订单终结 N 小时后由清扫任务解绑。

绑定失败绝不影响订单流程:脱敏展示兜底始终在。
"""
import logging

from ..config import settings
from ..models import Order

logger = logging.getLogger("superz.privacy")


def mask_phone(phone: str) -> str:
    """138****0001:留前 3 后 4。短号/空号一律全打码,绝不吐原文。"""
    if len(phone) >= 8:
        return f"{phone[:3]}****{phone[-4:]}"
    return "****" if phone else ""


def dialable_phone(order: Order) -> str:
    """商家/骑手可拨的号码:X 号 > 过渡期真号 > 严格模式无。"""
    if order.privacy_phone:
        return order.privacy_phone
    if settings.privacy_phone_strict:
        return ""
    return order.contact_phone


async def bind_order(order: Order) -> None:
    """支付成功后绑定 AXB 中间号,X 号写进 order.privacy_phone。

    未配置时静默返回(降级为打码+真号过渡)。配置后接
    阿里云 BindAxb(PoolKey/PhoneNoA=用户号/PhoneNoB=商家或骑手号,
    Expiration=订单预期完成时间+解绑窗口),失败只记日志。
    """
    if not settings.ali_pnp_configured or order.privacy_phone:
        return
    try:
        # TODO(接入时): 调阿里云 dyplsapi BindAxb,拿 SecretNo 与 SubsId:
        #   order.privacy_phone = secret_no
        # SubsId 存 Redis(privacy:subs:{order_no}),解绑时用
        logger.info("AXB 绑定占位:订单 %s(已配置密钥,待接入 SDK)", order.order_no)
    except Exception as exc:  # 绑定失败不阻塞支付主流程
        logger.warning("AXB 绑定失败 %s: %s", order.order_no, exc)


async def unbind_order(order: Order) -> None:
    """订单终结后解绑中间号(清扫任务调用,幂等)。"""
    if not order.privacy_phone:
        return
    try:
        # TODO(接入时): 调 UnbindSubscription(SubsId 从 Redis 取)
        logger.info("AXB 解绑占位:订单 %s", order.order_no)
    except Exception as exc:
        logger.warning("AXB 解绑失败 %s(下轮清扫重试): %s", order.order_no, exc)
        return
    order.privacy_phone = ""
