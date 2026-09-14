import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/main.dart';
import 'package:merchant_app/merchant_ui.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'order_fake_api.dart';
import 'shop_fake_api.dart';

/// 出餐之前还没骑手接单:订单卡上提醒「建议骑手接单后再出餐,或改为自己配送」。
///
/// 2026-09-15 起没人接单、到点被取消的单,已出餐的餐损平台不赔(服务端 auto_flow)——
/// 这句提醒是商家唯一能事前知道的地方。它该出现在「已接单、平台配送、还没骑手」的卡上,
/// 别的卡上不该出现(自己送、到店自取的单不等骑手;骑手接了就不用再提醒)。
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

  final acceptedAt = DateTime.now()
      .subtract(const Duration(minutes: 3))
      .toUtc()
      .toIso8601String();

  Future<void> pumpOngoing(WidgetTester t, Map<String, dynamic> order) async {
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light, density: SzDensity.operate, accentTone: 0),
      home: MerchantHomePage(
          api: orderFakeApi(pages: [order], todos: {'pending_orders': 0}),
          shop: Merchant.fromJson(shopJson())),
    ));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
    final bar = find.byType(NavigationBar);
    final nav = bar.evaluate().isNotEmpty ? bar : find.byType(NavigationRail);
    await t.tap(find.descendant(of: nav, matching: find.text('订单')));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
    await t.tap(find.descendant(
        of: find.byType(SegmentedButton<int>), matching: find.textContaining('进行中')));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
  }

  Future<void> teardown(WidgetTester t) async {
    await t.pumpWidget(const SizedBox());
    await t.pump();
  }

  testWidgets('已接单、平台配送、还没骑手:出餐按钮上方提醒', (t) async {
    await pumpOngoing(t, orderJson(no: 'SZNR1', status: 'accepted', accepted: acceptedAt));
    expect(find.text('出餐完成'), findsOneWidget, reason: '进行中卡没渲染出来');
    expect(find.text(kNoRiderCookHint), findsOneWidget,
        reason: '还没骑手接单就出餐,到点没人接被取消,餐损平台不赔 —— 得事前说');
    await teardown(t);
  });

  testWidgets('骑手已经接了:不提醒', (t) async {
    await pumpOngoing(
        t, orderJson(no: 'SZNR2', status: 'accepted', accepted: acceptedAt, riderId: 42));
    expect(find.text('出餐完成'), findsOneWidget);
    expect(find.text(kNoRiderCookHint), findsNothing);
    await teardown(t);
  });

  testWidgets('自己送、到店自取:不等骑手,不提醒', (t) async {
    await pumpOngoing(t, orderJson(
        no: 'SZNR3', status: 'accepted', accepted: acceptedAt, selfDelivery: true));
    expect(find.text(kNoRiderCookHint), findsNothing);
    await teardown(t);
    await pumpOngoing(
        t, orderJson(no: 'SZNR4', status: 'accepted', accepted: acceptedAt, pickup: true));
    expect(find.text(kNoRiderCookHint), findsNothing);
    await teardown(t);
  });

  test('判据:只看已接单、平台配送、还没骑手、不是追加单', () {
    Order o(Map<String, dynamic> j) => Order.fromJson(j);
    expect(showNoRiderCookHint(o(orderJson(no: 'A', status: 'accepted'))), isTrue);
    expect(showNoRiderCookHint(o(orderJson(no: 'B', status: 'ready'))), isFalse,
        reason: '已经出了餐,再说「出餐前」就晚了');
    expect(showNoRiderCookHint(o(orderJson(no: 'C', status: 'paid'))), isFalse);
    expect(showNoRiderCookHint(o({...orderJson(no: 'D', status: 'accepted'),
      'parent_order_no': 'SZPARENT0001'})), isFalse, reason: '追加单随原单,原单上已经提醒过');
    expect(kNoRiderCookHint, contains('建议骑手接单后再出餐,或改为自己配送'));
  });
}
