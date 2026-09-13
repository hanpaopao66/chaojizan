import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/food_safety_records_page.dart';
import 'package:user_app/main.dart' show superZTheme;
import 'package:user_app/voucher_pages.dart';

/// 列表空着的时候也要能下拉刷新。两种坏写法都不报错,往下拉只是没反应:
///
/// - 空状态直接放在 RefreshIndicator 里(SzEmpty 不能滚,下拉收不到滚动通知)——「我的食安投诉」原来这样;
/// - 空了显示 SzEmpty,有数据才套 RefreshIndicator ——「我的券包」原来这样。
///
/// 全仓的静态检查见 scripts/check_refresh_pullable.py,这里挑两个页面验真实行为。
void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'user_app', packageName: 'com.superz.user', version: '0.1.0', buildNumber: '1', buildSignature: ''));
  setUp(ApiClient.resetAppBuildForTest);

  (ApiClient, int Function()) emptyApi(String path) {
    var hits = 0;
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        if (req.url.path == path) hits++;
        return http.Response(jsonEncode(req.url.path == path ? [] : {}), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    return (api, () => hits);
  }

  testWidgets('我的食安投诉:空状态下往下拉,会重新拉一次', (tester) async {
    final (api, hits) = emptyApi('/food-safety/mine');
    await tester.pumpWidget(MaterialApp(theme: superZTheme(Brightness.light), home: FoodSafetyRecordsPage(api: api)));
    await tester.pumpAndSettle();
    expect(find.text('你还没有提交过食安投诉'), findsOneWidget);
    expect(hits(), 1);

    await tester.fling(find.text('你还没有提交过食安投诉'), const Offset(0, 300), 1000);
    await tester.pumpAndSettle();
    expect(hits(), 2, reason: '空状态下拉没触发刷新');
    expect(tester.takeException(), isNull);
  });

  testWidgets('我的券包:一张券都没有时往下拉,会重新拉一次', (tester) async {
    final (api, hits) = emptyApi('/vouchers/purchases/mine');
    await tester.pumpWidget(MaterialApp(theme: superZTheme(Brightness.light), home: MyVouchersPage(api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('还没有券'), findsOneWidget);
    expect(hits(), 1);

    await tester.fling(find.textContaining('还没有券'), const Offset(0, 300), 1000);
    await tester.pumpAndSettle();
    expect(hits(), 2, reason: '空着的时候下拉没触发刷新');
  });
}
