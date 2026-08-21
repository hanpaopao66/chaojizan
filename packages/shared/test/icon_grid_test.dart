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

  group('宽屏重排:列数不能等于 items 长度写死', () {
    // 商家端「店铺」页有 10 个跳转型入口。窄屏排 2 行 × 5 列;
    // 宽屏(≥600)如果还是 5 列一行,1080px 下每格 216px ——
    // 一个 40px 的图标居中飘着,两侧各 88px 空白,看着像图标掉队了。
    //
    // ⚠️ 列数**不会**自己跟着宽度变:SzIconGrid 是 Row + Expanded,
    // 不给 columns 就等于 items.length。判据是可用宽度不是平台(见 responsive.dart)
    List<SzIconGridItem> tools() => const [
          SzIconGridItem(icon: Icons.circle, label: '券核销'),
          SzIconGridItem(icon: Icons.circle, label: '店铺券'),
          SzIconGridItem(icon: Icons.circle, label: '团购券'),
          SzIconGridItem(icon: Icons.circle, label: '小票打印'),
          SzIconGridItem(icon: Icons.circle, label: '经营看板'),
          SzIconGridItem(icon: Icons.circle, label: '老客召回'),
          SzIconGridItem(icon: Icons.circle, label: '专属码'),
          SzIconGridItem(icon: Icons.circle, label: '消息'),
          SzIconGridItem(icon: Icons.circle, label: '客服'),
          SzIconGridItem(icon: Icons.circle, label: '判责申诉'),
        ];

    testWidgets('10 格一行:medium 最窄处(内容宽 488)不切字、不出界',
        (t) async {
      // 600 的平板竖屏减去 NavigationRail(约 80)和页面内边距(32)
      final h = await heightOf(t, SzIconGrid(items: tools(), columns: 10),
          screen: 520);
      expect(truncatedTexts(t), isEmpty,
          reason: '标签被切了。给 maxLines:2 让它换行,别用 ellipsis 省事');
      expect(textsPaintingOutside(t), isEmpty);
      expect(h, lessThanOrEqualTo(120),
          reason: '一行 10 格涨到 ${h.toStringAsFixed(0)}px 了');
    });

    testWidgets('10 格一行 + 长辈版 1.4×:仍不切字不出界', (t) async {
      await heightOf(t, SzIconGrid(items: tools(), columns: 10),
          screen: 520, scale: 1.4);
      expect(t.takeException(), isNull);
      expect(truncatedTexts(t), isEmpty);
      expect(textsPaintingOutside(t), isEmpty);
    });

    testWidgets('columns 比 items 少时补空位,不把最后一格拉宽', (t) async {
      // 7 个格子排 5 列 = 两行,第二行只有 2 个。如果不补空位,
      // 那 2 个会各占半行宽 —— 和上一行对不齐,看着像布局坏了
      await heightOf(
          t,
          SzIconGrid(items: tools().sublist(0, 7), columns: 5),
          screen: 390);
      final cells = t
          .widgetList<Expanded>(find.descendant(
              of: find.byType(SzIconGrid), matching: find.byType(Expanded)))
          .length;
      expect(cells, 10, reason: '7 个格子排 5 列该占满 2 行 10 个位置(3 个空位)');
    });

    testWidgets('不给 columns 时行为不变 —— 老调用点一个不用改', (t) async {
      final a = await heightOf(t, orders());
      final b = await heightOf(t, SzIconGrid(items: orders().items, columns: 4));
      expect(a, b);
    });
  });
}
