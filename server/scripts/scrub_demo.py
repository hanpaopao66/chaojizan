"""生产环境演示数据清理(M2 生产/演示隔离)。

删除 seed/demo_seed 灌入的演示账号及其名下全部数据(商家、菜品、订单、
流水、评价、工单……),并把管理员密码重置为环境变量 SUPERZ_ADMIN_PASSWORD。
演示账号的手机号约定为 138000000xx 段(seed 脚本专用,真实用户不可能撞上)。

用法(在部署机上):
    docker exec -e SUPERZ_ADMIN_PASSWORD='强密码' superz-api \
        python -m scripts.scrub_demo --yes

幂等:重复执行无副作用。不带 --yes 时只预览将删除的内容,不动数据。
"""
import argparse
import asyncio
import os
import sys

from sqlalchemy import delete, select, update

sys.path.insert(0, ".")

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Address,
    AfterSale,
    Dish,
    Favorite,
    Merchant,
    MerchantEarning,
    Order,
    OrderEvent,
    PushLog,
    Review,
    RiderEarning,
    RiderProfile,
    Ticket,
    User,
    UserRole,
    Withdrawal,
)

# seed/demo_seed 专用号段。管理员(role=admin)不删,只重置密码。
DEMO_PHONE_PREFIX = "1380000000"


async def scrub(apply: bool) -> None:
    async with SessionLocal() as db:
        demo_users = (await db.scalars(
            select(User).where(User.phone.startswith(DEMO_PHONE_PREFIX))
        )).all()
        if not demo_users:
            print("没有找到演示账号,无需清理")
        admin_ids = [u.id for u in demo_users if u.role == UserRole.admin]
        victim_ids = [u.id for u in demo_users if u.role != UserRole.admin]

        merchant_ids = list(await db.scalars(
            select(Merchant.id).where(Merchant.owner_id.in_(victim_ids))
        )) if victim_ids else []
        order_ids = list(await db.scalars(
            select(Order.id).where(
                Order.customer_id.in_(victim_ids)
                | Order.merchant_id.in_(merchant_ids)
                | Order.rider_id.in_(victim_ids)
            )
        )) if (victim_ids or merchant_ids) else []

        print(f"演示账号 {len(demo_users)} 个(管理员 {len(admin_ids)} 个只重置密码)")
        print(f"待删除:商家 {len(merchant_ids)} 家、订单 {len(order_ids)} 单及其全部关联数据")
        if not apply:
            print("\n预览模式,未做任何修改。确认无误后加 --yes 执行。")
            return

        # 密码先行校验:不通过就一行数据都不动
        new_password = os.environ.get("SUPERZ_ADMIN_PASSWORD", "")
        if admin_ids and len(new_password) < 12:
            print("\n✗ 未执行:请设置环境变量 SUPERZ_ADMIN_PASSWORD(至少 12 位)用于重置管理员密码")
            sys.exit(1)

        # FK 安全的删除顺序:订单的下游 → 订单 → 商家的下游 → 商家 → 用户的下游 → 用户
        if order_ids:
            for model in (OrderEvent, Review, AfterSale,
                          MerchantEarning, RiderEarning):
                await db.execute(delete(model).where(model.order_id.in_(order_ids)))
            await db.execute(delete(Order).where(Order.id.in_(order_ids)))
        if merchant_ids:
            await db.execute(delete(Dish).where(Dish.merchant_id.in_(merchant_ids)))
            await db.execute(
                delete(Favorite).where(Favorite.merchant_id.in_(merchant_ids)))
            await db.execute(delete(Merchant).where(Merchant.id.in_(merchant_ids)))
        if victim_ids:
            for model, col in ((Address, Address.user_id),
                               (RiderProfile, RiderProfile.rider_id),
                               (Withdrawal, Withdrawal.user_id),
                               (Ticket, Ticket.user_id),
                               (Favorite, Favorite.user_id),
                               (PushLog, PushLog.user_id)):
                await db.execute(delete(model).where(col.in_(victim_ids)))
            await db.execute(delete(User).where(User.id.in_(victim_ids)))

        if admin_ids:
            from app.security import hash_password
            await db.execute(update(User).where(User.id.in_(admin_ids))
                             .values(password_hash=hash_password(new_password)))
            print(f"✓ 管理员({len(admin_ids)} 个)密码已重置为 SUPERZ_ADMIN_PASSWORD")

        await db.commit()
        print("✓ 清理完成(幂等,可重复执行)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理生产环境演示数据")
    parser.add_argument("--yes", action="store_true", help="确认执行(否则只预览)")
    args = parser.parse_args()
    asyncio.run(scrub(args.yes))
