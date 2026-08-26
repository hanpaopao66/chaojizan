"""轻量营销触达三合一:生日券 / 复购提醒 / 收藏店上新。

**发券的钱由商家出**(#115):三个任务都只从商家批次(merchant_id 非空)
发券,商家没建批次就只推不发。平台立场是不靠补贴换增长——
用户端「我们承诺不做的事」印着这句,发钱的口子不能开在营销上。

共同的克制原则:
- 总频控:营销推送每人每自然周 ≤2 条(Redis mkt:freq:{uid}:{年-周});
- 用户可在「我的」一键关闭营销推送(users.marketing_push);
- 发券全部走 #49 批次(admin 建 trigger=birthday/winback 的批次,
  预算封顶),没有启用中的批次就只推不发/不推;
- 每个任务每天只跑一次(Redis 防重,照 #43 备货提醒)。
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Coupon, CouponBatch, Dish, Favorite, Merchant, Order,
                      User, UserRole)
from ..redis_client import get_redis
from ..state_machine import OrderStatus
from .push import push_to_user

logger = logging.getLogger("superz.marketing")

WEEKLY_CAP = 2


async def _under_cap(user_id: int) -> bool:
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    key = f"mkt:freq:{user_id}:{now.strftime('%G-%V')}"
    n = int(await get_redis().get(key) or 0)
    return n < WEEKLY_CAP


async def _count_send(user_id: int) -> None:
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    key = f"mkt:freq:{user_id}:{now.strftime('%G-%V')}"
    redis = get_redis()
    await redis.incr(key)
    await redis.expire(key, 14 * 86400)


async def _active_batches(db: AsyncSession, trigger: str) -> list[CouponBatch]:
    """每家店取一张启用中的批次(同店多张取最新建的)。

    钱是商家出的,触达范围就必须按店切开(#117):一店一批次,各发各的客,
    预算也各自封顶。老口径是随便挑一家店的批次去发全平台的人——
    那家店在替所有同行买单。
    """
    rows = (await db.scalars(
        select(CouponBatch).where(
            CouponBatch.trigger == trigger,
            CouponBatch.active.is_(True),
            CouponBatch.merchant_id.is_not(None),
            CouponBatch.issued < CouponBatch.total)
        .order_by(CouponBatch.created_at.desc()))).all()
    seen: set[int] = set()
    return [b for b in rows
            if b.merchant_id not in seen and not seen.add(b.merchant_id)]


async def dormant_customer_ids(db: AsyncSession, merchant_id: int,
                               dormant_days: int = 30,
                               lookback_days: int = 180) -> list[int]:
    """这家店的沉睡老客:在本店下过完成单,最近 dormant_days 天没再来。

    lookback_days 是下限——半年前来过一次就再没出现的,多半已经搬走或
    换了口味,再骚扰只是消耗商家预算和用户耐心。

    只返回 user_id 供发券用,不带任何身份信息;对商家侧只暴露计数(#117)。
    """
    rows = await db.execute(
        select(Order.customer_id, func.max(Order.created_at))
        .where(Order.merchant_id == merchant_id,
               Order.status == OrderStatus.COMPLETED)
        .group_by(Order.customer_id))
    now = datetime.now(timezone.utc)
    dormant_before = now - timedelta(days=dormant_days)
    active_after = now - timedelta(days=lookback_days)
    out = []
    for uid, last in rows:
        last_utc = (last.replace(tzinfo=timezone.utc)
                    if last.tzinfo is None else last)
        if active_after <= last_utc < dormant_before:
            out.append(uid)
    return out


async def run_birthday(db: AsyncSession, today_mmdd: str, year: int) -> int:
    """生日当天发券+推送(每店一年一张:source=birthday:{mid}:{uid}:{年})。

    券是商家出的,所以只发给这家店自己的老客(在本店下过完成单的人)——
    照 #117 的口径,商家的预算不替同行拉客。
    """
    batches = await _active_batches(db, "birthday")
    if not batches:
        return 0
    birthday_ids = set((await db.scalars(select(User.id).where(
        User.birthday == today_mmdd, User.role == UserRole.customer,
        User.marketing_push.is_(True)))).all())
    if not birthday_ids:
        return 0
    sent = 0
    for batch in batches:
        # 本店老客(下过完成单的),与今天过生日的人取交集
        mine = set((await db.scalars(
            select(Order.customer_id).where(
                Order.merchant_id == batch.merchant_id,
                Order.status == OrderStatus.COMPLETED).distinct())).all())
        targets = birthday_ids & mine
        if not targets:
            continue
        shop_name = await db.scalar(
            select(Merchant.name).where(Merchant.id == batch.merchant_id))
        for uid in targets:
            source = f"birthday:{batch.merchant_id}:{uid}:{year}"
            if await db.scalar(select(Coupon.id).where(Coupon.source == source)):
                continue
            if not await _under_cap(uid):
                continue
            from .coupons import issue_from_batch
            coupon = await issue_from_batch(db, batch, uid, note="生日快乐")
            if coupon is None:
                break  # 这家店的预算发完了
            coupon.source = source  # 覆盖为按店按年唯一
            await db.commit()
            await _count_send(uid)
            try:
                await push_to_user(
                    uid, "生日快乐 🎂",
                    f"{shop_name or '你常去的店'}送你 "
                    f"{batch.amount_cents / 100:g} 元生日券"
                    f"({batch.valid_days} 天内有效),今天想吃点好的",
                    {"type": "coupon"}, record_skip=True)
            except Exception:
                pass
            sent += 1
    return sent


#: 每店每天最多触达多少人。**是"发出去几条"的上限,不是"看几个候选"的上限**
#: —— 区别见 run_winback 里的长注释。
DAILY_PER_SHOP = 200


async def run_winback(db: AsyncSession) -> int:
    """复购提醒:按店召回本店的沉睡老客,券由这家店自己出(#115/#117)。

    每人每店每月最多一次(Redis),叠加全局每周 2 条的总频控,
    每店每天最多发 DAILY_PER_SHOP 条。

    ## 两处「静默漏人」,都修了

    **一、每日上限原来切的是候选人,不是发出去的条数。**

    老写法是 `for user in users[:200]` —— 先把候选名单砍到 200 再进循环,
    而循环里第一件事就是按 Redis 月键跳过本月已发过的人。于是:

    - 第 1 天:给前 200 人发,月键写上;
    - 第 2 天:切出来的还是**同样这 200 人**,全被月键跳过,一条也发不出去;
    - 第 201 人往后:这个月永远轮不到。

    演示库里 1 号店有 214 个沉睡老客,末尾那 14 个就是这么消失的
    (`select ... where id in (...)` 没有 ORDER BY,回来的顺序大致按 id
    递增,新注册的人 id 最大、永远排在最后 —— 也就是**最该被召回的新客
    反而最先被砍掉**)。

    现在遍历全部候选,**发满 200 条才停**,并且补上 `order_by(User.id)`:
    没有 ORDER BY 时顺序由执行计划决定,同一份名单换个计划就换一批人,
    "每天 200 人"到底是哪 200 人不可复现。

    **二、去重键在真的发出去之前就写上了。**

    老写法先 `set nx` 占坑,再判周频控;周频控挡下的人 `continue` 走了,
    坑却已经占上 —— 他这个月不会再被尝试,而他一条也没收到。
    预算发完那次 `break` 同理,最后那个人白白被标记。

    现在把它当成"先占坑,没发成就退坑":任何没真正发出去的路径都
    `delete` 掉这个键,下一轮照常重试。
    """
    batches = await _active_batches(db, "winback")
    if not batches:
        return 0
    redis = get_redis()
    month = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m")
    sent = 0
    for batch in batches:
        dormant_ids = await dormant_customer_ids(db, batch.merchant_id)
        if not dormant_ids:
            continue
        shop_name = await db.scalar(
            select(Merchant.name).where(Merchant.id == batch.merchant_id))
        users = (await db.scalars(select(User).where(
            User.id.in_(dormant_ids), User.marketing_push.is_(True))
            .order_by(User.id))).all()
        shop_sent = 0
        for user in users:
            if shop_sent >= DAILY_PER_SHOP:
                break  # 今天这家店发够了,剩下的明天接着来
            key = f"mkt:winback:{batch.merchant_id}:{user.id}:{month}"
            if not await redis.set(key, 1, ex=35 * 86400, nx=True):
                continue  # 本月已发过
            if not await _under_cap(user.id):
                await redis.delete(key)   # 没发成,退坑
                continue
            from .coupons import issue_from_batch
            coupon = await issue_from_batch(db, batch, user.id, note="好久不见")
            if coupon is None:
                await redis.delete(key)   # 没发成,退坑
                break  # 预算发完了,这家店本轮到此为止
            await db.commit()
            await _count_send(user.id)
            try:
                await push_to_user(
                    user.id, f"{shop_name or '你常去的店'}:好久不见",
                    f"送你 {batch.amount_cents / 100:g} 元券"
                    f"({batch.valid_days} 天内有效),回来尝尝",
                    {"type": "coupon"}, record_skip=True)
            except Exception:
                pass
            sent += 1
            shop_sent += 1
    return sent


async def run_new_dish(db: AsyncSession) -> int:
    """收藏店上新:当天上架的新菜,汇总推给收藏了这些店的用户;
    同店 7 天内不重复推(Redis),不发券只提醒。"""
    day_start = datetime.now(timezone.utc) - timedelta(hours=24)
    new_dishes = (await db.execute(
        select(Dish.merchant_id, func.count(Dish.id))
        .where(Dish.created_at >= day_start, Dish.is_on_sale.is_(True))
        .group_by(Dish.merchant_id))).all()
    if not new_dishes:
        return 0
    merchant_ids = [mid for mid, _ in new_dishes]
    shops = {m.id: m.name for m in (await db.scalars(
        select(Merchant).where(Merchant.id.in_(merchant_ids)))).all()}
    favs = (await db.execute(
        select(Favorite.user_id, Favorite.merchant_id).where(
            Favorite.merchant_id.in_(merchant_ids)))).all()
    by_user: dict[int, list[int]] = {}
    for uid, mid in favs:
        by_user.setdefault(uid, []).append(mid)
    redis = get_redis()
    sent = 0
    for uid, mids in by_user.items():
        user = await db.get(User, uid)
        if user is None or not user.marketing_push:
            continue
        fresh_mids = []
        for mid in mids:
            if await redis.set(f"mkt:favnew:{uid}:{mid}", 1,
                               ex=7 * 86400, nx=True):
                fresh_mids.append(mid)
        if not fresh_mids:
            continue
        if not await _under_cap(uid):
            # **没推成就把坑退掉**(同 run_winback 里的第二条)。
            # 不退的话:这周被总频控挡下的人,这几家店的上新在他那里
            # 就是消失了 —— 键还挂着 7 天,而他一条都没收到
            for mid in fresh_mids:
                await redis.delete(f"mkt:favnew:{uid}:{mid}")
            continue
        await _count_send(uid)
        names = "、".join(shops.get(m, "") for m in fresh_mids[:3])
        try:
            await push_to_user(uid, "你收藏的店上新了",
                               f"{names} 上了新菜,去看看?",
                               {"type": "favorite"}, record_skip=True)
        except Exception:
            pass
        sent += 1
    return sent


async def maybe_run_marketing(now_beijing: datetime) -> dict[str, int]:
    """10:00 跑生日+复购,18:00 跑收藏上新(各自 Redis 每日防重)。"""
    from ..db import SessionLocal
    from .auto_flow import _in_window
    from .flags import marketing_on
    redis = get_redis()
    result = {"birthday": 0, "winback": 0, "new_dish": 0}
    async with SessionLocal() as db:
        if not await marketing_on(db):
            return result  # 营销总开关关:一条不推、一张不发
    if _in_window("10:00", now_beijing, window_seconds=300):
        if await redis.set(f"mkt:morning:{now_beijing.date()}", 1,
                           ex=86400, nx=True):
            async with SessionLocal() as db:
                result["birthday"] = await run_birthday(
                    db, now_beijing.strftime("%m-%d"), now_beijing.year)
                result["winback"] = await run_winback(db)
    elif _in_window("18:00", now_beijing, window_seconds=300):
        if await redis.set(f"mkt:evening:{now_beijing.date()}", 1,
                           ex=86400, nx=True):
            async with SessionLocal() as db:
                result["new_dish"] = await run_new_dish(db)
    if any(result.values()):
        logger.info("营销触达:%s", result)
    return result
