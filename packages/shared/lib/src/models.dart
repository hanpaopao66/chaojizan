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

/// 评价一键标签白名单(与服务端 schemas.REVIEW_TAGS 保持一致)。
const List<String> kReviewTags = [
  '味道好', '分量足', '包装好', '配送快', '干净卫生', '回头客',
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
        category = json['category'] as String? ?? 'fast_food';

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
        stock = json['stock'] as int,
        dailyStock = json['daily_stock'] as int?,
        soldOutToday = json['sold_out_today'] as bool? ?? false,
        isOnSale = json['is_on_sale'] as bool? ?? true,
        isAlcohol = json['is_alcohol'] as bool? ?? false,
        imageUrl = json['image_url'] as String? ?? '',
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
  final int stock;

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
        scheduledAt = json['scheduled_at'] as String?,
        etaAt = json['eta_at'] as String?,
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
        sameShop = json['same_shop'] as bool? ?? false,
        sameWay = json['same_way'] as bool? ?? false,
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
  final String? scheduledAt; // 预约送达时间(空 = 尽快送)
  final String? etaAt;       // 预计送达时间(超时 15 分钟平台自动赔安抚券)
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
  final int? distanceM;   // 骑手最近上报位置到商家的直线距离,无定位为空
  final bool sameShop;    // 与手头某单同商家(顺路取)
  final bool sameWay;     // 与手头某单收货点相近(顺路送)
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
        protect = json['protect'] as bool? ?? false,
        salutation = json['salutation'] as String? ?? '';

  final int id;
  final String contactName;
  final String contactPhone;
  final String address;
  final String detail;
  final double lat;
  final double lng;
  final bool isDefault;
  final bool protect;      // 保护模式:骑手只见粗地址,门牌送达前不下发
  final String salutation; // 中性称呼(空=「顾客」)

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

class FinanceOrder {
  FinanceOrder.fromJson(Map<String, dynamic> json)
      : orderNo = json['order_no'] as String,
        foodCents = json['food_cents'] as int,
        commissionCents = json['commission_cents'] as int,
        netCents = json['net_cents'] as int,
        createdAt = json['created_at'] as String;

  final String orderNo;
  final int foodCents;
  final int commissionCents;
  final int netCents;
  final String createdAt;
}

class RiderProfile {
  RiderProfile.fromJson(Map<String, dynamic> json)
      : realName = json['real_name'] as String? ?? '',
        idCardNo = json['id_card_no'] as String? ?? '',
        idCardPhotoUrl = json['id_card_photo_url'] as String? ?? '',
        healthCertPhotoUrl = json['health_cert_photo_url'] as String? ?? '',
        status = json['status'] as String,
        rejectReason = json['reject_reason'] as String? ?? '';

  final String realName;
  final String idCardNo;
  final String idCardPhotoUrl;
  final String healthCertPhotoUrl;

  /// unsubmitted / pending / approved / rejected
  final String status;
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
  PoiTip.fromJson(Map<String, dynamic> json)
      : name = json['name'] as String,
        district = json['district'] as String? ?? '',
        lat = (json['lat'] as num).toDouble(),
        lng = (json['lng'] as num).toDouble();

  final String name;
  final String district;
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
