import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 骑手在哪(商家端)。
///
/// 顾客催单第一个电话往往打给店家,而店家此前对配送进度两眼一抹黑,
/// 只能回一句"应该快了"。这页给店家和顾客同一份事实:
/// 店 → 骑手当前位置 → 送达点,5 秒一刷。
///
/// 骑手位置 5 秒上报一次、Redis 5 分钟过期 —— 拿不到就明说
/// "位置暂不可用",不摆一个猜出来的点。
class RiderTrackPage extends StatefulWidget {
  const RiderTrackPage({super.key, required this.api, required this.order});

  final ApiClient api;
  final Order order;

  @override
  State<RiderTrackPage> createState() => _RiderTrackPageState();
}

class _RiderTrackPageState extends State<RiderTrackPage> {
  RiderLocation? _loc;
  bool _loaded = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _refresh();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    try {
      final loc = await widget.api.riderLocation(widget.order.orderNo);
      if (mounted) {
        setState(() {
          _loc = loc;
          _loaded = true;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loaded = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final order = widget.order;
    final hasShop = order.merchantLat != null && order.merchantLng != null;
    final hasRider = _loc?.lat != null && _loc?.lng != null;

    return Scaffold(
      appBar: AppBar(title: const Text('骑手在哪')),
      body: !_loaded
          ? const Center(child: CircularProgressIndicator())
          : Column(children: [
              Expanded(
                child: DeliveryMapView(points: [
                  if (hasShop)
                    MapPoint(
                      lat: order.merchantLat!,
                      lng: order.merchantLng!,
                      label: '本店',
                      icon: Icons.store,
                      color: sz.clay,
                    ),
                  if (hasRider)
                    MapPoint(
                      lat: _loc!.lat!,
                      lng: _loc!.lng!,
                      label: '骑手',
                      icon: Icons.delivery_dining,
                      color: sz.link,
                    ),
                  MapPoint(
                    lat: order.lat,
                    lng: order.lng,
                    label: '送达',
                    icon: Icons.location_on,
                    color: sz.earn,
                  ),
                ]),
              ),
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(
                      kPagePad, 12, kPagePad, 12),
                  child: Row(children: [
                    Icon(
                      hasRider
                          ? Icons.delivery_dining
                          : Icons.location_off_outlined,
                      size: 18,
                      color: hasRider ? sz.earn : sz.inkFaint,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        hasRider
                            ? (order.status == OrderStatus.pickedUp
                                ? '骑手配送中,位置 5 秒自动刷新'
                                : '骑手已接单,正在赶来取餐')
                            : '骑手位置暂不可用(可能刚接单或设备离线),稍等自动刷新',
                        style: TextStyle(fontSize: 13, color: sz.inkMuted),
                      ),
                    ),
                  ]),
                ),
              ),
            ]),
    );
  }
}
