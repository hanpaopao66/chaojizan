import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/pool_map_page.dart';
import 'package:superz_shared/superz_shared.dart';

/// 抢单池总览图(#297)。
///
/// 这一页最容易被"优化"坏的地方不是渲染,是**红线**:
/// 某天有人为了"更好用"按配送费给图钉染色、给最划算的那单加个角标,
/// 代码评审时看起来像体验优化,实际是软性派单 —— 平台在替骑手排序。
///
/// 所以这里锁两件事:同一种颜色、同一种图标。想违反就必须显式删测试,
/// 而删测试会在评审里被看见(和 test_labor_guard 同一个思路)。
void main() {
  Order order({
    String no = 'A1',
    String shop = '张记面馆',
    double? lat = 30.66,
    double? lng = 104.08,
    int fee = 500,
  }) =>
      Order.fromJson({
        'order_no': no,
        'status': 'paid',
        'merchant_id': 1,
        'merchant_name': shop,
        'merchant_lat': lat,
        'merchant_lng': lng,
        'items': const [],
        'food_cents': 2000,
        'delivery_fee_cents': fee,
        'total_cents': 2500,
        'address': '春熙路 1 号',
        'lat': 30.67,
        'lng': 104.09,
        'created_at': '2026-08-23T12:00:00+08:00',
      });

  Widget wrap(List<Order> orders, {({double lat, double lng})? me}) =>
      MaterialApp(
        theme: brandTheme(Brightness.light),
        home: RiderPoolMapPage(
          orders: orders,
          riderPosition: ValueNotifier(me),
        ),
      );

  testWidgets('池子空:说"没有单",不说"画不出来"', (t) async {
    await t.pumpWidget(wrap(const []));
    await t.pump();
    expect(find.textContaining('没有单'), findsOneWidget);
  });

  testWidgets('有单但缺商家坐标:说画不出来,不冒充空池子', (t) async {
    // 这两件事混在一起,骑手会以为现在没活干而下线
    await t.pumpWidget(wrap([order(lat: null, lng: null)]));
    await t.pump();
    expect(find.textContaining('画不出来'), findsOneWidget);
    expect(find.textContaining('没有单'), findsNothing);
  });

  testWidgets('没定到位就直说,不假装', (t) async {
    await t.pumpWidget(wrap([order()]));
    await t.pump();
    expect(find.textContaining('还没定到位'), findsOneWidget);
  });

  group('红线:只画点,不替骑手排序', () {
    test('同一家店的多单合成一个点,标出单数', () {
      final page = RiderPoolMapPage(
        orders: [order(no: 'A1'), order(no: 'A2'), order(no: 'A3')],
        riderPosition: ValueNotifier(null),
      );
      final pts = page.debugPickupPoints();
      expect(pts, hasLength(1), reason: '同一处叠三个图钉只看得见一个,反而丢信息');
      expect(pts.single.count, 3);
    });

    test('同名连锁但坐标不同的,不许合成一个点', () {
      final page = RiderPoolMapPage(
        orders: [
          order(no: 'A1', shop: '蜜雪冰城', lat: 30.66, lng: 104.08),
          order(no: 'A2', shop: '蜜雪冰城', lat: 30.70, lng: 104.12),
        ],
        riderPosition: ValueNotifier(null),
      );
      expect(page.debugPickupPoints(), hasLength(2),
          reason: '按店名合会把两个分店画到一个地方去');
    });

    test('配送费差十倍,图钉颜色和图标仍然一样', () {
      final page = RiderPoolMapPage(
        orders: [
          order(no: 'A1', shop: '便宜店', lat: 30.66, lng: 104.08, fee: 300),
          order(no: 'A2', shop: '贵店', lat: 30.68, lng: 104.10, fee: 3000),
        ],
        riderPosition: ValueNotifier(null),
      );
      final pins = page.debugPins(brandTheme(Brightness.light));
      expect(pins.map((p) => p.color).toSet(), hasLength(1),
          reason: '按配送费染色就是在替骑手排序 —— 软性派单');
      expect(pins.map((p) => p.icon).toSet(), hasLength(1));
    });

    test('传进来的顺序不影响画出来的内容', () {
      List<String> names(List<Order> os) => (RiderPoolMapPage(
            orders: os,
            riderPosition: ValueNotifier(null),
          ).debugPickupPoints()..sort((a, b) => a.name.compareTo(b.name)))
          .map((p) => p.name)
          .toList();
      final a = order(no: 'A1', shop: '甲', lat: 30.66, lng: 104.08);
      final b = order(no: 'A2', shop: '乙', lat: 30.68, lng: 104.10);
      expect(names([a, b]), names([b, a]));
    });
  });
}
