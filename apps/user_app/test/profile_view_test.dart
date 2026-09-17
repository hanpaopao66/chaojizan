import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/main.dart';

/// 「我的」页的入口密度与分块(#296)。
///
/// ## 这个测试防的是什么
///
/// 改版前这一页是一条从上到下的 ListView:12 个入口挤在一张卡里,
/// 高频的(订单、账目)和一年点一次的(注销、协议)靠**位置**区分优先级,
/// 而位置这件事用户扫不出来。真机 390×844 上首屏只看得到 8 个入口,
/// 那张 12 条的大卡首屏只露 1 条。
///
/// 密度这种事**没有报错** —— 功能全对、测试全绿,只是难用。
/// 所以拿数字锁住:首屏能看到几个入口,是这一页唯一的验收标准。
///
/// ## 「首屏可见入口」怎么数
///
/// 见 [visibleEntries]:数的是**真正能点的矩形**,不是某个具体组件类型。
/// 这样重排、换组件都不会让这个数字失真 —— 它问的是用户的问题
/// (「不滚动我能点到几样东西」),不是实现的问题。
/// 把渲染视口真的调成手机尺寸(与 packages/shared/test/text_fit.dart 同一套)。
/// 只给 MediaQuery 传 size 不改布局约束 —— 那会拿 800px 宽的屏去量 390 的密度。
void setPhoneViewport(WidgetTester tester, Size logical) {
  tester.view
    ..devicePixelRatio = 3.0
    ..physicalSize = logical * 3.0;
  addTearDown(tester.view.reset);
}

