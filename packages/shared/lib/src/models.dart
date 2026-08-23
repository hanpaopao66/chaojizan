/// 与后端 state_machine.py 一一对应的订单状态。
enum OrderStatus {
  pendingPayment('pending_payment', '待支付'),
  paid('paid', '待接单'),
  accepted('accepted', '制作中'),
  ready('ready', '待取餐'),
  pickedUp('picked_up', '配送中'),
  delivered('delivered', '已送达'),
  completed('completed', '已完成'),
  cancelled('cancelled', '已取消');

  const OrderStatus(this.value, this.label);

  final String value;
  final String label;

  static OrderStatus fromValue(String value) =>
      values.firstWhere((s) => s.value == value, orElse: () => cancelled);
}

/// 评价一键标签白名单(与服务端 schemas 保持一致)。
/// **按责任方分组**:配送是平台的事,配送标签只随骑手评分落库,
/// 从结构上进不了商家维度 —— 锅不该商家背。
const List<String> kReviewTags = [
  '味道好', '分量足', '包装好', '配送快', '干净卫生', '回头客',
];

/// 菜品标签白名单(与服务端 schemas.DISH_BADGES 一致)。
/// 只收商家自述的客观项;**故意不含"平台推荐""热销第一"** ——
/// 那种标签一旦存在,迟早变成可以买的位置,与"没有竞价排名"冲突。
const List<String> kDishBadges = [
  '新品', '招牌', '微辣', '中辣', '特辣', '不辣',
  '含花生', '含香菜', '素食', '儿童友好',
];

/// 忌口/过敏相关:这几个关乎安全,用户端要用醒目色而不是最淡的墨色
const Set<String> kAllergenBadges = {'含花生', '含香菜', '特辣'};

/// 商家侧负向标签(菜品/包装/出餐,商家自己能改的事)
const List<String> kMerchantNegTags = [
  '太咸了', '分量不足', '包装洒漏', '出餐慢', '和图不符',
];

/// 配送侧标签(正负都有;只挂骑手评分)
const List<String> kRiderReviewTags = [
  '送得快', '服务周到', '送得慢', '态度不好', '餐洒了',
];

/// 分 → 元的展示格式。金额在前后端之间永远以「分」传输。
String yuan(int cents) => '¥${(cents / 100).toStringAsFixed(2)}';

class Merchant {
  Merchant.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        name = json['name'] as String,
        description = json['description'] as String? ?? '',
        address = json['address'] as String? ?? '',
        lat = (json['lat'] as num).toDouble(),
        lng = (json['lng'] as num).toDouble(),
        isOpen = json['is_open'] as bool,
        commissionRate =
            double.tryParse(json['commission_rate'].toString()) ?? 0.06,
        status = json['status'] as String? ?? 'approved',
        rejectReason = json['reject_reason'] as String? ?? '',
        ratingAvg = (json['rating_avg'] as num?)?.toDouble(),
        ratingCount = json['rating_count'] as int? ?? 0,
        announcement = json['announcement'] as String? ?? '',
        logoUrl = json['logo_url'] as String? ?? '',
        openTime = json['open_time'] as String? ?? '',
        closeTime = json['close_time'] as String? ?? '',
        monthlySales = json['monthly_sales'] as int? ?? 0,
        promiseReadyMinutes = json['promise_ready_minutes'] as int? ?? 15,
        selfDelivery = json['self_delivery'] as bool? ?? false,
        topDishes = (json['top_dishes'] as List? ?? const [])
            .map((e) => TopDish.fromJson(e as Map<String, dynamic>))
            .toList(),
        minOrderCents = json['min_order_cents'] as int? ?? 0,
        packingFeeCents = json['packing_fee_cents'] as int? ?? 0,
        photoUrls =
            (json['photo_urls'] as List? ?? const []).cast<String>(),
        promoRules = (json['promo_rules'] as List? ?? const [])
            .map((e) => PromoRule.fromJson(e as Map<String, dynamic>))
            .toList(),
        giftRules = (json['gift_rules'] as List? ?? const [])
            .map((e) => GiftRule.fromJson(e as Map<String, dynamic>))
            .toList(),
        closedUntil = json['closed_until'] == null
            ? null
            : DateTime.tryParse(json['closed_until'] as String),
        holidayPlans = (json['holiday_plans'] as List? ?? const [])
            .cast<Map<String, dynamic>>(),
        viewerIsStaff = json['viewer_is_staff'] as bool? ?? false,
        viewerIsOwner = json['viewer_is_owner'] as bool? ?? true,
        licenseStage = json['license_stage'] as String? ?? 'ok',
        licenseExpiresAt = json['license_expires_at'] as String? ?? '',
        licenseDaysLeft = json['license_days_left'] as int?,
        category = json['category'] as String? ?? 'fast_food',
        kitchenCam = json['kitchen_cam'] as bool? ?? false,
        kitchenCamLabel =
            json['kitchen_cam_label'] as String? ?? '无明厨亮灶',
        dineInStatus = json['dine_in_status'] as String? ?? 'unknown',
        dineInLabel = json['dine_in_label'] as String? ?? '未填报',
        bizType = json['biz_type'] as String? ?? 'food',
        autoAccept = json['auto_accept'] as bool? ?? false,
        foodSeal = json['food_seal'] as bool? ?? false,
        foodSafetyHold = json['food_safety_hold'] as bool? ?? false,
        busyActive = json['busy_active'] as bool? ?? false,
        busyUntil = json['busy_until'] as String?,
        busyExtraMinutes = json['busy_extra_minutes'] as int? ?? 10,
        licenseNo = json['license_no'] as String? ?? '',
        licenseImageUrl = json['license_image_url'] as String? ?? '',
        specialLicenseNo = json['special_license_no'] as String? ?? '',
        specialLicenseImageUrl =
            json['special_license_image_url'] as String? ?? '',
        hygieneImageUrl = json['hygiene_image_url'] as String? ?? '';

  final int id;
  final String name;
  final String description;
  final int promiseReadyMinutes; // 承诺出餐时长(分钟)
  final bool selfDelivery;       // 商家自配送(订单不进抢单池,自己送)
  final String address;
  final double lat;
  final double lng;
  final bool isOpen;
  final double commissionRate;

  /// pending / approved / rejected
  final String status;
  final String rejectReason;
  final double? ratingAvg;
  final int ratingCount;
  final String announcement;
  final String logoUrl;
  final String openTime;
  final String closeTime;
  final int monthlySales;
  final List<TopDish> topDishes;
  final int minOrderCents;
  final int packingFeeCents;
  final String category; // 外卖品类 slug(清单见 merchant_categories.dart)

  /// 明厨亮灶(#155)。**列表页展示这两个字段是法定要求**:
  /// 总局令第 123 号第十三条要求平台"根据商家是否实施,在列表页展示
  /// 「无明厨亮灶」「有明厨亮灶」标识" —— 要标的是**两种**,
  /// 所以每家店都有,不是给装了的加徽章。
  ///
  /// 只有服务端判定 active 才是 true:待核验、掉线都算「无」——
  /// 看不到就是没有。
  final bool kitchenCam;
  final String kitchenCamLabel;

  /// 堂食标识(#187,总局令第 123 号第十二条,2026-06-01 施行)。
  /// 列表页和商家主页都要展示,和明厨亮灶一样是**法定公示项**。
  ///
  /// unknown 未填报 / yes 有堂食 / no 无堂食。**未填报就照实显示「未填报」**,
  /// 不要在客户端兜底成「有堂食」—— 猜一个填上等于替商家撒谎。
  /// dineInLabel 是服务端给的现成文案,三端不各写一套映射。
  final String dineInStatus;
  final String dineInLabel;
  final String bizType;  // 业态:food 餐饮外卖 / hotel 酒店住宿(工作台按此分叉)

  /// 自动接单(仅 GET /merchants/me 下发;支付成功即进入制作)
  final bool autoAccept;

  /// 食安封签:商家自述使用一次性封签(**不是平台认证**,文案要照此口径写)
  final bool foodSeal;

