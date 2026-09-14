import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 商家端、骑手端订单上的「顾客信用 N · 等级」小签(customer_credit.dart)。
///
/// - 只在接单之后的状态显示:服务端在待接单上漏带了,这里也不许冒出来;
/// - 响应里没有分数时不当成 0 分;
/// - 点开是服务端的公式说明(按看的人挑「谁能看到」那一条),不是客户端写死的一段话。
void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'shared', packageName: 'com.superz.shared', version: '0.1.0',
      buildNumber: '1', buildSignature: ''));
  setUp(ApiClient.resetAppBuildForTest);

  Order order(String status, {Object? credit = const {
    'score': 88, 'level': 'fair', 'level_label': '一般'}}) => Order.fromJson({
        'order_no': 'SZ1',
        'merchant_id': 1,
        'status': status,
        'items': [
          {'dish_id': 1, 'name': '牛肉面', 'price_cents': 2000, 'quantity': 1}
        ],
        'food_cents': 2000,
        'delivery_fee_cents': 300,
        'total_cents': 2300,
        'address': '某某小区',
        'lat': 30.66,
        'lng': 104.08,
        'created_at': '2026-09-14T12:00:00+08:00',
        if (credit != null) 'customer_credit': credit,
      });

  Future<void> pumpChip(WidgetTester t, Widget chip) async {
    await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light), home: Scaffold(body: Center(child: chip))));
    await t.pump();
  }

  test('接单之后的状态才显示', () {
    for (final s in ['accepted', 'ready', 'picked_up', 'delivered', 'completed']) {
      expect(customerCreditVisible(order(s)), isTrue, reason: s);
    }
    for (final s in ['pending_payment', 'paid', 'cancelled']) {
      expect(customerCreditVisible(order(s)), isFalse,
          reason: '$s 的单上出现顾客信用分 —— 接单之前看得到就会被拿来挑顾客');
    }
    expect(customerCreditVisible(order('accepted', credit: null)), isFalse);
  });

  test('响应里没有分数不当成 0 分', () {
    expect(CustomerCredit.tryParse(const {}), isNull);
    expect(CustomerCredit.tryParse(null), isNull);
    expect(order('accepted', credit: const {'level': 'good'}).customerCredit, isNull);
    expect(CustomerCredit.tryParse(const {'score': 90, 'level_label': '良好'})!.score, 90);
  });

  testWidgets('已接单:显示分数和等级', (t) async {
    await pumpChip(t, CustomerCreditChip(order: order('ready')));
    expect(find.text('顾客信用 88 · 一般'), findsOneWidget);
  });

  testWidgets('待接单:服务端漏带了也不显示', (t) async {
    await pumpChip(t, CustomerCreditChip(order: order('paid')));
    expect(find.textContaining('顾客信用'), findsNothing);
  });

  testWidgets('点开是服务端的公式说明,按看的人挑那一条', (t) async {
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final payload = req.url.path == '/transparency/credit'
            ? {
                'formula': '信用分 = 90 + 完成订单加分 − 扣分合计',
                'level_rule': '只要没有计分的扣分项,都是「良好」',
                'visibility': [
                  {'who': '商家', 'what': '接单之后看到分数和等级(商家那一条)'},
                  {'who': '骑手', 'what': '接到这一单之后看到分数和等级(骑手那一条)'},
                ],
                'never_used_for': ['不用来自动拒单', '不改派单顺序'],
              }
            : <String, dynamic>{};
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await pumpChip(t, CustomerCreditChip(order: order('picked_up'), api: api, viewer: '骑手'));
    await t.tap(find.text('顾客信用 88 · 一般'));
    await t.pumpAndSettle();
    expect(find.text('顾客信用分'), findsOneWidget);
    expect(find.text('接到这一单之后看到分数和等级(骑手那一条)'), findsOneWidget);
    expect(find.textContaining('商家那一条'), findsNothing);
    expect(find.text('· 不用来自动拒单'), findsOneWidget);
    expect(find.text('· 不改派单顺序'), findsOneWidget);
  });
}
