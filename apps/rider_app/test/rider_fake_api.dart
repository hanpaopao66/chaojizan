// ignore_for_file: depend_on_referenced_packages
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 骑手端 widget 测试的共用夹具:假后端 + 真机口径视口。
///
/// ## 两个必须先铺好的坑
///
/// **① `package_info_plus` 在测试环境不抛异常,是永远不返回。**
/// `ApiClient.loadAppBuild()` 在每个请求前 await 它,于是本进程的第一个
/// 请求会**永久挂起** —— 表现成第一个用例超时十分钟、后面的用例全过。
/// 所以 [setUpRiderTest] 里先 `PackageInfo.setMockInitialValues`。
///
/// **② `_appBuildTried` 是 static,跨用例不复位。**
/// 同一个文件里前面的用例碰过之后,后面的用例直接短路 ——
/// 涉及它的断言会**变成空断言**(不报错,只是什么也没验)。
/// 所以每个用例的 `setUp` 里调 `ApiClient.resetAppBuildForTest()`。
void setUpRiderTest() {
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'rider_app',
      packageName: 'com.superz.rider',
      version: '1.0.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });
  setUp(ApiClient.resetAppBuildForTest);
}

/// 把渲染视口真的调成手机尺寸。
///
/// ⚠️ **只给 MediaQuery 传 size 是没用的** —— widget 测试的渲染视口默认
/// 800×600,MediaQuery 里那个 size 只是元数据,不改布局约束。
/// 那会拿一块 800px 宽的屏去量 390 的密度。
void setPhoneViewport(WidgetTester tester, Size logical) {
  tester.view
    ..devicePixelRatio = 3.0
    ..physicalSize = logical * 3.0;
  addTearDown(tester.view.reset);
}

/// 390×844 的机器上,页面 body 拿到的可视高度:
///
///   844 − 47(顶部安全区) − 56(AppBar) − 96(底部导航 62 + 底部安全区 34)
///
/// 底部导航高度见 brand.dart 的 navigationBarTheme(62),
/// NavigationBar 自带 SafeArea(见 Flutter navigation_bar.dart)。
const double kFirstScreen = 645.0;

/// 首屏内**完整可见**的可点入口个数。
///
/// 判据是「有 onTap 的 InkWell 矩形」,并且:
/// - 底边超出首屏的不算(露一半的入口用户点不安心,也扫不到);
/// - 嵌套的只算最里面那个(卡片本身可点、里面又套着按钮,算一个)。
///
/// 数的是**真正能点的矩形**,不是某个具体组件类型 —— 这样重排、换组件
/// 都不会让这个数字失真:它问的是用户的问题(「不滚动我能点到几样东西」),
/// 不是实现的问题。
int visibleEntries(WidgetTester t, {double limit = kFirstScreen}) {
  final rects = <Rect>[];
  for (final element in find.byType(InkWell).evaluate()) {
    final w = element.widget as InkWell;
    if (w.onTap == null) continue;
    final box = element.renderObject as RenderBox?;
    if (box == null || !box.hasSize) continue;
    final rect = box.localToGlobal(Offset.zero) & box.size;
    if (rect.isEmpty || rect.bottom > limit) continue;
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

/// 「有没有字被画到自己的盒子外面」。与 packages/shared/test/text_fit.dart
/// 同一套判据 —— 测试文件不进包,跨包引不到,所以这里留一份。
///
/// 这类问题**不抛异常**:Flutter 把盒子裁到该有的宽度,然后照样把超出的
/// 字画出去,一声不吭。`takeException()` 是空的,页面看着渲染成功了。
List<String> textsPaintingOutside(WidgetTester tester) {
  final bad = <String>[];
  for (final element in find.byType(Text).evaluate()) {
    final widget = element.widget as Text;
    if (widget.overflow != TextOverflow.visible) continue;
    final para = element.renderObject as RenderParagraph?;
    if (para == null || !para.hasSize) continue;
    final canWrap = widget.softWrap != false && widget.maxLines != 1;
    final need = canWrap
        ? para.getMinIntrinsicWidth(double.infinity)
        : para.getMaxIntrinsicWidth(double.infinity);
    if (need > para.size.width + 0.5) {
      bad.add('「${widget.data}」要 ${need.toStringAsFixed(0)}px,'
          '盒子只有 ${para.size.width.toStringAsFixed(0)}px');
    }
  }
  return bad;
}

/// 假后端。默认是「一切正常的老骑手」:认证通过、账户已登记、培训已过。
///
/// 每个字段都能单独改成异常态,用来验条件块和状态值。
ApiClient fakeRiderApi({
  int unread = 0,
  // 今日/本周数据(服务端 SQL 聚合,不是客户端求和 —— 见 riders.py my_worklog)
  int todayMinutes = 312,
  int todayOrders = 14,
  int todayEarnedCents = 8600,
  int weekMinutes = 1980,
  int weekOrders = 71,
  int weekEarnedCents = 43200,
  // 里程(#309):计价里程,不含骑手到店那一段。null = 服务端还没给这个字段
  int? todayMeters = 42100,
  int? weekMeters = 213400,
  // 本次连续在线(注意:这是**会话**不是**今天**,见 riders.py my_fatigue)
  double fatigueMinutes = 312,
  String fatigueLevel = 'ok',
  String fatigueMessage = '',
  String verifyStatus = 'approved',
  bool payoutConfigured = true,
  String payoutTail = '4821',
  bool examPassed = true,
  // 拉不到就当没有:入口照常在,只是不显状态
  Set<String> failing = const {},

  /// 订单列表 —— 用来证明黄金位的数字**不**来自它
  List<Map<String, dynamic>> orders = const [],
}) =>
    ApiClient(
      baseUrl: 'http://test.local',
      httpClient: MockClient((req) async {
        final path = req.url.path;
        if (failing.contains(path)) {
          return http.Response('{"detail":"boom"}', 500,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        Object? payload;
        switch (path) {
          case '/riders/me/fatigue':
            payload = {
              'online_minutes': fatigueMinutes,
              'level': fatigueLevel,
              'message': fatigueMessage.isEmpty ? null : fatigueMessage,
              'blocks_grabbing': false,
            };
          case '/riders/me/worklog':
            payload = {
              'today_minutes': todayMinutes,
              'week_minutes': weekMinutes,
              'today_orders': todayOrders,
              'today_earned_cents': todayEarnedCents,
              'week_orders': weekOrders,
              'week_earned_cents': weekEarnedCents,
              if (todayMeters != null) 'today_meters': todayMeters,
              if (weekMeters != null) 'week_meters': weekMeters,
            };
          case '/riders/me/messages':
            payload = {'unread': unread, 'items': <dynamic>[]};
          case '/riders/profile':
            payload = {
              'real_name': '王**',
              'health_cert_photo_url': '',
              'status': verifyStatus,
              'id_verified': verifyStatus == 'approved',
              'health_cert_required': false,
              'city': '成都',
              'reject_reason': verifyStatus == 'rejected' ? '身份证照片模糊' : '',
            };
          case '/payout-account':
            payload = {
              'configured': payoutConfigured,
              'kind': 'bank_personal',
              'holder_name': '王**',
              'bank_name': '招商银行',
              'account_tail': payoutTail,
              'recently_changed': false,
            };
          case '/riders/exam/status':
            payload = {
              'passed': examPassed,
              'best_score': examPassed ? 100 : 60,
              'pass_score': 100,
              'version': 1,
            };
          case '/orders':
            payload = orders;
          default:
            payload = <String, dynamic>{};
        }
        return http.Response(jsonEncode(payload), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