  /// 食安停业闸门:置位时商家自己开不回营业(整改复核后由平台解除)
  final bool foodSafetyHold;

  /// 忙碌模式(高峰压单):生效期 ETA/出餐超时判定放宽,用户端亮「出餐较慢」标
  final bool busyActive;
  final String? busyUntil;
  final int busyExtraMinutes;

  /// 本店证照(仅 GET /merchants/me 且店主可见;其余接口为空串)。
  /// 被驳回后重新提交时回填表单 —— 不回填的话商家要把证号照片全部重来一遍
  final String licenseNo;
  final String licenseImageUrl;
  final String specialLicenseNo;       // 酒店:特种行业许可证号
  final String specialLicenseImageUrl; // 酒店:特种行业许可证照片
  final String hygieneImageUrl;        // 酒店:卫生许可证照片(选填)

  /// 门店相册(环境/后厨/证照实拍,最多 9 张)
  final List<String> photoUrls;
  final List<PromoRule> promoRules;
  final List<GiftRule> giftRules;

  /// 临时歇业到此刻(到点自动恢复);null = 未歇业
  final DateTime? closedUntil;

  /// 节假日计划 [{from,to,closed,open,close}](优先级高于每日营业时间)
  final List<Map<String, dynamic>> holidayPlans;

  /// 当前登录者是本店店员(而非店主):客户端据此隐藏提现/改价/子账号入口
  final bool viewerIsStaff;

  /// 当前登录者是这家店登记的经营者本人。
  /// **和 !viewerIsStaff 不是一回事**:连锁的区域经理不是店员(能改价、
  /// 能改设置),但也不是经营者本人 —— 资金动作服务端一律 403。
  /// 老服务端不下发这个字段时默认 true(单店商家的老行为)。
  final bool viewerIsOwner;

  /// 证照档位:unknown 未登记 / ok / soon(≤30天) / urgent(≤7天)
  /// / last(≤1天) / expired(已过期,宽限期内) / overdue(宽限期满,已停业)。
  /// **老服务端不下发时默认 'ok'** —— 默认不出横幅,宁可少提醒也不误报。
  final String licenseStage;
  final String licenseExpiresAt;
  final int? licenseDaysLeft;

  /// 今天生效的节假日计划(没有返回 null)
  Map<String, dynamic>? get todayHolidayPlan {
    final today = DateTime.now().toIso8601String().substring(0, 10);
    for (final p in holidayPlans) {
      final from = p['from'] as String? ?? '';
      final to = (p['to'] as String?)?.isNotEmpty == true
          ? p['to'] as String
          : from;
      if (from.isNotEmpty && from.compareTo(today) <= 0 &&
          today.compareTo(to) <= 0) {
        return p;
      }
    }
    return null;
  }

  String get ratingLabel =>
      ratingCount == 0 ? '暂无评分' : '★ $ratingAvg · $ratingCount 条评价';

  bool get isApproved => status == 'approved';
  bool get isPending => status == 'pending';
  bool get isRejected => status == 'rejected';

  /// 满减标签,如「满30减5」「满50减12」
  List<String> get promoLabels => promoRules
      .map((r) =>
          '满${r.thresholdCents ~/ 100}减${(r.offCents / 100).toStringAsFixed(r.offCents % 100 == 0 ? 0 : 1)}')
      .toList();
}

/// 退款流水(退款进度可视化):一次退款一条。
class RefundRecord {
  RefundRecord.fromJson(Map<String, dynamic> json)
      : amountCents = json['amount_cents'] as int,
        reason = json['reason'] as String? ?? '',
        channel = json['channel'] as String? ?? 'mock',
        status = json['status'] as String? ?? 'requested',
        createdAt = json['created_at'] as String? ?? '';

  final int amountCents;
  final String reason;

  /// mock(开发/演示,即时到账) / wechat(真实原路退回,1-3 个工作日)
  final String channel;

  /// requested(渠道处理中) / success(已到账) / failed(异常,人工介入)
  final String status;
  final String createdAt;
}

/// 平台公告(运营发通知不用发版)。
class PlatformAnnouncement {
  PlatformAnnouncement.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        title = json['title'] as String,
        content = json['content'] as String;

  final int id;
  final String title;
  final String content;
}

/// 列表页招牌菜(名/价/图)。
class TopDish {
  TopDish.fromJson(Map<String, dynamic> json)
      : name = json['name'] as String,
        priceCents = json['price_cents'] as int,
        imageUrl = json['image_url'] as String? ?? '';

  final String name;
  final int priceCents;
  final String imageUrl;
}

/// 商家满减规则(成本商家承担)。
class PromoRule {
  PromoRule({required this.thresholdCents, required this.offCents});

  PromoRule.fromJson(Map<String, dynamic> json)
      : thresholdCents = json['threshold_cents'] as int,
        offCents = json['off_cents'] as int;

  final int thresholdCents;
  final int offCents;

  Map<String, dynamic> toJson() =>
      {'threshold_cents': thresholdCents, 'off_cents': offCents};
}

/// 满赠:满 threshold 赠指定菜一份(满减动钱、满赠动货)。
class GiftRule {
  GiftRule({required this.thresholdCents, required this.dishId, this.name = ''});

  GiftRule.fromJson(Map<String, dynamic> json)
      : thresholdCents = json['threshold_cents'] as int,
        dishId = json['dish_id'] as int,
        name = json['name'] as String? ?? '';

  final int thresholdCents;
  final int dishId;
  final String name;

  Map<String, dynamic> toJson() =>
      {'threshold_cents': thresholdCents, 'dish_id': dishId, 'name': name};
}

class Dish {
  Dish.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        merchantId = json['merchant_id'] as int,
        name = json['name'] as String,
        category = json['category'] as String? ?? '',
        priceCents = json['price_cents'] as int,
        costCents = json['cost_cents'] as int? ?? 0,
        packingFeeCents = json['packing_fee_cents'] as int?,
        stock = json['stock'] as int,
        dailyStock = json['daily_stock'] as int?,
        soldOutToday = json['sold_out_today'] as bool? ?? false,
        isOnSale = json['is_on_sale'] as bool? ?? true,
        isAlcohol = json['is_alcohol'] as bool? ?? false,
        imageUrl = json['image_url'] as String? ?? '',
        sort = json['sort'] as int? ?? 0,
        comboItems = (json['combo_items'] as List? ?? const [])
            .cast<Map<String, dynamic>>(),
        comboDishes = (json['combo_dishes'] as List? ?? const [])
            .cast<Map<String, dynamic>>(),
        comboOriginalCents = json['combo_original_cents'] as int? ?? 0,
        serveWindow = json['serve_window'] as String? ?? '',
        servableNow = json['servable_now'] as bool? ?? true,
        description = json['description'] as String? ?? '',
        badges = (json['badges'] as List? ?? const []).cast<String>(),
        options = (json['options'] as List? ?? const [])
            .map((e) => OptionGroup.fromJson(e as Map<String, dynamic>))
            .toList(),
        flashPriceCents = json['flash_price_cents'] as int?,
        flashUntil = json['flash_until'] == null
            ? null
            : DateTime.tryParse(json['flash_until'] as String),
        monthlySales = json['monthly_sales'] as int? ?? 0;

  final int id;
  final int merchantId;
  final String name;
  final String category;
  final int priceCents;

  /// 成本(分/份),0 = **没录过**(不是成本为零)。
  /// 只有商家自己的接口下发这个字段;用户端菜单里恒为 0。
  final int costCents;

  /// 额外打包费(分/份);null = 用店铺的每单打包费。
  /// **在店铺那笔之外另加**,不是替代。
  final int? packingFeeCents;
  final int stock;

  /// 菜单顺序(小的在前,同值按 id):商家排的顺序,用户端照着看
  final int sort;

  /// 套餐子项 [{dish_id, quantity}];非空 = 这是个套餐
  final List<Map<String, dynamic>> comboItems;

  /// 套餐子项明细 [{name, quantity}](菜单接口填充,给用户看"套餐里有什么")
  final List<Map<String, dynamic>> comboDishes;

