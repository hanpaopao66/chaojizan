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
import 'models.dart';
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
    this.onAround,
    this.initialLat,
    this.initialLng,
  });

  /// 坐标 → 地址。由调用方注入,避免 shared 依赖具体的 ApiClient
  final Future<({String name, String district})> Function(double, double)
      onReverse;

  /// 坐标 → 周边地点列表(可选)。注入后地图下方会列出周边地点,
  /// 用户可直接点选 —— **认地名比认坐标容易得多**。
  ///
  /// 不注入时退化为原来的「一行反查地址 + 确认」,页面照常可用。
  final Future<List<NearbyPlace>> Function(double, double)? onAround;

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

  List<NearbyPlace> _around = const [];
  /// 用户在列表里点中的那个;null = 用图钉当前位置
  NearbyPlace? _picked;

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
        // 地图动过 = 之前选中的那个地点已经不相干了
        _picked = null;
      });
      if (widget.onAround != null) {
        final list = await widget.onAround!(target.latitude, target.longitude);
        if (!mounted || target != _center) return;
        setState(() => _around = list);
      }
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

  void _confirm() {
    final p = _picked;
    Navigator.of(context).pop(PickedPlace(
      // 选了列表里的地点就用它的坐标(那是这栋楼的准确位置);
      // 没选就用图钉 —— 用户拖到自家单元门口,不该被吸附到几十米外的大门
      lat: p?.lat ?? _center.latitude,
      lng: p?.lng ?? _center.longitude,
      name: p?.name ?? _name,
      district: p?.address ?? _district,
    ));
  }

  /// 周边地点列表。第一项是「图钉当前位置」—— 用户可能就是要那个点,
  /// 不能只给他一串 POI 而没有"我就要这儿"的选项。
  Widget _aroundList(SzColors sz) {
    if (_loading && _around.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: kPagePad),
      children: [
        _row(
          sz,
          selected: _picked == null,
          title: _name.isEmpty ? '图钉当前位置' : _name,
          subtitle: _district,
          distance: null,
          onTap: () => setState(() => _picked = null),
        ),
        if (_around.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4, bottom: 2),
            child: Text('周边地点',
                style: TextStyle(fontSize: 11.5, color: sz.inkFaint)),
          ),
        for (final p in _around)
          _row(
            sz,
            selected: _picked == p,
            title: p.name,
            subtitle: p.address,
            distance: p.distanceM,
            onTap: () => setState(() => _picked = p),
          ),
        if (_around.isEmpty && !_loading)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 18),
            child: Text('这附近没找到可选的地点,拖动地图试试',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12.5, color: sz.inkFaint)),
          ),
        const SizedBox(height: 4),
      ],
    );
  }

  Widget _row(
    SzColors sz, {
    required bool selected,
    required String title,
    required String subtitle,
    required int? distance,
    required VoidCallback onTap,
  }) =>
      InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 9),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(
              selected
                  ? Icons.radio_button_checked
                  : Icons.radio_button_unchecked,
              size: 18,
              color: selected ? sz.clay : sz.inkFaint,
            ),
            const SizedBox(width: 9),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: 14,
                          fontWeight:
                              selected ? FontWeight.w600 : FontWeight.w400,
                          color: selected ? sz.clay : sz.ink)),
                  if (subtitle.isNotEmpty)
                    Text(subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style:
                            TextStyle(fontSize: 11.5, color: sz.inkMuted)),
                ],
              ),
            ),
            if (distance != null) ...[
              const SizedBox(width: 8),
              // 距离让用户一眼判断"是不是我家那栋" —— 比看地图快
              Text(distance < 1000 ? '${distance}m' : '${(distance / 1000).toStringAsFixed(1)}km',
                  style: szFigure(fontSize: 11.5, color: sz.inkFaint)),
            ],
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ValueListenableBuilder<bool>(
      valueListenable: mapReady,
      builder: (context, ready, _) => _build(context, sz, ready),
    );
  }

  Widget _build(BuildContext context, SzColors sz, bool ready) {
    // 抽成局部变量:有/无周边列表时外层容器不同(Expanded vs 固定高),
    // 但里面的地图和准星是同一份
    final mapStack = Stack(
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
          );
    return Scaffold(
      appBar: AppBar(title: const Text('在地图上选位置')),
      body: Column(children: [
        // 有周边列表时地图给固定高度(约 38% 屏高),把下面让给列表 ——
        // 用户主要靠读地名确认"这是不是我家",地图是辅助。
        // 没有列表时地图占满剩余空间:那时它是唯一的信息源。
        //
        // **不能用 MediaQuery 的整屏高**:Column 里下面还有确认栏,
        // 那样会溢出
        if (widget.onAround == null)
          Expanded(child: mapStack)
        else
          SizedBox(
            height: MediaQuery.of(context).size.height * .38,
            child: mapStack,
          ),
        // ---- 下半屏:周边地点列表 ----
        //
        // 光给一个图钉 + 反查出来的一行地址,用户很难确认"这就是我家" ——
        // 反查给的往往是路名,而他要的是「XX 小区 10 号楼」。
        // 列一串周边地点带距离,**认地名比认坐标容易得多**。
        if (widget.onAround != null)
          Expanded(child: _aroundList(sz))
        else
          const SizedBox.shrink(),
        SafeArea(
          top: false,
          child: Padding(
            padding: EdgeInsets.fromLTRB(
                kPagePad, widget.onAround == null ? 12 : 8, kPagePad, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 没有周边列表时,这里就是唯一的地址显示
                if (widget.onAround == null) ...[
                  Row(children: [
                    Expanded(
                      child: Text(
                        _loading
                            ? '正在识别位置…'
                            : (_name.isEmpty ? '未识别到地址' : _name),
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
                ],
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    // 反查还没回来也允许确认:坐标已经是准的,
                    // 地址名用户可以自己写。卡着不让点才是帮倒忙
                    onPressed: _confirm,
                    child: Text(_picked == null ? '就选这里' : '选「${_picked!.name}」'),
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
