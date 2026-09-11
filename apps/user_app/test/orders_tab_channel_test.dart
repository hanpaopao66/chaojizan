import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/channel_config.dart';
import 'package:user_app/main.dart';
import 'package:user_app/stay_order_pages.dart';

/// 订单 tab 的频道条(设计稿 3b)。
///
/// ## 这里守的两条,和原来分段器那版是同一件事
///
/// 1. **关掉一个频道不能没收凭证。** 频道开关管的是「能不能新买」,
///    不管「已买的还能不能看」—— 住宿关了,历史住宿单照样要在列表里、
///    频道条上照样要有「住宿」。所以频道条只看**有没有单**,不看 ChannelConfig;
/// 2. **不能把人关在一个回不去的筛选里。** 原来分段器在住宿关掉时整条藏掉,
///    人停在住宿列表上就再没有控件能切回外卖。现在条上永远有「全部」,
///    只剩一个频道有单时整条不出、列表本身就是全部。
///
/// 另外两条是这次新加的行为:「全部」里住宿单和外卖单**按下单时间混排**,
/// 以及 320 屏 + 长辈版 1.4× 下订单卡不画出界(按钮和金额挤不下时换行)。
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // package_info_plus 在测试环境没有平台通道:PackageInfo.fromPlatform()
  // **不抛异常,是永远不返回**,第一个发请求的用例会挂满 10 分钟超时。
  // 和 profile_view_test 同一个坑,同一个铺垫
  setUpAll(() {
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    ChannelConfig.resetForTest();
  });

  Map<String, dynamic> order(
    String no, {
    String createdAt = '2026-09-01T10:00:00Z',
    String status = 'completed',
    String? bizType = 'food',
    String kind = 'food',
    String merchant = '张记面馆',
    bool hasReview = true,
  }) =>
      {
        'order_no': no,
        'id': no.hashCode & 0xffff,
        'merchant_id': 1,
        'merchant_name': merchant,
        'status': status,
        'items': [
          {'dish_id': 1, 'name': '牛肉面', 'price_cents': 1800, 'quantity': 1},
        ],
        'food_cents': 1800,
        'delivery_fee_cents': 400,
        'commission_cents': 90,
        'total_cents': 2200,
        'address': '春熙路 1 号',
        'lat': 30.66,
        'lng': 104.08,
        'remark': '',
        'has_review': hasReview,
        'order_kind': kind,
        if (bizType != null) 'biz_type': bizType,
        'created_at': createdAt,
      };

  Map<String, dynamic> stay(String no,
          {String createdAt = '2026-09-01T10:00:00Z',
          String status = 'paid'}) =>
      {
        'order_no': no,
        'merchant_id': 9,
        'hotel_name': '测试酒店',
        'room_type_name': '大床房',
        'status': status,
        'status_label': '待确认',
        'checkin_date': '2026-09-20',
        'checkout_date': '2026-09-21',
        'nights': 1,
        'total_cents': 12800,
        'created_at': createdAt,
      };

  ApiClient fakeApi({
    List<Map<String, dynamic>> orders = const [],
    List<Map<String, dynamic>> stays = const [],
    Map<String, dynamic>? counts,
  }) =>
      ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          Object? payload;
          switch (req.url.path) {
            case '/auth/login':
              payload = {
                'token': 'tkn',
                'user_id': 1,
                'name': '张三',
                'role': 'customer',
              };
            case '/orders':
              // 翻页请求(带 before)一律回空:测的是第一页之后的行为
              payload = req.url.queryParameters.containsKey('before')
                  ? <Object>[]
                  : orders;
            case '/stays/orders/mine':
              payload = stays;
            case '/orders/counts':
              payload = counts ?? <String, Object>{};
            default:
              payload = <String, Object>{};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<void> pump(
    WidgetTester tester, {
    List<Map<String, dynamic>> orders = const [],
    List<Map<String, dynamic>> stays = const [],
    Size size = const Size(390, 844),
    double textScale = 1.0,
    Map<String, dynamic>? counts,
  }) async {
    tester.view
      ..devicePixelRatio = 3.0
      ..physicalSize = size * 3.0;
    addTearDown(tester.view.reset);
    final api = fakeApi(orders: orders, stays: stays, counts: counts);
    // 不登录的话订单页整页短路成登录引导,断言的是另一个界面
    await api.login('13800000001', '123456');
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context)
            .copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!,
      ),
      home: Scaffold(body: OrdersTab(api: api)),
    ));
    await tester.pumpAndSettle();
  }

  /// 频道条上的一颗。频道名在页面上是唯一的(状态 chip 里没有「点外卖」这些词);
  /// 状态那一排的第一颗叫「全部状态」(设计稿 3b),所以「全部」只在频道条上
  Finder pill(String label) => find.text(label);
  Finder allPill() => find.text('全部');

  /// 频道条出没出来:它在的时候页面上有「全部」
  bool stripShown() => find.text('全部').evaluate().length == 1;

  group('条上的数来自服务端全量 count(设计稿 3b)', () {
    // 列表第一页只有三单,服务端说一共 38 单 —— 条上写 38,不写 3
    final counts = {
      'food': [
        {
          'biz_type': 'food',
          'total': 31,
          'pending_payment': 1,
          'active': 1,
          'to_review': 3,
        },
        {
          'biz_type': 'errand',
          'total': 5,
          'pending_payment': 0,
          'active': 0,
          'to_review': 0,
        },
      ],
      'stay': {'total': 2, 'pending_payment': 0, 'active': 0, 'to_review': 0},
    };
    final three = [
      order('F1'),
      order('E1', bizType: 'errand', kind: 'errand_send', merchant: '帮送'),
    ];

    testWidgets('频道后面是单数,状态只给三个待办带数', (tester) async {
      await pump(tester,
          orders: three, stays: [stay('S1')], counts: counts);
      for (final n in ['38', '31', '5', '2']) {
        expect(find.text(n), findsOneWidget, reason: '条上缺了「$n」');
      }
      expect(find.text('全部状态'), findsOneWidget);
      expect(find.text('待支付 · 1'), findsOneWidget);
      expect(find.text('进行中 · 1'), findsOneWidget);
      expect(find.text('待评价 · 3'), findsOneWidget);
      // 退款售后不是待办,不给数。它排在第五颗,390 宽下在横滑的屏外
      expect(find.text('退款售后', skipOffstage: false), findsOneWidget);
    });

    testWidgets('换到「帮我送」:状态上的数跟着换成这个频道的,0 不写', (tester) async {
      await pump(tester,
          orders: three, stays: [stay('S1')], counts: counts);
      await tester.tap(pill('帮我送'));
      await tester.pumpAndSettle();
      expect(find.text('待支付'), findsOneWidget);
      expect(find.text('待评价 · 3'), findsNothing);
    });

    testWidgets('接口回了不认识的形状:不挂数,更不挂 0', (tester) async {
      await pump(tester, orders: three, stays: [stay('S1')], counts: {});
      expect(stripShown(), isTrue);
      expect(find.text('0'), findsNothing);
      expect(find.text('待支付'), findsOneWidget);
    });
  });

  group('关频道不能没收凭证', () {
    testWidgets('住宿关掉了,历史住宿单照样在「全部」里,条上照样有「住宿」',
        (tester) async {
      ChannelConfig.setForTest(const ['food', 'voucher']); // 住宿已关
      await pump(tester,
          orders: [order('F1')],
          stays: [stay('S1', createdAt: '2026-09-02T10:00:00Z')]);

      expect(find.byType(StayOrderCard), findsOneWidget,
          reason: '订单是凭证:用户要拿它入住、退款 —— 关频道不能让它从列表里消失');
      expect(pill('住宿'), findsOneWidget);
      expect(stripShown(), isTrue, reason: '条上要有「全部」,人才回得去');
    });

    testWidgets('跑腿单在老服务端(不给 biz_type)也归「帮我送」,不混进外卖',
        (tester) async {
      await pump(tester, orders: [
        order('F1'),
        order('E1', bizType: null, kind: 'errand_send', merchant: '帮送'),
      ]);
      expect(pill('帮我送'), findsOneWidget);
      expect(pill('点外卖'), findsOneWidget);
    });
  });

  group('不能关在回不去的筛选里', () {
    testWidgets('只有一个频道有单:整条不出(一个选项的切换器是噪音)',
        (tester) async {
      await pump(tester, orders: [order('F1'), order('F2')]);
      expect(stripShown(), isFalse);
      expect(find.text('张记面馆'), findsNWidgets(2));
    });

    testWidgets('选了频道只看这个频道;点「全部」回得来', (tester) async {
      await pump(tester,
          orders: [order('F1'), order('R1', bizType: 'retail', merchant: '鲜果铺')],
          stays: [stay('S1')]);
      expect(pill('买菜买水果'), findsOneWidget);

      await tester.tap(pill('住宿'));
      await tester.pumpAndSettle();
      expect(find.byType(StayOrderCard), findsOneWidget);
      expect(find.text('张记面馆'), findsNothing);

      await tester.tap(pill('买菜买水果'));
      await tester.pumpAndSettle();
      expect(find.text('鲜果铺'), findsOneWidget);
      expect(find.byType(StayOrderCard), findsNothing);

      await tester.tap(allPill());
      await tester.pumpAndSettle();
      expect(find.text('鲜果铺'), findsOneWidget);
      expect(find.text('张记面馆'), findsOneWidget);
      expect(find.byType(StayOrderCard), findsOneWidget);
    });
  });

  group('「全部」混排', () {
    double topOf(WidgetTester tester, Finder f) => tester.getTopLeft(f).dy;

    testWidgets('住宿单按下单时间插在外卖单中间', (tester) async {
      await pump(tester, orders: [
        order('F1', createdAt: '2026-09-03T10:00:00Z', merchant: '新的面馆'),
        order('F2', createdAt: '2026-09-01T10:00:00Z', merchant: '旧的面馆'),
      ], stays: [
        stay('S1', createdAt: '2026-09-02T10:00:00Z'),
      ]);
      final newer = topOf(tester, find.text('新的面馆'));
      final hotel = topOf(tester, find.byType(StayOrderCard));
      final older = topOf(tester, find.text('旧的面馆'));
      expect(newer < hotel && hotel < older, isTrue,
          reason: '住宿单下在两单外卖之间,就该排在它俩之间');
    });

    testWidgets('外卖还没翻到底时,比已拉到的外卖都早的住宿单先不放', (tester) async {
      // 一整页 20 单 = 服务端可能还有更早的。这时放出一张 8 月的住宿单,
      // 往下再拉一页,新到的外卖单会插到它上面 —— 列表在手指底下重排
      final page = [
        for (var d = 30; d >= 11; d--)
          order('F$d', createdAt: '2026-09-${d.toString().padLeft(2, '0')}T10:00:00Z'),
      ];
      await pump(tester, orders: page, stays: [
        stay('S-OLD', createdAt: '2026-08-01T10:00:00Z'),
      ]);
      expect(find.byType(StayOrderCard, skipOffstage: false), findsNothing,
          reason: '第一页没拉满时才敢放更早的单');
    });
  });

  group('窄屏 + 长辈版', () {
    testWidgets('320 屏 1.4×:待评价的完成单两个按钮也不画出界', (tester) async {
      await pump(tester,
          orders: [order('F1', hasReview: false, merchant: '一家名字很长很长的面馆')],
          size: const Size(320, 640),
          textScale: 1.4);
      expect(tester.takeException(), isNull);
      expect(find.text('去评价'), findsOneWidget);
      expect(find.text('再来一单'), findsOneWidget);
    });

    testWidgets('进行中的单画进度行,节点名排得下', (tester) async {
      await pump(tester,
          orders: [order('F1', status: 'picked_up')],
          size: const Size(320, 640),
          textScale: 1.4);
      expect(tester.takeException(), isNull);
      for (final n in ['接单', '出餐', '取餐', '配送', '送达']) {
        expect(find.text(n), findsOneWidget, reason: '缺了进度节点「$n」');
      }
    });
  });
}