  /// 子项单点合计:比套餐价高的那部分就是"省了多少"
  final int comboOriginalCents;

  /// 供应时段 "06:00-10:30"(空 = 全天供应)
  final String serveWindow;

  /// 此刻是否在供应时段内。非供应时段**照常展示**(灰态),
  /// 不从菜单里消失 —— 消失会让用户以为这家店没这道菜
  final bool servableNow;

  bool get isCombo => comboItems.isNotEmpty;

  /// 套餐省了多少(非套餐或没便宜时为 0)
  int get comboSaveCents =>
      isCombo && comboOriginalCents > priceCents
          ? comboOriginalCents - priceCents
          : 0;

  /// 菜品描述(用户点之前想知道这菜里有什么)
  final String description;

  /// 标签角标(白名单 kDishBadges):新品/招牌/辣度/忌口提示
  final List<String> badges;

  /// 每日回满目标(空=未启用):每天 04:00 库存自动重置为该值
  final int? dailyStock;

  /// 估清(今日售罄):灰态展示,区别于下架;次日自动恢复
  final bool soldOutToday;
  final bool isOnSale;

  /// 酒类:「酒」角标,购买需实名且成年,未成年人禁止购买
  final bool isAlcohol;
  final String imageUrl;
  final List<OptionGroup> options;
  final int? flashPriceCents;
  final DateTime? flashUntil;
  final int monthlySales;

  bool get hasOptions => options.isNotEmpty;

  /// 限时折扣是否生效(两者齐 + 未过期)
  bool get flashActive =>
      flashPriceCents != null &&
      flashUntil != null &&
      flashUntil!.isAfter(DateTime.now().toUtc());

  /// 成交单价:折扣生效用折扣价,否则原价(与服务端下单口径一致)
  int get effectivePriceCents =>
      flashActive ? flashPriceCents! : priceCents;
}

/// 菜品规格/加料组(如「份量」单选必选、「加料」多选)。
class OptionGroup {
  OptionGroup({
    required this.name,
    required this.required_,
    required this.multi,
    required this.choices,
  });

  OptionGroup.fromJson(Map<String, dynamic> json)
      : name = json['name'] as String,
        required_ = json['required'] as bool? ?? false,
        multi = json['multi'] as bool? ?? false,
        choices = (json['choices'] as List? ?? const [])
            .map((e) => OptionChoice.fromJson(e as Map<String, dynamic>))
            .toList();

  final String name;
  final bool required_; // required 是 Dart 保留词
  final bool multi;
  final List<OptionChoice> choices;

  Map<String, dynamic> toJson() => {
        'name': name,
        'required': required_,
        'multi': multi,
        'choices': choices.map((c) => c.toJson()).toList(),
      };
}

class OptionChoice {
  OptionChoice({required this.name, required this.deltaCents});

  OptionChoice.fromJson(Map<String, dynamic> json)
      : name = json['name'] as String,
        deltaCents = json['delta_cents'] as int? ?? 0;

  final String name;
  final int deltaCents;

  Map<String, dynamic> toJson() =>
      {'name': name, 'delta_cents': deltaCents};

  String get label =>
      deltaCents > 0 ? '$name +¥${(deltaCents / 100).toStringAsFixed(deltaCents % 100 == 0 ? 0 : 1)}' : name;
}

/// 购物车行:同一菜品不同规格组合是不同的行。
class CartLine {
  CartLine({required this.dish, required this.choices, this.quantity = 1});

  final Dish dish;
  final List<String> choices;
  int quantity;

  /// 单价 = 成交价(含限时折扣) + 选中项加价之和
  int get unitCents {
    var total = dish.effectivePriceCents;
    for (final group in dish.options) {
      for (final c in group.choices) {
        if (choices.contains(c.name)) total += c.deltaCents;
      }
    }
    return total;
  }

  String get label =>
      choices.isEmpty ? dish.name : '${dish.name}(${choices.join('+')})';

  /// 同菜同规格判定(购物车合并用)
  bool sameAs(Dish d, List<String> c) =>
      dish.id == d.id &&
      choices.length == c.length &&
      choices.toSet().containsAll(c);

  Map<String, dynamic> toOrderItem() => {
        'dish_id': dish.id,
        'quantity': quantity,
        'choices': choices,
      };
}


class OrderItem {
  OrderItem.fromJson(Map<String, dynamic> json)
      : dishId = json['dish_id'] as int? ?? 0,
        name = json['name'] as String,
        priceCents = json['price_cents'] as int,
        quantity = json['quantity'] as int,
        isAlcohol = json['is_alcohol'] as bool? ?? false;

  final int dishId;
  final String name;
  final int priceCents;
  final int quantity;
  final bool isAlcohol; // 酒类:小票/骑手端提示查验收件人
}

class Order {
  Order.fromJson(Map<String, dynamic> json)
      : orderNo = json['order_no'] as String,
        merchantId = json['merchant_id'] as int,
        merchantName = json['merchant_name'] as String? ?? '',
        merchantAddress = json['merchant_address'] as String? ?? '',
        merchantLat = (json['merchant_lat'] as num?)?.toDouble(),
        merchantLng = (json['merchant_lng'] as num?)?.toDouble(),
        riderName = json['rider_name'] as String? ?? '',
        riderPhone = json['rider_phone'] as String? ?? '',
        merchantPhone = json['merchant_phone'] as String? ?? '',
        riderId = json['rider_id'] as int?,
        status = OrderStatus.fromValue(json['status'] as String),
        items = (json['items'] as List)
            .map((e) => OrderItem.fromJson(e as Map<String, dynamic>))
            .toList(),
        foodCents = json['food_cents'] as int,
        packingFeeCents = json['packing_fee_cents'] as int? ?? 0,
        discountCents = json['discount_cents'] as int? ?? 0,
        subsidyCents = json['subsidy_cents'] as int? ?? 0,
        promoNote = json['promo_note'] as String? ?? '',
        deliveryFeeCents = json['delivery_fee_cents'] as int,
        tipCents = json['tip_cents'] as int? ?? 0,
        totalCents = json['total_cents'] as int,
        commissionCents = json['commission_cents'] as int? ?? 0,
        address = json['address'] as String,
        lat = (json['lat'] as num).toDouble(),
        lng = (json['lng'] as num).toDouble(),
        contactName = json['contact_name'] as String? ?? '',
        contactPhone = json['contact_phone'] as String? ?? '',
        privacyPhone = json['privacy_phone'] as String? ?? '',
        remark = json['remark'] as String? ?? '',
        cancelReason = json['cancel_reason'] as String? ?? '',
        refundCents = json['refund_cents'] as int? ?? 0,
        refundNote = json['refund_note'] as String? ?? '',
        hasReview = json['has_review'] as bool? ?? false,
        scheduledAt = json['scheduled_at'] as String?,
        etaAt = json['eta_at'] as String?,
        // 到店时刻:骑手端据此决定还要不要显示「我到店了」。
        // 等餐时长 = 取餐 − 到店,是申诉超时时的证据
        arrivedShopAt = json['arrived_shop_at'] as String? ?? '',
        selfDelivery = json['self_delivery'] as bool? ?? false,
        noRiderAlerted = json['no_rider_alerted'] as bool? ?? false,
        acceptedAt = json['accepted_at'] as String?,
        readyLate = json['ready_late'] as bool? ?? false,
        addrProtect = json['addr_protect'] as bool? ?? false,
        addrRevealed = json['addr_revealed'] as bool? ?? false,
        deliveryPhotoUrl = json['delivery_photo_url'] as String? ?? '',
        pickup = json['pickup'] as bool? ?? false,
        pickupCode = json['pickup_code'] as String? ?? '',
        parentOrderNo = json['parent_order_no'] as String? ?? '',
        distanceM = json['distance_m'] as int?,
        tripM = json['trip_m'] as int?,
        distanceSource = json['distance_source'] as String? ?? 'straight',
        sameShop = json['same_shop'] as bool? ?? false,
        sameWay = json['same_way'] as bool? ?? false,
        sameWayLevel = json['same_way_level'] as String? ?? 'none',
        detourM = json['detour_m'] as int?,
        estMinutes = (json['est_minutes'] as num?)?.toDouble(),
        estWaitMinutes = (json['est_wait_minutes'] as num?)?.toDouble(),
        waitSource = json['wait_source'] as String? ?? 'declared',
        centsPerMinute = (json['cents_per_minute'] as num?)?.toDouble(),
        arrivedDropAt = '${json['arrived_drop_at'] ?? ''}',
        dropMinutes = (json['drop_minutes'] as num?)?.toDouble(),
        // 这个收货点历史上要花多久。**样本不足时为 null** ——
        // "这里确实快"和"我们还不知道"是两件事,客户端必须分得开
        dropP75Minutes = (json['drop_p75_minutes'] as num?)?.toDouble(),
        dropSample = (json['drop_sample'] as num?)?.toInt() ?? 0,
        // 配送费构成 + 中文名:**接单前就给**。8 块里有 3 块是因为
        // 要爬 6 楼 —— 知道这个才判断得了值不值
        // 顾客选的送上门还是送楼下。选楼下时骑手没有上楼的义务,
        // 小票上要写出来,否则商家会以为骑手偷懒
        toDoor = json['to_door'] as bool? ?? true,
        // 跑腿:food(外卖) / errand_send(帮送) / errand_buy(帮买)
        orderKind = '${json['order_kind'] ?? 'food'}',
        errandNote = '${json['errand_note'] ?? ''}',
        pickupAddress = '${json['pickup_address'] ?? ''}',
        pickupPhotoUrl = '${json['pickup_photo_url'] ?? ''}',
        goodsBudgetCents = (json['goods_budget_cents'] as num?)?.toInt() ?? 0,
        goodsActualCents = (json['goods_actual_cents'] as num?)?.toInt(),
        goodsReceiptUrl = '${json['goods_receipt_url'] ?? ''}',
        goodsRaiseStatus = '${json['goods_raise_status'] ?? ''}',
        goodsRaiseCents = (json['goods_raise_cents'] as num?)?.toInt(),
        feeParts = ((json['fee_parts'] as Map?) ?? const {})
            .map((k, v) => MapEntry('$k', v as int)),
        feePartLabels = ((json['fee_part_labels'] as Map?) ?? const {})
            .map((k, v) => MapEntry('$k', '$v')),
        createdAt = json['created_at'] as String;

