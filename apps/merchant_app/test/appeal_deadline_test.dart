import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/appeal_page.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'shop_fake_api.dart';

/// 申诉的 72 小时窗口必须是**进门就看见**的。
///
/// 店铺页把「判责申诉」收进了图标网格,格子里放不下副标题 ——
/// 原来那句 hint「对售后判责或差评有异议?72 小时内申诉」跟着没了。
/// **时限不是目录式说明,砍不得**:错过窗口就再也申诉不了,
/// 而它原来是商家在入口上第一眼看到的东西。
///
/// 这一页本来就有这句话,但在**最底下**,两个列表之后。
/// 商家从网格点进来,第一屏看到的是「没有判商家责任的售后记录」,
/// 翻到底才知道有个 72 小时。挪到顶上。
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

  testWidgets('72 小时窗口在第一屏,而且排在两个列表之前', (t) async {
    final api = shopFakeApi();
    await api.login('13800000009', 'pw');
    t.view
      ..devicePixelRatio = 3.0
      ..physicalSize = const Size(390, 844) * 3.0;
    addTearDown(t.view.reset);
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light, density: SzDensity.operate),
      home: MerchantAppealPage(api: api),
    ));
    await t.pumpAndSettle();

    final deadline = find.textContaining('72 小时');
    expect(deadline, findsOneWidget, reason: '时限文案不见了');

    double topOf(Finder f) {
      final box = t.renderObject<RenderBox>(f);
      return (box.localToGlobal(Offset.zero) & box.size).top;
    }

    expect(topOf(deadline), lessThan(topOf(find.text('已退款的售后(判商家责任)'))),
        reason: '时限还在页尾 —— 商家翻到底才知道有个窗口期');
    expect(topOf(deadline), lessThan(400),
        reason: '时限不在第一屏');
  });
}
