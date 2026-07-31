import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 自配送地图(商家端 #137)。
///
/// 商家自送时和骑手是同一种处境:要先知道**送去哪、多远**,再决定这单自不自送。
/// 此前商家端全程没有地图,只有一行文字地址 —— 远近全靠猜,
/// 猜错了就是自己骑半小时送一单 3 块钱配送费的活。
///
/// 比骑手端简单:只有两个点(店 → 送达点),没有实时位置要跟。
class SelfDeliveryMapPage extends StatelessWidget {
  const SelfDeliveryMapPage({super.key, required this.order});

  final Order order;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final hasShop = order.merchantLat != null && order.merchantLng != null;
    final km = hasShop
        ? distanceMeters(order.merchantLat!, order.merchantLng!,
            order.lat, order.lng)
        : null;

    return Scaffold(
      appBar: AppBar(title: const Text('自配送 · 送去哪')),
      body: Column(children: [
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
            padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Expanded(
                    child: Text(order.address,
                        style: TextStyle(fontSize: 14, color: sz.ink)),
                  ),
                  if (km != null)
                    // 直线距离,不是骑行里程 —— 写清楚,免得商家按这个数
                    // 估时间然后迟到
                    Text('直线 ${distanceLabel(km)}',
                        style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
                ]),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    icon: const Icon(Icons.navigation_outlined, size: 18),
                    label: const Text('导航去送餐'),
                    onPressed: () => navigateTo(context,
                        lat: order.lat,
                        lng: order.lng,
                        name: order.address,
                        mode: NavMode.ride),
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
