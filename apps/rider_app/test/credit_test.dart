import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rider_app/hall_widgets.dart';
import 'package:rider_app/main.dart';
import 'package:rider_app/task_panel.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 骑手端的顾客信用分、商家信用分:**接到这一单之后**才看得到,抢单大厅里没有。
///
/// 服务端只给「这一单的骑手」带分数(credit.visible_parties:池子里的单 rider_id
/// 是空的,谁都不是它的骑手)。大厅那条用例故意让假服务端在池子里**漏带**一次,
/// 守的是客户端的兜底 —— 抢单前看得到,就会被拿来挑顾客、挑店;
/// 而派单和排序里本来就没有它。跑腿单没有商家,也就没有商家的分。
void main() {
  setUpRiderTest();

  const credit = {'score': 76, 'level': 'fair', 'level_label': '一般'};

  Map<String, dynamic> orderJson({required String status, int? riderId,
      Map<String, Object>? customerCredit, Map<String, Object>? merchantCredit,
      String kind = 'food'}) => {
        'order_no': 'A1234567890abcdef',
        'status': status,
        'order_kind': kind,
        if (merchantCredit != null) 'merchant_credit': merchantCredit,
        'merchant_id': 1,
        'rider_id': riderId,
        'merchant_name': '张记面馆',
        'merchant_address': '春熙路 8 号',
        'merchant_lat': 30.6598,
        'merchant_lng': 104.0810,
        'items': [
          {'name': '红烧牛肉面', 'quantity': 1, 'price_cents': 2000},
        ],
        'food_cents': 2000,
        'delivery_fee_cents': 500,
        'tip_cents': 0,
        'total_cents': 2500,
        'address': '天府三街 100 号 2 单元 501',
        'lat': 30.6800,
        'lng': 104.0823,
        'created_at': '2026-09-14T12:00:00+08:00',
        'distance_m': 1700,
        'trip_m': 2300,
        'distance_source': 'route',
        'est_minutes': 18.0,
        if (customerCredit != null) 'customer_credit': customerCredit,
      };

  Future<void> pumpTask(WidgetTester t, List<Order> orders) async {
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(
        body: TaskPanel(
          orders: orders,
          riderPosition: ValueNotifier(null),
          actionsFor: (_) => const [],
          alertsFor: (_) => const [],
          unread: const {},
          onChat: (_) {},
          onCall: (_) {},
          onSos: () {},
          onNavigate: (_) {},
          onGoHall: () {},
          onRefresh: () async {},
        ),
      ),
    ));
    await t.pump();
  }

  testWidgets('接到这一单:任务卡上有顾客信用分(只有分数和等级)', (t) async {
    await pumpTask(t, [
      Order.fromJson(orderJson(status: 'accepted', riderId: 42, customerCredit: credit)),
    ]);
    expect(find.text('顾客信用 76 · 一般'), findsOneWidget);
  });

  const shop = {'score': 97, 'level': 'good', 'level_label': '良好'};

  testWidgets('接到这一单:任务卡上也有商家信用分', (t) async {
    await pumpTask(t, [
      Order.fromJson(orderJson(status: 'ready', riderId: 42, customerCredit: credit,
          merchantCredit: shop)),
    ]);
    expect(find.text('顾客信用 76 · 一般'), findsOneWidget);
    expect(find.text('商家信用 97 · 良好'), findsOneWidget);
  });

  testWidgets('跑腿单没有商家:服务端漏带了也不显示商家的分', (t) async {
    await pumpTask(t, [
      Order.fromJson(orderJson(status: 'picked_up', riderId: 42, customerCredit: credit,
          merchantCredit: shop, kind: 'errand_buy')),
    ]);
    expect(find.text('顾客信用 76 · 一般'), findsOneWidget, reason: '任务卡没渲染出来');
    expect(find.textContaining('商家信用'), findsNothing);
  });

  testWidgets('配送中同样有;服务端没给就不留空小签', (t) async {
    await pumpTask(t, [
      Order.fromJson(orderJson(status: 'picked_up', riderId: 42, customerCredit: credit)),
    ]);
    expect(find.text('顾客信用 76 · 一般'), findsOneWidget);
    await pumpTask(t, [Order.fromJson(orderJson(status: 'picked_up', riderId: 42))]);
    expect(find.textContaining('顾客信用'), findsNothing);
  });

  testWidgets('抢单大厅:服务端在池子里漏带了,卡上也不显示', (t) async {
    final pool = [orderJson(status: 'ready', customerCredit: credit,
        merchantCredit: const {'score': 97, 'level': 'good', 'level_label': '良好'})];
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final p = req.url.path;
        Object? payload;
        if (p == '/riders/available-orders') {
          payload = {'items': pool, 'filtered_by_prefs': 0, 'has_location': true,
                     'stale_prefs': []};
        } else if (p == '/riders/profile') {
          payload = {'status': 'approved', 'name': '测试骑手',
                     'rating_avg': 5.0, 'rating_count': 0};
        } else if (p.endsWith('s') || p.contains('orders')) {
          payload = [];
        } else {
          payload = {};
        }
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light), home: RiderHomePage(api: api)));
    await t.pumpAndSettle();
    // 上线才拉抢单池(同 grab_card_test 的做法)
    final pill = find.byType(SzStatePill);
    if (pill.evaluate().isNotEmpty) {
      await t.tap(pill.first);
      await t.pumpAndSettle();
    }
    await t.pump(const Duration(seconds: 6));
    await t.pumpAndSettle();
    expect(find.byType(HallOrderCard), findsWidgets,
        reason: '抢单卡没渲染出来,下面这条断言就是空的');
    expect(find.textContaining('顾客信用'), findsNothing,
        reason: '抢单大厅里出现了顾客信用分 —— 抢单前看得到就会被拿来挑顾客');
    expect(find.textContaining('商家信用'), findsNothing,
        reason: '抢单大厅里出现了商家信用分 —— 抢单前看得到就会被拿来挑店');
    await t.pumpWidget(const SizedBox());
    await t.pump();
  });
}
