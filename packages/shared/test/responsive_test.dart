import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

import 'text_fit.dart';

/// 屏幕档位与自适应外壳(#295)。
///
/// ## 这个测试防的是什么
///
/// 三端是手机优先写的,web 和桌面上直接把手机布局拉宽 ——
/// 1440px 的浏览器里金刚区两格各 700px、底部导航横跨整屏、
/// 正文一行 90 多个汉字。
///
/// 响应式退化**不报错**:功能全对、测试全绿,只是在大屏上难用。
/// 所以拿行为锁住。
void main() {
  Future<void> pumpAt(WidgetTester t, double width, Widget child) async {
    setPhoneViewport(t, Size(width, 900));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: child,
    ));
    await t.pumpAndSettle();
  }

  const items = [
    SzNavItem(icon: Icons.home_outlined, selectedIcon: Icons.home, label: '首页'),
    SzNavItem(
        icon: Icons.receipt_outlined, selectedIcon: Icons.receipt, label: '订单'),
    SzNavItem(
        icon: Icons.person_outline, selectedIcon: Icons.person, label: '我的'),
  ];

  Widget shell({int selected = 0}) => SzNavScaffold(
        items: items,
        selectedIndex: selected,
        onSelected: (_) {},
        body: const Center(child: Text('内容')),
      );

  group('档位划分', () {
    test('按可用宽度分档,不按设备', () {
      // 判据永远是当前宽度 —— 同一个 web 页面可能在手机浏览器里打开,
      // 桌面窗口也可以拖到很窄
      expect(szWidthFor(375), SzWidth.compact); // 手机竖屏
      expect(szWidthFor(599), SzWidth.compact);
      expect(szWidthFor(600), SzWidth.medium); // 平板竖屏 / 手机横屏
      expect(szWidthFor(1023), SzWidth.medium);
      expect(szWidthFor(1024), SzWidth.expanded); // 平板横屏 / 桌面
      expect(szWidthFor(1920), SzWidth.expanded);
    });

    test('只有 compact 用底部导航', () {
      expect(SzWidth.compact.hasSideNav, isFalse);
      expect(SzWidth.medium.hasSideNav, isTrue);
      expect(SzWidth.expanded.hasSideNav, isTrue);
    });

    test('侧栏只在 expanded 展开文字', () {
      // medium(600–1023)通常是平板竖屏或拖窄的桌面窗口,
      // 展开的侧栏会吃掉本来就不多的横向空间
      expect(SzWidth.medium.sideNavExtended, isFalse);
      expect(SzWidth.expanded.sideNavExtended, isTrue);
    });
  });

  group('导航外壳按档切换', () {
    testWidgets('375 手机:底部导航,没有侧栏', (t) async {
      await pumpAt(t, 375, shell());
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.byType(NavigationRail), findsNothing);
    });

    testWidgets('768 平板竖屏:侧栏,没有底部导航', (t) async {
      await pumpAt(t, 768, shell());
      expect(find.byType(NavigationRail), findsOneWidget);
      expect(find.byType(NavigationBar), findsNothing,
          reason: '平板上还钉着底部导航 —— 那是给拇指设计的,不是给鼠标');
    });

    testWidgets('1440 桌面:侧栏展开', (t) async {
      await pumpAt(t, 1440, shell());
      final rail = t.widget<NavigationRail>(find.byType(NavigationRail));
      expect(rail.extended, isTrue);
    });

    testWidgets('768 的侧栏不展开文字', (t) async {
      await pumpAt(t, 768, shell());
      final rail = t.widget<NavigationRail>(find.byType(NavigationRail));
      expect(rail.extended, isFalse);
    });

    testWidgets('三个档位都不抛异常、不画出界', (t) async {
      for (final w in [375.0, 600.0, 768.0, 1024.0, 1440.0, 1920.0]) {
        await pumpAt(t, w, shell());
        expect(t.takeException(), isNull, reason: '${w.toInt()}px 下渲染抛异常');
        expect(textsPaintingOutside(t), isEmpty,
            reason: '${w.toInt()}px 下有字画出界');
      }
    });

    testWidgets('切换回调在两种形态下都通', (t) async {
      for (final w in [375.0, 1440.0]) {
        var picked = -1;
        setPhoneViewport(t, Size(w, 900));
        await t.pumpWidget(MaterialApp(
          theme: brandTheme(Brightness.light),
          home: SzNavScaffold(
            items: items,
            selectedIndex: 0,
            onSelected: (i) => picked = i,
            body: const SizedBox(),
          ),
        ));
        await t.pumpAndSettle();
        await t.tap(find.text('订单'));
        await t.pumpAndSettle();
        expect(picked, 1, reason: '${w.toInt()}px 下点导航没回调');
      }
    });
  });

  group('内容限宽', () {
    testWidgets('宽屏上限住,窄屏上不干预', (t) async {
      // 窄屏:maxWidth 大于可用宽度,ConstrainedBox 不生效 ——
      // 所以可以无脑套在页面外面,不用自己判断档位
      final child = Container(color: Colors.red, height: 20);
      await pumpAt(t, 375,
          Scaffold(body: SzContentWidth(child: child)));
      expect(t.getSize(find.byWidget(child)).width, 375);

      await pumpAt(t, 1440,
          Scaffold(body: SzContentWidth(child: child)));
      expect(t.getSize(find.byWidget(child)).width, kContentMaxWidth,
          reason: '宽屏上内容没限宽 —— 一行汉字超过 40 个就会跳行');
    });

    testWidgets('三档最大宽度依次放宽', (t) async {
      // 不同内容形态需要不同的宽度上限:
      // 正文要短行才好读,卡片流可以并排,看板要放图表
      expect(kContentMaxWidth, lessThan(kFeedMaxWidth));
      expect(kFeedMaxWidth, lessThan(kWideMaxWidth));
      expect(kContentMaxWidth, lessThanOrEqualTo(760),
          reason: '单列内容超过 760 宽,一行汉字就超过 40 个了');
    });
  });
}
