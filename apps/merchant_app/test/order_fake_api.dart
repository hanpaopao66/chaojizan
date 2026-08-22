import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:superz_shared/superz_shared.dart';

/// 订单 tab 测试共用的假服务端。
///
/// **必须真渲染整页。** 这一批要守的三件事(待接单数从哪儿来、催单语音的
/// 判据是什么、动作行在窄屏溢不溢出)都是**行为**,源码文本断言守不住:
/// `shop_tab_density_test.dart` 的开头就写着它踩过的那一次 ——
/// 公告搬进弹层之后 `contains('controller: _announcement')` 照样绿,
/// 而它要守的行为已经反过来了。

/// 一单。默认是「刚下单、还没接」的外卖单。
Map<String, dynamic> orderJson({
  required String no,
  String status = 'paid',
  int total = 4800,
  String? created,
  String? accepted,
  bool pickup = false,
  bool selfDelivery = false,
  int? riderId,
  bool readyLate = false,
  String remark = '',
  String cancelReason = '',
  int refund = 0,
}) =>
    {
      'order_no': no,
      'merchant_id': 1,
      'status': status,
      'items': [
        {'dish_id': 1, 'name': '红烧牛肉面', 'price_cents': 2800, 'quantity': 1},
        {'dish_id': 2, 'name': '卤蛋', 'price_cents': 300, 'quantity': 2},
      ],
      'food_cents': 3400,
      'delivery_fee_cents': 400,
      'total_cents': total,
      'commission_cents': 216,
      'address': '望京 SOHO T1 座 2308 室',
      'lat': 39.99,
      'lng': 116.47,
      'remark': remark,
      'cancel_reason': cancelReason,
      'refund_cents': refund,
      'refund_note': refund > 0 ? '缺货退款' : '',
      'pickup': pickup,
      'pickup_code': pickup ? '3721' : '',
      'self_delivery': selfDelivery,
      'rider_id': riderId,
      'ready_late': readyLate,
      'accepted_at': accepted,
      'created_at': created ??
          DateTime.now()
              .subtract(const Duration(minutes: 4))
              .toUtc()
              .toIso8601String(),
    };

/// 一批单,`createdAt` 依次往前推 —— 游标分页要靠它排序。
List<Map<String, dynamic>> ordersJson({
  required int count,
  required String prefix,
  String status = 'paid',
  int startMinutesAgo = 1,
}) =>
    [
      for (var i = 0; i < count; i++)
        orderJson(
          no: '$prefix${(i + 1).toString().padLeft(4, '0')}',
          status: status,
          created: DateTime.now()
              .subtract(Duration(minutes: startMinutesAgo + i))
              .toUtc()
              .toIso8601String(),
        ),
    ];

Map<String, dynamic> merchantTodayJson({int orders = 0, int gmv = 0}) => {
      'today': {
        'orders': orders,
        'gmv_cents': gmv,
        'ongoing': 0,
        'done': 0,
        'cancelled': 0,
        'pickup_orders': 0
      },
      'yesterday': {
        'orders': 0,
        'gmv_cents': 0,
        'ongoing': 0,
        'done': 0,
        'cancelled': 0,
        'pickup_orders': 0
      },
    };

/// 每一次 `/orders` 请求的 query,按发生顺序记下来。
///
/// 用来证明「待接单是不是真的单独按状态拉了一次」——
/// 只看屏幕上的数字分不出「服务端给的」和「凑巧对上的」。
class OrdersRequestLog {
  final List<Map<String, String>> calls = [];

  List<Map<String, String>> get byStatus =>
      calls.where((q) => q.containsKey('status')).toList();
}

/// 造一个只认订单页那几条路径的 ApiClient。
///
/// [pages] 是游标分页的**全量**数据:按 createdAt 倒序排好,
/// 假服务端照 `/orders` 的真口径切片(`before` 严格小于、`limit` 上限 50、
/// `status` 精确过滤),而不是「不管问什么都回同一批」——
/// 假服务端比真服务端宽松的话,测试守不住任何东西。
ApiClient orderFakeApi({
  required List<Map<String, dynamic>> pages,
  Map<String, dynamic>? todos,
  Map<String, dynamic>? today,
  OrdersRequestLog? log,
}) {
  return ApiClient(
    baseUrl: 'http://test.local',
    httpClient: MockClient((req) async {
      Object? payload;
      switch (req.url.path) {
        case '/orders':
          final q = req.url.queryParameters;
          log?.calls.add(q);
          final limit = int.tryParse(q['limit'] ?? '20') ?? 20;
          final before = q['before'];
          final status = q['status'];
          var rows = [...pages];
          rows.sort((a, b) =>
              (b['created_at'] as String).compareTo(a['created_at'] as String));
          if (before != null && before.isNotEmpty) {
            rows = rows
                .where((o) => (o['created_at'] as String).compareTo(before) < 0)
                .toList();
          }
          if (status != null && status.isNotEmpty) {
            rows = rows.where((o) => o['status'] == status).toList();
          }
          payload = rows.take(limit.clamp(1, 50)).toList();
        case '/merchants/me/today':
          payload = today ?? merchantTodayJson();
        case '/merchants/me/todos':
          payload = todos ?? <String, dynamic>{'pending_orders': 0};
        case '/announcements':
          payload = <Map<String, dynamic>>[];
        default:
          payload = <String, dynamic>{};
      }
      return http.Response(jsonEncode(payload), 200,
          headers: {'content-type': 'application/json; charset=utf-8'});
    }),
  );
}

