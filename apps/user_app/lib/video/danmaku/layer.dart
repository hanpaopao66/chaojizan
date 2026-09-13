import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';

import '../models.dart';
import '../player/player_logic.dart';
import '../player/sz_video_controller.dart';
import 'danmaku_controller.dart';
import 'engine.dart';

/// 弹幕层(#360):`CustomPainter` + `Ticker`,每帧把当前视频时间喂给 [DanmakuEngine],按它算的位置画。
///
/// ## 时间怎么跟播放器对齐
///
/// 播放器大约 100ms 报一次位置,直接拿它画弹幕会一顿一顿的。所以每次报位置时记一个锚点
/// (位置, 墙上时刻, 倍速),两次报位置之间按「锚点 + 过去的墙上时间 × 倍速」外推;
/// 暂停、缓冲时不外推(弹幕跟着停);长按 3 倍速时倍速是 3,弹幕也跟着飞快。
///
/// 外推和实际位置难免差几十毫秒。新报来的位置比外推值**小**时不往回退(画面上会抖),
/// 停住等外推值被追上;差得太远(超过 1 秒)就当成跳了进度,让引擎按新时间重建。
///
/// 不透明度用外面套一层 [Opacity] 做,不改每条弹幕的颜色 —— 字和描边各自半透明叠在一起,
/// 描边会把字盖脏。
class DanmakuLayer extends StatefulWidget {
  const DanmakuLayer({super.key, required this.controller});

  final SzVideoController controller;

  @override
  State<DanmakuLayer> createState() => DanmakuLayerState();
}

class DanmakuLayerState extends State<DanmakuLayer> with SingleTickerProviderStateMixin {
  late final Ticker _ticker = createTicker(_onTick);
  late final DanmakuEngine _engine = DanmakuEngine(measure: _measure);
  final ValueNotifier<int> _repaint = ValueNotifier(0);
  final Stopwatch _wall = Stopwatch()..start();
  final TextPainter _measurer = TextPainter(textDirection: TextDirection.ltr, maxLines: 1);
  final Map<int, _Painted> _cache = {};

  int _anchorPos = 0;
  int _anchorWall = 0;
  double _rate = 1;
  bool _moving = false;
  int _display = 0;
  int _seenVersion = -1;
  int _seenSent = 0;

  SzVideoController get _c => widget.controller;
  DanmakuController get _d => _c.danmaku;

  @override
  void initState() {
    super.initState();
    _seenSent = _d.sentSeq;
    _c.addListener(_onPlayer);
    _d.addListener(_onDanmaku);
    PaintingBinding.instance.systemFonts.addListener(_onFonts);
    _anchorPos = _display = _c.position.inMilliseconds;
    _onPlayer();
  }

  /// 网页版的中文回落字体是第一次用到时才下载的:下载完之前排出来的字是方框(豆腐块),
  /// 宽度也不对。框架自己的 Text 会自动重排,这里自己缓存的 TextPainter 不会 —— 清掉重量重画。
  void _onFonts() {
    for (final p in _cache.values) {
      p.dispose();
    }
    _cache.clear();
    _engine.remeasure();
    _repaint.value++;
  }

