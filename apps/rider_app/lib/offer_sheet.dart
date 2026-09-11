import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';

import 'hall_widgets.dart';

/// 新单推送(设计稿 5c):从底部推上来的一张单子,15 秒后自己收起。
///
/// ## 这 15 秒是什么
///
/// **不是抢单窗口。** 服务端没有「过期不能抢」这回事 —— 收起之后这单
/// 还在大厅里,谁都能抢。倒计时只管这张弹层自己在屏幕上待多久:
/// 骑手在路上不该被一张没理它的单子一直挡着。所以文案写「N 秒后收起」,
/// 不写「还有 N 秒可抢」,后者是在编一个不存在的截止时间。
///
/// 不接 = 什么都不发生。服务端没有「拒单」接口,也不记。
///
/// ## 为什么不走 szShowSheet
///
/// 动效规范 05:推上来 260ms standard、**不回弹**,消失比出现快。
/// 系统底部弹层的动画控制器不归我们管,所以做成页面里的一层浮层,
/// 时长和曲线都在这里。它也是骑行中唯一保留的动效(见 SzMotion.riding)。
class RiderOfferOverlay extends StatefulWidget {
  const RiderOfferOverlay({
    super.key,
    required this.order,
    required this.toShopText,
    required this.tripText,
    required this.infoLine,
    required this.sameWay,
    required this.grabbing,
    required this.grabbed,
    required this.onGrab,
    required this.onDismiss,
    this.vibrate = true,
  });

  final Order order;
  final String? toShopText;
  final String? tripText;

  /// 「预计出餐 12:01   用户参考送达 12:20」
  final String infoLine;
  final bool sameWay;
  final bool grabbing;

  /// 抢到了:按钮换成成功块,由上层在 [SzSuccessSwap.hold] 之后收起
  final bool grabbed;
  final VoidCallback onGrab;

  /// 不接 / 倒计时到点 / 点遮罩
  final VoidCallback onDismiss;
  final bool vibrate;

  static const window = Duration(seconds: 15);

  @override
  State<RiderOfferOverlay> createState() => _RiderOfferOverlayState();
}

