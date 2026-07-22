import 'package:flutter/material.dart';

import 'brand_art.dart';

/// 弹性入场:成功图标/空态插画用,scale 从 0.6 弹到 1 + 淡入。
class PopIn extends StatelessWidget {
  const PopIn({super.key, required this.child, this.delayMs = 0});

  final Widget child;
  final int delayMs;

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Duration(milliseconds: 450 + delayMs),
      curve: Interval(delayMs / (450 + delayMs), 1, curve: Curves.easeOutBack),
      builder: (context, t, child) => Opacity(
        opacity: t.clamp(0, 1),
        child: Transform.scale(scale: 0.6 + 0.4 * t, child: child),
      ),
      child: child,
    );
  }
}

/// 列表项进场:淡入 + 上滑,按 index 依次错开(只对前几项生效,避免长列表拖沓)。
class FadeSlideIn extends StatelessWidget {
  const FadeSlideIn({super.key, required this.index, required this.child});

  final int index;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    if (index >= 8) return child; // 首屏之外不做进场,滚动性能优先
    final delay = index * 45;
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: Duration(milliseconds: 320 + delay),
      curve: Interval(delay / (320 + delay), 1, curve: Curves.easeOutCubic),
      builder: (context, t, child) => Opacity(
        opacity: t,
        child: Transform.translate(
            offset: Offset(0, 16 * (1 - t)), child: child),
      ),
      child: child,
    );
  }
}

/// 列表加载骨架屏:灰色占位块 + 呼吸动画,替代满屏转圈。
class SkeletonList extends StatefulWidget {
  const SkeletonList({super.key, this.itemCount = 6, this.itemHeight = 88});

  final int itemCount;
  final double itemHeight;

  @override
  State<SkeletonList> createState() => _SkeletonListState();
}

class _SkeletonListState extends State<SkeletonList>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 900),
    lowerBound: 0.35,
    upperBound: 0.75,
  )..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final base = Theme.of(context).colorScheme.surfaceContainerHighest;
    return FadeTransition(
      opacity: _controller,
      child: ListView.builder(
        physics: const NeverScrollableScrollPhysics(),
        itemCount: widget.itemCount,
        itemBuilder: (context, i) => Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Row(
            children: [
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                    color: base, borderRadius: BorderRadius.circular(12)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                        height: 16,
                        width: 140,
                        decoration: BoxDecoration(
                            color: base,
                            borderRadius: BorderRadius.circular(4))),
                    const SizedBox(height: 8),
                    Container(
                        height: 12,
                        width: double.infinity,
                        decoration: BoxDecoration(
                            color: base,
                            borderRadius: BorderRadius.circular(4))),
                    const SizedBox(height: 6),
                    Container(
                        height: 12,
                        width: 180,
                        decoration: BoxDecoration(
                            color: base,
                            borderRadius: BorderRadius.circular(4))),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 空态:品牌插画(按图标语义自动匹配)+ 文案 + 可选动作按钮。
/// 没有匹配插画的图标退回灰图标展示,调用方无需改动。
class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.icon,
    required this.text,
    this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String text;
  final String? actionLabel;
  final VoidCallback? onAction;

  static final Map<IconData, BrandArt> _artByIcon = {
    Icons.storefront_outlined: BrandArt.bowl,
    Icons.ramen_dining: BrandArt.bowl,
    Icons.restaurant_menu: BrandArt.bowl,
    Icons.receipt_long: BrandArt.receipt,
    Icons.receipt_long_outlined: BrandArt.receipt,
    Icons.confirmation_number_outlined: BrandArt.ticket,
    Icons.local_activity_outlined: BrandArt.ticket,
    Icons.cloud_off: BrandArt.offline,
    Icons.wifi_off: BrandArt.offline,
    Icons.search_off: BrandArt.search,
    Icons.search: BrandArt.search,
    Icons.favorite_outline: BrandArt.bowl,
  };

  @override
  Widget build(BuildContext context) {
    final outline = Theme.of(context).colorScheme.outline;
    final art = _artByIcon[icon];
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopIn(
              child: art != null
                  ? BrandArtView(art, size: 132)
                  : Icon(icon, size: 64, color: outline.withValues(alpha: 0.5)),
            ),
            const SizedBox(height: 12),
            Text(text,
                textAlign: TextAlign.center,
                style: TextStyle(color: outline, height: 1.5)),
            if (actionLabel != null) ...[
              const SizedBox(height: 16),
              FilledButton.tonal(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}
