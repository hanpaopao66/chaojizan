/// 品牌插画(全矢量 CustomPaint):空状态不用灰图标,用有温度的小画。
///
/// 统一手法:暖色大圆底 + 2.5px 圆头描边图形 + 品牌橙点缀 + 装饰小点,
/// 与 Logo(闪电 Z + 碗弧)同一造型语言——圆润、利落、有烟火气。
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'brand.dart';

enum BrandArt {
  bowl,     // 一碗热饭(冒蒸汽):没商家/没菜品
  ticket,   // 一张笑脸券:没券
  receipt,  // 一张单据:没订单
  offline,  // 断线的云:网络问题
  search,   // 放大镜找碗:搜索无结果
}

class BrandArtView extends StatelessWidget {
  const BrandArtView(this.art, {super.key, this.size = 128});

  final BrandArt art;
  final double size;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    return CustomPaint(
      size: Size.square(size),
      painter: _ArtPainter(art, dark),
    );
  }
}

class _ArtPainter extends CustomPainter {
  _ArtPainter(this.art, this.dark);

  final BrandArt art;
  final bool dark;

  late Canvas _c;
  late double _s;

  Offset p(double x, double y) => Offset(x * _s, y * _s);

  Paint get _stroke => Paint()
    ..color = dark ? const Color(0xFFB9AFA8) : const Color(0xFF5C544E)
    ..style = PaintingStyle.stroke
    ..strokeWidth = 0.028 * _s
    ..strokeCap = StrokeCap.round
    ..strokeJoin = StrokeJoin.round;

  Paint get _orangeStroke => Paint()
    ..color = kBrandOrange
    ..style = PaintingStyle.stroke
    ..strokeWidth = 0.028 * _s
    ..strokeCap = StrokeCap.round;

  Paint get _orangeFill => Paint()..color = kBrandOrange;

  @override
  void paint(Canvas canvas, Size size) {
    _c = canvas;
    _s = size.width;

    // 暖色大圆底
    canvas.drawCircle(
        p(0.5, 0.52), 0.42 * _s,
        Paint()
          ..color = (dark
              ? kBrandOrange.withValues(alpha: 0.10)
              : const Color(0xFFFFEDE4)));

    switch (art) {
      case BrandArt.bowl:
        _bowl();
      case BrandArt.ticket:
        _ticket();
      case BrandArt.receipt:
        _receipt();
      case BrandArt.offline:
        _offline();
      case BrandArt.search:
        _search();
    }
    _sparkles();
  }

  /// 装饰小点:插画的"呼吸感"来自不对称的小元素
  void _sparkles() {
    _c.drawCircle(p(0.16, 0.30), 0.014 * _s, _orangeFill);
    _c.drawCircle(p(0.86, 0.42), 0.010 * _s,
        Paint()..color = kBrandOrange.withValues(alpha: 0.55));
    _c.drawCircle(p(0.80, 0.20), 0.017 * _s,
        Paint()..color = kPromoAmber.withValues(alpha: 0.45));
  }

  void _steam(double cx) {
    // 两缕蒸汽:S 形短曲线
    for (final dx in [-0.05, 0.05]) {
      final path = Path()
        ..moveTo((cx + dx) * _s, 0.36 * _s)
        ..cubicTo((cx + dx - 0.03) * _s, 0.31 * _s, (cx + dx + 0.03) * _s,
            0.27 * _s, (cx + dx) * _s, 0.22 * _s);
      _c.drawPath(path, _orangeStroke..strokeWidth = 0.022 * _s);
    }
  }

  void _bowl() {
    _steam(0.5);
    // 碗体:上宽下窄的圆弧碗 + 碗足
    final bowl = Path()
      ..moveTo(0.24 * _s, 0.48 * _s)
      ..lineTo(0.76 * _s, 0.48 * _s)
      ..arcToPoint(p(0.24, 0.48),
          radius: Radius.circular(0.30 * _s), clockwise: true);
    _c.drawPath(bowl, _stroke);
    _c.drawLine(p(0.42, 0.79), p(0.58, 0.79), _stroke);
    // 碗沿高光(品牌橙一笔)
    _c.drawArc(Rect.fromLTRB(0.24 * _s, 0.40 * _s, 0.76 * _s, 0.56 * _s),
        math.pi * 0.15, math.pi * 0.25, false, _orangeStroke);
    // 筷子斜插
    _c.drawLine(p(0.60, 0.28), p(0.78, 0.10), _stroke);
    _c.drawLine(p(0.66, 0.32), p(0.84, 0.14), _stroke);
  }