  final String orderNo;
  final int merchantId;
  final String merchantName;
  final String merchantAddress;
  final double? merchantLat;
  final double? merchantLng;
  final String riderName;
  final String riderPhone;
  final String merchantPhone;
  final int? riderId;
  final OrderStatus status;
  final List<OrderItem> items;
  final int foodCents;
  final int packingFeeCents;
  final int discountCents;   // 商家满减
  final int subsidyCents;    // 平台补贴(首单立减)
  final String promoNote;
  final int deliveryFeeCents;

  /// 小费:100% 归骑手(骑手结算 = 配送费 + 小费)
  final int tipCents;
  final int totalCents;
  final int commissionCents;

  /// 商家实收 = 菜品 + 打包费 - 商家满减 - 平台佣金(账目透明卡用)
  int get merchantNetCents =>
      foodCents + packingFeeCents - discountCents - commissionCents;
  final String address;
  final double lat;
  final double lng;
  final String contactName;
  final String contactPhone;

  /// 商家/骑手侧可拨号码(隐私中间号 X 号或过渡期真号);
  /// contactPhone 在这两端是打码号,拨打一律用本字段。空 = 严格模式,隐藏拨打
  final String privacyPhone;
  final String remark;
  final String cancelReason;
  final int refundCents;
  final String refundNote;

  /// 这一单评过没有。**列表侧就要能算「待评价 N」** —— 没有它的话
  /// 只能对每笔已完成订单各打一发 `GET /orders/{no}/review` 看 404,
  /// 那个形态在列表上不成立。非完成态恒为 false(本来也不能评)
  final bool hasReview;
  final String? scheduledAt; // 预约送达时间(空 = 尽快送)
  final String? etaAt;       // 预计送达时间(超时 15 分钟平台自动赔安抚券)
  /// 骑手到店时刻(空 = 还没标记)。等餐时长 = 取餐 − 到店,申诉的证据
  final String arrivedShopAt;
  final bool selfDelivery;   // 商家自送(不走骑手,配送费归商家)
  final bool noRiderAlerted; // 无人接单告警中(可加急小费)
  final String? acceptedAt;  // 接单时刻(商家端备餐计时基准)
  final bool readyLate;      // 出餐超时(定格,商家端红色高亮)
  final bool addrProtect;    // 地址保护(骑手只见粗地址与中性称呼)
  final bool addrRevealed;   // 已临时放行完整门牌
  final String deliveryPhotoUrl; // 送达留证照片(仅用户/平台可见)
  final bool pickup;         // 到店自取(免配送费,不走骑手)
  final String pickupCode;   // 取餐码,商家核对后完成订单
  final String parentOrderNo; // 非空 = 追加单,随原单一起配送
  // 抢单池视角(仅骑手 available-orders 返回):到商家距离与顺路标记
  final int? distanceM;   // 骑手 → 取餐点(骑行路径距离),无定位为空
  final int? tripM;       // 取餐点 → 送达点。整单划不划算要看它
  /// route=腾讯骑行路径规划,straight=回退直线×1.2。
  /// 展示时要标出来 —— 距离准不准,骑手有权知道
  final String distanceSource;
  final bool sameShop;    // 与手头某单同商家(同店多取,取餐几乎零成本)
  final bool sameWay;     // 顺路(strong/weak 都为 true)
  final String sameWayLevel;  // strong / weak / none
  final int? detourM;     // 绕路增量:接这单比只送手头单多跑多远
  /// 预计总耗时(到店 + 等餐 + 送达)。骑手判断「值不值得接」看这个,
  /// 不是只看"到店多远"
  final double? estMinutes;
  final double? estWaitMinutes;   // 其中在店等餐
  /// measured=该店实测出餐 P80,declared=商家自报(样本不足)。
  /// 要标出来:「等 22 分钟」和「大概 15 分钟(样本还少)」,决策不一样
  final String waitSource;
  final double? centsPerMinute;   // 每分钟收入估算(横向比较用)

  /// 骑手到达收货点的时刻(空 = 还没点「我到了」)
  final String arrivedDropAt;
  /// 这一单实际的送达段停留时长(分钟);null = 没点过「我到了」
  final double? dropMinutes;
  /// 这个收货点的历史停留时长分位数与样本数
  final double? dropP75Minutes;
  final int dropSample;

  /// 送上门(默认)还是送到楼下
  final bool toDoor;

  /// 订单类型。跑腿单没有商家 —— 骑手端要据此把"取餐"改成"取件",
  /// 商家端根本看不到这类单(它挂在独立的服务主体上)
  final String orderKind;
  bool get isErrand => orderKind.startsWith('errand');
  /// 寄什么 / 买什么
  final String errandNote;
  /// 取件点地址(跑腿单的取件点在订单自己身上,不在商家上)
  final String pickupAddress;
  /// 取件时拍的物品照
  final String pickupPhotoUrl;

  /// 帮买:预付商品款 / 小票实付 / 小票照片 / 加价确认。
  /// **小票用户看得到** —— 代买最容易起的纠纷就是"你是不是多报了"
  final int goodsBudgetCents;
  final int? goodsActualCents;
  final String goodsReceiptUrl;
  final String goodsRaiseStatus;
  final int? goodsRaiseCents;
  bool get isErrandBuy => orderKind == 'errand_buy';

  /// 配送费构成(分)与中文名。接单前可见 ——
  /// 美团官方只承诺"接单前能看到价格",看不到明细;这一步我们做了
  final Map<String, int> feeParts;
  final Map<String, String> feePartLabels;
  final String createdAt;

  String get summary =>
      items.map((i) => '${i.name}×${i.quantity}').join('、');

