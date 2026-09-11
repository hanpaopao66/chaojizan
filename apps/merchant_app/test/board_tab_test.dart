import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/main.dart';
import 'package:merchant_app/new_order_page.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'order_fake_api.dart';
import 'shop_fake_api.dart';

/// 看板 tab(设计稿 6a)和新单详情(6c)。
///
/// 看板和订单 tab 共用同一份订单列表、待接数、接单拒单、WebSocket 和定时器,
/// 所以这里测的是**看板怎么把那一份数说对**:台面上的钱是哪个口径、
/// 三格各数的是什么、卡片上的编号和钱从哪儿来,以及几件动手的事
/// (全部接单、关店、进详情接单)请求有没有真的发出去。
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

  String todayKey() {
    final d = DateTime.now();
    return '${d.year}-${d.month.toString().padLeft(2, '0')}-'
        '${d.day.toString().padLeft(2, '0')}';
  }

  String minutesAgo(int m) =>
      DateTime.now().subtract(Duration(minutes: m)).toUtc().toIso8601String();

  Future<void> pumpBoard(
    WidgetTester t,
    ApiClient api, {
    Map<String, dynamic>? shop,
    double height = 1600,
  }) async {
    setPhoneViewport(t, Size(390, height));
    await t.pumpWidget(MaterialApp(
      theme:
          brandTheme(Brightness.light, density: SzDensity.operate, accentTone: 0),
      home: MerchantHomePage(
          api: api, shop: Merchant.fromJson(shop ?? shopJson())),
    ));
    await t.pump();
    await t.pump(const Duration(milliseconds: 600));
  }

  Future<void> teardown(WidgetTester t) async {
    await t.pumpWidget(const SizedBox());
    await t.pump();
  }

  /// 三格之一上的那个数
  String tileCount(WidgetTester t, String label) {
    final tile = find
        .ancestor(of: find.text(label), matching: find.byType(InkWell))
        .first;
    return t
        .widgetList<Text>(find.descendant(of: tile, matching: find.byType(Text)))
        .first
        .data!;
  }

  List<String> textsIn(Finder scope) => [
        for (final e
            in find.descendant(of: scope, matching: find.byType(Text)).evaluate())
          (e.widget as Text).data ??
              (e.widget as Text).textSpan?.toPlainText() ??
              '',
      ];

  group('标题栏与台面', () {
    testWidgets('落地就是看板:店名、营业 pill、消息铃铛', (t) async {
      final api = orderFakeApi(pages: const [], shop: shopJson());
      await pumpBoard(t, api);
      expect(find.text('张记牛肉面'), findsOneWidget);
      expect(find.widgetWithText(SzStatePill, '营业中'), findsOneWidget);
      expect(find.byTooltip('消息'), findsOneWidget);
      await teardown(t);
    });

    testWidgets('今日实收是 /finance/daily 今天那一行的 net —— 和账本同一个口径',
        (t) async {
      final log = OrdersRequestLog();
      final api = orderFakeApi(
        pages: const [],
        shop: shopJson(),
        log: log,
        daily: [
          {
            'day': todayKey(),
            'order_count': 47,
            'food_cents': 126984,
            'commission_cents': 6349,
            'net_cents': 120635,
          },
        ],
      );
      await pumpBoard(t, api);
      expect(t.widget<SzRollingAmount>(find.byType(SzRollingAmount)).cents,
          120635);
      final slab = textsIn(find.byType(SzLedgerCard));
      expect(slab, contains('今日实收 · 菜价 − 4.5%'),
          reason: '费率照店铺的档位写,4.5% 不许截成 4%');
      expect(slab.where((s) => s.contains('¥63.49')), isNotEmpty,
          reason: '平台抽了多少是同一行的 commission');
      expect(slab.where((s) => s.contains('明天')), isEmpty,
          reason: '提现是商家自己点的,不是每天自动打款 —— 不说「明天到卡」');
      await teardown(t);
    });

    testWidgets('区域经理 / 店员:台面上没有钱,换成今日单量', (t) async {
      final api = orderFakeApi(
        pages: const [],
        shop: shopJson(viewerIsOwner: false),
        today: merchantTodayJson(orders: 12),
      );
      await pumpBoard(t, api, shop: shopJson(viewerIsOwner: false));
      expect(find.byType(SzRollingAmount), findsNothing);
      final slab = textsIn(find.byType(SzLedgerCard));
      expect(slab, contains('今日订单 · 下单口径'));
      expect(slab, contains('12 单'));
      expect(slab.where((s) => s.contains('¥')), isEmpty,
          reason: '/finance/daily 对非经营者本人是 403 —— 钱不是给他看的');
      await teardown(t);
    });
  });

  group('三格', () {
    testWidgets('待接单和订单 tab 同一个数;待骑手取不数自取和自己送的单', (t) async {
      // 「掉出 20 条窗口的待接单也要数到」由 order_tab_test.dart 守着 ——
      // 看板读的是同一个 _pendingCount,这里只验三格各数的是什么
      final api = orderFakeApi(
        pages: [
          for (var i = 0; i < 5; i++) orderJson(no: 'SZP$i'),
          for (var i = 0; i < 3; i++) orderJson(no: 'SZA$i', status: 'accepted'),
          orderJson(no: 'SZR1', status: 'ready'),
          orderJson(no: 'SZR2', status: 'ready', pickup: true),
          orderJson(no: 'SZR3', status: 'ready', selfDelivery: true),
        ],
        todos: {'pending_orders': 5},
        shop: shopJson(),
      );
      await pumpBoard(t, api);
      expect(tileCount(t, '待接单'), '5');
      expect(tileCount(t, '制作中'), '3');
      expect(tileCount(t, '待骑手取'), '1',
          reason: '自取的等顾客、自己送的等商家,都不等骑手');
      await teardown(t);
    });
  });

  group('待接单卡(设计稿 6a)', () {
    testWidgets('#单号后四位、下单时刻与尾号、菜价 − 费率、做完到手多少', (t) async {
      final api = orderFakeApi(
        pages: [orderJson(no: 'SZ2026091100128411', contactPhone: '138****3382')],
        todos: {'pending_orders': 1},
        shop: shopJson(),
      );
      await pumpBoard(t, api);
      // 服务端不发「当天第几单」,拿单号尾巴当叫号,和小票上印的对得上
      expect(find.text('#128411'), findsOneWidget);
      expect(find.textContaining('尾号 3382'), findsOneWidget);
      // 菜品 34.00(28 + 3×2),平台 4.5% 支付时落定为 2.16
      expect(find.text('菜价 ¥34.00 − 4.5%'), findsOneWidget);
      expect(find.text('¥31.84'), findsOneWidget);
      expect(find.text('接单 · 15 分出餐'), findsOneWidget,
          reason: '按钮上写明按承诺几分钟出餐');
      await teardown(t);
    });

    testWidgets('新单光晕只给工作台打开之后来的单,冷启动时已有的不闪', (t) async {
      final api = orderFakeApi(
        pages: [
          orderJson(no: 'SZOLD1', created: minutesAgo(4)),
          // 打开工作台之后才下的单(时刻在打开之后)
          orderJson(
              no: 'SZNEW1',
              created: DateTime.now()
                  .add(const Duration(minutes: 1))
                  .toUtc()
                  .toIso8601String()),
        ],
        todos: {'pending_orders': 2},
        shop: shopJson(),
      );
      await pumpBoard(t, api);
      final glows = t.widgetList<SzAttention>(find.byType(SzAttention)).toList();
      expect(glows, hasLength(2));
      expect(glows.where((g) => g.playOnMount), hasLength(1),
          reason: '冷启动时列表里已有的单不该集体闪一遍(动效规范 07)');
      expect(find.text('新单'), findsOneWidget, reason: '「新单」字样只给新来的那一单');
      await teardown(t);
    });

    testWidgets('全部接单:先问一句,再按下单先后逐单接', (t) async {
      final log = OrdersRequestLog();
      final api = orderFakeApi(
        pages: [
          orderJson(no: 'SZ0003', created: minutesAgo(1)),
          orderJson(no: 'SZ0001', created: minutesAgo(3)),
          orderJson(no: 'SZ0002', created: minutesAgo(2)),
        ],
        todos: {'pending_orders': 3},
        shop: shopJson(),
        log: log,
      );
      await pumpBoard(t, api);
      await t.tap(find.widgetWithText(TextButton, '全部接单'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(find.text('一次接下 3 单?'), findsOneWidget,
          reason: '没有批量接口,一次接十几单是个大动作,先问');
      expect(log.accepted, isEmpty, reason: '还没确认就接了');
      await t.tap(find.widgetWithText(FilledButton, '全部接单'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(log.accepted, ['SZ0001', 'SZ0002', 'SZ0003'],
          reason: '先下的单先接:顾客等得最久');
      expect(find.text('已接 3 单'), findsOneWidget);
      await teardown(t);
    });
  });

  group('营业 pill(动效规范 10)', () {
    testWidgets('关店先确认,手上还有单要把数说出来;取消就不动', (t) async {
      final log = OrdersRequestLog();
      final api = orderFakeApi(
        pages: [
          orderJson(no: 'SZP1'),
          orderJson(no: 'SZP2'),
          orderJson(no: 'SZA1', status: 'accepted'),
        ],
        todos: {'pending_orders': 2},
        shop: shopJson(),
        log: log,
      );
      await pumpBoard(t, api);
      await t.tap(find.widgetWithText(SzStatePill, '营业中'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(find.text('现在打烊?'), findsOneWidget);
      expect(find.textContaining('你手上还有 3 单'), findsOneWidget,
          reason: '打烊不会取消已下的单,商家得知道手上还有几单要做完');
      await t.tap(find.text('先不打烊'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(log.writes.where((w) => w.$2 == '/merchants/me'), isEmpty);
      expect(find.widgetWithText(SzStatePill, '营业中'), findsOneWidget);

      await t.tap(find.widgetWithText(SzStatePill, '营业中'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      await t.tap(find.widgetWithText(FilledButton, '打烊'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      final patch = log.writes.where((w) => w.$2 == '/merchants/me').toList();
      expect(patch, hasLength(1));
      expect(patch.single.$3, {'is_open': false});
      expect(find.widgetWithText(SzStatePill, '已打烊'), findsOneWidget);
      await teardown(t);
    });

    testWidgets('开店不问 —— 开错了关掉就是', (t) async {
      final log = OrdersRequestLog();
      final shop = shopJson(isOpen: false);
      final api =
          orderFakeApi(pages: const [], shop: shop, log: log);
      await pumpBoard(t, api, shop: shop);
      await t.tap(find.widgetWithText(SzStatePill, '已打烊'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(find.text('现在打烊?'), findsNothing);
      expect(log.writes.single.$3, {'is_open': true});
      expect(find.widgetWithText(SzStatePill, '营业中'), findsOneWidget);
      await teardown(t);
    });

    testWidgets('食安停业:pill 说「食安停业」,点了只解释,不发请求', (t) async {
      final log = OrdersRequestLog();
      final shop = shopJson(isOpen: false, foodSafetyHold: true);
      final api = orderFakeApi(pages: const [], shop: shop, log: log);
      await pumpBoard(t, api, shop: shop);
      await t.tap(find.widgetWithText(SzStatePill, '食安停业'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(find.text('食安停业中'), findsOneWidget);
      expect(log.writes, isEmpty);
      await teardown(t);
    });

    testWidgets('临时歇业中:pill 说「歇业中」,不说「已打烊」', (t) async {
      final shop = shopJson(
          isOpen: false,
          closedUntil: DateTime.now()
              .toUtc()
              .add(const Duration(hours: 2))
              .toIso8601String());
      final api = orderFakeApi(pages: const [], shop: shop);
      await pumpBoard(t, api, shop: shop);
      expect(find.widgetWithText(SzStatePill, '歇业中'), findsOneWidget,
          reason: '歇业是到点自动恢复的,和手动打烊对商家是两回事');
      await teardown(t);
    });
  });

  group('新单详情(设计稿 6c)', () {
    testWidgets('点卡片进详情;在详情里接单,请求走工作台,成功后退回', (t) async {
      final log = OrdersRequestLog();
      final api = orderFakeApi(
        pages: [orderJson(no: 'SZ2026091100128411')],
        todos: {'pending_orders': 1},
        shop: shopJson(),
        log: log,
      );
      await pumpBoard(t, api);
      await t.tap(find.text('#128411'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 400));
      expect(find.text('新单 #128411'), findsOneWidget);
      await t.tap(find.text('接单,15 分钟出餐'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 100));
      expect(log.accepted, ['SZ2026091100128411']);
      expect(find.text('已接单'), findsOneWidget, reason: '成功态(规范 06)');
      // 成功块停 800ms 再退回
      await t.pump(const Duration(milliseconds: 900));
      await t.pump(const Duration(milliseconds: 400));
      expect(find.text('新单 #128411'), findsNothing);
      await teardown(t);
    });

    Future<void> pumpDetail(WidgetTester t, Map<String, dynamic> order) async {
      setPhoneViewport(t, const Size(390, 1200));
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light,
            density: SzDensity.operate, accentTone: 0),
        home: NewOrderPage(
          order: Order.fromJson(order),
          shop: Merchant.fromJson(shopJson()),
          promiseMinutes: 15,
          busyExtraMinutes: 10,
          onAccept: () async => true,
          onReject: () async => false,
        ),
      ));
      await t.pump();
    }

    testWidgets('分账:平台 4.5% 订单完成才收,配送费全额归骑手、与商家无关', (t) async {
      await pumpDetail(t, orderJson(no: 'SZ0001'));
      expect(find.text('菜价合计'), findsOneWidget);
      expect(find.text('平台 4.5%(订单完成才收)'), findsOneWidget);
      expect(find.text('−¥2.16'), findsOneWidget);
      expect(find.text('配送费 ¥4 → 骑手全额,与你无关'), findsOneWidget);
      expect(find.text('¥31.84'), findsOneWidget);
      await t.pumpWidget(const SizedBox());
    });

    testWidgets('自己送的单:配送费归商家,算进实收', (t) async {
      await pumpDetail(t, orderJson(no: 'SZ0001', selfDelivery: true));
      expect(find.text('配送费 ¥4 · 你自己送,归你'), findsOneWidget);
      expect(find.text('¥35.84'), findsOneWidget,
          reason: '和服务端 credit_merchant_for_order 同口径:自送单配送费并进商家应收');
      await t.pumpWidget(const SizedBox());
    });

    testWidgets('自取单:没有配送费这一说', (t) async {
      await pumpDetail(t, orderJson(no: 'SZ0001', pickup: true));
      expect(find.text('到店自取 · 无配送费'), findsOneWidget);
      await t.pumpWidget(const SizedBox());
    });

    testWidgets('不编数据:没有「第 N 次来」;出餐时间照实按店铺承诺(含忙碌加时)',
        (t) async {
      await pumpDetail(t, orderJson(no: 'SZ0001'));
      expect(find.textContaining('次来'), findsNothing,
          reason: '服务端不给商家顾客的到店次数');
      expect(
          find.textContaining('按店铺承诺 15 分钟 · 忙碌模式 +10 分钟',
              findRichText: true),
          findsOneWidget,
          reason: '没有逐单改出餐时间的接口,不画那四个按钮');
      expect(find.text('接单,25 分钟出餐'), findsOneWidget);
      expect(find.textContaining('直线'), findsOneWidget,
          reason: '距离是按坐标算的直线,不是骑行路程');
      await t.pumpWidget(const SizedBox());
    });
  });

  group('提示音(动效规范 07)', () {
    /// 截下平台通道:震动一次 = 响了一轮
    List<String> hook(WidgetTester t) {
      final calls = <String>[];
      t.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        calls.add(call.method);
        return null;
      });
      addTearDown(() => t.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null));
      return calls;
    }

    // 一轮两声(间隔 600ms)的节奏在 order_announcer_test.dart 里量:
    // 测试环境没有播放器插件,整页跑的时候那两声观察不到
    testWidgets('有待接单时 30 秒响一轮', (t) async {
      final api = orderFakeApi(
        pages: [orderJson(no: 'SZ0001')],
        todos: {'pending_orders': 1},
        shop: shopJson(),
      );
      await pumpBoard(t, api);
      final calls = hook(t);
      await t.pump(const Duration(seconds: 29));
      expect(calls.where((c) => c == 'HapticFeedback.vibrate'), isEmpty,
          reason: '原来 10 秒一遍,一单没接一分钟响六次 —— 商家会去把声音关掉');
      await t.pump(const Duration(seconds: 2));
      expect(calls.where((c) => c == 'HapticFeedback.vibrate'), hasLength(1));
      await teardown(t);
    });
  });
}
