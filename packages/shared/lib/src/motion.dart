/// 三端动效:令牌 + 组件。数值来自设计稿「三端动效规范」(2026-09,
/// 设计稿本身不进仓库),本文件是它的代码实现 —— 以这里为准。
///
/// 核心就一句:**动得少,动得准**。所有动效只用四个时长、三条曲线;
/// 用户端 / 商家端出场带一点回弹,骑手端一律更快、不回弹 ——
/// 骑手在路上看手机,回弹的那 100 毫秒是在跟他抢注意力。
///
/// 三条通用约束也在这里落地:
///  - 系统「减少动态效果」打开时,时长全部归零,账本数字直接给终值;
///  - 骑手在骑行(GPS > 8km/h)时关掉一切非必要动效,只留新单推送
///    (骑手端的定位服务写 [SzMotion.riding]);
///  - 列表刷新不重播入场 —— 入场只在第一次建出来时播,
///    要重播(下拉刷新、换频道)由调用方换 key。
library;

import 'dart:math' as math;

import 'package:flutter/cupertino.dart' show CupertinoPageTransitionsBuilder;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show HapticFeedback;

import 'brand.dart';

/// 时长与曲线。
abstract final class SzMotion {
  /// 按压、开关、chip 选中、骑手端所有反馈
  static const fast = Duration(milliseconds: 120);

  /// 卡片入场、页面切换、频道条滑块、状态推进一段
  static const base = Duration(milliseconds: 220);

  /// 抽屉、底部弹层、成功态
  static const slow = Duration(milliseconds: 320);

  /// 账本数字滚动、分账条生长 —— 唯一允许的慢动作,因为钱要看清
  static const ledger = Duration(milliseconds: 900);

  /// 列表错落,最多累加到第 [staggerCap] 项
  static const stagger = Duration(milliseconds: 40);
  static const staggerCap = 6;

  /// cubic-bezier(.2,.8,.2,1):进场、滑块、数字滚动
  static const Curve standard = Cubic(0.2, 0.8, 0.2, 1.0);

  /// cubic-bezier(.34,1.3,.64,1):用户端 / 商家端出场,带一点回弹。骑手端不用
  static const Curve spring = Cubic(0.34, 1.3, 0.64, 1.0);

  /// cubic-bezier(.4,0,1,1):消失。消失永远比出现快
  static const Curve exit = Cubic(0.4, 0.0, 1.0, 1.0);

  /// 骑手正在骑行(速度 > 8km/h)。骑手端定位服务写,其余两端恒为 false。
  static final ValueNotifier<bool> riding = ValueNotifier(false);

  /// 此刻该不该省掉「非必要」动效:系统减少动态效果,或者骑手在骑车。
  static bool off(BuildContext context) =>
      (MediaQuery.maybeDisableAnimationsOf(context) ?? false) || riding.value;

  /// 只看系统开关(新单推送这类「必要」动效用:骑行中也要播)。
  static bool systemOff(BuildContext context) =>
      MediaQuery.maybeDisableAnimationsOf(context) ?? false;

  /// 关了动效就是 0,否则原样。
  static Duration of(BuildContext context, Duration d) =>
      off(context) ? Duration.zero : d;

  /// 列表第 [index] 项的错落延迟
  static Duration staggerAt(int index) =>
      stagger * math.min(math.max(index, 0), staggerCap);
}

/// 各端的动效性格。用户端 / 商家端 [bouncy];骑手端不回弹、成功态更快。
@immutable
class SzMotionStyle extends ThemeExtension<SzMotionStyle> {
  const SzMotionStyle({this.bouncy = true});

  final bool bouncy;

  /// 出场位移用的曲线(透明度一律 standard)
  Curve get enter => bouncy ? SzMotion.spring : SzMotion.standard;

  /// 成功块放大的时长:用户/商家 320 spring,骑手 220 standard
  Duration get success => bouncy ? SzMotion.slow : SzMotion.base;

  @override
  SzMotionStyle copyWith({bool? bouncy}) =>
      SzMotionStyle(bouncy: bouncy ?? this.bouncy);

  @override
  SzMotionStyle lerp(covariant SzMotionStyle? other, double t) =>
      t < 0.5 ? this : (other ?? this);
}

