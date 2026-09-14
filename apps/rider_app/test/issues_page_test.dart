import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rider_app/issues_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 「配送异常与申诉」:裁成退款判的是谁,**以服务端给的 fault 为准**。
///
/// 到店未出餐、餐品不齐是商家那一环的问题 —— 判商家责任、商家承担退款,不算骑手的,
/// 这一页上既不能写成「判骑手责任」,也不能给申诉按钮(服务端那边申诉也会 409)。
/// 老服务端没带 fault 时按种类兜底,和服务端 delivery_fault.MERCHANT_KINDS 同一组。
void main() {
  setUpRiderTest();

  Map<String, dynamic> issue(int id, String kind, String resolution,
          {String? fault}) =>
      {
        'id': id,
        'order_no': 'aaaaaaaaaaaaaaaa00$id',
        'rider_id': 7,
        'kind': kind,
        'note': '',
        'photo_url': '',
        'status': 'resolved',
        'resolution': resolution,
        'resolve_note': '',
        'created_at': '2026-09-14T10:00:00+00:00',
        'resolved_at': '2026-09-14T10:10:00+00:00',
        if (fault != null) 'fault': fault,
      };

  ApiClient fakeApi(List<Map<String, dynamic>> issues) => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final Object payload = switch (req.url.path) {
            '/riders/issues' => issues,
            '/appeals/mine' => const <Map<String, dynamic>>[],
            _ => const <String, dynamic>{},
          };
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<void> pump(WidgetTester t, List<Map<String, dynamic>> issues) async {
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: RiderIssuesPage(api: fakeApi(issues))));
    await t.pumpAndSettle();
  }

  final appealButton = find.widgetWithText(OutlinedButton, '申诉(72 小时内)');

  testWidgets('判商家责任的写明不算你的、没有申诉;判骑手责任的才有', (t) async {
    await pump(t, [
      issue(1, 'not_ready', 'refund', fault: 'merchant'),
      issue(2, 'food_damaged', 'refund', fault: 'rider'),
    ]);
    expect(find.textContaining('到店未出餐'), findsOneWidget);
    expect(find.textContaining('判商家责任,商家承担退款'), findsOneWidget);
    expect(find.textContaining('判骑手责任,平台先行赔付'), findsOneWidget);
    expect(appealButton, findsOneWidget);
  });

  testWidgets('老服务端没带 fault:按种类兜底', (t) async {
    await pump(t, [
      issue(3, 'items_missing', 'refund'),
      issue(4, 'cannot_contact', 'mark_delivered'),
    ]);
    expect(find.textContaining('餐品不齐'), findsOneWidget);
    expect(find.textContaining('判商家责任,商家承担退款'), findsOneWidget);
    expect(appealButton, findsNothing, reason: '商家责任、顾客原因都不是骑手的,不给申诉');
  });

  test('issueFault:服务端给了就用服务端的', () {
    expect(issueFault(issue(5, 'items_missing', 'refund', fault: 'merchant')), 'merchant');
    expect(issueFault(issue(6, 'food_damaged', 'refund')), 'rider');
    expect(issueFault(issue(7, 'not_ready', 'continue_delivery')), '');
    expect(issueFault(issue(8, 'wrong_address', 'mark_delivered')), 'customer');
  });
}
