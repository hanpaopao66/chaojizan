import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/dish_detail_page.dart';

/// 菜品详情页(设计稿 D)的选规格规则。
///
/// 规则和服务端 orders.resolve_options 同一口径:必选组至少一项、单选组最多一项、
/// 选项按规格组的顺序带回去。原来的规格弹层对「必选的多选组」不设防 ——
/// 把默认选上的那一项点掉,照样能加进购物车,一直走到结算页才被服务端 422 顶回来。
void main() {
  final api = ApiClient(baseUrl: 'http://test.local');
  final shop = Merchant.fromJson(const {
    'id': 1,
    'name': '张记面馆',
    'lat': 30.0,
    'lng': 104.0,
    'is_open': true,
    'commission_rate': '0.045',
    'packing_fee_cents': 100,
  });

  Dish dish({
    int stock = 12,
    bool soldOutToday = false,
    int? dailyStock = 20,
    bool toppingRequired = false,
  }) =>
      Dish.fromJson({
        'id': 3,
        'merchant_id': 1,
        'name': '油泼扯面',
        'category': '招牌',
        'price_cents': 1400,
        'stock': stock,
        'daily_stock': dailyStock,
        'sold_out_today': soldOutToday,
        'packing_fee_cents': 50,
        'monthly_sales': 96,
        'options': [
          {
            'name': '份量',
            'required': true,
            'multi': false,
            'choices': [
              {'name': '小份', 'delta_cents': 0},
              {'name': '大份', 'delta_cents': 300},
            ],
          },
          {
            'name': '加料',
            'required': toppingRequired,
            'multi': true,
            'choices': [
              {'name': '加卤蛋', 'delta_cents': 250},
              {'name': '加牛肉', 'delta_cents': 600},
            ],
          },
          {
            'name': '辣度',
            'required': true,
            'multi': false,
            'choices': [
              {'name': '不辣', 'delta_cents': 0},
              {'name': '微辣', 'delta_cents': 0},
            ],
          },
        ],
      });

  /// 从一个空页面推进详情页,返回「pop 回来的结果」的读取器
  Future<DishPick? Function()> open(WidgetTester t, Dish d,
      {int inCart = 0}) async {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    DishPick? result;
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: TextButton(
              onPressed: () async {
                result = await Navigator.of(context).push<DishPick>(
                    MaterialPageRoute(
                        builder: (_) => DishDetailPage(
                            api: api, shop: shop, dish: d, inCart: inCart)));
              },
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ));
    await t.tap(find.text('open'));
    await t.pumpAndSettle();
    return () => result;
  }

  FilledButton addButton(WidgetTester t) =>
      t.widget<FilledButton>(find.byType(FilledButton));

  testWidgets('必选单选组默认选第一项,而且点不空', (t) async {
    await open(t, dish());
    expect(find.text('加入购物车'), findsOneWidget);
    expect(addButton(t).onPressed, isNotNull);
    // 已选的「小份」再点一下:必选的单选组不许点空
    await t.tap(find.text('小份'));
    await t.pump();
    expect(find.text('加入购物车'), findsOneWidget);
    // 明细里写的是选中的规格,按组的顺序
    expect(find.text('小份 + 不辣'), findsOneWidget);
  });

  testWidgets('必选的多选组点空了:按钮变「请选择」且点不了,选回来才放行',
      (t) async {
    await open(t, dish(toppingRequired: true));
    // 必选组默认选了第一项「加卤蛋」,把它点掉
    await t.tap(find.text('加卤蛋 +¥2.50'));
    await t.pump();
    expect(find.text('请选择加料'), findsOneWidget);
    expect(addButton(t).onPressed, isNull,
        reason: '必选组空着就放进购物车,要到结算页才被服务端 422 拒掉');

    await t.tap(find.text('加牛肉 +¥6.00'));
    await t.pump();
    expect(find.text('加入购物车'), findsOneWidget);
    expect(addButton(t).onPressed, isNotNull);
  });

  testWidgets('选好的规格按组的顺序、连同份数带回店铺页', (t) async {
    final result = await open(t, dish());
    await t.tap(find.text('微辣'));
    await t.tap(find.text('加牛肉 +¥6.00'));
    await t.tap(find.text('大份 +¥3.00'));
    await t.pump();
    // 底栏合计 = (14 + 3 + 6) × 1
    expect(find.text('¥23.00'), findsWidgets);
    await t.tap(find.byIcon(Icons.add).last);
    await t.pump();
    expect(find.text('¥46.00'), findsWidgets);

    await t.tap(find.text('加入购物车'));
    await t.pumpAndSettle();
    final pick = result();
    expect(pick, isNotNull);
    expect(pick!.choices, ['大份', '加牛肉', '微辣'],
        reason: '服务端 resolve_options 按规格组的顺序认选项');
    expect(pick.quantity, 2);
  });

  testWidgets('打包费分两笔写清:每份的和每单的,抽成比例照店铺的算', (t) async {
    await open(t, dish());
    expect(find.text('打包费 · 每份 ¥0.50'), findsOneWidget);
    expect(find.textContaining('店铺另收打包费 ¥1.00 / 单'), findsOneWidget);
    // 4.5% 不能被取整成「4%」或「5%」
    expect(find.textContaining('打包费在 4.5% 抽成基数里'), findsOneWidget);
  });

  testWidgets('加到库存上限就不再给加', (t) async {
    await open(t, dish(stock: 3), inCart: 2);
    await t.tap(find.byIcon(Icons.add).last);
    await t.pump();
    // 还能加 1 份:点了 + 份数也停在 1
    expect(find.text('¥14.00'), findsWidgets);
    expect(find.text('¥28.00'), findsNothing);
  });

  testWidgets('库存全在购物车里了:按钮说清楚,点不了', (t) async {
    await open(t, dish(stock: 2), inCart: 2);
    expect(find.text('库存都在购物车里了'), findsOneWidget);
    expect(addButton(t).onPressed, isNull);
  });

  testWidgets('今日售罄:底栏照实写明天自动恢复,没有加购按钮', (t) async {
    await open(t, dish(stock: 0, soldOutToday: true));
    expect(find.text('今日售罄 · 明天自动恢复'), findsOneWidget);
    expect(find.byType(FilledButton), findsNothing);
  });

  testWidgets('没设每日回满的菜卖完了:不许说「今日还剩」、也不编恢复时间',
      (t) async {
    await open(t, dish(stock: 0, dailyStock: null));
    expect(find.text('已售罄 · 等商家补货'), findsOneWidget);
    expect(find.textContaining('今日还剩'), findsNothing);
  });
}
