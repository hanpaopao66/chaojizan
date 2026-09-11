import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rider_app/hall_widgets.dart';
import 'package:rider_app/main.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 抢单卡的信息密度。
///
/// ## 这一端的判据和用户端不一样
///
/// 用户端那轮的结论是「一屏多塞几张」。这里不是 —— 骑手在路上,单手、
/// 可能戴手套、屏幕上可能有雨。**触控区只能更大不能更小**
/// (见 profile_grid_test 那条 4 格上限)。
///
/// 所以这一组盯的不是"塞得下几张",是**同一件事说了几遍**:
/// 卡上曾经把两段距离显示两次(1878 行用米、1998 行用公里),
/// 那是 #293 加新行时没删旧行留下的。重复不会报错,只会让骑手
/// 在雨里多读两行字才找得到他真正要的那个数。
void main() {
  setUpRiderTest();

  Map<String, dynamic> poolOrder() => {
        'order_no': 'A1234567890abcdef',
        'status': 'ready',
        'merchant_id': 1,
        'merchant_name': '张记面馆',
        'merchant_address': '春熙路 8 号',
        'merchant_lat': 30.6598,
        'merchant_lng': 104.0810,
        'items': [
          {'name': '红烧牛肉面', 'quantity': 1, 'price_cents': 2000},
        ],
        'food_cents': 2000,
        'delivery_fee_cents': 500,
        'tip_cents': 100,
        'total_cents': 2600,
        'address': '天府三街 100 号 2 单元 501',
        'lat': 30.6800,
        'lng': 104.0823,
        'created_at': '2026-08-25T12:00:00+08:00',
        'distance_m': 1700,
        'trip_m': 2300,
        'distance_source': 'route',
        'est_minutes': 18.0,
        'fee_parts': {'base': 300, 'night': 200},
        'fee_part_labels': {'base': '基础配送费', 'night': '夜间配送'},
      };

  ApiClient poolApi(List<Map<String, dynamic>> pool) => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final p = req.url.path;
          Object? payload;
          if (p == '/riders/available-orders') {
            payload = {
              'items': pool,
              'filtered_by_prefs': 0,
              'has_location': true,
              'stale_prefs': [],
            };
          } else if (p == '/riders/profile') {
            // 未认证会弹窗挡住上线 —— 抢单池就永远是空的
            payload = {'status': 'approved', 'name': '测试骑手',
                       'rating_avg': 5.0, 'rating_count': 0};
          } else if (p.endsWith('s') || p.contains('orders')) {
            payload = [];
          } else {
            payload = {};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<void> pump(WidgetTester t,
      {Size screen = const Size(390, 844),
      double textScale = 1.0,
      Map<String, dynamic>? order}) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = screen * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      builder: (c, child) => MediaQuery(
        data: MediaQuery.of(c)
            .copyWith(textScaler: TextScaler.linear(textScale)),
        child: child!,
      ),
      home: RiderHomePage(api: poolApi([order ?? poolOrder()])),
    ));
    await t.pumpAndSettle();
    // _online 只由标题栏的状态 pill 设置,不从接口读 —— 不点它,
    // 抢单池永远是空的,而所有断言都会报"找不到文字",看不出真正的原因
    final pill = find.byType(SzStatePill);
    if (pill.evaluate().isNotEmpty) {
      await t.tap(pill.first);
      await t.pumpAndSettle();
    }
    // 上线之后靠 5 秒轮询拉抢单池,pumpAndSettle 不推进定时器 ——
    // 不走这一步池子永远是空的
    await t.pump(const Duration(seconds: 6));
    await t.pumpAndSettle();
  }

  /// 卡上所有可见文字,拼成一段。
  String cardText(WidgetTester t) => find
      .byType(Text)
      .evaluate()
      .map((e) => (e.widget as Text).data ?? '')
      .where((s) => s.isNotEmpty)
      .join(' | ');

  group('别再长回去', () {
    testWidgets('一张卡不超过 200px', (t) async {
      await pump(t);
      final h = t.getSize(find.byType(HallOrderCard).first).height;
      // 设计稿 5a 的卡:配送费大字 + 取送两点 + 一行备注 + 抢单,实测 160 上下。
      // 原来的卡 335px,因为每条决策信息各占一整行(还带 emoji)。
      //
      // 这一端**不追求一屏多塞几张** —— 触控区是硬底线。这条守的是
      // 另一件事:别再往上堆行。条件行(难度提示、酒类…)只在真有这事时出现。
      expect(h, lessThanOrEqualTo(200),
          reason: '卡高 ${h.toStringAsFixed(0)}px —— 又加了什么?先想想能删哪行');
      expect(h, greaterThan(0), reason: '没量到卡,测试脚手架坏了');
    });
  });

  group('不许溢出', () {
    testWidgets('390 屏上卡片横向不出界', (t) async {
      await pump(t);
      expect(t.takeException(), isNull,
          reason: '抢单卡横向溢出 —— 真机上是黄黑条 + 文字被裁。'
              '钱那一行左右两个 Column 都要能收缩,不能各自按内容撑开');
    });
  });

  group('骑手真实场景', () {
    testWidgets('长辈版 1.3 倍字也不出界', (t) async {
      // 骑手不都是年轻人。字放大之后左右两栏更挤,正是溢出最容易复现的时候
      await pump(t, textScale: 1.3);
      expect(t.takeException(), isNull);
    });

    testWidgets('320 窄屏也不出界', (t) async {
      await pump(t, screen: const Size(320, 640));
      expect(t.takeException(), isNull);
    });

    testWidgets('难度提示很长时也不出界', (t) async {
      // #301 的难度提示是骑手自己写的,可以很长
      final o = poolOrder()
        ..['hardship_note'] = '无电梯爬楼6楼；步行进小区约300米；车辆禁入；门禁难进';
      await pump(t, order: o);
      expect(t.takeException(), isNull);
    });
  });

  group('同一件事只说一遍', () {
    testWidgets('两段距离各出现一次:取餐点那行的「距你」、送达点那行的「送程」',
        (t) async {
      await pump(t);
      final s = cardText(t);
      expect(s.contains('跑程:到店'), isFalse,
          reason: '旧的「跑程:到店 X 米 + 送 Y 米」回来了');
      // 1700m / 2300m 各只出现一次,挂在各自那一行的末尾
      expect(find.text('1.7km'), findsOneWidget);
      expect(find.text('2.3km'), findsOneWidget);
    });

    testWidgets('钱只写一次,写的是骑手实得', (t) async {
      await pump(t);
      // 配送费 5 + 小费 1 = 6,不是订单总额 26
      expect(find.text('¥6.00'), findsOneWidget);
      expect(find.text('¥26.00'), findsNothing);
    });
  });
}
