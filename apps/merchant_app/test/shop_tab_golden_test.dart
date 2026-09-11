@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/appeal_page.dart';
import 'package:merchant_app/shop_tab.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'real_fonts.dart';
import 'shop_fake_api.dart';

/// 店铺页三种状态的截图(真机口径 390×844)。
///
/// 生成/更新:`flutter test test/shop_tab_golden_test.dart --update-goldens`
///
/// ## 为什么要有图
///
/// 首屏入口数是个数字,它答不了「挤不挤、读不读得懂」。
/// 而密度改造最容易翻车的地方恰恰是"数字达标了但看着更乱了"。
///
/// ## 为什么要手动装字体
///
/// widget 测试默认只有 Ahem(每个字都是一个方块)。不装字体的话截出来
/// 是一屏黑方块 —— 那种图既看不出问题也证明不了什么。
/// 这里把项目真正用的三套字体和 Material 图标都装上,截出来的才是商家看到的。
void main() {
  Future<void> loadFonts() async {
    // 字族名必须带 packages/superz_shared/ 前缀 —— brand.dart 的 kSansFamily 等
    // 就是这么叫的(依赖包的字体在 FontManifest 里注册成这个名字)。
    // 这里原来按裸名 'SzSans' 装,和主题要的名字对不上,截图里的衬线数字
    // 其实一直是回落字体。见 real_fonts.dart
    await loadRealFonts();
    final loader = FontLoader('MaterialIcons');
    final icons = File('build/unit_test_assets/fonts/MaterialIcons-Regular.otf');
    if (icons.existsSync()) {
      loader.addFont(icons
          .readAsBytes()
          .then((b) => ByteData.view(Uint8List.fromList(b).buffer)));
      await loader.load();
    }
  }

  /// 截图用的主题:商家端那一套(碗色主强调),外加一处测试专用的补丁 ——
  /// 组件主题里**没写字族**的样式(按钮文字、AppBar 标题)在真机上落到系统字,
  /// 测试环境没有系统字,不补就是一排方块。
  ThemeData goldenTheme() {
    final base = brandTheme(Brightness.light,
        density: SzDensity.operate, accentTone: 0);
    TextStyle? fix(TextStyle? s) => (s ?? const TextStyle()).copyWith(
        fontFamily: kSansFamily, fontFamilyFallback: const ['PingFang SC']);
    ButtonStyle fixButton(ButtonStyle? b) => (b ?? const ButtonStyle())
        .copyWith(
            textStyle: WidgetStatePropertyAll(
                fix(b?.textStyle?.resolve(const <WidgetState>{}))));
    return base.copyWith(
      appBarTheme: base.appBarTheme
          .copyWith(titleTextStyle: fix(base.appBarTheme.titleTextStyle)),
      textButtonTheme:
          TextButtonThemeData(style: fixButton(base.textButtonTheme.style)),
      filledButtonTheme:
          FilledButtonThemeData(style: fixButton(base.filledButtonTheme.style)),
      outlinedButtonTheme: OutlinedButtonThemeData(
          style: fixButton(base.outlinedButtonTheme.style)),
    );
  }

  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'merchant_app',
      packageName: 'com.superz.merchant',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
    await loadFonts();
  });

  setUp(() => SharedPreferences.setMockInitialValues({}));

  /// 把整个 tab 壳子搭出来:可选的证照横幅 + 店铺页 + 底部导航。
  /// 截的是商家真正看到的那一屏,不是脱了壳的 ListView。
  ///
  /// 2026-09 浅色定稿(设计稿 6i)起店铺 tab 没有标题栏:身份行就是第一行,
  /// 营业开关从标题栏挪进了页面里的那张卡
  Future<void> pumpFrame(
    WidgetTester t, {
    required Map<String, dynamic> shop,
    Map<String, dynamic>? todos,
    List<Map<String, dynamic>> afterSales = const [],
    Widget? banner,
  }) async {
    final api = shopFakeApi(shop: shop, todos: todos, afterSales: afterSales);
    await api.login('13800000009', 'pw');
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(
      theme: goldenTheme(),
      home: MediaQuery(
        // 真机的安全区:刘海 47 + 底部小白条 34
        data: const MediaQueryData(
            size: Size(390, 844),
            padding: EdgeInsets.only(top: 47, bottom: 34)),
        child: Scaffold(
          body: SafeArea(
            bottom: false,
            child: Column(children: [
              if (banner != null) banner,
              Expanded(child: ShopTabPage(api: api, onOpenFinance: () {})),
            ]),
          ),
          bottomNavigationBar: NavigationBar(
            selectedIndex: 4,
            destinations: const [
              NavigationDestination(
                  icon: Icon(Icons.dashboard_outlined), label: '看板'),
              NavigationDestination(
                  icon: Icon(Icons.receipt_long_outlined), label: '订单'),
              NavigationDestination(
                  icon: Icon(Icons.menu_book_outlined), label: '菜单'),
              NavigationDestination(
                  icon: Icon(Icons.account_balance_wallet_outlined),
                  label: '账本'),
              NavigationDestination(
                  icon: Icon(Icons.storefront), label: '店铺'),
            ],
          ),
        ),
      ),
    ));
    await t.pumpAndSettle();
  }

  testWidgets('① 正常营业', (t) async {
    await pumpFrame(t,
        shop: shopJson(),
        todos: todosJson(badUnreplied: 3, messagesUnread: 1));
    await expectLater(find.byType(MaterialApp),
        matchesGoldenFile('goldens/shop_01_open.png'));
  });

  testWidgets('② 临时歇业中', (t) async {
    await pumpFrame(t,
        shop: shopJson(
            isOpen: false,
            // ⚠️ 必须是**将来**的时刻,否则 `_bizList` 判定"歇业已结束",
            // 那一条状态条根本不渲染 —— 第一版写了个过去的时间,
            // 截出来的「临时歇业中」图里恰恰没有临时歇业中。
            //
            // 用本地墙钟 14:00 折成 UTC:`_hhmmLocal` 会把它折回本地,
            // 于是任何机器上都稳定显示「14:00 自动恢复」,截图可复现
            closedUntil: DateTime(2030, 8, 21, 14).toUtc().toIso8601String()),
        todos: todosJson(badUnreplied: 3));
    await expectLater(find.byType(MaterialApp),
        matchesGoldenFile('goldens/shop_02_resting.png'));
  });

  testWidgets('③ 证照即将到期(带横幅)', (t) async {
    await pumpFrame(t,
        shop: shopJson(
            licenseStage: 'soon',
            licenseExpiresAt: '2026-09-13',
            licenseDaysLeft: 23),
        todos: todosJson(messagesUnread: 1),
        banner: Builder(builder: (c) {
          final scheme = Theme.of(c).colorScheme;
          return Material(
            color: scheme.secondaryContainer,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 12, 10),
              child: Row(children: [
                Icon(Icons.info_outline,
                    size: 20, color: scheme.onSecondaryContainer),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('食品经营许可证 23 天后到期',
                            style: TextStyle(
                                fontWeight: FontWeight.w600,
                                color: scheme.onSecondaryContainer)),
                        const SizedBox(height: 2),
                        Text('到期后有 7 天宽限,逾期自动停业。点此提交新证',
                            style: TextStyle(
                                fontSize: kFontNote,
                                color: scheme.onSecondaryContainer)),
                      ]),
                ),
                Icon(Icons.chevron_right, color: scheme.onSecondaryContainer),
              ]),
            ),
          );
        }));
    await expectLater(find.byType(MaterialApp),
        matchesGoldenFile('goldens/shop_03_license.png'));
  });

  testWidgets('④ 判责申诉页:72 小时窗口进门就看见', (t) async {
    final api = shopFakeApi();
    await api.login('13800000009', 'pw');
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(
      theme: goldenTheme(),
      home: MerchantAppealPage(api: api),
    ));
    await t.pumpAndSettle();
    await expectLater(find.byType(MaterialApp),
        matchesGoldenFile('goldens/shop_04_appeal.png'));
  });
}