void main() {
  // 390×844 的机器上,ListView 拿到的可视高度:
  //   844 − 47(顶部安全区) − 56(AppBar) − 96(底部导航 62 + 底部安全区 34)
  // 底部导航高度见 brand.dart 的 navigationBarTheme(62),
  // NavigationBar 自带 SafeArea(见 Flutter navigation_bar.dart)
  const firstScreen = 645.0;

  /// 首屏内**完整可见**的可点入口个数。
  ///
  /// 判据是「有 onTap 的 InkWell 矩形」,并且:
  /// - 底边超出首屏的不算(露一半的入口用户点不安心,也扫不到);
  /// - 嵌套的只算最里面那个(头像卡里套着换头像的圆形按钮,算一个)。
  int visibleEntries(WidgetTester t) {
    final rects = <Rect>[];
    for (final element in find.byType(InkWell).evaluate()) {
      final w = element.widget as InkWell;
      if (w.onTap == null) continue;
      final box = element.renderObject as RenderBox?;
      if (box == null || !box.hasSize) continue;
      final rect = box.localToGlobal(Offset.zero) & box.size;
      if (rect.isEmpty || rect.bottom > firstScreen) continue;
      rects.add(rect);
    }
    // 小的优先:一个矩形如果把已经数过的入口整个包住,它是外壳不是入口
    rects.sort((a, b) => (a.width * a.height).compareTo(b.width * b.height));
    final kept = <Rect>[];
    for (final r in rects) {
      if (kept.any((k) => r.contains(k.topLeft) && r.contains(k.bottomRight))) {
        continue;
      }
      kept.add(r);
    }
    return kept.length;
  }

  Map<String, dynamic> order({
    String no = 'SZ1',
    String status = 'completed',
    int total = 3200,
    bool hasReview = false,
    int refund = 0,
  }) =>
      {
        'order_no': no,
        'merchant_id': 1,
        'merchant_name': '楼下面馆',
        'status': status,
        'items': [
          {'dish_id': 1, 'name': '牛肉面', 'price_cents': 2000, 'quantity': 1}
        ],
        'food_cents': 2000,
        'delivery_fee_cents': 300,
        'total_cents': total,
        'commission_cents': 100,
        'discount_cents': 200,
        'subsidy_cents': 0,
        'refund_cents': refund,
        'address': '某某小区 1 栋',
        'lat': 30.66,
        'lng': 104.08,
        'has_review': hasReview,
        'created_at': '2026-08-20T12:00:00+08:00',
      };

  /// 照服务端 `/orders/counts` 的口径从同一批单子算出数 ——
  /// 角标只能来自服务端,但测试里「服务端」就是这两个列表
  Map<String, dynamic> countsOf(
      List<Map<String, dynamic>> orders, List<Map<String, dynamic>> stays) {
    const active = {'paid', 'accepted', 'ready', 'picked_up', 'delivered'};
    int n(bool Function(Map<String, dynamic>) f) => orders.where(f).length;
    return {
      'food': [
        if (orders.isNotEmpty)
          {
            'biz_type': 'food',
            'total': orders.length,
            'pending_payment': n((o) => o['status'] == 'pending_payment'),
            'active': n((o) => active.contains(o['status'])),
            'to_review': n(
                (o) => o['status'] == 'completed' && o['has_review'] != true),
          },
      ],
      'stay': {
        'total': stays.length,
        'pending_payment': stays.where((s) => s['status'] == 'created').length,
        'active': stays
            .where((s) =>
                const {'paid', 'confirmed', 'checked_in'}.contains(s['status']))
            .length,
        'to_review': 0,
      },
    };
  }

  Map<String, dynamic> stay({String status = 'created'}) => {
        'order_no': 'ST1',
        'checkin_date': '2026-09-01',
        'checkout_date': '2026-09-02',
        'status': status,
        'hotel_name': '城南旅馆',
      };

  ApiClient fakeApi({
    String riskLevel = '',
    bool marketing = true,
    List<Map<String, dynamic>> orders = const [],
    List<Map<String, dynamic>> stays = const [],
    bool verified = false,
    String? createdAt,
    List<Map<String, dynamic>> miniApps = const [],
    bool countsEndpoint = true,
    Map<String, dynamic>? counts,
    Map<String, dynamic> features = const {},
  }) {
    return ApiClient(
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
          case '/auth/me':
            payload = {
              'id': 1,
              'phone': '13800000001',
              'name': '张三',
              'role': 'customer',
              'avatar_url': '',
              'birthday': '',
              'marketing_push': true,
              'risk_level': riskLevel,
              'risk_note': riskLevel.isEmpty ? '' : '系统检测到异常',
              'identity_verified': verified,
              if (createdAt != null) 'created_at': createdAt,
            };
          case '/mini-apps/catalog':
            payload = {'items': miniApps, 'total': miniApps.length,
                       'next_cursor': null, 'categories': [], 'sort_rule': ''};
          case '/mini-apps/me':
            payload = {'recent': [], 'starred': []};
          case '/config':
            payload = {'marketing': marketing, 'features': features};
          case '/orders':
            payload = orders;
          case '/orders/counts':
            // 老服务端没有这个接口:「我的」页要退回数第一页
            if (!countsEndpoint) {
              return http.Response('{"detail":"Not Found"}', 404,
                  headers: {'content-type': 'application/json'});
            }
            payload = counts ?? countsOf(orders, stays);
          case '/stays/orders/mine':
            payload = stays;
          default:
            payload = <String, dynamic>{};
        }
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
  }

  /// 把「我的」页放进真机口径的可视区里。
  /// 宽 390、高 [firstScreen] —— 也就是**只给它首屏那么大的窗**。
  Future<void> pumpProfile(WidgetTester t, ApiClient api,
      {double scale = 1.0}) async {
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
          body: Align(
            alignment: Alignment.topLeft,
            child: SizedBox(
                width: 390, height: firstScreen, child: ProfileView(api: api)),
          ),
        ),
      ),
    ));
    await t.pumpAndSettle();
  }

  Future<ApiClient> loggedIn({
    String riskLevel = '',
    bool marketing = true,
    List<Map<String, dynamic>> orders = const [],
    List<Map<String, dynamic>> stays = const [],
    bool verified = false,
    String? createdAt,
    List<Map<String, dynamic>> miniApps = const [],
    bool countsEndpoint = true,
    Map<String, dynamic>? counts,
    // 板块开关(/config 的 features.*)。缺省全开 —— 服务端不给这个字段时
    // 客户端按"开着"算(`!= false`),桩要和那个口径一致
    Map<String, dynamic> features = const {},
  }) async {
    SharedPreferences.setMockInitialValues({});
    final api = fakeApi(
        riskLevel: riskLevel,
        marketing: marketing,
        orders: orders,
        stays: stays,
        verified: verified,
        createdAt: createdAt,
        miniApps: miniApps,
        countsEndpoint: countsEndpoint,
        counts: counts,
        features: features);
    await api.login('13800000001', 'pw');
    return api;
  }

  // package_info_plus 在测试环境没有平台通道:`PackageInfo.fromPlatform()`
  // **不抛异常,是永远不返回**。而 ApiClient.loadAppBuild() 在每个请求前
  // await 它(静态标记只保证试一次),于是本进程的第一个请求会永久挂起 ——
  // 表现成第一个用例超时 10 分钟,后面的用例全过。先把它铺好
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('首屏密度', () {
    testWidgets('已登录:首屏至少 14 个入口', (t) async {
      final api = await loggedIn(orders: [order()]);
      await pumpProfile(t, api);
      final n = visibleEntries(t);
      // 18:两轮网格化之后的实测值(帮助/反馈/食安投诉一组,
      // 实名/邀请/生日推送一组;邀请有礼 2026-09-14 下线后实测仍是 18)。
      // 门槛跟着实测往上抬 —— 只抬不降,
      // 不然下次有人把网格改回列表条这里照样绿。
      //
      // 注意首屏数不是唯一收益:第二轮压的是首屏**以下**的长度,
      // 整页要滚的距离 261 → 215px
      expect(n, greaterThanOrEqualTo(18),
          reason: '首屏只看得到 $n 个入口。改版前是 8 个,'
              '这一页的全部意义就是把这个数字提上来');
    });

    testWidgets('未登录:首屏不许是一片灰占位,至少 10 个入口', (t) async {
      SharedPreferences.setMockInitialValues({});
      final api = fakeApi();
      await pumpProfile(t, api);
      final n = visibleEntries(t);
      expect(n, greaterThanOrEqualTo(15),
          reason: '游客首屏只有 $n 个能点的东西 —— '
              '登录前这一页也得是有用的');
    });
  });

  // 改造前后的对比数字从这里出。**只打印不断言** ——
  // 断言在上面那组里,这条的用处是让「改了多少」有一份可复现的记录:
  // 把 lib/main.dart 换回旧版再跑一次,拿到的就是改造前的三个数
  testWidgets('MEASURE 三种状态的首屏入口数', (t) async {
    final loggedInApi = await loggedIn(orders: [order()]);
    await pumpProfile(t, loggedInApi);
    final a = visibleEntries(t);

    SharedPreferences.setMockInitialValues({});
    await pumpProfile(t, fakeApi());
    final b = visibleEntries(t);

    final riskApi = await loggedIn(riskLevel: 'limit', orders: [order()]);
    await pumpProfile(t, riskApi);
    final c = visibleEntries(t);

    // ignore: avoid_print
    print('MEASURE\t已登录=$a\t未登录=$b\t风控受限=$c');
  });

  group('长辈版:目标用户恰恰是扫不动这一页的人', () {
    testWidgets('长辈版开关在首屏内', (t) async {
      final api = await loggedIn(orders: [order()]);
      await pumpProfile(t, api);
      final finder = find.textContaining('长辈版');
      expect(finder, findsOneWidget);
      final box = t.renderObject<RenderBox>(finder);
      final rect = box.localToGlobal(Offset.zero) & box.size;
      expect(rect.bottom, lessThanOrEqualTo(firstScreen),
          reason: '长辈版被推到首屏外(底边 ${rect.bottom.toStringAsFixed(0)}px)。'
              '看不清这一页的人,正是要找它的人');
    });

    testWidgets('带开关的入口条不超过 72px', (t) async {
      final h = await () async {
        setPhoneViewport(t, const Size(390, 844));
        final w = SzEntryTile(
            icon: Icons.text_fields,
            title: '长辈版(大字模式)',
            hint: '放大全局字号,看得更清楚',
            trailing: Switch(value: false, onChanged: (_) {}),
            onTap: () {});
        await t.pumpWidget(MaterialApp(
          theme: brandTheme(Brightness.light),
          home: Scaffold(
              body: Align(alignment: Alignment.topCenter, child: w)),
        ));
        await t.pumpAndSettle();
        return t.getSize(find.byWidget(w)).height;
      }();
      // 72 = Switch 的 48px 触控区 + 上下各 12 的内边距。
      // **不许为了省高度去缩触控区** —— 这一行的用户就是手不稳的人
      expect(h, lessThanOrEqualTo(72),
          reason: '开关行涨到 ${h.toStringAsFixed(0)}px 了');
    });
  });

  /// 角标上的数。订单卡头上还有频道足迹(「■ 2」),光按文字找会撞上
  Finder badgeText(String n) =>
      find.descendant(of: find.byType(Badge), matching: find.text(n));

  group('订单区:按状态分流,数字是它区别于底部 tab 的全部理由', () {
    testWidgets('四格都在,且待评价/退款售后不是凭空造的状态', (t) async {
      final api = await loggedIn(orders: [order()]);
      await pumpProfile(t, api);
      for (final label in ['待支付', '进行中', '待评价', '退款售后']) {
        expect(find.text(label), findsOneWidget, reason: '缺了「$label」格');
      }
      expect(find.text('我的订单'), findsOneWidget);
    });

    testWidgets('待支付角标 = 外卖 + 住宿', (t) async {
      final api = await loggedIn(
        orders: [
          order(no: 'A', status: 'pending_payment'),
          order(no: 'B', status: 'completed'),
        ],
        stays: [stay(status: 'created'), stay(status: 'confirmed')],
      );
      await pumpProfile(t, api);
      // 外卖 1 笔待支付 + 住宿 1 笔待支付 = 2。
      // 住宿的 created 单 15 分钟不付就自动关闭,漏数它是真金白银的损失
      expect(badgeText('2'), findsOneWidget,
          reason: '待支付角标没把住宿的待支付单算进去');
    });

    testWidgets('待评价角标来自 has_review,不靠一单一发请求去猜', (t) async {
      final api = await loggedIn(orders: [
        order(no: 'A', status: 'completed', hasReview: false),
        order(no: 'B', status: 'completed', hasReview: false),
        order(no: 'C', status: 'completed', hasReview: true),
      ]);
      await pumpProfile(t, api);
      expect(badgeText('2'), findsOneWidget,
          reason: '待评价应为 2(3 笔完成,1 笔已评)');
    });

    testWidgets('角标用服务端全量 count,不数列表第一页', (t) async {
      // 列表只回来 1 单(第一页),服务端说一共有 5 单待评价 ——
      // 评价没有时限,老单也算,第一页数不出来
      final api = await loggedIn(orders: [
        order(no: 'A', status: 'completed', hasReview: false),
      ], counts: {
        'food': [
          {
            'biz_type': 'food',
            'total': 40,
            'pending_payment': 0,
            'active': 0,
            'to_review': 5,
          },
        ],
        'stay': {'total': 0, 'pending_payment': 0, 'active': 0, 'to_review': 0},
      });
      await pumpProfile(t, api);
      expect(badgeText('5'), findsOneWidget,
          reason: '待评价该是服务端数的 5,不是第一页里那 1 单');
    });

    testWidgets('老服务端没有 /orders/counts:退回数第一页,不是全 0', (t) async {
      final api = await loggedIn(countsEndpoint: false, orders: [
        order(no: 'A', status: 'completed', hasReview: false),
        order(no: 'B', status: 'completed', hasReview: false),
      ]);
      await pumpProfile(t, api);
      expect(badgeText('2'), findsOneWidget,
          reason: '接口 404 时角标不能变成 0 —— 那等于藏起待办');
    });

    testWidgets('订单卡头上是频道足迹:买过的频道各一个色块 + 单数', (t) async {
      final api = await loggedIn(
        // 都评过了:待评价没有角标,页面上的「3」只可能是足迹
        orders: [
          order(no: 'A', hasReview: true),
          order(no: 'B', hasReview: true),
          order(no: 'C', hasReview: true),
        ],
        stays: [stay(status: 'confirmed')],
      );
      await pumpProfile(t, api);
      // 外卖 3、住宿 1;数不在角标里,在卡头上
      expect(find.text('3'), findsOneWidget);
      expect(badgeText('3'), findsNothing);
      expect(find.text('全部订单'), findsNothing,
          reason: '有足迹时卡头不再重复写「全部订单」—— 整行本身就是那个入口');
    });

    testWidgets('优惠券 / 团购券挂的是「还能用几张」,hold 色,不是待办红', (t) async {
      final api = await loggedIn(orders: [
        order(no: 'A', hasReview: true),
      ], counts: {
        'food': [
          {
            'biz_type': 'food',
            'total': 1,
            'pending_payment': 0,
            'active': 0,
            'to_review': 0,
          },
        ],
        'stay': {'total': 0, 'pending_payment': 0, 'active': 0, 'to_review': 0},
        'coupons_usable': 3,
        'tickets': {'total': 4, 'usable': 2},
      });
      await pumpProfile(t, api);
      expect(badgeText('3'), findsOneWidget, reason: '优惠券还能用 3 张');
      expect(badgeText('2'), findsOneWidget, reason: '团购券还能用 2 张');
      final hold = Theme.of(t.element(find.byType(ProfileView))).sz.hold;
      for (final n in ['3', '2']) {
        final badge = t.widget<Badge>(
            find.ancestor(of: badgeText(n), matching: find.byType(Badge)));
        expect(badge.backgroundColor, hold);
      }
      // 团购买过 4 张:在卡头足迹里,不在角标里
      expect(find.text('4'), findsOneWidget);
      expect(badgeText('4'), findsNothing);
    });

    testWidgets('拿不到数(老服务端):卡头退回「全部订单」', (t) async {
      final api = await loggedIn(countsEndpoint: false, orders: [order()]);
      await pumpProfile(t, api);
      expect(find.text('全部订单'), findsOneWidget);
    });

    testWidgets('退款售后不给角标 —— 退款到账不是待办', (t) async {
      // B 给 hasReview:true,好让「待评价」那格也是 0 ——
      // 这条要验的是「退款售后不挂角标」,别让别的格子的数字混进来
      final api = await loggedIn(orders: [
        order(no: 'A', status: 'cancelled', refund: 3200),
        order(no: 'B', status: 'completed', hasReview: true),
      ]);
      await pumpProfile(t, api);
      expect(badgeText('1'), findsNothing,
          reason: '给退款记录挂红点只会制造焦虑');
    });

    testWidgets('未登录不渲染订单区 —— 四个 0 的格子就是灰占位', (t) async {
      SharedPreferences.setMockInitialValues({});
      await pumpProfile(t, fakeApi());
      expect(find.text('我的订单'), findsNothing);
      expect(find.text('待评价'), findsNothing);
    });
  });

  group('账目透明放在黄金位', () {
    testWidgets('三个账目入口都在首屏,且排在订单区之前', (t) async {
      final api = await loggedIn(orders: [order()]);
      await pumpProfile(t, api);
      double bottomOf(String text) {
        final box = t.renderObject<RenderBox>(find.text(text));
        return (box.localToGlobal(Offset.zero) & box.size).bottom;
      }

      for (final label in ['钱去哪了', '平台账本', '平台体检']) {
        expect(find.text(label), findsOneWidget);
        expect(bottomOf(label), lessThanOrEqualTo(firstScreen));
      }
      expect(bottomOf('钱去哪了'), lessThan(bottomOf('我的订单')),
          reason: '账目该在订单之上 —— 这是这个平台要用户记住的东西');
    });

    testWidgets('游客也看得到账目入口:它不依赖登录', (t) async {
      SharedPreferences.setMockInitialValues({});
      await pumpProfile(t, fakeApi());
      expect(find.text('钱去哪了'), findsOneWidget);
      expect(find.text('平台体检'), findsOneWidget);
    });
  });

  group('删掉的和留下的', () {
    testWidgets('三格数字卡不再出现 —— 那两个数字只统计了最近 20 单',
        (t) async {
      final api = await loggedIn(orders: [order()]);
      await pumpProfile(t, api);
      expect(find.text('累计优惠'), findsNothing,
          reason: 'myOrders() 默认 limit=20,'
              '「累计」在第 21 单之后就是错的');
      expect(find.text('已完成订单'), findsNothing);
    });

    testWidgets('用户协议与隐私政策留在「我的」页(商店审核要求)', (t) async {
      final api = await loggedIn(orders: [order()]);
      await pumpProfile(t, api);
      await t.dragUntilVisible(
        find.text('用户协议与隐私政策'),
        find.byType(ListView),
        const Offset(0, -120),
      );
      expect(find.text('用户协议与隐私政策'), findsOneWidget);
    });

    testWidgets('设置与客服不再占正文行', (t) async {
      final api = await loggedIn(orders: [order()]);
      await pumpProfile(t, api);
      expect(find.text('设置'), findsNothing,
          reason: '设置该在 AppBar 右上角');
      expect(find.text('联系平台客服'), findsNothing,
          reason: '客服该在 AppBar 右上角');
    });
  });

  group('风控受限', () {
    testWidgets('横幅照常显示,一分不缩', (t) async {
      final api = await loggedIn(riskLevel: 'limit', orders: [order()]);
      await pumpProfile(t, api);
      expect(find.textContaining('营销权益暂被限制'), findsOneWidget);
    });

    testWidgets('营销权益被限制时不给营销入口(生日券那一格)', (t) async {
      final api = await loggedIn(riskLevel: 'limit', orders: [order()]);
      await pumpProfile(t, api);
      await t.pumpAndSettle();
      expect(find.text('生日与推送'), findsNothing,
          reason: '账号营销权益已被限制,却还能点进营销入口 —— '
              '要么处置是假的,要么点进去才发现是死路');
    });

    testWidgets('风控态下首屏仍有 12 个入口', (t) async {
      final api = await loggedIn(riskLevel: 'limit', orders: [order()]);
      await pumpProfile(t, api);
      final n = visibleEntries(t);
      expect(n, greaterThanOrEqualTo(12),
          reason: '风控横幅 88px 不缩,但也不该把整页挤没(当前 $n)');
    });
  });

  group('邀请有礼下线(2026-09-14,平台不出钱做营销)', () {
    testWidgets('营销开着、账号没受限,也没有「邀请有礼」入口和「各得券」的说法', (t) async {
      final api = await loggedIn(orders: [order()]);
      await pumpProfile(t, api);
      await t.pumpAndSettle();
      expect(find.text('生日与推送'), findsOneWidget, reason: '营销开着,前提得成立');
      expect(find.text('邀请有礼'), findsNothing,
          reason: '邀请有礼停了(服务端填码 410),入口还在就是一条死路');
      expect(find.textContaining('各得券'), findsNothing);
    });
  });

  group('身份行、账目台面、网格(设计稿 3e)', () {
    testWidgets('实名了挂「已实名」,手机号打码,写哪年哪月加入', (t) async {
      final api = await loggedIn(
          verified: true, createdAt: '2026-07-15T10:00:00+08:00');
      await pumpProfile(t, api);
      expect(find.text('已实名'), findsOneWidget);
      expect(find.text('138 **** 0001 · 2026 年 7 月加入'), findsOneWidget);
      expect(find.text('13800000001'), findsNothing,
          reason: '这一页常被截图,完整手机号不该摆在最显眼的位置');
    });

    testWidgets('没实名不挂标,实名入口还在下面的列表里', (t) async {
      final api = await loggedIn();
      await pumpProfile(t, api);
      expect(find.text('已实名'), findsNothing);
      // 身份行只在已实名时出标记、点它是改昵称 —— 没实名的人要去实名,
      // 靠的就是这一格。设计稿原本想删掉它,删了就只剩结算页买酒那一个入口
      await t.scrollUntilVisible(find.text('实名认证'), 200);
      expect(find.text('实名认证'), findsOneWidget);
    });

    testWidgets('账目台面里的字取的是深色态颜色 —— 不是黑底黑字', (t) async {
      final api = await loggedIn();
      await pumpProfile(t, api);
      // SzLedgerCard 在台面**里面**把 SzColors 换成深色态。
      // 在台面外面先取 sz 再传进来,拿到的是浅色那套墨色 —— 深底上看不见
      final title = t.widget<Text>(find.text('平台只抽这么多'));
      expect(title.style?.color, SzColors.dark.ink);
      expect(find.byType(SzLedgerCard), findsOneWidget);
    });

    testWidgets('有小程序才出「小程序」格子,点开是抽屉面板', (t) async {
      final api = await loggedIn(miniApps: [
        {
          'appid': 'sz0123456789abcdef',
          'id': 1,
          'name': '透明中心',
          'icon': '📊',
          'tagline': '',
          'kind': 'app',
          'hosting': 'external',
          'developer': {'name': '陕西爱卡斯科技有限公司', 'label': '官方'},
        },
      ]);
      await pumpProfile(t, api);
      await t.tap(find.text('小程序'));
      await t.pumpAndSettle();
      expect(find.textContaining('人工挑选'), findsOneWidget);
    });

    testWidgets('清单是空的就不出这一格 —— 点开一个空面板比没有入口更糟', (t) async {
      final api = await loggedIn();
      await pumpProfile(t, api);
      expect(find.text('小程序'), findsNothing);
    });
  });

  // ---------------- 板块入口:一个板块一格(2026-09-17) ----------------
  //
  // 这一页原来只有视频有自己一块(六格图标),音乐和论坛一个入口都没有。
  // 板块多起来之后照样摊开就是十八格,而那六格在 VideoMePage 里本来就有一份。
  group('板块入口', () {
    Finder tile(String label) => find.widgetWithText(InkWell, label);

    testWidgets('三个板块各一格,不再摊开视频那六格', (t) async {
      await pumpProfile(t, await loggedIn());
      await t.dragUntilVisible(tile('我的视频'),
          find.byType(ListView), const Offset(0, -80));
      for (final k in ['我的视频', '我的音乐', '我的论坛']) {
        expect(tile(k), findsOneWidget, reason: k);
      }
      // 那六格是 VideoMePage 的事。摆在这里是第二份,两份迟早对不上
      for (final k in ['观看历史', '稍后再看', '视频收藏', '创作中心', '视频设置']) {
        expect(find.text(k), findsNothing, reason: '$k 不该还留在「我的」页上');
      }
    });

    testWidgets('关掉的板块不出那一格——**入口和开关要对上**', (t) async {
      // 用户 2026-09-17 踩过的正是这一类:功能闸开了,入口没跟着出,
      // 人以为功能坏了。反过来同样难受:闸关着入口还在,点进去只说「暂未开放」
      await pumpProfile(
          t, await loggedIn(features: {'video': true, 'music': false, 'forum': true}));
      await t.dragUntilVisible(tile('我的视频'),
          find.byType(ListView), const Offset(0, -80));
      expect(tile('我的视频'), findsOneWidget);
      expect(tile('我的论坛'), findsOneWidget);
      expect(find.text('我的音乐'), findsNothing, reason: '音乐关着就不该有这一格');
    });

    testWidgets('三个都关着时一格都不出', (t) async {
      await pumpProfile(
          t,
          await loggedIn(
              features: {'video': false, 'music': false, 'forum': false}));
      for (final k in ['我的视频', '我的音乐', '我的论坛']) {
        expect(find.text(k), findsNothing, reason: k);
      }
    });
    // 「这时候整张卡不画、而不是画成一张空卡」那一条**没有用例守**:
    // 试过三种数卡片的写法(按首屏数 / 滚到底数 / 给足高度数),
    // 每一种红的原因都是 ListView 的懒加载而不是产品行为 —— 再往下写
    // 就是在测框架。那一条由实现里那句 `if (items.isEmpty) return
    // const SizedBox.shrink();` 兜着,改动时留意。

    testWidgets('服务端没给 features 时按「开着」算——老服务端不该把入口弄没', (t) async {
      await pumpProfile(t, await loggedIn(features: const {}));
      await t.dragUntilVisible(tile('我的音乐'),
          find.byType(ListView), const Offset(0, -80));
      expect(tile('我的音乐'), findsOneWidget);
    });
  });
}
