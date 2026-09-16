/// 底部导航上方的常驻条(DEV-PROMPTS-41 I5):音乐放歌时把迷你播放条放进 szAboveNavSlot,
/// 走到哪一格都跟着;不放歌时插槽是空的,一点地方都不占。
///
/// 这里测的是**外壳的行为**:外壳不认识音乐模块,只画插槽里的东西 —— 换成别的模块(通话悬浮条)也一样。
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/main.dart' show superZTheme;

void main() {
  tearDown(() => szAboveNavSlot.value = null);

  Future<void> pump(WidgetTester tester, {double width = 390}) async {
    tester.view
      ..devicePixelRatio = 1
      ..physicalSize = Size(width, 900);
    addTearDown(tester.view.reset);
    await tester.pumpWidget(MaterialApp(
      theme: superZTheme(Brightness.light),
      home: ValueListenableBuilder<Widget?>(
        valueListenable: szAboveNavSlot,
        builder: (ctx, slot, _) => SzNavScaffold(
          selectedIndex: 0,
          onSelected: (_) {},
          aboveNav: slot,
          items: const [
            SzNavItem(icon: Icons.home_outlined, selectedIcon: Icons.home, label: '首页'),
            SzNavItem(icon: Icons.person_outline, selectedIcon: Icons.person, label: '我的'),
          ],
          body: const Center(child: Text('内容')),
        ),
      ),
    ));
    await tester.pumpAndSettle();
  }

  testWidgets('插槽空着:底栏就是底栏,没有多余的条', (tester) async {
    await pump(tester);
    expect(find.text('内容'), findsOneWidget);
    expect(find.text('迷你条'), findsNothing);
  });

  testWidgets('放进去就出现在底栏上方,收走就没了', (tester) async {
    await pump(tester);
    szAboveNavSlot.value = const SizedBox(height: 56, child: Center(child: Text('迷你条')));
    await tester.pumpAndSettle();
    expect(find.text('迷你条'), findsOneWidget);

    final bar = tester.getRect(find.text('迷你条'));
    final nav = tester.getRect(find.text('首页'));
    expect(bar.bottom, lessThanOrEqualTo(nav.top), reason: '条子在底部导航上方');

    szAboveNavSlot.value = null;
    await tester.pumpAndSettle();
    expect(find.text('迷你条'), findsNothing);
  });

  testWidgets('宽屏(侧栏)时也在,贴在内容那一列底下', (tester) async {
    await pump(tester, width: 1200);
    szAboveNavSlot.value = const SizedBox(height: 56, child: Center(child: Text('迷你条')));
    await tester.pumpAndSettle();
    expect(find.text('迷你条'), findsOneWidget);
    final bar = tester.getRect(find.text('迷你条'));
    final body = tester.getRect(find.text('内容'));
    expect(bar.top, greaterThan(body.top), reason: '在内容下面');
  });
}
