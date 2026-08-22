import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/promises_page.dart';
import 'package:merchant_app/rules_page.dart';
import 'package:merchant_app/shop_tab.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'shop_fake_api.dart';

/// 店铺页顶那张费率卡:可以永久关掉,但**关掉不许把入口带走**。
///
/// ## 这一端的风险比用户端还大
///
/// 改之前查过全仓的构造点,卡里那三个入口是这样的:
///
/// | 入口 | 卡之外还有谁能到 |
/// |---|---|
/// | 钱怎么分的 | `onOpenFinance` → 对账 **底部 tab**,常驻,关不掉 |
/// | 平台对你的承诺 | **没有别人。**`MerchantPromisesPage` 全仓只在 `shop_tab.dart` 被构造一次 |
/// | 平台规则 | **没有别人。**`MerchantRulesPage` 同理 |
///
/// 也就是说,照着首页承诺条那样「一关了之」会让两份文件从商家端消失 ——
/// 而其中一份正是「平台对你的承诺」。所以这一版的规矩是
/// **关掉的是卡,不是入口**:卡收起的同时,那两条落到底部的账号组里。
///
/// 「钱怎么分的」**不搬** —— 对账本来就是底部 tab,再挂一条是重复入口不是保障。
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

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    ApiClient.resetAppBuildForTest();
  });

  /// 整页渲染。视口和盒子一起给到 3600 —— 只放大 SizedBox 会被渲染视口
  /// 夹住,ListView 只建前一千多像素,断言就假绿了(见 shop_tab_page_test.dart)。
  Future<void> pumpShop(WidgetTester t, ApiClient api,
      {NavigatorObserver? observer, VoidCallback? onOpenFinance}) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 3600) * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light, density: SzDensity.operate),
      navigatorObservers: [if (observer != null) observer],
      home: Scaffold(
        body: Align(
          alignment: Alignment.topLeft,
          child: SizedBox(
            width: 390,
            height: 3600,
            child: ShopTabPage(api: api, onOpenFinance: onOpenFinance),
          ),
        ),
      ),
    ));
    await t.pumpAndSettle();
  }

  Future<ApiClient> loggedIn() async {
    final api = shopFakeApi();
    await api.login('13800000009', 'pw');
    return api;
  }

  group('默认不关', () {
    testWidgets('卡在,关闭按钮也在', (t) async {
      await pumpShop(t, await loggedIn());
      expect(find.text('本月费率 · 只降不升'), findsOneWidget);
      expect(find.byIcon(Icons.close), findsOneWidget,
          reason: '这张卡没有关闭按钮');
    });

    testWidgets('关闭按钮触控区 40×40', (t) async {
      await pumpShop(t, await loggedIn());
      final hit = find
          .ancestor(
              of: find.byIcon(Icons.close), matching: find.byType(InkWell))
          .first;
      final size = t.getSize(hit);
      expect(size.width, greaterThanOrEqualTo(40));
      expect(size.height, greaterThanOrEqualTo(40));
      expect(size.width, lessThanOrEqualTo(48));
      expect(size.height, lessThanOrEqualTo(48));
    });
  });

  group('关掉之后', () {
    testWidgets('卡不再渲染', (t) async {
      await pumpShop(t, await loggedIn());
      await t.tap(find.byIcon(Icons.close));
      await t.pumpAndSettle();
      expect(find.text('本月费率 · 只降不升'), findsNothing);
      expect(find.textContaining('本月已完成'), findsNothing);
    });

    testWidgets('冷启动后仍然是关的', (t) async {
      await pumpShop(t, await loggedIn());
      await t.tap(find.byIcon(Icons.close));
      await t.pumpAndSettle();
      await pumpShop(t, await loggedIn());
      expect(find.text('本月费率 · 只降不升'), findsNothing,
          reason: '重开之后卡又回来了 —— 关闭状态没落盘');
    });

    testWidgets('落的是 shop_gold_hidden,不和别端串键', (t) async {
      await pumpShop(t, await loggedIn());
      await t.tap(find.byIcon(Icons.close));
      await t.pumpAndSettle();
      final sp = await SharedPreferences.getInstance();
      expect(sp.getBool('shop_gold_hidden'), isTrue);
    });
  });

  group('关掉之后那两份文件仍然可达', () {
    // 这一组是这次改动的**硬判据**。这两页在全仓只有这一个构造点,
    // 卡一关它们就没了 —— 而其中一份是「平台对你的承诺」
    for (final (label, page) in [
      ('平台对你的承诺', MerchantPromisesPage),
      ('平台规则', MerchantRulesPage),
    ]) {
      testWidgets('$label → $page', (t) async {
        SharedPreferences.setMockInitialValues({'shop_gold_hidden': true});
        final spy = _PushSpy();
        await pumpShop(t, await loggedIn(), observer: spy);
        expect(find.text('本月费率 · 只降不升'), findsNothing,
            reason: '前置条件没成立:卡还开着');

        final target = find.text(label);
        expect(target, findsOneWidget,
            reason: '卡关掉之后「$label」在这一页上找不到了 —— '
                '它在全仓**没有**第二个入口');
        spy.lastPushed = null;
        await t.tap(target);
        await t.pump();
        t.takeException();
        expect(spy.lastPushed, page,
            reason: '「$label」点下去没到 $page,'
                '而是 ${spy.lastPushed ?? "什么也没 push"}');
      });
    }

    testWidgets('「钱怎么分的」不搬:它的家是对账 tab,不是这张卡', (t) async {
      SharedPreferences.setMockInitialValues({'shop_gold_hidden': true});
      var opened = false;
      await pumpShop(t, await loggedIn(), onOpenFinance: () => opened = true);
      // 卡关了就没有这个入口了 —— 这是对的:对账是常驻底部 tab,
      // 在设置组里再挂一条只是重复
      expect(find.text('钱怎么分的'), findsNothing);
      expect(opened, isFalse);
    });

    testWidgets('卡开着的时候不重复挂', (t) async {
      await pumpShop(t, await loggedIn());
      for (final label in ['平台对你的承诺', '平台规则']) {
        expect(find.text(label), findsOneWidget,
            reason: '「$label」在页面上出现了不止一次');
      }
    });
  });
}

/// 记下最近一次 push 的是什么页。
class _PushSpy extends NavigatorObserver {
  Type? lastPushed;

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    final page = route is MaterialPageRoute ? route.builder : null;
    if (page == null) return;
    try {
      lastPushed = page(navigator!.context).runtimeType;
    } catch (_) {
      lastPushed = null;
    }
  }
}
