"""防刷单风控:下单后异步评估,只标记不拦截。

原则:宁可错标不可错拦——命中只写 orders.risk_flags 供后台复核,
资金结算照常(钱是真付的);确认(confirmed)的单从月售/销量排行剔除。
规则四条(阈值在 config 可调):
  addr_freq            同收货位置(~65m)24h 内多单且多账号
  new_account_subsidy  注册 1 小时内下单且用了首单立减(补贴照给)
  merchant_related     下单设备与店主设备相同(自己刷自己店)
  multi_account_device 同设备 24h 内多账号下单
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

        # ② 新号 + 首单立减(标记,补贴照给——宁可错给不可错杀)
        if (order.subsidy_cents > 0 and customer is not None
                and customer.created_at is not None):
            created = customer.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if now - created < timedelta(hours=1):
                hits.append("new_account_subsidy")

        # ③ 商家关联:下单设备与店主设备相同(同一部手机装了两端)
        if (customer is not None and merchant is not None
                and customer.device_id):
            owner = await db.get(User, merchant.owner_id)
            if owner is not None and owner.device_id == customer.device_id:
                hits.append("merchant_related")

        # ④ 同设备多账号:24h 内该设备下单的账号数 ≥2
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