  @override
  void didUpdateWidget(DanmakuLayer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.controller, widget.controller)) {
      oldWidget.controller.removeListener(_onPlayer);
      oldWidget.controller.danmaku.removeListener(_onDanmaku);
      widget.controller.addListener(_onPlayer);
      widget.controller.danmaku.addListener(_onDanmaku);
      _seenVersion = -1;
      _seenSent = _d.sentSeq;
      _engine.seek(_c.position.inMilliseconds);
    }
  }

  @override
  void dispose() {
    _c.removeListener(_onPlayer);
    _d.removeListener(_onDanmaku);
    PaintingBinding.instance.systemFonts.removeListener(_onFonts);
    _ticker.dispose();
    _repaint.dispose();
    _measurer.dispose();
    for (final p in _cache.values) {
      p.dispose();
    }
    super.dispose();
  }

  /// 点在 [p] 上的弹幕(播放器单击时先问这里:点中弹幕就出弹幕菜单,没点中才是显示 / 隐藏控件)
  Danmaku? hitTest(Offset p) => _engine.hitTest(p.dx, p.dy)?.item;

  // ---------------------------------------------------------------- 时钟

  int _estimate(int wall) => _moving ? _anchorPos + ((wall - _anchorWall) * _rate).round() : _anchorPos;

  void _onPlayer() {
    if (!mounted) return;
    final pos = _c.position.inMilliseconds;
    final wall = _wall.elapsedMilliseconds;
    final jumped = (pos - _estimate(wall)).abs() > 1000;
    _anchorPos = pos;
    _anchorWall = wall;
    _rate = effectiveSpeed(_c.speed, boosting: _c.boosting);
    _moving = _c.playing && !_c.buffering && _c.error == null;
    if (jumped) _display = pos;
    if (_moving) {
      if (!_ticker.isActive) _ticker.start();
    } else {
      if (_ticker.isActive) _ticker.stop();
      // 停着的时候不外推:直接对到播放器报的位置(拖进度条往回拖也在这里重建)
      _advanceTo(pos);
    }
  }

  void _onDanmaku() {
    if (!mounted) return;
    // 设置变了(字号、速度、显示区域)要重新 configure,那在 build 里做
    setState(() {});
    if (!_moving) _advanceTo(_display);
  }

  void _onTick(Duration _) {
    _advanceTo(max(_display, _estimate(_wall.elapsedMilliseconds)));
  }

  void _advanceTo(int t) {
    _display = t;
    _syncData();
    _engine.advance(t);
    _repaint.value++;
  }

  /// 先把自己刚发的硬塞上屏,再同步列表 —— 顺序反过来的话,新列表里多了一条「过去的」弹幕,
  /// 引擎会判成窗口变了、整屏重建,刚发的那条反而可能因为没空轨道被丢掉。
  void _syncData() {
    for (final m in _d.sentSince(_seenSent)) {
      // 在别的页面(全屏)发的、隔了很久才回到这一层的,不硬塞,按普通弹幕排
      if ((m.timeMs - _display).abs() < 5000) _engine.insertNow(m);
    }
    _seenSent = _d.sentSeq;
    if (_d.version != _seenVersion) {
      _seenVersion = _d.version;
      _engine.setItems(_d.visible);
    }
  }

  // ---------------------------------------------------------------- 画

  static TextStyle _style(double fs, {Color? color, Paint? foreground}) => TextStyle(
        fontSize: fs,
        height: 1.2,
        fontWeight: FontWeight.w600,
        color: foreground == null ? color : null,
        foreground: foreground,
      );

  double _measure(String text, double fontSize) {
    _measurer.text = TextSpan(text: text, style: _style(fontSize));
    _measurer.layout();
    return _measurer.width;
  }

  _Painted _painted(DanmakuSlot s) {
    final hit = _cache[s.item.id];
    if (hit != null && hit.fontSize == s.fontSize && identical(hit.item, s.item)) return hit;
    hit?.dispose();
    final color = Color(0xFF000000 | (s.item.color & 0xFFFFFF));
    // 深色字配白描边,其余配黑描边:黑字黑描边等于一坨黑
    final dark = color.computeLuminance() < 0.12;
    final stroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = max(1.5, s.fontSize / 11)
      ..strokeJoin = StrokeJoin.round
      ..color = (dark ? Colors.white : Colors.black).withValues(alpha: .72);
    final fill = TextPainter(
      text: TextSpan(text: s.item.text, style: _style(s.fontSize, color: color)),
      textDirection: TextDirection.ltr,
      maxLines: 1,
    )..layout();
    final outline = TextPainter(
      text: TextSpan(text: s.item.text, style: _style(s.fontSize, foreground: stroke)),
      textDirection: TextDirection.ltr,
      maxLines: 1,
    )..layout();
    final p = _Painted(item: s.item, fontSize: s.fontSize, fill: fill, outline: outline);
    _cache[s.item.id] = p;
    return p;
  }

  static final Paint _border = Paint()
    ..style = PaintingStyle.stroke
    ..strokeWidth = 1.2
    ..color = Colors.white.withValues(alpha: .9);

  void _paint(Canvas canvas, Size size) {
    final e = _engine;
    final trackH = e.trackHeight;
    final now = e.nowMs;
    final alive = <int>{};
    for (final s in e.active) {
      final x = e.xOf(s, now);
      if (x > size.width || x + s.width < 0) continue;
      final p = _painted(s);
      alive.add(s.item.id);
      final y = e.yOf(s) + (trackH - p.fill.height) / 2;
      p.outline.paint(canvas, Offset(x, y));
      p.fill.paint(canvas, Offset(x, y));
      if (s.item.mine) {
        // 自己发的带边框(§5.10),一眼认得出哪条是自己的
        canvas.drawRRect(
          RRect.fromRectAndRadius(Rect.fromLTWH(x - 4, y - 1, s.width + 8, p.fill.height + 2), const Radius.circular(4)),
          _border,
        );
      }
    }
    // 缓存里不在屏上的清掉(留一点余量,别每帧都扫)
    if (_cache.length > alive.length + 48) {
      _cache.removeWhere((id, p) {
        if (alive.contains(id)) return false;
        p.dispose();
        return true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = _d.settings;
    return LayoutBuilder(builder: (context, box) {
      final size = box.biggest;
      // 标准字号跟着画面高度走:竖屏小窗(约 220 高)是 25 × 0.62 ≈ 15.5,横屏全屏(约 390 高)是 25。
      // 固定 25 的话小窗里一屏只放得下五六行,字还压着半个画面
      final viewScale = size.height <= 0 ? 1.0 : (size.height / 360).clamp(0.62, 1.0);
      _engine.configure(
        width: size.width,
        height: size.height,
        fontSize: DanmakuEngine.standardSize * viewScale * s.fontScale,
        speed: s.speed,
        area: s.area,
      );
      return Opacity(
        opacity: s.opacity,
        child: CustomPaint(size: size, painter: _DanmakuPainter(this)),
      );
    });
  }
}

class _DanmakuPainter extends CustomPainter {
  _DanmakuPainter(this.state) : super(repaint: state._repaint);

  final DanmakuLayerState state;

  @override
  void paint(Canvas canvas, Size size) => state._paint(canvas, size);

  @override
  bool shouldRepaint(covariant _DanmakuPainter old) => true;
}

class _Painted {
  _Painted({required this.item, required this.fontSize, required this.fill, required this.outline});

  final Danmaku item;
  final double fontSize;
  final TextPainter fill;
  final TextPainter outline;

  void dispose() {
    fill.dispose();
    outline.dispose();
  }
}
