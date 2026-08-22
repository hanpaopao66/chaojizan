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
  const bg = Color(0xFFFFFFFF);

  Future<void> loadFonts() async {
    Future<void> load(String family, List<String> paths) async {
      final loader = FontLoader(family);
      for (final p in paths) {
        final f = File(p);
        if (!f.existsSync()) continue;
        loader.addFont(
            f.readAsBytes().then((b) => ByteData.view(Uint8List.fromList(b).buffer)));
      }
      await loader.load();
    }

    const shared = '../../packages/shared/assets/fonts';
    // SzSans / SzSerif 是拉丁子集,**不含 CJK 字形**(brand.dart 的注释
    // 就写着「中文一律回落系统字」)。测试里没有系统字,所以给这两族
    // 各补一份中文子集,不然凡是显式指定了字族的地方都是方块
    const cjk = '$shared/SzSerifCJK-Regular.ttf';
    await load('SzSans',
        ['$shared/SzSans-Regular.ttf', '$shared/SzSans-Semibold.ttf', cjk]);
    await load('SzSerif',
        ['$shared/SzSerif-Regular.ttf', '$shared/SzSerif-Semibold.ttf', cjk]);
    await load('SzSerifCJK',
        ['$shared/SzSerifCJK-Regular.ttf', '$shared/SzSerifCJK-Semibold.ttf']);
    // ⚠️ 中文的回落链(brand.dart 的 `_cjkFallback`)指的是**系统字体**
    // ['PingFang SC', 'Noto Sans CJK SC', 'Heiti SC'] —— widget 测试里
    // 一个都不存在,于是整屏中文渲染成方块(第一版截出来就是那样)。
    // 拿打包的思源宋体子集顶上这三个名字,只是替系统字占位。
    for (final sys in ['PingFang SC', 'Noto Sans CJK SC', 'Heiti SC']) {
      await load(sys, ['$shared/SzSerifCJK-Regular.ttf']);
    }
    // 正文的默认字族也铺上中文字形,否则没写 fontFamily 的那些 Text 还是方块
    await load('Roboto', ['$shared/SzSerifCJK-Regular.ttf']);
    await load('MaterialIcons',
        ['build/unit_test_assets/fonts/MaterialIcons-Regular.otf']);
  }

  /// 截图用的主题。
  ///
  /// ⚠️ `brandTheme` 里没写 `fontFamily` 的那些样式(bodyMedium 之类)
  /// 在 widget 测试里会落到 **Ahem** —— 每个字符都是一个实心方块,
  /// 而 Ahem 号称"覆盖所有字形",于是 `fontFamilyFallback` 永远不会触发。
  /// 只补 fallback 是没用的(第二版截出来 ListTile 的副标题仍是灰块),
  /// 必须把主字族显式指过去。
  ThemeData goldenTheme() {
    final base = brandTheme(Brightness.light, density: SzDensity.operate);
    TextStyle? fix(TextStyle? s) => s?.copyWith(
        fontFamily: s.fontFamily ?? 'SzSans',
        fontFamilyFallback: const ['PingFang SC', 'SzSerifCJK']);
    return base.copyWith(
      textTheme: base.textTheme.apply(
          fontFamily: 'SzSans',
          fontFamilyFallback: const ['PingFang SC', 'SzSerifCJK']),
      listTileTheme: base.listTileTheme.copyWith(
        titleTextStyle: fix(base.listTileTheme.titleTextStyle),
        subtitleTextStyle: fix(base.listTileTheme.subtitleTextStyle),
      ),
      appBarTheme: base.appBarTheme
          .copyWith(titleTextStyle: fix(base.appBarTheme.titleTextStyle)),
      // 按钮的文字样式走 WidgetStateProperty,textTheme.apply 盖不到它们 ——
      // 不补的话「立即恢复」「同意退款」这些都是方块
      textButtonTheme: TextButtonThemeData(
          style: (base.textButtonTheme.style ?? const ButtonStyle())
              .copyWith(textStyle: WidgetStatePropertyAll(fix(const TextStyle())))),
      filledButtonTheme: FilledButtonThemeData(
          style: (base.filledButtonTheme.style ?? const ButtonStyle())
              .copyWith(textStyle: WidgetStatePropertyAll(fix(const TextStyle())))),
      outlinedButtonTheme: OutlinedButtonThemeData(
          style: (base.outlinedButtonTheme.style ?? const ButtonStyle())
              .copyWith(textStyle: WidgetStatePropertyAll(fix(const TextStyle())))),
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

  /// 把整个 tab 壳子搭出来:AppBar(营业开关)+ 可选的证照横幅 + 店铺页。
  /// 截的是商家真正看到的那一屏,不是脱了壳的 ListView。
  Future<void> pumpFrame(
    WidgetTester t, {
    required Map<String, dynamic> shop,
    Map<String, dynamic>? todos,
    List<Map<String, dynamic>> afterSales = const [],
    Widget? banner,
    required String openLabel,
    required bool isOpen,
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
        // SzPageScaffold 不是 Scaffold:带 appBar 的页面在宽屏上要限宽,
        // 走查用的壳也得和真页面一致,否则 golden 量的不是线上那个布局
        child: SzPageScaffold(
          backgroundColor: bg,
          appBar: AppBar(
            title: const Text('店铺'),
            actions: [
              IconButton(
                  icon: const Icon(Icons.local_fire_department_outlined),
                  onPressed: () {}),
              Row(children: [
                const Icon(Icons.notifications_active, size: 18),
                const SizedBox(width: 8),
                Text(openLabel),
                Switch(value: isOpen, onChanged: (_) {}),
                const SizedBox(width: 8),
              ]),
            ],
          ),
          body: Column(children: [
            if (banner != null) banner,
            Expanded(child: ShopTabPage(api: api, onOpenFinance: () {})),
          ]),
          bottomNavigationBar: NavigationBar(
            selectedIndex: 3,
            destinations: const [
              NavigationDestination(
                  icon: Icon(Icons.receipt_long_outlined), label: '订单'),
              NavigationDestination(
                  icon: Icon(Icons.restaurant_menu_outlined), label: '菜品'),
              NavigationDestination(
                  icon: Icon(Icons.bar_chart_outlined), label: '对账'),
              NavigationDestination(icon: Icon(Icons.store), label: '店铺'),
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
        todos: todosJson(badUnreplied: 3, messagesUnread: 1),
        openLabel: '营业中',
        isOpen: true);
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
        todos: todosJson(badUnreplied: 3),
        openLabel: '已打烊',
        isOpen: false);
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
                                fontSize: 12,
                                color: scheme.onSecondaryContainer)),
                      ]),
                ),
                Icon(Icons.chevron_right, color: scheme.onSecondaryContainer),
              ]),
            ),
          );
        }),
        openLabel: '营业中',
        isOpen: true);
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
