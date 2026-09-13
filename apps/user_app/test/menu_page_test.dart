import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/dish_detail_page.dart';
import 'package:user_app/main.dart';

/// 店铺页「点餐」页签(设计稿 A)上照实写的几件事。
///
/// 这些都不报错:写错了只是屏幕上多一句假话 —— 所以拿断言锁住。
void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    // 同 shop_card_test:测试环境里 PackageInfo 永远不返回,不 mock 会挂着定时器
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.chaojizan.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  Map<String, dynamic> shopJson(
          {String rate = '0.045',
          bool self = false,
          int min = 2000,
          int? effective}) =>
      {
        'id': 7,
        'name': '张记面馆',
        'address': '高新路 128 号',
        'lat': 30.6,
        'lng': 104.0,
        'is_open': true,
        'commission_rate': rate,
        'rating_avg': 4.8,
        'rating_count': 268,
        'monthly_sales': 268,
        'min_order_cents': min,
        if (effective != null) 'effective_min_order_cents': effective,
        'self_delivery': self,
        'promo_rules': const [],
        'kitchen_cam': false,
        'kitchen_cam_label': '无明厨亮灶',
        'dine_in_status': 'yes',
        'dine_in_label': '有堂食',
      };

  Map<String, dynamic> dishJson(int id, String name,
          {int price = 1600,
          int stock = 50,
          bool soldOut = false,
          int monthly = 0,
          List<Map<String, dynamic>> options = const []}) =>
      {
        'id': id,
        'merchant_id': 7,
        'name': name,
        'category': '招牌',
        'price_cents': price,
        'stock': stock,
        'sold_out_today': soldOut,
        'monthly_sales': monthly,
        'options': options,
      };

  final dishes = [
    dishJson(1, '牛肉面', monthly: 128),
    dishJson(2, '油泼扯面', price: 1400, options: [
      {
        'name': '份量',
        'required': true,
        'multi': false,
        'choices': [
          {'name': '小份', 'delta_cents': 0},
          {'name': '大份', 'delta_cents': 300},
        ],
      },
    ]),
    dishJson(3, '凉皮', price: 800, stock: 0, soldOut: true),
    dishJson(4, '卤蛋', price: 250),
  ];

  Future<void> pump(WidgetTester t,
      {String rate = '0.045',
      bool self = false,
      int min = 2000,
      int? effective}) async {
    final shop =
        shopJson(rate: rate, self: self, min: min, effective: effective);
    SharedPreferences.setMockInitialValues({});
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final p = req.url.path;
        Object? body;
        if (p == '/merchants/7') {
          body = shop;
        } else if (p == '/merchants/7/dishes') {
          body = dishes;
        } else if (p == '/cart/7') {
          body = {'items': []};
        } else if (p.endsWith('/coupons') ||
            p.endsWith('frequent-dishes') ||
            p.endsWith('/reviews')) {
          body = [];
        } else {
          body = {};
        }
        return http.Response(jsonEncode(body), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: MenuPage(api: api, merchant: Merchant.fromJson(shop)),
    ));
    await t.pumpAndSettle();
    addTearDown(Analytics.resetSession);
  }

  testWidgets('4.5% 的店写 4.5%,不被取整成 4%', (t) async {
    await pump(t);
    // 0.045 * 100 在浮点里是 4.4999…,旧写法 toStringAsFixed(0) 出来是「4」
    expect(find.textContaining('4.5%', findRichText: true), findsOneWidget);
  });

  testWidgets('月售挂小签;有规格的给「选规格」;售罄照实写明天自动恢复', (t) async {
    await pump(t);
    expect(find.text('月售 128'), findsOneWidget);
    expect(find.text('选规格'), findsOneWidget);
    expect(find.text('今日售罄'), findsOneWidget);
    expect(find.text('明天自动恢复'), findsOneWidget);
    expect(find.textContaining('10:00'), findsNothing,
        reason: '恢复时间没有这个字段,估清是次日 04:00 统一恢复');
  });

  testWidgets('选规格进详情页,加完回来车里有这一份', (t) async {
    await pump(t);
    await t.tap(find.text('选规格'));
    await t.pumpAndSettle();
    expect(find.byType(DishDetailPage), findsOneWidget);
    await t.tap(find.text('大份 +¥3.00'));
    await t.pump();
    await t.tap(find.text('加入购物车'));
    await t.pumpAndSettle();
    expect(find.byType(DishDetailPage), findsNothing);
    // 购物车条合计 = 14 + 3
    expect(find.text('¥17.00'), findsOneWidget);
  });

  testWidgets('商家自己送的店,购物车条不说配送费归骑手', (t) async {
    await pump(t, self: true);
    expect(find.textContaining('100% 归骑手'), findsNothing);
    expect(find.textContaining('这家店自己送'), findsOneWidget);
  });

  testWidgets('「商家」页签的承诺卡:费率写准,自己送的店不说配送费归骑手', (t) async {
    await pump(t, self: true);
    await t.tap(find.text('商家'));
    await t.pumpAndSettle();
    expect(find.textContaining('本店仅被抽成 4.5%'), findsOneWidget);
    expect(find.textContaining('这家店自己送,配送费归商家'), findsOneWidget);
    expect(find.textContaining('小费全归骑手'), findsNothing,
        reason: '自配送的店不收小费(orders.py 直接拒),配送费归商家(settlement.py)');
    // 页尾的评价入口切回「评价」页签
    await t.tap(find.textContaining('用户评价', findRichText: true));
    await t.pumpAndSettle();
    expect(find.text('全部 0'), findsNothing); // 没评价时不画筛选
    expect(find.text('还没有评价,下单后来做第一个评价的人'), findsOneWidget);
  });

  /// 菜单里某道菜那一行的「+」
  Finder addOf(String name) => find.descendant(
      of: find
          .ancestor(of: find.text(name), matching: find.byType(InkWell))
          .first,
      matching: find.bySemanticsLabel('增加'));

  FilledButton checkoutButton(WidgetTester t, String label) =>
      t.widget<FilledButton>(find.ancestor(
          of: find.text(label), matching: find.byType(FilledButton)));

  testWidgets('起送价按实际的写(含平台下限):空车写「¥15 起送」,不够写差多少、点不了', (t) async {
    // 商家自己没设起送价(0),平台下限 ¥15:服务端给的实际起送价是 15
    await pump(t, min: 0, effective: 1500);
    // 店铺头上那行原来只看商家自设的,设 0 就不写起送
    expect(find.textContaining('配送费 ¥3 起 · ¥15 起送'), findsOneWidget);
    expect(checkoutButton(t, '¥15 起送').onPressed, isNull);

    await t.tap(addOf('卤蛋'));
    await t.pumpAndSettle();
    expect(checkoutButton(t, '差 ¥12.5 起送').onPressed, isNull,
        reason: '¥2.50 的单到结算页也提交不了,服务端按 ¥15 拦');

    await t.tap(addOf('牛肉面'));
    await t.pumpAndSettle();
    expect(checkoutButton(t, '去结算').onPressed, isNotNull);
  });
}
