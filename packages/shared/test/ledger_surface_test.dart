import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 账目台面(#133)。
///
/// 守的核心是那条**约定**:台面内部把 SzColors 整个换掉,
/// 子组件照常读 `Theme.of(context).sz.ink` 就能拿到适配深底的颜色。
/// 一旦这条断了,台面里就是黑底黑字 —— 而且不会有任何编译错误。
void main() {
  Widget wrap(Widget child, Brightness b) => MaterialApp(
        theme: brandTheme(b),
        home: Scaffold(body: Center(child: child)),
      );

  for (final b in [Brightness.light, Brightness.dark]) {
    final label = b == Brightness.light ? '浅色' : '深色';

    testWidgets('$label:台面内的令牌被换成适配深底的一套', (tester) async {
      late SzColors inside;
      await tester.pumpWidget(wrap(
          SzLedgerCard(child: Builder(builder: (c) {
            inside = Theme.of(c).sz;
            return const SizedBox();
          })),
          b));

      // 台面底 = ledger,而不是页面的 surface
      final page = b == Brightness.light ? SzColors.light : SzColors.dark;
      expect(inside.surface, page.ledger);

      // 正文必须是浅色 —— 深底上用页面的墨色就是黑底黑字
      expect(inside.ink, SzColors.dark.ink);

      // 语义色取深色态亮版:浅色态的墨绿墨褐压在深底上读不出来
      expect(inside.earn, SzColors.dark.earn);
      expect(inside.hold, SzColors.dark.hold);
    });

    testWidgets('$label:裸 Text 不带颜色时也不会是黑底黑字', (tester) async {
      await tester.pumpWidget(wrap(
          const SzLedgerCard(child: Text('分账明细')), b));
      final t = tester.widget<Text>(find.text('分账明细'));
      final style = DefaultTextStyle.of(
              tester.element(find.text('分账明细')))
          .style;
      expect(t.style?.color ?? style.color, isNotNull);
      expect(t.style?.color ?? style.color, SzColors.dark.ink);
    });
  }

  testWidgets('深色页上补了边框(明度差只有 1.10,光靠颜色分不出两层)',
      (tester) async {
    await tester.pumpWidget(wrap(const SzLedgerCard(child: Text('x')),
        Brightness.dark));
    final box = tester.widget<Container>(find.byType(Container).first);
    final deco = box.decoration as BoxDecoration;
    expect(deco.border, isNotNull, reason: '深色下没有边界,台面会糊进页底');
  });

  testWidgets('浅色页上不需要边框(反差已有 14.35)', (tester) async {
    await tester.pumpWidget(wrap(const SzLedgerCard(child: Text('x')),
        Brightness.light));
    final box = tester.widget<Container>(find.byType(Container).first);
    expect((box.decoration as BoxDecoration).border, isNull);
  });

  testWidgets('可点的台面能触发回调', (tester) async {
    var tapped = false;
    await tester.pumpWidget(wrap(
        SzLedgerCard(onTap: () => tapped = true, child: const Text('分账')),
        Brightness.light));
    await tester.tap(find.text('分账'));
    expect(tapped, isTrue);
  });

  group('分账行的钱色语义(#133)', () {
    Future<Color> amountColor(WidgetTester tester, Widget row) async {
      await tester.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(body: SzLedgerCard(child: row)),
      ));
      // 台面里最大的那段金额就是这一行的钱
      final texts = tester.widgetList<Text>(find.byType(Text)).where(
          (t) => (t.data ?? '').contains('¥'));
      return texts.last.style!.color!;
    }

    testWidgets('平台留存走 hold,不走 earn', (tester) async {
      final c = await amountColor(
          tester,
          const SzFeeRow(
              label: '平台佣金', amountCents: 58350, negative: true, isHold: true));
      expect(c, SzColors.dark.hold,
          reason: '佣金是被抽走的钱,染成 earn 绿等于说"抽你的钱是好事"');
      expect(c, isNot(SzColors.dark.earn));
    });

    testWidgets('用户省下的钱仍然走 earn', (tester) async {
      final c = await amountColor(tester,
          const SzFeeRow(label: '满减优惠', amountCents: 500, negative: true));
      expect(c, SzColors.dark.earn, reason: '满减是用户省下的,绿色没错');
    });

    testWidgets('普通流水行既不是 earn 也不是 hold', (tester) async {
      final c = await amountColor(
          tester, const SzFeeRow(label: '菜品流水', amountCents: 1196680));
      expect(c, SzColors.dark.ink);
    });
  });
}
