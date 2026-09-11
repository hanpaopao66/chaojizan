import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:merchant_app/dish_manage_page.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'order_fake_api.dart' show setPhoneViewport;

/// 菜单页(设计稿 6e):左边竖排分类、右边菜品行、每行一个「在售 / 售罄」开关。
///
/// ## 「本月」在这个 App 里被用成了两个意思
///
/// 菜品页的销量来自 `/merchants/me/dishes`,服务端 `_DISH_SALES_SQL` 写的是
/// `o.created_at >= now() - interval '30 days'` —— **滚动 30 天**。
/// 而同一个 App 的账本页「本月已完成 N 单」用的是 `/me/commission-tier` 的
/// `this_month_completed`,那是 `now_bj.replace(day=1)` 起算的**自然月**。
///
/// 每月 1 号这两个窗差得最远:自然月只有 1 天,滚动窗有 30 天。
/// 商家拿这个数决定下架哪道菜,窗口说错了,决定就是错的。
///
/// ## 行上的开关管的是「今天」
///
/// 开 = 在售,关 = 今日售罄(估清,明早 04:00 自动恢复)。永久的上下架
/// 在编辑页和批量操作里 —— 两件事不再挤在同一个开关上。
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

  Map<String, dynamic> dishJson(int id,
          {required String name,
          String category = '招牌',
          int monthly = 120,
          int todaySold = 0,
          int stock = 42,
          int? dailyStock,
          bool soldOut = false,
          bool onSale = true}) =>
      {
        'id': id,
        'merchant_id': 1,
        'name': name,
        'category': category,
        'price_cents': 2800,
        'cost_cents': 900,
        'stock': stock,
        'daily_stock': dailyStock,
        'sold_out_today': soldOut,
        'is_on_sale': onSale,
        'image_url': 'https://x/y.jpg',
        'sort': id,
        'monthly_sales': monthly,
        'today_sold': todaySold,
      };

  /// 写操作记在这里:(方法, 路径, 请求体)
  late List<(String, String, Map<String, dynamic>)> writes;

  /// [sellOutStatus] 给估清接口指定一个状态码(409 = 服务端说已经是估清状态)
  ApiClient dishFakeApi(List<Map<String, dynamic>> dishes,
      {int sellOutStatus = 200}) {
    writes = [];
    return ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final path = req.url.path;
        if (req.method != 'GET') {
          final body = req.body.isEmpty
              ? <String, dynamic>{}
              : (jsonDecode(req.body) as Map).cast<String, dynamic>();
          writes.add((req.method, path, body));
          final m = RegExp(r'/merchants/me/dishes/(\d+)').firstMatch(path);
          if (m != null) {
            final id = int.parse(m.group(1)!);
            final d = dishes.firstWhere((d) => d['id'] == id);
            if (path.endsWith('/sell-out') && sellOutStatus != 200) {
              return http.Response(
                  jsonEncode({'detail': '已经是估清状态'}), sellOutStatus,
                  headers: {
                    'content-type': 'application/json; charset=utf-8'
                  });
            }
            final out = {
              ...d,
              ...body,
              if (path.endsWith('/sell-out')) 'sold_out_today': true,
              if (path.endsWith('/sell-out')) 'stock': 0,
              if (path.endsWith('/cancel')) 'sold_out_today': false,
              if (path.endsWith('/cancel')) 'stock': 30,
            };
            return http.Response(jsonEncode(out), 200,
                headers: {'content-type': 'application/json; charset=utf-8'});
          }
          return http.Response(jsonEncode(<String, dynamic>{}), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        final payload =
            path == '/merchants/me/dishes' ? dishes : <String, dynamic>{};
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
  }

  Future<void> pumpDishes(WidgetTester t, List<Map<String, dynamic>> dishes,
      {int sellOutStatus = 200}) async {
    setPhoneViewport(t, const Size(390, 1800));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light,
          density: SzDensity.operate, accentTone: 0),
      home: Scaffold(
        body: Align(
          alignment: Alignment.topLeft,
          child: SizedBox(
              width: 390,
              height: 1800,
              child: DishManagePage(
                  api: dishFakeApi(dishes, sellOutStatus: sellOutStatus))),
        ),
      ),
    ));
    await t.pump();
    await t.pump(const Duration(milliseconds: 400));
  }

  List<String> allTexts() => find
      .byType(Text)
      .evaluate()
      .map((e) => (e.widget as Text).data ?? '')
      .where((s) => s.isNotEmpty)
      .toList();

  /// 某道菜那一行上的开关
  Finder switchOf(String name) => find.byWidgetPredicate(
      (w) => w is SzSwitch && (w.semanticLabel ?? '').startsWith('$name '));

  /// #33 4.2 的指标:① 首屏能看到几道菜 ② 改一道菜要几步。
  ///
  /// 分类原来是一条横向 chip 条(宽屏才有左侧栏);设计稿 6e 改成**任何宽度都是
  /// 左边一列**。100 道菜的店找一道菜,仍然是「点一次 + 半屏」。
  group('左边的分类栏:点一次只看这一类', () {
    List<Map<String, dynamic>> mixed() => [
          dishJson(1, name: '红烧牛肉面', category: '主食'),
          dishJson(2, name: '酸辣粉', category: '主食'),
          dishJson(3, name: '可乐', category: '饮品'),
        ];

    testWidgets('默认全部,分类各自带数量', (t) async {
      await pumpDishes(t, mixed());
      expect(find.text('全部 · 3'), findsOneWidget);
      expect(find.text('主食 · 2'), findsOneWidget);
      expect(find.text('饮品 · 1'), findsOneWidget);
      expect(find.text('可乐'), findsOneWidget);
    });

    testWidgets('选中一类后,别的类不再出现', (t) async {
      await pumpDishes(t, mixed());
      await t.tap(find.text('主食 · 2'));
      await t.pump();
      expect(find.text('红烧牛肉面'), findsOneWidget);
      expect(find.text('可乐'), findsNothing,
          reason: '筛了主食还看得见饮品,那这个分类栏就是白放的');
      // 只剩一类时不再重复分类名 —— 左边分类栏上已经高亮着
      expect(find.text('主食'), findsNothing,
          reason: '分类头和高亮的那一格说的是同一件事,重复一遍纯占地方');
    });

    testWidgets('只有一个分类时,分类栏整个不出现', (t) async {
      await pumpDishes(t, [
        dishJson(1, name: '红烧牛肉面', category: '主食'),
        dishJson(2, name: '酸辣粉', category: '主食'),
      ]);
      expect(find.text('全部 · 2'), findsNothing,
          reason: '一个分类的店点它没有任何意义 —— 那时它是纯噪音');
    });

    testWidgets('窄屏上也是左边一列(88 宽),不是横条', (t) async {
      await pumpDishes(t, mixed());
      final rail = t.getRect(find.text('主食 · 2'));
      final dish = t.getRect(find.text('可乐'));
      expect(rail.right, lessThanOrEqualTo(88),
          reason: '分类在左边一列里,不在菜品上方的横条里');
      expect(dish.left, greaterThan(88));
    });
  });

  group('标题行:在售 / 售罄数 + 添加', () {
    testWidgets('数的是这一刻卖得了和卖不了的', (t) async {
      await pumpDishes(t, [
        dishJson(1, name: '牛肉面'),
        dishJson(2, name: '担担面'),
        dishJson(3, name: '肥肠面', soldOut: true, stock: 0),
        dishJson(4, name: '冰粉', onSale: false),
      ]);
      expect(find.text('2 个在售 · 1 售罄 · 1 下架'), findsOneWidget,
          reason: '下架的菜也在列表里,不说出来的话数对不上');
      expect(find.widgetWithText(FilledButton, '添加'), findsOneWidget);
    });

    testWidgets('批量操作从「⋯」进(长按留给置顶)', (t) async {
      await pumpDishes(t, [dishJson(1, name: '牛肉面')]);
      await t.tap(find.byIcon(Icons.more_horiz));
      await t.pumpAndSettle();
      await t.tap(find.text('批量操作'));
      await t.pumpAndSettle();
      expect(find.text('已选 0'), findsOneWidget);
      for (final label in ['改分类', '估清', '下架', '上架']) {
        expect(find.text(label), findsWidgets, reason: '批量里缺了「$label」');
      }
    });

    testWidgets('长按一道菜仍是置顶', (t) async {
      await pumpDishes(t, [
        dishJson(1, name: '牛肉面'),
        dishJson(2, name: '担担面'),
      ]);
      await t.longPress(find.text('担担面'));
      await t.pump();
      expect(writes.map((w) => w.$2), contains('/merchants/me/dishes/reorder'),
          reason: '长按是上一版就教给商家的置顶手势,改了会按错菜');
    });
  });

  group('行上的开关:开 = 在售,关 = 今日售罄', () {
    testWidgets('关:走估清接口,并说清明早 04:00 自动恢复', (t) async {
      await pumpDishes(t, [dishJson(1, name: '牛肉面')]);
      expect(t.widget<SzSwitch>(switchOf('牛肉面')).value, isTrue);
      await t.tap(switchOf('牛肉面'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(writes.map((w) => w.$2), contains('/merchants/me/dishes/1/sell-out'),
          reason: '这个开关管的是今天,关掉是估清,不是下架');
      expect(writes.where((w) => w.$3.containsKey('is_on_sale')), isEmpty,
          reason: '拨一下就把菜从菜单上拿掉,用户就看不到这道菜了');
      expect(find.textContaining('04:00'), findsWidgets);
    });

    testWidgets('估清的菜:开关是关的,行上写明早 04:00 自动恢复', (t) async {
      await pumpDishes(
          t, [dishJson(1, name: '肥肠面', soldOut: true, stock: 0)]);
      expect(t.widget<SzSwitch>(switchOf('肥肠面')).value, isFalse);
      expect(find.text('售罄 · 明早 04:00 自动恢复'), findsOneWidget);
      await t.tap(switchOf('肥肠面'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(writes.map((w) => w.$2),
          contains('/merchants/me/dishes/1/sell-out/cancel'));
    });

    testWidgets('服务端说「已经是估清状态」(409):照实说,不当成故障', (t) async {
      await pumpDishes(t, [dishJson(1, name: '牛肉面')], sellOutStatus: 409);
      await t.tap(switchOf('牛肉面'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(find.textContaining('已经是估清状态'), findsOneWidget);
      expect(find.textContaining('已刷新'), findsOneWidget);
    });

    testWidgets('卖到 0 的菜:拨开先问补多少份,不悄悄补成 100', (t) async {
      await pumpDishes(t, [dishJson(1, name: '卤蛋', stock: 0)]);
      expect(find.text('库存 0 · 补货后才能卖'), findsOneWidget);
      await t.tap(switchOf('卤蛋'));
      await t.pumpAndSettle();
      expect(find.text('「卤蛋」库存是 0'), findsOneWidget);
      await t.enterText(find.byType(TextField), '50');
      await t.tap(find.text('补货'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      final patch = writes.where((w) => w.$1 == 'PATCH').toList();
      expect(patch, hasLength(1));
      expect(patch.single.$3, {'stock': 50});
    });

    testWidgets('下架的菜:拨开就是重新上架', (t) async {
      await pumpDishes(t, [dishJson(1, name: '冰粉', onSale: false)]);
      expect(find.text('已下架 · 用户看不到'), findsOneWidget);
      await t.tap(switchOf('冰粉'));
      await t.pump();
      await t.pump(const Duration(milliseconds: 300));
      expect(writes.single.$3, {'is_on_sale': true});
    });
  });

  /// #33 4.2 第 3 点:缺图提示挪到缩略图角标。
  ///
  /// 它原先在行尾和估清按钮、上下架开关挤一列 ——
  /// 挤窄标题列、逼副标题折行,每行 64→78。12 道全缺图就是 +168px。
  testWidgets('缺图提示压在缩略图上,不占行高', (t) async {
    await pumpDishes(t, [
      {...dishJson(1, name: '红烧牛肉面'), 'image_url': ''},
    ]);
    expect(find.text('缺图'), findsOneWidget, reason: '缺图还是要提示,只是换了位置');
    // 角标在 48×48 的缩略图范围内,不是在行尾那一列
    final badge = t.getCenter(find.text('缺图'));
    final tile = t.getTopLeft(find.text('红烧牛肉面'));
    expect(badge.dx, lessThan(tile.dx),
        reason: '角标跑到标题右边去了 —— 那就还是在挤标题列');
  });

  testWidgets('时间窗只说「近 30 天」,不说「本月」;销量榜已移除', (t) async {
    await pumpDishes(t, [
      dishJson(1, name: '红烧牛肉面', monthly: 200),
      dishJson(2, name: '酸辣粉', monthly: 180),
      dishJson(3, name: '卤蛋', monthly: 160),
    ]);

    expect(allTexts().where((s) => s.contains('本月')), isEmpty,
        reason: '服务端算的是 interval 30 days(滚动窗),写「本月」的话——'
            '每月 1 号这两个窗能差 29 天');
    // #33 4.2:销量榜整块砍掉了。账本页的经营分析明说包含「菜品排行」,
    // 这一页只留「N 道零销量」,因为那是待办,排行榜不是。
    // 这条断言防的是有人看着空位又把榜加回来
    expect(find.textContaining('销量榜'), findsNothing,
        reason: '排行榜不该在干活页占地方 —— 首屏是留给菜的');
  });

  testWidgets('零销量提示也要说「近 30 天」', (t) async {
    await pumpDishes(t, [
      dishJson(1, name: '红烧牛肉面', monthly: 200),
      dishJson(2, name: '滞销菜甲', monthly: 0),
      dishJson(3, name: '滞销菜乙', monthly: 0),
    ]);

    final stale = allTexts().where((s) => s.contains('零销量')).toList();
    expect(stale, isNotEmpty, reason: '滞销提示不见了');
    expect(stale.single, contains('近 30 天'),
        reason: '「$stale」说的是本月,服务端算的是近 30 天');
    expect(stale.single, isNot(contains('本月')));
  });

  testWidgets('每行说的是今天卖了几份 —— 数来自服务端的 today_sold', (t) async {
    // 设计稿 6e 的行副标题是「今日已卖 N 份」(原来是「月售 N」)。
    // 这个数是服务端按今天的有效订单算的(含还在做的单),客户端不自己数 ——
    // 客户端手里只有最近 20 单,数出来的是「最近 20 单里有几份」
    await pumpDishes(t, [dishJson(1, name: '红烧牛肉面', todaySold: 31)]);
    expect(find.text('今日已卖 31 份'), findsOneWidget);
    expect(allTexts().where((s) => s.contains('月售')), isEmpty,
        reason: '行上的数换成了今天的,别两个口径并排放');
  });
}
