import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 「我的信用分」页在商家端、骑手端(credit.dart 的 CreditPage,三端共用一页)。
///
/// 顾客那一份的完整走法在 apps/user_app/test/credit_page_test.dart;这里守的是
/// 「同一页换一种角色」时容易漏的几件事:
///
/// - 头上「谁看得到」那一句是服务端给的(商家的和顾客的不一样),不是写死的顾客那句;
/// - 申诉框里「改判会怎样」那一句是服务端给的(商家原通道改判是补回净额,不是退钱给你);
/// - 商家的售后判责原通道打的是 `/appeals` 的 after_sale;骑手的售后判责没有原通道,
///   打 `/credit/me/appeals`,带着种类 after_sale_fault。
void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'shared', packageName: 'com.superz.shared', version: '0.1.0',
      buildNumber: '1', buildSignature: ''));
  setUp(ApiClient.resetAppBuildForTest);

  const after = '申诉成立后,这一条不再计分,分数马上重算';

  Map<String, dynamic> merchant() => {
        'role': 'merchant',
        'role_label': '商家',
        'score': 90,
        'level': 'good',
        'level_label': '良好',
        'base': 90,
        'plus': 10,
        'minus': 10,
        'formula_line': '90 + 10 − 10 = 90',
        'seen_by': '你接了单的顾客、接到这一单的骑手只看得到分数和等级,看不到下面这些明细;'
            '店铺页、搜索、排序里没有它。',
        'window_days': 180,
        'orders': {'count': 431, 'points': 10, 'cap': 10, 'recent': []},
        'deductions': [
          {
            'kind': 'after_sale_fault',
            'record_id': 31,
            'title': '你拒绝的售后,顾客申诉后平台复核判为商家责任',
            'order_no': 'aaaaaaaaaaaa77ab12',
            'note': '复核:照片可证,该售后应当受理',
            'points': -10,
            'at': '2026-09-12T12:00:00+00:00',
            'expires_at': '2027-03-11T12:00:00+00:00',
            'appeal': {
              'via': 'appeal', 'target_type': 'after_sale', 'target_id': 31,
              'state': '', 'label': '申诉', 'note': '', 'after': after,
              'confirm': '平台会重新复核这次判定。改判的话,这一条不再计分,被冲掉的那笔净额补回来。',
            },
          },
        ],
        'excluded': [],
        'rules': {
          'formula': '信用分 = 90 + 完成订单加分 − 扣分合计,结果限定在 0–100 之间。只看最近 180 天',
          'visibility': [
            {'who': '顾客', 'what': '你接单之后,在这一单上看到分数和等级,看不到明细'},
          ],
        },
      };

  Map<String, dynamic> rider() => {
        ...merchant(),
        'role': 'rider',
        'role_label': '骑手',
        'seen_by': '你接到的单上,顾客和商家只看得到分数和等级,看不到下面这些明细;抢单大厅里没有它。',
        'deductions': [
          {
            'kind': 'after_sale_fault',
            'record_id': 52,
            'title': '顾客售后,平台仲裁判为骑手责任(洒餐、丢餐等,平台先行赔付)',
            'order_no': 'bbbbbbbbbbbb33cd44',
            'note': '',
            'points': -10,
            'at': '2026-09-12T12:00:00+00:00',
            'expires_at': '2027-03-11T12:00:00+00:00',
            'appeal': {
              'via': 'ticket', 'target_type': '', 'target_id': 0, 'state': '',
              'label': '申诉(客服工单)', 'note': '', 'after': after,
              'confirm': '会转给平台客服,回复在「联系平台客服」里看得到。$after',
            },
          },
        ],
      };

  final calls = <(String, String, Map<String, dynamic>)>[];

  ApiClient fakeApi(Map<String, dynamic> Function() me) => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final body = req.body.isEmpty
              ? <String, dynamic>{}
              : (jsonDecode(req.body) as Map).cast<String, dynamic>();
          calls.add((req.method, req.url.path, body));
          final payload = switch (req.url.path) {
            '/credit/me' => me(),
            '/appeals' => {'id': 2, 'status': 'open'},
            '/credit/me/appeals' => {'id': 1, 'status': 'open', 'ticket_id': 9},
            _ => <String, dynamic>{},
          };
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<void> pumpPage(WidgetTester t, ApiClient api) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 2400) * 3.0;
    addTearDown(t.view.reset);
    calls.clear();
    await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light), home: CreditPage(api: api)));
    await t.pumpAndSettle();
  }

  bool hasText(String needle) => find
      .byType(Text)
      .evaluate()
      .map((e) => (e.widget as Text).data ?? '')
      .any((s) => s.contains(needle));

  testWidgets('商家:头上那一句是服务端给的,不是顾客那句', (t) async {
    await pumpPage(t, fakeApi(merchant));
    expect(hasText('你接了单的顾客、接到这一单的骑手只看得到分数和等级'), isTrue);
    expect(hasText('接了你单的商家'), isFalse, reason: '商家的页面上出现了顾客那一句');
    expect(hasText('完成订单 431 单'), isTrue);
    expect(hasText('你拒绝的售后,顾客申诉后平台复核判为商家责任'), isTrue);
    expect(hasText('订单尾号 77ab12'), isTrue);
  });

  testWidgets('商家:售后判责走原通道 after_sale,申诉框里说的是补回净额', (t) async {
    await pumpPage(t, fakeApi(merchant));
    await t.tap(find.widgetWithText(TextButton, '申诉'));
    await t.pumpAndSettle();
    expect(find.textContaining('被冲掉的那笔净额补回来'), findsOneWidget);
    expect(find.textContaining('钱也会原路退回'), findsNothing);
    await t.enterText(find.byType(TextField), '出餐前拍过照,盒子是完好的');
    await t.tap(find.widgetWithText(FilledButton, '提交申诉'));
    await t.pumpAndSettle();
    final post = calls.where((c) => c.$1 == 'POST' && c.$2 == '/appeals').toList();
    expect(post, hasLength(1));
    expect(post.first.$3['target_type'], 'after_sale');
    expect(post.first.$3['target_id'], 31);
    expect(calls.where((c) => c.$2 == '/credit/me/appeals'), isEmpty);
  });

  testWidgets('骑手:售后判责没有原通道,走工单,带着种类和记录', (t) async {
    await pumpPage(t, fakeApi(rider));
    expect(hasText('抢单大厅里没有它'), isTrue);
    await t.tap(find.widgetWithText(TextButton, '申诉(客服工单)'));
    await t.pumpAndSettle();
    expect(find.textContaining('联系平台客服'), findsWidgets);
    await t.enterText(find.byType(TextField), '取餐时餐盒已经裂了,我拍了照');
    await t.tap(find.widgetWithText(FilledButton, '提交申诉'));
    await t.pumpAndSettle();
    final post = calls.where((c) => c.$1 == 'POST' && c.$2 == '/credit/me/appeals').toList();
    expect(post, hasLength(1));
    expect(post.first.$3['kind'], 'after_sale_fault');
    expect(post.first.$3['record_id'], 52);
    expect(calls.where((c) => c.$2 == '/appeals'), isEmpty);
  });

  testWidgets('理由不够 5 个字不提交', (t) async {
    await pumpPage(t, fakeApi(rider));
    await t.tap(find.widgetWithText(TextButton, '申诉(客服工单)'));
    await t.pumpAndSettle();
    await t.enterText(find.byType(TextField), '冤枉');
    await t.tap(find.widgetWithText(FilledButton, '提交申诉'));
    await t.pumpAndSettle();
    expect(calls.where((c) => c.$1 == 'POST'), isEmpty);
    expect(find.text('理由至少写 5 个字,复核的人要有东西可看'), findsOneWidget);
  });
}
