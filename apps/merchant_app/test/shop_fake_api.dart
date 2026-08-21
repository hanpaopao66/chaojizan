import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:superz_shared/superz_shared.dart';

/// 店铺页测试共用的假服务端。
///
/// **不是为了省事才造这个。** 店铺页的验收标准是「不滚动能点到几样东西」,
/// 那个数字只有把整页真渲染出来才量得到 —— 而整页渲染要先过 `_load()`
/// 的七个请求。拿源码做文本断言是另一条路,但这一页刚证明了它不靠谱:
/// 旧的 `shop_tab_density_test.dart` 断言 `contains('controller: _announcement')`
/// 来锁「公告留在页面里」,而公告搬进弹层之后那行文本照样在,测试照样绿。

/// 一份完整的 `/merchants/me` 响应。默认是「正常营业、证照没到期、店主本人」。
Map<String, dynamic> shopJson({
  bool isOpen = true,
  String openTime = '09:00',
  String closeTime = '21:00',
  String? closedUntil,
  String announcement = '本店牛肉面每日现煮,不用高汤粉',
  int ratingCount = 312,
  double ratingAvg = 4.8,
  int minOrderCents = 2000,
  int packingFeeCents = 100,
  int promiseReadyMinutes = 15,
  bool selfDelivery = false,
  bool autoAccept = true,
  bool foodSeal = true,
  String dineInStatus = 'unknown',
  String licenseExpiresAt = '2027-03-15',
  String licenseStage = 'ok',
  int? licenseDaysLeft = 206,
  bool viewerIsStaff = false,
  bool viewerIsOwner = true,
  bool foodSafetyHold = false,
  List<Map<String, dynamic>> holidayPlans = const [],
  List<Map<String, dynamic>> promoRules = const [],
  List<Map<String, dynamic>> giftRules = const [],
  List<String> photoUrls = const [],
}) =>
    {
      'id': 1,
      'name': '张记牛肉面',
      'description': '',
      'address': '朝阳区望京街 12 号 1 层',
      'lat': 39.99,
      'lng': 116.47,
      'is_open': isOpen,
      'commission_rate': 0.045,
      'status': 'approved',
      'rating_avg': ratingAvg,
      'rating_count': ratingCount,
      'announcement': announcement,
      'logo_url': '',
      'open_time': openTime,
      'close_time': closeTime,
      'monthly_sales': 820,
      'promise_ready_minutes': promiseReadyMinutes,
      'self_delivery': selfDelivery,
      'min_order_cents': minOrderCents,
      'packing_fee_cents': packingFeeCents,
      'photo_urls': photoUrls,
      'promo_rules': promoRules,
      'gift_rules': giftRules,
      'closed_until': closedUntil,
      'holiday_plans': holidayPlans,
      'viewer_is_staff': viewerIsStaff,
      'viewer_is_owner': viewerIsOwner,
      'license_stage': licenseStage,
      'license_expires_at': licenseExpiresAt,
      'license_days_left': licenseDaysLeft,
      'category': 'fast_food',
      'kitchen_cam': false,
      'kitchen_cam_label': '无明厨亮灶',
      'dine_in_status': dineInStatus,
      'dine_in_label': switch (dineInStatus) {
        'yes' => '有堂食',
        'no' => '无堂食',
        _ => '未填报',
      },
      'biz_type': 'food',
      'auto_accept': autoAccept,
      'food_seal': foodSeal,
      'food_safety_hold': foodSafetyHold,
      'busy_active': false,
      'busy_extra_minutes': 10,
      'license_no': 'JY11105080012345',
      'license_image_url': '',
    };

Map<String, dynamic> afterSaleJson({int id = 1}) => {
      'id': id,
      'reason': '面里有头发',
      'status': 'pending',
      'reply': '',
      'order_no': 'SZ2026082100$id',
      'order_summary': '牛肉面 x1 等 2 件',
      'total_cents': 3800,
      'images': <String>[],
      'fault': '',
      'created_at': '2026-08-21T11:20:00+08:00',
    };

Map<String, dynamic> reviewJson(int id, {String reply = ''}) => {
      'id': id,
      'order_no': 'SZ$id',
      'merchant_id': 1,
      'customer_name': '张*',
      'merchant_rating': 5,
      'rider_rating': 5,
      'comment': '好吃',
      'image_urls': <String>[],
      'reply': reply,
      'tags': <String>[],
      'created_at': '2026-08-20T12:00:00+08:00',
      'hidden': false,
    };