extension SzMotionStyleX on ThemeData {
  SzMotionStyle get szMotion => extension<SzMotionStyle>() ?? const SzMotionStyle();
}

/// 页面切换:Android(及 web / 桌面)fade-through 220ms,**不缩放**;
/// iOS 走系统 Cupertino 侧滑。
///
/// fade-through 的「through」是穿过底色:旧页先淡到纸色,新页再从纸色淡进来。
/// 旧页外面垫一层页底色,否则两页都半透明的那几帧会露出窗口的黑底。
class SzFadeThroughPageTransitionsBuilder extends PageTransitionsBuilder {
  const SzFadeThroughPageTransitionsBuilder();

  @override
  Duration get transitionDuration => SzMotion.base;

  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) {
    final inOpacity = CurvedAnimation(
      parent: animation,
      curve: const Interval(0.35, 1, curve: SzMotion.standard),
      reverseCurve: const Interval(0.35, 1, curve: SzMotion.exit),
    );
    final outOpacity = ReverseAnimation(CurvedAnimation(
      parent: secondaryAnimation,
      curve: const Interval(0, 0.35, curve: SzMotion.exit),
    ));
    return ColoredBox(
      color: Theme.of(context).scaffoldBackgroundColor,
      child: FadeTransition(
        opacity: outOpacity,
        child: FadeTransition(opacity: inOpacity, child: child),
      ),
    );
  }
}

/// 三端主题统一挂的页面切换表。
const PageTransitionsTheme kSzPageTransitions = PageTransitionsTheme(
  builders: {
    TargetPlatform.android: SzFadeThroughPageTransitionsBuilder(),
    TargetPlatform.fuchsia: SzFadeThroughPageTransitionsBuilder(),
    TargetPlatform.linux: SzFadeThroughPageTransitionsBuilder(),
    TargetPlatform.windows: SzFadeThroughPageTransitionsBuilder(),
    TargetPlatform.macOS: SzFadeThroughPageTransitionsBuilder(),
    TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
  },
);

/// 01 卡片入场:opacity 0→1、y +12→0,220ms;透明度 standard,
/// 位移用各端的出场曲线(用户/商家 spring、骑手 standard);按 index 错落 40ms。
///
/// 只在**第一次建出来**时播。数据刷新时同一个 key 的卡不会重播;
/// 想重播(下拉刷新、换频道)就让外层换一个 key。
/// 第 8 项以后不做入场:那是首屏之外,滚动出来时再飞一次只会拖慢滚动。
class SzEnter extends StatelessWidget {
  const SzEnter({
    super.key,
    required this.index,
    required this.child,
    this.dy = 12,
  });

  final int index;
  final Widget child;
  final double dy;

  @override
  Widget build(BuildContext context) {
    if (index >= 8 || SzMotion.off(context)) return child;
    final enter = Theme.of(context).szMotion.enter;
    final delay = SzMotion.staggerAt(index);
    final total = SzMotion.base + delay;
    final start = delay.inMicroseconds / total.inMicroseconds;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: total,
      builder: (context, t, child) {
        final k = ((t - start) / (1 - start)).clamp(0.0, 1.0);
        return Opacity(
          opacity: SzMotion.standard.transform(k),
          child: Transform.translate(
            offset: Offset(0, dy * (1 - enter.transform(k))),
            child: child,
          ),
        );
      },
      child: child,
    );
  }
}

/// 按压反馈:按下 scale .97(120ms),松开回 1。给实底主按钮包一层。
class SzPressScale extends StatefulWidget {
  const SzPressScale({super.key, required this.child, this.enabled = true});

  final Widget child;
  final bool enabled;

  @override
  State<SzPressScale> createState() => _SzPressScaleState();
}

class _SzPressScaleState extends State<SzPressScale> {
  bool _down = false;

  void _set(bool v) {
    if (!widget.enabled || _down == v) return;
    setState(() => _down = v);
  }

  @override
  Widget build(BuildContext context) {
    return Listener(
      onPointerDown: (_) => _set(true),
      onPointerUp: (_) => _set(false),
      onPointerCancel: (_) => _set(false),
      child: AnimatedScale(
        scale: _down ? 0.97 : 1,
        duration: SzMotion.of(context, SzMotion.fast),
        curve: SzMotion.standard,
        child: widget.child,
      ),
    );
  }
}

