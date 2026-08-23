import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:superz_shared/superz_shared.dart';

import 'text_fit.dart';

/// 弹窗的紧凑度。
///
/// ## 这个测试防的是什么
///
/// Material 的默认内边距是给桌面留的:标题上 24、标题到正文 20、
/// 正文到按钮 24。真机上一个"暂无计划"两行字的弹窗,光空白就吃掉
/// 七十多像素 —— 弹窗占了大半屏,有效内容只有两行。
///
/// 密度这种事没有报错:功能全对、测试全绿,只是难用。拿数字锁住。
void main() {
  Future<Size> cardSize(WidgetTester t, Widget dialog,
      {SzDensity d = SzDensity.operate}) async {
    await t.pumpWidget(const SizedBox());
    await t.pump();
    setPhoneViewport(t, const Size(390, 844));
    await t.pumpWidget(MaterialApp(
      theme: brandTheme(Brightness.light, density: d),
      home: Builder(
        builder: (c) => Scaffold(
          body: Center(
            child: ElevatedButton(
              onPressed: () => showDialog(context: c, builder: (_) => dialog),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ));
    await t.tap(find.text('open'));
    await t.pumpAndSettle();
    return t.getSize(find.descendant(
            of: find.byType(Dialog), matching: find.byType(Material))
        .first);
  }

  final actions = [
    TextButton(onPressed: () {}, child: const Text('取消')),
    FilledButton(onPressed: () {}, child: const Text('保存')),
  ];
  const body = Text('暂无计划。春节歇业、除夕只开半天,都在这里提前设置。');

  testWidgets('同样的内容,SzDialog 比裸 AlertDialog 矮一截', (t) async {
    final bare = await cardSize(
        t,
        AlertDialog(
            title: const Text('节假日计划'), content: body, actions: actions));
    final compact = await cardSize(
        t,
        SzDialog(
            title: const Text('节假日计划'), content: body, actions: actions));
    expect(compact.height, lessThan(bare.height),
        reason: '收紧没生效:${compact.height} 不比 ${bare.height} 矮');
    expect(bare.height - compact.height, greaterThanOrEqualTo(20),
        reason: '只省了 ${bare.height - compact.height}px,'
            '不值得为它多一个组件 —— 要么把 padding 再收,要么别做这层');
  });

  testWidgets('弹窗宽度按窄屏给足:390 屏上不小于 340', (t) async {
    final s = await cardSize(t,
        SzDialog(title: const Text('提示'), content: body, actions: actions));
    // 默认 insetPadding 水平 40 会把弹窗压到 310,一句十来个字的提示
    // 被逼成三行 —— 高度全长在换行上
    expect(s.width, greaterThanOrEqualTo(340));
  });

  testWidgets('收的是空白不是触控区:按钮仍是密度给的高度', (t) async {
    await cardSize(t,
        SzDialog(title: const Text('提示'), content: body, actions: actions));
    final btn = t.getSize(find.widgetWithText(FilledButton, '保存'));
    expect(btn.height, greaterThanOrEqualTo(SzDensity.operate.buttonHeight),
        reason: '弹窗里的按钮被压矮了 —— 戴手套按不准那条不因为在弹窗里就不算');
  });

  testWidgets('没有标题时正文自己补回顶部留白', (t) async {
    final s = await cardSize(t, SzDialog(content: body, actions: actions));
    expect(s.height, greaterThan(0));
    // 正文不能贴着弹窗顶边
    final top = t.getTopLeft(find.byWidget(body)).dy;
    final card = t.getTopLeft(find.descendant(
            of: find.byType(Dialog), matching: find.byType(Material))
        .first).dy;
    expect(top - card, greaterThanOrEqualTo(12),
        reason: '没有标题时正文贴着顶边,看着像被截断了');
  });
}