/// 把渲染视口真的调成手机尺寸。
///
/// ⚠️ **只给 MediaQuery 传 size 是没用的** —— widget 测试的渲染视口默认
/// 800×600,那块屏怎么排都不挤,窄屏溢出一条都测不出来。
void setPhoneViewport(WidgetTester tester, Size logical) {
  tester.view
    ..devicePixelRatio = 3.0
    ..physicalSize = logical * 3.0;
  addTearDown(tester.view.reset);
}

/// 「有没有字被画到自己的盒子外面」。与 `packages/shared/test/text_fit.dart`
/// 同一套判据 —— 测试文件不进包,跨包引不到,所以这里留一份
/// (`rider_fake_api.dart` 也留了一份,同样的理由)。
///
/// 这类问题**不抛异常**:Flutter 把盒子裁到该有的宽度,然后照样把超出的
/// 字画出去,一声不吭。`takeException()` 是空的,页面看着渲染成功了。
List<String> textsPaintingOutside(WidgetTester tester) {
  final bad = <String>[];
  for (final element in find.byType(Text).evaluate()) {
    final widget = element.widget as Text;
    if (widget.overflow != TextOverflow.visible) continue;
    final para = element.renderObject as RenderParagraph?;
    if (para == null || !para.hasSize) continue;
    final canWrap = widget.softWrap != false && widget.maxLines != 1;
    final need = canWrap
        ? para.getMinIntrinsicWidth(double.infinity)
        : para.getMaxIntrinsicWidth(double.infinity);
    if (need > para.size.width + 0.5) {
      bad.add('「${widget.data}」要 ${need.toStringAsFixed(0)}px,'
          '盒子只有 ${para.size.width.toStringAsFixed(0)}px');
    }
  }
  return bad;
}

/// 订单卡内容区的右边界:屏宽 − 12(卡外边距)− 1(描边)− 12(卡内边距)。
/// 见 `main.dart` 订单卡的 `margin` / `Border.all` / `padding`。
double cardContentRight(double screenWidth) => screenWidth - 25;

/// 有哪些按钮被画到了订单卡外面。
///
/// **`takeException()` 不够。** `RenderFlex` 溢出时
/// `remainingSpace = math.max(0.0, actualSizeDelta)`,`MainAxisAlignment.end`
/// 于是退化成 start,**溢出的是最后一个孩子** —— 也就是「接单」。
/// 而 `Row` 默认 `Clip.none`,它照样被画出来:在 390 上正好压到卡的描边上,
/// 在 360 上有一截跑到屏幕外。两种都不抛第二次异常。
///
/// 所以这里直接量按钮的矩形:凡是右边缘超过卡片内容区的,列出来。
///
/// ⚠️ **只看订单列表里的按钮**([within],默认是 `RefreshIndicator` ——
/// 订单流在它里面,而分段器在它外面)。不限定范围的话会把
/// `SegmentedButton` 内部的三个 `TextButton` 也算进来:它们排在页面级的
/// 12px 边距里,右边缘本来就比卡片内容区远,一测一个假红。
List<String> buttonsOutsideCard(WidgetTester tester, double screenWidth,
    {Finder? within}) {
  final limit = cardContentRight(screenWidth);
  final scope = within ?? find.byType(RefreshIndicator);
  final bad = <String>[];
  for (final type in const [
    FilledButton,
    OutlinedButton,
    TextButton,
    IconButton
  ]) {
    final inScope = scope.evaluate().isEmpty
        ? find.byType(type)
        : find.descendant(of: scope, matching: find.byType(type));
    for (final element in inScope.evaluate()) {
      final box = element.renderObject as RenderBox?;
      if (box == null || !box.hasSize) continue;
      final rect = box.localToGlobal(Offset.zero) & box.size;
      if (rect.width == 0 || rect.height == 0) continue;
      if (rect.right > limit + 0.5) {
        bad.add('$type 右边缘 ${rect.right.toStringAsFixed(0)}px,'
            '卡片内容区只到 ${limit.toStringAsFixed(0)}px');
      }
    }
  }
  return bad;
}
