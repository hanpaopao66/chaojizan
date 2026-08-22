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


async def _dispatch_refund(db, *, biz_type: str, biz_id: int, trade_no: str,
                           paid_total_cents: int, refund_cents: int,
                           reason: str):
    """写一条退款流水并向渠道发起。**外卖/团购券/住宿三条线唯一的出口。**

    - 未配置商户参数:mock 通道,立即置 success(开发/演示期)
    - 已配置:调微信退款 API(同步 SDK 丢线程池),渠道受理为 requested,
      REFUND.SUCCESS 回调置 success(见 routers/payments.py ——
      那段按 out_refund_no 反查,三条线共用,不需要知道是哪条业务线)
    返回 Refund 对象(未 commit,调用方负责)。

    `paid_total_cents` 是**用户为这笔业务实际付进来的总额**,微信退款 API
    要求同时给 `refund` 和 `total`,两者对不上直接拒。外卖那条线没单独存
    这个数(部分退款会扣减 total_cents),只能反推;券和住宿的实付额
    是稳定列,调用方直接给。

    金额语义在这里收口:`refund_cents` 必须是**真的会从支付渠道原路退回去
    的钱**。业务表上那个 refund_cents 不一定等于它 —— 住宿「到店无房」
    的退款额是「房费 + 商家违约金」,违约金那部分退款通道退不了
    (超过原支付额),得走还没接入的转账通道,详见 routers/stays 的调用点。
    """
    import asyncio

    from ..models import Refund, RefundStatus

    client = get_client()
    refund = Refund(
        biz_type=biz_type,
        biz_id=biz_id,
        out_refund_no=f"{trade_no}-{uuid.uuid4().hex[:8]}",
        amount_cents=refund_cents,
        reason=reason[:200],
        channel="mock" if client is None else "wechat",
    )
    if client is None:
        refund.status = RefundStatus.success
        logger.info("模拟退款成功 %s 分: %s %s (%s)",
                    refund_cents, biz_type, trade_no, reason)
    else:
        code, message = await asyncio.to_thread(
            client.refund,
            out_trade_no=trade_no,
            out_refund_no=refund.out_refund_no,
            amount={"refund": refund_cents, "total": paid_total_cents,
                    "currency": "CNY"},
            reason=reason[:80],
        )
        if code in (200, 201):
            refund.status = RefundStatus.requested
        else:
            refund.status = RefundStatus.failed
            refund.error = f"HTTP {code}: {str(message)[:250]}"
            logger.error("微信退款发起失败 %s: %s %s", trade_no, code, message)
    db.add(refund)
    return refund


async def request_refund(db, order: Order, refund_cents: int, reason: str) -> "object":
    """缺货部分退款/整单退款/售后退款,**外卖/跑腿唯一入口**。

    每次退款写一条 refunds 流水(金额对账凭据,审计核对 Σ流水 == 订单 refund_cents)。
    返回 Refund 对象;调用方负责 commit。

    ## 调用方两条纪律(写在这里是因为破坏它们没有任何症状)

    **1)`order.refund_cents` 由本函数累计,调用方不要再自己加。**
    以前是每个调用点手写一行 `order.refund_cents += x`,14 处里有 4 处
    写在了 `request_refund` **之前** —— 而下面反推原始支付总额用的正是
    `total_cents + refund_cents`,提前加过就把本次退款算了两遍,
    反推出 2T 而实际只退 T,微信按"两个数对不上"直接拒掉。
    mock 通道不校验这两个数,所以这个错在真机联调之前一点症状都没有。

    **2)先调本函数,再去改 `order.total_cents`。** 同理:反推依赖的是
    「改动之前」的剩余应付。先把 total 扣掉再来调,反推出来的就少了一截。

    渠道拒绝(failed)时**不累计** refund_cents:钱一分没退出去,账面就
    不能写"已退" —— 否则下一笔退款的反推还会再错一轮,而公开账本
    (services/ledger)读的就是这个数。失败的流水留在 refunds 表里,
    审计规则 11b(services/audit.py 的 `refund_failed`)会把它捞出来要
    人工介入 —— 那条规则以前**不存在**,这句注释承诺了一条没写的检查(#33)。
    """
    from ..models import REFUND_BIZ_FOOD, RefundStatus

    refund = await _dispatch_refund(
        db, biz_type=REFUND_BIZ_FOOD, biz_id=order.id,
        trade_no=order.order_no,
        # 原始支付总额 = 当前订单金额 + 历史已退金额(部分退款会扣减 total_cents)
        paid_total_cents=order.total_cents + order.refund_cents,
        refund_cents=refund_cents, reason=reason)
    # 外卖行额外落这两列:规则 6 的冲账判据(_reversal_due_ids)要 join
    # 回 orders,外键约束也只有真外键给得了。券/住宿行是 NULL
    refund.order_id = order.id
    refund.order_no = order.order_no
    if refund.status != RefundStatus.failed:
        order.refund_cents += refund_cents
    return refund


async def request_voucher_refund(db, purchase, refund_cents: int, reason: str):
    """团购券退款。券只有"全额退未使用的券"一种口径,实付额就是售价。

    **不改 purchase 上的任何字段** —— 状态由调用方按业务判定,
    本函数只负责把钱推出去并留下凭据。自检核对
    「Σ流水 == 售价」(规则 14),渠道拒绝就会当场不平。
    """
    from ..models import REFUND_BIZ_VOUCHER

    return await _dispatch_refund(
        db, biz_type=REFUND_BIZ_VOUCHER, biz_id=purchase.id,
        trade_no=purchase.purchase_no,
        paid_total_cents=purchase.sell_price_cents,
        refund_cents=refund_cents, reason=reason)


async def request_stay_refund(db, stay, refund_cents: int, reason: str):
    """住宿退款(用户取消 / 商家拒单 / noshow / 到店无房 / 协商退)。

    住宿的 `total_cents` 是稳定的房费总额,从不随退款下调
    (外卖那种"剩余应付"的语义在这里不存在),所以实付额直接给。

    **也不改 stay 上的 refund_cents。** 住宿的退款额是**取消政策**
    算出来的、一单只落定一次,不是逐笔累加出来的;渠道失败时把它清零
    反而会连带打破规则 9(净额+退款 == 房费)。让它保持"按政策该退多少",
    由规则 15 去核「Σ流水 == 该退多少」—— 渠道退失败就在那儿报出来。
    """
    from ..models import REFUND_BIZ_STAY

    return await _dispatch_refund(
        db, biz_type=REFUND_BIZ_STAY, biz_id=stay.id,
        trade_no=stay.order_no, paid_total_cents=stay.total_cents,
        refund_cents=refund_cents, reason=reason)


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
