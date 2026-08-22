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

  /// #33 4.2 的指标:① 首屏能看到几道菜 ② 改一道菜的价格要几步。
  ///
  /// 分类条是这一页**唯一主动加的高度**(43px)。换回来的是:
  /// 100 道菜的店找一道菜,从「滚 N 屏」变成「点一次 + 半屏」。
  group('分类条:点一次只看这一类', () {
    List<Map<String, dynamic>> mixed() => [
          dishJson(1, name: '红烧牛肉面', category: '主食'),
          dishJson(2, name: '酸辣粉', category: '主食'),
          dishJson(3, name: '可乐', category: '饮品'),
        ];

    testWidgets('默认全部,分类各自带数量', (t) async {
      await pumpDishes(t, mixed());
      expect(find.text('全部 3'), findsOneWidget);
      expect(find.text('主食 2'), findsOneWidget);
      expect(find.text('饮品 1'), findsOneWidget);
      expect(find.text('可乐'), findsOneWidget);
    });

    testWidgets('选中一类后,别的类不再出现', (t) async {
      await pumpDishes(t, mixed());
      await t.tap(find.text('主食 2'));
      await t.pump();
      expect(find.text('红烧牛肉面'), findsOneWidget);
      expect(find.text('可乐'), findsNothing,
          reason: '筛了主食还看得见饮品,那这个分类条就是白加的 43px');
      // 只剩一类时不再重复分类名 —— 分类条上已经高亮着
      expect(find.text('主食'), findsNothing,
          reason: '分类头和高亮的 chip 说的是同一件事,重复一遍纯占地方');
    });

    testWidgets('只有一个分类时,分类条整个不出现', (t) async {
      await pumpDishes(t, [
        dishJson(1, name: '红烧牛肉面', category: '主食'),
        dishJson(2, name: '酸辣粉', category: '主食'),
      ]);
      expect(find.text('全部 2'), findsNothing,
          reason: '一个分类的店点它没有任何意义 —— 那时它是纯噪音');
    });
  });

  /// #33 4.2 第 3 点:缺图提示挪到缩略图角标。
  ///
  /// 它原先在 `trailing` 里和估清按钮、上下架开关挤一列 ——
  /// 挤窄标题列、逼副标题折行,每行 64→78。12 道全缺图就是 +168px。
  testWidgets('缺图提示压在缩略图上,不占行高', (t) async {
    await pumpDishes(t, [
      {...dishJson(1, name: '红烧牛肉面'), 'image_url': ''},
    ]);
    expect(find.text('缺图'), findsOneWidget, reason: '缺图还是要提示,只是换了位置');
    // 角标在 48×48 的缩略图范围内,不是在行尾那一列
    final badge = t.getCenter(find.text('缺图'));
    final tile = t.getTopLeft(find.text('红烧牛肉面'));
    expect(badge.dx, lessThan(tile.dx),
        reason: '角标跑到标题右边去了 —— 那就还是在挤标题列');
  });

  testWidgets('时间窗只说「近 30 天」,不说「本月」;销量榜已移除', (t) async {
    await pumpDishes(t, [
      dishJson(1, name: '红烧牛肉面', monthly: 200),
      dishJson(2, name: '酸辣粉', monthly: 180),
      dishJson(3, name: '卤蛋', monthly: 160),
    ]);

    expect(allTexts().where((s) => s.contains('本月')), isEmpty,
        reason: '服务端算的是 interval 30 days(滚动窗),写「本月」的话——'
            '每月 1 号这两个窗能差 29 天');
    // #33 4.2:销量榜整块砍掉了。它是**同一份东西的第三份** ——
    // 每行副标题已经有「月售 N」,对账页 AnalyticsPage 也明说包含
    // 「菜品排行」。这一页只留「N 道零销量」,因为那是待办,排行榜不是。
    // 这条断言防的是有人看着空位又把榜加回来
    expect(find.textContaining('销量榜'), findsNothing,
        reason: '排行榜不该在干活页占地方 —— 首屏是留给菜的');
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