  /// 含酒精饮品(交付时查验收件人年龄)
  bool get hasAlcohol => items.any((i) => i.isAlcohol);

  /// 预约标签,如「预约 18:30 送达」;非预约单返回 null
  String? get scheduledLabel {
    final s = scheduledAt;
    if (s == null) return null;
    final t = DateTime.tryParse(s)?.toLocal();
    if (t == null) return null;
    final hh = t.hour.toString().padLeft(2, '0');
    final mm = t.minute.toString().padLeft(2, '0');
    final now = DateTime.now();
    final day = (t.year == now.year && t.month == now.month && t.day == now.day)
        ? ''
        : '${t.month}/${t.day} ';
    return '预约 $day$hh:$mm 送达';
  }

  /// 预计送达标签,如「预计 18:30 前送达」;无 ETA 返回 null
  String? get etaLabel {
    final s = etaAt;
    if (s == null) return null;
    final t = DateTime.tryParse(s)?.toLocal();
    if (t == null) return null;
    final hh = t.hour.toString().padLeft(2, '0');
    final mm = t.minute.toString().padLeft(2, '0');
    return '预计 $hh:$mm 前送达';
  }
}

class Address {
  Address.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        contactName = json['contact_name'] as String,
        contactPhone = json['contact_phone'] as String,
        address = json['address'] as String,
        detail = json['detail'] as String? ?? '',
        lat = (json['lat'] as num).toDouble(),
        lng = (json['lng'] as num).toDouble(),
        isDefault = json['is_default'] as bool,
        floor = json['floor'] as int?,
        hasElevator = json['has_elevator'] as bool?,
        protect = json['protect'] as bool? ?? false,
        salutation = json['salutation'] as String? ?? '',
        tag = json['tag'] as String? ?? '';

  final int id;
  final String contactName;
  final String contactPhone;
  final String address;
  final String detail;
  final double lat;
  final double lng;
  final bool isDefault;

  /// 楼层与电梯(选填,null = 没填)。填了两件事会变准:
  /// ETA 更诚实(爬 6 楼确实更慢)、无电梯高楼层送上门会收上门难度费
  /// (顾客付、**全额归骑手**,也可以选送到楼下不收)
  final int? floor;
  final bool? hasElevator;
  final bool protect;      // 保护模式:骑手只见粗地址,门牌送达前不下发
  final String salutation; // 中性称呼(空=「顾客」)

  /// 标签:家 / 公司 / 学校(或自定义)。空 = 没打标签。
  /// 地址簿里三个「XX路XX号」排在一起时,用户得逐字读才知道哪个是家
  final String tag;

  String get fullAddress => detail.isEmpty ? address : '$address $detail';
}

class Review {
  Review.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        merchantRating = json['merchant_rating'] as int,
        riderRating = json['rider_rating'] as int?,
        comment = json['comment'] as String? ?? '',
        imageUrls = (json['image_urls'] as List? ?? const []).cast<String>(),
        tags = (json['tags'] as List? ?? const []).cast<String>(),
        riderTags = (json['rider_tags'] as List? ?? const []).cast<String>(),
        reply = json['reply'] as String? ?? '',
        isAnonymous = json['is_anonymous'] as bool? ?? false,
        appendContent = json['append_content'] as String? ?? '',
        appendImages =
            (json['append_images'] as List? ?? const []).cast<String>(),
        appendAt = json['append_at'] as String?,
        appendReply = json['append_reply'] as String? ?? '',
        hidden = json['hidden'] as bool? ?? false,
        customerName = json['customer_name'] as String? ?? '',
        createdAt = json['created_at'] as String;

  final int id;
  final bool hidden; // 申诉改判后隐藏,不计入评分
  final int merchantRating;
  final int? riderRating;
  final String comment;
  final List<String> imageUrls;
  final List<String> tags;
  final List<String> riderTags; // 配送维度标签(不进商家维度)
  final String reply;
  final bool isAnonymous;      // 真匿名(商家侧不可反查)
  final String appendContent;  // 追评(首评后 7 天内一次)
  final List<String> appendImages;
  final String? appendAt;
  final String appendReply;    // 商家对追评的回复
  final String customerName;
  final String createdAt;
}

class UserProfile {
  UserProfile.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        phone = json['phone'] as String,
        name = json['name'] as String,
        role = json['role'] as String,
        avatarUrl = json['avatar_url'] as String? ?? '',
        birthday = json['birthday'] as String? ?? '',
        marketingPush = json['marketing_push'] as bool? ?? true,
        riskLevel = json['risk_level'] as String? ?? '',
        riskNote = json['risk_note'] as String? ?? '';

  final int id;
  final String phone;
  final String name;
  final String birthday;      // MM-DD,生日当天发券
  final bool marketingPush;   // 营销推送开关
  final String riskLevel;     // ""正常 / limit 限制 / frozen 冻结(反作弊处置)
  final String riskNote;      // 处置原因(对用户可见)
  final String role;
  final String avatarUrl;
}

class AfterSale {
  AfterSale.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        reason = json['reason'] as String,
        status = json['status'] as String,
        reply = json['reply'] as String? ?? '',
        orderNo = json['order_no'] as String? ?? '',
        orderSummary = json['order_summary'] as String? ?? '',
        totalCents = json['total_cents'] as int? ?? 0,
        images = (json['images'] as List?)?.cast<String>() ?? const [],
        fault = json['fault'] as String? ?? '',
        createdAt = json['created_at'] as String;

  final int id;
  final String reason;

  /// 举证照片(相对路径,展示用 api.resolveUrl 拼全)
  final List<String> images;

  /// ""=未判 / merchant=商家责任 / rider=骑手责任(平台先行赔付)
  final String fault;

  /// pending / accepted / rejected
  final String status;
  final String reply;
  final String orderNo;
  final String orderSummary;
  final int totalCents;
  final String createdAt;

  String get statusLabel => switch (status) {
        'pending' => '商家处理中',
        'accepted' => '已退款',
        'rejected' => '商家已回复',
        _ => status,
      };
}

class OrderEvent {
  OrderEvent.fromJson(Map<String, dynamic> json)
      : toStatus = json['to_status'] as String,
        actorRole = json['actor_role'] as String,
        createdAt = json['created_at'] as String;

  final String toStatus;
  final String actorRole;
  final String createdAt;
}

class RiderLocation {
  RiderLocation.fromJson(Map<String, dynamic> json)
      : lat = (json['lat'] as num?)?.toDouble(),
        lng = (json['lng'] as num?)?.toDouble();

  final double? lat;
  final double? lng;
}

class DayStat {
  DayStat.fromJson(Map<String, dynamic> json)
      : day = json['day'] as String,
        orderCount = json['order_count'] as int,
        foodCents = json['food_cents'] as int,
        commissionCents = json['commission_cents'] as int,
        netCents = json['net_cents'] as int;

  final String day;
  final int orderCount;
  final int foodCents;
  final int commissionCents;
  final int netCents;
}

/// 一条入账/冲账明细。
///
/// [id] 是**分页游标的一部分**:接口按 (created_at, id) 两列排序,
/// 只拿 createdAt 翻页会把同一秒的行整组跳过 —— 实测演示库因此漏过
/// 一条 -¥30 的冲账,商家看到的明细比实际到手的钱多。
class FinanceOrder {
  FinanceOrder.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int? ?? 0, orderNo = json['order_no'] as String,
        foodCents = json['food_cents'] as int,
        commissionCents = json['commission_cents'] as int,
        netCents = json['net_cents'] as int,
        createdAt = json['created_at'] as String;

  /// 分页游标的一部分,和 createdAt 一起传
  final int id;
  final String orderNo;
  final int foodCents;
  final int commissionCents;
  final int netCents;
  final String createdAt;
}

