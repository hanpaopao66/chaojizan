import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/main.dart';
import 'package:user_app/mini_apps_panel.dart';

/// 首页下拉抽屉(#278)的首次提示与面板文案。
///
/// ## 这个测试防的是什么
///
/// 下拉是隐性手势,不提示几乎没人会去拉;可提示一旦出现就得**能永久消失**,
/// 学会了还天天顶在首页就是打扰。两头都没有报错可言,只能靠这里锁住:
/// 没学会时出现、点过/拉开过之后永不再出现、没有小程序时压根不出现。
///
/// 面板底部那句「顺序」的说明也锁在这儿:它是一句对外的承诺,
/// 设计稿里原本写的是「按登记顺序」,而服务端实际按运营排的 sort 排 ——
/// 查不实的话不能再混进来。
void main() {
  // package_info_plus 在测试环境永远不返回(见 shop_card_test 的同一条注释)
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.chaojizan.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  const hint = '↓ 下拉打开小程序';

  Map<String, dynamic> app({String icon = '📊'}) => {
        'id': 1,
        'name': '透明中心',
        'icon': icon,
        'tagline': '平台账本',
        'entry_url': 'https://chaojizan.cc/transparency',
        'allowed_origins': ['https://chaojizan.cc'],
        'perms': ['initData'],
      };

  ApiClient fakeApi(List<Map<String, dynamic>> apps) => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          Object? payload;
          if (req.url.path == '/mini-apps') {
            payload = apps;
          } else {
            payload = req.url.path.endsWith('s') ? [] : {};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  /// 收货地址要给:没有它首页会等手机定位,测试环境里永远等不到
  final addr = Address.fromJson(const {
    'id': 1,
    'contact_name': '张三',
    'contact_phone': '13800000001',
    'address': '春熙路 1 号',
    'lat': 30.6598,
    'lng': 104.0810,
    'is_default': true,
  });

  Future<void> pump(WidgetTester t, List<Map<String, dynamic>> apps,
      {Key? key}) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(
      key: key,
      theme: brandTheme(Brightness.light),
      home: Scaffold(
          body: MerchantListView(api: fakeApi(apps), deliveryAddress: addr)),
    ));
    await t.pumpAndSettle();
    addTearDown(Analytics.resetSession);
  }

  group('首次提示', () {
    testWidgets('没学会手势、又有小程序时出现', (t) async {
      SharedPreferences.setMockInitialValues({});
      await pump(t, [app()]);
      expect(find.text(hint), findsOneWidget);
    });

    testWidgets('没有小程序时不出现 —— 没东西的抽屉不该教人去拉', (t) async {
      SharedPreferences.setMockInitialValues({});
      await pump(t, []);
      expect(find.text(hint), findsNothing);
    });

    testWidgets('点过一次就永久不再出现', (t) async {
      SharedPreferences.setMockInitialValues({});
      await pump(t, [app()]);
      await t.tap(find.text(hint));
      await t.pumpAndSettle();
      // 点这行字直接打开面板(用鼠标的桌面浏览器拉不动列表,只能点)
      expect(find.text('小程序'), findsOneWidget);
      Navigator.of(t.element(find.text('小程序'))).pop();
      await t.pumpAndSettle();
      expect(find.text(hint), findsNothing);

      final sp = await SharedPreferences.getInstance();
      expect(sp.getBool('home_miniapps_hint_seen'), isTrue,
          reason: '只藏在内存里的话,下次启动又冒出来');

      // 重进首页(同一份本地存储)
      await pump(t, [app()], key: const ValueKey('second-launch'));
      expect(find.text(hint), findsNothing);
    });
  });

  group('面板与露头条', () {
    testWidgets('面板底部说清顺序是人工排的,不写「登记顺序」', (t) async {
      SharedPreferences.setMockInitialValues({});
      await pump(t, [app()]);
      await t.tap(find.text(hint));
      await t.pumpAndSettle();
      expect(find.textContaining('人工排定'), findsOneWidget);
      expect(find.textContaining('登记顺序'), findsNothing);
    });

    testWidgets('露头条画衬线字块(设计稿 2a):运营配的汉字照用', (t) async {
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
          body: MiniAppsPeek(
            pull: kMiniAppsPullThreshold,
            apps: [MiniAppInfo.fromJson(app(icon: '账'))],
          ),
        ),
      ));
      expect(find.text('账'), findsOneWidget);
      expect(find.text('松手打开小程序'), findsOneWidget);
      // 和频道字块同一种字:回落链第一顺位是打包的宋体子集
      final glyph = t.widget<Text>(find.text('账'));
      expect(glyph.style?.fontFamilyFallback?.first, kSerifCjkFamily);
    });

    testWidgets('老数据里的 emoji 不画,退回名字的第一个字', (t) async {
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
          body: MiniAppsPeek(
            pull: kMiniAppsPullThreshold,
            apps: [MiniAppInfo.fromJson(app(icon: '🏪'))],
          ),
        ),
      ));
      expect(find.text('🏪'), findsNothing,
          reason: 'emoji 自带颜色,和整页的衬线字块不是一套');
      expect(find.text('透'), findsOneWidget, reason: '「透明中心」的第一个字');
    });

    test('选字规则', () {
      MiniAppInfo a(String icon, String name) =>
          MiniAppInfo.fromJson({...app(icon: icon), 'name': name});
      expect(miniAppGlyph(a('水', '交水电费')), '水');
      expect(miniAppGlyph(a('💧', '交水电费')), '交');
      expect(miniAppGlyph(a('', '公开账本')), '公');
      // 两个字的 icon 不是「一个字」,也退回名字
      expect(miniAppGlyph(a('账本', '公开账本')), '公');
    });

    testWidgets('面板里是同一个字,不是另一副样子', (t) async {
      SharedPreferences.setMockInitialValues({});
      await pump(t, [app(icon: '账')]);
      await t.tap(find.text(hint));
      await t.pumpAndSettle();
      expect(find.text('账'), findsOneWidget);
      expect(find.text('透明中心'), findsOneWidget);
    });
  });
}
