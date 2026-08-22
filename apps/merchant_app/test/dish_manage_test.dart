import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/dish_manage_page.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'order_fake_api.dart' show setPhoneViewport;

/// 菜品页:榜单说的时间窗必须是服务端真正算的那个窗。
///
/// ## 「本月」在这个 App 里被用成了两个意思
///
/// 菜品页的销量来自 `/merchants/me/dishes`,服务端 `_DISH_SALES_SQL` 写的是
/// `o.created_at >= now() - interval '30 days'` —— **滚动 30 天**。
/// 而同一个 App 的对账页「本月已完成 N 单」用的是 `/me/commission-tier` 的
/// `this_month_completed`,那是 `now_bj.replace(day=1)` 起算的**自然月**。
///
/// 每月 1 号这两个窗差得最远:自然月只有 1 天,滚动窗有 30 天。
/// 商家拿这个榜单决定下架哪道菜,窗口说错了,决定就是错的。
void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'merchant_app',
      packageName: 'com.superz.merchant',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Map<String, dynamic> dishJson(int id,
          {required String name,
          String category = '招牌',
          int monthly = 120,
          bool onSale = true}) =>
      {
        'id': id,
        'merchant_id': 1,
        'name': name,
        'category': category,
        'price_cents': 2800,
        'cost_cents': 900,
        'stock': 42,
        'sold_out_today': false,
        'is_on_sale': onSale,
        'image_url': 'https://x/y.jpg',
        'sort': id,
        'monthly_sales': monthly,
      };

  ApiClient dishFakeApi(List<Map<String, dynamic>> dishes) => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final payload = req.url.path == '/merchants/me/dishes'
              ? dishes
              : <String, dynamic>{};
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<void> pumpDishes(
      WidgetTester t, List<Map<String, dynamic>> dishes) async {
    setPhoneViewport(t, const Size(390, 1800));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light, density: SzDensity.operate),
      home: Scaffold(
        body: Align(
          alignment: Alignment.topLeft,
          child: SizedBox(
              width: 390,
              height: 1800,
              child: DishManagePage(api: dishFakeApi(dishes))),
        ),
      ),
    ));
    await t.pump();
    await t.pump(const Duration(milliseconds: 400));
  }

  List<String> allTexts() => find
      .byType(Text)
      .evaluate()
      .map((e) => (e.widget as Text).data ?? '')
      .where((s) => s.isNotEmpty)
      .toList();

  testWidgets('销量榜的标题说的是「近 30 天」,不是「本月」', (t) async {
    await pumpDishes(t, [
      dishJson(1, name: '红烧牛肉面', monthly: 200),
      dishJson(2, name: '酸辣粉', monthly: 180),
      dishJson(3, name: '卤蛋', monthly: 160),
    ]);

    expect(allTexts().where((s) => s.contains('本月')), isEmpty,
        reason: '服务端算的是 interval 30 days(滚动窗),标题却写「本月」——'
            '每月 1 号这两个窗能差 29 天');
    expect(find.text('近 30 天销量榜'), findsOneWidget);
  });

  testWidgets('零销量提示也要说「近 30 天」', (t) async {
    await pumpDishes(t, [
      dishJson(1, name: '红烧牛肉面', monthly: 200),
      dishJson(2, name: '滞销菜甲', monthly: 0),
      dishJson(3, name: '滞销菜乙', monthly: 0),
    ]);

    final stale = allTexts().where((s) => s.contains('零销量')).toList();
    expect(stale, isNotEmpty, reason: '滞销提示不见了');
    expect(stale.single, contains('近 30 天'),
        reason: '「$stale」说的是本月,服务端算的是近 30 天');
    expect(stale.single, isNot(contains('本月')));
  });

  testWidgets('逐行的「月售 N」照旧 —— 那是行业惯用语,不动它', (t) async {
    await pumpDishes(t, [dishJson(1, name: '红烧牛肉面', monthly: 200)]);
    expect(allTexts().where((s) => s.contains('月售 200')), isNotEmpty);
  });
}
