/// 地图选点(#137):在地图上定位收货地址。
///
/// 为什么需要:搜索联想只覆盖已收录的 POI。新交付的小区、城中村、
/// 园区里的某栋楼,搜出来要么没有、要么只能选到几百米外的地标 ——
/// 用户只好把真实位置写进「门牌详情」里,而**配送费和配送范围是按坐标算的**,
/// 坐标差 500 米,骑手就白跑一趟。
///
/// 交互:**图钉钉死在屏幕中心,拖的是地图**。比"拖图钉"稳:
/// 手指不会挡住要对准的那个点,单手也能操作。这也是国内主流地图选点的做法。
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_tencent_map/flutter_tencent_map.dart' as tx;

import 'brand.dart';
import 'map_boot.dart';

/// 选点结果。
@immutable
class PickedPlace {
  const PickedPlace({
    required this.lat,
    required this.lng,
    required this.name,
    required this.district,
  });

  final double lat;
  final double lng;

  /// 反查到的地址名(可能为空,调用方要能接受)
  final String name;
  final String district;
}

class MapPickerPage extends StatefulWidget {
  const MapPickerPage({
    super.key,
    required this.onReverse,
    this.initialLat,
    this.initialLng,
  });

  /// 坐标 → 地址。由调用方注入,避免 shared 依赖具体的 ApiClient
  final Future<({String name, String district})> Function(double, double)
      onReverse;

  final double? initialLat;
  final double? initialLng;

  @override
  State<MapPickerPage> createState() => _MapPickerPageState();
}

class _MapPickerPageState extends State<MapPickerPage> {
  /// 成都春熙路:没有初始坐标时的落点
  static const _fbLat = 30.6598, _fbLng = 104.0810;

  late tx.LatLng _center = tx.LatLng(
      widget.initialLat ?? _fbLat, widget.initialLng ?? _fbLng);

  Timer? _debounce;
  String _name = '';
  String _district = '';
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    // 进来就反查一次,不用等用户先动一下地图
    WidgetsBinding.instance.addPostFrameCallback((_) => _reverse());
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  /// 相机停下才反查。SDK 的 onCameraMoveEnd 比自己防抖准,
  /// 但**仍然保留 400ms 防抖** —— 用户连续微调时它会连发多次,
  /// 而反查是按次计费的
  void _onCameraEnd(tx.CameraPosition pos) {
    _center = pos.target;
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), _reverse);
  }

  Future<void> _reverse() async {
    if (!mounted) return;
    setState(() => _loading = true);
    final target = _center;
    try {
      final r = await widget.onReverse(target.latitude, target.longitude);
      // 反查回来时用户可能又拖走了 —— 那就丢弃这个结果,
      // 否则地址栏显示的是上一个位置,和图钉对不上
      if (!mounted || target != _center) return;
      setState(() {
        _name = r.name;
        _district = r.district;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      // 反查失败不阻断:坐标本身是准的,让用户自己写地址名
      setState(() {
        _name = '';
        _district = '地址解析失败,可直接确认位置后手填';
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ValueListenableBuilder<bool>(
      valueListenable: mapReady,
      builder: (context, ready, _) => _build(context, sz, ready),
    );
  }

  Widget _build(BuildContext context, SzColors sz, bool ready) {
    return Scaffold(
      appBar: AppBar(title: const Text('在地图上选位置')),
      body: Column(children: [
        Expanded(
          child: Stack(
            alignment: Alignment.center,
            children: [
              if (ready)
                tx.TencentMap(
                  apiKey: tencentApiKey,
                  initialCameraPosition: tx.CameraPosition(
                      target: _center, zoom: 17),
                  compassEnabled: false,
                  trafficEnabled: false,
                  tiltGesturesEnabled: false,
                  rotateGesturesEnabled: false,
                  onCameraMoveEnd: _onCameraEnd,
                )
              else
                // 没同意隐私 / 没编 key:不渲染白板,给一句能看懂的话
                Container(
                  color: sz.surfaceAlt,
                  alignment: Alignment.center,
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      kTencentMapKey.isEmpty
                          ? '这个版本没有启用街道底图,\n请直接用上方搜索选地址'
                          : '同意隐私政策后才能显示地图,\n也可以直接用上方搜索选地址',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 13, color: sz.inkMuted),
                    ),
                  ),
                ),
              // 图钉钉在正中间。**不用 SDK 的 Marker** —— Marker 是贴在地图上的,
              // 地图一动它跟着动,那就不是准星了。
              // IgnorePointer:它只是准星,不能吃掉落在它身上的拖动手势
              if (ready)
                IgnorePointer(
                child: Padding(
                  // 图钉尖在底部,往上抬半个图标高度,让**尖端**对准中心
                  padding: const EdgeInsets.only(bottom: 34),
                  child: Icon(Icons.location_on, size: 40, color: sz.clay),
                ),
              ),
              if (ready)
                Positioned(
                  right: 6,
                  bottom: 4,
                  child: Text('© 腾讯地图',
                      style: TextStyle(fontSize: 9, color: sz.inkFaint)),
                ),
            ],
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Expanded(
                    child: Text(
                      _loading ? '正在识别位置…' : (_name.isEmpty ? '未识别到地址' : _name),
                      style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: _name.isEmpty ? sz.inkMuted : sz.ink),
                    ),
                  ),
                  if (_loading)
                    SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: sz.inkFaint),
                    ),
                ]),
                if (_district.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(_district,
                      style: TextStyle(fontSize: 12, color: sz.inkMuted)),
                ],
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    // 反查还没回来也允许确认:坐标已经是准的,
                    // 地址名用户可以自己写。卡着不让点才是帮倒忙
                    onPressed: () => Navigator.of(context).pop(PickedPlace(
                      lat: _center.latitude,
                      lng: _center.longitude,
                      name: _name,
                      district: _district,
                    )),
                    child: const Text('就选这里'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ]),
    );
  }
}
