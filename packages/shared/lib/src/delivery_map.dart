/// 配送地图(用户端/骑手端/商家端共用):腾讯官方地图 SDK(#138)。
///
/// ## 为什么从栅格瓦片换成原生 SDK
///
/// 只有一个理由:**不糊**。实测腾讯与高德的栅格瓦片都只有 256×256,没有高清版,
/// 而手机像素密度 2.75~3 倍 —— 256px 被拉到 700 多物理像素,必然糊。
/// 这跟换哪家厂商无关,是栅格方案在高密度屏上的固有问题。SDK 是矢量渲染。
///
/// 代价是 APK **+13.4MB**(实测空壳 14.6 → 28.0MB)。这是拍板接受的,
/// 但不要再往上叠:除地图外别顺手引入其他原生 SDK。
///
/// ## 坐标口径
///
/// **全程 GCJ-02,不转换。** 腾讯 SDK 与本系统全局口径一致。
/// (唤起百度导航是唯一例外,见 nav_launcher.dart。)
///
/// ## 四种降级,都不是白板
///
/// 1. 没编 key(开发/CI 包)→ 品牌网格 + 三点连线;
/// 2. 用户没同意隐私 → 同上,并提示"同意后可看街道底图";
/// 3. SDK 启动失败 → 同上;
/// 4. **平台没有原生 SDK**(web / macOS / Windows / Linux)→ 同上。
///    这一条和前三条不一样:它是**永久**的,所以提示语也不同 ——
///    写"待启用"会让人一直等一个不会来的东西。
///
/// 方位与距离本来就是真的,「没有街道底图」不该等于「这个功能没了」。
library;

import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_tencent_map/flutter_tencent_map.dart' as tx;

import 'brand.dart';
import 'map_boot.dart';
import 'map_pin_bitmap.dart';
import 'nav_launcher.dart';

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

/// 配送地图。
///
/// 入参刻意保持「一组点 + 连线顺序」的**通用形态**,不给商家/骑手/送达
/// 写死三个字段 —— 顺路串单做出来之后要一次画多个取送点,
/// 轨迹回放要画几十个点,那时不该再改这个组件的签名。
class DeliveryMapView extends StatefulWidget {
  const DeliveryMapView({super.key, required this.points, this.pathThrough});

  /// 全部标点(商家/送达点/骑手…),GCJ-02
  final List<MapPoint> points;

  /// 连线顺序(取自 points 的下标),如 [商家, 骑手, 送达点]
  final List<int>? pathThrough;

  @override
  State<DeliveryMapView> createState() => _DeliveryMapViewState();
}