/// 06 抢单 / 接单成功:按钮 opacity→0(120ms),成功块 scale .8→1
/// (用户/商家 320ms spring;骑手 220ms standard),切换那一刻震动 medium。
///
/// [done] 由调用方在接口成功后置 true;「800ms 后自动跳转」也归调用方
/// (这里只管画),见 [SzSuccessSwap.hold]。
class SzSuccessSwap extends StatefulWidget {
  const SzSuccessSwap({
    super.key,
    required this.done,
    required this.button,
    required this.success,
  });

  final bool done;
  final Widget button;
  final Widget success;

  /// 成功态停留多久再跳走
  static const hold = Duration(milliseconds: 800);

  @override
  State<SzSuccessSwap> createState() => _SzSuccessSwapState();
}

class _SzSuccessSwapState extends State<SzSuccessSwap> {
  @override
  void didUpdateWidget(covariant SzSuccessSwap old) {
    super.didUpdateWidget(old);
    if (widget.done && !old.done) HapticFeedback.mediumImpact();
  }

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(context).szMotion;
    final off = SzMotion.off(context);
    return Stack(
      alignment: Alignment.center,
      children: [
        AnimatedOpacity(
          opacity: widget.done ? 0 : 1,
          duration: off ? Duration.zero : SzMotion.fast,
          child: IgnorePointer(ignoring: widget.done, child: widget.button),
        ),
        Positioned.fill(
          child: IgnorePointer(
            ignoring: !widget.done,
            child: AnimatedOpacity(
              opacity: widget.done ? 1 : 0,
              duration: off ? Duration.zero : SzMotion.fast,
              child: AnimatedScale(
                scale: widget.done ? 1 : 0.8,
                duration: off ? Duration.zero : style.success,
                curve: style.bouncy ? SzMotion.spring : SzMotion.standard,
                child: widget.success,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// 07 商家新单提醒:卡片外圈一圈 clay 光晕 0→6px→0,600ms × [times]。
///
/// 每当 [trigger] 变了(来了新单)就播一轮;第一次建出来时 [playOnMount]
/// 决定播不播 —— 冷启动时列表里已有的单不该集体闪一遍。
class SzAttention extends StatefulWidget {
  const SzAttention({
    super.key,
    required this.child,
    this.trigger,
    this.times = 3,
    this.playOnMount = true,
    this.radius = kRadiusMd,
  });

  final Widget child;
  final Object? trigger;
  final int times;
  final bool playOnMount;
  final double radius;

  @override
  State<SzAttention> createState() => _SzAttentionState();
}

class _SzAttentionState extends State<SzAttention>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: Duration(milliseconds: 600 * widget.times),
  );

  @override
  void initState() {
    super.initState();
    if (widget.playOnMount) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _play());
    }
  }

  @override
  void didUpdateWidget(covariant SzAttention old) {
    super.didUpdateWidget(old);
    if (widget.trigger != old.trigger) _play();
  }

  void _play() {
    if (!mounted || SzMotion.off(context)) return;
    _c.forward(from: 0);
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final clay = Theme.of(context).sz.clay;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, child) {
        // 每 600ms 一个来回:sin 从 0 到峰值再回 0
        final phase = (_c.value * widget.times) % 1.0;
        final k = _c.isAnimating ? math.sin(phase * math.pi) : 0.0;
        return DecoratedBox(
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(widget.radius),
            boxShadow: k <= 0
                ? const []
                : [
                    BoxShadow(
                      color: clay.withValues(alpha: .28),
                      spreadRadius: 6 * k,
                    ),
                  ],
          ),
          child: child,
        );
      },
      child: widget.child,
    );
  }
}

/// 「新单」字样和光晕同频闪 [times] 次(opacity 1 → .25 → 1,600ms 一次)。
class SzBlink extends StatefulWidget {
  const SzBlink({super.key, required this.child, this.trigger, this.times = 3});

  final Widget child;
  final Object? trigger;
  final int times;

  @override
  State<SzBlink> createState() => _SzBlinkState();
}

