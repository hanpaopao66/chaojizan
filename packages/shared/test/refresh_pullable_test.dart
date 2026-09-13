import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 列表空着的时候也要能下拉刷新。
///
/// 常见的坏写法是「空了显示 SzEmpty,有数据才套 RefreshIndicator」:空着的时候往下拉没反应,
/// 新数据进来只能退出重进。不报错,只能靠测试和 scripts/check_refresh_pullable.py 钉住。
void main() {
  setUpAll(() => PackageInfo.setMockInitialValues(
      appName: 'shared', packageName: 'com.superz.shared', version: '0.1.0', buildNumber: '1', buildSignature: ''));
  setUp(ApiClient.resetAppBuildForTest);

  testWidgets('SzRefreshableEmpty:往下拉会刷新,内容照旧在正中', (tester) async {
    var refreshed = 0;
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(
        body: SzRefreshableEmpty(
          onRefresh: () async => refreshed++,
          child: const Text('还没有'),
        ),
      ),
    ));
    // 和原来直接放一个居中的 SzEmpty 看起来一样(测试默认 800×600)
    expect(tester.getCenter(find.text('还没有')).dy, closeTo(300, 1));

    await tester.fling(find.text('还没有'), const Offset(0, 300), 1000);
    await tester.pumpAndSettle();
    expect(refreshed, 1);
  });

  testWidgets('客服工单:一个工单都没有时往下拉,会重新拉一次', (tester) async {
    var hits = 0;
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        if (req.url.path == '/tickets/mine') hits++;
        return http.Response(jsonEncode(req.url.path == '/tickets/mine' ? [] : {}), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await tester.pumpWidget(MaterialApp(theme: brandTheme(Brightness.light), home: SupportPage(api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('有任何问题都可以找平台'), findsOneWidget);
    expect(hits, 1);

    await tester.fling(find.textContaining('有任何问题都可以找平台'), const Offset(0, 300), 1000);
    await tester.pumpAndSettle();
    expect(hits, 2, reason: '空着的时候下拉没触发刷新');
  });
}
