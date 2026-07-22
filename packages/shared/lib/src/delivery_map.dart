/// 配送地图(用户端/骑手端共用):flutter_map + 天地图瓦片。
///
/// 为什么不用高德 SDK:那个 .so 独占 31MB(APK 的 58%),而我们只画
/// 三个点一条线。flutter_map 纯 Dart 零原生依赖,天地图是官方免费底图。
///
/// 坐标约定:入参一律 GCJ-02(全系统统一),贴瓦片时内部转 WGS-84。
/// 未配置 TIANDITU_KEY 时自动降级:无街道底图,画品牌网格 + 三点连线示意,
/// 功能不断(相对方位与距离仍然真实)。
library;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import 'brand.dart';
import 'coord_utils.dart';

/// 天地图 key:--dart-define=TIANDITU_KEY=xxx 注入(tianditu.gov.cn 免费申请)
const String kTiandituKey = String.fromEnvironment('TIANDITU_KEY');

/// 地图上的一个点(GCJ-02)
class MapPoint {
  const MapPoint({
    required this.lat,
    required this.lng,
    required this.label,
    required this.icon,
    required this.color,
  });

  final double lat;
  final double lng;
  final String label;
  final IconData icon;
  final Color color;
}

class DeliveryMapView extends StatelessWidget {
  const DeliveryMapView({super.key, required this.points, this.pathThrough});

  /// 全部标点(商家/送达点/骑手),GCJ-02
  final List<MapPoint> points;

  /// 连线顺序(取自 points 的下标),如 [商家, 骑手, 送达点]
  final List<int>? pathThrough;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final wgs = [
      for (final p in points) gcj02ToWgs84(p.lat, p.lng),
    ];
    final latLngs = [for (final w in wgs) LatLng(w.lat, w.lng)];

    final bounds = LatLngBounds.fromPoints(latLngs);
    final path = pathThrough ?? List.generate(points.length, (i) => i);

    return Stack(
      children: [
        FlutterMap(
          options: MapOptions(
            initialCameraFit: latLngs.length > 1
                ? CameraFit.bounds(
                    bounds: bounds,
                    padding: const EdgeInsets.fromLTRB(48, 96, 48, 120))
                : null,
            initialCenter: latLngs.first,
            initialZoom: 15,
            minZoom: 4,
            maxZoom: 17.9,
            backgroundColor: theme.brightness == Brightness.dark
                ? const Color(0xFF14181F)
                : const Color(0xFFEDF0F2),
          ),
          children: [
            if (kTiandituKey.isNotEmpty) ...[
              // 天地图矢量底图 + 中文注记(Web 墨卡托,WGS-84)
              TileLayer(
                urlTemplate: 'https://t{s}.tianditu.gov.cn/DataServer'
                    '?T=vec_w&x={x}&y={y}&l={z}&tk=$kTiandituKey',
                subdomains: const ['0', '1', '2', '3', '4', '5', '6', '7'],
                userAgentPackageName: 'cn.superz.app',
              ),
              TileLayer(
                urlTemplate: 'https://t{s}.tianditu.gov.cn/DataServer'
                    '?T=cva_w&x={x}&y={y}&l={z}&tk=$kTiandituKey',
                subdomains: const ['0', '1', '2', '3', '4', '5', '6', '7'],
                userAgentPackageName: 'cn.superz.app',
              ),
            ] else
              // 降级模式:品牌网格打底,三点方位与距离依然真实
              const _GridBackdrop(),
            if (path.length > 1)
              PolylineLayer(polylines: [
                Polyline(
                  points: [for (final i in path) latLngs[i]],
                  strokeWidth: 3,
                  color: kBrandOrange.withValues(alpha: .75),
                  pattern: const StrokePattern.dotted(),
                ),
              ]),
            MarkerLayer(markers: [
              for (var i = 0; i < points.length; i++)
                Marker(
                  point: latLngs[i],
                  width: 92,
                  height: 64,
                  alignment: Alignment.topCenter,
                  child: _Pin(point: points[i]),
                ),
            ]),
          ],
        ),
        if (kTiandituKey.isNotEmpty)
          const Positioned(
            right: 6,
            bottom: 4,
            child: Text('© 天地图 GS(2024)0568号',
                style: TextStyle(fontSize: 9, color: Colors.black38)),
          )
        else
          Positioned(
            left: 12,
            top: 12,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: theme.colorScheme.surface.withValues(alpha: .9),
                borderRadius: BorderRadius.circular(999),
                border: Border.all(color: theme.colorScheme.outlineVariant),
              ),
              child: Text('示意模式 · 街道底图待启用',
                  style: theme.textTheme.bodySmall?.copyWith(fontSize: 11)),
            ),
          ),
      ],
    );
  }
}

/// 品牌化标点:色环图标 + 名签
class _Pin extends StatelessWidget {
  const _Pin({required this.point});

  final MapPoint point;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(
            color: point.color,
            shape: BoxShape.circle,
            border: Border.all(color: Colors.white, width: 2),
            boxShadow: const [
              BoxShadow(color: Colors.black26, blurRadius: 6, offset: Offset(0, 2)),
            ],
          ),
          child: Icon(point.icon, size: 15, color: Colors.white),
        ),
        const SizedBox(height: 3),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
          decoration: BoxDecoration(
            color: theme.colorScheme.surface.withValues(alpha: .92),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(point.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                  fontSize: 10.5,
                  fontWeight: FontWeight.w600,
                  color: theme.colorScheme.onSurface)),
        ),
      ],
    );
  }
}

/// 无底图时的品牌网格(暗色友好)
class _GridBackdrop extends StatelessWidget {
  const _GridBackdrop();

  @override
  Widget build(BuildContext context) {
    return CustomPaint(size: Size.infinite, painter: _GridPainter(
        Theme.of(context).brightness == Brightness.dark
            ? Colors.white10
            : Colors.black.withValues(alpha: .06)));
  }
}

class _GridPainter extends CustomPainter {
  _GridPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1;
    const gap = 44.0;
    for (var x = 0.0; x < size.width; x += gap) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), paint);
    }
    for (var y = 0.0; y < size.height; y += gap) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _GridPainter old) => old.color != color;
}