class _SzBlinkState extends State<SzBlink> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: Duration(milliseconds: 600 * widget.times),
  );

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && !SzMotion.off(context)) _c.forward(from: 0);
    });
  }

  @override
  void didUpdateWidget(covariant SzBlink old) {
    super.didUpdateWidget(old);
    if (widget.trigger != old.trigger && !SzMotion.off(context)) {
      _c.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      builder: (context, child) {
        final phase = (_c.value * widget.times) % 1.0;
        final dim = _c.isAnimating ? math.sin(phase * math.pi) : 0.0;
        return Opacity(opacity: 1 - 0.75 * dim, child: child);
      },
      child: widget.child,
    );
  }
}

/// 角标出现:scale 0→1 spring(320ms)。数字变化不重播,只在从无到有时弹一下。
class SzPopBadge extends StatelessWidget {
  const SzPopBadge({super.key, required this.show, required this.child});

  final bool show;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return AnimatedScale(
      scale: show ? 1 : 0,
      duration: SzMotion.of(context, SzMotion.slow),
      curve: show ? SzMotion.spring : SzMotion.exit,
      child: child,
    );
  }
}

/// 09 账本数字:0 → 终值 900ms standard,等宽数字不跳宽。
///
/// 第一次建出来时从 0 滚上去;之后值变了(轮询到新单)从旧值滚到新值;
/// [replayKey] 变了(下拉刷新)才从 0 再滚一次。切 tab 回来不重播 ——
/// 那时 State 还在,值没变就什么都不做。
class SzRollingAmount extends StatefulWidget {
  const SzRollingAmount({
    super.key,
    required this.cents,
    required this.style,
    this.prefix = '¥',
    this.decimals = 2,
    this.replayKey,
  });

  final int cents;
  final TextStyle style;
  final String prefix;
  final int decimals;
  final Object? replayKey;

  @override
  State<SzRollingAmount> createState() => _SzRollingAmountState();
}

class _SzRollingAmountState extends State<SzRollingAmount> {
  double _from = 0;

  @override
  void didUpdateWidget(covariant SzRollingAmount old) {
    super.didUpdateWidget(old);
    if (widget.replayKey != old.replayKey) {
      _from = 0;
    } else if (widget.cents != old.cents) {
      _from = old.cents.toDouble();
    }
  }

  @override
  Widget build(BuildContext context) {
    final target = widget.cents.toDouble();
    if (SzMotion.off(context)) {
      return Text(szYuanText(widget.cents, widget.prefix, widget.decimals),
          style: widget.style);
    }
    return TweenAnimationBuilder<double>(
      key: ValueKey(widget.replayKey),
      tween: Tween(begin: _from, end: target),
      duration: SzMotion.ledger,
      curve: SzMotion.standard,
      builder: (context, v, _) => Text(
          szYuanText(v.round(), widget.prefix, widget.decimals),
          style: widget.style),
    );
  }
}

/// 分 → 「¥1,206.35」。千分位是给眼睛分组用的,金额一过千就读不准。
String szYuanText(int cents, [String prefix = '¥', int decimals = 2]) {
  final neg = cents < 0;
  final abs = cents.abs();
  final whole = abs ~/ 100;
  final frac = abs % 100;
  final s = whole.toString();
  final buf = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) buf.write(',');
    buf.write(s[i]);
  }
  final tail = decimals <= 0
      ? ''
      : '.${frac.toString().padLeft(2, '0').substring(0, math.min(2, decimals))}';
  return '${neg ? '−' : ''}$prefix$buf$tail';
}

/// 分账条的一段。
@immutable
class SzSplitPart {
  const SzSplitPart(this.value, this.color, {this.opacity = 1});

  final num value;
  final Color color;
  final double opacity;
}

/// 09 分账条:每段宽度 0→占比,900ms standard,段间 delay 120ms。
///
/// 占比按真实金额算(比例失真的图比没有图更糟);某段是 0 就不画。
/// [replayKey] 同 [SzRollingAmount]。
class SzSplitBar extends StatelessWidget {
  const SzSplitBar({
    super.key,
    required this.parts,
    this.height = 10,
    this.gap = 3,
    this.track,
    this.replayKey,
  });

