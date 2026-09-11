@Tags(['golden'])
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/main.dart';
import 'package:merchant_app/new_order_page.dart';
import 'package:merchant_app/voucher_manage_page.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 商家端五页 + 新单详情 + 核销成功态,按 2026-09 浅色定稿的样例数据截图,
/// 和设计稿(6a / 6c / 6e / 6g / 6i / 6k / 6l)并排对照用。
///
/// 生成:`flutter test test/design_render_test.dart --update-goldens --run-skipped`
///
/// 截图是**给人看的评审产物**,不做 CI 门禁(dart_test.yaml 的 golden 标签):
/// 字形栅格化跨平台不一致,而且这里优先用本机的中文黑体,换台机器就不一样。
/// 页面上还有跟着时钟走的字(「11:51 下单」「等 1 分 20 秒」「9 月 1 日 — 11 日」),
/// 所以它**只拿来生成**(带 --update-goldens 跑),不拿来比对;
/// 生成的 design_*.png 在 .gitignore 里,不进仓库。
///
/// 画布 390×844、顶部 44 的状态栏(设计稿的手机框就是这个尺寸),
/// 底部不留小白条 —— 稿子上导航栏贴底。
void main() {
  const shared = '../../packages/shared/assets/fonts';

  /// 本机的中文黑体。设计稿的中文走 PingFang,测试环境里没有系统字,
  /// 找得到 macOS 自带的冬青黑体就用它顶上,找不到退回打包的宋体子集
  /// (那样中文会是宋体,排版位置仍然可比)。
  String cjkSans() {
    for (final p in [
      '/System/Library/Fonts/Hiragino Sans GB.ttc',
      '/System/Library/Fonts/STHeiti Light.ttc',
    ]) {
      if (File(p).existsSync()) return p;
    }
    return '$shared/SzSerifCJK-Regular.ttf';
  }

  Future<void> loadFonts() async {
    Future<void> load(String family, List<String> paths) async {
      final loader = FontLoader(family);
      for (final p in paths) {
        final f = File(p);
        if (!f.existsSync()) continue;
        loader.addFont(f
            .readAsBytes()
            .then((b) => ByteData.view(Uint8List.fromList(b).buffer)));
      }
      await loader.load();
    }

    final cjk = cjkSans();
    // 字族名必须带 packages/superz_shared/ 前缀(brand.dart 的 kSansFamily 等)。
    // 拉丁子集里没有中文,每一族后面补一份中文字形 —— 真机上是系统字回落
    await load(kSansFamily,
        ['$shared/SzSans-Regular.ttf', '$shared/SzSans-Semibold.ttf', cjk]);
    await load(kSerifFamily,
        ['$shared/SzSerif-Regular.ttf', '$shared/SzSerif-Semibold.ttf', cjk]);
    await load(kSerifCjkFamily,
        ['$shared/SzSerifCJK-Regular.ttf', '$shared/SzSerifCJK-Semibold.ttf']);
    // 系统字的位置:中文回落链,以及组件主题里没写字族的那些样式
    // (按钮文字、AppBar 标题)—— 它们在真机上落到系统默认字,测试里默认是
    // Roboto,不补就是一排方块
    // FlutterTest 是测试环境的默认字族:按钮上那种在页面里自己写的样式
    // 没有字族,真机上走系统字,这里让它们落到同一套中文黑体
    for (final sys in [
      'PingFang SC',
      'Noto Sans CJK SC',
      'Heiti SC',
      'Roboto',
      'FlutterTest',
    ]) {
      await load(sys, [cjk]);
    }
    await load('MaterialIcons',
        ['build/unit_test_assets/fonts/MaterialIcons-Regular.otf']);
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

  final now = DateTime.now();
  String iso(Duration ago) => now.subtract(ago).toUtc().toIso8601String();
  String day(DateTime d) => '${d.year}-${d.month.toString().padLeft(2, '0')}-'
      '${d.day.toString().padLeft(2, '0')}';

  Map<String, dynamic> shop({bool open = true}) => {
        'id': 1,
        'name': '张记面馆',
        'description': '',
        'address': '学府街 12 号',
        'lat': 30.5728,
        'lng': 104.0668,
        'is_open': open,
        'commission_rate': 0.05,
        'status': 'approved',
        'rating_avg': 4.8,
        'rating_count': 312,
        'announcement': '本店牛肉面每日现煮',
        'logo_url': '',
        'open_time': '10:00',
        'close_time': '21:30',
        'monthly_sales': 820,
        'promise_ready_minutes': 12,
        'self_delivery': false,
        'min_order_cents': 2000,
        'packing_fee_cents': 0,
        'photo_urls': <String>[],
        'promo_rules': <Map>[],
        'gift_rules': <Map>[],
        'closed_until': null,
        'holiday_plans': <Map>[],
        'viewer_is_staff': false,
        'viewer_is_owner': true,
        'license_stage': 'ok',
        'license_expires_at': '2027-03-15',
        'license_days_left': 186,
        'category': 'noodles',
        'kitchen_cam': false,
        'kitchen_cam_label': '无明厨亮灶',
        'dine_in_status': 'yes',
        'dine_in_label': '有堂食',
        'biz_type': 'food',
        'auto_accept': false,
        'created_at': '2026-02-14T02:00:00Z',
        'food_seal': true,
        'food_safety_hold': false,
        'busy_active': false,
        'busy_extra_minutes': 10,
      };

  Map<String, dynamic> order(String no,
          {required String status,
          required List<(String, int, int)> items,
          required Duration ago,
          String remark = '',
          String phone = '138****3382',
          bool pickup = false,
          double lat = 30.5870,
          double lng = 104.0600}) =>
      {
        'order_no': no,
        'merchant_id': 1,
        'status': status,
        'items': [
          for (final (n, p, q) in items)
            {'dish_id': 1, 'name': n, 'price_cents': p, 'quantity': q},
        ],
        'food_cents': items.fold<int>(0, (s, i) => s + i.$2 * i.$3),
        'delivery_fee_cents': pickup ? 0 : 500,
        'total_cents': items.fold<int>(0, (s, i) => s + i.$2 * i.$3) + 500,
        'commission_cents':
            (items.fold<int>(0, (s, i) => s + i.$2 * i.$3) * 0.05).round(),
        'address': '高新路 88 号 3 栋',
        'lat': lat,
        'lng': lng,
        'contact_phone': phone,
        'remark': remark,
        'pickup': pickup,
        'pickup_code': pickup ? '3721' : '',
        'to_door': true,
        'accepted_at': status == 'paid' ? null : iso(ago - const Duration(minutes: 1)),
        'created_at': iso(ago),
      };

  final pending = [
    order('SZ2609110008411',
        status: 'paid',
        items: [('牛肉面', 1600, 1), ('卤蛋', 250, 2)],
        remark: '不要香菜,面硬一点',
        ago: const Duration(seconds: 80)),
    order('SZ2609110000921',
        status: 'paid',
        items: [('酸辣粉', 1300, 2), ('凉拌黄瓜', 800, 1)],
        remark: '微辣',
        phone: '139****0921',
        pickup: true,
        ago: const Duration(seconds: 12)),
    order('SZ2609110007710',
        status: 'paid',
        items: [('牛肉面', 1800, 2)],
        phone: '137****7710',
        ago: const Duration(seconds: 5)),
  ];
  final others = [
    for (var i = 0; i < 5; i++)
      order('SZ26091100050$i',
          status: 'accepted',
          items: [('担担面', 1400, 1)],
          ago: Duration(minutes: 6 + i)),
    for (var i = 0; i < 2; i++)
      order('SZ26091100060$i',
          status: 'ready',
          items: [('牛肉面', 1600, 1)],
          ago: Duration(minutes: 20 + i)),
  ];

  List<Map<String, dynamic>> dishes() {
    Map<String, dynamic> d(int id, String name, String cat, int price,
            {int sold = 0, bool soldOut = false}) =>
        {
          'id': id,
          'merchant_id': 1,
          'name': name,
          'category': cat,
          'price_cents': price,
          'stock': soldOut ? 0 : 60,
          'sold_out_today': soldOut,
          'is_on_sale': true,
          'image_url': '',
          'sort': id,
          'monthly_sales': 200,
          'today_sold': sold,
        };
    return [
      d(1, '牛肉面', '面食', 1600, sold: 31),
      d(2, '担担面', '面食', 1400, sold: 12),
      d(3, '酸辣粉', '面食', 1300, sold: 18),
      d(4, '肥肠面', '面食', 1800, sold: 9, soldOut: true),
      d(5, '素椒杂酱面', '面食', 1200, sold: 7),
      d(6, '卤蛋', '面食', 250, sold: 40),
      d(7, '凉拌黄瓜', '面食', 600, sold: 5, soldOut: true),
      d(8, '豆浆', '面食', 300, sold: 15),
      d(9, '米粉', '粉', 1200, sold: 3),
      d(10, '红油抄手', '小吃', 1000, sold: 6),
      d(11, '冰粉', '饮品', 500, sold: 8),
    ];
  }

  List<Map<String, dynamic>> daily() => [
        for (var i = 0; i < now.day; i++)
          () {
            final food = 127000 + (i * 3700) % 25000;
            final c = (food * 0.05).round();
            return {
              'day': day(now.subtract(Duration(days: i))),
              'order_count': 41 + (i * 7) % 17,
              'food_cents': food,
              'commission_cents': c,
              'net_cents': food - c,
            };
          }(),
      ];

  ApiClient fakeApi() => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          Object? payload;
          switch (req.url.path) {
            case '/auth/login':
              payload = {
                'token': 'tkn',
                'user_id': 9,
                'name': '老张',
                'role': 'merchant'
              };
            case '/orders':
              payload = [...pending, ...others];
            case '/merchants/me':
              payload = shop();
            case '/merchants/me/todos':
              payload = {'pending_orders': 3, 'messages_unread': 0};
            case '/merchants/me/today':
              payload = {
                'today': {'orders': 58, 'gmv_cents': 150000, 'ongoing': 7,
                  'done': 47, 'cancelled': 1, 'pickup_orders': 4},
                'yesterday': {'orders': 51},
              };
            case '/merchants/me/finance/daily':
              final rows = daily();
              payload = req.url.queryParameters['days'] == '1'
                  ? [
                      {
                        'day': day(now),
                        'order_count': 47,
                        'food_cents': 126984,
                        'commission_cents': 6349,
                        'net_cents': 120635,
                      }
                    ]
                  : rows;
            case '/merchants/me/dishes':
              payload = dishes();
            case '/merchants/me/wallet':
              payload = {
                'balance_cents': 1386500,
                'total_earned_cents': 9864000,
                'pending_withdrawal_cents': 0,
                'withdrawn_cents': 8577500,
                'deposit_required_cents': 50000,
                'deposit_held_cents': 50000,
                'withdrawable_cents': 1336500,
              };
            case '/merchants/me/withdrawals':
              payload = <Map>[];
            case '/merchants/me/commission-tier':
              payload = {
                'commission_rate': 0.05,
                'tier_rate': 0.05,
                'tiers': <Map>[],
                'last_month_completed': 1402,
                'this_month_completed': 486,
                'next_tier_from': null,
                'next_tier_rate': null,
                'orders_to_next': null,
              };
            case '/payout-account':
              payload = {
                'configured': true,
                'kind': 'bank_personal',
                'holder_name': '张*',
                'bank_name': '建设银行',
                'account_tail': '0417',
              };
            case '/merchants/me/printers':
              payload = {
                'enabled': true,
                'items': [
                  {'id': 1, 'sn': '9200', 'purpose': 'front'}
                ],
              };
            case '/merchants/me/after-sales':
            case '/merchants/me/coupon-batches':
            case '/announcements':
              payload = <Map>[];
            case '/merchants/me/prep-time':
              payload = {
                'enough': false,
                'window_days': 30,
                'samples': 12,
                'min_samples': 20,
                'never_used_for': '这个数只用来帮你定承诺值,不参与排序、不影响流量分配',
              };
            case '/merchants/me/kitchen-cam':
              payload = {'status': 'none', 'listed_label': '无明厨亮灶'};
            case '/vouchers/redeemed-today':
              payload = {
                'count': 6,
                'net_cents': 17052,
                'items': [
                  for (final (t, at, tail, sell) in [
                    ('双人套餐', 1, '1204', 6800),
                    ('单人牛肉面套餐', 33, '0871', 1900),
                    ('双人套餐', 347, '5520', 6800),
                    ('单人牛肉面套餐', 373, '3318', 1900),
                  ])
                    {
                      'title': t,
                      'redeemed_at': iso(Duration(minutes: at)),
                      'code_tail': tail,
                      'sell_price_cents': sell,
                      'face_value_cents': sell + 1000,
                      'commission_cents': (sell * 0.02).round(),
                      'net_cents': sell - (sell * 0.02).round(),
                    },
                ],
              };
            case '/vouchers/redeem':
              payload = {
                'purchase_no': 'VP1',
                'voucher_id': 1,
                'merchant_id': 1,
                'sell_price_cents': 6800,
                'face_value_cents': 8800,
                'commission_cents': 136,
                'net_cents': 6664,
                'code': '882133901204',
                'status': 'redeemed',
                'redeemed_at': iso(Duration.zero),
                'title': '双人套餐',
              };
            default:
              payload = <String, dynamic>{};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  /// 商家端的主题,外加一处测试专用的补丁:组件主题里那些**没写字族**的
  /// 样式(AppBar 标题、按钮文字、输入框提示)在真机上落到系统字,
  /// 测试环境没有系统字、会画成方块,这里给它们指上 SzSans(+ 中文)。
  ThemeData theme() {
    final base = brandTheme(Brightness.light,
        density: SzDensity.operate, accentTone: 0);
    const fallback = ['PingFang SC'];
    TextStyle? fix(TextStyle? s) => (s ?? const TextStyle())
        .copyWith(fontFamily: kSansFamily, fontFamilyFallback: fallback);
    ButtonStyle? fixButton(ButtonStyle? b) => (b ?? const ButtonStyle())
        .copyWith(
            textStyle: WidgetStatePropertyAll(
                fix(b?.textStyle?.resolve(const <WidgetState>{}))));
    return base.copyWith(
      appBarTheme: base.appBarTheme
          .copyWith(titleTextStyle: fix(base.appBarTheme.titleTextStyle)),
      filledButtonTheme:
          FilledButtonThemeData(style: fixButton(base.filledButtonTheme.style)),
      outlinedButtonTheme: OutlinedButtonThemeData(
          style: fixButton(base.outlinedButtonTheme.style)),
      textButtonTheme:
          TextButtonThemeData(style: fixButton(base.textButtonTheme.style)),
      inputDecorationTheme: base.inputDecorationTheme
          .copyWith(hintStyle: fix(base.inputDecorationTheme.hintStyle)),
      segmentedButtonTheme: SegmentedButtonThemeData(
          style: fixButton(base.segmentedButtonTheme.style)),
    );
  }

  /// 数据是异步到的:到的那一帧才开始入场、滚数字,再多走几帧才停。
  /// 一次 pump(2 秒) 只画一帧,截到的是动画第 0 帧
  Future<void> settle(WidgetTester t) async {
    for (var i = 0; i < 6; i++) {
      await t.pump(const Duration(milliseconds: 500));
    }
  }

  Future<void> frame(WidgetTester t, Widget home) async {
    t.view
      ..devicePixelRatio = 2.0
      ..physicalSize = const Size(390, 844) * 2.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MediaQuery(
      data: const MediaQueryData(
          size: Size(390, 844), padding: EdgeInsets.only(top: 44)),
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: theme(),
        home: home,
      ),
    ));
    await settle(t);
  }

  Future<void> shot(WidgetTester t, String name) async {
    await expectLater(
        find.byType(MaterialApp), matchesGoldenFile('goldens/design_$name.png'));
  }

  Future<void> teardown(WidgetTester t) async {
    await t.pumpWidget(const SizedBox());
    await t.pump();
  }

  Future<void> tapNav(WidgetTester t, String label) async {
    await t.tap(find.descendant(
        of: find.byType(NavigationBar), matching: find.text(label)));
    await settle(t);
  }

  testWidgets('6a 看板', (t) async {
    final api = fakeApi();
    await api.login('13800000009', 'pw');
    await frame(t,
        MerchantHomePage(api: api, shop: Merchant.fromJson(shop())));
    await shot(t, '6a_board');
    await teardown(t);
  });

  testWidgets('6c 新单详情', (t) async {
    final o = Order.fromJson(pending.first);
    await frame(
        t,
        NewOrderPage(
          order: o,
          shop: Merchant.fromJson(shop()),
          promiseMinutes: 12,
          onAccept: () async => true,
          onReject: () async => false,
          onEditPromise: () async => null,
        ));
    await shot(t, '6c_new_order');
    await teardown(t);
  });

  testWidgets('6e 菜单', (t) async {
    final api = fakeApi();
    await api.login('13800000009', 'pw');
    await frame(t,
        MerchantHomePage(api: api, shop: Merchant.fromJson(shop())));
    await tapNav(t, '菜单');
    await shot(t, '6e_menu');
    await teardown(t);
  });

  testWidgets('6g 账本', (t) async {
    final api = fakeApi();
    await api.login('13800000009', 'pw');
    await frame(t,
        MerchantHomePage(api: api, shop: Merchant.fromJson(shop())));
    await tapNav(t, '账本');
    await shot(t, '6g_ledger');
    await teardown(t);
  });

  testWidgets('6i 店铺', (t) async {
    final api = fakeApi();
    await api.login('13800000009', 'pw');
    await frame(t,
        MerchantHomePage(api: api, shop: Merchant.fromJson(shop())));
    await tapNav(t, '店铺');
    await shot(t, '6i_shop');
    await teardown(t);
  });

  testWidgets('订单 tab', (t) async {
    final api = fakeApi();
    await api.login('13800000009', 'pw');
    await frame(t,
        MerchantHomePage(api: api, shop: Merchant.fromJson(shop())));
    await tapNav(t, '订单');
    await shot(t, 'orders');
    await teardown(t);
  });

  testWidgets('6k 团购核销', (t) async {
    final api = fakeApi();
    await api.login('13800000009', 'pw');
    await frame(t, VoucherRedeemPage(api: api));
    await shot(t, '6k_redeem');
    await teardown(t);
  });

  testWidgets('6l 核销成功(浅色)', (t) async {
    final api = fakeApi();
    await api.login('13800000009', 'pw');
    await frame(t, VoucherRedeemPage(api: api));
    await t.enterText(find.byType(TextField), '882133901204');
    await t.tap(find.text('核销'));
    await settle(t);
    await shot(t, '6l_redeem_success');
    await teardown(t);
  });
}
