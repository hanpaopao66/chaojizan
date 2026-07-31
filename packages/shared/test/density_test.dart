import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

/// 三端密度分化(#134)。
///
/// 守的是一件事:**密度必须真的传导到渲染尺寸**,而不只是主题里存了个数。
/// 所以下面全部量 `tester.getSize()` 的实测值,不去读 ThemeData 的字段 ——
/// 读字段的测试在"主题被某个页面局部 copyWith 覆盖掉"时照样绿。
void main() {
  /// `key: ValueKey(d)` 不是装饰,是这条测试成立的前提。
  ///
  /// 同一个测试里连续 pump 两个只有 theme 不同的 MaterialApp,Flutter 会复用
  /// 整棵 element 树,按钮**保持第一次解析出的 style** —— 实测两态量出来都是
  /// 第一次那个值(48/48),于是"密度没生效"和"密度生效了"长得一模一样。
  /// 加 key 让 `Widget.canUpdate` 判否,强制重建,量到的才是这一态的真实尺寸。
  Future<Size> sizeOf(
      WidgetTester tester, SzDensity d, Widget child, Type type) async {
    await tester.pumpWidget(MaterialApp(
      key: ValueKey(d),
      theme: brandTheme(Brightness.light, density: d),
      home: Scaffold(body: Center(child: child)),
    ));
    return tester.getSize(find.byType(type));
  }

  group('点击区', () {
    testWidgets('主按钮:操作态比浏览态高', (tester) async {
      final btn = FilledButton(onPressed: () {}, child: const Text('接单'));
      final browse = await sizeOf(tester, SzDensity.browse, btn, FilledButton);
      final operate =
          await sizeOf(tester, SzDensity.operate, btn, FilledButton);
      expect(operate.height, greaterThan(browse.height),
          reason: '商家/骑手端的主按钮没变大 —— 密度没传导到渲染');
      expect(browse.height, greaterThanOrEqualTo(48),
          reason: '浏览态也不能低于 Material 的 48 基线');
      expect(operate.height, greaterThanOrEqualTo(56),
          reason: '戴手套按 56 是本项目定的下限,见 docs/BRAND.md');
    });

    testWidgets('次按钮:两态都不低于 44(iOS 人机指南下限)', (tester) async {
      final btn = OutlinedButton(onPressed: () {}, child: const Text('拒单'));
      for (final d in SzDensity.values) {
        final s = await sizeOf(tester, d, btn, OutlinedButton);
        expect(s.height, greaterThanOrEqualTo(44), reason: '$d 的次按钮太小');
      }
    });

    testWidgets('文字按钮也有命中区,不是只有文字那么大', (tester) async {
      final btn = TextButton(onPressed: () {}, child: const Text('详情'));
      for (final d in SzDensity.values) {
        final s = await sizeOf(tester, d, btn, TextButton);
        expect(s.height, greaterThanOrEqualTo(44),
            reason: '$d 的文字按钮命中区不足,手指点不中');
      }
    });

    testWidgets('图标按钮:操作态命中区更大', (tester) async {
      final btn = IconButton(onPressed: () {}, icon: const Icon(Icons.phone));
      final browse = await sizeOf(tester, SzDensity.browse, btn, IconButton);
      final operate = await sizeOf(tester, SzDensity.operate, btn, IconButton);
      expect(operate.width, greaterThan(browse.width));
      expect(browse.width, greaterThanOrEqualTo(44),
          reason: '连浏览态都不该低于 44');
    });
  });

  group('信息密度', () {
    testWidgets('列表行:操作态更高(一屏少放几行,换点不错)', (tester) async {
      const tile = SizedBox(
        width: 300,
        child: ListTile(title: Text('订单 #1024'), subtitle: Text('待接单')),
      );
      final browse = await sizeOf(tester, SzDensity.browse, tile, ListTile);
      final operate = await sizeOf(tester, SzDensity.operate, tile, ListTile);
      expect(operate.height, greaterThan(browse.height));
    });

    testWidgets('正文字号:操作态更大(后厨油烟、骑手日晒下都要看得清)', (tester) async {
      double fontOf(SzDensity d) =>
          brandTheme(Brightness.light, density: d)
              .listTileTheme
              .titleTextStyle!
              .fontSize!;
      expect(fontOf(SzDensity.operate), greaterThan(fontOf(SzDensity.browse)));
    });
  });

  group('分化不能走样', () {
    test('浏览态严格等于分化之前的老口径,用户端不该被动变样', () {
      final t = brandTheme(Brightness.light, density: SzDensity.browse);
      expect(t.filledButtonTheme.style!.minimumSize!.resolve({}),
          const Size(64, 48));
      expect(t.outlinedButtonTheme.style!.minimumSize!.resolve({}),
          const Size(64, 44));
      expect(t.listTileTheme.titleTextStyle!.fontSize, 14.5);
      expect(t.inputDecorationTheme.contentPadding,
          const EdgeInsets.symmetric(horizontal: 16, vertical: 13));
      expect(t.visualDensity, VisualDensity.standard);
    });

    test('浏览态是默认值:忘了传参的新页面拿到的是用户端口径', () {
      final implicit = brandTheme(Brightness.light);
      final browse = brandTheme(Brightness.light, density: SzDensity.browse);
      expect(implicit.listTileTheme.titleTextStyle!.fontSize,
          browse.listTileTheme.titleTextStyle!.fontSize);
    });

    testWidgets('密度不动颜色:两态的品牌色必须一致', (tester) async {
      for (final b in Brightness.values) {
        final a = brandTheme(b, density: SzDensity.browse).extension<SzColors>()!;
        final o =
            brandTheme(b, density: SzDensity.operate).extension<SzColors>()!;
        expect(o.clay, a.clay, reason: '$b:密度改了平台色 —— 三端会长得不像一家');
        expect(o.paper, a.paper, reason: '$b:密度改了页底色');
        expect(o.ledger, a.ledger, reason: '$b:密度改了账目表面色');
        expect(o.channelTones, a.channelTones, reason: '$b:密度改了频道色板');
      }
    });
  });
}
