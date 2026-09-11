import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/main.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'order_fake_api.dart';
import 'real_fonts.dart';
import 'shop_fake_api.dart';

/// 待接单卡的高度(#33 4.1 第 4 点的收益:首屏多放一张待接单卡)。
///
/// 从 order_tab_test.dart 挪出来单独成文件,因为它要**装真字体**量:
/// 测试默认字体里拉丁字母一个字一个 em 宽,「菜价 ¥34.00 − 4.5%」在那种字体下
/// 折成三行,卡会高出 30px —— 那张卡在真机上不存在。
/// 字体一装就是整个测试进程,所以不和那边的窄屏溢出检查放一起
/// (那几条故意用偏宽的默认字体,算是悲观检查)。
void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'merchant_app',
      packageName: 'com.superz.merchant',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
    await loadRealFonts();
  });
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('390 窄屏上待接单卡不超过 180', (t) async {
    final api = orderFakeApi(
      pages: [orderJson(no: 'SZ0001', remark: '不要香菜,面硬一点')],
      todos: {'pending_orders': 1},
    );
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MaterialApp(
      theme:
          brandTheme(Brightness.light, density: SzDensity.operate, accentTone: 0),
      home: MerchantHomePage(api: api, shop: Merchant.fromJson(shopJson())),
    ));
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
    await t.tap(find.descendant(
        of: find.byType(NavigationBar), matching: find.text('订单')));
    await t.pump();
    await t.pump(const Duration(milliseconds: 600));

    // 卡片是订单列表里那个带描边的 Container,取第一张的高度。
    // 0294c4a 把动作行换成 Wrap 之后窄屏上它是 238;方案要求回到 180 以下。
    // 2026-09 换成设计稿 6a 的卡(编号 + 时刻 | 等了多久、菜、备注、
    // 钱 | 拒单 接单)之后实测约 156
    final card = find
        .descendant(
            of: find.byType(RefreshIndicator), matching: find.byType(Container))
        .evaluate()
        .map((e) => e.renderObject as RenderBox?)
        .where((b) => b != null && b.hasSize && b.size.height > 60)
        .map((b) => b!.size.height)
        .toList();
    expect(card, isNotEmpty, reason: '没找到订单卡');
    // 设计稿上这张卡约 132,差的那 20 多 px 在按钮的触控高度上(视觉 32、
    // 点击区 48)。要拿到就得缩触控区 —— 干活页不干这事(同 shop_tab
    // 「带开关的入口条不超过 72px,不许缩触控区」那条)
    expect(card.first, lessThanOrEqualTo(180),
        reason: '待接单卡 ${card.first}px —— 钱和按钮又挤成两行了,'
            '这一点的收益(首屏多放一张)就没拿到');
    expect(t.takeException(), isNull);
    await t.pumpWidget(const SizedBox());
    await t.pump();
  });
}
