import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 订单上的「顾客信用 N · 等级」「商家信用 …」「骑手信用 …」小签(credit.dart)。
///
/// - 只在接单之后的状态显示:服务端在待接单上漏带了,这里也不许冒出来;
/// - 商家的分跑腿单上没有(挂的是虚拟服务主体);骑手的分要这一单真有骑手;
/// - 响应里没有分数时不当成 0 分;
/// - 点开是服务端的公式说明 —— 读的是**被看的那一方**那一份,按看的人挑「谁能看到」那一条。
void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'shared', packageName: 'com.superz.shared', version: '0.1.0',
      buildNumber: '1', buildSignature: ''));
  setUp(ApiClient.resetAppBuildForTest);

  Order order(String status, {Object? credit = const {
    'score': 88, 'level': 'fair', 'level_label': '一般'},
    Object? merchantCredit, Object? riderCredit, int? riderId,
    String kind = 'food'}) => Order.fromJson({
        'order_no': 'SZ1',
        'merchant_id': 1,
        'status': status,
        'order_kind': kind,
        'rider_id': riderId,
        if (merchantCredit != null) 'merchant_credit': merchantCredit,
        if (riderCredit != null) 'rider_credit': riderCredit,
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
    expect(CreditBrief.tryParse(const {}), isNull);
    expect(CreditBrief.tryParse(null), isNull);
    expect(order('accepted', credit: const {'level': 'good'}).customerCredit, isNull);
    expect(CreditBrief.tryParse(const {'score': 90, 'level_label': '良好'})!.score, 90);
  });

  testWidgets('已接单:显示分数和等级', (t) async {
    await pumpChip(t, CustomerCreditChip(order: order('ready')));
    expect(find.text('顾客信用 88 · 一般'), findsOneWidget);
  });

  testWidgets('待接单:服务端漏带了也不显示', (t) async {
    await pumpChip(t, CustomerCreditChip(order: order('paid')));
    expect(find.textContaining('顾客信用'), findsNothing);
  });

  const m = {'score': 95, 'level': 'good', 'level_label': '良好'};
  const r = {'score': 82, 'level': 'fair', 'level_label': '一般'};

  test('商家、骑手的分同样只在接单之后显示', () {
    for (final s in ['accepted', 'ready', 'picked_up', 'delivered', 'completed']) {
      final o = order(s, merchantCredit: m, riderCredit: r, riderId: 42);
      expect(merchantCreditVisible(o), isTrue, reason: s);
      expect(riderCreditVisible(o), isTrue, reason: s);
    }
    for (final s in ['pending_payment', 'paid', 'cancelled']) {
      final o = order(s, merchantCredit: m, riderCredit: r, riderId: 42);
      expect(merchantCreditVisible(o), isFalse, reason: s);
      expect(riderCreditVisible(o), isFalse, reason: s);
    }
  });

  test('没有骑手的单不显示骑手的分;跑腿单不显示商家的分', () {
    expect(riderCreditVisible(order('accepted', riderCredit: r)), isFalse,
        reason: '还没有骑手接单 —— 服务端漏带了也不许冒出来');
    final errand = order('picked_up', kind: 'errand_buy', merchantCredit: m,
        riderCredit: r, riderId: 42);
    expect(merchantCreditVisible(errand), isFalse, reason: '跑腿单没有商家');
    expect(riderCreditVisible(errand), isTrue);
  });

  testWidgets('三种小签各写各的名字', (t) async {
    final o = order('picked_up', merchantCredit: m, riderCredit: r, riderId: 42);
    await pumpChip(t, Column(children: [
      CustomerCreditChip(order: o),
      MerchantCreditChip(order: o),
      RiderCreditChip(order: o),
    ]));
    expect(find.text('顾客信用 88 · 一般'), findsOneWidget);
    expect(find.text('商家信用 95 · 良好'), findsOneWidget);
    expect(find.text('骑手信用 82 · 一般'), findsOneWidget);
  });

  testWidgets('点开商家的小签:读商家那一份公式,挑顾客那一条', (t) async {
    final roles = <String?>[];
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        roles.add(req.url.queryParameters['role']);
        return http.Response(jsonEncode({
          'title': '商家信用分',
          'formula': '信用分 = 90 + 完成订单加分 − 扣分合计',
          'visibility': [
            {'who': '顾客', 'what': '你接单之后看到分数和等级(顾客那一条)'},
            {'who': '骑手', 'what': '接到这一单之后看到(骑手那一条)'},
          ],
          'never_used_for': ['不进店铺排序、曝光和搜索'],
        }), 200, headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await pumpChip(t, MerchantCreditChip(order: order('ready', merchantCredit: m), api: api));
    await t.tap(find.text('商家信用 95 · 良好'));
    await t.pumpAndSettle();
    expect(roles, everyElement('merchant'), reason: '说明读的不是被看的那一方那一份');
    expect(find.text('商家信用分'), findsOneWidget);
    expect(find.text('你接单之后看到分数和等级(顾客那一条)'), findsOneWidget);
    expect(find.textContaining('骑手那一条'), findsNothing);
    expect(find.text('· 不进店铺排序、曝光和搜索'), findsOneWidget);
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