class _RiderOfferOverlayState extends State<RiderOfferOverlay>
    with TickerProviderStateMixin {
  // 推上来 260ms standard;收起按「消失比出现快 40%」取 156ms exit
  late final AnimationController _slide = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 260),
    reverseDuration: const Duration(milliseconds: 156),
  );
  late final AnimationController _count = AnimationController(
    vsync: this,
    duration: RiderOfferOverlay.window,
  );
  Timer? _tick;
  int _left = RiderOfferOverlay.window.inSeconds;
  bool _closing = false;

  @override
  void initState() {
    super.initState();
    // 新单推送是「必要动效」:骑行中也照播,只有系统减少动态效果时直接到位
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (SzMotion.systemOff(context)) {
        _slide.value = 1;
      } else {
        _slide.forward();
      }
      if (widget.vibrate) HapticFeedback.heavyImpact();
      _count.forward();
      _tick = Timer.periodic(const Duration(seconds: 1), (_) {
        if (!mounted || widget.grabbed || widget.grabbing) return;
        setState(() => _left--);
        // 最后 3 秒每秒轻震一下:不看屏幕也知道它要收了
        if (_left > 0 && _left <= 3 && widget.vibrate) {
          HapticFeedback.lightImpact();
        }
        if (_left <= 0) _close();
      });
    });
  }

  @override
  void didUpdateWidget(covariant RiderOfferOverlay old) {
    super.didUpdateWidget(old);
    // 抢的过程中停住倒计时:这时候收起会让人以为没抢上
    if (widget.grabbing || widget.grabbed) {
      _count.stop();
    } else if (old.grabbing && !widget.grabbing && !widget.grabbed) {
      _count.forward();
    }
  }

  Future<void> _close() async {
    if (_closing) return;
    _closing = true;
    _tick?.cancel();
    if (!SzMotion.systemOff(context)) {
      await _slide.animateBack(0, curve: SzMotion.exit);
    }
    if (mounted) widget.onDismiss();
  }

  @override
  void dispose() {
    _tick?.cancel();
    _slide.dispose();
    _count.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final wide = szWidthOf(context).hasSideNav;
    final sheet = _sheet(context, sz);
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _close();
      },
      child: Stack(children: [
        // 遮罩:墨色 35%,点一下等于「不接」
        Positioned.fill(
          child: FadeTransition(
            opacity: _slide,
            child: GestureDetector(
              onTap: widget.grabbing || widget.grabbed ? null : _close,
              child: ColoredBox(color: sz.ink.withValues(alpha: .35)),
            ),
          ),
        ),
        Align(
          alignment: wide ? Alignment.center : Alignment.bottomCenter,
          child: AnimatedBuilder(
            animation: _slide,
            builder: (context, child) {
              final k = SzMotion.standard.transform(_slide.value);
              return FractionalTranslation(
                translation: Offset(0, wide ? 0.08 * (1 - k) : (1 - k)),
                child: Opacity(opacity: wide ? k : 1, child: child),
              );
            },
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: sheet,
            ),
          ),
        ),
      ]),
    );
  }

  Widget _sheet(BuildContext context, SzColors sz) {
    final o = widget.order;
    final accent = Theme.of(context).colorScheme.primary;
    final wide = szWidthOf(context).hasSideNav;
    return Material(
      color: sz.surface,
      borderRadius: wide
          ? BorderRadius.circular(20)
          : const BorderRadius.vertical(top: Radius.circular(20)),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 18, 18, 22),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Center(
                child: Container(
                  width: 36,
                  height: 4,
                  decoration: BoxDecoration(
                      color: sz.line, borderRadius: BorderRadius.circular(2)),
                ),
              ),
              const SizedBox(height: 14),
              Row(children: [
                Expanded(
                  child: Text(
                      '新单 · ${o.isErrand ? "帮我送" : o.merchantName}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: kFontNote,
                          letterSpacing: 1,
                          color: sz.inkMuted)),
                ),
                // 倒计时条:从满到空,15 秒 linear;数字每秒跳,不做过渡
                SizedBox(
                  width: 44,
                  height: 4,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(2),
                    child: AnimatedBuilder(
                      animation: _count,
                      builder: (context, _) => LinearProgressIndicator(
                        value: 1 - _count.value,
                        minHeight: 4,
                        color: sz.clay,
                        backgroundColor: sz.line,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                Text.rich(TextSpan(children: [
                  TextSpan(
                      text: '$_left',
                      style: szFigure(fontSize: kFontNote, color: sz.ink)),
                  TextSpan(
                      text: ' 秒后收起',
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ])),
              ]),
              const SizedBox(height: 14),
              Row(
                crossAxisAlignment: CrossAxisAlignment.baseline,
                textBaseline: TextBaseline.alphabetic,
                children: [
                  Text(szYuanText(HallOrderCard.riderTakeCents(o)),
                      style: szMoney(
                          fontSize: kFigureHero, color: sz.earn, height: 1)),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                        o.isErrand ? '跑腿费 − 平台 2%' : '配送费全额 · 平台不抽',
                        style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              Container(
                padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
                decoration: BoxDecoration(
                  color: sz.paper,
                  borderRadius: BorderRadius.circular(kRadiusMd),
                ),
                child: Column(children: [
                  _row(sz, true,
                      o.isErrand
                          ? '取件 · ${o.merchantAddress}'
                          : '${o.merchantName} · ${o.merchantAddress}',
                      widget.toShopText == null ? null : '距你 ${widget.toShopText}'),
                  const SizedBox(height: 8),
                  _row(sz, false, o.address,
                      widget.tripText == null ? null : '送程 ${widget.tripText}'),
                ]),
              ),
              if (widget.infoLine.isNotEmpty || widget.sameWay) ...[
                const SizedBox(height: 12),
                Wrap(spacing: 12, runSpacing: 4, children: [
                  if (widget.infoLine.isNotEmpty)
                    Text(widget.infoLine,
                        style: TextStyle(
                            fontSize: kFontNote, color: sz.inkMuted)),
                  if (widget.sameWay)
                    Text('与当前单顺路',
                        style: TextStyle(fontSize: kFontNote, color: sz.earn)),
                ]),
              ],
              const SizedBox(height: 16),
              SizedBox(
                height: 50,
                child: SzSuccessSwap(
                  done: widget.grabbed,
                  button: Row(children: [
                    OutlinedButton(
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(72, 50),
                        padding: const EdgeInsets.symmetric(horizontal: 20),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10)),
                      ),
                      onPressed: widget.grabbing ? null : _close,
                      child: const Text('不接'),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: SzPressScale(
                        enabled: !widget.grabbing,
                        child: FilledButton(
                          style: FilledButton.styleFrom(
                            backgroundColor: accent,
                            minimumSize: const Size.fromHeight(50),
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(10)),
                            textStyle: const TextStyle(
                                fontSize: kFontTitle,
                                fontWeight: FontWeight.w600),
                          ),
                          onPressed: widget.grabbing ? null : widget.onGrab,
                          child: Text(widget.grabbing ? '抢单中…' : '抢单'),
                        ),
                      ),
                    ),
                  ]),
                  success: Container(
                    decoration: BoxDecoration(
                      color: sz.earn,
                      borderRadius: BorderRadius.circular(10),
                    ),
                    alignment: Alignment.center,
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      Icon(Icons.check_circle, size: 20, color: sz.surface),
                      const SizedBox(width: 8),
                      Text('已抢到 · 去取餐',
                          style: TextStyle(
                              fontSize: kFontTitle,
                              fontWeight: FontWeight.w600,
                              color: sz.surface)),
                    ]),
                  ),
                ),
              ),
              const SizedBox(height: 10),
              Text('不接不扣分;收起后这单还在大厅里',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _row(SzColors sz, bool pickup, String text, String? trailing) =>
      Row(children: [
        SzPointDot(pickup: pickup),
        const SizedBox(width: 10),
        Expanded(
          child: Text(text,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
        ),
        if (trailing != null) ...[
          const SizedBox(width: 8),
          Text(trailing, style: szFigure(fontSize: kFontNote, color: sz.inkMuted)),
        ],
      ]);
}
