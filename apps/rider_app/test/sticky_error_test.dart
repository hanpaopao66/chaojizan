import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rider_app/reviews_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 顾客评价拉失败之后要能回来。
///
/// 原来出错页没有重试按钮、又不在下拉刷新里,拉成功了 _load 也不清 _error ——
/// 断一次网,这一页就一直是「拿不到评价」,只能退出重进。不报错,只能靠测试钉住
/// (全仓的静态检查见 scripts/check_sticky_error.py、check_refresh_pullable.py)。
void main() {
  setUpRiderTest();

  testWidgets('拿不到评价时往下拉,拉成功就回到评价页', (tester) async {
    var hits = 0;
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        if (req.url.path != '/riders/me/reviews') {
          return http.Response('{}', 200, headers: {'content-type': 'application/json; charset=utf-8'});
        }
        hits++;
        if (hits == 1) {
          return http.Response(jsonEncode({'detail': '网络开小差了'}), 503,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        return http.Response(jsonEncode({'items': [], 'count': 0, 'average': null, 'note': '评价不影响派单'}), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await tester.pumpWidget(MaterialApp(theme: brandTheme(Brightness.light), home: RiderReviewsPage(api: api)));
    await tester.pumpAndSettle();
    expect(find.textContaining('拿不到评价'), findsOneWidget);

    await tester.fling(find.textContaining('拿不到评价'), const Offset(0, 300), 1000);
    await tester.pumpAndSettle();
    expect(hits, 2, reason: '出错页下拉没触发刷新');
    expect(find.textContaining('拿不到评价'), findsNothing, reason: '拉成功了还挂着出错页');
    expect(find.text('还没有顾客评价'), findsOneWidget);
  });
}
