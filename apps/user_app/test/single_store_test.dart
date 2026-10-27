import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/help_page.dart';
import 'package:user_app/main.dart';
import 'package:user_app/settings_page.dart';
import 'package:user_app/single_store_home.dart';

/// 单门店版(应用商店包,packages/shared/lib/src/edition.dart)里**不许出现**的东西。
///
/// 单门店版靠编译期常量收起入口,所以这组测试要带着那个常量跑;不带的时候(平常的 `flutter test`)整组跳过:
///
///     flutter test --dart-define=SUPERZ_EDITION=single test/single_store_test.dart
///
/// (make analyze 和 CI 的「dart 单测」都会单独这样跑一次。)
///
/// 这些东西露出来都不报错:界面照样能用,只是商店审核员看到一个「平台」—— 拒审。所以拿断言锁住。
void main() {
  group('单门店版', _singleStore,
      skip: kSingleStore
          ? false
          : '只在单门店版跑:flutter test --dart-define=SUPERZ_EDITION=single test/single_store_test.dart');
}

void _singleStore() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    // 测试环境里 PackageInfo 永远不返回,不 mock 第一个请求会一直挂着(同 profile_view_test)
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.chaojizan.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    SingleStore.id = null;
  });

  Map<String, dynamic> shopJson() => {
        'id': 7,
        'name': '张记面馆',
        'address': '高新路 128 号',
        'lat': 30.6,
        'lng': 104.0,
        'is_open': true,
        'commission_rate': '0.05',
        'rating_avg': 4.8,
        'rating_count': 26,
        'monthly_sales': 120,
        'min_order_cents': 2000,
        'self_delivery': true,
        'promo_rules': const [],
        'kitchen_cam': false,
        'kitchen_cam_label': '无明厨亮灶',
        'dine_in_status': 'yes',
        'dine_in_label': '有堂食',
      };

  /// 记下每个请求,看单门店版有没有去碰它不该碰的接口
  final requests = <Uri>[];

  ApiClient fakeApi({int? storeId = 7}) {
    requests.clear();
    return ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        requests.add(req.url);
        final p = req.url.path;
        Object? body;
        switch (p) {
          case '/auth/login':
            body = {'token': 'tkn', 'user_id': 1, 'name': '张三', 'role': 'customer'};
          case '/auth/me':
            body = {
              'id': 1,
              'phone': '13800000001',
              'name': '张三',
              'role': 'customer',
              'avatar_url': '',
              'birthday': '',
              'marketing_push': true,
              'risk_level': '',
              'risk_note': '',
              'identity_verified': false,
            };
          case '/config':
            body = {
              'marketing': true,
              'features': const {},
              'single_store': {'merchant_id': storeId},
            };
          case '/merchants/7':
            body = shopJson();
          case '/merchants/7/dishes':
            body = [
              {
                'id': 1,
                'merchant_id': 7,
                'name': '牛肉面',
                'category': '招牌',
                'price_cents': 1600,
                'stock': 50,
                'sold_out_today': false,
                'monthly_sales': 12,
                'options': const [],
              }
            ];
          case '/cart/7':
            body = {'items': []};
          case '/orders':
            body = [];
          case '/orders/counts':
            body = {'food': [], 'stay': {'total': 0}, 'coupons_usable': 0};
          default:
            body = p.endsWith('/coupons') || p.endsWith('/reviews') ? [] : {};
        }
        return http.Response(jsonEncode(body), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
  }

  void phone(WidgetTester t) {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
  }

  Future<void> pumpHome(WidgetTester t, ApiClient api) async {
    phone(t);
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: SingleStoreHome(api: api),
    ));
    await t.pumpAndSettle();
    addTearDown(Analytics.resetSession);
  }

  /// 单门店版里一个字都不许出现的说法:它们都在说「这是一个平台」
  const platformWords = ['5%', '骑手', '平台', '拼单', '团购', '住宿', '视频', '聊天', '论坛', '音乐', '小程序'];

  void expectNoPlatformWords(WidgetTester t) {
    for (final w in platformWords) {
      expect(find.textContaining(w, findRichText: true), findsNothing, reason: '界面上出现了「$w」');
    }
  }

  group('首页外壳', () {
    testWidgets('底栏只有点餐 / 订单 / 我的,点餐就是后台配的那家店', (t) async {
      await pumpHome(t, fakeApi());
      final nav = t.widget<NavigationBar>(find.byType(NavigationBar));
      expect(nav.destinations.length, 3);
      for (final label in ['点餐', '订单', '我的']) {
        expect(find.descendant(of: find.byType(NavigationBar), matching: find.text(label)),
            findsOneWidget);
      }
      expect(find.byType(MenuPage), findsOneWidget);
      expect(find.text('张记面馆'), findsWidgets);
      expect(SingleStore.id, 7);
    });

    testWidgets('店铺页:没有拼单、分享、收藏,也没有平台抽成和排队', (t) async {
      await pumpHome(t, fakeApi());
      expect(find.byIcon(Icons.person_add_alt_outlined), findsNothing);
      expect(find.byIcon(Icons.share_outlined), findsNothing);
      expect(find.byIcon(Icons.favorite_outline), findsNothing);
      expectNoPlatformWords(t);
      expect(requests.any((u) => u.path.contains('queue')), isFalse,
          reason: '首版不放到店排队,接口都不该调');
      expect(requests.any((u) => u.path.startsWith('/favorites')), isFalse);
    });

    testWidgets('「商家」页签:证照还在,平台承诺卡不出', (t) async {
      await pumpHome(t, fakeApi());
      await t.tap(find.text('商家'));
      await t.pumpAndSettle();
      expect(find.text('证照信息'), findsOneWidget);
      expectNoPlatformWords(t);
    });

    testWidgets('后台没配店:说加载失败、给重试,不猜一家顶上', (t) async {
      await pumpHome(t, fakeApi(storeId: null));
      expect(find.byType(MenuPage), findsNothing);
      expect(find.textContaining('门店信息加载失败'), findsOneWidget);
      expect(find.text('重试'), findsOneWidget);
    });
  });

  group('我的', () {
    Future<ApiClient> loggedIn() async {
      final api = fakeApi();
      await api.login('13800000001', 'pw');
      SingleStore.id = 7;
      return api;
    }

    testWidgets('只留点餐用得到的入口', (t) async {
      final api = await loggedIn();
      phone(t);
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(body: ProfileView(api: api)),
      ));
      await t.pumpAndSettle();
      // 按页面从上到下的顺序滚着找:保留的一个个都要找得到。
      // 板块卡在最后 —— 生产的频道配置里有团购、视频音乐论坛的开关也开着(这里 features 为空 = 都开),
      // 单门店版照样只能有「点餐」那一张
      for (final kept in ['帮助中心', '意见反馈', '用户协议与隐私政策', '优惠券', '收货地址', '我的食安投诉']) {
        await t.scrollUntilVisible(find.text(kept), 200);
        expect(find.text(kept), findsOneWidget, reason: '「$kept」要留着');
      }
      expect(find.text('开发票'), findsWidgets);
      for (final gone in ['团购券', '我的收藏', '小程序', '我的信用分', '实名认证', 'AI 助手',
          '我的 AI 机器人', '钱去哪了', '平台账本', '平台体检', '我的视频', '我的音乐', '我的论坛',
          '超值团购', '住宿', '去点外卖', '去逛团购']) {
        expect(find.text(gone), findsNothing, reason: '「$gone」不该出现在单门店版里');
      }
      expect(find.textContaining('暂未开放'), findsNothing, reason: '审核员眼里「暂未开放」是没做完的入口');
      // 订单只数这一家店的;信用分、住宿、小程序目录都不拉
      expect(requests.where((u) => u.path == '/orders/counts').every(
          (u) => u.queryParameters['merchant_id'] == '7'), isTrue);
      expect(requests.any((u) => u.path.startsWith('/credit') || u.path.startsWith('/stays') ||
          u.path.startsWith('/mini-apps')), isFalse, reason: '$requests');
    });

    testWidgets('设置:没有聊天、小程序、扫码登录的设备,注销还在', (t) async {
      final api = await loggedIn();
      phone(t);
      await t.pumpWidget(MaterialApp(
          theme: brandTheme(Brightness.light), home: SettingsPage(api: api)));
      await t.pumpAndSettle();
      expect(find.textContaining('聊天'), findsNothing);
      expect(find.text('小程序授权与数据'), findsNothing);
      expect(find.text('已登录的网页和电脑'), findsNothing);
      expect(find.text('检查更新'), findsNothing, reason: '商店包不做应用内更新');
      await t.scrollUntilVisible(find.text('注销账号'), 200);
      expect(find.text('注销账号'), findsOneWidget);
    });

    testWidgets('关于我们:不链平台官网、不说平台立场', (t) async {
      phone(t);
      await t.pumpWidget(MaterialApp(
          theme: brandTheme(Brightness.light), home: const AboutPage()));
      await t.pumpAndSettle();
      expect(find.text('官方网站'), findsNothing);
      expect(find.text('运营主体'), findsOneWidget);
      expectNoPlatformWords(t);
    });

    testWidgets('帮助中心:用单门店版自己的问答,不读后台那份平台问答', (t) async {
      final api = fakeApi();
      phone(t);
      await t.pumpWidget(MaterialApp(
          theme: brandTheme(Brightness.light), home: HelpCenterPage(api: api)));
      await t.pumpAndSettle();
      expect(find.text('到店自取怎么取餐?'), findsOneWidget);
      expectNoPlatformWords(t);
    });
  });

  test('协议和隐私政策是门店点餐版', () {
    expect(kTermsText, contains('门店点餐版'));
    expect(kPrivacyText, contains('门店点餐版'));
    for (final w in ['骑手', '聊天', '视频', '信用分', '团购']) {
      expect(kPrivacyText.contains(w), isFalse, reason: '隐私政策里出现了「$w」');
      expect(kTermsText.contains(w), isFalse, reason: '用户协议里出现了「$w」');
    }
  });
}
