import 'dart:math';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import 'player_logic.dart';
import 'sz_video_controller.dart';

/// 播放器永远是黑底,强调色取深色态的黏土橘(浅色态那个在黑底上偏暗)。
final Color kPlayerAccent = SzColors.dark.clay;

/// 播放器上的字都是白的;时间、提示用这几个样式。
const TextStyle kPlayerText = TextStyle(color: Colors.white, fontSize: kFontBody);
const TextStyle kPlayerNote = TextStyle(color: Colors.white, fontSize: kFontNote);
const TextStyle kPlayerMicro = TextStyle(color: Colors.white, fontSize: kFontMicro);

/// 雪碧图缓存键:地址带签名和到期时间,换一次签名地址就变 —— 按「分 P + 第几张」缓存才命中得了
String spriteCacheKey(int partId, int sheet) => 'vsprite-$partId-$sheet';

/// 拖进度条前把这一 P 的雪碧图都预取一下(最多 4 张),拖起来缩略图才跟得上手指。
void precacheSprites(BuildContext context, SzVideoController c) {
  final s = c.part.sprite;
  if (s == null) return;
  for (var i = 0; i < s.urls.length; i++) {
    precacheImage(szNetImageKeyed(c.resolveUrl(s.urls[i]), spriteCacheKey(c.part.id, i)), context,
        onError: (_, __) {});
  }
}

/// 进度条缩略图:雪碧图里 [ms] 那一刻的那一格。
///
/// 格子用 [SpriteInfo.cellAt] 算(VIDEO-API 1.4)。显示那一格的做法:把整张雪碧图放大到
/// 「一格 = 这个框」的尺寸,用 [spriteAlignment] 算出的对齐值摆进一格大小的框,框外的裁掉。
class SpriteThumb extends StatelessWidget {
  const SpriteThumb({super.key, required this.controller, required this.ms, this.maxWidth = 160, this.maxHeight = 90});

  final SzVideoController controller;
  final int ms;
  final double maxWidth;
  final double maxHeight;

  @override
  Widget build(BuildContext context) {
    final s = controller.part.sprite;
    if (s == null) return const SizedBox.shrink();
    final size = spriteThumbSize(s, maxW: maxWidth, maxH: maxHeight);
    final cell = s.cellAt(ms);
    final box = BoxDecoration(
      color: Colors.black,
      borderRadius: BorderRadius.circular(kRadiusSm),
      border: Border.all(color: Colors.white.withValues(alpha: .7)),
    );
    if (cell == null) return Container(width: size.w, height: size.h, decoration: box);
    final a = spriteAlignment(col: cell.col, row: cell.row, cols: s.cols, rows: s.rows);
    final url = controller.resolveUrl(s.urls[cell.sheet]);
    return Container(
      width: size.w,
      height: size.h,
      decoration: box,
      clipBehavior: Clip.antiAlias,
      child: OverflowBox(
        alignment: Alignment(a.x, a.y),
        minWidth: size.w * s.cols,
        maxWidth: size.w * s.cols,
        minHeight: size.h * s.rows,
        maxHeight: size.h * s.rows,
        child: Image(
          image: szNetImageKeyed(url, spriteCacheKey(controller.part.id, cell.sheet)),
          fit: BoxFit.fill,
          gaplessPlayback: true,
          errorBuilder: (_, __, ___) => const SizedBox.shrink(),
        ),
      ),
    );
  }
}

/// 播放器的进度条:已播 / 已缓冲 / 拖动;上方叠高能进度条(弹幕密度曲线)。
///
/// 拖动时在手指上方显示雪碧图缩略图和目标时间,松手才跳(拖的过程中视频照常播);点一下直接跳。
class PlayerProgressBar extends StatefulWidget {
  const PlayerProgressBar({super.key, required this.controller, this.onScrub});

  final SzVideoController controller;