class _DeliveryMapViewState extends State<DeliveryMapView> {
  tx.TencentMapController? _ctrl;
  final Map<int, Uint8List> _pins = {};
  bool _pinsReady = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _buildPins();
  }

  @override
  void didUpdateWidget(covariant DeliveryMapView old) {
    super.didUpdateWidget(old);
    // 点变了要重画图钉(骑手位置是 5 秒一刷的)。只在**标签或配色**变化时重画:
    // 光是坐标动了,图钉图片是一样的,重画纯属浪费
    final changed = old.points.length != widget.points.length ||
        [for (var i = 0; i < old.points.length; i++)
          old.points[i].label != widget.points[i].label].contains(true);
    if (changed) _buildPins();
  }

  Future<void> _buildPins() async {
    final sz = Theme.of(context).sz;
    final dpr = MediaQuery.devicePixelRatioOf(context);
    final out = <int, Uint8List>{};
    for (var i = 0; i < widget.points.length; i++) {
      final p = widget.points[i];
      out[i] = await buildPinBitmap(
        label: p.label, icon: p.icon, color: p.color,
        labelBg: sz.surface, labelFg: sz.ink, dpr: dpr,
      );
    }
    if (!mounted) return;
    setState(() {
      _pins
        ..clear()
        ..addAll(out);
      _pinsReady = true;
    });
  }

  /// 让所有点都进画面。SDK 自己算 zoom,不要手写 —— 手写的那套在
  /// 两点极近(自取单商家=送达点)时会算出无意义的超大 zoom
  Future<void> _fitAll() async {
    final c = _ctrl;
    if (c == null || widget.points.length < 2) return;
    final lats = widget.points.map((p) => p.lat);
    final lngs = widget.points.map((p) => p.lng);
    await c.moveCamera(
      tx.CameraUpdate.newLatLngBounds(
        tx.LatLngBounds(
          southwest: tx.LatLng(
              lats.reduce((a, b) => a < b ? a : b),
              lngs.reduce((a, b) => a < b ? a : b)),
          northeast: tx.LatLng(
              lats.reduce((a, b) => a > b ? a : b),
              lngs.reduce((a, b) => a > b ? a : b)),
        ),
        // padding 是**位置参数**不是命名参数(踩过)。给 64 是为了让标点的
        // 名签不贴边 —— 只给边界的话图钉会正好压在画面边缘
        64.0,
      ),
      animated: false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (widget.points.isEmpty) return const SizedBox.shrink();
    final path = widget.pathThrough ??
        List.generate(widget.points.length, (i) => i);

    return ValueListenableBuilder<bool>(
      valueListenable: mapReady,
      builder: (context, ready, _) {
        if (!ready || !_pinsReady) return _fallback(theme, path);
        return Stack(children: [
          tx.TencentMap(
            apiKey: tencentApiKey,
            initialCameraPosition: tx.CameraPosition(
              target: tx.LatLng(
                  widget.points.first.lat, widget.points.first.lng),
              zoom: 15,
            ),
            // 只画三个点一条线,不需要这些:关掉省电、也少一份视觉噪音
            compassEnabled: false,
            trafficEnabled: false,
            tiltGesturesEnabled: false,
            rotateGesturesEnabled: false,
            touchPoiEnabled: false,
            markers: {
              for (var i = 0; i < widget.points.length; i++)
                if (_pins[i] != null)
                  tx.Marker(
                    id: 'p$i',
                    position: tx.LatLng(
                        widget.points[i].lat, widget.points[i].lng),
                    icon: tx.BitmapDescriptor.fromBytes(_pins[i]!),
                    // 图钉尖对准坐标:锚点放底部中间
                    anchor: const Offset(0.5, 1.0),
                  ),
            },
            polylines: {
              if (path.length > 1)
                tx.Polyline(
                  id: 'route',
                  points: [
                    for (final i in path)
                      tx.LatLng(widget.points[i].lat, widget.points[i].lng)
                  ],
                  width: 6,
                  color: kBrandOrange.withValues(alpha: .8),
                ),
            },
            onMapCreated: (c) async {
              _ctrl = c;
              await _fitAll();
            },
          ),
          // 版权标注是地图服务商的硬性要求,不能因为"占地方"就去掉
          const Positioned(
            right: 6,
            bottom: 4,
            child: Text('© 腾讯地图',
                style: TextStyle(fontSize: 9, color: Colors.black38)),
          ),
        ]);
      },
    );
  }

  /// 没有地图时显示什么(#290)。
  ///
  /// 以前这里画一张网格 + 图钉的「示意图」,方位和距离是真的、只是没有街道
  /// 底图。**去掉了** —— 一张自绘的网格看起来像地图但不是地图,用户没法拿它
  /// 找路;而真正有用的动作(用系统地图打开)反而被那张图挡住了。
  ///
  /// 三种触发原因里,只有第三种是永久的,所以文案分开写:
  /// 写「待启用」会让桌面端用户一直等一个不会来的东西。
  Widget _fallback(ThemeData theme, List<int> path) {
    final sz = theme.sz;
    final first = widget.points.isEmpty ? null : widget.points.first;
    final target = widget.points.length > 1 ? widget.points.last : first;
    final why = !mapSdkSupported
        ? '这个平台没有地图组件'
        : kTencentMapKey.isEmpty
            ? '地图待启用'
            : '同意隐私政策后可看地图';
    return Container(
      color: sz.surfaceAlt,
      alignment: Alignment.center,
      padding: const EdgeInsets.all(kPagePad),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.map_outlined, size: 30, color: sz.inkFaint),
        const SizedBox(height: 8),
        Text(why, style: TextStyle(fontSize: 13, color: sz.inkMuted)),
        if (target != null) ...[
          const SizedBox(height: 4),
          Text(target.label,
              maxLines: 2,
              textAlign: TextAlign.center,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12.5, color: sz.ink)),
          const SizedBox(height: 12),
          // 没有内嵌地图时,能做的事一件都没少 —— 系统地图照样导得了
          FilledButton.tonalIcon(
            icon: const Icon(Icons.navigation_outlined, size: 18),
            label: const Text('用手机地图打开'),
            onPressed: () => navigateTo(context,
                lat: target.lat, lng: target.lng, name: target.label),
          ),
        ],
      ]),
    );
  }
}
