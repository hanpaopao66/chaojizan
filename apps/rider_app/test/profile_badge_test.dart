import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/profile_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 「我的」页只有一处数字:消息的未读数。
///
/// ## 为什么只有它
///
/// 未读数是服务端 COUNT,和分页无关,是真的「有几条等你看」。其余候选:
/// - 意外保障:今天没有登记行意味着"今天还没上过线",不是"没保障",
///   挂上去会每天早上误报一次;
/// - 实名 / 结算卡 / 培训:它们是**状态**不是**几件待办**,
///   「未登记」比一个红点有信息量,所以写成带色的状态字。
///
/// 设计稿 5i 之后未读数不再是网格角上的红色 Badge,而是消息那一行
/// 右边的「N 条未读」(clay 色)—— 不是报警,是一件等着看的事。
void main() {
  setUpRiderTest();

  Future<void> pump(WidgetTester t, ApiClient api) async {
    setPhoneViewport(t, const Size(390, 2400));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(
          body: RiderProfilePage(
              api: api, onOpenWallet: () {}, onOpenOrders: () {})),
    ));
    await t.pumpAndSettle();
  }

  SzEntryTile tile(WidgetTester t, String title) => t.widget<SzEntryTile>(
      find.byWidgetPredicate((w) => w is SzEntryTile && w.title == title));

  testWidgets('全页没有红色 Badge', (t) async {
    await pump(t, fakeRiderApi(unread: 5));
    expect(find.byType(Badge), findsNothing);
  });

  group('消息那一行', () {
    testWidgets('有未读:写「3 条未读」', (t) async {
      await pump(t, fakeRiderApi(unread: 3));
      expect(tile(t, '消息').value, '3 条未读');
    });

    testWidgets('未读为 0:什么都不写', (t) async {
      await pump(t, fakeRiderApi(unread: 0));
      expect(tile(t, '消息').value, isNull);
    });

    testWidgets('未读数拉不到:当 0,入口照常在', (t) async {
      await pump(t, fakeRiderApi(failing: {'/riders/me/messages'}));
      expect(tile(t, '消息').value, isNull);
    });

    testWidgets('未读很多:写 20+,不写猜出来的数', (t) async {
      await pump(t, fakeRiderApi(unread: 57));
      expect(tile(t, '消息').value, '20+ 条未读');
    });
  });

  testWidgets('除了消息,别的入口都不挂数字', (t) async {
    await pump(t, fakeRiderApi(unread: 5));
    final numbered = <String>[
      for (final e in find.byType(SzEntryTile).evaluate())
        if (((e.widget as SzEntryTile).value ?? '').contains(RegExp(r'\d')) &&
            (e.widget as SzEntryTile).title != '消息')
          (e.widget as SzEntryTile).title,
    ];
    expect(numbered, isEmpty, reason: '这些入口挂了数字:$numbered');
  });

  testWidgets('开工准备的三件事用带色状态字,不用数字', (t) async {
    await pump(
        t,
        fakeRiderApi(
            unread: 0,
            verifyStatus: 'unsubmitted',
            payoutConfigured: false,
            examPassed: false));
    expect(find.text('去提交'), findsOneWidget);
    expect(find.text('未登记'), findsOneWidget);
    expect(find.text('未通过'), findsWidgets);
    expect(find.byType(Badge), findsNothing);
  });
}