/// 骑手实名档案。
///
/// **服务端不再下发身份证号,也不再收身份证照片。**
/// 二要素核验(姓名+证号查国家人口基础信息库)不需要照片,
/// 而照片是敏感个人影像 —— 不收就没有泄露面。
/// [realName] 是打码后的(如「王**」)。
class RiderProfile {
  RiderProfile.fromJson(Map<String, dynamic> json)
      : realName = json['real_name'] as String? ?? '',
        healthCertPhotoUrl = json['health_cert_photo_url'] as String? ?? '',
        status = json['status'] as String,
        idVerified = json['id_verified'] as bool? ?? false,
        healthCertRequired = json['health_cert_required'] as bool? ?? false,
        city = json['city'] as String? ?? '',
        rejectReason = json['reject_reason'] as String? ?? '';

  /// 打码姓名(如「王**」);证号不下发
  final String realName;

  /// 健康证:**选填**。国家层面不要求送餐员持健康证,
  /// 只有地方另有要求的城市才需要
  final String healthCertPhotoUrl;

  /// unsubmitted / pending / approved / rejected
  final String status;

  /// 是否经过二要素核验(区别于历史的人工审核路径)
  final bool idVerified;

  /// **本市**是否要求健康证。国家层面不要求(送餐员不属于"直接接触入口
  /// 食品的人员",四川已取消),只有查证过本地有规章的城市才为 true
  final bool healthCertRequired;

  /// 骑手所在城市(首次上线按定位解析);空 = 还没上线过
  final String city;

  final String rejectReason;

  bool get isApproved => status == 'approved';
}

class Wallet {
  Wallet.fromJson(Map<String, dynamic> json)
      : balanceCents = json['balance_cents'] as int,
        totalEarnedCents = json['total_earned_cents'] as int,
        pendingWithdrawalCents = json['pending_withdrawal_cents'] as int,
        withdrawnCents = json['withdrawn_cents'] as int,
        depositRequiredCents = json['deposit_required_cents'] as int? ?? 0,
        depositHeldCents = json['deposit_held_cents'] as int? ?? 0,
        withdrawableCents =
            json['withdrawable_cents'] as int? ?? (json['balance_cents'] as int);

  final int balanceCents;
  final int totalEarnedCents;
  final int pendingWithdrawalCents;
  final int withdrawnCents;

  /// 保证金(商家):从营收留存;可提 = 余额 - 应留
  final int depositRequiredCents;
  final int depositHeldCents;
  final int withdrawableCents;
}

class Earning {
  Earning.fromJson(Map<String, dynamic> json)
      : orderNo = json['order_no'] as String,
        amountCents = json['amount_cents'] as int,
        createdAt = json['created_at'] as String;

  final String orderNo;
  final int amountCents;
  final String createdAt;
}

class Withdrawal {
  Withdrawal.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        amountCents = json['amount_cents'] as int,
        status = json['status'] as String,
        rejectReason = json['reject_reason'] as String? ?? '',
        createdAt = json['created_at'] as String;

  final int id;
  final int amountCents;

  /// pending / paid / rejected / failed
  final String status;
  final String rejectReason;
  final String createdAt;

  String get statusLabel => switch (status) {
        'pending' => '处理中',
        'paid' => '已到账',
        'rejected' => '已驳回',
        'failed' => '打款失败,余额已退回',
        _ => status,
      };
}

class PayoutAccount {
  PayoutAccount.fromJson(Map<String, dynamic> json)
      : configured = json['configured'] as bool? ?? false,
        kind = json['kind'] as String? ?? '',
        holderName = json['holder_name'] as String? ?? '',
        bankName = json['bank_name'] as String? ?? '',
        accountTail = json['account_tail'] as String? ?? '',
        recentlyChanged = json['recently_changed'] as bool? ?? false;

  final bool configured;
  final String kind;
  final String holderName;
  final String bankName;
  final String accountTail;
  final bool recentlyChanged;

  String get kindLabel => switch (kind) {
        'bank_corporate' => '对公账户',
        'bank_personal' => '银行卡',
        'wechat' => '微信',
        'alipay' => '支付宝',
        _ => kind,
      };
}

class PoiTip {
  /// 地图选点等本地来源用(不是所有 POI 都来自服务端 JSON)
  const PoiTip({
    required this.name,
    required this.district,
    required this.lat,
    required this.lng,
    this.city = '',
  });

  PoiTip.fromJson(Map<String, dynamic> json)
      : name = json['name'] as String,
        district = json['district'] as String? ?? '',
        city = json['city'] as String? ?? '',
        lat = (json['lat'] as num).toDouble(),
        lng = (json['lng'] as num).toDouble();

  final String name;
  final String district;

  /// 结构化城市名(「西安市」),服务端从腾讯的 address_component 取,
  /// 和商家入驻解析出来的 city 同一个口径。
  /// **别再从 [district] 那串行政区划里抠** —— 见 CityPref 的注释
  final String city;
  final double lat;
  final double lng;
}

class Ticket {
  Ticket.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        content = json['content'] as String,
        contact = json['contact'] as String? ?? '',
        status = json['status'] as String,
        reply = json['reply'] as String? ?? '',
        createdAt = json['created_at'] as String,
        repliedAt = json['replied_at'] as String?;

  final int id;
  final String content;
  final String contact;

  /// open / replied / closed
  final String status;
  final String reply;
  final String createdAt;
  final String? repliedAt;

  String get statusLabel => switch (status) {
        'open' => '等待回复',
        'replied' => '已回复',
        'closed' => '已关闭',
        _ => status,
      };
}

/// 团购券(商家发布的代金券)。
class VoucherDeal {
  VoucherDeal.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        merchantId = json['merchant_id'] as int,
        title = json['title'] as String,
        description = json['description'] as String? ?? '',
        sellPriceCents = json['sell_price_cents'] as int,
        faceValueCents = json['face_value_cents'] as int,
        totalCount = json['total_count'] as int,
        soldCount = json['sold_count'] as int? ?? 0,
        perUserLimit = json['per_user_limit'] as int? ?? 5,
        validDays = json['valid_days'] as int? ?? 90,
        isActive = json['is_active'] as bool? ?? true,
        merchantName = json['merchant_name'] as String? ?? '',
        merchantLogo = json['merchant_logo'] as String? ?? '';

  final int id;
  final int merchantId;
  final String title;
  final String description;
  final int sellPriceCents;
  final int faceValueCents;
  final int totalCount;
  final int soldCount;
  final int perUserLimit;
  final int validDays;
  final bool isActive;
  final String merchantName;
  final String merchantLogo;

  /// 折扣标签,如「4.5折」
  String get discountLabel {
    final zhe = sellPriceCents / faceValueCents * 10;
    return '${zhe.toStringAsFixed(1)}折';
  }
}

/// 已购的券实例。
class VoucherTicket {
  VoucherTicket.fromJson(Map<String, dynamic> json)
      : purchaseNo = json['purchase_no'] as String,
        voucherId = json['voucher_id'] as int,
        merchantId = json['merchant_id'] as int,
        sellPriceCents = json['sell_price_cents'] as int,
        faceValueCents = json['face_value_cents'] as int,
        commissionCents = json['commission_cents'] as int? ?? 0,
        netCents = json['net_cents'] as int? ?? 0,
        code = json['code'] as String,
        status = json['status'] as String,
        expiresAt = json['expires_at'] as String?,
        redeemedAt = json['redeemed_at'] as String?,
        title = json['title'] as String? ?? '',
        merchantName = json['merchant_name'] as String? ?? '',
        merchantAddress = json['merchant_address'] as String? ?? '',
        merchantLat = (json['merchant_lat'] as num?)?.toDouble(),
        merchantLng = (json['merchant_lng'] as num?)?.toDouble(),
        expired = json['expired'] as bool? ?? false;

  final String purchaseNo;
  final int voucherId;
  final int merchantId;
  final int sellPriceCents;
  final int faceValueCents;
  final int commissionCents;
  final int netCents;
  final String code;
  final String status;
  final String? expiresAt;
  final String? redeemedAt;
  final String title;
  final String merchantName;
  final String merchantAddress;
  final double? merchantLat;
  final double? merchantLng;
  final bool expired;

