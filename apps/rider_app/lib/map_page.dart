import 'package:flutter/foundation.dart'
    show defaultTargetPlatform, TargetPlatform;
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

/// 配送地图:取餐点(商家)、送达点(顾客)、骑手实时位置。
/// 底图:天地图(shared/delivery_map.dart);真正的骑行导航跳外部高德 App。
class DeliveryMapPage extends StatelessWidget {
  const DeliveryMapPage({
    super.key,
    required this.order,
    required this.riderPosition,
  });

  final Order order;

  /// 由主页持有并随 GPS 更新,地图页跟着动
  final ValueNotifier<({double lat, double lng})?> riderPosition;

  /// 唤起高德 App 骑行导航;没装高德则打开网页版。
  /// dev=0 表示传入坐标已是 GCJ-02,t=3 骑行模式。(跳转协议不需要 SDK/Key)
  Future<void> _navigate(double lat, double lng, String name) async {
    final encoded = Uri.encodeComponent(name);
    final appUri = defaultTargetPlatform == TargetPlatform.iOS
        ? Uri.parse(
            'iosamap://path?sourceApplication=superz&dlat=$lat&dlon=$lng&dname=$encoded&dev=0&t=3')
        : Uri.parse(
            'amapuri://route/plan/?sourceApplication=superz&dlat=$lat&dlon=$lng&dname=$encoded&dev=0&t=3');
    if (await canLaunchUrl(appUri)) {
      await launchUrl(appUri);
      return;
    }
    await launchUrl(
      Uri.parse(
          'https://uri.amap.com/navigation?to=$lng,$lat,$encoded&mode=ride&src=superz'),
      mode: LaunchMode.externalApplication,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('配送 · ${order.status.label}')),
      body: ValueListenableBuilder(
        valueListenable: riderPosition,
        builder: (context, rider, _) {
          final points = <MapPoint>[
            if (order.merchantLat != null && order.merchantLng != null)
              MapPoint(
                  lat: order.merchantLat!,
                  lng: order.merchantLng!,
                  label: '取餐 ${order.merchantName}',
                  icon: Icons.storefront,
                  color: kPromoAmber),
            if (rider != null)
              MapPoint(
                  lat: rider.lat,
                  lng: rider.lng,
                  label: '我',
                  icon: Icons.sports_motorsports,
                  color: kBrandOrange),
            MapPoint(
                lat: order.lat,
                lng: order.lng,
                label: '送达',
                icon: Icons.home,
                color: kMoneyGreen),
          ];
          return DeliveryMapView(points: points);
        },
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            children: [
              if (order.merchantLat != null && order.merchantLng != null)
                Expanded(
                  child: FilledButton.tonalIcon(
                    icon: const Icon(Icons.store),
                    label: const Text('导航去取餐'),
                    onPressed: () => _navigate(
                        order.merchantLat!, order.merchantLng!,
                        order.merchantName),
                  ),
                ),
              if (order.merchantLat != null) const SizedBox(width: 12),
              Expanded(
                child: FilledButton.icon(
                  icon: const Icon(Icons.home),
                  label: const Text('导航去送餐'),
                  onPressed: () =>
                      _navigate(order.lat, order.lng, order.address),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
