"""微信支付:统一下单 + 回调。模拟支付仍在 orders.py(开发期用)。"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import AuditAlert, Merchant, Order, Refund, RefundStatus, User
from ..security import require_role
from ..services.payment_core import mark_order_paid
from ..services.wechat_pay import create_app_prepay, parse_notify
from ..state_machine import OrderStatus

logger = logging.getLogger("superz.wxpay")

router = APIRouter(tags=["支付"])

AMOUNT_MISMATCH_CHECK = "payment_amount_mismatch"
PAID_CANCELLED_CHECK = "payment_on_cancelled_order"


def _notify_amount_cents(resource: dict) -> int | None:
    """回调里的实收金额(分);取不到或类型不对返回 None。

    取 `amount.total` 而不是 `amount.payer_total`,因为下单时报给微信的
    就是 total(见 wechat_pay.create_app_prepay 的 `amount={"total": ...}`)
    —— 两端拿同一个口径才比得起来。两者在我们这里目前恒等(没接微信侧的
    代金券/立减),但接了之后 payer_total 会小于 total,而商家该收到的、
    平台该抽佣的都是 total,拿 payer_total 比等于自己给自己判错。

    **返回 None 不代表 0,也不代表通过。** 调用方一律当校验不通过处理:
    读不出金额就等于没验金额,而"没验金额就入账"正是这次要堵掉的洞。
    """
    amount = resource.get("amount")
    if not isinstance(amount, dict):
        return None
    total = amount.get("total")
    # bool 是 int 的子类,挡一下;金额必须是整数分
    return total if isinstance(total, int) and not isinstance(total, bool) else None


async def _reject_amount_mismatch(
    db: AsyncSession, order: Order, paid: int | None
) -> None:
    """金额对不上:写告警并落盘,绝不入账。

    去重按订单号:微信对非 2xx 会在 24 小时内重试十几次,每次写一条
    会把管理后台首页的红条刷满,反而盖掉别的账务问题 ——
    告警的价值在于被看见,不在于条数。
    """
    # 去重的匹配串带上后缀,不能只 LIKE 订单号:订单号是变长的,
    # 光匹配前缀会把"另一单"误判成重复,那是把真告警丢掉
    key = f"订单 {order.order_no} 应付"
    detail = (f"微信支付回调金额不符:{key} {order.total_cents} 分,"
              f"回调 {paid} 分。已拒绝入账,订单保持待支付,"
              f"请人工核对微信商户后台该笔交易")
    logger.error("%s", detail)
    dup = await db.scalar(select(AuditAlert.id).where(
        AuditAlert.check_name == AMOUNT_MISMATCH_CHECK,
        AuditAlert.detail.contains(key)))
    if dup is None:
        db.add(AuditAlert(check_name=AMOUNT_MISMATCH_CHECK, detail=detail[:500]))
    # 必须在抛异常之前提交:告警是这条路径唯一的产出,
    # 跟着事务一起回滚的话,拒绝入账就成了静默丢单
    await db.commit()


async def _alert_paid_on_cancelled(db: AsyncSession, order: Order) -> None:
    """钱收了,单没了。

    用户付款成功但订单已取消(取消与支付并发、或超时清扫抢在回调前面)。
    这条路径以前是**静默 ack** —— 微信那边显示付款成功、我们这边订单是已取消,
    钱躺在商户号里没人知道,直到用户来投诉。

    仍然 ack:订单已取消是终态,重试不会把它变回来,让微信一直重试没有意义。
    但必须留一条告警,让人去退这笔钱。
    """
    key = f"订单 {order.order_no} 已取消"
    detail = (f"用户付款成功但{key}:实付 {order.total_cents} 分。"
              f"钱已到商户号而订单不存在,需人工原路退款")
    logger.error("%s", detail)
    dup = await db.scalar(select(AuditAlert.id).where(
        AuditAlert.check_name == PAID_CANCELLED_CHECK,
        AuditAlert.detail.contains(key)))
    if dup is None:
        db.add(AuditAlert(check_name=PAID_CANCELLED_CHECK, detail=detail[:500]))
        await db.commit()


@router.post("/orders/{order_no}/pay/wechat")
async def wechat_prepay(
    order_no: str,
    user: User = Depends(require_role("customer")),
    db: AsyncSession = Depends(get_db),
):
    """微信 App 支付统一下单,返回拉起支付的参数。未配置商户号时 503。"""
    order = await db.scalar(select(Order).where(Order.order_no == order_no))
    if order is None or order.customer_id != user.id:
        raise HTTPException(404, "订单不存在")
    if order.status != OrderStatus.PENDING_PAYMENT:
        raise HTTPException(409, "订单不是待支付状态")
    return create_app_prepay(order)


@router.post("/payments/wechat/notify")
async def wechat_notify(request: Request, db: AsyncSession = Depends(get_db)):
    """微信回调(支付 + 退款共用):验签 → 解密 → 按事件分发,全部幂等。"""
    body = await request.body()
    parsed = parse_notify(dict(request.headers), body)
    if parsed is None:
        # 未配置时不该被调到;验签失败一律拒绝,防伪造回调
        raise HTTPException(400, "验签失败")
    event_type, resource = parsed

    if event_type == "TRANSACTION.SUCCESS":
        if resource.get("trade_state") != "SUCCESS":
            return {"code": "SUCCESS", "message": "成功"}
        order = await db.scalar(
            select(Order)
            .where(Order.order_no == resource.get("out_trade_no"))
            .with_for_update()
        )
        if order is None:
            # 404 是**故意**的,不是漏处理:微信收到非 2xx 会按
            # 15s/15s/30s… 递增重试近 24 小时,而这里最可能的原因是
            # 回调跑在了下单事务提交之前 —— 等一会儿再来就对了。
            # 日志明说"已让微信重试",免得排查的人以为这笔回调丢了
            logger.error("微信支付回调找不到订单 %s,返回 404 让微信稍后重试",
                         resource.get("out_trade_no"))
            raise HTTPException(404, "订单不存在")

        # 服务商模式预留位:届时回调会带 sp_mchid(服务商号)/ sub_mchid
        # (特约商户号)。**现在一个字段都不校验、更不硬编码** ——
        # 普通服务商(/v3/applyment4sub)与电商收付通(/v3/ecommerce)
        # 两套的字段和语义都不同,类目答案没出来就先写死一套,
        # 切过去时要么校验形同虚设,要么把真回调挡在门外。
        # 改下单参数那一批在这里补两条,处理方式与金额不符一致
        # (拒绝入账 + 告警,不要自作主张纠正):
        #   1) sp_mchid == settings.wxpay_mchid —— 确认是我们这个服务商收的款;
        #   2) sub_mchid == merchant.sub_mchid —— 确认结给了这一单的商家,
        #      连锁多店共用一个 owner,结错店就是结错钱。

        if order.status == OrderStatus.PENDING_PAYMENT:
            # **金额只在"即将入账"这条路上校验。**
            # 重复回调时订单早已不是待支付,mark_order_paid 是空操作、
            # 没有资金动作要保护;而 total_cents 在支付之后会被加急小费、
            # 帮买按小票补收、改地址退差价改动,拿一条老回调去比新金额
            # 必然误报,误报多了这条检查就废了。
            paid = _notify_amount_cents(resource)
            if paid != order.total_cents:
                await _reject_amount_mismatch(db, order, paid)
                # 不 ack:让这笔留在微信的重试队列里,对方商户后台的
                # "回调失败"也看得见,多一双眼睛。金额不符是确定性的、
                # 重试不会把它变好,但告警已按订单去重,不会刷屏
                raise HTTPException(400, "回调金额与订单应付不符,已拒绝入账")

        # transaction_id 是分账接口的必传入参,以前直接丢了。
        # 幂等:一旦落库就不再改写 —— 重复回调不保证带这个字段,
        # 覆盖回空值会让这一单永远分不了账,而且事后补不回来
        tx_id = str(resource.get("transaction_id") or "").strip()[:64]
        backfilled = bool(tx_id) and not order.wx_transaction_id
        if backfilled:
            order.wx_transaction_id = tx_id
        was_pending = order.status == OrderStatus.PENDING_PAYMENT
        if order.status == OrderStatus.CANCELLED:
            await _alert_paid_on_cancelled(db, order)

        merchant = await db.get(Merchant, order.merchant_id)
        await mark_order_paid(db, order, merchant, actor_role="system")
        if backfilled and not was_pending:
            # 重复回调走的是 mark_order_paid 的幂等分支,它直接返回、不 commit。
            # 这时补落的 transaction_id 得自己提交,否则随会话一起丢掉
            await db.commit()

    elif event_type.startswith("REFUND."):
        refund = await db.scalar(
            select(Refund)
            .where(Refund.out_refund_no == resource.get("out_refund_no"))
            .with_for_update()
        )
        if refund is None:
            logger.error("退款回调找不到流水: %s", resource.get("out_refund_no"))
            raise HTTPException(404, "退款流水不存在")
        if refund.status != RefundStatus.success:  # 幂等:成功是终态
            if event_type == "REFUND.SUCCESS":
                refund.status = RefundStatus.success
            else:  # ABNORMAL / CLOSED:渠道侧失败,审计会因金额不平而告警
                refund.status = RefundStatus.failed
                refund.error = f"渠道回调 {event_type}"
                logger.error("退款失败 %s: %s", refund.out_refund_no, event_type)
            await db.commit()

    return {"code": "SUCCESS", "message": "成功"}
