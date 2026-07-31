"""演示环境整备:隐藏测试残留店铺,创建一批像样的演示店。

- 外卖店 13 家(品类各异,撑满首页两屏):门头图、6-7 道带图菜品
  (纯 Python 生成的暖色渐变图,真实照片后续替换)
- 近 30 天的已完成订单(撑起「月售」)+ 真实评价(撑起评分)
- 团购券 10 张、演示酒店 3 家(经济/舒适/高档,房型 + 未来 45 天房态)
- 幂等:重复运行不会重复创建;清老数据用 scripts/scrub_demo.py

用法(在 server/ 目录):python -m scripts.demo_seed
"""
import asyncio
import random
import struct
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update

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


def _put_public(key: str, data: bytes) -> str:
    """写进公开存储并返回可访问地址。

    走 storage 而不是直接写 uploads/:生产的后端是 MinIO,
    往本地目录写文件在那边根本不会被读到 —— 而 seed 恰恰是
    「本地跑得通、线上一片灰」最容易发生的地方。
    """
    from app.services import storage

    if not storage.backend().exists(key, private=False):
        storage.backend().put(data, key, private=False)
    return f"/img/{key}"


def _put_private(key: str, data: bytes) -> str:
    from app.services import storage

    if not storage.backend().exists(key, private=True):
        storage.backend().put(data, key, private=True)
    return f"/files/{key}"


def _gradient_png(idx: int) -> bytes:
    """纯色渐变块的字节。只给没有真实照片的位置兜底。"""
    import tempfile

    top, bottom = PALETTES[idx % len(PALETTES)]
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = Path(f.name)
    try:
        _png(tmp, 400, 300, top, bottom)
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


def make_image(name: str, idx: int) -> str:
    """兜底色块(公开类:房型等)。"""
    return _put_public(f"demo/{name}.png", _gradient_png(idx))


def make_private_image(name: str, idx: int) -> str:
    """兜底色块(私密类:证照)。

    演示证照也走私密桶 —— 演示数据和真实数据在**存储策略**上必须一致,
    否则 e2e 和迁移对账会得到一个"看起来没问题"的假象。
    """
    return _put_private(f"demo/{name}.png", _gradient_png(idx))


# ---- 演示用真实照片(scripts/fetch_demo_photos.py 抓的 Commons PD/CC0 图) ----
#
# 只用于演示数据。真实商家没传图时**绝不能**套用这些:
# 给一家店配一张不属于它的诱人照片,是平台替商家做虚假宣传,
# 与「不杀熟、不虚标」的立场直接冲突。真实商家缺图走客户端的品类占位图。
# 图存在 seed_assets(进 git、随部署同步),seed 时灌进公开存储。
_ASSET_DIR = Path(__file__).resolve().parent.parent / "seed_assets" / "demo_photos"
_PHOTOS: dict[str, list[str]] = {}
try:
    import json as _json

    _manifest = _ASSET_DIR / "manifest.json"
    if _manifest.exists():
        for _cat, _items in _json.loads(_manifest.read_text()).items():
            _files = [e["file"] for e in _items
                      if (_ASSET_DIR / e["file"]).exists()]
            if _files:
                _PHOTOS[_cat] = _files
except Exception:  # 图没抓过就整体退回色块,不影响 seed 跑通
    _PHOTOS = {}


def category_photo(category: str, idx: int, fallback_name: str) -> str:
    """按品类取一张真实照片;该品类没图就回退成色块。

    idx 用来在同品类的几张里轮换。传店铺 id 而不是常数 0 ——
    否则同品类的每家店都取到同一张,列表里一排一模一样的图,比色块还假。
    """
    pool = _PHOTOS.get(category or "")
    if not pool:
        return make_image(fallback_name, idx)
    name = pool[idx % len(pool)]
    return _put_public(f"demo/photos/{name}", (_ASSET_DIR / name).read_bytes())


