import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/main.dart';
import 'package:user_app/order_filter.dart';

/// 底部导航改版(DEV-PROMPTS-40 #339):「首页 / 消息 / 视频 / 我的」,订单搬家。
///
/// 订单是外卖的命脉,这组测试锁的是「入口没有变深」:
/// - 首页有进行中的单时顶上有一条,一单直达详情;
/// - 订单页是独立页面(带券包),「我的」四格 push 它,筛选带过去。
void main() {
  Map<String, dynamic> order(String no, String status, {String eta = ''}) => {
        'order_no': no,
        'merchant_id': 1,
        'merchant_name': '楼下面馆',
        'status': status,
        'items': [
          {'dish_id': 1, 'name': '牛肉面', 'price_cents': 2000, 'quantity': 1}
        ],
        'food_cents': 2000,
        'delivery_fee_cents': 300,
        'total_cents': 2300,
        'commission_cents': 100,
        'address': '某某小区 1 栋',
        'lat': 30.66,
        'lng': 104.08,
        'created_at': '2026-09-12T12:00:00+08:00',
        if (eta.isNotEmpty) 'eta_at': eta,
      };

  ApiClient fakeApi(List<Map<String, dynamic>> orders) => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final Object payload = switch (req.url.path) {
            '/auth/login' => {
                'token': 'tkn',
                'user_id': 1,
                'name': '张三',
                'role': 'customer',
              },
            '/orders' => orders,
            '/orders/counts' => {'food': [], 'stay': {'total': 0}},
            '/stays/orders/mine' => <Object>[],
            _ => <String, dynamic>{},
          };
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  // package_info_plus 在测试环境没有平台通道,不铺好的话第一个请求永远不返回
  // (见 profile_view_test.dart 同一段注释)
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<ApiClient> loggedIn(List<Map<String, dynamic>> orders) async {
    final api = fakeApi(orders);
    await api.login('13800000001', 'x');
    return api;
  }

  testWidgets('首页进行中订单条:一单写店名和状态、带预计送达', (tester) async {
    final api = await loggedIn([
      order('SZ1', 'picked_up', eta: '2026-09-12T12:40:00+08:00'),
      order('SZ2', 'completed'),
    ]);
    await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: Scaffold(body: ActiveOrdersBar(api: api))));
    await tester.pumpAndSettle();
    expect(find.text('楼下面馆 · 配送中'), findsOneWidget);
    expect(find.textContaining('送达'), findsOneWidget);
  });

  testWidgets('首页进行中订单条:多单时说几单,没有进行中的单时不占位', (tester) async {
    final api = await loggedIn([order('SZ1', 'accepted'), order('SZ2', 'paid')]);
    await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: Scaffold(body: ActiveOrdersBar(api: api))));
    await tester.pumpAndSettle();
    expect(find.text('2 个订单进行中'), findsOneWidget);

    final idle = await loggedIn([order('SZ3', 'completed'), order('SZ4', 'cancelled')]);
    await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: Scaffold(body: ActiveOrdersBar(key: UniqueKey(), api: idle))));
    await tester.pumpAndSettle();
    expect(find.byType(InkWell), findsNothing);
  });

  testWidgets('订单页是独立页面:标题、券包入口都在', (tester) async {
    final api = await loggedIn([order('SZ1', 'completed')]);
    await tester.pumpWidget(MaterialApp(
        theme: superZTheme(Brightness.light),
        home: OrdersPage(api: api, filter: OrderFilter.toReview)));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('我的订单'), findsOneWidget);
    expect(find.text('券包'), findsOneWidget);
  });

  test('main.dart 里没有「切到订单 tab」的残留', () {
    // 订单 tab 已经不存在:再出现 `_tab = 1` 的订单跳转,就是切到了「消息」
    final src = _read('lib/main.dart');
    expect(src.contains("label: '订单'"), isFalse);
    expect(src.contains('_ordersFilter'), isFalse);
    for (final label in ['首页', '消息', '视频', '我的']) {
      expect(src.contains("label: '$label'"), isTrue, reason: label);
    }
  });
}

String _read(String path) => File(path).readAsStringSync();
