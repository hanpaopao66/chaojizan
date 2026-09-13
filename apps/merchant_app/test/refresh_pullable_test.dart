import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/hotel/stay_reviews_page.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 住客点评的下拉刷新。两个坑都不报错,只能靠测试钉住:
///
/// 1. 原来「空了显示 SzEmpty,有点评才套下拉刷新」:还没有点评时往下拉没反应,
///    新点评进来只能退出重进(全仓的静态检查见 scripts/check_refresh_pullable.py);
/// 2. 原来下拉写的是箭头 `setState(() => _future = …)`:把 Future 交给了 setState,
///    debug 包直接断言失败(scripts/check_setstate_future.py)。
void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'merchant_app', packageName: 'com.superz.merchant', version: '0.1.0', buildNumber: '1',
      buildSignature: ''));
  setUp(ApiClient.resetAppBuildForTest);

  Future<int Function()> pumpPage(WidgetTester tester, List<Map<String, dynamic>> reviews) async {
    var hits = 0;
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final mine = req.url.path == '/stays/me/reviews';
        if (mine) hits++;
        return http.Response(jsonEncode(mine ? reviews : {}), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await tester.pumpWidget(MaterialApp(theme: brandTheme(Brightness.light), home: StayReviewsPage(api: api)));
    await tester.pumpAndSettle();
    return () => hits;
  }

  testWidgets('还没有点评时往下拉,会重新拉一次', (tester) async {
    final hits = await pumpPage(tester, []);
    expect(find.textContaining('还没有住客点评'), findsOneWidget);
    expect(hits(), 1);

    await tester.fling(find.textContaining('还没有住客点评'), const Offset(0, 300), 1000);
    await tester.pumpAndSettle();
    expect(hits(), 2, reason: '空着的时候下拉没触发刷新');
  });

  testWidgets('有点评时往下拉:重新拉一次,不抛异常', (tester) async {
    final hits = await pumpPage(tester, [
      {'id': 1, 'rating': 5, 'comment': '床很软', 'reviewer_name': '住客', 'created_at': '2026-09-01T10:00:00'},
    ]);
    expect(find.textContaining('床很软'), findsOneWidget);

    await tester.fling(find.textContaining('床很软'), const Offset(0, 300), 1000);
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(hits(), 2);
  });
}
