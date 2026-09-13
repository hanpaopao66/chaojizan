// 单稿数据的近 30 天折线图。自己用 CustomPainter 画,不引图表库 —— 就一条线、一个选中点,
// 为这个多带一个几百 KB 的依赖不值。坐标换算是纯函数,单测锁住。
import 'dart:math';

import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// y 轴顶到哪:不小于最大值的「整数」(1 / 2 / 5 × 10ⁿ)。全是 0 时取 1 —— 线贴着底边画出来,
/// 而不是除以 0 画成一片 NaN。
double chartCeil(num maxValue) {
  if (maxValue <= 0) return 1;
  final exp = (log(maxValue) / ln10).floor();
  final base = pow(10, exp).toDouble();
  for (final m in const [1, 2, 5, 10]) {
    if (m * base >= maxValue) return m * base;
  }
  return 10 * base;
}

/// 每个值在画布上的位置:x 在左右留白之间均分(只有一个点时放中间),
/// y 从底边往上按 [yMax] 缩放(不给就取 [chartCeil]);超出范围的夹到上下边。
List<Offset> chartPoints(List<num> values, Size size, {EdgeInsets pad = EdgeInsets.zero, double? yMax}) {
  if (values.isEmpty) return const [];
  final top = yMax ?? chartCeil(values.reduce(max));
  final w = max(0.0, size.width - pad.horizontal);
  final h = max(0.0, size.height - pad.vertical);
  final n = values.length;
  return [
    for (var i = 0; i < n; i++)
      Offset(
        pad.left + (n == 1 ? w / 2 : w * i / (n - 1)),
        pad.top + h - (top <= 0 ? 0 : (values[i] / top).clamp(0, 1) * h),
      ),
  ];
}

/// 手指在 x 处对应第几个点(就近取整),越界夹到两头。
int chartIndexAt(double dx, int count, Size size, {EdgeInsets pad = EdgeInsets.zero}) {
  if (count <= 1) return 0;
  final w = size.width - pad.horizontal;
  if (w <= 0) return 0;
  final i = ((dx - pad.left) / w * (count - 1)).round();
  return i.clamp(0, count - 1);
}

/// 「2026-09-07」→「9/7」
String chartDayLabel(String day) {
  final p = day.split('-');
  if (p.length != 3) return day;
  return '${int.tryParse(p[1]) ?? p[1]}/${int.tryParse(p[2]) ?? p[2]}';
}

/// 近 N 天每天的增量。点一下 / 横着拖看某一天的数。
class StatsLineChart extends StatefulWidget {
  const StatsLineChart({super.key, required this.days, required this.values, required this.label, this.height = 180});

  /// 每一天(「2026-09-07」),和 [values] 一一对应
  final List<String> days;
  final List<int> values;

  /// 这条线是什么(「播放」)
  final String label;
  final double height;

  @override
  State<StatsLineChart> createState() => _StatsLineChartState();
}

class _StatsLineChartState extends State<StatsLineChart> {
  int? _sel;

  static const _pad = EdgeInsets.fromLTRB(34, 10, 10, 22);

  @override
  void didUpdateWidget(covariant StatsLineChart old) {
    super.didUpdateWidget(old);
    if (old.values.length != widget.values.length) _sel = null;
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final n = widget.values.length;
    final int i = min(max(_sel ?? n - 1, 0), max(0, n - 1));
    final head = n == 0 ? '暂无数据' : '${chartDayLabel(widget.days[i])} ${widget.label} ${widget.values[i]}';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(head, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      const SizedBox(height: 6),
      SizedBox(
        height: widget.height,
        child: LayoutBuilder(builder: (context, box) {
          final size = Size(box.maxWidth, widget.height);
          void pick(Offset p) => setState(() => _sel = chartIndexAt(p.dx, n, size, pad: _pad));
          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapDown: (d) => pick(d.localPosition),
            onHorizontalDragUpdate: (d) => pick(d.localPosition),
            child: CustomPaint(
              size: size,
              painter: _LinePainter(
                values: widget.values,
                days: widget.days,
                selected: n == 0 ? null : i,
                line: sz.clay,
                grid: sz.line,
                text: sz.inkMuted,
                pad: _pad,
                textScaler: MediaQuery.textScalerOf(context),
              ),
            ),
          );
        }),
      ),
    ]);
  }
}

