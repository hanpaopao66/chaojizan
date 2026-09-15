"""防刷单风控:下单后异步评估,只标记不拦截。

原则:宁可错标不可错拦——命中只写 orders.risk_flags 供后台复核,
资金结算照常(钱是真付的);确认(confirmed)的单从月售/销量排行剔除。
规则三条(阈值在 config 可调):
  addr_freq            同收货位置(~65m)24h 内多单且多账号
  merchant_related     下单设备与店主设备相同(自己刷自己店)
  multi_account_device 同设备 24h 内多账号下单

原来还有一条 new_account_subsidy(注册 1 小时内下单且用了首单立减),防的是小号薅首单立减。
首单立减 2026-09-15 连开关带代码删了、平台券也停发了,新号下单拿不到任何平台补贴,这条跟着删;
历史订单 risk_flags 里记着的这个标记照旧留着。
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update

from ..config import settings
from ..db import SessionLocal
from ..models import Merchant, Order, User

logger = logging.getLogger("superz.risk")

_DEG = 0.0006  # ≈65m 的经纬度包围盒(风控标记用,不需要测地线精度)


async def _assess(order_id: int) -> None:
    async with SessionLocal() as db:
        order = await db.get(Order, order_id)
        if order is None:
            return
        customer = await db.get(User, order.customer_id)
        merchant = await db.get(Merchant, order.merchant_id)
        now = datetime.now(timezone.utc)
        hits: list[str] = []

        # ① 同收货位置高频:24h 内 ≥N 单且 ≥2 个账号(配送单才有收货位置)
        if not order.pickup:
            row = (await db.execute(
                select(func.count(Order.id),
                       func.count(func.distinct(Order.customer_id)))
                .where(Order.pickup.is_(False),
                       Order.created_at > now - timedelta(hours=24),
                       Order.lat.between(order.lat - _DEG, order.lat + _DEG),
                       Order.lng.between(order.lng - _DEG, order.lng + _DEG))
            )).first()
            if (row[0] >= settings.risk_addr_orders_24h and row[1] >= 2):
                hits.append("addr_freq")

        # ② 商家关联:下单设备与店主设备相同(同一部手机装了两端)
        if (customer is not None and merchant is not None
                and customer.device_id):
            owner = await db.get(User, merchant.owner_id)
            if owner is not None and owner.device_id == customer.device_id:
                hits.append("merchant_related")

        # ③ 同设备多账号:24h 内该设备下单的账号数 ≥2
        if customer is not None and customer.device_id:
            accounts = await db.scalar(
                select(func.count(func.distinct(Order.customer_id)))
                .join(User, User.id == Order.customer_id)
                .where(User.device_id == customer.device_id,
                       Order.created_at > now - timedelta(hours=24)))
            if (accounts or 0) >= 2:
                hits.append("multi_account_device")

        if hits:
            await db.execute(
                update(Order).where(Order.id == order.id)
                .values(risk_flags={"hits": hits, "status": ""}))
            await db.commit()
            logger.info("风控标记 order=%s hits=%s", order.order_no, hits)


def assess_order_async(order_id: int) -> None:
    """下单主流程调用:丢后台任务,评估失败绝不影响下单。"""
    async def _task():
        try:
            await _assess(order_id)
        except Exception:
            logger.exception("风控评估失败 order_id=%s", order_id)

    try:
        asyncio.get_running_loop().create_task(_task())
    except RuntimeError:  # 无事件循环(理论上不会,防御)
        pass
