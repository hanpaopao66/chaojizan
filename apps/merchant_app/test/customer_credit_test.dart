import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/main.dart';
import 'package:merchant_app/new_order_page.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'order_fake_api.dart';
import 'shop_fake_api.dart';

/// 商家端订单卡上的顾客信用分。
///
/// 商家端没有订单详情页,卡片就是全部 —— 所以「已接单的订单详情里看得到」
/// 落在进行中 / 历史栏的卡上;「接单之前看不到」落在待接单栏的卡和点开的新单详情上。
///
/// 服务端只给接过的单带分数(customer_credit.counterpart_may_see);这里的待接单用例
/// 故意让假服务端**漏带**一次,守的是客户端那一道兜底:接单之前看得到,就会被拿来挑顾客。
void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'merchant_app',
      packageName: 'com.superz.merchant',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });
  setUp(() => SharedPreferences.setMockInitialValues({}));

  const credit = {'score': 76, 'level': 'fair', 'level_label': '一般'};
  final acceptedAt = DateTime.now()
      .subtract(const Duration(minutes: 3))
      .toUtc()
      .toIso8601String();

  Future<void> openTab(WidgetTester t, String label) async {
    final bar = find.byType(NavigationBar);
    final nav = bar.evaluate().isNotEmpty ? bar : find.byType(NavigationRail);
    await t.tap(find.descendant(of: nav, matching: find.text(label)));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
  }

  Future<void> pumpOrders(WidgetTester t, ApiClient api) async {
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light, density: SzDensity.operate, accentTone: 0),
      home: MerchantHomePage(api: api, shop: Merchant.fromJson(shopJson())),
    ));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
    await openTab(t, '订单');
  }

  Future<void> segment(WidgetTester t, String prefix) async {
    await t.tap(find.descendant(
        of: find.byType(SegmentedButton<int>), matching: find.textContaining(prefix)));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
  }

  Future<void> teardown(WidgetTester t) async {
    await t.pumpWidget(const SizedBox());
    await t.pump();
  }

  testWidgets('已接单的卡上有顾客信用分(只有分数和等级)', (t) async {
    final api = orderFakeApi(pages: [
      {...orderJson(no: 'SZACC1', status: 'accepted', accepted: acceptedAt),
       'customer_credit': credit},
    ], todos: {'pending_orders': 0});
    await pumpOrders(t, api);
    await segment(t, '进行中');
    expect(find.text('顾客信用 76 · 一般'), findsOneWidget);
    await teardown(t);
  });

  testWidgets('出餐之后、已完成的历史单上也有', (t) async {
    final api = orderFakeApi(pages: [
      {...orderJson(no: 'SZDONE1', status: 'completed', accepted: acceptedAt),
       'customer_credit': credit},
    ], todos: {'pending_orders': 0});
    await pumpOrders(t, api);
    await segment(t, '历史');
    expect(find.text('顾客信用 76 · 一般'), findsOneWidget);
    await teardown(t);
  });

  testWidgets('待接单的卡和新单详情里没有 —— 服务端漏带了也不显示', (t) async {
    final api = orderFakeApi(pages: [
      {...orderJson(no: 'SZPAID1'), 'customer_credit': credit},
    ], todos: {'pending_orders': 1});
    await pumpOrders(t, api);
    expect(find.text('接单 · 15 分出餐'), findsOneWidget, reason: '待接单卡没渲染出来,下面的断言是空的');
    expect(find.textContaining('顾客信用'), findsNothing);
    // 点开新单详情(设计稿 6c)
    await t.tap(find.textContaining('红烧牛肉面').first);
    await t.pumpAndSettle();
    expect(find.byType(NewOrderPage), findsOneWidget);
    expect(find.textContaining('顾客信用'), findsNothing);
    await teardown(t);
  });

  testWidgets('取消了的单不显示', (t) async {
    final api = orderFakeApi(pages: [
      {...orderJson(no: 'SZCXL1', status: 'cancelled', accepted: acceptedAt,
                    cancelReason: '顾客取消'),
       'customer_credit': credit},
    ], todos: {'pending_orders': 0});
    await pumpOrders(t, api);
    await segment(t, '历史');
    expect(find.textContaining('取消原因'), findsOneWidget, reason: '历史卡没渲染出来');
    expect(find.textContaining('顾客信用'), findsNothing);
    await teardown(t);
  });

  testWidgets('服务端没给分数的已接单卡上不留空小签', (t) async {
    final api = orderFakeApi(pages: [
      orderJson(no: 'SZACC2', status: 'accepted', accepted: acceptedAt),
    ], todos: {'pending_orders': 0});
    await pumpOrders(t, api);
    await segment(t, '进行中');
    expect(find.text('出餐完成'), findsOneWidget, reason: '进行中卡没渲染出来');
    expect(find.textContaining('顾客信用'), findsNothing);
    await teardown(t);
  });
}