/// 样本够、比承诺慢 7 分钟 —— `_measuredPrep()` 的完整形态(103px 那一档)。
Map<String, dynamic> prepJson({bool enough = true}) => enough
    ? {
        'enough': true,
        'window_days': 30,
        'samples': 128,
        'min_samples': 20,
        'p50': 16,
        'p80': 22,
        'p95': 31,
        'gap_minutes': 7,
        'peer_median_p50': 18,
        'never_used_for': '这个数只用来帮你定承诺值,不参与排序、不影响流量分配',
      }
    : {
        'enough': false,
        'window_days': 30,
        'samples': 12,
        'min_samples': 20,
        'never_used_for': '这个数只用来帮你定承诺值,不参与排序、不影响流量分配',
      };

Map<String, dynamic> todosJson({
  int afterSales = 0,
  int badUnreplied = 0,
  int badOverdue = 0,
  int messagesUnread = 0,
  int appealable = 0,
  int couponLow = 0,
  int healthExpiring = 0,
}) =>
    {
      'pending_orders': 0,
      'after_sales': afterSales,
      'bad_reviews_unreplied': badUnreplied,
      'bad_reviews_overdue': badOverdue,
      'coupon_batches_low': couponLow,
      'flash_expiring': 0,
      'messages_unread': messagesUnread,
      'health_certs_expiring': healthExpiring,
      'appealable': appealable,
    };

Map<String, dynamic> tierJson({
  double rate = 0.045,
  int thisMonth = 128,
  int? nextFrom = 200,
  double? nextRate = 0.04,
}) =>
    {
      'commission_rate': rate,
      'tier_rate': rate,
      'tiers': [
        {'from_orders': 0, 'rate': 0.05},
        {'from_orders': 100, 'rate': 0.045},
        {'from_orders': 200, 'rate': 0.04},
      ],
      'last_month_completed': 118,
      'this_month_completed': thisMonth,
      'next_tier_from': nextFrom,
      'next_tier_rate': nextRate,
      'orders_to_next': nextFrom == null ? null : nextFrom - thisMonth,
    };

/// 造一个只认店铺页那几条路径的 ApiClient。
///
/// 认不出的路径一律回 `{}` —— 那正是"这一页多发了一个请求却没人用"时
/// 会走到的分支,回空对象而不是 404,是为了让漏接的地方安静地少显示一块,
/// 而不是把整页打回错误态(与 `SzGather.soft` 的口径一致)。
ApiClient shopFakeApi({
  Map<String, dynamic>? shop,
  List<Map<String, dynamic>> afterSales = const [],
  List<Map<String, dynamic>> reviews = const [],
  Map<String, dynamic>? prep,
  Map<String, dynamic>? todos,
  Map<String, dynamic>? tier,
  String kitchenCamStatus = 'none',
  void Function(String path)? onRequest,
}) {
  return ApiClient(
    baseUrl: 'http://test.local',
    httpClient: MockClient((req) async {
      onRequest?.call(req.url.path);
      Object? payload;
      switch (req.url.path) {
        case '/auth/login':
          payload = {
            'token': 'tkn',
            'user_id': 9,
            'name': '老张',
            'role': 'merchant',
          };
        case '/merchants/me':
          payload = shop ?? shopJson();
        case '/merchants/me/after-sales':
          payload = afterSales;
        case '/merchants/me/reviews':
          payload = reviews;
        case '/merchants/me/coupon-batches':
          payload = <Map<String, dynamic>>[];
        case '/merchants/me/prep-time':
          payload = prep ?? prepJson();
        case '/merchants/me/kitchen-cam':
          payload = {
            'status': kitchenCamStatus,
            'listed_label':
                kitchenCamStatus == 'active' ? '有明厨亮灶' : '无明厨亮灶',
          };
        case '/merchants/me/todos':
          payload = todos ?? todosJson();
        case '/merchants/me/commission-tier':
          payload = tier ?? tierJson();
        case '/appeals/mine':
          payload = <Map<String, dynamic>>[];
        default:
          payload = <String, dynamic>{};
      }
      return http.Response(jsonEncode(payload), 200,
          headers: {'content-type': 'application/json; charset=utf-8'});
    }),
  );
}
