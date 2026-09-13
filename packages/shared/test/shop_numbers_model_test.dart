import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 店铺页上几个数的解析:实际起送价、全店评价概览、点过某道菜的订单的评价。
void main() {
  Map<String, dynamic> shop(Map<String, dynamic> extra) => {
        'id': 7,
        'name': '张记面馆',
        'lat': 30.0,
        'lng': 104.0,
        'is_open': true,
        ...extra,
      };

  group('实际起送价', () {
    test('服务端给了就用服务端的(含平台下限)', () {
      final m = Merchant.fromJson(
          shop({'min_order_cents': 0, 'effective_min_order_cents': 1500}));
      expect(m.minOrderCents, 0);
      expect(m.effectiveMinOrderCents, 1500);
    });

    test('老服务端不给这个字段:退回商家自设的,和字段出现之前一样', () {
      final m = Merchant.fromJson(shop({'min_order_cents': 2000}));
      expect(m.effectiveMinOrderCents, 2000);
      expect(Merchant.fromJson(shop({})).effectiveMinOrderCents, 0);
    });
  });

  test('评价概览:星级按 1–5 补齐,没有评价时均分是空不是 0', () {
    final o = ReviewOverview.fromJson({
      'count': 3,
      'avg': 4.3,
      'stars': {'5': 2, '3': 1},
      'photo': 1,
      'good': 2,
      'bad': 0,
      'append': 0,
    });
    expect(o.stars, {1: 0, 2: 0, 3: 1, 4: 0, 5: 2});
    expect(o.avg, 4.3);
    final empty = ReviewOverview.fromJson({'count': 0, 'avg': null});
    expect(empty.avg, isNull);
    expect(empty.stars.values.every((n) => n == 0), isTrue);
  });

  test('点过这道菜的订单:单数、好评数、最近几条', () {
    final r = DishOrderReviews.fromJson({
      'count': 5,
      'good': 4,
      'recent': [
        {
          'id': 9,
          'merchant_rating': 5,
          'comment': '面很筋道',
          'customer_name': '王**',
          'created_at': '2026-09-10T04:00:00Z',
        },
      ],
    });
    expect(r.count, 5);
    expect(r.good, 4);
    expect(r.recent.single.comment, '面很筋道');
  });
}