  /// 开始 / 结束拖动(拖着的时候外面别自动隐藏控件)
  final ValueChanged<bool>? onScrub;

  @override
  State<PlayerProgressBar> createState() => _PlayerProgressBarState();
}

class _PlayerProgressBarState extends State<PlayerProgressBar> {
  double? _drag;

  SzVideoController get _c => widget.controller;

  int get _durMs => _c.duration.inMilliseconds;

  void _start(double x, double w) {
    precacheSprites(context, _c);
    widget.onScrub?.call(true);
    setState(() => _drag = w <= 0 ? 0 : (x / w).clamp(0.0, 1.0));
  }

  void _update(double x, double w) {
    if (_drag == null) return;
    setState(() => _drag = w <= 0 ? 0 : (x / w).clamp(0.0, 1.0));
  }

  void _end() {
    final v = _drag;
    setState(() => _drag = null);
    widget.onScrub?.call(false);
    if (v != null) _c.seekTo(Duration(milliseconds: (v * _durMs).round()));
  }

  void _cancel() {
    setState(() => _drag = null);
    widget.onScrub?.call(false);
  }

  double _buffered() {
    final raw = _c.raw;
    if (raw == null || _durMs <= 0) return 0;
    var end = 0;
    for (final r in raw.value.buffered) {
      end = max(end, r.end.inMilliseconds);
    }
    return (end / _durMs).clamp(0.0, 1.0);
  }

  @override
  Widget build(BuildContext context) {
    final dur = _durMs;
    final pos = _c.position.inMilliseconds;
    final value = _drag ?? (dur > 0 ? (pos / dur).clamp(0.0, 1.0) : 0.0);
    final levels = _c.danmaku.showing ? _c.danmaku.densityLevels : const <double>[];
    return LayoutBuilder(builder: (context, box) {
      final w = box.maxWidth;
      return Semantics(
        label: '播放进度',
        value: '${playerClock(pos)} / ${playerClock(dur)}',
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onHorizontalDragStart: (d) => _start(d.localPosition.dx, w),
          onHorizontalDragUpdate: (d) => _update(d.localPosition.dx, w),
          onHorizontalDragEnd: (_) => _end(),
          onHorizontalDragCancel: _cancel,
          onTapUp: (d) {
            if (w > 0 && dur > 0) {
              _c.seekTo(Duration(milliseconds: (d.localPosition.dx / w * dur).round().clamp(0, dur)));
            }
          },
          child: SizedBox(
            height: 32,
            child: Stack(clipBehavior: Clip.none, children: [
              if (levels.any((x) => x > 0))
                Positioned(
                  left: 0,
                  right: 0,
                  top: 0,
                  height: 14,
                  child: CustomPaint(painter: _DensityPainter(levels: levels, played: value)),
                ),
              Positioned.fill(
                child: CustomPaint(
                  painter: _BarPainter(value: value, buffered: _buffered(), dragging: _drag != null),
                ),
              ),
              if (_drag != null) _preview(w, value, dur),
            ]),
          ),
        ),
      );
    });
  }

  Widget _preview(double w, double value, int dur) {
    final ms = (value * dur).round();
    final s = _c.part.sprite;
    final thumb = s == null ? null : spriteThumbSize(s);
    final double bw = max(thumb?.w ?? 0.0, 96.0);
    final double left = (value * w - bw / 2).clamp(0.0, max(0.0, w - bw));
    return Positioned(
      left: left,
      bottom: 30,
      width: bw,
      child: IgnorePointer(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (s != null) SpriteThumb(controller: _c, ms: ms),
          const SizedBox(height: 4),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(
              color: Colors.black.withValues(alpha: .6),
              borderRadius: BorderRadius.circular(kRadiusSm),
            ),
            child: Text('${playerClock(ms)} / ${playerClock(dur)}', style: kPlayerNote),
          ),
        ]),
      ),
    );
  }
}

class _BarPainter extends CustomPainter {
  _BarPainter({required this.value, required this.buffered, required this.dragging});

