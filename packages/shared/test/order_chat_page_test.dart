import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 订单群(一单一个群:你 + 商家 + 骑手)。
///
/// 锁住的是这几件事:群头写群里有谁、置顶的订单条、发言人按角色标名字(骑手带「· 骑手」)、
/// 快捷回复发到群里(to=group)、老版本私聊标「只有你们两个看得到」、归档后没有输入框和快捷回复。
void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'shared', packageName: 'com.superz.shared', version: '0.1.0', buildNumber: '1', buildSignature: ''));
  setUp(ApiClient.resetAppBuildForTest);

  Map<String, dynamic> payload({bool readonly = false}) => {
        'readonly': readonly,
        'archive_at': null,
        'title': '订单 #123456 · 张记面馆',
        'members': [
          {'role': 'customer', 'name': '你'},
          {'role': 'merchant', 'name': '张记面馆'},
          {'role': 'rider', 'name': '赵师傅'},
        ],
        'order': {
          'order_no': 'SZ123456',
          'status': 'picked_up',
          'status_label': '配送中',
          'items_summary': '牛肉面 ×1、卤蛋 ×2',
          'total_cents': 2600,
          'eta_at': DateTime(2026, 9, 11, 12, 41).toIso8601String(),
        },
        'messages': [
          {'id': 1, 'from': 'merchant', 'to': 'group', 'sender_name': '张记面馆', 'kind': 'text',
            'content': '出餐了,卤蛋多给了一个', 'mine': false, 'private': false,
            'created_at': DateTime.now().toIso8601String()},
          {'id': 2, 'from': 'rider', 'to': 'group', 'sender_name': '赵师傅', 'kind': 'text',
            'content': '到楼下了,放门口还是您下来拿?', 'mine': false, 'private': false,
            'created_at': DateTime.now().toIso8601String()},
          {'id': 3, 'from': 'customer', 'to': 'merchant', 'sender_name': '你', 'kind': 'text',
            'content': '发票抬头写公司', 'mine': true, 'private': true,
            'created_at': DateTime.now().toIso8601String()},
        ],
      };

  Future<List<Map<String, dynamic>>> pump(WidgetTester tester, {bool readonly = false}) async {
    final sent = <Map<String, dynamic>>[];
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        if (req.method == 'POST' && req.url.path == '/orders/SZ123456/messages') {
          sent.add(jsonDecode(req.body) as Map<String, dynamic>);
          return http.Response(jsonEncode({'id': 9, 'created_at': DateTime.now().toIso8601String()}), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        return http.Response(jsonEncode(req.url.path == '/orders/SZ123456/messages' ? payload(readonly: readonly) : {}),
            200, headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: OrderChatPage(api: api, orderNo: 'SZ123456', quickReplies: kCustomerQuickReplies, onOpenOrder: () {}),
    ));
    await tester.pump();
    await tester.pump();
    return sent;
  }

  testWidgets('群头、置顶订单条、按角色标名字', (tester) async {
    await pump(tester);
    expect(find.text('订单 #123456 · 张记面馆'), findsOneWidget);
    expect(find.text('你、张记面馆、赵师傅'), findsOneWidget);
    expect(find.textContaining('置顶消息'), findsOneWidget);
    expect(find.textContaining('牛肉面 ×1、卤蛋 ×2 · ¥26.00'), findsOneWidget);
    expect(find.textContaining('配送中 · 预计 12:41 送达'), findsOneWidget);
    expect(find.text('看订单'), findsOneWidget);
    expect(find.text('张记面馆'), findsOneWidget, reason: '商家的消息标店名');
    expect(find.text('赵师傅 · 骑手'), findsOneWidget, reason: '骑手的消息带「· 骑手」');
    expect(find.textContaining('张记面馆接单 · 赵师傅抢到这一单'), findsOneWidget);
    expect(find.text('只有你们两个看得到'), findsOneWidget, reason: '老版本私聊要标出来');
    expect(find.textContaining('群里不出现手机号'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('快捷回复发到群里', (tester) async {
    final sent = await pump(tester);
    for (final q in kCustomerQuickReplies) {
      expect(find.text(q), findsOneWidget);
    }
    await tester.tap(find.text('我下来拿'));
    await tester.pump();
    await tester.pump();
    expect(sent, [
      {'to': 'group', 'kind': 'quick', 'content': '我下来拿'}
    ]);
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('归档后能翻不能发:没有输入框和快捷回复', (tester) async {
    await pump(tester, readonly: true);
    expect(find.textContaining('出餐了'), findsOneWidget);
    expect(find.byType(TextField), findsNothing);
    expect(find.text('我下来拿'), findsNothing);
    expect(find.textContaining('已归档'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
  });
}
