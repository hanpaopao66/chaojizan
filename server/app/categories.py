"""外卖商家品类白名单(前后端共用口径,客户端在 packages/shared 有同名清单)。

品类是展示归类不是资质项:商家入驻必选、随时可改、管理员可纠错。
新增品类只改这里(和客户端清单),接口校验自动生效。
"""

MERCHANT_CATEGORIES: dict[str, str] = {
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

DEFAULT_CATEGORY = "fast_food"
