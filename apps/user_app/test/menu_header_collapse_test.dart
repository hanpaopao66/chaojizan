import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/main.dart';

/// 店铺页往上滑:店头滚走、页签条停在顶上;滑回顶店头回来(稿子 A/B/C)。
///
/// 原来店头钉着不动:一家有公告、排队卡、店铺券的店,390×844 上页签条在 y≈600,
/// 菜单只剩购物车条上面一百来像素。这些都不报错,只是屏幕上菜单没地方放 —— 拿坐标锁住。
void main() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    // 同 menu_page_test:测试环境里 PackageInfo 永远不返回,不 mock 会挂着定时器
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.chaojizan.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  const announcement = '今日加量不加价,牛肉面多加二两面';

  final shop = {
    'id': 7,
    'name': '张记面馆',
    'address': '高新路 128 号',
    'lat': 30.6,
    'lng': 104.0,
    'is_open': true,
    'commission_rate': '0.045',
    'rating_avg': 4.8,
    'rating_count': 45,
    'monthly_sales': 268,
    'min_order_cents': 2000,
    'self_delivery': false,
    'promo_rules': const [],
    'kitchen_cam': false,
    'kitchen_cam_label': '无明厨亮灶',
    'dine_in_status': 'yes',
    'dine_in_label': '有堂食',
    'food_seal': true,
    'announcement': announcement,
  };

  // 18 个分类:头尾两类各 12 道(一屏放不下),中间各 2 道。
  // 分类多到分类栏自己要滚,才看得出它有没有被菜品列表带着跑
  const middle = [
    '面食', '米饭', '盖饭', '凉菜', '热菜', '小吃', '汤羹', '饮品', //
    '甜品', '套餐', '早点', '夜宵', '卤味', '烧烤', '素菜', '主食',
  ];
  var nextId = 1;
  Map<String, dynamic> dish(String name, String category) => {
        'id': nextId++,
        'merchant_id': 7,
        'name': name,
        'category': category,
        'price_cents': 1600,
        'stock': 50,
        'sold_out_today': false,
        'monthly_sales': 0,
        'options': const [],
      };
  final dishes = [
    for (var i = 1; i <= 12; i++) dish('牛肉面 $i', '招牌'),
    for (final c in middle) ...[dish('$c 甲', c), dish('$c 乙', c)],
    for (var i = 1; i <= 12; i++) dish('加料 $i', '加料'),
  ];

  final queue = {
    'enabled': true,
    'table_types': [
      {
        'name': '小桌',
        'seats_min': 1,
        'seats_max': 2,
        'waiting': 3,
        'wait_upper_minutes': 20,
        'cap': 30,
      },
      {
        'name': '大桌',
        'seats_min': 3,
        'seats_max': 6,
        'waiting': 0,
        'wait_upper_minutes': 0,
        'cap': 30,
      },
    ],
  };

  Map<String, dynamic> coupon(int id, int off, int threshold) => {
        'id': id,
        'off_cents': off,
        'threshold_cents': threshold,
        'can_claim': true,
      };
  final coupons = [
    coupon(1, 500, 0),
    coupon(2, 800, 4000),
    coupon(3, 1000, 3000),
  ];

  // 45 条评价,id 越大越新;按 20 一页是三页
  final reviews = [
    for (var id = 45; id >= 1; id--)
      {
        'id': id,
        'merchant_rating': 5,
        'comment': '第$id条',
        'image_urls': const [],
        'tags': const [],
        'reply': '',
        'append_content': '',
        'customer_name': '王**',
        'created_at':
            DateTime.utc(2026, 9, 1).add(Duration(hours: id)).toIso8601String(),
      },
  ];

  late List<Uri> reviewPages;

  Future<void> pump(WidgetTester t, {Size size = const Size(390, 844)}) async {
    SharedPreferences.setMockInitialValues({});
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = size * 3.0;
    addTearDown(t.view.reset);
    reviewPages = [];
    final api = ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final p = req.url.path;
        Object? body;
        if (p == '/merchants/7') {
          body = shop;
        } else if (p == '/merchants/7/dishes') {
          body = dishes;
        } else if (p == '/cart/7') {
          body = {'items': []};
        } else if (p == '/merchants/7/coupons') {
          body = coupons;
        } else if (p == '/queue/merchants/7') {
          body = queue;
        } else if (p == '/merchants/7/reviews/overview') {
          body = {
            'count': reviews.length,
            'avg': 5.0,
            'stars': {'1': 0, '2': 0, '3': 0, '4': 0, '5': reviews.length},
            'photo': 0,
            'good': reviews.length,
            'bad': 0,
            'append': 0,
          };
        } else if (p == '/merchants/7/reviews') {
          reviewPages.add(req.url);
          final before = int.tryParse(req.url.queryParameters['before'] ?? '');
          final limit =
              int.tryParse(req.url.queryParameters['limit'] ?? '') ?? 50;
          body = reviews
              .where((r) => before == null || (r['id'] as int) < before)
              .take(limit)
              .toList();
        } else if (p.endsWith('frequent-dishes')) {
          body = [];
        } else {
          body = {};
        }
        return http.Response(jsonEncode(body), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: MenuPage(api: api, merchant: Merchant.fromJson(shop)),
    ));
    await t.pumpAndSettle();
    addTearDown(Analytics.resetSession);
  }

  final tabBar = find.byType(TabBar);
  double tabTop(WidgetTester t) => t.getTopLeft(tabBar).dy;
  double tabBottom(WidgetTester t) => t.getBottomLeft(tabBar).dy;
  double appBarBottom(WidgetTester t) =>
      t.getBottomLeft(find.byType(AppBar)).dy;

  /// 在页签条正下方、分类栏右边(菜品列表 / 评价列表 / 商家页)按住往上(dy<0)或往下拖
  Future<void> dragContent(WidgetTester t, double dy) async {
    await t.dragFrom(
        t.getBottomLeft(tabBar) + const Offset(250, 24), Offset(0, dy));
    await t.pumpAndSettle();
  }

  testWidgets('点餐页签往上滑:店头滚走、页签条停在标题栏底下;滑回顶店头回来', (t) async {
    await pump(t);
    final start = tabTop(t);
    // 前提:这家店的店头确实很高,页签条被推到了屏幕下半截
    expect(start, greaterThan(500), reason: '店头不够高,测不出问题:页签条在 $start');
    expect(find.text(announcement).hitTestable(), findsOneWidget);

    // 拖 200 里头 20 是起拖的判定距离(touch slop),店头跟着上去 180
    await dragContent(t, -200);
    expect(tabTop(t), closeTo(start - 180, 1), reason: '往上拖,店头没跟着上去');

    // 再拖一大段:店头整个滚走,页签条停在标题栏底下,剩下的位移给菜单
    await dragContent(t, -1500);
    expect(tabTop(t), closeTo(appBarBottom(t), .5), reason: '页签条没停在顶上');
    expect(find.text('点餐').hitTestable(), findsOneWidget, reason: '页签条得还在屏幕上');
    expect(find.text(announcement).hitTestable(), findsNothing);
    expect(find.text('牛肉面 1').hitTestable(), findsNothing,
        reason: '店头滚完剩下的位移要给菜单:第一道菜该滚上去了');
    expect(find.text('牛肉面 12').hitTestable(), findsOneWidget);

    // 往下拖回去:菜单先回到顶,店头再回来
    await dragContent(t, 3000);
    expect(tabTop(t), closeTo(start, .5));
    expect(find.text(announcement).hitTestable(), findsOneWidget);
    expect(find.text('牛肉面 1').hitTestable(), findsOneWidget);
  });

  testWidgets('店头收起后点分类栏靠后的分类:列表跳到那一类的第一道,店头照样收着', (t) async {
    await pump(t);
    await dragContent(t, -1500);
    final pinned = tabTop(t);
    expect(pinned, closeTo(appBarBottom(t), .5));

    // 滑菜单时分类栏不能跟着跑:第一个分类还紧挨着页签条。
    // 分类栏也挂上内层控制器的话,外层协调器把同一段位移也加给它
    expect(find.text('招牌').hitTestable(), findsOneWidget,
        reason: '分类栏被菜品列表带着滚了');
    expect(t.getTopLeft(find.text('招牌')).dy - tabBottom(t),
        inInclusiveRange(0, 20),
        reason: '分类栏被菜品列表带着滚了');

    // 分类栏自己往上滑,露出最后一个分类;页签条和菜单都不动
    final dishBefore = t.getTopLeft(find.text('牛肉面 12')).dy;
    await t.dragFrom(Offset(40, tabBottom(t) + 200), const Offset(0, -600));
    await t.pumpAndSettle();
    expect(tabTop(t), pinned);
    expect(t.getTopLeft(find.text('牛肉面 12')).dy, dishBefore);

    await t.tap(find.text('加料'));
    await t.pumpAndSettle();
    expect(find.text('牛肉面 12'), findsNothing);
    // 新分类从第一道看起。「加料」也有 12 道、一屏放不下 ——
    // 列表要是还停在上一类滚到的位置,这一道就在屏幕上面看不见
    expect(find.text('加料 1').hitTestable(), findsOneWidget);
    expect(t.getTopLeft(find.text('加料 1')).dy - tabBottom(t), lessThan(40));
    expect(tabTop(t), pinned, reason: '换分类不该把店头拉回来');

    // 在新分类里往下拉到顶,店头回来
    await dragContent(t, 3000);
    expect(find.text(announcement).hitTestable(), findsOneWidget);
  });

  testWidgets('评价页签往上滑店头也收起;滑到底照样接着翻页', (t) async {
    await pump(t);
    await t.tap(find.text('评价'));
    await t.pumpAndSettle();
    final start = tabTop(t);
    expect(reviewPages.length, 1, reason: '没滑到底不去要下一页');

    await dragContent(t, -300);
    expect(tabTop(t), closeTo(start - 280, 1), reason: '往上拖,店头没跟着上去');

    for (var i = 0; i < 20; i++) {
      await dragContent(t, -900);
    }
    expect(tabTop(t), closeTo(appBarBottom(t), .5));
    expect(reviewPages.length, 3, reason: '45 条按 20 一页是三页,第三页不满就不再要');
    expect(reviewPages[1].queryParameters['before'], '26');
    expect(reviewPages[2].queryParameters['before'], '6');
    expect(find.text('第1条').hitTestable(), findsOneWidget);
  });

  testWidgets('商家页签往上滑店头也收起', (t) async {
    await pump(t);
    await t.tap(find.text('商家'));
    await t.pumpAndSettle();
    final start = tabTop(t);
    await dragContent(t, -2000);
    expect(tabTop(t), lessThan(start - 300));
    expect(tabTop(t), closeTo(appBarBottom(t), .5));
    expect(find.text('商家').hitTestable(), findsOneWidget);
  });

  testWidgets('宽屏(侧栏 + 限宽)一样:店头收起,页签条停在标题栏底下', (t) async {
    await pump(t, size: const Size(1280, 800));
    expect(t.getSize(tabBar).width, lessThanOrEqualTo(kContentMaxWidth),
        reason: '宽屏上页签条和内容一起限宽');
    final start = tabTop(t);
    await dragContent(t, -1500);
    expect(tabTop(t), lessThan(start - 300));
    expect(tabTop(t), closeTo(appBarBottom(t), .5));
    expect(find.text('点餐').hitTestable(), findsOneWidget);
    await dragContent(t, 3000);
    expect(tabTop(t), closeTo(start, .5));
  });
}
