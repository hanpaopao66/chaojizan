import 'dart:math';

/// WGS-84(GPS 原始坐标)→ GCJ-02(高德/国测局坐标)转换。
///
/// 约定:Super-Z 全系统(数据库、接口、地图)统一使用 GCJ-02。
/// GPS 定位结果必须先过这个函数再上报/展示,否则地图上会偏移 100~700 米。
({double lat, double lng}) wgs84ToGcj02(double lat, double lng) {
  if (_outOfChina(lat, lng)) return (lat: lat, lng: lng);
  var dLat = _transformLat(lng - 105.0, lat - 35.0);
  var dLng = _transformLng(lng - 105.0, lat - 35.0);
  final radLat = lat / 180.0 * pi;
  var magic = sin(radLat);
  magic = 1 - _ee * magic * magic;
  final sqrtMagic = sqrt(magic);
  dLat = (dLat * 180.0) / ((_a * (1 - _ee)) / (magic * sqrtMagic) * pi);
  dLng = (dLng * 180.0) / (_a / sqrtMagic * cos(radLat) * pi);
  return (lat: lat + dLat, lng: lng + dLng);
}

/// GCJ-02 → WGS-84 逆变换(迭代法,误差 < 1e-6 度 ≈ 0.1 米)。
///
/// 用途:OSM 等 WGS-84 底图展示。全系统存储统一 GCJ-02,只在需要时转回来。
/// (配送地图换成腾讯瓦片后不再需要这一步 —— 腾讯本身就是 GCJ-02。)
({double lat, double lng}) gcj02ToWgs84(double lat, double lng) {
  if (_outOfChina(lat, lng)) return (lat: lat, lng: lng);
  var wgsLat = lat;
  var wgsLng = lng;
  for (var i = 0; i < 3; i++) {
    final gcj = wgs84ToGcj02(wgsLat, wgsLng);
    wgsLat -= gcj.lat - lat;
    wgsLng -= gcj.lng - lng;
  }
  return (lat: wgsLat, lng: wgsLng);
}

/// GCJ-02 → BD-09(百度坐标)。
///
/// 只在**唤起百度地图导航**时用一次:百度是国内唯一不吃 GCJ-02 的主流地图,
/// 直接把 GCJ-02 传给它,终点会偏出去几百米 —— 骑手照着导航跑到隔壁街。
/// 腾讯与高德都是 GCJ-02,不需要转。
({double lat, double lng}) gcj02ToBd09(double lat, double lng) {
  const xPi = pi * 3000.0 / 180.0;
  final z = sqrt(lng * lng + lat * lat) + 0.00002 * sin(lat * xPi);
  final theta = atan2(lat, lng) + 0.000003 * cos(lng * xPi);
  return (lat: z * sin(theta) + 0.006, lng: z * cos(theta) + 0.0065);
}

/// 两点直线距离(米),骑手端"距你多远/送程多远"用
double distanceMeters(double lat1, double lng1, double lat2, double lng2) {
  const earthRadius = 6371000.0;
  final dLat = _rad(lat2 - lat1);
  final dLng = _rad(lng2 - lng1);
  final a = sin(dLat / 2) * sin(dLat / 2) +
      cos(_rad(lat1)) * cos(_rad(lat2)) * sin(dLng / 2) * sin(dLng / 2);
  return 2 * earthRadius * asin(sqrt(a));
}

double _rad(double deg) => deg * pi / 180.0;

/// 距离展示:850m / 2.3km
String distanceLabel(double meters) => meters >= 1000
    ? '${(meters / 1000).toStringAsFixed(1)} 公里'
    : '${meters.round()} 米';

/// 紧凑版:`1.7km` / `860m`。**只给空间极窄的地方用**
/// (小票、角标)—— 正文一律用 [distanceLabel] 的中文单位:
/// 「km」是给开发看的,不是给点外卖的人和骑手看的
String distanceLabelShort(double meters) => meters >= 1000
    ? '${(meters / 1000).toStringAsFixed(1)}km'
    : '${meters.round()}m';

/// 预计送达(分钟)= 出餐 20 分钟 + 骑行(15km/h ≈ 250m/min)。
///
/// **只用于商家列表卡片的粗估**。真要下单的那个数一律问服务端
/// (`/orders/delivery-fee` 的 `eta_minutes`,和下单后订单上的
/// `eta_at` 同源)—— 客户端算不了路网、算不了这家店今天出餐多快。
///
/// 出餐常量从 15 改成 20,对齐服务端的 `ETA_PREP_MINUTES`(#295)。
/// 原来差这 5 分钟,列表页系统性地比结算页乐观 —— 用户在列表看到
/// 「25 分钟」点进去变「30 分钟」,每一单都这样。宁可列表说得保守些。
int etaMinutes(double distanceM) => 20 + (distanceM / 250).ceil();

/// 纯骑行时间(分钟),不含出餐(#293)。
///
/// 骑手端抢单卡用它:「去取餐 1.7km」看不出要骑多久,而他要在几秒内
/// 判断这单接不接。速度用的是和服务端 `labor_guard.RIDE_SPEED_KMH`
/// **同一个** 15km/h —— 那是个含等灯、找楼栋的保守值,两边不一致的话
/// 骑手看到的分钟数和平台承诺给顾客的对不上。
///
/// ⚠️ 只是给骑手看的参考,**不参与任何时限考核**。
int rideMinutes(double distanceM) => (distanceM / 250).ceil().clamp(1, 999);

const _a = 6378245.0;
const _ee = 0.00669342162296594323;

bool _outOfChina(double lat, double lng) =>
    lng < 72.004 || lng > 137.8347 || lat < 0.8293 || lat > 55.8271;

double _transformLat(double x, double y) {
  var ret = -100.0 +
      2.0 * x +
      3.0 * y +
      0.2 * y * y +
      0.1 * x * y +
      0.2 * sqrt(x.abs());
  ret += (20.0 * sin(6.0 * x * pi) + 20.0 * sin(2.0 * x * pi)) * 2.0 / 3.0;
  ret += (20.0 * sin(y * pi) + 40.0 * sin(y / 3.0 * pi)) * 2.0 / 3.0;
  ret += (160.0 * sin(y / 12.0 * pi) + 320 * sin(y * pi / 30.0)) * 2.0 / 3.0;
  return ret;
}

double _transformLng(double x, double y) {
  var ret = 300.0 +
      x +
      2.0 * y +
      0.1 * x * x +
      0.1 * x * y +
      0.1 * sqrt(x.abs());
  ret += (20.0 * sin(6.0 * x * pi) + 20.0 * sin(2.0 * x * pi)) * 2.0 / 3.0;
  ret += (20.0 * sin(x * pi) + 40.0 * sin(x / 3.0 * pi)) * 2.0 / 3.0;
  ret += (150.0 * sin(x / 12.0 * pi) + 300.0 * sin(x / 30.0 * pi)) * 2.0 / 3.0;
  return ret;
}
