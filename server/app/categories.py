"""商家品类白名单(前后端共用口径,客户端在 packages/shared 有同名清单)。

品类是展示归类不是资质项:商家入驻必选、随时可改、管理员可纠错。
新增品类只改这里(和客户端清单),接口校验自动生效。

## 按业态分组,但 key 全局唯一

零售(超市/水果店)的品类和餐饮是两套,不能混在一张表里 ——
一家水果店选不到"川湘菜",一家快餐店也选不到"母婴玩具"。

但 `Merchant.category` 是**一列**,所以 key 必须全局唯一:
`snacks` 在餐饮里已经是「特色小吃」,零售的「休闲零食」就得叫
`casual_snacks`。key 撞车的话,光看这一列分不出是哪个业态的哪个品类,
而 `biz_type` 是另一列 —— 靠两列联合才能解释一个值,是自找的麻烦。
下面的 `_assert_unique()` 在导入时就把这条钉死。
"""

#: 餐饮品类。
FOOD_CATEGORIES: dict[str, str] = {
    "premium_dining": "品质正餐",
    "drinks_dessert": "饮品甜点",
    "fast_food": "快餐便当",       # 存量商家默认归此
    "light_salad": "轻食沙拉",
    "burger_pizza": "汉堡披萨",
    "noodles": "米粉面馆",
    "bbq_fried": "烤串炸鸡",
    "braised_duck": "卤味鸭脖",
    "baozi_congee": "包子粥店",
    "dumplings": "饺子馄饨",
    "malatang": "麻辣烫冒菜",
    "sichuan_hunan": "川湘菜",
    "regional": "地方菜系",
    "snacks": "特色小吃",
    "western": "西餐",
    "wraps": "夹馍饼类",
    "japan_korea": "日韩料理",
    "dry_pot": "香锅干锅",
    "hotpot_skewers": "火锅串串",
    "crayfish_bbq": "龙虾烧烤",
    "beef_lamb_soup": "牛羊肉汤",
    "southeast_asia": "东南亚菜",
    "pastry": "糕点甜点",
}

#: 零售品类(超市 / 水果店 / 便利店)。照美团闪购的分法拟的。
#:
#: **key 不与餐饮重名**:休闲零食是 casual_snacks 不是 snacks
#: (后者已被「特色小吃」占用),酒水饮料是 drinks_alcohol 不是
#: drinks_dessert(后者是「饮品甜点」)。理由见模块抬头。
RETAIL_CATEGORIES: dict[str, str] = {
    "supermarket": "超市便利",     # 零售存量商家默认归此
    "fresh_produce": "生鲜果蔬",
    "casual_snacks": "休闲零食",
    "drinks_alcohol": "酒水饮料",
    "daily_goods": "日用百货",
    "beauty_care": "美妆个护",
    "mom_baby": "母婴玩具",
    "flowers_plants": "鲜花绿植",
    "pet_supplies": "宠物用品",
    "digital_home": "数码家电",
}

#: 业态 → 该业态可选的品类。入驻和改店铺设置时按这个给选项。
#: 住宿不在这里 —— 酒店的档次在 hotel_profiles.tier,不走品类。
CATEGORIES_BY_BIZ: dict[str, dict[str, str]] = {
    "food": FOOD_CATEGORIES,
    "retail": RETAIL_CATEGORIES,
}

#: 全部品类的合并视图。**只用于「把 key 翻译成中文」这类不关心业态的场合**;
#: 校验一律走 CATEGORIES_BY_BIZ,否则水果店能选「川湘菜」
MERCHANT_CATEGORIES: dict[str, str] = {**FOOD_CATEGORIES, **RETAIL_CATEGORIES}

#: 各业态的默认品类(存量商家、以及入驻时没选的兜底)
DEFAULT_CATEGORY_BY_BIZ: dict[str, str] = {
    "food": "fast_food",
    "retail": "supermarket",
}

DEFAULT_CATEGORY = "fast_food"


def _assert_unique() -> None:
    """key 撞车在导入时就炸掉,不要等到线上出现一个解释不了的品类值。"""
    dup = set(FOOD_CATEGORIES) & set(RETAIL_CATEGORIES)
    if dup:
        raise RuntimeError(f"品类 key 在餐饮与零售之间重名:{sorted(dup)}")


_assert_unique()


def categories_of(biz_type: str) -> dict[str, str]:
    """这个业态可选的品类。未知业态给空 —— 不猜、不兜底到餐饮。"""
    return CATEGORIES_BY_BIZ.get(biz_type, {})