SHOPS = [
    {
        "phone": "13800000002", "owner": "张老板", "name": "张记面馆",
        "category": "noodles",
        "description": "手工碱水面,汤头每天现吊", "address": "东风路 2 号",
        "lat": 30.6612, "lng": 104.0823,
        "announcement": "每天限量 200 碗,汤头卖完就收摊",
        "dishes": [
            ("招牌牛肉面", "招牌", 1800), ("肥肠面", "招牌", 2000),
            ("素椒杂酱面", "面", 1300), ("清汤抄手(12个)", "抄手", 1400),
            ("红油抄手(12个)", "抄手", 1500), ("拌鸡丝", "凉菜", 1200),
            ("卤蛋", "加料", 300),
        ],
        "reviews": [
            (5, "牛肉给得多,面条筋道"),
            (5, "肥肠处理得很干净,无异味"),
            (4, "好吃,辣度可以再问一下顾客"),
            (5, "老板实在,汤都是现吊的"),
        ],
        "orders_30d": 68,
    },
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
    {
        "phone": "13800000015", "owner": "赵师傅", "name": "赵记冒菜",
        "category": "dry_pot",
        "description": "牛油锅底,冒菜论斤称", "address": "东风路 28 号",
        "lat": 30.6625, "lng": 104.0812,
        "announcement": "锅底每天一换,素菜 6 元一份不玩秤",
        "dishes": [
            ("冒牛肉(半斤)", "荤菜", 2800), ("冒毛肚", "荤菜", 2600),
            ("冒鸭血", "荤菜", 1200), ("冒土豆", "素菜", 600),
            ("冒藕片", "素菜", 600), ("冒豆皮", "素菜", 600),
            ("米饭", "主食", 200),
        ],
        "reviews": [
            (5, "牛油味正,和店里堂食一个味"),
            (5, "分量称得足,不玩虚的"),
            (4, "微辣也挺辣,不能吃辣的注意"),
            (5, "鸭血嫩,土豆粉糯"),
        ],
        "orders_30d": 55,
    },
    {
        "phone": "13800000016", "owner": "金姐", "name": "金家紫菜包饭",
        "category": "japan_korea",
        "description": "现卷现切,泡菜自家腌", "address": "春熙路步行街 52 号",
        "lat": 30.6598, "lng": 104.0835,
        "announcement": "包饭现点现卷,放凉了不好吃请尽快享用",
        "dishes": [
            ("经典紫菜包饭", "包饭", 1200), ("金枪鱼包饭", "包饭", 1600),
            ("辣白菜五花肉拌饭", "拌饭", 1900), ("部队火锅(单人)", "锅物", 2600),
            ("海带汤", "汤", 600), ("自制辣白菜", "小菜", 500),
        ],
        "reviews": [
            (5, "泡菜是真自己腌的,脆"),
            (4, "拌饭酱给得足,饭稍软"),
            (5, "部队火锅料很实在"),
        ],
        "orders_30d": 41,
    },
    {
        "phone": "13800000017", "owner": "大牛", "name": "大牛汉堡",
        "category": "burger_pizza",
        "description": "现打牛肉饼,不用冷冻饼", "address": "青年路 6 号",
        "lat": 30.6640, "lng": 104.0820,
        "announcement": "牛肉饼每日现打现煎,出餐 12 分钟请耐心",
        "dishes": [
            ("经典牛肉堡", "汉堡", 2200), ("双层芝士牛堡", "汉堡", 2800),
            ("脆鸡腿堡", "汉堡", 1800), ("现炸薯条", "小食", 900),
            ("洋葱圈", "小食", 1000), ("可乐(大杯)", "饮品", 600),
        ],
        "reviews": [
            (5, "肉饼有颗粒感,一吃就是现打的"),
            (5, "薯条到手还是脆的,袋子设计用心了"),
            (4, "好吃但等得稍久,毕竟现做"),
        ],
        "orders_30d": 47,
    },
    {
        "phone": "13800000018", "owner": "周孃", "name": "周孃卤味",
        "category": "braised_duck",
        "description": "老卤三十年,每天新起", "address": "东风路 55 号",
        "lat": 30.6575, "lng": 104.0830,
        "announcement": "下午四点出锅,卤味售完即止",
        "dishes": [
            ("卤鸭脖(半斤)", "卤味", 1500), ("卤鸭翅(4个)", "卤味", 1400),
            ("卤豆干", "卤味", 800), ("卤藕片", "卤味", 900),
            ("麻辣兔头(2个)", "招牌", 2200), ("卤鸡爪(6个)", "卤味", 1300),
        ],
        "reviews": [
            (5, "兔头麻辣入味,啃得停不下来"),
            (5, "鸭脖不柴,卤香够"),
            (4, "豆干稍咸,下酒正好"),
        ],
        "orders_30d": 39,
    },
    {
        "phone": "13800000019", "owner": "小轻", "name": "轻食研究所",
        "category": "light_salad",
        "description": "当日食材,酱汁分装", "address": "春熙路步行街 60 号",
        "lat": 30.6608, "lng": 104.0840,
        "announcement": "沙拉酱汁全部分装,自己控制热量",
        "dishes": [
            ("鸡胸肉能量碗", "主食沙拉", 2400), ("牛油果藜麦碗", "主食沙拉", 2600),
            ("烟熏三文鱼沙拉", "主食沙拉", 2900), ("低脂鸡肉卷", "卷类", 1800),
            ("鲜榨橙汁", "饮品", 1200), ("希腊酸奶杯", "甜品", 1000),
        ],
        "reviews": [
            (5, "鸡胸肉不柴,健身餐靠它了"),
            (5, "食材新鲜,牛油果给了整半个"),
            (4, "好吃,就是对干饭人来说量小"),
        ],
        "orders_30d": 36,
    },
    {
        "phone": "13800000021", "owner": "马老板", "name": "马记牛肉汤",
        "category": "beef_lamb_soup",
        "description": "牛骨熬汤六小时,清真", "address": "青年路 33 号",
        "lat": 30.6560, "lng": 104.0808,
        "announcement": "汤免费续,饼子现烙",
        "dishes": [
            ("招牌牛肉汤", "汤", 1600), ("牛杂汤", "汤", 1500),
            ("羊肉汤", "汤", 1800), ("现烙饼子", "主食", 300),
            ("凉拌牛肉", "凉菜", 2600), ("糖蒜", "小菜", 200),
        ],
        "reviews": [
            (5, "汤是真熬出来的,奶白色"),
            (5, "牛肉给得厚道,饼子香"),
            (5, "冬天来一碗,从头暖到脚"),
            (4, "好喝,香菜记得备注多放"),
        ],
        "orders_30d": 51,
    },
    {
        "phone": "13800000022", "owner": "甜甜", "name": "甜言蜜语甜品",
        "category": "pastry",
        "description": "低糖配方,当日现做", "address": "春熙路步行街 71 号",
        "lat": 30.6618, "lng": 104.0845,
        "announcement": "全线低糖配方,好吃不齁",
        "dishes": [
            ("提拉米苏(盒)", "蛋糕", 1800), ("巴斯克芝士(块)", "蛋糕", 1600),
            ("杨枝甘露千层", "千层", 2200), ("蛋挞(2个)", "挞类", 800),
            ("冰醪糟汤圆", "中式", 900), ("红糖冰粉", "中式", 700),
        ],
        "reviews": [
            (5, "低糖是真的,吃完不腻"),
            (5, "千层皮薄,芒果新鲜"),
            (4, "冰粉料足,就是冰化得快"),
        ],
        "orders_30d": 44,
    },
]