class _LinePainter extends CustomPainter {
  _LinePainter({
    required this.values,
    required this.days,
    required this.selected,
    required this.line,
    required this.grid,
    required this.text,
    required this.pad,
    required this.textScaler,
  });

  final List<int> values;
  final List<String> days;
  final int? selected;
  final Color line;
  final Color grid;
  final Color text;
  final EdgeInsets pad;
  final TextScaler textScaler;

  void _label(Canvas canvas, String s, Offset at, {TextAlign align = TextAlign.left}) {
    final tp = TextPainter(
      text: TextSpan(text: s, style: TextStyle(fontSize: kFontMicro, color: text)),
      textDirection: TextDirection.ltr,
      textScaler: textScaler,
    )..layout();
    final dx = switch (align) {
      TextAlign.right => at.dx - tp.width,
      TextAlign.center => at.dx - tp.width / 2,
      _ => at.dx,
    };
    tp.paint(canvas, Offset(dx, at.dy - tp.height / 2));
  }

  @override
  void paint(Canvas canvas, Size size) {
    final top = chartCeil(values.isEmpty ? 0 : values.reduce(max));
    final gridPaint = Paint()
      ..color = grid
      ..strokeWidth = 1;
    // 三条横线:底、中、顶。只标底和顶的数:中间那条在小数值时是 2.5 这种,标出来反而怪
    for (final f in const [0.0, 0.5, 1.0]) {
      final y = pad.top + (size.height - pad.vertical) * (1 - f);
      canvas.drawLine(Offset(pad.left, y), Offset(size.width - pad.right, y), gridPaint);
    }
    _label(canvas, '0', Offset(pad.left - 6, size.height - pad.bottom), align: TextAlign.right);
    _label(canvas, _short(top), Offset(pad.left - 6, pad.top), align: TextAlign.right);
    if (values.isEmpty) return;

    final pts = chartPoints(values, size, pad: pad, yMax: top);
    final path = Path()..moveTo(pts.first.dx, pts.first.dy);
    for (final p in pts.skip(1)) {
      path.lineTo(p.dx, p.dy);
    }
    final base = size.height - pad.bottom;
    final area = Path.from(path)
      ..lineTo(pts.last.dx, base)
      ..lineTo(pts.first.dx, base)
      ..close();
    canvas.drawPath(area, Paint()..color = line.withValues(alpha: .10));
    canvas.drawPath(
      path,
      Paint()
        ..color = line
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2
        ..strokeJoin = StrokeJoin.round,
    );

    // 横轴只标头、尾两天:30 个日期挤不下,头尾说清楚范围就够
    if (days.isNotEmpty) {
      _label(canvas, chartDayLabel(days.first), Offset(pts.first.dx, size.height - pad.bottom / 2),
          align: TextAlign.left);
      if (days.length > 1) {
        _label(canvas, chartDayLabel(days.last), Offset(pts.last.dx, size.height - pad.bottom / 2),
            align: TextAlign.right);
      }
    }

    final s = selected;
    if (s != null && s >= 0 && s < pts.length) {
      final p = pts[s];
      canvas.drawLine(Offset(p.dx, pad.top), Offset(p.dx, base), gridPaint..color = line.withValues(alpha: .35));
      canvas.drawCircle(p, 4.5, Paint()..color = line);
      canvas.drawCircle(p, 2, Paint()..color = Colors.white);
    }
  }

  static String _short(double v) {
    if (v >= 10000) return '${(v / 10000).toStringAsFixed(v % 10000 == 0 ? 0 : 1)}万';
    return v == v.roundToDouble() ? v.toInt().toString() : v.toStringAsFixed(1);
  }

  @override
  bool shouldRepaint(covariant _LinePainter old) =>
      !listEquals(old.values, values) ||
      old.selected != selected ||
      old.line != line ||
      old.grid != grid ||
      old.text != text ||
      old.textScaler != textScaler;
}
