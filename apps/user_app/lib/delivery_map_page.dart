import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 用户看配送:商家(取餐点)、我家(送达点)、骑手实时位置(5 秒一刷)。
/// 底图:天地图(shared/delivery_map.dart);未配 key 自动进示意模式。
class DeliveryMapPage extends StatefulWidget {
  const DeliveryMapPage({super.key, required this.api, required this.order});

  final ApiClient api;
  final Order order;

  @override
  State<DeliveryMapPage> createState() => _DeliveryMapPageState();
}

class _DeliveryMapPageState extends State<DeliveryMapPage>
    with SingleTickerProviderStateMixin {
  RiderLocation? _rider;
  Timer? _timer;

  // 骑手位置平滑移动:5 秒一个新坐标,在旧新位置间做 2 秒插值,
  // 地图上的骑手是"骑过去"而不是"闪现"
  late final AnimationController _moveController = AnimationController(
      vsync: this, duration: const Duration(seconds: 2))
    ..addListener(() => setState(() {}));
  ({double lat, double lng})? _fromPos;
  ({double lat, double lng})? _toPos;

  ({double lat, double lng})? get _animatedRiderPos {
    final to = _toPos;
    if (to == null) return null;
    final from = _fromPos ?? to;
    final t = Curves.easeInOut.transform(_moveController.value);
    return (
      lat: from.lat + (to.lat - from.lat) * t,
      lng: from.lng + (to.lng - from.lng) * t,
    );
  }

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _moveController.dispose();
    super.dispose();
  }

  Future<void> _poll() async {
    try {
      final rider = await widget.api.riderLocation(widget.order.orderNo);
      if (!mounted) return;
      setState(() {
        _rider = rider;
        if (rider?.lat != null) {
          final next = (lat: rider!.lat!, lng: rider.lng!);
          if (_toPos == null) {
            _toPos = next; // 首个坐标直接落点
          } else if (next != _toPos) {
            _fromPos = _animatedRiderPos ?? _toPos;
            _toPos = next;
            _moveController.forward(from: 0);
          }
        }
      });
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final order = widget.order;
    final rider = _animatedRiderPos;

    final points = <MapPoint>[
      if (order.merchantLat != null && order.merchantLng != null)
        MapPoint(
            lat: order.merchantLat!,
            lng: order.merchantLng!,
            label: order.merchantName,
            icon: Icons.storefront,
            color: kPromoAmber),
      if (rider != null)
        MapPoint(
            lat: rider.lat,
            lng: rider.lng,
            label: '骑手',
            icon: Icons.sports_motorsports,
            color: kBrandOrange),
      MapPoint(
          lat: order.lat,
          lng: order.lng,
          label: '送达地址',
          icon: Icons.home,
          color: kMoneyGreen),
    ];

    return Scaffold(
      appBar: AppBar(title: Text('配送进度 · ${order.status.label}')),
      body: DeliveryMapView(points: points),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Text(
            _rider?.lat == null ? '等待骑手位置上报…' : '骑手位置 5 秒自动刷新',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ),
      ),
    );
  }
}
