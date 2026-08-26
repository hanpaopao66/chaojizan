import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/main.dart';

/// 首页商家卡的密度与信息完整度。
///
/// ## 这个测试防的是什么
///
/// 改版前一张卡 182px:标签换到两行(44px),而那几个标签在真实数据里
/// **每家店都一样**(「5% 封顶」是平台承诺不是店铺属性,六家店全一样);
/// 招牌菜只有一道也占满一行(45px);62px 的缩略图配 109px 的右列,
/// **图下方空着 47px**。一屏只放得下 3.5 张。
///
/// 松散这种事没有报错。所以拿两个数字锁住:
/// 卡高不许再涨、图下不许再留空白。
void main() {
  // package_info_plus 在测试环境没有平台通道:`PackageInfo.fromPlatform()`
  // **不抛异常,是永远不返回**。ApiClient.loadAppBuild() 在请求前 await 它
  // (带 2 秒超时),于是用例结束时那个定时器还挂着 ——
  // 报的是「widget 树销毁后仍有 Timer」,和卡片本身无关。
  // 同样的坑 profile_view_test 里已经记过一次
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.chaojizan.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  void setPhoneViewport(WidgetTester t, Size logical) {
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = logical * 3.0;
    addTearDown(t.view.reset);
  }

  Map<String, dynamic> shop({
    String name = '牛牛牛杂',
    double? rating = 4.8,
    int sales = 128,
    int? avgSpend = 2000,
    List<Map<String, dynamic>> promos = const [
      {'type': 'full_cut', 'threshold_cents': 3000, 'off_cents': 100},
    ],
  }) =>
      {
        'id': 1,
        'name': name,
        'address': '测试路 1 号',
        'lat': 30.6598,
        'lng': 104.0810,
        'distance_m': 71,
        'is_open': true,
        'commission_rate': '0.05',
        'rating_avg': rating,
        'rating_count': rating == null ? 0 : 20,
        'monthly_sales': sales,
        'avg_spend_cents': avgSpend,
        'min_order_cents': 1500,
        'promo_rules': promos,
        'food_seal': true,
        'dine_in_status': 'yes',
        'dine_in_label': '有堂食',
        'kitchen_cam': false,
        'kitchen_cam_label': '无明厨亮灶',
        'top_dishes': const [],
      };

  ApiClient fakeApi(List<Map<String, dynamic>> shops) => ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          Object? payload;
          if (req.url.path == '/merchants') {
            payload = shops;
          } else {
            payload = req.url.path.endsWith('s') ? [] : {};
          }
          return http.Response(jsonEncode(payload), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      );

  Future<void> pump(WidgetTester t, List<Map<String, dynamic>> shops) async {
    SharedPreferences.setMockInitialValues({});
    setPhoneViewport(t, const Size(390, 844));
    // 传一个收货地址进去:没有它列表会等手机定位,而测试环境里
    // Geolocator 永远拿不到结果 —— 表现是列表一直空着,
    // 而所有断言都在报"找不到店名",看不出真正的原因
    final addr = Address.fromJson(const {
      'id': 1,
      'contact_name': '张三',
      'contact_phone': '13800000001',
      'address': '春熙路 1 号',
      'lat': 30.6598,
      'lng': 104.0810,
      'is_default': true,
    });
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(
          body: MerchantListView(api: fakeApi(shops), deliveryAddress: addr)),
    ));
    await t.pumpAndSettle();
    // 卡片渲染会打曝光埋点,埋点是 30 秒批量上报 —— 用例结束时那个
    // 定时器还挂着,测试框架会报「widget 树销毁后仍有 Timer」。
    // 埋点本身没错,是测试要负责收尾
    addTearDown(Analytics.resetSession);
  }

  /// 卡内的文字查找。
  ///
  /// ⚠️ **必须限定在卡里**。整页搜的话会误中:「5%」命中首页承诺条
  /// (「商家总负担 5% 封顶」),「月售」命中排序钮「月售优先」——
  /// 两次都让断言看起来失败,而卡本身是对的。
  Finder inCard(String text) => find.descendant(
      of: find.ancestor(
          of: find.text('牛牛牛杂'), matching: find.byType(Container)).last,
      matching: find.textContaining(text));

  /// 卡片外框的矩形(带底部发丝线的那个 Container)。
  Rect cardRect(WidgetTester t) {
    final f = find.ancestor(
        of: find.text('牛牛牛杂'), matching: find.byType(Container));
    for (final e in f.evaluate()) {
      final box = e.renderObject as RenderBox?;
      if (box == null || !box.hasSize) continue;
      final r = box.localToGlobal(Offset.zero) & box.size;
      if (r.width > 300) return r; // 通栏的那个才是卡
    }
    fail('找不到商家卡');
  }

  group('信息完整度', () {
    testWidgets('评分 / 月售 / 人均 / 起送 / 券 一个都不少', (t) async {
      await pump(t, [shop()]);
      for (final s in ['4.8', '月售 128', '人均 ¥20', '起送 ¥15', '满30减1']) {
        expect(inCard(s), findsWidgets, reason: '缺了「$s」');
      }
    });

    testWidgets('法定标识两种状态都要标(总局令 123 号)', (t) async {
      await pump(t, [shop()]);
      // 无明厨亮灶的店也要标出来 —— 法规要求标两种,不是只标有的
      expect(inCard('无明厨亮灶'), findsOneWidget);
      expect(inCard('有堂食'), findsOneWidget);
    });

    testWidgets('没有的如实写,不编', (t) async {
      await pump(t, [shop(rating: null, sales: 0, avgSpend: null, promos: [])]);
      expect(find.text('暂无评价'), findsOneWidget);
      expect(find.text('新店'), findsOneWidget);
      expect(inCard('月售'), findsNothing,
          reason: '零单不该写「月售 0」—— 那是在替新店宣布自己没生意');
    });

    testWidgets('「5% 封顶」不再出现在卡上', (t) async {
      await pump(t, [shop()]);
      expect(inCard('5%'), findsNothing,
          reason: '平台承诺不是店铺属性,每张卡重复一遍只是占地方');
    });
  });

  group('密度', () {
    testWidgets('一张卡不超过 130px', (t) async {
      await pump(t, [shop()]);
      final h = cardRect(t).height;
      expect(h, lessThanOrEqualTo(130),
          reason: '卡高 ${h.toStringAsFixed(0)}px。改版前是 182px,'
              '这一版的全部意义就是把它压下来');
    });

    testWidgets('图下不留空白:文字块不比图矮', (t) async {
      await pump(t, [shop()]);
      final img = t.getRect(find.byType(SzImage).first);
      expect(img.height, 100, reason: '缩略图应当是 100px 定高');
      // 文字块和图一样高 —— 这就是"横向不能超过图片"
      final card = cardRect(t);
      expect(card.height - img.height, lessThanOrEqualTo(26),
          reason: '卡比图高出 ${(card.height - img.height).toStringAsFixed(0)}px,'
              '超过上下内边距之和 —— 说明文字把卡撑高了,图旁边会留空');
    });

    testWidgets('内容再少,卡也不塌', (t) async {
      await pump(t, [shop(rating: null, sales: 0, avgSpend: null, promos: [])]);
      final h = cardRect(t).height;
      expect(h, greaterThanOrEqualTo(120),
          reason: '空数据的卡塌成 ${h.toStringAsFixed(0)}px,列表会参差不齐');
    });
  });
}
