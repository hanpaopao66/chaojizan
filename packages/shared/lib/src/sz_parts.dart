/// 2026-09 浅色定稿里三端共用的几个小件:状态 pill、文字页签、虚线脚注。
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show HapticFeedback;

import 'brand.dart';
import 'motion.dart';

/// 标题栏右侧的状态 pill:「● 营业中」「● 在线 · 高新路」「● 已打烊」。
///
/// 开 = earn 淡底 earn 字;关 = inkMuted 淡底。颜色随状态 220ms 过渡,
/// **文字直接换不做过渡**(动效规范 10)。给了 [onTap] 就是一个开关:
/// 点一下震动 light,确认弹窗之类的由调用方在 onTap 里做。
class SzStatePill extends StatelessWidget {
  const SzStatePill({
    super.key,
    required this.label,
    required this.on,
    this.onTap,
    this.tone,
  });

  final String label;
  final bool on;
  final VoidCallback? onTap;

  /// 覆盖「开」的颜色(默认 earn)。「食安停业」这类用 danger
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final fg = on ? (tone ?? sz.earn) : sz.inkMuted;
    final d = SzMotion.of(context, SzMotion.base);
    final pill = AnimatedContainer(
      duration: d,
      curve: SzMotion.standard,
      padding: const EdgeInsets.fromLTRB(8, 5, 10, 5),
      decoration: BoxDecoration(
        color: fg.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        AnimatedContainer(
          duration: d,
          width: 7,
          height: 7,
          decoration: BoxDecoration(color: fg, shape: BoxShape.circle),
        ),
        const SizedBox(width: 6),
        Text(label,
            style: TextStyle(
                fontSize: kFontNote,
                fontWeight: FontWeight.w600,
                color: fg,
                height: 1.2)),
      ]),
    );
    if (onTap == null) return pill;
    return Semantics(
      button: true,
      toggled: on,
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: () {
          HapticFeedback.lightImpact();
          onTap!();
        },
        // 视觉是一枚小 pill,点击区撑到 48 高
        child: ConstrainedBox(
          constraints: const BoxConstraints(minHeight: 48),
          child: Center(widthFactor: 1, child: pill),
        ),
      ),
    );
  }
}

/// 标题栏里的纯文字页签:「今天 本周 本月」「9 月 8 月 全部」。
///
/// 选中墨色加粗,其余 inkFaint 退后 —— 它们是「看哪一段」的切换,
/// 不是导航,所以不画下划线也不画底。颜色切换 120ms。
class SzTextTabs extends StatelessWidget {
  const SzTextTabs({
    super.key,
    required this.labels,
    required this.index,
    required this.onChanged,
  });

  final List<String> labels;
  final int index;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      for (var i = 0; i < labels.length; i++)
        InkWell(
          borderRadius: BorderRadius.circular(kRadiusSm),
          onTap: i == index ? null : () => onChanged(i),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 44, minWidth: 40),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              child: Center(
                widthFactor: 1,
                // szSans:AnimatedDefaultTextStyle 整个替换上层字样,要自带字族
                child: AnimatedDefaultTextStyle(
                  duration: SzMotion.of(context, SzMotion.fast),
                  style: szSans(
                    fontSize: kFontBody,
                    fontWeight: i == index ? FontWeight.w600 : FontWeight.w400,
                    color: i == index ? sz.ink : sz.inkMuted,
                  ),
                  child: Text(labels[i]),
                ),
              ),
            ),
          ),
        ),
    ]);
  }
}

/// 页签下面那道**定长**短线(TabBar 的 `indicator:`):视频 tab 的「关注 推荐 热门 竖屏」、
/// 详情页的「简介 评论」。
///
/// Material 的下划线要么和整格一样宽、要么和文字一样宽 ——「评论 486」比「简介」长一截,
/// 两个页签下面的线就一长一短;设计稿上是同一道 20 / 24 的短线居中。
class SzTabUnderline extends Decoration {
  const SzTabUnderline({required this.color, this.width = 20, this.thickness = 2});

  final Color color;
  final double width;
  final double thickness;

  @override
  BoxPainter createBoxPainter([VoidCallback? onChanged]) => _TabUnderlinePainter(this);
}

class _TabUnderlinePainter extends BoxPainter {
  _TabUnderlinePainter(this.d);

  final SzTabUnderline d;

  @override
  void paint(Canvas canvas, Offset offset, ImageConfiguration configuration) {
    final size = configuration.size;
    if (size == null) return;
    final rect = offset & size;
    canvas.drawRRect(
      RRect.fromRectAndRadius(
        Rect.fromCenter(
          center: Offset(rect.center.dx, rect.bottom - d.thickness / 2),
          width: d.width,
          height: d.thickness,
        ),
        Radius.circular(d.thickness / 2),
      ),
      Paint()..color = d.color,
    );
  }
}

/// 虚线框里的一句话:承诺类的脚注(「不想干了随时能走……」)。
///
/// 虚线而不是卡片:它不是一个可以点的东西,也不是数据,是一句说在前面的话。
class SzDashedNote extends StatelessWidget {
  const SzDashedNote({super.key, required this.child, this.padding});

  final Widget child;
  final EdgeInsetsGeometry? padding;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return CustomPaint(
      painter: _DashedRRectPainter(color: sz.line, radius: kRadiusMd),
      child: Padding(
        padding: padding ?? const EdgeInsets.fromLTRB(16, 14, 16, 14),
        child: DefaultTextStyle.merge(
          style: TextStyle(fontSize: kFontNote, height: 1.5, color: sz.inkMuted),
          child: child,
        ),
      ),
    );
  }
}

class _DashedRRectPainter extends CustomPainter {
  _DashedRRectPainter({required this.color, required this.radius});

  final Color color;
  final double radius;

  @override
  void paint(Canvas canvas, Size size) {
    final rrect = RRect.fromRectAndRadius(
        (Offset.zero & size).deflate(0.5), Radius.circular(radius));
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    const dash = 4.0, gap = 3.0;
    for (final m in (Path()..addRRect(rrect)).computeMetrics()) {
      var d = 0.0;
      while (d < m.length) {
        canvas.drawPath(m.extractPath(d, d + dash), paint);
        d += dash + gap;
      }
    }
  }

  @override
  bool shouldRepaint(covariant _DashedRRectPainter old) =>
      old.color != color || old.radius != radius;
}