  void _ticket() {
    // 票券:圆角矩形,两侧半圆缺口,中间虚线
    final r = Rect.fromLTRB(0.20 * _s, 0.34 * _s, 0.80 * _s, 0.66 * _s);
    final ticket = Path()
      ..addRRect(RRect.fromRectAndRadius(r, Radius.circular(0.05 * _s)));
    final notchL = Path()
      ..addOval(Rect.fromCircle(center: p(0.20, 0.50), radius: 0.045 * _s));
    final notchR = Path()
      ..addOval(Rect.fromCircle(center: p(0.80, 0.50), radius: 0.045 * _s));
    _c.drawPath(
        Path.combine(PathOperation.difference,
            Path.combine(PathOperation.difference, ticket, notchL), notchR),
        _stroke);
    // 中缝虚线
    for (var y = 0.38; y < 0.63; y += 0.07) {
      _c.drawLine(p(0.62, y), p(0.62, y + 0.035), _stroke..strokeWidth = 0.02 * _s);
    }
    // 左半张画个笑(与 Logo 呼应)
    _c.drawCircle(p(0.34, 0.45), 0.012 * _s, _orangeFill);
    _c.drawCircle(p(0.46, 0.45), 0.012 * _s, _orangeFill);
    _c.drawArc(Rect.fromLTRB(0.32 * _s, 0.44 * _s, 0.48 * _s, 0.58 * _s),
        math.pi * 0.15, math.pi * 0.7, false, _orangeStroke);
  }

  void _receipt() {
    // 单据:上直下锯齿
    final path = Path()..moveTo(0.30 * _s, 0.24 * _s);
    path.lineTo(0.70 * _s, 0.24 * _s);
    path.lineTo(0.70 * _s, 0.72 * _s);
    var x = 0.70;
    var up = false;
    while (x > 0.30) {
      x -= 0.08;
      path.lineTo(math.max(x, 0.30) * _s, (up ? 0.72 : 0.76) * _s);
      up = !up;
    }
    path.close();
    _c.drawPath(path, _stroke);
    // 三行"字"(最后一行橙色 = 合计)
    _c.drawLine(p(0.38, 0.35), p(0.62, 0.35), _stroke);
    _c.drawLine(p(0.38, 0.44), p(0.56, 0.44), _stroke);
    _c.drawLine(p(0.38, 0.56), p(0.62, 0.56), _orangeStroke);
  }

  void _offline() {
    // 云
    final cloud = Path()
      ..moveTo(0.30 * _s, 0.55 * _s)
      ..arcToPoint(p(0.38, 0.38), radius: Radius.circular(0.13 * _s))
      ..arcToPoint(p(0.58, 0.36), radius: Radius.circular(0.12 * _s))
      ..arcToPoint(p(0.72, 0.55), radius: Radius.circular(0.11 * _s))
      ..close();
    _c.drawPath(cloud, _stroke);
    // 断开的连线 + 小叉
    _c.drawLine(p(0.42, 0.62), p(0.48, 0.70), _stroke);
    _c.drawLine(p(0.56, 0.70), p(0.62, 0.78), _stroke);
    _c.drawLine(p(0.68, 0.62), p(0.76, 0.70), _orangeStroke);
    _c.drawLine(p(0.76, 0.62), p(0.68, 0.70), _orangeStroke);
  }

  void _search() {
    // 放大镜,镜片里一个小碗
    _c.drawCircle(p(0.44, 0.46), 0.17 * _s, _stroke);
    _c.drawLine(p(0.57, 0.59), p(0.72, 0.74), _stroke..strokeWidth = 0.036 * _s);
    final bowl = Path()
      ..moveTo(0.36 * _s, 0.45 * _s)
      ..lineTo(0.52 * _s, 0.45 * _s)
      ..arcToPoint(p(0.36, 0.45),
          radius: Radius.circular(0.09 * _s), clockwise: true);
    _c.drawPath(bowl, _orangeStroke..strokeWidth = 0.022 * _s);
  }

  @override
  bool shouldRepaint(covariant _ArtPainter old) =>
      old.art != art || old.dark != dark;
}