  final List<SzSplitPart> parts;
  final double height;
  final double gap;
  final Color? track;
  final Object? replayKey;

  @override
  Widget build(BuildContext context) {
    final shown = [for (final p in parts) if (p.value > 0) p];
    final total = shown.fold<double>(0, (a, p) => a + p.value.toDouble());
    final off = SzMotion.off(context);
    return ClipRRect(
      borderRadius: BorderRadius.circular(999),
      child: Container(
        height: height,
        color: track,
        child: total <= 0
            ? null
            : LayoutBuilder(builder: (context, box) {
                final usable =
                    math.max(0.0, box.maxWidth - gap * (shown.length - 1));
                final stagger = const Duration(milliseconds: 120);
                final total2 = SzMotion.ledger + stagger * (shown.length - 1);
                return TweenAnimationBuilder<double>(
                  key: ValueKey(replayKey),
                  tween: Tween(begin: off ? 1 : 0, end: 1),
                  duration: off ? Duration.zero : total2,
                  builder: (context, t, _) {
                    final children = <Widget>[];
                    for (var i = 0; i < shown.length; i++) {
                      final p = shown[i];
                      final start = (stagger * i).inMicroseconds /
                          total2.inMicroseconds;
                      final end = start +
                          SzMotion.ledger.inMicroseconds /
                              total2.inMicroseconds;
                      final k = off
                          ? 1.0
                          : SzMotion.standard.transform(
                              ((t - start) / (end - start)).clamp(0.0, 1.0));
                      if (i > 0) children.add(SizedBox(width: gap));
                      children.add(Container(
                        width: usable * (p.value / total) * k,
                        color: p.color.withValues(alpha: p.opacity),
                      ));
                    }
                    return Row(children: children);
                  },
                );
              }),
      ),
    );
  }
}

/// 10 开关:滑块 x 0→24 200ms spring,轨道色 220ms,拨动时震动 light。
///
/// 开 = earn(「在营业 / 在售」是好事),关 = 发丝线再压一档。
/// [small] 是菜单行里的小号(36×20),默认是营业开关那种大号(56×32)。
class SzSwitch extends StatelessWidget {
  const SzSwitch({
    super.key,
    required this.value,
    required this.onChanged,
    this.small = false,
    this.semanticLabel,
  });

