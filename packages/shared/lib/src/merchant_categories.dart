/// 品类清单(与服务端 app/categories.py 同口径,新增品类两边一起改)。
///
/// 品类是展示归类不是资质项:商家入驻必选、店铺设置随时可改。
/// v1 图标用 emoji(零资源成本,风格统一),要换彩绘图标时只改这里。
library;

import 'package:flutter/material.dart';

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

/// 品类符号(缺图占位的底纹用)。emoji 在不同 Android 机型渲染差异很大,
/// 而且和这套观感不搭,所以占位图用 Material 图标——它已经打进包里,
/// 零额外体积。金刚区那些 emoji 保持不动,那是另一个用途。
const Map<String, IconData> kMerchantCategoryIcon = {
  'premium_dining': Icons.restaurant,
  'drinks_dessert': Icons.local_cafe_outlined,
  'fast_food': Icons.lunch_dining,
  'light_salad': Icons.eco_outlined,
  'burger_pizza': Icons.local_pizza_outlined,
  'noodles': Icons.ramen_dining,
  'bbq_fried': Icons.kebab_dining,
  'braised_duck': Icons.set_meal,
  'baozi_congee': Icons.breakfast_dining,
  'dumplings': Icons.dinner_dining,
  'malatang': Icons.soup_kitchen_outlined,
  'sichuan_hunan': Icons.local_fire_department_outlined,
  'regional': Icons.rice_bowl,
  'snacks': Icons.bakery_dining,
  'western': Icons.restaurant_menu,
  'wraps': Icons.flatware,
  'japan_korea': Icons.set_meal_outlined,
  'dry_pot': Icons.outdoor_grill_outlined,
  'hotpot_skewers': Icons.local_fire_department,
  'crayfish_bbq': Icons.outdoor_grill,
  'beef_lamb_soup': Icons.soup_kitchen,
  'southeast_asia': Icons.rice_bowl_outlined,
  'pastry': Icons.cake_outlined,
};

/// 零售品类(超市 / 水果店 / 便利店),与服务端 RETAIL_CATEGORIES 同口径。
///
/// **key 不与餐饮重名**:休闲零食是 casual_snacks 不是 snacks(后者已被
/// 「特色小吃」占用),酒水饮料是 drinks_alcohol 不是 drinks_dessert。
/// 服务端的 categories.py 有同样的说明和一个导入时的守卫 ——
/// merchants.category 只有一列,撞名了就得靠 biz_type 联合才能解释一个值。
const Map<String, String> kRetailCategories = {
  'supermarket': '超市便利',
  'fresh_produce': '生鲜果蔬',
  'casual_snacks': '休闲零食',
  'drinks_alcohol': '酒水饮料',
  'daily_goods': '日用百货',
  'beauty_care': '美妆个护',
  'mom_baby': '母婴玩具',
  'flowers_plants': '鲜花绿植',
  'pet_supplies': '宠物用品',
  'digital_home': '数码家电',
};

const Map<String, IconData> kRetailCategoryIcon = {
  'supermarket': Icons.storefront_outlined,
  'fresh_produce': Icons.eco_outlined,
  'casual_snacks': Icons.cookie_outlined,
  'drinks_alcohol': Icons.local_bar_outlined,
  'daily_goods': Icons.inventory_2_outlined,
  'beauty_care': Icons.face_retouching_natural_outlined,
  'mom_baby': Icons.child_friendly_outlined,
  'flowers_plants': Icons.local_florist_outlined,
  'pet_supplies': Icons.pets_outlined,
  'digital_home': Icons.devices_other_outlined,
};

/// 该业态可选的品类。**按业态取,不要把两张表合起来** ——
/// 合起来意味着一家快餐店的下拉里出现「母婴玩具」。
Map<String, String> categoriesOfBiz(String bizType) => switch (bizType) {
      'food' => kMerchantCategories,
      'retail' => kRetailCategories,
      _ => const {},
    };

/// 取品类符号;未知品类回落到通用餐具(住宿等非餐饮业态调用方自己给)。
IconData merchantCategoryIcon(String? category) =>
    kMerchantCategoryIcon[category] ??
    kRetailCategoryIcon[category] ??
    Icons.restaurant_outlined;
