import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/main.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'order_fake_api.dart';
import 'shop_fake_api.dart';

/// 订单 tab:待接单这个数从哪儿来、催单语音的判据是什么、历史是不是真历史、
/// 动作行在窄屏放不放得下。
///
/// ## 这四件事都是「安静地错」
///
/// `/orders` 默认 `limit=20`(api_client.dart),服务端按 `created_at desc`
/// 切片、不带状态过滤(orders.py)。而 `_orders` 这一个列表同时驱动:
/// 顶栏「N 单待接」、三个分段的内容、**以及每 10 秒一次的催单语音**。
///
/// 午高峰 20 单以上时,更早的未接单会掉出这个窗口 —— 顶栏数不到、
/// 列表里看不见、**语音也不再响**。而这个文件自己的注释写着
/// 「午高峰漏一单,这个平台赔不起」。
///
/// 服务端早就有权威数:`/merchants/me/todos` 的 `pending_orders`
/// 是 `count(Order.id) where status == PAID`,全量、无窗口 ——
/// 而订单页**已经把它拉下来了**,只是一次都没用。
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

  Future<void> pumpHome(
    WidgetTester t,
    ApiClient api, {
    double width = 390,
    double height = 844,
    double scale = 1.0,
  }) async {
    setPhoneViewport(t, Size(width, height));
    await t.pumpWidget(MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: brandTheme(Brightness.light, density: SzDensity.operate),
        home: MerchantHomePage(api: api, shop: Merchant.fromJson(shopJson())),
      ),
    ));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
  }

  /// 拆掉页面,让 `dispose()` 把三个定时器和 WebSocket 收干净。
  /// 不拆的话 `testWidgets` 结束时会报 "A Timer is still pending"。
  Future<void> teardown(WidgetTester t) async {
    await t.pumpWidget(const SizedBox());
    await t.pump();
  }

  /// 屏幕上出现过的整段文字里,有没有哪一段包含 [needle]。
  bool hasTextContaining(String needle) => find
      .byType(Text)
      .evaluate()
      .map((e) => (e.widget as Text).data ?? '')
      .any((s) => s.contains(needle));

  String? titleText() {
    for (final e in find.byType(Text).evaluate()) {
      final d = (e.widget as Text).data ?? '';
      if (d.startsWith('订单')) return d;
    }
    return null;
  }

  group('待接单这个数不许从一页列表里数出来', () {
    testWidgets('25 单待接,而 /orders 一页只回 20 单 —— 顶栏要说 25', (t) async {
      // 25 单全是待接。服务端一页最多回 20(orders.py limit 上限 50,
      // 客户端默认 20),所以列表里只看得见 20 单
      final api = orderFakeApi(
        pages: ordersJson(count: 25, prefix: 'SZPAID'),
        todos: {'pending_orders': 25},
      );
      await pumpHome(t, api);

      expect(titleText(), '订单(25 单待接)',
          reason: '顶栏的数字是从 20 条列表里数出来的 —— '
              '第 21 单之后的未接单不但看不见,连数都数不到');
      await teardown(t);
    });

    testWidgets('顶栏的数走服务端聚合,不是列表长度', (t) async {
      // 列表里一单待接都没有(最新 20 单全已完成),而服务端说还欠着 5 单 ——
      // 那 5 单比这 20 单更早,已经掉出窗口了
      final api = orderFakeApi(
        pages: [
          ...ordersJson(count: 20, prefix: 'SZDONE', status: 'completed'),
          ...ordersJson(count: 5, prefix: 'SZOLD', startMinutesAgo: 120),
        ],
        todos: {'pending_orders': 5},
      );
      await pumpHome(t, api);

      expect(titleText(), '订单(5 单待接)',
          reason: '列表里看不见 ≠ 没有。服务端 /todos.pending_orders 说还有 5 单');
      await teardown(t);
    });

    testWidgets('掉出窗口的未接单要能在「待接单」栏里看到并接掉', (t) async {
      final log = OrdersRequestLog();
      final api = orderFakeApi(
        pages: [
          ...ordersJson(count: 20, prefix: 'SZDONE', status: 'completed'),
          ...ordersJson(count: 5, prefix: 'SZOLD', startMinutesAgo: 120),
        ],
        todos: {'pending_orders': 5},
        log: log,
      );
      await pumpHome(t, api, height: 1600);

      expect(log.byStatus, isNotEmpty,
          reason: '服务端说还欠 5 单、列表里一单都没有,就该按状态单独拉一次 —— '
              '光把数字改对,商家听见响却找不到那一单');
      expect(hasTextContaining('SZOLD'), isFalse,
          reason: '(订单号不直接上屏,这里只是防止断言写错)');
      expect(find.widgetWithText(FilledButton, '接单'), findsWidgets,
          reason: '待接单栏里必须真有单可接,不能是「这一栏没有订单」');
      await teardown(t);
    });
  });

  group('催单语音的判据 —— 漏单的最后一道防线', () {
    /// `OrderAnnouncer.announce()` 第一句是 `HapticFeedback.vibrate()`,
    /// 走 `SystemChannels.platform`。截下这个通道就能数出「催了几次」——
    /// 比断言源码里那一行文本靠谱得多。
    List<String> hookPlatformChannel(WidgetTester t) {
      final calls = <String>[];
      t.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
        calls.add(call.method == 'HapticFeedback.vibrate'
            ? 'vibrate'
            : '${call.method}:${call.arguments}');
        return null;
      });
      addTearDown(() => t.binding.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, null));
      return calls;
    }

    testWidgets('未接单掉出 20 条窗口之后,语音仍然要催', (t) async {
      final api = orderFakeApi(
        pages: [
          ...ordersJson(count: 20, prefix: 'SZDONE', status: 'completed'),
          ...ordersJson(count: 5, prefix: 'SZOLD', startMinutesAgo: 120),
        ],
        todos: {'pending_orders': 5},
      );
      await pumpHome(t, api);
      final calls = hookPlatformChannel(t);

      // 催单定时器 10 秒一跳
      await t.pump(const Duration(seconds: 11));

      expect(calls.where((c) => c == 'vibrate'), isNotEmpty,
          reason: '列表里数不到待接单,催单就哑了 —— '
              '而这正是商家最需要被叫醒的时候(五单没接,全掉出窗口)');
      await teardown(t);
    });

    testWidgets('真的一单不欠时不许乱催', (t) async {
      final api = orderFakeApi(
        pages: ordersJson(count: 20, prefix: 'SZDONE', status: 'completed'),
        todos: {'pending_orders': 0},
      );
      await pumpHome(t, api);
      final calls = hookPlatformChannel(t);
      await t.pump(const Duration(seconds: 11));

      expect(calls.where((c) => c == 'vibrate'), isEmpty,
          reason: '没有待接单还在响,商家下次就不信这个提示音了');
      await teardown(t);
    });
  });

  group('「历史」要是真历史,不是最近 20 单的残余', () {
    testWidgets('最新 20 单全在进行中时,历史栏要能往前翻', (t) async {
      final api = orderFakeApi(
        pages: [
          ...ordersJson(count: 20, prefix: 'SZGOING', status: 'accepted'),
          ...ordersJson(
              count: 12,
              prefix: 'SZHIST',
              status: 'completed',
              startMinutesAgo: 300),
        ],
        todos: {'pending_orders': 0},
      );
      await pumpHome(t, api, height: 1600);

      await t.tap(find.text('历史'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));

      expect(hasTextContaining('这一栏没有订单'), isFalse,
          reason: '「历史」是从最近 20 单里过滤出来的 —— 一家一天 40 单的店,'
              '过了午市点历史可能一条都没有,而屏幕会说「没有订单」');
      expect(find.byType(RefreshIndicator), findsOneWidget);
      await teardown(t);
    });

    testWidgets('历史栏有「看更早的」,点了能翻出上一页', (t) async {
      final api = orderFakeApi(
        pages: [
          ...ordersJson(count: 20, prefix: 'SZGOING', status: 'accepted'),
          // 24 条更早的已完成单:第一页(20 条)满,所以还有「更早的」可翻
          ...ordersJson(
              count: 24,
              prefix: 'SZHIST',
              status: 'completed',
              startMinutesAgo: 300),
        ],
        todos: {'pending_orders': 0},
      );
      await pumpHome(t, api, height: 2400);
      await t.tap(find.text('历史'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));

      final more = find.text('看更早的订单');
      expect(more, findsOneWidget,
          reason: '历史没有翻页入口 = 更早的单永远看不到,'
              '而平台的招牌是「每一单的账都可查」');
      await t.tap(more);
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(find.byType(RefreshIndicator), findsOneWidget);
      await teardown(t);
    });
  });

  group('订单卡的动作行:窄屏上一个按钮都不许被推出卡外', () {
    /// 一张待接单卡 + 一张自送待取餐卡。
    /// 后者是最宽的一种(打印 + 聊天 + 地图 + 开始配送(自送))。
    ApiClient twoCards() => orderFakeApi(
          pages: [
            orderJson(no: 'SZ0001'),
            orderJson(
                no: 'SZ0002',
                status: 'ready',
                selfDelivery: true,
                created: DateTime.now()
                    .subtract(const Duration(minutes: 30))
                    .toUtc()
                    .toIso8601String()),
          ],
          todos: {'pending_orders': 1},
        );

    for (final (width, scale) in const [
      (390.0, 1.0),
      (360.0, 1.0),
      (320.0, 1.0),
      (390.0, 1.4),
      (320.0, 1.4),
    ]) {
      testWidgets('${width.toInt()}dp × ${scale}x 不溢出', (t) async {
        await pumpHome(t, twoCards(), width: width, height: 2400, scale: scale);

        // 待接单栏:打印 + 聊天 + 缺货退款 + 拒单 + 接单(实测本征宽 354px)
        expect(find.widgetWithText(FilledButton, '接单'), findsOneWidget,
            reason: '卡没渲染出来的话,下面几条断言等于没测');
        expect(t.takeException(), isNull,
            reason: 'RenderFlex 溢出了 —— 溢出时 end 对齐退化成 start,'
                '被挤出去的是最后一个孩子,也就是「接单」');
        expect(buttonsOutsideCard(t, width), isEmpty, reason: '按钮被画到卡片内容区外面了');
        expect(textsPaintingOutside(t), isEmpty);

        // 进行中栏:自送待取餐是最宽的一种(实测本征宽 410px)
        await t.tap(find.text('进行中'));
        await t.pump();
        await t.pump(const Duration(milliseconds: 200));
        expect(find.widgetWithText(FilledButton, '开始配送(自送)'), findsOneWidget);
        expect(t.takeException(), isNull, reason: '自送待取餐那一行要 410px,比待接单还宽');
        expect(buttonsOutsideCard(t, width), isEmpty);
        expect(textsPaintingOutside(t), isEmpty);
        await teardown(t);
      });
    }

    testWidgets('进行中卡在 320 上也放得下', (t) async {
      final api = orderFakeApi(
        pages: [
          orderJson(
              no: 'SZ0003',
              status: 'accepted',
              accepted: DateTime.now()
                  .subtract(const Duration(minutes: 9))
                  .toUtc()
                  .toIso8601String()),
        ],
        todos: {'pending_orders': 0},
      );
      await pumpHome(t, api, width: 320, height: 1600);
      await t.tap(find.text('进行中'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 200));
      expect(find.widgetWithText(FilledButton, '出餐完成'), findsOneWidget);
      expect(t.takeException(), isNull);
      expect(buttonsOutsideCard(t, 320), isEmpty);
      await teardown(t);
    });
  });
}
