"""演示环境整备:隐藏测试残留店铺,创建一批像样的演示店。

- 外卖店 7 家(品类各异,撑满首页一屏):门头图、5-7 道带图菜品
  (纯 Python 生成的暖色渐变图,真实照片后续替换)
- 近 30 天的已完成订单(撑起「月售」)+ 真实评价(撑起评分)
- 团购券若干(应用商店审核要求已上线功能有真实感数据)
- 演示酒店 1 家(2 个房型 + 未来 45 天房态,可浏览可下单)
- 幂等:重复运行不会重复创建

用法(在 server/ 目录):python -m scripts.demo_seed
"""
import asyncio
import random
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import (
    Dish,
    HotelProfile,
    Merchant,
    MerchantEarning,
    MerchantStatus,
    Order,
    OrderEvent,
    Review,
    RoomCalendar,
    RoomType,
    User,
    UserRole,
    Voucher,
)
from app.security import hash_password
from app.state_machine import OrderStatus

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads" / "demo"
random.seed(42)  # 每次生成结果一致


# ---------- 纯 Python 渐变 PNG(无第三方依赖) ----------
def _png(path: Path, w: int, h: int, top: tuple, bottom: tuple) -> None:
    rows = b""
    for y in range(h):
        t = y / (h - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        # 加一点横向明暗起伏,不至于太"平"
        row = b"\x00" + bytes(
            v
            for x in range(w)
            for v in (
                min(255, r + (8 if (x // 40) % 2 else 0)),
                min(255, g + (8 if (x // 40) % 2 else 0)),
                min(255, b),
            )
        )
        rows += row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(rows, 6))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


# 暖色食物色系
PALETTES = [
    ((230, 126, 34), (192, 57, 43)),    # 烧烤橙红
    ((241, 196, 15), (211, 84, 0)),     # 金黄
    ((211, 84, 0), (120, 40, 31)),      # 酱色
    ((26, 188, 156), (22, 130, 93)),    # 清爽绿(饮品)
    ((236, 112, 99), (146, 43, 33)),    # 辣红
    ((245, 176, 65), (175, 96, 26)),    # 焦糖
]


def make_image(name: str, idx: int) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{name}.png"
    if not path.exists():
        top, bottom = PALETTES[idx % len(PALETTES)]
        _png(path, 400, 300, top, bottom)
    return f"/uploads/demo/{name}.png"


SHOPS = [
    {
        "phone": "13800000006", "owner": "陈姐", "name": "陈姐麻辣烫",
        "category": "malatang",
        "description": "汤底每天现熬,26 种食材自选", "address": "春熙路步行街 21 号",
        "lat": 30.6605, "lng": 104.0818,
        "announcement": "汤底免费续,加入 Super-Z 后全场比大平台便宜 10%",
        "dishes": [
            ("招牌麻辣烫(微辣)", "招牌", 1500), ("招牌麻辣烫(特辣)", "招牌", 1500),
            ("牛肉麻辣烫", "招牌", 1900), ("冬阴功汤底麻辣烫", "新品", 1800),
            ("手工丸子拼盘", "小食", 900), ("冰镇酸梅汤", "饮品", 500),
        ],
        "reviews": [
            (5, "汤底真的鲜,比商场里那家便宜好几块"),
            (5, "分量足,阿姨人特别好"),
            (4, "好吃,就是特辣是真的辣"),
            (5, "知道平台只抽 5% 之后,以后就点这家了"),
        ],
        "orders_30d": 46,
    },
    {
        "phone": "13800000007", "owner": "老北方", "name": "老北方饺子馆",
        "category": "dumplings",
        "description": "手工现包,一天卖三千个", "address": "东风路 12 号",
        "lat": 30.6620, "lng": 104.0795,
        "announcement": "每天 10:30 开门现包,卖完即止",
        "dishes": [
            ("猪肉大葱水饺(15个)", "水饺", 1600), ("三鲜水饺(15个)", "水饺", 1800),
            ("酸汤水饺(12个)", "水饺", 1500), ("锅贴(8个)", "煎烙", 1200),
            ("拍黄瓜", "凉菜", 800), ("小米粥", "粥汤", 400),
        ],
        "reviews": [
            (5, "皮薄馅大,和店里吃一个味"),
            (5, "送来还是热的,骑手辛苦"),
            (4, "锅贴稍微有点油,饺子没得说"),
        ],
        "orders_30d": 38,
    },
    {
        "phone": "13800000008", "owner": "小唐", "name": "清心茶饮",
        "category": "drinks_dessert",
        "description": "鲜果现切,不用果酱", "address": "春熙路步行街 35 号",
        "lat": 30.6592, "lng": 104.0822,
        "announcement": "本店所有原料公示在柜台,欢迎监督",
        "dishes": [
            ("满杯鲜橙", "鲜果茶", 1200), ("杨枝甘露", "鲜果茶", 1400),
            ("茉莉奶绿", "奶茶", 1000), ("生椰拿铁", "咖啡", 1300),
            ("柠檬气泡水", "气泡", 900),
        ],
        "reviews": [
            (5, "真的是鲜橙子,能吃到果肉"),
            (5, "杨枝甘露芒果给得大方"),
            (5, "支持透明账单的良心平台和良心店"),
            (4, "好喝,配送稍慢了几分钟"),
        ],
        "orders_30d": 61,
    },
    {
        "phone": "13800000009", "owner": "老宋", "name": "宋记烤串",
        "category": "bbq_fried",
        "description": "炭火现烤,肉串每天早市现串", "address": "青年路夜市 8 号",
        "lat": 30.6631, "lng": 104.0839,
        "announcement": "晚市 17:00 起炉,炭火烤串现烤现送",
        "dishes": [
            ("羊肉串(10串)", "烤串", 2500), ("牛肉串(10串)", "烤串", 2800),
            ("烤鸡翅(2只)", "烤串", 1200), ("烤韭菜(5串)", "素菜", 600),
            ("烤茄子", "素菜", 900), ("冰镇酸奶", "饮品", 600),
        ],
        "reviews": [
            (5, "炭火味很正,送到还是烫的"),
            (4, "鸡翅烤得刚好,韭菜稍咸"),
            (5, "夜宵就靠这家续命"),
        ],
        "orders_30d": 52,
    },
    {
        "phone": "13800000011", "owner": "刘嬢", "name": "刘嬢家常川菜",
        "category": "sichuan_hunan",
        "description": "家常口味,回锅肉是招牌", "address": "东风路 45 号",
        "lat": 30.6580, "lng": 104.0801,
        "announcement": "两荤一素工作餐 22 元,免配送费",
        "dishes": [
            ("回锅肉", "招牌", 2600), ("麻婆豆腐", "招牌", 1600),
            ("鱼香肉丝", "热菜", 2200), ("干煸四季豆", "热菜", 1500),
            ("番茄蛋汤", "汤", 800), ("米饭", "主食", 200),
        ],
        "reviews": [
            (5, "回锅肉灯盏窝,地道"),
            (5, "分量大,两个人一份回锅肉一份素菜够了"),
            (4, "好吃,微辣对外地朋友也友好"),
        ],
        "orders_30d": 44,
    },
    {
        "phone": "13800000012", "owner": "早点王", "name": "王记包子铺",
        "category": "baozi_congee",
        "description": "凌晨四点发面,豆浆现磨", "address": "春熙路步行街 3 号",
        "lat": 30.6615, "lng": 104.0830,
        "announcement": "早市 6:00-10:30,包子卖完即止",
        "dishes": [
            ("鲜肉大包(2个)", "包子", 600), ("酱肉包(2个)", "包子", 700),
            ("素三鲜包(2个)", "包子", 500), ("现磨豆浆", "饮品", 300),
            ("皮蛋瘦肉粥", "粥", 800), ("茶叶蛋", "小食", 250),
        ],
        "reviews": [
            (5, "包子皮暄软,馅料实在"),
            (5, "豆浆是真现磨的,有豆香"),
            (4, "粥不错,就是高峰期要等一会"),
        ],
        "orders_30d": 57,
    },
    {
        "phone": "13800000014", "owner": "阿凯", "name": "凯记猪脚饭",
        "category": "fast_food",
        "description": "老卤慢炖四小时,饭管够", "address": "青年路 19 号",
        "lat": 30.6570, "lng": 104.0845,
        "announcement": "猪脚饭加饭不要钱,干饭人放心点",
        "dishes": [
            ("招牌猪脚饭", "招牌", 1800), ("卤肉饭", "招牌", 1500),
            ("隆江猪脚饭(大份)", "招牌", 2200), ("卤蛋", "加料", 300),
            ("酸菜", "加料", 200), ("例汤", "汤", 400),
        ],
        "reviews": [
            (5, "猪脚软糯不腻,卤汁拌饭绝了"),
            (5, "加饭真的不要钱,老板实在"),
            (4, "好吃,就是高峰期出餐慢点"),
        ],
        "orders_30d": 49,
    },
]

# 团购券(挂在上面演示店上;phone -> 券定义)
VOUCHERS = {
    "13800000006": [
        ("50元代金券", "全场通用,到店/外带均可核销", 4500, 5000, 200),
        ("100元代金券", "全场通用,聚餐更划算", 8800, 10000, 100),
    ],
    "13800000009": [
        ("80元烤串代金券", "晚市可用,节假日通用", 6900, 8000, 150),
    ],
    "13800000011": [
        ("60元代金券", "家常川菜全场通用", 5200, 6000, 150),
    ],
}

# 演示酒店:2 个房型 + 未来 45 天房态
HOTEL = {
    "phone": "13800000013", "owner": "何店长", "name": "锦里舒心酒店",
    "description": "地铁口 200 米,免费停车,24 小时前台",
    "address": "锦里东路 66 号", "lat": 30.6588, "lng": 104.0790,
    "tier": "comfort",
    "facilities": ["wifi", "parking", "breakfast", "luggage"],
    "rooms": [
        ("高级大床房", "1.8m 大床", 22, 2, 18800, 3),
        ("舒适双床房", "1.2m 双床", 26, 3, 21800, 2),
    ],
}


async def main():
    async with SessionLocal() as db:
        # 0) 张记面馆:把测试期的 1px 图换成正经演示图
        zhang_owner = await db.scalar(
            select(User).where(User.phone == "13800000002")
        )
        zhang = await db.scalar(
            select(Merchant).where(Merchant.owner_id == zhang_owner.id)
        )
        if zhang is not None:
            zhang.logo_url = make_image("logo_zhang", 2)
            dishes = (
                await db.scalars(select(Dish).where(
                    Dish.merchant_id == zhang.id, Dish.is_on_sale.is_(True)))
            ).all()
            for i, d in enumerate(dishes):
                d.image_url = make_image(f"dish_zhang_{i}", i)
            print(f"张记面馆图片已修复({len(dishes)} 道菜)")

        # 1) 隐藏测试残留店铺(不删,避免外键麻烦;下架+驳回后用户端不可见)
        result = await db.execute(
            update(Merchant)
            .where(Merchant.name == "王记火锅")
            .values(is_open=False, status=MerchantStatus.rejected,
                    reject_reason="测试数据,已隐藏")
        )
        print(f"已隐藏测试店铺 {result.rowcount} 家")

        customer = await db.scalar(
            select(User).where(User.phone == "13800000001")
        )

        for shop_def in SHOPS:
            owner = await db.scalar(
                select(User).where(User.phone == shop_def["phone"])
            )
            if owner is None:
                owner = User(
                    phone=shop_def["phone"], name=shop_def["owner"],
                    role=UserRole.merchant,
                    password_hash=hash_password("123456"),
                )
                db.add(owner)
                await db.flush()

            shop = await db.scalar(
                select(Merchant).where(Merchant.owner_id == owner.id)
            )
            if shop is not None:
                print(f"「{shop_def['name']}」已存在,跳过")
                continue

            slug = shop_def["phone"][-4:]
            shop = Merchant(
                owner_id=owner.id,
                name=shop_def["name"],
                description=shop_def["description"],
                address=shop_def["address"],
                lat=shop_def["lat"], lng=shop_def["lng"],
                is_open=True,
                status=MerchantStatus.approved,
                category=shop_def.get("category", "fast_food"),
                license_no=f"JY151010009{slug}",
                announcement=shop_def["announcement"],
                logo_url=make_image(f"logo_{slug}", int(slug) % len(PALETTES)),
            )
            db.add(shop)
            await db.flush()

            dishes = []
            for i, (dname, cat, price) in enumerate(shop_def["dishes"]):
                dish = Dish(
                    merchant_id=shop.id, name=dname, category=cat,
                    price_cents=price, stock=100,
                    image_url=make_image(f"dish_{slug}_{i}", i),
                )
                db.add(dish)
                dishes.append(dish)
            await db.flush()

            # 2) 近 30 天完成订单(撑月售;演示数据不挂骑手,不影响真实骑手钱包)
            now = datetime.now(timezone.utc)
            orders = []
            for n in range(shop_def["orders_30d"]):
                dish = random.choice(dishes)
                qty = random.randint(1, 2)
                food = dish.price_cents * qty
                fee = 300
                commission = int(food * 0.05)
                created = now - timedelta(
                    days=random.uniform(0, 29), minutes=random.uniform(0, 600)
                )
                order = Order(
                    order_no=f"demo{slug}{n:04d}" + "0" * 8,
                    customer_id=customer.id,
                    merchant_id=shop.id,
                    rider_id=None,
                    status=OrderStatus.COMPLETED,
                    items=[{"dish_id": dish.id, "name": dish.name,
                            "price_cents": dish.price_cents, "quantity": qty}],
                    food_cents=food, delivery_fee_cents=fee,
                    total_cents=food + fee, commission_cents=commission,
                    address="演示订单", lat=shop.lat, lng=shop.lng,
                    created_at=created,
                )
                db.add(order)
                orders.append((order, food, commission, created))
            await db.flush()

            # 商家账本同步(对账页数据一致)
            for order, food, commission, created in orders:
                db.add(MerchantEarning(
                    merchant_id=shop.id, order_id=order.id,
                    order_no=order.order_no, food_cents=food,
                    commission_cents=commission, net_cents=food - commission,
                    created_at=created,
                ))
                db.add(OrderEvent(
                    order_id=order.id, from_status="delivered",
                    to_status="completed", actor_role="system",
                    created_at=created,
                ))

            # 3) 评价(挂在前几笔订单上)+ 评分聚合
            rating_sum = 0
            for i, (stars, comment) in enumerate(shop_def["reviews"]):
                order = orders[i][0]
                db.add(Review(
                    order_id=order.id, customer_id=customer.id,
                    merchant_id=shop.id, rider_id=None,
                    merchant_rating=stars, comment=comment,
                    created_at=orders[i][3],
                ))
                rating_sum += stars
            shop.rating_sum = rating_sum
            shop.rating_count = len(shop_def["reviews"])

            print(f"「{shop_def['name']}」创建完成:"
                  f"{len(dishes)} 道菜 / 月售 {shop_def['orders_30d']} / "
                  f"评分 {rating_sum / len(shop_def['reviews']):.1f}")

        # 4) 团购券(商店审核:已上线功能要有可浏览可下单的数据)
        for phone, deals in VOUCHERS.items():
            owner = await db.scalar(select(User).where(User.phone == phone))
            if owner is None:
                continue
            shop = await db.scalar(
                select(Merchant).where(Merchant.owner_id == owner.id))
            if shop is None:
                continue
            for title, desc, sell, face, total in deals:
                exists = await db.scalar(select(Voucher).where(
                    Voucher.merchant_id == shop.id, Voucher.title == title))
                if exists is not None:
                    continue
                db.add(Voucher(
                    merchant_id=shop.id, title=title, description=desc,
                    sell_price_cents=sell, face_value_cents=face,
                    total_count=total, per_user_limit=5, valid_days=90,
                ))
                print(f"「{shop.name}」上架团购券:{title}")

        # 5) 演示酒店:2 房型 + 未来 45 天房态
        hotel_owner = await db.scalar(
            select(User).where(User.phone == HOTEL["phone"]))
        if hotel_owner is None:
            hotel_owner = User(
                phone=HOTEL["phone"], name=HOTEL["owner"],
                role=UserRole.merchant,
                password_hash=hash_password("123456"),
            )
            db.add(hotel_owner)
            await db.flush()
        hotel = await db.scalar(
            select(Merchant).where(Merchant.owner_id == hotel_owner.id))
        if hotel is None:
            hotel = Merchant(
                owner_id=hotel_owner.id,
                name=HOTEL["name"],
                description=HOTEL["description"],
                address=HOTEL["address"],
                lat=HOTEL["lat"], lng=HOTEL["lng"],
                is_open=True,
                status=MerchantStatus.approved,
                biz_type="hotel",
                license_no="91510100MA6DEMO01X",
                logo_url=make_image("logo_hotel", 1),
                photo_urls=[make_image(f"hotel_photo_{i}", i) for i in range(3)],
            )
            db.add(hotel)
            await db.flush()
            db.add(HotelProfile(
                merchant_id=hotel.id, tier=HOTEL["tier"],
                front_desk_phone=HOTEL["phone"],
                facilities=HOTEL["facilities"],
                special_license_no="川公旅DEMO001",
                special_license_image_url=make_image("hotel_license", 0),
            ))
            today = datetime.now(timezone.utc).date()
            for r, (rname, bed, area, guests, price, qty) in enumerate(
                    HOTEL["rooms"]):
                room = RoomType(
                    merchant_id=hotel.id, name=rname, bed_type=bed,
                    area_m2=area, max_guests=guests,
                    image_urls=[make_image(f"room_{r}_{i}", r + i)
                                for i in range(2)],
                    facilities=["wifi", "hot_water"],
                    sort=r,
                )
                db.add(room)
                await db.flush()
                for n in range(45):
                    db.add(RoomCalendar(
                        room_type_id=room.id,
                        date=today + timedelta(days=n),
                        price_cents=price + (2000 if n % 7 in (4, 5) else 0),
                        total_qty=qty,
                    ))
            print(f"「{HOTEL['name']}」创建完成:"
                  f"{len(HOTEL['rooms'])} 个房型 / 45 天房态")
        else:
            print(f"「{HOTEL['name']}」已存在,跳过")

        await db.commit()
    print("\n演示数据集就绪 🎉(重复运行安全)")


if __name__ == "__main__":
    asyncio.run(main())
