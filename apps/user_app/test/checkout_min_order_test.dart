import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/checkout_page.dart';

/// 结算页上两个「照实写」的数:起送价、抽成比例。
///
/// 起送价按服务端给的实际起送价(max(商家自设, 平台下限))比 —— 原来比的是
/// 商家自设的,设成 0 的店这里永远不拦,提交了才被 409 顶回来。
/// 抽成比例原来用 toStringAsFixed(0),4.5% 那一档写成「4%」。
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

  // 商家自己没设起送价(0),平台下限 ¥15:服务端给的实际起送价是 15
  final shop = Merchant.fromJson(const {
    'id': 7,
    'name': '张记面馆',
    'lat': 30.6,
    'lng': 104.0,
    'is_open': true,
    'commission_rate': '0.045',
    'min_order_cents': 0,
    'effective_min_order_cents': 1500,
  });

  CartLine line(int price, {int qty = 1}) => CartLine(
        dish: Dish.fromJson({
          'id': price,
          'merchant_id': 7,
          'name': '菜$price',
          'price_cents': price,
          'stock': 50,
        }),
        choices: const [],
        quantity: qty,
      );

  Future<void> pump(WidgetTester t, List<CartLine> cart) async {
    SharedPreferences.setMockInitialValues({});
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final p = req.url.path;
        final Object body = switch (p) {
          '/addresses' => [
              {
                'id': 1,
                'contact_name': '王小明',
                'contact_phone': '13800000000',
                'address': '高新路 128 号',
                'lat': 30.61,
                'lng': 104.01,
                'is_default': true,
              }
            ],
          '/orders/delivery-fee' => {'fee_cents': 300},
          '/orders/coupons/mine' => [],
          _ => {},
        };
        return http.Response(jsonEncode(body), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: CheckoutPage(api: api, merchant: shop, cart: cart),
    ));
    await t.pumpAndSettle();
    addTearDown(Analytics.resetSession);
  }

  FilledButton submit(WidgetTester t) => t.widget<FilledButton>(find
      .descendant(
          of: find.byType(SafeArea).last, matching: find.byType(FilledButton))
      .last);

  testWidgets('商家设 0 的店也按 ¥15 拦:写差多少,按钮点不了', (t) async {
    await pump(t, [line(1200)]);
    expect(find.text('差 ¥3.00 起送'), findsOneWidget);
    expect(find.text('¥15 起送'), findsOneWidget);
    expect(submit(t).onPressed, isNull);
  });

  testWidgets('够了就能提交;分账里的抽成写 4.5%,不被取整成 4%', (t) async {
    await pump(t, [line(1200), line(300)]);
    expect(find.text('提交订单'), findsOneWidget);
    expect(submit(t).onPressed, isNotNull);
    await t.scrollUntilVisible(find.textContaining('只扣 4.5% 服务费'), 300,
        scrollable: find.byType(Scrollable).first);
    expect(find.textContaining('只扣 4.5% 服务费'), findsOneWidget);
    expect(find.textContaining('= 4.5%'), findsOneWidget);
    expect(find.textContaining('4% 服务费'), findsNothing);
  });
}
