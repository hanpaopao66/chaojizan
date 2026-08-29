import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:rider_app/weekly_page.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 周报里的里程与每公里收入(#309)。
///
/// ## 为什么这两个数放在一起
///
/// 时薪答的是「这段时间值不值」,每公里答的是「这些路值不值」——
/// 顺路单多的一周时薪好看,但公里数也高。骑手要两个数才判断得了。
///
/// ## 口径必须跟着数走
///
/// 这是**计价里程**(取餐点→收货地),不含骑手到店那一段。
/// 他会拿它跟车上里程表对,对不上就会觉得平台在少算 ——
/// 而少的不是里程,是我们没说清这个数不是全程。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() {
    PackageInfo.setMockInitialValues(
      appName: 'rider_app',
      packageName: 'com.superz.rider',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  setUp(() => SharedPreferences.setMockInitialValues({}));

  ApiClient api({int? meters = 213400, int? centsPerKm = 370}) => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          Object? payload;
          if (req.url.path == '/riders/me/weekly-report') {
            payload = {
              'week_start': '2026-08-24',
              'days': List.generate(
                  7, (_) => {'orders': 2, 'earned_cents': 1600,
                      'minutes': 60}),
              'orders': 14,
              'earned_cents': 11200,
              'online_minutes': 420,
              'cents_per_hour': 1600,
              if (meters != null) 'meters': meters,
              if (centsPerKm != null) 'cents_per_km': centsPerKm,
              'distance_note': '计价里程(取餐点→收货地),不含到店那一段;'
                  '所以每公里的数比按里程表算的偏高',
              'fee_parts': <String, dynamic>{},
              'fee_part_labels': <String, dynamic>{},
              'note': '只统计,不考核',
            };
          } else {
            payload = <String, Object>{};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<void> pump(WidgetTester t, ApiClient c) async {
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: RiderWeeklyPage(api: c),
    ));
    await t.pumpAndSettle();
  }

  testWidgets('显示公里数与每公里收入', (t) async {
    await pump(t, api());
    expect(find.textContaining('213.4 公里'), findsOneWidget);
    expect(find.textContaining('每公里 ¥3.7'), findsOneWidget);
  });

  testWidgets('口径写出来 —— 否则骑手会以为平台把他的里程算少了', (t) async {
    await pump(t, api());
    expect(find.textContaining('不含到店'), findsOneWidget,
        reason: '只给数字不给口径,骑手拿它跟里程表一对就会觉得平台在少算');
  });

  testWidgets('里程太短时不给每公里 —— 分母太小算出来是荒唐数字', (t) async {
    await pump(t, api(meters: 800, centsPerKm: null));
    expect(find.textContaining('0.8 公里'), findsOneWidget);
    // 断言要带 ¥:口径说明里那句「所以每公里的数比按里程表算的偏高」
    // 也含「每公里」三个字,只搜词会假命中
    expect(find.textContaining('每公里 ¥'), findsNothing,
        reason: '和时薪同一条理由:分母太小的数他会拿去判断值不值得跑');
  });

  testWidgets('服务端没给这个字段时整块不渲染', (t) async {
    await pump(t, api(meters: null, centsPerKm: null));
    expect(find.textContaining('公里'), findsNothing);
  });
}
