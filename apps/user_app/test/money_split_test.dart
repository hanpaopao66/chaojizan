import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/money_flow_page.dart';

/// 一单的钱怎么分(orderSplit)—— 订单卡、详情分账卡、「钱去哪了」页共用。
///
/// ## 这个测试防的是什么
///
/// 三处原来对所有单都套外卖那一个公式。跑腿单套上去,「商家实收」是个负数,
/// 「配送费 100% 归骑手」也是错的(平台收了跑腿费的 2%);商家自送单的配送费
/// 被写成了「骑手所得」,而那单根本没有骑手。**页面照常画、数字照常出,
/// 不报任何错** —— 只有逐类对着服务端的结算口径(services/settlement.py)才看得出来。
///
/// 所以每一类单都断言两件事:该有的行有、不该有的行没有;
/// 各份加起来对得上用户实付(+ 平台补贴 + 帮买补收)。
void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
        appName: 'user_app', packageName: 'com.chaojizan.user',
        version: '0.1.0', buildNumber: '1', buildSignature: '');
  });

  Order order({
    String kind = 'food',
    int food = 2000,
    int packing = 0,
    int discount = 0,
    int subsidy = 0,
    int delivery = 400,
    int tip = 0,
    required int commission,
    required int total,
    bool selfDelivery = false,
    int budget = 0,
    int? actual,
    int refund = 0,
  }) =>
      Order.fromJson({
        'order_no': 'T1',
        'merchant_id': 1,
        'merchant_name': kind == 'food' ? '张记面馆' : '帮买',
        'status': 'completed',
        'items': const [],
        'food_cents': food,
        'packing_fee_cents': packing,
        'discount_cents': discount,
        'subsidy_cents': subsidy,
        'delivery_fee_cents': delivery,
        'tip_cents': tip,
        'commission_cents': commission,
        'total_cents': total,
        'refund_cents': refund,
        'self_delivery': selfDelivery,
        'order_kind': kind,
        'goods_budget_cents': budget,
        if (actual != null) 'goods_actual_cents': actual,
        'address': '春熙路 1 号',
        'lat': 30.66,
        'lng': 104.08,
        'created_at': '2026-09-01T10:00:00Z',
      });

  Map<String, int> byName(OrderSplit s) =>
      {for (final p in s.parts) p.name: p.cents};

  group('分法跟着单子的类型走', () {
    test('外卖:商家 / 骑手 / 平台,加起来 = 实付 + 平台补贴', () {
      // 菜 20 + 打包 1 − 满减 2 − 首单立减 3 + 配送 4 + 小费 1 = 实付 21
      final o = order(food: 2000, packing: 100, discount: 200, subsidy: 300,
          delivery: 400, tip: 100, commission: 95, total: 2100);
      final s = orderSplit(o);
      expect(byName(s), {'商家实收': 1805, '骑手所得': 500, '平台留存': 95});
      expect(s.sumCents, o.totalCents + o.subsidyCents,
          reason: '首单立减是平台出的,用户没付、商家照收');
    });

    test('商家自送:没有骑手那一行,配送费并进商家', () {
      final o = order(food: 3000, delivery: 300, commission: 150,
          total: 3300, selfDelivery: true);
      final s = orderSplit(o);
      expect(byName(s), {'商家实收': 3150, '平台留存': 150},
          reason: '这一单没有骑手;原来把 3 块配送费写成了「骑手所得」');
      expect(s.sumCents, o.totalCents);
    });

    test('帮送:没有商家,平台收的是跑腿费的 2%', () {
      final o = order(kind: 'errand_send', food: 0, delivery: 600,
          commission: 12, total: 600);
      final s = orderSplit(o);
      expect(byName(s), {'骑手所得': 588, '平台服务费': 12},
          reason: '套外卖公式的话「商家实收」是 −0.12');
      expect(s.sumCents, o.totalCents);
      final rider = s.parts.firstWhere((p) => p.name == '骑手所得');
      expect(rider.note.contains('100%'), isFalse,
          reason: '跑腿费里平台收了 2%,「100% 归骑手」是假话');
    });

    test('帮买:商品款单列,预付多出的退回', () {
      // 预付商品款 50 存在 food_cents 里;小票实付 46,退回 4
      final o = order(kind: 'errand_buy', food: 5000, delivery: 600,
          commission: 12, total: 5600, budget: 5000, actual: 4600);
      final s = orderSplit(o);
      expect(byName(s),
          {'骑手所得': 588, '平台服务费': 12, '商品款': 4600, '退回给你': 400});
      expect(s.sumCents, o.totalCents);
    });

    test('帮买:小票超出预估,补收的那部分对账时加回来', () {
      final o = order(kind: 'errand_buy', food: 5000, delivery: 600,
          commission: 12, total: 5600, budget: 5000, actual: 5500);
      final s = orderSplit(o);
      expect(byName(s)['商品款'], 5500);
      expect(byName(s).containsKey('退回给你'), isFalse);
      expect(s.extraCents, 500);
      expect(s.sumCents, o.totalCents + s.extraCents);
    });

    test('帮买:小票还没传,商品款先按预付算,不出「退回」', () {
      final o = order(kind: 'errand_buy', food: 5000, delivery: 600,
          commission: 12, total: 5600, budget: 5000);
      final s = orderSplit(o);
      expect(byName(s)['商品款'], 5000);
      expect(byName(s).containsKey('退回给你'), isFalse);
      expect(s.sumCents, o.totalCents);
    });
  });

  group('「钱去哪了」页', () {
    Future<void> pumpPage(WidgetTester t, Order o) async {
      t.view
        ..devicePixelRatio = 3.0
        ..physicalSize = const Size(390, 1600) * 3.0;
      addTearDown(t.view.reset);
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: MoneyFlowPage(
            api: ApiClient(baseUrl: 'http://test.local'), order: o),
      ));
      await t.pumpAndSettle();
    }

    testWidgets('跑腿单:没有「商家实收」,也不再写「不抽配送费」', (t) async {
      await pumpPage(t, order(kind: 'errand_send', food: 0, delivery: 600,
          commission: 12, total: 600));
      expect(find.text('商家实收'), findsNothing);
      expect(find.text('平台服务费'), findsOneWidget);
      expect(find.textContaining('不抽配送费'), findsNothing,
          reason: '同一页上平台正收着跑腿费的 2%');
      expect(find.textContaining('跑腿只收跑腿费的 2%'), findsOneWidget);
    });

    testWidgets('商家自送单:没有「骑手所得」', (t) async {
      await pumpPage(t, order(food: 3000, delivery: 300, commission: 150,
          total: 3300, selfDelivery: true));
      expect(find.text('骑手所得'), findsNothing);
      expect(find.text('商家实收'), findsOneWidget);
    });

    testWidgets('退过款的单:说清上面是退款前的分法', (t) async {
      await pumpPage(t, order(food: 2000, delivery: 400, commission: 100,
          total: 2400, refund: 800));
      expect(find.textContaining('这一单退过 ¥8.00'), findsOneWidget);
    });
  });
}
