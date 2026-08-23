import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 抢单池总览:**现在池子里这些单,取餐点都在哪。**
///
/// ## 为什么单卡上的「看路线」还不够
///
/// 卡上那个按钮回答的是「这一单在哪」,一次一单。骑手在池子里真正要
/// 判断的却是另一件事:**「这些单彼此挨得近吗」** —— 三单都在同一条
/// 街上和三单散在城市三个角落,是完全不同的两小时。
///
/// 一张一张点进去看,看到第三张就忘了第一张在哪。所以给一张总览。
///
/// ## 红线:只画点,不排序、不推荐
///
/// 和热力图同源(DEV-PROMPTS-17「给信息不给指令」):
///
/// - **所有取餐点一个颜色、一个大小**。按配送费染色、给"推荐"角标、
///   或者把某几单画得更显眼,都是在替骑手做决定 —— 那是软性派单,
///   会变成「平台让我去我才有单」的另一种绑定;
/// - 不画建议路线、不算"最优接单顺序";
/// - 同一家店的多单合成一个点标出单数 —— 这是**去重**,不是排名:
///   同一个位置上叠三个图钉,骑手只会看见一个,反而丢信息。
///
/// 接不接、先接哪个,他自己判断。地图的职责到"看得见"为止。
class RiderPoolMapPage extends StatelessWidget {
  const RiderPoolMapPage({
    super.key,
    required this.orders,
    required this.riderPosition,
  });

  /// 当前可抢的单(已按页面上的排序传进来,但这里**不使用**顺序)
  final List<Order> orders;

  /// 由主页持有并随 GPS 更新
  final ValueNotifier<({double lat, double lng})?> riderPosition;

  /// 按取餐点合并同一家店的多单。
  ///
  /// 返回 (纬度, 经度, 店名, 单数)。用店名而不是坐标做键:
  /// 连锁店不同分店坐标不同,店名相同 —— 合了就把两个地方画成一个点。
  /// 所以键取「店名 + 坐标」,只有真在同一处的才合。
  List<({double lat, double lng, String name, int count})> _pickupPoints() {
    final byPlace = <String, ({double lat, double lng, String name, int n})>{};
    for (final o in orders) {
      final lat = o.merchantLat, lng = o.merchantLng;
      if (lat == null || lng == null) continue;
      final key = '${o.merchantName}@${lat.toStringAsFixed(5)},'
          '${lng.toStringAsFixed(5)}';
      final prev = byPlace[key];
      byPlace[key] = (
        lat: lat,
        lng: lng,
        name: o.merchantName,
        n: (prev?.n ?? 0) + 1,
      );
    }
    return [
      for (final v in byPlace.values)
        (lat: v.lat, lng: v.lng, name: v.name, count: v.n)
    ];
  }

  /// 测试用:合并后的取餐点。
  ///
  /// 暴露它是为了让红线测得到 —— 「图钉是不是同色」这种事在
  /// widget 测试里要去翻渲染树,翻不动就没人写测试,红线就成了口头约定。
  @visibleForTesting
  List<({double lat, double lng, String name, int count})>
      debugPickupPoints() => _pickupPoints();

  /// 测试用:实际画出去的图钉(不含骑手自己)。
  @visibleForTesting
  List<MapPoint> debugPins(ThemeData theme) {
    final sz = theme.sz;
    return [
      for (final p in _pickupPoints())
        MapPoint(
            lat: p.lat,
            lng: p.lng,
            label: p.count > 1 ? '${p.name} ${p.count} 单' : p.name,
            icon: Icons.storefront,
            color: sz.hold),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final places = _pickupPoints();
    return SzPageScaffold(
      // 地图挤在 720 里看不清,和配送地图页同档
      contentMaxWidth: kWideMaxWidth,
      appBar: AppBar(title: const Text('取餐点总览')),
      body: ValueListenableBuilder(
        valueListenable: riderPosition,
        builder: (context, rider, _) {
          if (places.isEmpty) {
            // 「池子空」和「这些单都没有商家坐标」是两回事,分开说
            return Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  orders.isEmpty
                      ? '现在池子里没有单'
                      : '这些单还没有商家位置,画不出来',
                  style: TextStyle(color: sz.inkMuted),
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          final points = <MapPoint>[
            if (rider != null)
              MapPoint(
                  lat: rider.lat,
                  lng: rider.lng,
                  label: '我',
                  icon: Icons.sports_motorsports,
                  color: sz.clay),
            // 单数写进标签不做角标(角标容易读成"优先级");
            // ⚠️ 一律同色同图标 —— 按配送费染色就是在替骑手排序。
            // 和 debugPins 走同一个函数,免得两处飘开、红线测了个寂寞
            ...debugPins(Theme.of(context)),
          ];
          return Column(children: [
            Expanded(child: DeliveryMapView(points: points)),
            SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
                child: Text(
                  rider == null
                      ? '图上是现在能抢的 ${orders.length} 单的取餐点。'
                        '还没定到位,所以没画你的位置'
                      : '图上是现在能抢的 ${orders.length} 单的取餐点,'
                        '橙色那个是你。接不接、先接哪个由你定',
                  style: TextStyle(fontSize: 12, color: sz.inkMuted),
                ),
              ),
            ),
          ]);
        },
      ),
    );
  }
}
