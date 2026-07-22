/// 外卖品类清单(与服务端 app/categories.py 同口径,新增品类两边一起改)。
///
/// 品类是展示归类不是资质项:商家入驻必选、店铺设置随时可改。
/// v1 图标用 emoji(零资源成本,风格统一),要换彩绘图标时只改这里。
library;

const Map<String, String> kMerchantCategories = {
  'premium_dining': '品质正餐',
  'drinks_dessert': '饮品甜点',
  'fast_food': '快餐便当',
  'light_salad': '轻食沙拉',
  'burger_pizza': '汉堡披萨',
  'noodles': '米粉面馆',
  'bbq_fried': '烤串炸鸡',
  'braised_duck': '卤味鸭脖',
  'baozi_congee': '包子粥店',
  'dumplings': '饺子馄饨',
  'malatang': '麻辣烫冒菜',
  'sichuan_hunan': '川湘菜',
  'regional': '地方菜系',
  'snacks': '特色小吃',
  'western': '西餐',
  'wraps': '夹馍饼类',
  'japan_korea': '日韩料理',
  'dry_pot': '香锅干锅',
  'hotpot_skewers': '火锅串串',
  'crayfish_bbq': '龙虾烧烤',
  'beef_lamb_soup': '牛羊肉汤',
  'southeast_asia': '东南亚菜',
  'pastry': '糕点甜点',
};

const Map<String, String> kMerchantCategoryEmoji = {
  'premium_dining': '🍽️',
  'drinks_dessert': '🧋',
  'fast_food': '🍱',
  'light_salad': '🥗',
  'burger_pizza': '🍔',
  'noodles': '🍜',
  'bbq_fried': '🍗',
  'braised_duck': '🦆',
  'baozi_congee': '🥣',
  'dumplings': '🥟',
  'malatang': '🍲',
  'sichuan_hunan': '🌶️',
  'regional': '🍛',
  'snacks': '🍡',
  'western': '🥩',
  'wraps': '🌯',
  'japan_korea': '🍣',
  'dry_pot': '🥘',
  'hotpot_skewers': '🍢',
  'crayfish_bbq': '🦞',
  'beef_lamb_soup': '🐑',
  'southeast_asia': '🥥',
  'pastry': '🍰',
};

String merchantCategoryLabel(String slug) =>
    kMerchantCategories[slug] ?? '快餐便当';
