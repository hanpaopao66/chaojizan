"""生产环境演示数据清理(生产/演示隔离)。

删除 seed/demo_seed 灌入的演示账号及其名下全部数据(商家、菜品、订单、
团购券、住宿、流水、评价、工单……),并可重置管理员密码。
演示账号号段:138000000xx(现行 seed)与 938000000xx(历史 seed),
真实用户不可能撞上。

账本:**不动。**

这里曾经连 ledger_anchors 一起清、让链重新起链,理由写的是"演示订单被清后
历史锚点必然与数据重算对不上"。

**这个理由是错的。** 锚点存的是当天的 payload **全文**,`/ledger/days/{day}`
返回的是存下来的那份,不是实时查询 —— 底层单据删掉之后,锚点照样复算得出
同样的 payload_hash 和 chain_hash。见 tests/unit/test_ledger_immutable.py。

而清账本的代价极大:2026-07-28 在生产上跑过一次,官方见证节点从那天报警
到今天 9000 多次 —— 它本地留着 2026-06-13 起的 71 天,平台侧只剩 2026-06-29,
中间 16 天在平台侧整个消失。对外部观察者来说,那就是「平台删了 16 天的账」。
更糟的是警报从此卡死:真出事时也没人会再看它。

真有非重置不可的理由,走 services/ledger.py 的 open_new_epoch():
它会先把旧链的链尾哈希冻结成一条永久公开记录再动手。

用法(在部署机上,先预览再执行):
    docker exec superz-api python -m scripts.scrub_demo
    docker exec -e SUPERZ_ADMIN_PASSWORD='强密码' superz-api \
        python -m scripts.scrub_demo --yes

幂等:重复执行无副作用。不带 --yes 时只预览将删除的内容,不动数据。
管理员账号不删;SUPERZ_ADMIN_PASSWORD 未设置时跳过密码重置。
"""
import argparse
import asyncio
import os
import sys

from sqlalchemy import delete, or_, select, text, update

sys.path.insert(0, ".")

from app.db import SessionLocal  # noqa: E402
from app import models as m  # noqa: E402
from app.models import (  # noqa: E402
    Merchant,
    Order,
    RoomType,
    StayOrder,
    User,
    UserRole,
    Voucher,
)

# seed/demo_seed 专用号段(138000000xx / 938000000xx,覆盖尾号 00-99)。
# 管理员(role=admin)不删,只重置密码。
DEMO_PHONE_PREFIXES = ("138000000", "938000000")


async def _wipe(db, model, apply: bool, **id_sets) -> int:
    """按模型上实际存在的外键列删除;列不存在或集合为空则跳过。"""
    conds = [getattr(model, col).in_(ids)
             for col, ids in id_sets.items()
             if ids and hasattr(model, col)]
    if not conds:
        return 0
    total = 0
    for cond in conds:  # 分列删,同一行命中多列也只是幂等重删
        if apply:
            result = await db.execute(delete(model).where(cond))
            total += result.rowcount or 0
        else:
            total += len((await db.scalars(select(model.id).where(cond))).all())
    return total