# 团购券(挂在上面演示店上;phone -> 券定义)
VOUCHERS = {
    "13800000002": [
        ("20元面食代金券", "全场面食通用,堂食外带均可", 1800, 2000, 200),
    ],
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
    "13800000015": [
        ("50元冒菜代金券", "全场通用,节假日不加价", 4300, 5000, 150),
    ],
    "13800000017": [
        ("30元汉堡代金券", "全场通用,现打牛肉饼", 2600, 3000, 150),
        ("双人套餐券(两堡两小食两饮)", "指定套餐,超值拼单", 5800, 7200, 80),
    ],
    "13800000021": [
        ("40元代金券", "牛肉汤全场通用,汤免费续", 3500, 4000, 120),
    ],
    "13800000022": [
        ("25元甜品代金券", "全场低糖甜品通用", 2100, 2500, 150),
    ],
}

# 演示酒店:每家 2-3 个房型 + 未来 45 天房态
HOTELS = [
    {
        "phone": "13800000013", "owner": "何店长", "name": "锦里舒心酒店",
        "description": "地铁口 200 米,免费停车,24 小时前台",
        "address": "锦里东路 66 号", "lat": 30.6588, "lng": 104.0790,
        "tier": "comfort",
        "facilities": ["wifi", "parking", "breakfast", "luggage"],
        "rooms": [
            ("高级大床房", "1.8m 大床", 22, 2, 18800, 3),
            ("舒适双床房", "1.2m 双床", 26, 3, 21800, 2),
            ("亲子家庭房", "1.8m+1.2m", 32, 4, 26800, 2),
        ],
    },
    {
        "phone": "13800000023", "owner": "程掌柜", "name": "青旅小筑",
        "description": "青年旅舍,公共厨房与桌游区,近夜市",
        "address": "青年路 88 号", "lat": 30.6635, "lng": 104.0850,
        "tier": "economy",
        "facilities": ["wifi", "luggage"],
        "rooms": [
            ("标准大床房", "1.5m 大床", 16, 2, 9800, 4),
            ("经济双床房", "1.2m 双床", 18, 2, 11800, 3),
        ],
    },
    {
        "phone": "13800000024", "owner": "杜经理", "name": "望江雅居酒店",
        "description": "江景房,含双早,健身房与自助洗衣",
        "address": "望江路 9 号", "lat": 30.6550, "lng": 104.0870,
        "tier": "premium",
        "facilities": ["wifi", "parking", "breakfast", "gym", "laundry"],
        "rooms": [
            ("江景大床房", "2.0m 大床", 36, 2, 42800, 3),
            ("行政双床房", "1.5m 双床", 38, 3, 46800, 2),
            ("江景套房", "2.0m 大床+客厅", 52, 3, 68800, 1),
        ],
    },
]


