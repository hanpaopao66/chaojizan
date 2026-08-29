import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/main.dart';

/// 店铺页排队卡:**手里有号就得自动刷新**。
///
/// ## 为什么这是链路问题不是体验问题
///
/// 「到号了」的通知链是:服务端叫号 → JPush 推送。但没配推送的部署
/// (线上现在就是)推送只写审计日志,而用户端又没有消息中心 ——
/// 不轮询的话,取了号的人**没有任何途径**知道被叫号,
/// 叫号 120 秒宽限一过商家就能标过号。链在这里是断的。
///
/// 判据两条:有号时页面会自己再去拉状态;没号时不拉(白打接口)。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  setUp(() => SharedPreferences.setMockInitialValues({}));

  Merchant shop() => Merchant.fromJson({
        'id': 1,
        'name': '张记面馆',
        'lat': 30.66,
        'lng': 104.08,
        'is_open': true,
        'commission_rate': '0.06',
      });

  testWidgets('有号:排队状态每 15 秒自动刷新', (tester) async {
    var queuePulls = 0;
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        Object? payload;
        switch (req.url.path) {
          case '/auth/login':
            payload = {
              'token': 'tkn',
              'user_id': 1,
              'name': '张三',
              'role': 'customer'
            };
          case '/merchants/1':
            payload = {
              'id': 1,
              'name': '张记面馆',
              'lat': 30.66,
              'lng': 104.08,
              'is_open': true,
              'commission_rate': '0.06',
            };
          case '/queue/merchants/1':
            queuePulls++;
            payload = {'enabled': true, 'table_types': <Object>[]};
          case '/queue/tickets/mine':
            payload = [
              {
                'ticket_no': 'A-005',
                'merchant_id': 1,
                'status': 'waiting',
                'ahead': 3,
                'wait_upper_minutes': 30,
                'passed_count': 0,
              }
            ];
          default:
            payload = req.url.path.contains('dishes')
                ? <Object>[]
                : <String, Object>{};
        }
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await api.login('13800000001', '123456');

    await tester.pumpWidget(
        MaterialApp(home: MenuPage(api: api, merchant: shop())));
    await tester.pump();
    final baseline = queuePulls;
    expect(baseline, greaterThan(0), reason: '进店铺页要拉一次排队现状');

    // 过两个轮询周期:必须又拉过 —— 不刷新的话被叫号了用户不知道
    await tester.pump(const Duration(seconds: 31));
    expect(queuePulls, greaterThan(baseline),
        reason: '手里有号却不自动刷新 —— 没配推送的部署里,'
            '这是用户知道「到号了」的唯一途径');

    // 收尾:把页面拆掉,轮询必须停(dispose 泄漏定时器会让测试框架报错)
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('没号:不轮询(白打接口)', (tester) async {
    var queuePulls = 0;
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        Object? payload;
        switch (req.url.path) {
          case '/auth/login':
            payload = {
              'token': 'tkn',
              'user_id': 1,
              'name': '张三',
              'role': 'customer'
            };
          case '/merchants/1':
            payload = {
              'id': 1,
              'name': '张记面馆',
              'lat': 30.66,
              'lng': 104.08,
              'is_open': true,
              'commission_rate': '0.06',
            };
          case '/queue/merchants/1':
            queuePulls++;
            payload = {'enabled': true, 'table_types': <Object>[]};
          case '/queue/tickets/mine':
            payload = <Object>[];
          default:
            payload = req.url.path.contains('dishes')
                ? <Object>[]
                : <String, Object>{};
        }
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await api.login('13800000001', '123456');

    await tester.pumpWidget(
        MaterialApp(home: MenuPage(api: api, merchant: shop())));
    await tester.pump();
    final baseline = queuePulls;

    await tester.pump(const Duration(seconds: 31));
    expect(queuePulls, baseline, reason: '没号还在轮询 —— 纯浪费');
    await tester.pumpWidget(const SizedBox());
  });
}