  String get statusLabel => expired
      ? '已过期'
      : switch (status) {
          'pending_payment' => '待支付',
          'paid' => '待使用',
          'redeemed' => '已使用',
          'refunded' => '已退款',
          _ => '已关闭',
        };

  bool get usable => status == 'paid' && !expired;

  /// 券码分组展示:1234 5678 9012
  String get prettyCode => code.replaceAllMapped(
      RegExp(r'.{4}'), (m) => '${m.group(0)} ').trim();
}

// ---------- 住宿(酒店垂类)----------

/// 酒店档次(slug -> 中文),与服务端 HOTEL_TIERS 一致
const kHotelTiers = {
  'economy': '经济型',
  'comfort': '舒适型',
  'premium': '高档型',
  'luxury': '豪华型',
};

/// 取消政策(slug -> 中文档位名)
const kCancelPolicies = {
  'limited_free': '限时免费取消',
  'first_night': '取消扣首晚',
  'strict': '不可退',
};

class RoomType {
  RoomType.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        merchantId = json['merchant_id'] as int? ?? 0,
        name = json['name'] as String,
        bedType = json['bed_type'] as String? ?? '',
        areaM2 = json['area_m2'] as int? ?? 0,
        maxGuests = json['max_guests'] as int? ?? 2,
        imageUrls = (json['image_urls'] as List? ?? const []).cast<String>(),
        facilities = (json['facilities'] as List? ?? const []).cast<String>(),
        cancelPolicy = json['cancel_policy'] as String? ?? 'limited_free',
        freeCancelUntil = json['free_cancel_until'] as String? ?? '18:00',
        isOnSale = json['is_on_sale'] as bool? ?? true,
        sort = json['sort'] as int? ?? 0;

  final int id;
  final int merchantId;
  final String name;
  final String bedType;
  final int areaM2;
  final int maxGuests;
  final List<String> imageUrls;
  final List<String> facilities;
  final String cancelPolicy;
  final String freeCancelUntil;
  final bool isOnSale;
  final int sort;

  String get policyLabel => kCancelPolicies[cancelPolicy] ?? cancelPolicy;
}

/// 房价房态日历单元格(某房型某天)
class RoomDay {
  RoomDay.fromJson(Map<String, dynamic> json)
      : date = json['date'] as String,
        priceCents = json['price_cents'] as int,
        totalQty = json['total_qty'] as int? ?? 0,
        soldQty = json['sold_qty'] as int? ?? 0,
        closed = json['closed'] as bool? ?? false;

  final String date;
  final int priceCents;
  final int totalQty;
  final int soldQty;
  final bool closed;

  int get leftQty => totalQty - soldQty;
}

/// 商家日历网格:每房型一行
class RoomCalendarRow {
  RoomCalendarRow.fromJson(Map<String, dynamic> json)
      : roomTypeId = json['room_type_id'] as int,
        roomTypeName = json['room_type_name'] as String? ?? '',
        days = (json['days'] as List? ?? const [])
            .map((e) => RoomDay.fromJson(e as Map<String, dynamic>))
            .toList();

  final int roomTypeId;
  final String roomTypeName;
  final List<RoomDay> days;
}

/// 酒店列表卡片(消费端)
class HotelCard {
  HotelCard.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        name = json['name'] as String,
        tier = json['tier'] as String? ?? 'economy',
        address = json['address'] as String? ?? '',
        lat = (json['lat'] as num?)?.toDouble() ?? 0,
        lng = (json['lng'] as num?)?.toDouble() ?? 0,
        logoUrl = json['logo_url'] as String? ?? '',
        photoUrls = (json['photo_urls'] as List? ?? const []).cast<String>(),
        ratingAvg = (json['rating_avg'] as num?)?.toDouble(),
        ratingCount = json['rating_count'] as int? ?? 0,
        distanceM = json['distance_m'] as int?,
        minNightPriceCents = json['min_night_price_cents'] as int?,
        full = json['full'] as bool? ?? false;

  final int id;
  final String name;
  final String tier;
  final String address;
  final double lat;
  final double lng;
  final String logoUrl;
  final List<String> photoUrls;
  final double? ratingAvg;
  final int ratingCount;
  final int? distanceM;
  final int? minNightPriceCents; // null = 区间内满房
  final bool full;

  String get tierLabel => kHotelTiers[tier] ?? tier;
  String get distanceLabel {
    final d = distanceM;
    if (d == null) return '';
    return d < 1000 ? '${d}m' : '${(d / 1000).toStringAsFixed(1)}km';
  }
}

/// 房型报价(详情页,按查询区间聚合)
class RoomQuote {
  RoomQuote.fromJson(Map<String, dynamic> json)
      : roomType =
            RoomType.fromJson(json['room_type'] as Map<String, dynamic>),
        totalCents = json['total_cents'] as int?,
        nightly = (json['nightly'] as List? ?? const [])
            .map((e) => RoomDay.fromJson(e as Map<String, dynamic>))
            .toList(),
        bookable = json['bookable'] as bool? ?? false,
        leftQty = json['left_qty'] as int?,
        cancelPolicyText = json['cancel_policy_text'] as String? ?? '';

  final RoomType roomType;
  final int? totalCents; // 区间总价(一间);null = 不可订
  final List<RoomDay> nightly;
  final bool bookable;
  final int? leftQty; // 仅剩 X 间(≤3 才有值)
  final String cancelPolicyText;
}

/// 酒店详情(消费端)
class HotelDetail {
  HotelDetail.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        name = json['name'] as String,
        description = json['description'] as String? ?? '',
        tier = json['tier'] as String? ?? 'economy',
        address = json['address'] as String? ?? '',
        lat = (json['lat'] as num?)?.toDouble() ?? 0,
        lng = (json['lng'] as num?)?.toDouble() ?? 0,
        frontDeskPhone = json['front_desk_phone'] as String? ?? '',
        checkinFrom = json['checkin_from'] as String? ?? '14:00',
        checkoutUntil = json['checkout_until'] as String? ?? '12:00',
        facilities = (json['facilities'] as List? ?? const []).cast<String>(),
        logoUrl = json['logo_url'] as String? ?? '',
        photoUrls = (json['photo_urls'] as List? ?? const []).cast<String>(),
        ratingAvg = (json['rating_avg'] as num?)?.toDouble(),
        ratingCount = json['rating_count'] as int? ?? 0,
        checkinDate = json['checkin_date'] as String? ?? '',
        checkoutDate = json['checkout_date'] as String? ?? '',
        rooms = (json['rooms'] as List? ?? const [])
            .map((e) => RoomQuote.fromJson(e as Map<String, dynamic>))
            .toList();

  final int id;
  final String name;
  final String description;
  final String tier;
  final String address;
  final double lat;
  final double lng;
  final String frontDeskPhone;
  final String checkinFrom;
  final String checkoutUntil;
  final List<String> facilities;
  final String logoUrl;
  final List<String> photoUrls;
  final double? ratingAvg;
  final int ratingCount;
  final String checkinDate;
  final String checkoutDate;
  final List<RoomQuote> rooms;

  String get tierLabel => kHotelTiers[tier] ?? tier;
}

