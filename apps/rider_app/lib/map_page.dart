import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 配送地图:取餐点(商家)、送达点(顾客)、骑手实时位置。
/// 底图:腾讯地图(shared/delivery_map.dart);骑行导航跳外部地图 App
/// (腾讯/高德/百度,装了哪些给哪些选)。
class DeliveryMapPage extends StatelessWidget {
  const DeliveryMapPage({
    super.key,
    required this.order,
    required this.riderPosition,
  });

  final Order order;

  /// 由主页持有并随 GPS 更新,地图页跟着动
  final ValueNotifier<({double lat, double lng})?> riderPosition;

  /// 唤起外部地图骑行导航。装了哪些给哪些选,只装一个就直接走。
  /// 实现在 packages/shared/lib/src/nav_launcher.dart(纯跳转协议,不接 SDK)。
  Future<void> _navigate(
          BuildContext context, double lat, double lng, String name) =>
      navigateTo(context, lat: lat, lng: lng, name: name, mode: NavMode.ride);

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      // 限宽用宽档:地图挤在 720 里看不清 —— 
      // 宽度上限按**内容形态**选,不是统一限死
      contentMaxWidth: kWideMaxWidth,
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
                  color: Theme.of(context).sz.hold),
            if (rider != null)
              MapPoint(
                  lat: rider.lat,
                  lng: rider.lng,
                  label: '我',
                  icon: Icons.sports_motorsports,
                  color: Theme.of(context).sz.clay),
            MapPoint(
                lat: order.lat,
                lng: order.lng,
                label: '送达',
                icon: Icons.home,
                color: Theme.of(context).sz.earn),
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
                        context, order.merchantLat!, order.merchantLng!,
                        order.merchantName),
                  ),
                ),
              if (order.merchantLat != null) const SizedBox(width: 12),
              Expanded(
                child: FilledButton.icon(
                  icon: const Icon(Icons.home),
                  label: const Text('导航去送餐'),
                  onPressed: () => _navigate(
                      context, order.lat, order.lng, order.address),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