  final bool value;
  final ValueChanged<bool>? onChanged;
  final bool small;
  final String? semanticLabel;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final w = small ? 36.0 : 56.0;
    final h = small ? 20.0 : 32.0;
    final inset = small ? 2.0 : 3.0;
    final knob = h - inset * 2;
    final offTrack = Color.alphaBlend(sz.ink.withValues(alpha: .05), sz.line);
    final enabled = onChanged != null;
    return Semantics(
      toggled: value,
      enabled: enabled,
      label: semanticLabel,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: !enabled
            ? null
            : () {
                HapticFeedback.lightImpact();
                onChanged!(!value);
              },
        // 视觉 36×20 太小,点击区撑到 48(菜单一行一个,戴手套也按得到)
        child: ConstrainedBox(
          constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
          child: Center(
            child: AnimatedContainer(
              duration: SzMotion.of(context, SzMotion.base),
              curve: SzMotion.standard,
              width: w,
              height: h,
              decoration: BoxDecoration(
                color: (value ? sz.earn : offTrack)
                    .withValues(alpha: enabled ? 1 : .5),
                borderRadius: BorderRadius.circular(h / 2),
              ),
              padding: EdgeInsets.all(inset),
              child: AnimatedAlign(
                duration: SzMotion.of(context, const Duration(milliseconds: 200)),
                curve: SzMotion.spring,
                alignment:
                    value ? Alignment.centerRight : Alignment.centerLeft,
                child: Container(
                  width: knob,
                  height: knob,
                  decoration: BoxDecoration(
                    color: sz.surface,
                    shape: BoxShape.circle,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 04 订单状态推进。
///
/// 每推进一格:线段 scaleX 0→1(220ms standard),然后终点圆 scale .6→1
/// (120ms spring);已过 earn、当前 clay、未到 line。状态文字的 crossfade
/// 归调用方(一个 AnimatedSwitcher 就够)。
class SzProgressRail extends StatefulWidget {
  const SzProgressRail({
    super.key,
    required this.labels,
    required this.step,
    this.dots = true,
    this.fontSize = kFontMicro,
  });

  /// 节点名,如「已接单 / 已取餐 / 配送中 / 送达」
  final List<String> labels;

  /// 当前在第几格(0 起);-1 = 还没开始(整条是灰的)
  final int step;
  final bool dots;
  final double fontSize;

  @override
  State<SzProgressRail> createState() => _SzProgressRailState();
}

class _SzProgressRailState extends State<SzProgressRail>
    with SingleTickerProviderStateMixin {
  // 一格 340ms:线 220 + 点 120
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 340),
    value: 1,
  );

  @override
  void didUpdateWidget(covariant SzProgressRail old) {
    super.didUpdateWidget(old);
    if (widget.step > old.step && !SzMotion.off(context)) {
      _c.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final step = widget.step;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        final line = SzMotion.standard
            .transform(const Interval(0, 220 / 340).transform(_c.value));
        final dotK = SzMotion.spring
            .transform(const Interval(220 / 340, 1).transform(_c.value));
        final row = <Widget>[];
        for (var i = 0; i < widget.labels.length; i++) {
          final done = i < step;
          final cur = i == step;
          final color = done ? sz.earn : cur ? sz.clay : sz.inkFaint;
          final scale = cur ? (0.6 + 0.4 * dotK) : 1.0;
          row.add(Row(mainAxisSize: MainAxisSize.min, children: [
            if (widget.dots) ...[
              Transform.scale(
                scale: scale,
                child: Container(
                  width: 7,
                  height: 7,
                  decoration: BoxDecoration(
                    color: done ? sz.earn : cur ? sz.clay : sz.line,
                    shape: BoxShape.circle,
                  ),
                ),
              ),
              const SizedBox(width: 4),
            ],
            Text(widget.labels[i],
                style: TextStyle(
                    fontSize: widget.fontSize,
                    height: 1.2,
                    fontWeight: cur ? FontWeight.w600 : FontWeight.w400,
                    color: color)),
          ]));
          if (i < widget.labels.length - 1) {
            // 线段:底是发丝线,走过的铺 earn;刚走进来的那一段(i == step-1)
            // 按动画从左往右画(设计稿:scaleX 0→1)
            final fill = i < step - 1 ? 1.0 : (i == step - 1 ? line : 0.0);
            row.add(Expanded(
              child: Container(
                height: widget.dots ? 2 : 1,
                margin: const EdgeInsets.symmetric(horizontal: 6),
                color: sz.line,
                alignment: Alignment.centerLeft,
                child: FractionallySizedBox(
                  widthFactor: fill,
                  child: Container(color: sz.earn),
                ),
              ),
            ));
          }
        }
        return Row(children: row);
      },
    );
  }
}

/// 08 核销成功:圆环 draw → 勾 draw → 文字 → 三格错落,总长约 800ms,
/// 结束时震动一次。环/勾/文字的区间照设计稿:ring 0–.4 / tick .33–.6 /
/// text .5–.75(三格在它后面各差 40ms,见 [SzCheckDraw.tileDelay])。
class SzCheckDraw extends StatefulWidget {
  const SzCheckDraw({super.key, this.size = 64, this.play = true});

  final double size;
  final bool play;

  /// 调用方给「核销成功」文字、三格数字排的延迟(相对动画开始)
  static const textDelay = Duration(milliseconds: 400);
  static Duration tileDelay(int i) => Duration(milliseconds: 480 + 40 * i);

  @override
  State<SzCheckDraw> createState() => _SzCheckDrawState();
}

class _SzCheckDrawState extends State<SzCheckDraw>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 800),
  );

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !widget.play) return;
      if (SzMotion.off(context)) {
        _c.value = 1;
      } else {
        _c.forward().whenComplete(() => HapticFeedback.heavyImpact());
      }
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) => CustomPaint(
        size: Size.square(widget.size),
        painter: _CheckPainter(
          ring: SzMotion.standard
              .transform(const Interval(0, .4).transform(_c.value)),
          tick: SzMotion.standard
              .transform(const Interval(.33, .6).transform(_c.value)),
          track: sz.line,
          color: sz.earn,
        ),
      ),
    );
  }
}

