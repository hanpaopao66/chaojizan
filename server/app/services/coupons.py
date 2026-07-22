"""平台券发放(批次制)。

成本全平台承担:下单抵扣走 subsidy 口径,与首单立减/安抚券同一条
审计通道,资金口径零新增。防超发/防重发:
- 批次总量:条件 UPDATE issued < total(预算封顶,发完自动停);
- 每人每批次一张:coupons.source = batch:{批次id}:{user_id} 唯一约束;
- 新客券防薅:同设备已有其他账号的用户不自动发(#44 风控口径)。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Coupon, CouponBatch, User

logger = logging.getLogger("superz.coupons")


async def issue_from_batch(db: AsyncSession, batch: CouponBatch,
                           user_id: int, note: str = "") -> Coupon | None:
    """从批次给用户发一张券。返回 None = 没发(重复/停用/发完)。
    不单独 commit,随调用方事务提交。"""
    if not batch.active:
        return None
    source = f"batch:{batch.id}:{user_id}"
    existing = await db.scalar(select(Coupon.id).where(
        Coupon.source == source))
    if existing:
        return None
    # 预算封顶:条件 UPDATE 防并发超发
    taken = (await db.execute(
        update(CouponBatch)
        .where(CouponBatch.id == batch.id, CouponBatch.issued < CouponBatch.total)
        .values(issued=CouponBatch.issued + 1)
        .returning(CouponBatch.id))).first()
    if taken is None:
        return None  # 发完了
    coupon = Coupon(
        user_id=user_id,
        amount_cents=batch.amount_cents,
        min_spend_cents=batch.min_spend_cents,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=batch.valid_days),
        source=source,
        batch_id=batch.id,
        note=note or batch.name,
    )
    db.add(coupon)
    return coupon


async def _device_has_other_account(db: AsyncSession, user: User) -> bool:
    """新客券防薅:同设备已有其他账号(#44 multi_account_device 口径)。"""
    if not user.device_id:
        return False
    other = await db.scalar(select(User.id).where(
        User.device_id == user.device_id, User.id != user.id).limit(1))
    return other is not None


async def issue_newcomer(db: AsyncSession, user: User) -> None:
    """注册钩子:给新用户发所有启用中的新客券批次(通常一个)。

    自带 try/except,发券失败绝不影响注册。调用方无需 commit
    (本函数自行 commit——注册已提交,这里是追加动作)。
    """
    try:
        from .flags import marketing_on
        if not await marketing_on(db):
            return  # 营销总开关关(没有补贴预算),一张不发
        if await _device_has_other_account(db, user):
            logger.info("新客券跳过(同设备多账号): user=%s", user.id)
            return
        batches = (await db.scalars(
            select(CouponBatch).where(CouponBatch.trigger == "newcomer",
                                      CouponBatch.active.is_(True)))).all()
        issued = [await issue_from_batch(db, b, user.id) for b in batches]
        if any(issued):
            await db.commit()
    except Exception:
        logger.exception("新客券发放失败 user=%s", user.id)
