import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/main.dart';
import 'package:user_app/money_flow_page.dart';
import 'package:user_app/transparency_page.dart';
import 'package:user_app/trust_page.dart';

/// 「我的」页顶那张账目卡:可以永久关掉,但**关掉不许把入口带走**。
///
/// ## 为什么这张卡不能像首页承诺条那样一关了之
///
/// 首页 `_promiseStrip` 关掉是安全的,它自己的注释写清了判据:
/// 「关掉不影响任何功能,『我的 → 这钱怎么算的』一直在」——
/// 也就是说,**它敢消失是因为这张卡兜着**。
///
/// 而这张卡是终点站,不是转发站。改之前查过全仓的构造点:
///
/// | 入口 | 卡之外还有谁能到 |
/// |---|---|
/// | 钱去哪了 | 首页承诺条(**它自己也能关**)、订单详情按钮(要 `commission_cents > 0`) |
/// | 平台账本 | 只有 `money_flow_page.dart:220`(得先进得去分账页) |
/// | 平台体检 | 只有 `trust_page.dart:177`(得先进得去平台账本) |
///
/// 于是最坏那条路是真的:**承诺条关了 + 这张卡关了 + 一单没下过**,
/// 平台账本和平台体检就从这个 App 里彻底消失了 —— 而它们正是
/// 「我们和三大平台的结构性差别」。所以这一版的规矩是
/// **关掉的是卡,不是入口**:卡收起的同时,三条入口落到底部那张设置卡里。
///
/// 这个测试就是拿那条最坏路径当判据。
void main() {
  // package_info_plus 在测试环境没有平台通道:`PackageInfo.fromPlatform()`
  // **不抛异常,是永远不返回**,第一个请求会永久挂起。先把它铺好
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

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    // 同文件前面的用例碰过这个 static 标记之后,后面的用例会短路
    ApiClient.resetAppBuildForTest();
  });

  Map<String, dynamic> order() => {
        'order_no': 'SZ1',
        'merchant_id': 1,
        'merchant_name': '楼下面馆',
        'status': 'completed',
        'items': [
          {'dish_id': 1, 'name': '牛肉面', 'price_cents': 2000, 'quantity': 1}
        ],
        'food_cents': 2000,
        'delivery_fee_cents': 300,
        'total_cents': 2300,
        // 分账页要真数字才进得去(否则 openMoneyFlow 退回说明弹层)
        'commission_cents': 115,
        'discount_cents': 0,
        'subsidy_cents': 0,
        'refund_cents': 0,
        'tip_cents': 0,
        'address': '某小区',
        // ⚠️ lat/lng 是 `Order.fromJson` 里少数几个**没有默认值**的字段。
        // 漏了会抛,而 openMoneyFlow 的 catch 把异常吃掉退回说明弹层 ——
        // 表现成「点了没反应」,查半天才发现是假数据的问题
        'lat': 30.66,
        'lng': 104.08,
        'created_at': '2026-08-21T12:00:00+08:00',
      };

  ApiClient fakeApi({List<Map<String, dynamic>> orders = const []}) =>
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
            case '/auth/me':
              payload = {
                'id': 1,
                'phone': '13800000001',
                'name': '张三',
                'role': 'customer',
                'avatar_url': '',
                'birthday': '',
                'marketing_push': true,
                'risk_level': '',
                'risk_note': '',
              };
            case '/config':
              payload = {'marketing': true};
            case '/orders':
              payload = orders;
            default:
              payload = <String, dynamic>{};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<ApiClient> loggedIn(
      {List<Map<String, dynamic>> orders = const []}) async {
    final api = fakeApi(orders: orders);
    await api.login('13800000001', 'pw');
    return api;
  }

  /// 整页渲染。**视口和盒子一起放大到 3000** —— 只放大 SizedBox 没用,
  /// 它会被渲染视口(默认 800×600)夹住,ListView 于是只建前一千多像素,
  /// 「入口不在页面上」和「那一段压根没渲染」长得一模一样,断言会假绿。
  Future<void> pumpProfile(WidgetTester t, ApiClient api,
      {NavigatorObserver? observer}) async {
    tester(t);
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      navigatorObservers: [if (observer != null) observer],
      home: Scaffold(
        body: Align(
          alignment: Alignment.topLeft,
          child:
              SizedBox(width: 390, height: 3000, child: ProfileView(api: api)),
        ),
      ),
    ));
    await t.pumpAndSettle();
  }

  group('默认不关', () {
    testWidgets('卡在,关闭按钮也在', (t) async {
      await pumpProfile(t, await loggedIn(orders: [order()]));
      expect(find.text('平台只抽这么多'), findsOneWidget);
      expect(find.byIcon(Icons.close), findsOneWidget,
          reason: '这张卡没有关闭按钮 —— 宣言看过一次就够,得给得起关的人一个出口');
    });

    testWidgets('关闭按钮触控区 40×40:图标只有 16,光按图标点不中', (t) async {
      await pumpProfile(t, await loggedIn(orders: [order()]));
      final hit = find
          .ancestor(
              of: find.byIcon(Icons.close), matching: find.byType(InkWell))
          .first;
      final size = t.getSize(hit);
      expect(size.width, greaterThanOrEqualTo(40));
      expect(size.height, greaterThanOrEqualTo(40));
      // 大到误触也是错的:整卡宽 358,关闭键不该吃掉其中一大块
      expect(size.width, lessThanOrEqualTo(48));
      expect(size.height, lessThanOrEqualTo(48));
    });
  });

  group('关掉之后', () {
    testWidgets('卡不再渲染', (t) async {
      await pumpProfile(t, await loggedIn(orders: [order()]));
      await t.tap(find.byIcon(Icons.close));
      await t.pumpAndSettle();
      expect(find.text('平台只抽这么多'), findsNothing);
      expect(find.text('每一单的钱去了哪里,平台的账本长什么样,都查得到'), findsNothing);
    });

    testWidgets('冷启动后仍然是关的', (t) async {
      await pumpProfile(t, await loggedIn(orders: [order()]));
      await t.tap(find.byIcon(Icons.close));
      await t.pumpAndSettle();

      // 换一棵全新的树 + 全新的 ApiClient,模拟杀进程重开。
      // SharedPreferences 的 mock 值不重置 —— 上一步写进去的就该留着
      await pumpProfile(t, await loggedIn(orders: [order()]));
      expect(find.text('平台只抽这么多'), findsNothing,
          reason: '重开之后卡又回来了 —— 关闭状态没落盘,只是一次 setState');
    });

    testWidgets('落的是 profile_ledger_hidden,不和首页承诺条串键', (t) async {
      await pumpProfile(t, await loggedIn(orders: [order()]));
      await t.tap(find.byIcon(Icons.close));
      await t.pumpAndSettle();
      final sp = await SharedPreferences.getInstance();
      expect(sp.getBool('profile_ledger_hidden'), isTrue);
      // 首页那条是 home_pledge_hidden。共用一个键的话,
      // 关掉「我的」这张卡会把首页承诺条一起带走(反过来也是)
      expect(sp.getBool('home_pledge_hidden'), isNull,
          reason: '两处共用了同一个键 —— 关一个会连带关掉另一个');
    });
  });

  group('关掉之后那三个入口仍然可达', () {
    // 这一组是这次改动的**硬判据**。上面「卡不再渲染」全绿而这一组红,
    // 意味着我们把一个能关的横幅换成了三条走不到的路
    for (final (label, page) in [
      ('钱去哪了', MoneyFlowPage),
      ('平台账本', TrustPage),
      ('平台体检', TransparencyPage),
    ]) {
      testWidgets('$label → $page', (t) async {
        SharedPreferences.setMockInitialValues({'profile_ledger_hidden': true});
        final spy = _PushSpy();
        await pumpProfile(t, await loggedIn(orders: [order()]), observer: spy);
        expect(find.text('平台只抽这么多'), findsNothing, reason: '前置条件没成立:卡还开着');

        final target = find.text(label);
        expect(target, findsOneWidget,
            reason: '卡关掉之后「$label」在这一页上找不到了 —— '
                '它在别处**没有**入口(见本文件头的那张表)');
        spy.lastPushed = null;
        await t.tap(target);
        // openMoneyFlow 要先 await myOrders() 才知道往哪跳,一帧不够
        await t.pump();
        await t.pump(const Duration(milliseconds: 300));
        await t.pump(const Duration(milliseconds: 300));
        // 目标页自己会去拉数据,假后端回 {} 时可能报错,与本测试无关
        t.takeException();
        expect(spy.lastPushed, page,
            reason: '「$label」点下去没到 $page,而是 ${spy.lastPushed ?? "什么也没 push"}');
      });
    }

    testWidgets('卡开着的时候不重复挂:同一个入口不许一页出现两次', (t) async {
      await pumpProfile(t, await loggedIn(orders: [order()]));
      for (final label in ['钱去哪了', '平台账本', '平台体检']) {
        expect(find.text(label), findsOneWidget,
            reason: '「$label」在页面上出现了不止一次 —— '
                '卡里一份、列表里一份,那是两个入口不是一个');
      }
    });
  });
}

/// 把渲染视口真的调成手机尺寸(与 profile_view_test.dart 同一套)。
void tester(WidgetTester t) {
  t.view
    ..devicePixelRatio = 3.0
    ..physicalSize = const Size(390, 3000) * 3.0;
  addTearDown(t.view.reset);
}

/// 记下最近一次 push 的是什么页。
class _PushSpy extends NavigatorObserver {
  Type? lastPushed;

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) {
    final page = route is MaterialPageRoute ? route.builder : null;
    if (page == null) return;
    // builder 还没跑过,拿不到实例 —— 跑一次拿类型。
    // 目标页的 initState 会去拉数据,拉不到不影响这里取类型
    try {
      lastPushed = page(navigator!.context).runtimeType;
    } catch (_) {
      lastPushed = null;
    }
  }
}