async def scrub(apply: bool) -> None:
    async with SessionLocal() as db:
        # 生产库迁移可能滞后于模型:不存在的表直接跳过,别让预览半途炸掉
        existing_tables = set((await db.scalars(text(
            "select tablename from pg_tables where schemaname='public'"))).all())
        cond = or_(*[User.phone.startswith(p) for p in DEMO_PHONE_PREFIXES])
        demo_users = (await db.scalars(select(User).where(cond))).all()
        admin_ids = [u.id for u in demo_users if u.role == UserRole.admin]
        uids = [u.id for u in demo_users if u.role != UserRole.admin]

        mids = list(await db.scalars(
            select(Merchant.id).where(Merchant.owner_id.in_(uids)))) if uids else []
        oids = list(await db.scalars(select(Order.id).where(
            Order.customer_id.in_(uids or [0])
            | Order.merchant_id.in_(mids or [0])
            | Order.rider_id.in_(uids or [0])))) if (uids or mids) else []
        sids = list(await db.scalars(select(StayOrder.id).where(
            StayOrder.customer_id.in_(uids or [0])
            | StayOrder.merchant_id.in_(mids or [0])))) if (uids or mids) else []
        vids = list(await db.scalars(
            select(Voucher.id).where(Voucher.merchant_id.in_(mids)))) if mids else []
        rtids = list(await db.scalars(
            select(RoomType.id).where(RoomType.merchant_id.in_(mids)))) if mids else []

        print(f"演示账号 {len(uids)} 个(另有管理员 {len(admin_ids)} 个只重置密码)")
        print(f"名下:商家 {len(mids)} / 订单 {len(oids)} / 住宿单 {len(sids)}"
              f" / 团购券 {len(vids)} / 房型 {len(rtids)}")

        new_password = os.environ.get("SUPERZ_ADMIN_PASSWORD", "")
        if apply and admin_ids and new_password and len(new_password) < 12:
            print("✗ 未执行:SUPERZ_ADMIN_PASSWORD 至少 12 位")
            sys.exit(1)

        # FK 安全顺序:单据下游 → 单据 → 商家资产 → 商家 → 用户资产 → 用户
        plan = [
            # 订单/住宿单/团购的下游
            (m.OrderEvent,          dict(order_id=oids)),
            (m.Review,              dict(order_id=oids)),
            (m.AfterSale,           dict(order_id=oids)),
            (m.FoodSafetyReport,    dict(order_id=oids)),
            (m.Refund,              dict(order_id=oids)),
            (m.DeliveryIssue,       dict(order_id=oids)),
            (m.Message,             dict(order_id=oids)),
            (m.ProfitSharingRecord, dict(order_id=oids)),
            (m.MerchantEarning,     dict(order_id=oids, merchant_id=mids)),
            (m.RiderEarning,        dict(order_id=oids, rider_id=uids)),
            (m.AddressFeedback,     dict(customer_id=uids, rider_id=uids)),
            (m.StayAfterSale,       dict(stay_order_id=sids)),
            (m.StayReview,          dict(stay_order_id=sids)),
            (m.VoucherPurchase,     dict(voucher_id=vids, customer_id=uids)),
            # 单据本体
            (m.Order,               dict(id=oids)),
            (m.StayOrder,           dict(id=sids)),
            # 商家资产
            (m.RoomCalendar,        dict(room_type_id=rtids)),
            (m.RoomType,            dict(id=rtids)),
            (m.HotelProfile,        dict(merchant_id=mids)),
            (m.Voucher,             dict(id=vids)),
            (m.Dish,                dict(merchant_id=mids)),
            (m.Cart,                dict(merchant_id=mids, user_id=uids)),
            (m.Favorite,            dict(merchant_id=mids, user_id=uids)),
            (m.MerchantStaff,       dict(merchant_id=mids, user_id=uids)),
            (m.Coupon,              dict(merchant_id=mids, user_id=uids)),
            (m.CouponBatch,         dict(merchant_id=mids)),
            (m.InvoiceRequest,      dict(merchant_id=mids)),
            (m.Merchant,            dict(id=mids)),
            # 用户资产
            (m.Address,             dict(user_id=uids)),
            (m.UserIdentity,        dict(user_id=uids)),
            (m.RiderProfile,        dict(rider_id=uids)),
            (m.Withdrawal,          dict(user_id=uids)),
            (m.Ticket,              dict(user_id=uids)),
            (m.PushLog,             dict(user_id=uids)),
            (m.AppEvent,            dict(user_id=uids)),
            (m.Referral,            dict(inviter_id=uids, invitee_id=uids)),
            (m.PayoutAccount,       dict(user_id=uids)),
            (m.RiderInsuranceDay,   dict(rider_id=uids)),
            (m.RiderAccident,       dict(rider_id=uids)),
            (m.RiderExam,           dict(rider_id=uids)),
            (m.RiderGear,           dict(rider_id=uids)),
            (m.RiderSession,        dict(rider_id=uids)),
            (m.RiderEmergency,      dict(rider_id=uids)),
            (m.RiskActionLog,       dict(user_id=uids)),
            (m.Appeal,              dict(user_id=uids)),
            (m.User,                dict(id=uids)),
        ]
        for model, id_sets in plan:
            if model.__tablename__ not in existing_tables:
                print(f"  - 跳过 {model.__tablename__}(表不存在,迁移未到)")
                continue
            n = await _wipe(db, model, apply, **id_sets)
            if n:
                print(f"  {'✓ 删除' if apply else '将删除'} "
                      f"{model.__tablename__}: {n}")

        if not apply:
            print("\n预览模式,未做任何修改。确认无误后加 --yes 执行。")
            return

        # ⚠️ **不清空账本锚点。**
        #
        # 锚点存的是当天的 payload 全文,不是实时查询 —— 单据删了它照样自洽,
        # 见证节点复算得出同样的哈希(tests/unit/test_ledger_immutable.py 锁着)。
        # 当初那条"必然对不上"的理由是错的,而代价是 9000 多次警报。
        #
        # 真要重置走 ledger.open_new_epoch():先冻结旧链链尾再动手。
        if m.AuditAlert.__tablename__ in existing_tables:
            # 未决告警会引用已删单据,留着就是每天一条查不下去的红条;
            # AuditRun(历史核账记录)**不删** —— 删了"连续 N 天零差错"
            # 会归零,那是自己给自己抹掉的信用
            await db.execute(delete(m.AuditAlert))
            print("  ✓ 未决内审告警已清空(账本锚点与历史核账记录保留)")

        if admin_ids and new_password:
            from app.security import hash_password
            await db.execute(update(User).where(User.id.in_(admin_ids))
                             .values(password_hash=hash_password(new_password)))
            print(f"  ✓ 管理员({len(admin_ids)} 个)密码已重置")

        await db.commit()
        print("✓ 清理完成(幂等,可重复执行)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理生产环境演示数据")
    parser.add_argument("--yes", action="store_true", help="确认执行(否则只预览)")
    args = parser.parse_args()
    asyncio.run(scrub(args.yes))
