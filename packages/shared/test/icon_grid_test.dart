import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

import 'text_fit.dart';

/// 图标网格的密度与窄屏行为(#296)。
///
/// ## 这个组件解决什么
///
/// `SzEntryTile` 一条 46px,只有 hint 的 63px —— 那是给「需要一句说明」
/// 或者「有状态值可显示」的入口用的。但有一类入口两样都给不出:
/// 标题两三个字就说清了(优惠券、我的收藏、待评价),彼此完全平级。
/// 这类东西排成竖列是浪费:一条 46px 只放一个词。
///
/// 网格把它们横过来:四个入口 ≤100px,合下来 25px 一个,
/// **密度是列表条的两倍**。这不是推翻 SzEntryTile,是给它补上
/// 「说不出状态值」的那一档。
///
/// ## 为什么要有测试
///
/// 网格最容易坏在窄屏 + 长辈版:一格只有 58px 宽,而「退款售后」
/// 四个字在 1.4× 下要 64px。`channel_grid.dart` 已经踩过一次
/// (那次是画到隔壁格子上,不报错也不留痕),这里把判据固定下来。
void main() {
  Future<double> heightOf(WidgetTester t, Widget w,
      {double scale = 1.0, double screen = 390}) async {
    setPhoneViewport(t, Size(screen, 844));
    await t.pumpWidget(MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(scale)),
      child: MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
          body: Align(
            alignment: Alignment.topCenter,
            child: SizedBox(width: screen - 32, child: w),
          ),
        ),
      ),
    ));
    await t.pumpAndSettle();
    return t.getSize(find.byWidget(w)).height;
  }

  // 「我的」页订单区那四格:最长的标签是「退款售后」
  SzIconGrid orders({int pending = 0, int active = 0, int toReview = 0}) =>
      SzIconGrid(items: [
        SzIconGridItem(
            icon: Icons.account_balance_wallet_outlined,
            label: '待支付',
            badge: pending,
            onTap: () {}),
        SzIconGridItem(
            icon: Icons.local_shipping_outlined,
            label: '进行中',
            badge: active,
            onTap: () {}),
        SzIconGridItem(
            icon: Icons.rate_review_outlined,
            label: '待评价',
            badge: toReview,
            onTap: () {}),
        SzIconGridItem(
            icon: Icons.assignment_return_outlined,
            label: '退款售后',
            onTap: () {}),
      ]);

  group('密度', () {
    testWidgets('四个入口不超过 100px —— 合下来 25px 一个,是列表条的两倍密',
        (t) async {
      final h = await heightOf(t, orders());
      expect(h, lessThanOrEqualTo(100),
          reason: '网格长回去了(当前 ${h.toStringAsFixed(0)}px)。'
              '四条 SzEntryTile 是 184px,网格再涨就没有理由存在了');
    });

    testWidgets('角标不额外占高度', (t) async {
      final bare = await heightOf(t, orders());
      final badged = await heightOf(t, orders(pending: 3, active: 12));
      expect(badged, bare, reason: '角标把行顶高了 —— 它该浮在图标角上');
    });
  });

  group('窄屏 + 长辈版:标签换行,不切字', () {
    testWidgets('320 屏 1.4× 下没有标签被切成省略号', (t) async {
      await heightOf(t, orders(pending: 1), scale: 1.4, screen: 320);
      // 「退款售后」在 320@1.4× 下一格只有 60px 出头,一行放不下。
      // 允许它折成两行,**不允许**切成「退款…」——
      // 四个字切掉一半的入口等于没写(channel_grid.dart 同样的教训)
      expect(truncatedTexts(t), isEmpty,
          reason: '标签被切了。给 maxLines:2 让它换行,别用 ellipsis 省事');
    });

    testWidgets('320 屏 1.4× 下不画出界', (t) async {
      await heightOf(t, orders(pending: 1), scale: 1.4, screen: 320);
      expect(t.takeException(), isNull);
      expect(textsPaintingOutside(t), isEmpty);
    });

    testWidgets('390 屏 1.4× 下也不切不溢出', (t) async {
      await heightOf(t, orders(pending: 1, toReview: 2), scale: 1.4);
      expect(truncatedTexts(t), isEmpty);
      expect(textsPaintingOutside(t), isEmpty);
    });
  });

  group('角标', () {
    testWidgets('0 不显示', (t) async {
      await heightOf(t, orders());
      expect(find.text('0'), findsNothing);
    });

    testWidgets('非 0 显示数字', (t) async {
      await heightOf(t, orders(pending: 2, toReview: 7));
      expect(find.text('2'), findsOneWidget);
      expect(find.text('7'), findsOneWidget);
    });
  });
}
