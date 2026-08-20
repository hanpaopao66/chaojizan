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

  group('自适应弹层', () {
    Future<void> open(WidgetTester t, double width) async {
      setPhoneViewport(t, Size(width, 900));
      await t.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Builder(
          builder: (ctx) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () => szShowSheet<void>(
                    context: ctx,
                    builder: (_) => const SizedBox(
                        height: 200, child: Center(child: Text('弹层内容')))),
                child: const Text('打开'),
              ),
            ),
          ),
        ),
      ));
      await t.pumpAndSettle();
      await t.tap(find.text('打开'));
      await t.pumpAndSettle();
    }

    testWidgets('375 手机:底部弹层', (t) async {
      await open(t, 375);
      expect(find.byType(BottomSheet), findsOneWidget);
      expect(find.byType(Dialog), findsNothing);
    });

    testWidgets('1440 桌面:居中对话框', (t) async {
      await open(t, 1440);
      expect(find.byType(Dialog), findsOneWidget);
      expect(find.byType(BottomSheet), findsNothing,
          reason: '桌面上还是底部弹层 —— 那会变成横贯屏底的一条长条,'
              '内容在左边一小块,而视线在屏幕中央');
    });

    testWidgets('对话框收得住宽度,不铺满', (t) async {
      await open(t, 1440);
      // ⚠️ 量的是白底那层 Material,不是 `find.byType(Dialog)` ——
      // Dialog 的 RenderBox 是它外面那层 padding 盒,**永远等于屏宽**。
      // 我第一次拿它做断言,量出 1440 以为没限住,差点去改一段本来对的代码。
      final surface = find
          .descendant(of: find.byType(Dialog), matching: find.byType(Material))
          .first;
      final w = t.getSize(surface).width;
      expect(w, lessThanOrEqualTo(kContentMaxWidth),
          reason: '对话框白底横跨了整个 1440(实际 ${w.toStringAsFixed(0)})');
      expect(w, greaterThan(300), reason: '对话框窄成一条 —— 多半是被内容撑没了');
    });

    testWidgets('两种形态都能拿到返回值', (t) async {
      for (final w in [375.0, 1440.0]) {
        String? got;
        setPhoneViewport(t, Size(w, 900));
        await t.pumpWidget(MaterialApp(
          theme: brandTheme(Brightness.light),
          home: Builder(
            builder: (ctx) => Scaffold(
              body: Center(
                child: TextButton(
                  onPressed: () async {
                    got = await szShowSheet<String>(
                      context: ctx,
                      builder: (sheetCtx) => TextButton(
                        onPressed: () => Navigator.pop(sheetCtx, '选了'),
                        child: const Text('选它'),
                      ),
                    );
                  },
                  child: const Text('打开'),
                ),
              ),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.tap(find.text('打开'));
        await t.pumpAndSettle();
        await t.tap(find.text('选它'));
        await t.pumpAndSettle();
        expect(got, '选了', reason: '${w.toInt()}px 下弹层没回传值');
      }
    });

    testWidgets('对话框里的 SafeArea 不补边距,底部弹层里照补', (t) async {
      // builder 是照底部弹层写的(带 SafeArea),两种形态共用一份代码。
      // 对话框浮在屏幕中间,离刘海和小白条都远,再补 34px 只是一条白边
      Future<double> gap(double width) async {
        setPhoneViewport(t, Size(width, 900));
        t.view.padding =
            const FakeViewPadding(bottom: 34 * 3, top: 47 * 3);
        final inner = Container(height: 40, color: Colors.red);
        await t.pumpWidget(MaterialApp(
          // ⚠️ key 必须跟着宽度变:pumpWidget 会复用 element 树,
          // Navigator 的路由栈也跟着留下来 —— 上一轮的弹层没关,
          // 下一轮点"打开"点的是它盖住的地方
          key: ValueKey(width),
          theme: brandTheme(Brightness.light),
          home: Builder(
            builder: (ctx) => Scaffold(
              body: Center(
                child: TextButton(
                  onPressed: () => szShowSheet<void>(
                      context: ctx,
                      builder: (_) => SafeArea(child: inner)),
                  child: const Text('打开'),
                ),
              ),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.tap(find.text('打开'));
        await t.pumpAndSettle();
        final safe = t.getSize(find.byType(SafeArea).last).height;
        return safe - t.getSize(find.byWidget(inner)).height;
      }

      expect(await gap(1440), 0,
          reason: '对话框底下多了一条 34px 的白边');
      expect(await gap(375), greaterThan(0),
          reason: '底部弹层反而不避让小白条了 —— 内容会被系统手势条压住');
    });

    testWidgets('拖拽条:底部弹层听主题的,对话框一律不画', (t) async {
      // brandTheme 的 bottomSheetTheme 全局开了拖拽条。helper 的
      // showDragHandle 必须**可空** —— 写死 false 会显式覆盖主题,
      // 把三端的拖拽条一起关掉。这条断言就是防这个
      Future<int> handles(double width, {bool? flag}) async {
        setPhoneViewport(t, Size(width, 900));
        await t.pumpWidget(MaterialApp(
          key: ValueKey('$width-$flag'),
          theme: brandTheme(Brightness.light),
          home: Builder(
            builder: (ctx) => Scaffold(
              body: Center(
                child: TextButton(
                  onPressed: () => szShowSheet<void>(
                      context: ctx,
                      showDragHandle: flag,
                      builder: (_) =>
                          const SizedBox(height: 120, child: Text('内容'))),
                  child: const Text('打开'),
                ),
              ),
            ),
          ),
        ));
        await t.pumpAndSettle();
        await t.tap(find.text('打开'));
        await t.pumpAndSettle();
        return find
            .byWidgetPredicate(
                (w) => w.runtimeType.toString().contains('DragHandle'))
            .evaluate()
            .length;
      }

      expect(await handles(375), greaterThan(0),
          reason: '手机上没拖拽条了 —— 多半是把 showDragHandle 写成了非空默认值,'
              '显式 false 会盖掉 brandTheme 里的全局设置');
      expect(await handles(375, flag: false), 0,
          reason: 'showDragHandle 参数没接上,传 false 也照画');
      expect(await handles(1440, flag: true), 0,
          reason: '对话框上顶着一根拖拽条 —— 它拖不动,纯是个装饰');
    });

    testWidgets('isSheetBottom 跟着档位走', (t) async {
      for (final (w, expected) in [(375.0, true), (768.0, false), (1440.0, false)]) {
        setPhoneViewport(t, Size(w, 900));
        late bool got;
        await t.pumpWidget(MaterialApp(
          home: Builder(builder: (ctx) {
            got = isSheetBottom(ctx);
            return const SizedBox();
          }),
        ));
        await t.pumpAndSettle();
        expect(got, expected, reason: '${w.toInt()}px 判错了');
      }
    });
  });

  group('appBar 跟着内容限宽', () {
    Widget shellWithBar({double maxWidth = kFeedMaxWidth}) => SzNavScaffold(
          items: items,
          selectedIndex: 0,
          onSelected: (_) {},
          contentMaxWidth: maxWidth,
          appBar: AppBar(title: const Text('标题')),
          body: const Center(child: Text('内容')),
        );

    testWidgets('窄屏上 appBar 照常给 Scaffold', (t) async {
      await pumpAt(t, 375, shellWithBar());
      expect(find.byType(AppBar), findsOneWidget);
      expect(find.text('标题'), findsOneWidget);
    });

    testWidgets('宽屏上 appBar 的内容不超过 contentMaxWidth', (t) async {
      await pumpAt(t, 1440, shellWithBar(maxWidth: 1080));
      final w = t.getSize(find.byType(AppBar)).width;
      expect(w, lessThanOrEqualTo(1080),
          reason: '标题栏横跨了整个 1440(实际 ${w.toStringAsFixed(0)})—— '
              '标题贴最左、图标钉最右,而下面的内容是居中的,上下对不齐');
    });

    testWidgets('appBar 和 body 用同一个宽度,对得齐', (t) async {
      await pumpAt(t, 1440, shellWithBar(maxWidth: 720));
      expect(t.getSize(find.byType(AppBar)).width, lessThanOrEqualTo(720));
    });

    testWidgets('宽屏上标题还在,没被吃掉', (t) async {
      await pumpAt(t, 1440, shellWithBar());
      expect(find.text('标题'), findsOneWidget);
    });
  });

  group('push 出来的子页也要限宽', () {
    // 这一条是**验收时才发现的**:改完外壳在 1440 上一切正常,
    // 点进「意见反馈」——整页铺满,返回箭头钉在屏幕最左上角,
    // 提交按钮横跨 1440,一个按钮一米宽。
    //
    // 子页是 push 出来的,不在 SzNavScaffold 里,所以外壳那次改动
    // 一点也管不到它们。手机上完全看不出来。
    Widget page({double maxWidth = kContentMaxWidth, Widget? bottom}) =>
        SzPageScaffold(
          contentMaxWidth: maxWidth,
          appBar: AppBar(title: const Text('意见反馈')),
          bottomNavigationBar: bottom,
          body: Column(children: [
            Container(key: const Key('内容'), height: 40, color: Colors.red),
          ]),
        );

    testWidgets('窄屏上就是普通 Scaffold,不干预', (t) async {
      await pumpAt(t, 375, page());
      expect(t.getSize(find.byKey(const Key('内容'))).width, 375);
      expect(find.byType(AppBar), findsOneWidget);
    });

    testWidgets('1440 上正文和标题栏一起收到 720', (t) async {
      await pumpAt(t, 1440, page());
      expect(t.getSize(find.byKey(const Key('内容'))).width, kContentMaxWidth);
      final bar = t.getSize(find.byType(AppBar)).width;
      expect(bar, lessThanOrEqualTo(kContentMaxWidth),
          reason: '标题栏还横跨 1440(实际 ${bar.toStringAsFixed(0)})—— '
              '返回箭头会钉在屏幕最左上角,离正文半个屏');
    });

    testWidgets('底栏按钮也跟着收,不做一米宽的按钮', (t) async {
      await pumpAt(
          t,
          1440,
          page(
              bottom: Container(
                  key: const Key('底栏'), height: 56, color: Colors.blue)));
      final w = t.getSize(find.byKey(const Key('底栏'))).width;
      expect(w, lessThanOrEqualTo(kContentMaxWidth),
          reason: '"提交"按钮横跨了 1440(实际 ${w.toStringAsFixed(0)})—— '
              '点哪儿都行反而不知道该点哪儿');
    });

    testWidgets('要放表格的页面可以传宽一档', (t) async {
      await pumpAt(t, 1600, page(maxWidth: kWideMaxWidth));
      expect(t.getSize(find.byKey(const Key('内容'))).width, kWideMaxWidth);
    });

    testWidgets('各档都不抛异常、不画出界', (t) async {
      for (final w in [375.0, 600.0, 768.0, 1024.0, 1440.0, 1920.0]) {
        await pumpAt(t, w, page());
        expect(t.takeException(), isNull, reason: '${w.toInt()}px 下抛异常');
        expect(textsPaintingOutside(t), isEmpty, reason: '${w.toInt()}px 下字出界');
      }
    });
  });
}
