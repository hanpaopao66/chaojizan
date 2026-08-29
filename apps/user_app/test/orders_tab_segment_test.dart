import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/channel_config.dart';
import 'package:user_app/main.dart';
import 'package:user_app/stay_order_pages.dart';

/// 订单 tab 的频道分段:**关掉一个频道不能把人关在里面**。
///
/// ## 这条守的是一个死路,不是一个样式
///
/// 「我的」页四格会按「哪边有单落哪边」跳转,只有住宿单时它带 segment=1
/// 过来 —— 这条路**不看 ChannelConfig**。而订单页在住宿关掉时把分段器
/// 整条藏掉,于是 _segment 停在 1、页面上再没有任何控件能切回外卖。
///
/// 结果是一个**能进不能出**的状态:用户看着一列住宿单,想回去看外卖单
/// 只能杀进程重开。这种故障不报错、不崩溃,测试也全绿 ——
/// 只有真去走一遍那条路才会撞上。
///
/// 所以判据不是「分段器在不在」,是**「回得去吗」**:
/// 只要人已经在住宿分段上,就必须存在一个能切回外卖的控件。
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

  ApiClient fakeApi({List<Map<String, dynamic>> stays = const []}) =>
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
              payload = <Object>[];
            case '/stays/orders/mine':
              payload = stays;
            default:
              payload = <String, Object>{};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<void> pump(WidgetTester tester, int segment,
      {List<Map<String, dynamic>> stays = const []}) async {
    final api = fakeApi(stays: stays);
    // 不登录的话订单页整页短路成登录引导,断言的是另一个界面
    await api.login('13800000001', '123456');
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: OrdersTab(api: api, segment: segment)),
    ));
    await tester.pump();
  }

  testWidgets('住宿关掉时,从「我的」带 segment=1 进来不能把人关在住宿里',
      (tester) async {
    ChannelConfig.setForTest(const ['food', 'voucher']);   // 住宿已关
    await pump(tester, 1);

    // 判据是「人不在住宿里」。带 segment=1 进来的路不看 ChannelConfig
    // (「我的」页四格按「哪边有单落哪边」跳),而分段器在住宿关掉时
    // 整条隐藏 —— 不钳制的话人停在住宿列表,页面上没有任何控件能
    // 切回外卖,只能杀进程。修法是落地时直接钳回外卖列表
    expect(find.byType(StayOrderListView), findsNothing,
        reason: '住宿关掉后还把人放进住宿列表 —— 分段器已隐藏,'
            '这是一个能进不能出的状态');
    expect(find.byType(OrderListView), findsOneWidget);
  });

  testWidgets('住宿关掉且本来就在外卖分段:不显示分段器(一个选项的分段器是噪音)',
      (tester) async {
    ChannelConfig.setForTest(const ['food', 'voucher']);
    await pump(tester, 0);
    expect(find.byType(SegmentedButton<int>), findsNothing);
  });

  testWidgets('住宿关掉但有历史住宿单:分段器保留 —— 关频道不能没收凭证',
      (tester) async {
    ChannelConfig.setForTest(const ['food', 'voucher']);
    await pump(tester, 1, stays: [
      {
        'order_no': 'ST1',
        'hotel_id': 1,
        'hotel_name': '测试酒店',
        'status': 'paid',
        'room_name': '大床房',
        'checkin_date': '2026-09-01',
        'checkout_date': '2026-09-02',
        'nights': 1,
        'total_cents': 12800,
        'created_at': '2026-08-29T10:00:00',
      }
    ]);
    await tester.pump();     // 等 _probeLegacyStays 的 setState 落地

    // 订单是凭证:用户要拿它入住、退款。频道开关管「能不能新买」,
    // 不管「已买的还能不能看」——「我的」页四格也照常统计住宿单,
    // 数字说有 1 单,点进来必须有地方看
    expect(find.byType(SegmentedButton<int>), findsOneWidget,
        reason: '有历史住宿单时藏掉分段器,等于没收用户的凭证');
    expect(find.byType(StayOrderListView), findsOneWidget);
  });

  testWidgets('住宿开着:分段器正常显示', (tester) async {
    ChannelConfig.setForTest(const ['food', 'stay', 'voucher']);
    await pump(tester, 0);
    expect(find.byType(SegmentedButton<int>), findsOneWidget);
  });
}
