import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/profile_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 骑手端「我的」页的**触控区下限**。
///
/// ## 这一端的密度有上限,和另外两端不一样
///
/// 顾客坐在沙发上用两只手看手机。商家站在柜台后面,屏幕是干的。
/// **骑手在路上:单手、可能戴着手套、屏幕上可能有雨、车还没停稳。**
/// 所以触控区只能更大不能更小。
///
/// 设计稿 5i 把原来那排 4 格网格去掉了,入口一律是整行的列表条 ——
/// 整行宽、至少 44 高,比 88px 宽的网格格子更好点。这里锁住三件事:
/// 没有网格回来、每一条可点的行不低于 44、窄屏大字下不切字不出界。
void main() {
  setUpRiderTest();

  Future<void> pump(WidgetTester t,
      {double scale = 1.0, double width = 390}) async {
    setPhoneViewport(t, Size(width, 2400));
    await t.pumpWidget(MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
            body: RiderProfilePage(
                api: fakeRiderApi(unread: 3),
                onOpenWallet: () {},
                onOpenOrders: () {})),
      ),
    ));
    await t.pumpAndSettle();
  }

  testWidgets('没有网格:入口都是整行的列表条', (t) async {
    await pump(t);
    expect(find.byType(SzIconGrid), findsNothing,
        reason: '网格回来了。要加入口请加成列表条 —— 88px 一格,戴手套点不中');
  });

  for (final width in [320.0, 390.0]) {
    for (final scale in [1.0, 1.4]) {
      testWidgets('每一条入口不低于 44 高 @$width ${scale}x', (t) async {
        await pump(t, width: width, scale: scale);
        final low = <String>[];
        for (final e in find.byType(SzEntryTile).evaluate()) {
          final h = (e.renderObject! as RenderBox).size.height;
          if (h < 44) low.add('${(e.widget as SzEntryTile).title}:${h.toStringAsFixed(0)}');
        }
        expect(low, isEmpty, reason: '这些入口矮于 44:$low');
        expect(t.takeException(), isNull);
        expect(textsPaintingOutside(t), isEmpty);
      });
    }
  }
}
