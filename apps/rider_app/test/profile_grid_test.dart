import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rider_app/profile_page.dart';
import 'package:superz_shared/superz_shared.dart';

import 'rider_fake_api.dart';

/// 骑手端网格的**触控区下限**(#297)。
///
/// ## 这一端的密度有上限,和另外两端不一样
///
/// 顾客坐在沙发上用两只手看手机。商家站在柜台后面,屏幕是干的。
/// **骑手在路上:单手、可能戴着手套、屏幕上可能有雨、车还没停稳。**
///
/// 所以「一屏塞更多入口」这件事在这一端有一条硬底线 ——
/// 触控区**要更大而不是更小**。用户端那轮的结论(网格密度是列表的两倍,
/// 所以能塞就塞)在这里只成立到 4 格为止:
///
/// | 列数 | 390 屏每格 | 320 屏每格 |
/// |---|---|---|
/// | 3 格 | 118 × 74 | 95 × 74 |
/// | **4 格** | **88.5 × 74** | **71 × 74** |
/// | 5 格 | 70.8 × 74 | 56.8 × 74 |
///
/// 5 格在 390 上就已经掉到 320 屏 4 格的水平,再窄一档就低于
/// Material 的 48×48 最小触控区了。**所以 4 格是底,不许再加。**
///
/// ## 为什么要有这条断言
///
/// 因为它是唯一拦得住下一个人的东西。
///
/// 「再加一个入口嘛,反正一行放得下」——这句话本身没有错,
/// 布局不会报错、截图看着也正常、所有别的测试都是绿的。
/// 只有戴着手套在雨里点不中的那个骑手知道出了问题,
/// 而他不会来提 issue,他只会点第三次。
///
/// 同理**不许把网格套进 `SzCard`**:卡的 14px 横向内边距会把每格
/// 从 88.5 压到 81.5,高度从 82 涨到 110 —— 为了一个边框
/// 既缩了触控区又多占了地方。
void main() {
  setUpRiderTest();

  Future<void> pump(WidgetTester t,
      {double scale = 1.0, double width = 390}) async {
    setPhoneViewport(t, Size(width, 844));
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

  SzIconGrid theGrid(WidgetTester t) =>
      t.widget<SzIconGrid>(find.byType(SzIconGrid));

  /// 网格里一格的实际渲染尺寸。
  Size cellSize(WidgetTester t) {
    final cell = find.descendant(
        of: find.byType(SzIconGrid), matching: find.byType(InkWell));
    expect(cell, findsWidgets);
    return t.getSize(cell.first);
  }

  group('列数:4 格是底,不许再加', () {
    testWidgets('恰好 4 格', (t) async {
      await pump(t);
      expect(theGrid(t).items.length, 4,
          reason: '网格格子数变了。5 格在 390 上每格只剩 70.8px —— '
              '骑手戴着手套点不中。要加入口请加成列表条,别挤网格');
    });

    testWidgets('不给 columns —— 一行放完,不折行', (t) async {
      await pump(t);
      expect(theGrid(t).columns, isNull);
    });
  });

  group('触控区下限', () {
    testWidgets('390 屏:每格不小于 80 × 70', (t) async {
      await pump(t);
      final s = cellSize(t);
      expect(s.width, greaterThanOrEqualTo(80),
          reason: '每格只剩 ${s.width.toStringAsFixed(1)}px 宽');
      expect(s.height, greaterThanOrEqualTo(70),
          reason: '每格只剩 ${s.height.toStringAsFixed(1)}px 高');
    });

    testWidgets('320 窄屏:每格仍不小于 64 × 70(Material 最小触控区是 48)', (t) async {
      await pump(t, width: 320);
      final s = cellSize(t);
      expect(s.width, greaterThanOrEqualTo(64),
          reason: '320 屏上每格只剩 ${s.width.toStringAsFixed(1)}px —— '
              '这已经是最坏情况了,再小就该改成 3 格');
      expect(s.height, greaterThanOrEqualTo(70));
    });

    testWidgets('长辈版 1.4× 下触控区只会变大不会变小', (t) async {
      await pump(t, scale: 1.4);
      final s = cellSize(t);
      expect(s.height, greaterThanOrEqualTo(70));
    });
  });

  group('不套卡', () {
    testWidgets('网格外面没有 SzCard', (t) async {
      await pump(t);
      expect(
          find.ancestor(
              of: find.byType(SzIconGrid), matching: find.byType(SzCard)),
          findsNothing,
          reason: '网格被套进 SzCard 了 —— 每格从 88.5 压到 81.5,'
              '高度从 82 涨到 110。为一个边框既缩触控区又多占地方');
    });
  });

  group('窄屏 + 长辈版:标签换行,不切字', () {
    testWidgets('320 屏 1.4× 下没有标签被切成省略号', (t) async {
      await pump(t, scale: 1.4, width: 320);
      // 四个字的标签(「我的订单」「哪儿有单」「顾客评价」)在 320@1.4×
      // 一行放不下。允许折成两行,**不允许**切成「我的…」——
      // 四个字切掉一半的入口等于没写(channel_grid.dart 的教训)
      final truncated = <String>[
        for (final e in find
            .descendant(
                of: find.byType(SzIconGrid), matching: find.byType(Text))
            .evaluate())
          if ((e.renderObject! as RenderParagraph).didExceedMaxLines)
            (e.widget as Text).data ?? '',
      ];
      expect(truncated, isEmpty, reason: '网格标签被切了:$truncated');
    });

    testWidgets('320 屏 1.4× 下不画出界', (t) async {
      await pump(t, scale: 1.4, width: 320);
      expect(t.takeException(), isNull);
      expect(textsPaintingOutside(t), isEmpty);
    });
  });

  group('进网格的必须是「说不出状态值」的那一档', () {
    testWidgets('四个标签都不超过四个字', (t) async {
      // 标题两三个字就说清、给不出状态值、彼此平级 —— 这才是网格那一档。
      // 需要一句说明或者有状态值的,该留在 SzEntryTile
      await pump(t);
      for (final it in theGrid(t).items) {
        expect(it.label.length, lessThanOrEqualTo(4),
            reason: '「${it.label}」太长了,它该是列表条不是网格格子');
      }
    });
  });
}
