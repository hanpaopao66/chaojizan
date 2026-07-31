/// 把品牌标点画成位图,喂给腾讯 SDK 的 Marker(#138)。
///
/// 为什么要这一层:`flutter_map` 的 Marker 直接吃 Flutter Widget,
/// 而原生 SDK 的 Marker 只吃图片(`BitmapDescriptor`)。
/// 迁到 SDK 后如果改用 SDK 自带的默认图钉,三端的标点就会变成一模一样的
/// 系统红气球 —— 商家/骑手/送达点靠颜色和图标区分的设计就没了。
///
/// 所以在 Dart 侧用 Canvas 画一张,尺寸按设备像素比放大,保证在高密度屏上也锐利
/// (这次迁移的**全部目的**就是不糊,标点自己糊了就很讽刺)。
library;

import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

/// 画一个「色环 + 图标 + 名签」的标点,返回 PNG 字节。
///
/// [dpr] 传 `MediaQuery.devicePixelRatioOf(context)`:按物理像素画,
/// 否则在 3 倍屏上就是一张被拉大的糊图。
Future<Uint8List> buildPinBitmap({
  required String label,
  required IconData icon,
  required Color color,
  required Color labelBg,
  required Color labelFg,
  double dpr = 3.0,
}) async {
  const w = 96.0, h = 66.0;          // 逻辑尺寸(含名签)
  const r = 13.0;                    // 色环半径
  final rec = ui.PictureRecorder();
  final canvas = Canvas(rec);
  canvas.scale(dpr);

  final cx = w / 2;
  const cy = r + 2;

  // 阴影 → 白边 → 实心圆:白边是为了在深色底图上也能看清边界
  canvas.drawCircle(Offset(cx, cy + 1.5), r + 1,
      Paint()..color = Colors.black.withValues(alpha: .22)
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 3));
  canvas.drawCircle(Offset(cx, cy), r + 2, Paint()..color = Colors.white);
  canvas.drawCircle(Offset(cx, cy), r, Paint()..color = color);

  // 图标:用字体图形直接画,不必再准备一套 png 资源
  final ip = TextPainter(
    text: TextSpan(
      text: String.fromCharCode(icon.codePoint),
      style: TextStyle(
        fontSize: 15,
        fontFamily: icon.fontFamily,
        package: icon.fontPackage,
        color: Colors.white,
      ),
    ),
    textDirection: TextDirection.ltr,
  )..layout();
  ip.paint(canvas, Offset(cx - ip.width / 2, cy - ip.height / 2));

  // 名签
  final lp = TextPainter(
    text: TextSpan(
      text: label,
      style: TextStyle(
          fontSize: 10.5, fontWeight: FontWeight.w600, color: labelFg),
    ),
    textDirection: TextDirection.ltr,
    maxLines: 1,
    ellipsis: '…',
  )..layout(maxWidth: w - 8);

  final bw = math.min(lp.width + 12, w);
  final top = cy + r + 6;
  final rect = RRect.fromRectAndRadius(
      Rect.fromLTWH(cx - bw / 2, top, bw, lp.height + 4),
      const Radius.circular(6));
  canvas.drawRRect(rect, Paint()..color = labelBg);
  lp.paint(canvas, Offset(cx - lp.width / 2, top + 2));

  final img = await rec.endRecording().toImage((w * dpr).ceil(),
      (h * dpr).ceil());
  final bd = await img.toByteData(format: ui.ImageByteFormat.png);
  img.dispose();
  return bd!.buffer.asUint8List();
}