class _CheckPainter extends CustomPainter {
  _CheckPainter({
    required this.ring,
    required this.tick,
    required this.track,
    required this.color,
  });

  final double ring;
  final double tick;
  final Color track;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width / 64; // 设计稿画在 64×64 上
    final c = Offset(size.width / 2, size.height / 2);
    final r = 28 * s;
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3 * s
      ..color = track;
    canvas.drawCircle(c, r, base);
    final arc = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3 * s
      ..strokeCap = StrokeCap.round
      ..color = color;
    canvas.drawArc(Rect.fromCircle(center: c, radius: r), -math.pi / 2,
        2 * math.pi * ring, false, arc);
    if (tick <= 0) return;
    final path = Path()
      ..moveTo(20 * s, 33 * s)
      ..lineTo(29 * s, 41 * s)
      ..lineTo(45 * s, 24 * s);
    final metric = path.computeMetrics().first;
    canvas.drawPath(
      metric.extractPath(0, metric.length * tick),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 4 * s
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round
        ..color = color,
    );
  }

  @override
  bool shouldRepaint(covariant _CheckPainter old) =>
      old.ring != ring || old.tick != tick || old.color != color;
}

/// 延迟出现:[delay] 之后 opacity 0→1、y +8→0(220ms)。成功态里的文字和三格用。
class SzDelayedIn extends StatelessWidget {
  const SzDelayedIn({
    super.key,
    required this.delay,
    required this.child,
    this.dy = 8,
    this.curve,
  });

  final Duration delay;
  final Widget child;
  final double dy;

  /// 位移曲线;不给就用各端的出场曲线(用户/商家 spring、骑手 standard)
  final Curve? curve;

  @override
  Widget build(BuildContext context) {
    if (SzMotion.off(context)) return child;
    final enter = curve ?? Theme.of(context).szMotion.enter;
    final total = delay + SzMotion.base;
    final start = delay.inMicroseconds / total.inMicroseconds;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: total,
      builder: (context, t, child) {
        final k = ((t - start) / (1 - start)).clamp(0.0, 1.0);
        return Opacity(
          opacity: SzMotion.standard.transform(k),
          child: Transform.translate(
              offset: Offset(0, dy * (1 - enter.transform(k))), child: child),
        );
      },
      child: child,
    );
  }
}

/// 03 频道条切换时的列表:旧页 opacity→0 + x∓12,新页从另一侧进来,同时进行。
/// 方向由 [index] 比上一次大还是小决定。
class SzDirectionalSwitcher extends StatefulWidget {
  const SzDirectionalSwitcher({
    super.key,
    required this.index,
    required this.child,
  });

  final int index;
  final Widget child;

  @override
  State<SzDirectionalSwitcher> createState() => _SzDirectionalSwitcherState();
}

class _SzDirectionalSwitcherState extends State<SzDirectionalSwitcher> {
  int _dir = 1;

  @override
  void didUpdateWidget(covariant SzDirectionalSwitcher old) {
    super.didUpdateWidget(old);
    if (widget.index != old.index) _dir = widget.index > old.index ? 1 : -1;
  }

  @override
  Widget build(BuildContext context) {
    final dir = _dir;
    return AnimatedSwitcher(
      duration: SzMotion.of(context, SzMotion.base),
      switchInCurve: SzMotion.standard,
      switchOutCurve: SzMotion.standard,
      layoutBuilder: (current, previous) => Stack(
        alignment: Alignment.topCenter,
        children: [...previous, if (current != null) current],
      ),
      transitionBuilder: (child, anim) {
        final incoming = child.key == ValueKey(widget.index);
        return AnimatedBuilder(
          animation: anim,
          child: child,
          builder: (context, child) {
            // 进来的从 +12·dir 滑到 0;出去的(anim 从 1 退到 0)滑向 -12·dir
            final dx = incoming ? 12.0 * dir * (1 - anim.value)
                                : -12.0 * dir * (1 - anim.value);
            return Opacity(
              opacity: anim.value,
              child: Transform.translate(offset: Offset(dx, 0), child: child),
            );
          },
        );
      },
      child: KeyedSubtree(key: ValueKey(widget.index), child: widget.child),
    );
  }
}
