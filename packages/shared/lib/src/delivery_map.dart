/// 配送地图(用户端/骑手端共用):flutter_map + 腾讯地图瓦片。
///
/// 为什么不用原生地图 SDK:高德那个 .so 独占 31MB(APK 的 58%),
/// 而我们只画三个点一条线。flutter_map 纯 Dart,零原生依赖。
///
/// **坐标口径:全程 GCJ-02,不转换。** 腾讯地图本身就是 GCJ-02,
/// 与本系统全局口径一致 —— 这是换掉天地图的主要理由之一:
/// 天地图是 WGS-84,原先每次渲染都要把所有点转一道,转换本身就是错误来源。
///
/// 未配置 TENCENT_MAP_KEY 时自动降级:无街道底图,画品牌网格 + 三点连线示意,
/// 功能不断(相对方位与距离仍然真实)。
library;

import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

import 'brand.dart';

/// 腾讯地图 key:--dart-define=TENCENT_MAP_KEY=xxx 注入。
/// 与服务端逆地理(services/geo_city.py)共用同一把。
const String kTencentMapKey = String.fromEnvironment('TENCENT_MAP_KEY');

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
    // 腾讯瓦片是 GCJ-02,入参也是 GCJ-02 —— 直接用,不转换
    final latLngs = [for (final p in points) LatLng(p.lat, p.lng)];

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
            if (kTencentMapKey.isNotEmpty)
              // 腾讯地图栅格瓦片。中文注记已经烘焙在这一层里,
              // 不像天地图要底图 + 注记贴两层。
              //
              // **tms: true 不能省。** 腾讯的 y 轴是自下而上(TMS 口径),
              // 而 flutter_map 默认是自上而下(XYZ)。少了这行,请求照样返回
              // HTTP 200 —— 只是给你一张地球另一边的空白瓦片,
              // 表现为"地图一片灰",很容易误判成 key 没生效(实测过)。
              TileLayer(
                urlTemplate: 'https://rt{s}.map.gtimg.com/tile'
                    '?z={z}&x={x}&y={y}&styleid=1&version=117'
                    '&key=$kTencentMapKey',
                subdomains: const ['0', '1', '2', '3'],
                tms: true,
                userAgentPackageName: 'cn.superz.app',
              )
            else
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
        // 版权标注是地图服务商的硬性要求,不能因为"占地方"就去掉
        if (kTencentMapKey.isNotEmpty)
          const Positioned(
            right: 6,
            bottom: 4,
            child: Text('© 腾讯地图',
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
