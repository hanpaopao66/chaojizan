"""初始化演示数据:三个角色各一个账号 + 一家开业的店 + 三道菜。

用法(在 server/ 目录下):
    python -m scripts.seed
"""
import asyncio

from sqlalchemy import select, text

from app.db import Base, SessionLocal, engine
from app.models import (  # noqa: F401
    Dish,
    Merchant,
    MerchantStatus,
    RiderProfile,
    User,
    UserRole,
    VerifyStatus,
)
from app.security import hash_password

DEMO_PASSWORD = "123456"
ACCOUNTS = [
    ("13800000001", "测试用户", UserRole.customer),
    ("13800000002", "张老板", UserRole.merchant),
    ("13800000003", "骑手小王", UserRole.rider),
    ("13800000000", "平台管理员", UserRole.admin),
    ("13800000004", "李老板", UserRole.merchant),  # 演示待审核商家
    ("13800000005", "骑手小李", UserRole.rider),   # 演示待审核骑手
]
# 示例坐标:成都春熙路商圈
SHOP_LAT, SHOP_LNG = 30.6598, 104.0810


async def main():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        users = {}
        for phone, name, role in ACCOUNTS:
            user = await db.scalar(select(User).where(User.phone == phone))
            if user is None:
                user = User(
                    phone=phone,
                    name=name,
                    role=role,
                    password_hash=hash_password(DEMO_PASSWORD),
                )
                db.add(user)
                await db.flush()
            users[phone] = user

        shop = await db.scalar(
            select(Merchant).where(Merchant.owner_id == users["13800000002"].id)
        )
        if shop is None:
            shop = Merchant(
                owner_id=users["13800000002"].id,
                name="张记面馆",
                description="二十年老店,现炒浇头",
                address="春熙路步行街 8 号",
                lat=SHOP_LAT,
                lng=SHOP_LNG,
                is_open=True,
                status=MerchantStatus.approved,
                license_no="JY15101000012345",
                announcement="新店入驻超级赞,平台只抽 5%,让利全在菜价里",
            )
            db.add(shop)
            await db.flush()
            db.add_all(
                [
                    Dish(merchant_id=shop.id, name="红烧牛肉面", category="招牌", price_cents=1800, stock=100),
                    Dish(merchant_id=shop.id, name="酸辣粉", category="小吃", price_cents=1200, stock=100),
                    Dish(merchant_id=shop.id, name="冰豆浆", category="饮品", price_cents=600, stock=200),
                ]
            )
        else:
            # 老库补数据:公告和分类(幂等)
            if not shop.announcement:
                shop.announcement = "新店入驻超级赞,平台只抽 5%,让利全在菜价里"
            category_map = {"红烧牛肉面": "招牌", "酸辣粉": "小吃", "冰豆浆": "饮品"}
            existing_dishes = await db.scalars(
                select(Dish).where(Dish.merchant_id == shop.id, Dish.category == "")
            )
            for d in existing_dishes:
                d.category = category_map.get(d.name, "")
            # 库存补回基线:e2e 每跑一轮都会永久消耗库存(已完成订单不回补),
            # 不补的话跑几轮后菜品售罄,后续测试必挂
            baseline_stock = {"红烧牛肉面": 100, "酸辣粉": 100, "冰豆浆": 200}
            all_dishes = await db.scalars(
                select(Dish).where(Dish.merchant_id == shop.id)
            )
            for d in all_dishes:
                base = baseline_stock.get(d.name)
                if base is not None and d.stock < base:
                    d.stock = base

        # 一家待审核的店,方便演示后台审核流程
        pending = await db.scalar(
            select(Merchant).where(Merchant.owner_id == users["13800000004"].id)
        )
        if pending is None:
            db.add(
                Merchant(
                    owner_id=users["13800000004"].id,
                    name="李记烧烤",
                    description="深夜食堂,炭火现烤",
                    address="春熙路步行街 66 号",
                    lat=SHOP_LAT + 0.002,
                    lng=SHOP_LNG + 0.001,
                    is_open=False,
                    status=MerchantStatus.pending,
                    license_no="JY15101000067890",
                )
            )
        # 骑手小王:已通过实名认证(演示 e2e 用它接单)
        rider = users["13800000003"]
        rp = await db.scalar(select(RiderProfile).where(RiderProfile.rider_id == rider.id))
        if rp is None:
            db.add(RiderProfile(
                rider_id=rider.id, real_name="王小王",
                id_card_no="51010119900101001X",
                id_card_photo_url="/uploads/demo_idcard.jpg",
                health_cert_photo_url="/uploads/demo_health.jpg",
                status=VerifyStatus.approved,
            ))

        # 收款账户:演示商家(对公)与骑手(支付宝),提现全链路开箱即用
        from app.models import PayoutAccount
        from app.services.crypto import encrypt
        for phone, role, kind, holder, acct, bank in [
            ("13800000002", "merchant", "bank_corporate",
             "成都张记面馆餐饮有限公司", "51001887700889900123", "中国建设银行成都春熙支行"),
            ("13800000003", "rider", "alipay", "王小王", "13800000003", ""),
        ]:
            owner = users[phone]
            existing_pa = await db.scalar(
                select(PayoutAccount).where(PayoutAccount.user_id == owner.id))
            if existing_pa is None:
                db.add(PayoutAccount(
                    user_id=owner.id, role=role, kind=kind, holder_name=holder,
                    account_no_encrypted=encrypt(acct), account_tail=acct[-4:],
                    bank_name=bank,
                ))

        # 骑手小李:待审核,演示后台审核流程
        rider2 = users["13800000005"]
        rp2 = await db.scalar(select(RiderProfile).where(RiderProfile.rider_id == rider2.id))
        if rp2 is None:
            db.add(RiderProfile(
                rider_id=rider2.id, real_name="李小李",
                id_card_no="51010119920202002X",
                id_card_photo_url="/uploads/demo_idcard2.jpg",
                health_cert_photo_url="/uploads/demo_health2.jpg",
                status=VerifyStatus.pending,
            ))
        await db.commit()

    print("演示数据就绪。测试账号(密码均为 123456):")
    for phone, name, role in ACCOUNTS:
        print(f"  {role.value:10s} {phone}  {name}")


if __name__ == "__main__":
    asyncio.run(main())