/// 住宿订单(三端共用)
class StayOrder {
  StayOrder.fromJson(Map<String, dynamic> json)
      : orderNo = json['order_no'] as String,
        merchantId = json['merchant_id'] as int? ?? 0,
        roomTypeId = json['room_type_id'] as int? ?? 0,
        checkinDate = json['checkin_date'] as String,
        checkoutDate = json['checkout_date'] as String,
        nights = json['nights'] as int? ?? 1,
        roomsQty = json['rooms_qty'] as int? ?? 1,
        guestName = json['guest_name'] as String? ?? '',
        guestPhone = json['guest_phone'] as String? ?? '',
        arrivalNote = json['arrival_note'] as String? ?? '',
        roomTypeName = json['room_type_name'] as String? ?? '',
        nightlyPrices = (json['nightly_prices'] as List? ?? const [])
            .cast<Map<String, dynamic>>(),
        totalCents = json['total_cents'] as int? ?? 0,
        feeCents = json['fee_cents'] as int? ?? 0,
        netCents = json['net_cents'] as int? ?? 0,
        cancelPolicy = json['cancel_policy'] as String? ?? 'limited_free',
        freeCancelUntil = json['free_cancel_until'] as String? ?? '18:00',
        status = json['status'] as String,
        statusLabel = json['status_label'] as String? ?? '',
        cancelPolicyText = json['cancel_policy_text'] as String? ?? '',
        rejectReason = json['reject_reason'] as String? ?? '',
        refundCents = json['refund_cents'] as int? ?? 0,
        refundNote = json['refund_note'] as String? ?? '',
        hotelName = json['hotel_name'] as String? ?? '',
        hotelAddress = json['hotel_address'] as String? ?? '',
        hotelPhone = json['hotel_phone'] as String? ?? '',
        createdAt = json['created_at'] as String? ?? '',
        paidAt = json['paid_at'] as String?,
        confirmedAt = json['confirmed_at'] as String?,
        checkedInAt = json['checked_in_at'] as String?,
        completedAt = json['completed_at'] as String?,
        cancelledAt = json['cancelled_at'] as String?;

  final String orderNo;
  final int merchantId;
  final int roomTypeId;
  final String checkinDate;
  final String checkoutDate;
  final int nights;
  final int roomsQty;
  final String guestName;
  final String guestPhone;
  final String arrivalNote;
  final String roomTypeName;
  final List<Map<String, dynamic>> nightlyPrices;
  final int totalCents;
  final int feeCents;
  final int netCents;
  final String cancelPolicy;
  final String freeCancelUntil;

  /// created/closed/paid/confirmed/checked_in/completed/cancelled/rejected/noshow
  final String status;
  final String statusLabel;
  final String cancelPolicyText;
  final String rejectReason;
  final int refundCents;
  final String refundNote;
  final String hotelName;
  final String hotelAddress;
  final String hotelPhone;
  final String createdAt;
  final String? paidAt;
  final String? confirmedAt;
  final String? checkedInAt;
  final String? completedAt;
  final String? cancelledAt;

  bool get isActive => const {'created', 'paid', 'confirmed', 'checked_in'}
      .contains(status);
  String get stayLabel =>
      '$checkinDate 入住 · $nights 晚 · $roomsQty 间';
}

/// 取消试算(确认弹层)
class StayCancelPreview {
  StayCancelPreview.fromJson(Map<String, dynamic> json)
      : refundCents = json['refund_cents'] as int,
        penaltyCents = json['penalty_cents'] as int,
        note = json['note'] as String? ?? '';

  final int refundCents;
  final int penaltyCents;
  final String note;
}

/// 住宿点评一键标签白名单(与服务端 STAY_REVIEW_TAGS 一致)
const List<String> kStayReviewTags = [
  '干净卫生', '位置方便', '隔音好', '性价比高', '服务热情',
  '设施陈旧', '隔音差', '卫生一般',
];

class StayReview {
  StayReview.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        rating = json['rating'] as int,
        comment = json['comment'] as String? ?? '',
        imageUrls = (json['image_urls'] as List? ?? const []).cast<String>(),
        tags = (json['tags'] as List? ?? const []).cast<String>(),
        reply = json['reply'] as String? ?? '',
        isAnonymous = json['is_anonymous'] as bool? ?? false,
        appendContent = json['append_content'] as String? ?? '',
        appendReply = json['append_reply'] as String? ?? '',
        createdAt = json['created_at'] as String? ?? '',
        reviewerName = json['reviewer_name'] as String? ?? '',
        orderNo = json['order_no'] as String? ?? '';

  final int id;
  final int rating;
  final String comment;
  final List<String> imageUrls;
  final List<String> tags;
  final String reply;
  final bool isAnonymous;
  final String appendContent;
  final String appendReply;
  final String createdAt;
  final String reviewerName;
  final String orderNo;
}

/// 住宿售后(到店无房赔付 / 协商退)
class StayAfterSale {
  StayAfterSale.fromJson(Map<String, dynamic> json)
      : id = json['id'] as int,
        kind = json['kind'] as String,
        status = json['status'] as String,
        note = json['note'] as String? ?? '',
        merchantNote = json['merchant_note'] as String? ?? '',
        refundCents = json['refund_cents'] as int? ?? 0,
        penaltyCents = json['penalty_cents'] as int? ?? 0,
        orderNo = json['order_no'] as String? ?? '',
        guestName = json['guest_name'] as String? ?? '',
        totalCents = json['total_cents'] as int? ?? 0,
        createdAt = json['created_at'] as String? ?? '';

  final int id;
  final String kind;      // no_room / nego_refund
  final String status;    // pending / accepted / rejected / auto_accepted
  final String note;
  final String merchantNote;
  final int refundCents;
  final int penaltyCents;
  final String orderNo;
  final String guestName;
  final int totalCents;
  final String createdAt;

  String get kindLabel => kind == 'no_room' ? '到店无房' : '协商退款';
  String get statusLabel => switch (status) {
        'pending' => '待商家处理',
        'accepted' => '已通过',
        'auto_accepted' => '已通过(超时自动成立)',
        _ => '未通过',
      };
  bool get resolvedOk => status == 'accepted' || status == 'auto_accepted';
}

/// 我的常点:近 90 天点得最多的「店+菜」组合(#119)
class FrequentDish {
  FrequentDish.fromJson(Map<String, dynamic> json)
      : dishId = json['dish_id'] as int,
        dishName = json['dish_name'] as String? ?? '',
        priceCents = json['price_cents'] as int? ?? 0,
        imageUrl = json['image_url'] as String? ?? '',
        merchantId = json['merchant_id'] as int,
        merchantName = json['merchant_name'] as String? ?? '',
        merchantOpen = json['merchant_open'] as bool? ?? true,
        times = json['times'] as int? ?? 0,
        lastAt = json['last_at'] as String? ?? '';

  final int dishId;
  final String dishName;
  final int priceCents;
  final String imageUrl;
  final int merchantId;
  final String merchantName;

  /// 店是否在营业;没开也照常展示,只是点不了
  final bool merchantOpen;
  final int times;
  final String lastAt;
}

/// 地图下方列出的一个周边地点。
class NearbyPlace {
  const NearbyPlace({
    required this.name,
    required this.address,
    required this.distanceM,
    required this.lat,
    required this.lng,
  });

  factory NearbyPlace.fromJson(Map<String, dynamic> j) => NearbyPlace(
        name: j['name'] as String? ?? '',
        address: j['address'] as String? ?? '',
        distanceM: (j['distance_m'] as num?)?.round() ?? 0,
        lat: (j['lat'] as num).toDouble(),
        lng: (j['lng'] as num).toDouble(),
      );

  final String name;
  final String address;

  /// 距图钉多少米。让用户一眼判断"是不是我家那栋" —— 比看地图快
  final int distanceM;
  final double lat;
  final double lng;
}

/// 小程序清单条目(#277,Telegram 模式:就是一个网页 + 桥权限)。
/// allowedOrigins 是 JS 桥的安全边界:桥只对这些 origin 注入/应答。
class MiniAppInfo {
  const MiniAppInfo({
    required this.id,
    required this.name,
    required this.icon,
    required this.tagline,
    required this.entryUrl,
    required this.allowedOrigins,
    required this.perms,
  });

  factory MiniAppInfo.fromJson(Map<String, dynamic> j) => MiniAppInfo(
        id: j['id'] as int,
        name: j['name'] as String? ?? '',
        icon: j['icon'] as String? ?? '',
        tagline: j['tagline'] as String? ?? '',
        entryUrl: j['entry_url'] as String? ?? '',
        allowedOrigins:
            (j['allowed_origins'] as List? ?? const []).cast<String>(),
        perms: (j['perms'] as List? ?? const []).cast<String>(),
      );

  final int id;
  final String name;

  /// emoji 字面量或 https 图片地址,按内容渲染
  final String icon;
  final String tagline;
  final String entryUrl;
  final List<String> allowedOrigins;
  final List<String> perms;
}