async def _fill_history(db, shop, shop_def, dishes, customer, slug):
    """给一家店补近 30 天的已完成订单、商家账本与评价。

    抽成函数是因为**两条路径都要用它**:新建的演示店,以及
    「已经存在但一单都没有」的店(scripts/seed.py 建的张记面馆就是后者)。
    原先这段只长在新建分支里,于是全新部署的门面店月售恒为 0。
    """
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
    return len(orders)


async def main():
    async with SessionLocal() as db:
        # 0) 张记面馆:把测试期的 1px 图换成正经演示图(生产库可能没有,跳过)
        zhang_owner = await db.scalar(
            select(User).where(User.phone == "13800000002")
        )
        zhang = None if zhang_owner is None else await db.scalar(
            select(Merchant).where(Merchant.owner_id == zhang_owner.id)
        )
        if zhang is not None:
            zhang.logo_url = category_photo("noodles", 0, "logo_zhang")
            dishes = (
                await db.scalars(select(Dish).where(
                    Dish.merchant_id == zhang.id, Dish.is_on_sale.is_(True)))
            ).all()
            for i, d in enumerate(dishes):
                d.image_url = category_photo("noodles", i + 1,
                                             f"dish_zhang_{i}")
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
            select(User).where(
                User.phone == "13800000001", User.role == UserRole.customer)
        )
        if customer is None:
            # 演示顾客(审核测试账号同号):生产库首次跑时创建
            customer = User(
                phone="13800000001", name="演示顾客",
                role=UserRole.customer,
                password_hash=hash_password("123456"),
            )
            db.add(customer)
            await db.flush()

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

            # 幂等按「老板 或 店名」查重:老库的演示店老板手机号可能对不上,
            # 只查老板会重建同名店并撞 demo 单号
            shop = await db.scalar(
                select(Merchant).where(Merchant.owner_id == owner.id)
            ) or await db.scalar(
                select(Merchant).where(Merchant.name == shop_def["name"])
            )
            slug = shop_def["phone"][-4:]

            if shop is not None:
                # 已存在**且已有历史单** → 真的没事可做。
                #
                # 但「存在却一单都没有」是有的:张记面馆由 scripts/seed.py 建,
                # 走不到下面的造单分支,于是**全新部署里门面店月售是 0** ——
                # 用户看到的是一家没人点过的店,e2e 的 monthly_sales 断言也挂。
                # 老开发库因为跑过上百次 e2e 攒出了单子,恰好盖住了这个洞。
                n_orders = await db.scalar(
                    select(func.count()).select_from(Order)
                    .where(Order.merchant_id == shop.id))
                if n_orders:
                    print(f"「{shop_def['name']}」已存在,跳过")
                    continue
                dishes = list(await db.scalars(
                    select(Dish).where(Dish.merchant_id == shop.id,
                                       Dish.is_on_sale.is_(True))))
                if not dishes:
                    print(f"「{shop_def['name']}」已存在但没有在售菜品,跳过")
                    continue
                print(f"「{shop_def['name']}」已存在但没有历史单,补月售")
                await _fill_history(db, shop, shop_def, dishes, customer, slug)
                continue

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
                logo_url=category_photo(
                    shop_def.get("category", "fast_food"), int(slug),
                    f"logo_{slug}"),
            )
            db.add(shop)
            await db.flush()

            dishes = []
            for i, (dname, cat, price) in enumerate(shop_def["dishes"]):
                dish = Dish(
                    merchant_id=shop.id, name=dname, category=cat,
                    price_cents=price, stock=100,
                    image_url=category_photo(
                        shop_def.get("category", "fast_food"),
                        int(slug) + i + 1, f"dish_{slug}_{i}"),
                )
                db.add(dish)
                dishes.append(dish)
            await db.flush()

            # 2) 近 30 天完成订单 + 账本 + 评价(与"补月售"分支共用同一段逻辑)
            n_orders = await _fill_history(
                db, shop, shop_def, dishes, customer, slug)

            print(f"「{shop_def['name']}」创建完成:"
                  f"{len(dishes)} 道菜 / 月售 {n_orders} / "
                  f"评分 {shop.rating_sum / shop.rating_count:.1f}")

        # 4) 团购券(商店审核:已上线功能要有可浏览可下单的数据)
        name_by_phone = {s["phone"]: s["name"] for s in SHOPS}
        for phone, deals in VOUCHERS.items():
            owner = await db.scalar(select(User).where(User.phone == phone))
            shop = None
            if owner is not None:
                shop = await db.scalar(
                    select(Merchant).where(Merchant.owner_id == owner.id))
            if shop is None:  # 老库的店老板手机号对不上,按店名兜底
                shop = await db.scalar(select(Merchant).where(
                    Merchant.name == name_by_phone.get(phone, "")))
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

        # 5) 演示酒店:每家 2-3 房型 + 未来 45 天房态
        for h_idx, hotel_def in enumerate(HOTELS):
            hotel_owner = await db.scalar(
                select(User).where(User.phone == hotel_def["phone"]))
            if hotel_owner is None:
                hotel_owner = User(
                    phone=hotel_def["phone"], name=hotel_def["owner"],
                    role=UserRole.merchant,
                    password_hash=hash_password("123456"),
                )
                db.add(hotel_owner)
                await db.flush()
            hotel = await db.scalar(
                select(Merchant).where(Merchant.owner_id == hotel_owner.id)
            ) or await db.scalar(
                select(Merchant).where(Merchant.name == hotel_def["name"]))
            if hotel is not None:
                print(f"「{hotel_def['name']}」已存在,跳过")
                continue
            slug = hotel_def["phone"][-4:]
            hotel = Merchant(
                owner_id=hotel_owner.id,
                name=hotel_def["name"],
                description=hotel_def["description"],
                address=hotel_def["address"],
                lat=hotel_def["lat"], lng=hotel_def["lng"],
                is_open=True,
                status=MerchantStatus.approved,
                biz_type="hotel",
                license_no=f"91510100MA6DM{slug}X",
                logo_url=make_image(f"logo_hotel_{slug}", h_idx + 1),
                photo_urls=[make_image(f"hotel_{slug}_photo_{i}", h_idx + i)
                            for i in range(3)],
            )
            db.add(hotel)
            await db.flush()
            db.add(HotelProfile(
                merchant_id=hotel.id, tier=hotel_def["tier"],
                front_desk_phone=hotel_def["phone"],
                facilities=hotel_def["facilities"],
                special_license_no=f"川公旅DEMO{slug}",
                special_license_image_url=make_private_image(
                    f"hotel_{slug}_license", h_idx),
            ))
            today = datetime.now(timezone.utc).date()
            for r, (rname, bed, area, guests, price, qty) in enumerate(
                    hotel_def["rooms"]):
                room = RoomType(
                    merchant_id=hotel.id, name=rname, bed_type=bed,
                    area_m2=area, max_guests=guests,
                    image_urls=[make_image(f"room_{slug}_{r}_{i}", r + i)
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
                        # 周五周六上浮,像真实房价
                        price_cents=price + (2000 if n % 7 in (4, 5) else 0),
                        total_qty=qty,
                    ))
            print(f"「{hotel_def['name']}」创建完成:"
                  f"{len(hotel_def['rooms'])} 个房型 / 45 天房态")

        # 回填真实照片:已存在的演示商家不会走上面的新建分支,
        # 挂的还是老的色块图。这里按品类补上。
        #
        # **只替换色块图**(/uploads/demo/xxx.png):商家自己传的图绝不能碰。
        # 判据是路径 —— 色块图在 /uploads/demo/ 下且是 .png,
        # 商家上传的落在 /uploads/ 根下且带随机名
        if _PHOTOS:
            filled_m = filled_d = 0
            shops = (await db.scalars(select(Merchant))).all()
            for shop in shops:
                url = shop.logo_url or ""
                is_block = url.startswith("/uploads/demo/") and url.endswith(".png")
                if not url or is_block:
                    new_url = category_photo(
                        shop.category, shop.id, f"logo_m{shop.id}")
                    if new_url != url and "/photos/" in new_url:
                        shop.logo_url = new_url
                        filled_m += 1
                shop_dishes = (await db.scalars(
                    select(Dish).where(Dish.merchant_id == shop.id))).all()
                for i, d in enumerate(shop_dishes):
                    durl = d.image_url or ""
                    d_block = (durl.startswith("/uploads/demo/")
                               and durl.endswith(".png"))
                    if durl and not d_block:
                        continue          # 真实上传的图,不动
                    nd = category_photo(
                        shop.category, shop.id + i + 1, f"dish_m{d.id}")
                    if nd != durl and "/photos/" in nd:
                        d.image_url = nd
                        filled_d += 1
            if filled_m or filled_d:
                print(f"回填真实照片:{filled_m} 家店 / {filled_d} 道菜"
                      f"(只替换色块图,商家自传的图未动)")

        await db.commit()
    print("\n演示数据集就绪 🎉(重复运行安全)")


if __name__ == "__main__":
    asyncio.run(main())
