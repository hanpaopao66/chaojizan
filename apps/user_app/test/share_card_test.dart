import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/share_card.dart';

/// 分享卡(设计稿 E/F):晒单卡的金额打码开关,和卡上写的账对不对得上。
void main() {
  Order order({bool self = false, int tip = 0}) => Order.fromJson({
        'order_no': 'o1',
        'merchant_id': 7,
        'merchant_name': '张记面馆',
        'status': 'completed',
        'items': [
          {'dish_id': 1, 'name': '牛肉面', 'price_cents': 1600, 'quantity': 1},
          {'dish_id': 2, 'name': '卤蛋', 'price_cents': 250, 'quantity': 2},
        ],
        'food_cents': 2100,
        'packing_fee_cents': 0,
        'discount_cents': 0,
        'delivery_fee_cents': 300,
        'tip_cents': tip,
        'total_cents': 2400 + tip,
        'commission_cents': 105,
        'self_delivery': self,
        'address': '高新路 1 号',
        'lat': 30.0,
        'lng': 104.0,
        'created_at': '2026-09-10T04:00:00Z',
      });

  Future<void> open(WidgetTester t, Order o) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: TextButton(
              onPressed: () => showOrderShareCard(context, o),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ));
    await t.tap(find.text('open'));
    await t.pumpAndSettle();
  }

  bool shows(String s) =>
      find.textContaining(s, findRichText: true).evaluate().isNotEmpty;

  testWidgets('默认打码;拨开关当场换成真实金额,再拨回去又打上', (t) async {
    await open(t, order());
    expect(find.text('金额打码'), findsOneWidget);
    // 开关的说明里也有「¥**」,所以带上前面的名字认卡上的那一处
    expect(shows('商家 ¥**'), isTrue, reason: '默认打码(原来晒单设置的默认值就是打码)');
    expect(shows('¥19.95'), isFalse);

    await t.tap(find.byType(SzSwitch));
    await t.pumpAndSettle();
    // 商家 = 21 − 1.05;骑手 = 配送费 3;平台 = 1.05
    expect(shows('商家 ¥19.95'), isTrue);
    expect(shows('骑手 ¥3.00'), isTrue);
    expect(shows('平台 ¥1.05'), isTrue);
    expect(shows('商家 ¥**'), isFalse);

    await t.tap(find.byType(SzSwitch));
    await t.pumpAndSettle();
    expect(shows('¥19.95'), isFalse);
    expect(shows('商家 ¥**'), isTrue);
  });

  testWidgets('分账条真画出来了:三段、8 高、宽按金额', (t) async {
    await open(t, order());
    final segs = find.descendant(
        of: find.byType(RepaintBoundary).last,
        matching: find.byType(ColoredBox));
    final sizes = [
      for (final e in segs.evaluate()) t.getSize(find.byWidget(e.widget))
    ].where((s) => s.height == 8).toList();
    expect(sizes.length, 3, reason: '商家 / 骑手 / 平台 三段,0 元的段不画');
    // 商家 19.95 : 骑手 3 : 平台 1.05 —— 宽度比例跟金额走
    expect(sizes[0].width / sizes[2].width, closeTo(1995 / 105, 0.5));
  });

  testWidgets('商家自己送的单:没有骑手那一份,配送费并进商家', (t) async {
    await open(t, order(self: true));
    await t.tap(find.byType(SzSwitch));
    await t.pumpAndSettle();
    expect(shows('骑手'), isFalse,
        reason: '自配送单没有骑手,原来这里照外卖公式写「骑手 ¥3(配送费+小费全额)」');
    expect(shows('商家 ¥22.95(含配送费,商家自己送)'), isTrue);
    expect(shows('配送费全归骑手'), isFalse);
  });

  testWidgets('有小费才写「配送费+小费全额」;抽成按这一单自己的档位写', (t) async {
    await open(t, order());
    expect(shows('(配送费全额)'), isTrue);
    expect(shows('小费'), isFalse);
    // 105 / 2100 = 5%
    expect(shows('商家只抽 5%'), isTrue);
  });

  testWidgets('存图、分享两个按钮都在,底下说清图里没有个人信息', (t) async {
    await open(t, order());
    expect(find.text('存图'), findsOneWidget);
    expect(find.text('分享'), findsOneWidget);
    expect(find.text('图里不带你的手机号、地址和订单号'), findsOneWidget);
  });

  testWidgets('店铺卡:抽成写这家店的档位,有规格的菜价后面带「起」', (t) async {
    final m = Merchant.fromJson(const {
      'id': 7,
      'name': '张记面馆',
      'lat': 30.0,
      'lng': 104.0,
      'is_open': true,
      'commission_rate': '0.045',
      'rating_avg': 4.8,
      'rating_count': 268,
      'monthly_sales': 268,
    });
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(
        body: Center(
          child: shopShareCard(m, dishes: const [
            (name: '油泼扯面', priceCents: 1400, from: true),
            (name: '卤蛋', priceCents: 250, from: false),
          ]),
        ),
      ),
    ));
    expect(shows('商家只抽 4.5%'), isTrue);
    expect(find.text('¥14.00 起'), findsOneWidget);
    expect(find.text('¥2.50'), findsOneWidget);
    expect(find.text('月售 268'), findsOneWidget);
  });
}
