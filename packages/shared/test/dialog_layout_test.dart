import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

import 'text_fit.dart';

/// 弹窗的**位置与边界**:不错位、不出界、不被键盘吃掉。
///
/// ## 和 dialog_density_test 分工
///
/// 那个测的是「够不够紧凑」(空白别浪费),这个测的是「摆得对不对」。
/// 两件事会互相打架 —— 把内边距压到 0 最紧凑,但字就贴边了。
///
/// ## 这一类问题为什么测不出来又最难发现
///
/// 溢出有三种,报错方式各不相同:
///
/// | 形态 | 有没有异常 | 表现 |
/// |---|---|---|
/// | Row/Column 排不下 | ✅ 抛 RenderFlex overflow | 黄黑条 |
/// | 字画到盒子外 | ❌ **一声不吭** | 字压到别的元素上 |
/// | 弹窗超出屏幕 | ❌ 一声不吭 | 按钮在屏幕外,点不到 |
///
/// 后两种在真机上才看得见,而写代码的人用的是大屏、标准字号、没开键盘。
/// 所以这一组专门跑**不利条件**:小屏 + 长辈版 1.4 倍字 + 键盘弹起 + 宽屏。
void main() {
  /// 打开一个弹窗并返回弹窗卡片的矩形。
  Future<Rect> openDialog(
    WidgetTester t,
    Widget dialog, {
    Size screen = const Size(375, 667),
    double textScale = 1.0,
    double keyboard = 0,
  }) async {
    await t.pumpWidget(const SizedBox());
    setPhoneViewport(t, screen);
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light),
      builder: (c, child) => MediaQuery(
        data: MediaQuery.of(c).copyWith(
          textScaler: TextScaler.linear(textScale),
          viewInsets: EdgeInsets.only(bottom: keyboard),
        ),
        child: child!,
      ),
      home: Builder(
        builder: (c) => Scaffold(
          body: Center(
            child: ElevatedButton(
              onPressed: () => showDialog<void>(
                  context: c, useSafeArea: true, builder: (_) => dialog),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ));
    await t.tap(find.text('open'));
    await t.pumpAndSettle();
    // 量的是**看得见的那张卡**,不是布局容器。
    //
    // 踩过两次:`find.byType(Material).last` 抓到的是最里面那个
    // (按钮或输入框自己的 Material);而 `find.byType(AlertDialog)` /
    // `Dialog` 的 RenderBox **铺满整个屏幕** —— 它们是负责居中的容器,
    // 量出来永远是 1280x800,看着像"弹窗铺满全屏"。
    //
    // 真正的卡片是 Dialog 里最外层那个 Material。
    return t.getRect(find
        .descendant(of: find.byType(Dialog), matching: find.byType(Material))
        .first);
  }

  /// 一个内容不算短的真实形态:标题 + 两段说明 + 三个按钮。
  Widget sample({bool scrollable = false}) => SzDialog(
        scrollable: scrollable,
        title: const Text('生日与营销推送'),
        content: const Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
              decoration: InputDecoration(
                  labelText: '生日(MM-DD,选填)',
                  helperText: '只收集月日,生日当天送券',
                  border: OutlineInputBorder())),
          SwitchListTile(
              title: Text('接收营销推送'),
              subtitle: Text('生日/优惠/收藏店上新;订单通知不受影响'),
              value: true,
              onChanged: null),
        ]),
        actions: [
          TextButton(onPressed: null, child: Text('取消')),
          FilledButton(onPressed: null, child: Text('保存')),
        ],
      );

  group('小屏标准字号', () {
    testWidgets('不出屏、不溢出、字不画到盒子外', (t) async {
      final r = await openDialog(t, sample());
      expect(t.takeException(), isNull);
      expect(textsPaintingOutside(t), isEmpty);
      expect(r.left, greaterThanOrEqualTo(0));
      expect(r.right, lessThanOrEqualTo(375));
      expect(r.top, greaterThanOrEqualTo(0));
      expect(r.bottom, lessThanOrEqualTo(667));
    });
  });

  group('长辈版:字放大 1.4 倍', () {
    testWidgets('弹窗仍然整个在屏幕里', (t) async {
      final r = await openDialog(t, sample(scrollable: true), textScale: 1.4);
      expect(t.takeException(), isNull, reason: '长辈版下弹窗溢出了');
      expect(r.top, greaterThanOrEqualTo(0),
          reason: '弹窗顶出屏幕外 ${(-r.top).toStringAsFixed(0)}px —— '
              '标题看不见了');
      expect(r.bottom, lessThanOrEqualTo(667),
          reason: '弹窗底超出屏幕 ${(r.bottom - 667).toStringAsFixed(0)}px —— '
              '按钮点不到。内容长的弹窗要 scrollable: true');
    });

    testWidgets('按钮仍然在屏幕里点得到', (t) async {
      await openDialog(t, sample(scrollable: true), textScale: 1.4);
      final save = t.getRect(find.text('保存'));
      expect(save.bottom, lessThanOrEqualTo(667),
          reason: '「保存」被推到屏幕外了');
    });
  });

  group('键盘弹起', () {
    testWidgets('弹窗上移,不被键盘盖住', (t) async {
      // iPhone SE 上中文键盘约 300px
      final r = await openDialog(t, sample(scrollable: true), keyboard: 300);
      expect(t.takeException(), isNull);
      expect(r.bottom, lessThanOrEqualTo(667 - 300),
          reason: '弹窗底边 ${r.bottom.toStringAsFixed(0)} 压在键盘下面'
              '(键盘顶边 367)—— 输入框和按钮都够不着');
    });
  });

  group('宽屏', () {
    testWidgets('不铺满整个屏幕宽', (t) async {
      final r = await openDialog(t, sample(),
          screen: const Size(1280, 800));
      expect(r.width, lessThanOrEqualTo(720),
          reason: '弹窗宽 ${r.width.toStringAsFixed(0)}px —— '
              '一行字横跨整屏,眼睛要来回扫');
      expect(r.center.dx, closeTo(640, 1),
          reason: '弹窗没有水平居中');
    });
  });

  group('内容很长', () {
    testWidgets('scrollable 的弹窗不出屏', (t) async {
      final long = SzDialog(
        scrollable: true,
        title: const Text('用户协议'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [for (var i = 0; i < 40; i++) Text('第 $i 条 ' * 6)],
        ),
        actions: [TextButton(onPressed: null, child: const Text('我知道了'))],
      );
      final r = await openDialog(t, long);
      expect(t.takeException(), isNull);
      expect(r.bottom, lessThanOrEqualTo(667));
      expect(r.top, greaterThanOrEqualTo(0));
    });
  });
}
