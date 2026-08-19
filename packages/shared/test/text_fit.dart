import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';

/// 「有没有字被画到自己的盒子外面」的判据。测试专用,不进包。
///
/// ## 为什么需要一个专门的判据
///
/// 这类问题**不抛异常**。Flutter 把盒子裁到该有的宽度,然后照样把超出的
/// 字画出去,一声不吭 —— `tester.takeException()` 是空的,页面看着渲染成功了。
/// 比 RenderFlex 那种黄黑条还难发现,因为它连条都没有。
///
/// ## 判据怎么来的(踩过两次)
///
/// 第一版用 `getMinIntrinsicWidth > 盒子宽`。看着能用,其实只在
/// `maxLines: 1` 时成立 —— 那时候不许换行,最小内在宽度就等于整行宽度。
/// 换成 `softWrap: false` 但不限行数,它返回的是**一个字**的宽度(21.3),
/// 漏报。
///
/// 正确的分法是先问「这段字能不能换行」:
///
/// - 能换行(默认):排不下会折行,只有**单个不可断的词**超宽才画出界
///   → 判据是 `getMinIntrinsicWidth`;
/// - 不能换行(`softWrap: false` 或 `maxLines: 1`):整行必须塞进盒子
///   → 判据是 `getMaxIntrinsicWidth`。
///
/// 另外 `overflow` 不是 `visible` 的一律跳过 —— `ellipsis`/`clip`/`fade`
/// 是**故意的截断**,画不出界。截断该不该发生是设计问题,用 [truncatedTexts] 单看。
List<String> textsPaintingOutside(WidgetTester tester) {
  final bad = <String>[];
  for (final element in find.byType(Text).evaluate()) {
    final widget = element.widget as Text;
    // 被裁掉或加省略号的不会画出界
    if (widget.overflow != TextOverflow.visible) continue;
    final para = element.renderObject as RenderParagraph?;
    if (para == null || !para.hasSize) continue;

    final canWrap = widget.softWrap != false && widget.maxLines != 1;
    final need = canWrap
        ? para.getMinIntrinsicWidth(double.infinity)
        : para.getMaxIntrinsicWidth(double.infinity);
    if (need > para.size.width + 0.5) {
      bad.add('「${widget.data}」要 ${need.toStringAsFixed(0)}px,'
          '盒子只有 ${para.size.width.toStringAsFixed(0)}px'
          '${canWrap ? "(有不可断的长词)" : "(不许换行)"}');
    }
  }
  return bad;
}

/// 哪些字被切成了省略号。
///
/// **截断不算失败** —— 它是设计选择。但「最窄屏 + 最大字号下谁被切了」
/// 得有人知道,而不是等用户来说。
List<String> truncatedTexts(WidgetTester tester) {
  final out = <String>[];
  for (final element in find.byType(Text).evaluate()) {
    final para = element.renderObject as RenderParagraph?;
    if (para == null || !para.hasSize || !para.didExceedMaxLines) continue;
    out.add('「${(element.widget as Text).data}」');
  }
  return out;
}

/// 把渲染视口真的调成手机尺寸。
///
/// ⚠️ **只给 MediaQuery 传 size 是没用的。** widget 测试的渲染视口默认
/// 800×600,MediaQuery 里那个 size 只是元数据,不改布局约束 ——
/// 结果是拿一块 800px 宽的屏在测「360 窄屏」,怎么排都不挤。
void setPhoneViewport(WidgetTester tester, Size logical) {
  tester.view
    ..devicePixelRatio = 3.0
    ..physicalSize = logical * 3.0;
  addTearDown(tester.view.reset);
}
