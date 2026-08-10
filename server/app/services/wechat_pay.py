"""微信支付 V3(App 支付 + 分账占位)。

基于官方推荐的 wechatpayv3 库。未配置商户参数时 get_client() 返回 None,
支付接口返回 503,客户端自动降级到模拟支付——开发期全流程照跑。

联调清单见 docs/INTEGRATIONS.md。个别字段名可能随 SDK 版本微调,
所有调用点都集中在这一个文件里。
"""
import logging
import time
import uuid
from pathlib import Path

from fastapi import HTTPException

from ..config import settings
from ..models import Order

logger = logging.getLogger("superz.wxpay")

try:
    from wechatpayv3 import WeChatPay, WeChatPayType
except ImportError:  # 依赖未装时也不阻塞其他功能
    WeChatPay = None
    WeChatPayType = None

_client = None


def get_client():
    global _client
    if not settings.wxpay_configured or WeChatPay is None:
        return None
    if _client is None:
        try:
            extra = {}
            pub_path = Path(settings.wxpay_public_key_path or "")
            if settings.wxpay_public_key_id and pub_path.is_file():
                # 公钥模式(2024 下半年后新开的商户号默认,本商户号即是):
                # 微信不再发平台证书,回调验签用「微信支付公钥」
                extra["public_key"] = pub_path.read_text()
                extra["public_key_id"] = settings.wxpay_public_key_id
            elif settings.wxpay_public_key_id:
                logger.error("公钥文件缺失,微信支付未启用: %s",
                             settings.wxpay_public_key_path)
                return None
            else:
                # 平台证书模式(老商户号):SDK 自动下载,缓存避免每次重启重拉
                cert_dir = Path(settings.wxpay_private_key_path).parent / "platform"
                cert_dir.mkdir(parents=True, exist_ok=True)
                extra["cert_dir"] = str(cert_dir)
            _client = WeChatPay(
                wechatpay_type=WeChatPayType.APP,
                mchid=settings.wxpay_mchid,
                private_key=Path(settings.wxpay_private_key_path).read_text(),
                cert_serial_no=settings.wxpay_cert_serial_no,
                apiv3_key=settings.wxpay_api_v3_key,
                appid=settings.wxpay_app_id,
                notify_url=settings.wxpay_notify_url,
                logger=logger,
                **extra,
            )
        except Exception:
            # 配置有误不能把下单接口打成 500:记日志 + 返回 None(接口 503)
            logger.exception("微信支付客户端初始化失败,请检查证书/密钥配置")
            return None
    return _client


def create_app_prepay(order: Order) -> dict:
    """统一下单,返回 App 拉起微信支付所需的参数(客户端用 fluwx 调起)。"""
    client = get_client()
    if client is None:
        raise HTTPException(503, "微信支付未配置,请先使用模拟支付(联调时填好商户参数即可启用)")

    code, message = client.pay(
        description=f"Super-Z 外卖订单 {order.order_no}",
        out_trade_no=order.order_no,
        amount={"total": order.total_cents},
        pay_type=WeChatPayType.APP,
    )
    if code != 200:
        logger.error("微信统一下单失败 %s: %s", code, message)
        raise HTTPException(502, "微信下单失败,请稍后再试")

    import json

    prepay_id = json.loads(message)["prepay_id"]
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    # App 调起支付的二次签名(SDK 提供 sign 方法)
    sign = client.sign([settings.wxpay_app_id, timestamp, nonce, prepay_id])
    return {
        "appid": settings.wxpay_app_id,
        "partnerid": settings.wxpay_mchid,
        "prepayid": prepay_id,
        "package": "Sign=WXPay",
        "noncestr": nonce,
        "timestamp": timestamp,
        "sign": sign,
    }


def parse_notify(headers: dict, body: bytes) -> tuple[str, dict] | None:
    """验签并解密微信回调,返回 (event_type, resource);验签失败返回 None。

    事件类型:TRANSACTION.SUCCESS(支付成功)、REFUND.SUCCESS / REFUND.ABNORMAL /
    REFUND.CLOSED(退款结果)。路由层按事件分发处理。
    """
    client = get_client()
    if client is None:
        return None
    result = client.callback(headers, body)
    if not result or not result.get("event_type"):
        return None
    return result["event_type"], result.get("resource", {})


async def request_refund(db, order: Order, refund_cents: int, reason: str) -> "object":
    """缺货部分退款/整单退款/售后退款,统一入口。

    每次退款写一条 refunds 流水(金额对账凭据,审计核对 Σ流水 == 订单 refund_cents)。
    - 未配置商户参数:mock 通道,立即置 success(开发/演示期)
    - 已配置:调微信退款 API(同步 SDK 丢线程池),渠道受理为 requested,
      REFUND.SUCCESS 回调置 success(见 routers/payments.py)
    返回 Refund 对象;调用方负责 commit。
    """
    import asyncio

    from ..models import Refund, RefundStatus

    client = get_client()
    refund = Refund(
        order_id=order.id,
        order_no=order.order_no,
        out_refund_no=f"{order.order_no}-{uuid.uuid4().hex[:8]}",
        amount_cents=refund_cents,
        reason=reason[:200],
        channel="mock" if client is None else "wechat",
    )
    if client is None:
        refund.status = RefundStatus.success
        logger.info("模拟退款成功 %s 分: %s (%s)", refund_cents, order.order_no, reason)
    else:
        # 原始支付总额 = 当前订单金额 + 历史已退金额(部分退款会扣减 total_cents)
        original_total = order.total_cents + order.refund_cents
        code, message = await asyncio.to_thread(
            client.refund,
            out_trade_no=order.order_no,
            out_refund_no=refund.out_refund_no,
            amount={"refund": refund_cents, "total": original_total,
                    "currency": "CNY"},
            reason=reason[:80],
        )
        if code in (200, 201):
            refund.status = RefundStatus.requested
        else:
            refund.status = RefundStatus.failed
            refund.error = f"HTTP {code}: {str(message)[:250]}"
            logger.error("微信退款发起失败 %s: %s %s", order.order_no, code, message)
    db.add(refund)
    return refund


# ---------- 服务商分账(五 API 桩,联调时按 SDK 填实) ----------

async def submit_sub_merchant_application(merchant, contact: dict) -> str:
    """特约商户进件(桩):返回申请单号;未配置返回空串。
    TODO(联调):POST /v3/applyment4sub/applyment,材料含证照/结算账户。"""
    if get_client() is None:
        return ""
    logger.info("进件待实现(需服务商资质): merchant=%s", merchant.id)
    return ""


async def query_sub_merchant_application(applyment_id: str) -> str:
    """进件状态查询(桩):返回状态串;未配置返回空串。"""
    if get_client() is None:
        return ""
    return ""


async def add_profitsharing_receiver(sub_mchid: str) -> bool:
    """把特约商户号添加为分账接收方(桩)。
    TODO(联调):POST /v3/profitsharing/receivers/add,type=MERCHANT_ID。"""
    if get_client() is None:
        return False
    logger.info("添加分账接收方待实现: %s", sub_mchid)
    return False


async def download_profitsharing_bill(bill_date: str) -> bytes | None:
    """下载分账账单(桩):每日对账用,与 profit_sharing_records 核对,
    差异写 audit_alerts。未配置返回 None。
    TODO(联调):GET /v3/profitsharing/bills?bill_date=。"""
    if get_client() is None:
        return None
    return None