  final double value;
  final double buffered;
  final bool dragging;

  @override
  void paint(Canvas canvas, Size size) {
    final y = size.height / 2 + 4;
    final h = dragging ? 4.0 : 3.0;
    RRect bar(double to) =>
        RRect.fromLTRBR(0, y - h / 2, max(0, to * size.width), y + h / 2, Radius.circular(h / 2));
    canvas.drawRRect(bar(1), Paint()..color = Colors.white.withValues(alpha: .28));
    if (buffered > 0) canvas.drawRRect(bar(buffered), Paint()..color = Colors.white.withValues(alpha: .45));
    canvas.drawRRect(bar(value), Paint()..color = kPlayerAccent);
    final c = Offset(value * size.width, y);
    canvas.drawCircle(c, dragging ? 8 : 6, Paint()..color = Colors.white);
    canvas.drawCircle(c, dragging ? 3.5 : 2.5, Paint()..color = kPlayerAccent);
  }

  @override
  bool shouldRepaint(covariant _BarPainter old) =>
      old.value != value || old.buffered != buffered || old.dragging != dragging;
}

/// 高能进度条:每桶一个点连成平滑曲线,下面填半透明;已播过的那段染强调色。
class _DensityPainter extends CustomPainter {
  _DensityPainter({required this.levels, required this.played});

  final List<double> levels;
  final double played;

  @override
  void paint(Canvas canvas, Size size) {
    final n = levels.length;
    if (n == 0 || size.width <= 0) return;
    final path = Path()..moveTo(0, size.height);
    Offset at(int i) => Offset(n == 1 ? size.width / 2 : i / (n - 1) * size.width, size.height * (1 - levels[i]));
    var prev = at(0);
    path.lineTo(prev.dx, prev.dy);
    for (var i = 1; i < n; i++) {
      final p = at(i);
      final mid = Offset((prev.dx + p.dx) / 2, (prev.dy + p.dy) / 2);
      path.quadraticBezierTo(prev.dx, prev.dy, mid.dx, mid.dy);
      prev = p;
    }
    path
      ..lineTo(prev.dx, prev.dy)
      ..lineTo(size.width, size.height)
      ..close();
    canvas.drawPath(path, Paint()..color = Colors.white.withValues(alpha: .22));
    canvas.save();
    canvas.clipRect(Rect.fromLTWH(0, 0, played * size.width, size.height));
    canvas.drawPath(path, Paint()..color = kPlayerAccent.withValues(alpha: .55));
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant _DensityPainter old) => !identical(old.levels, levels) || old.played != played;
}

/// 播放器上的小图标按钮(白色、紧凑)。
class PlayerIconButton extends StatelessWidget {
  const PlayerIconButton({super.key, required this.icon, required this.tooltip, required this.onPressed, this.size = 24});

  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;
  final double size;

  @override
  Widget build(BuildContext context) => IconButton(
        tooltip: tooltip,
        onPressed: onPressed,
        icon: Icon(icon, color: Colors.white, size: size),
        padding: EdgeInsets.zero,
        constraints: const BoxConstraints.tightFor(width: 40, height: 40),
        visualDensity: VisualDensity.compact,
      );
}

/// 播放器上的文字按钮(倍速、清晰度、选集)。
class PlayerTextButton extends StatelessWidget {
  const PlayerTextButton({super.key, required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) => InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(kRadiusSm),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 10),
          child: Text(label, style: kPlayerText.copyWith(fontWeight: FontWeight.w600)),
        ),
      );
}

/// 半透明黑底的小胶囊(续播提示、切换提示、3 倍速提示)。
class PlayerPill extends StatelessWidget {
  const PlayerPill({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.black.withValues(alpha: .62),
          borderRadius: BorderRadius.circular(18),
        ),
        child: DefaultTextStyle(style: kPlayerNote, child: child),
      );
}
