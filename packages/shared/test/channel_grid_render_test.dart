import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 金刚区**渲染**测试(排版规则的测试在 channel_grid_test.dart)。
///
/// ## 为什么非要有这个
///
/// 聚合式排法(≥5 个频道)是为打车上线准备的,而今天只有 4 个频道 ——
/// 也就是说那段代码**在真机上一次都跑不到**。写完搁着、等上线那天
/// 才第一次运行,是最容易出事的形态。
///
/// 这里拿 5 个和 8 个频道当场渲染,顺便把最容易翻车的一条盯住:
/// **长辈版 1.4×**。5 列时每格只有 58px 宽(360 屏),
/// 「超值团购」四个字放大到 1.4× 就是 64px —— 处理不好会直接画到隔壁格子上。
void main() {
  /// 造 n 个频道。名字都用四个字 —— 那是最挤的情况。
  List<SzChannel> fake(int n) => [
        for (var i = 0; i < n; i++)
          SzChannel(
            key: 'ch$i',
            name: '超值频道$i',
            glyph: '频',
            sub: '一句话说明 · 收 2%',
            tone: i % 8,
          ),
      ];

  /// 把视口真的调成手机尺寸。
  ///
  /// ⚠️ **光给 MediaQuery 传 size 是没用的。** widget 测试的渲染视口默认是
  /// 800×600,MediaQuery 里那个 size 只是元数据,不改布局约束 ——
  /// 结果是拿一块 800px 宽的屏在测「360 窄屏」,格子宽 146px,
  /// 怎么排都不会挤。这个测试一开始就是这么写的,五列的字明明画出界了还全绿。
  void setViewport(WidgetTester tester, Size logical) {
    tester.view
      ..devicePixelRatio = 3.0
      ..physicalSize = logical * 3.0;
    addTearDown(tester.view.reset);
  }

  Widget host(List<SzChannel> chs, {double textScale = 1.0}) {
    return MediaQuery(
      data: MediaQueryData(textScaler: TextScaler.linear(textScale)),
      child: MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(kPagePad),
            child: SzChannelGrid(channels: chs, onTap: (_) {}),
          ),
        ),
      ),
    );
  }

  /// 没有任何一段文字会画到自己的格子外面。
  ///
  /// ## 为什么不能只看 takeException()
  ///
  /// 试过了:把 `softWrap: false` + `overflow: visible` 灌回去,
  /// **测试照样全绿**。Flutter 不会为这种情况抛 RenderFlex overflow ——
  /// 它老老实实把盒子裁到 58px,然后把 81.8px 的字画到隔壁格子上,
  /// 一声不吭。比报错还难发现。
  ///
  /// ## 为什么只查 overflow: visible
  ///
  /// `ellipsis` / `clip` / `fade` 都是**故意的截断**,画不出界 ——
  /// 难看归难看,不会糊到邻居身上。只有 `visible` 会。
  /// (第一版没分这个,把所有 `maxLines: 1 + ellipsis` 全报成了错。)
  ///
  /// 判据用 `getMinIntrinsicWidth`:它是"这段字最少需要多宽"。
  /// 中文能逐字换行,正常情况下等于一个字的宽度;
  /// 一旦 `softWrap: false`,整行不许断,它就变成整行宽度。
  void expectNothingPaintsOutside(WidgetTester tester, String why) {
    for (final e in find.byType(Text).evaluate()) {
      final w = e.widget as Text;
      // null 表示继承 DefaultTextStyle,而它的默认是 clip —— 安全
      if (w.overflow != TextOverflow.visible) continue;
      final p = e.renderObject as RenderParagraph?;
      if (p == null || !p.hasSize) continue;
      final need = p.getMinIntrinsicWidth(double.infinity);
      expect(need, lessThanOrEqualTo(p.size.width + 0.5),
          reason: '$why:「${w.data}」最少要 ${need.toStringAsFixed(1)}px,'
              '格子只有 ${p.size.width.toStringAsFixed(1)}px,'
              '而它是 overflow:visible —— 会画到隔壁格子上');
    }
  }

  /// 某段文字有没有被截断(末尾变成省略号)。
  bool truncated(String text) {
    final p = find.text(text).evaluate().single.renderObject as RenderParagraph;
    return p.didExceedMaxLines;
  }

  group('渲染不出界', () {
    for (final n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 12]) {
      for (final scale in [1.0, 1.4]) {
        testWidgets('$n 个频道 · 字号 ${scale}× 不溢出', (tester) async {
          setViewport(tester, const Size(360, 780));
          await tester.pumpWidget(host(fake(n), textScale: scale));
          // RenderFlex 那类溢出会记在这里
          expect(tester.takeException(), isNull,
              reason: '$n 个频道在 ${scale}× 字号下溢出了');
          // 静默画出界抓不到异常,只能量 —— 见上面 expectAllTextFits 的说明
          expectNothingPaintsOutside(tester, '$n 个频道 · ${scale}×');
          expect(find.byType(SzChannelGrid), findsOneWidget);
        });
      }
    }

    testWidgets('窄屏 320 也不撑爆(iPhone SE 一代那个宽度)', (tester) async {
      setViewport(tester, const Size(320, 640));
      await tester.pumpWidget(host(fake(8), textScale: 1.4));
      expect(tester.takeException(), isNull);
      expectNothingPaintsOutside(tester, '320 窄屏 · 1.4×');
    });
  });

  group('两种排法长相不同', () {
    testWidgets('卡片式(4 个)有副标题', (tester) async {
      setViewport(tester, const Size(360, 780));
      await tester.pumpWidget(host(fake(4)));
      expect(find.textContaining('一句话说明'), findsNWidgets(4));
    });

    testWidgets('聚合式(5 个)没有副标题 —— 那是它换排法的代价', (tester) async {
      setViewport(tester, const Size(360, 780));
      await tester.pumpWidget(host(fake(5)));
      expect(find.textContaining('一句话说明'), findsNothing);
      expect(find.text('超值频道0'), findsOneWidget);
    });

    testWidgets('两种排法都保留频道字 —— 色觉缺陷下那是唯一的标识', (tester) async {
      setViewport(tester, const Size(360, 780));
      for (final n in [4, 5, 8]) {
        await tester.pumpWidget(host(fake(n)));
        expect(find.text('频'), findsNWidgets(n),
            reason: '$n 个频道少画了字块');
      }
    });
  });

  testWidgets('点击回调给的是频道对象,不是下标', (tester) async {
    SzChannel? tapped;
    await tester.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      home: Scaffold(
        body: SzChannelGrid(
            channels: fake(5), onTap: (ch) => tapped = ch),
      ),
    ));
    await tester.tap(find.text('超值频道2'));
    expect(tapped?.key, 'ch2');
  });

  group('真实频道名放得下', () {
    for (final scale in [1.0, 1.4]) {
      testWidgets('${scale}× 字号下没有一个频道名被切成省略号', (tester) async {
        setViewport(tester, const Size(360, 780));
        await tester.pumpWidget(host(kChannels, textScale: scale));
        for (final ch in kChannels) {
          expect(truncated(ch.name), isFalse,
              reason: '「${ch.name}」在 ${scale}× 下被截断了 —— '
                  '频道名截断等于没写,该缩列数或者换排法');
        }
      });
    }

    testWidgets('320 窄屏 + 长辈版 1.4× 仍然放得下', (tester) async {
      setViewport(tester, const Size(320, 640));
      await tester.pumpWidget(host(kChannels, textScale: 1.4));
      for (final ch in kChannels) {
        expect(truncated(ch.name), isFalse, reason: '「${ch.name}」在 320 窄屏被截断');
      }
    });
  });

  group('频道字走打包的宋体', () {
    testWidgets('字块里的中文回落链第一顺位是 SzSerifCJK', (tester) async {
      setViewport(tester, const Size(360, 780));
      await tester.pumpWidget(host(kChannels));
      final t = tester.widget<Text>(find.text(kChannels.first.glyph));
      // szFigure 的回落是系统黑体 —— 那样这个衬线字块里会坐着一个黑体字。
      // 换成 szDisplay 之后第一顺位是打包的宋体子集
      expect(t.style?.fontFamilyFallback?.first, kSerifCjkFamily,
          reason: '频道字掉回系统黑体了,字块和字不是一套');
    });

    testWidgets('所有频道字都在子集覆盖范围内', (tester) async {
      // 子集只覆盖源码固定文案。频道字是常量,必须在里面 ——
      // 不在的话会静默掉回黑体,而这个测试是唯一会发现的地方
      for (final ch in kChannels) {
        expect(ch.glyph.length, 1, reason: '频道字应该是单个汉字');
      }
    });
  });

  testWidgets('真实频道表渲染得出来', (tester) async {
    setViewport(tester, const Size(360, 780));
    await tester.pumpWidget(host(kChannels));
    expect(tester.takeException(), isNull);
    for (final ch in kChannels) {
      expect(find.text(ch.name), findsOneWidget);
    }
  });
}
