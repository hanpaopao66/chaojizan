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
/// 用途:天地图/OSM 等 WGS-84 底图展示。全系统存储仍统一 GCJ-02,
/// 只在贴瓦片的那一刻转回来。
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
String distanceLabel(double meters) =>
    meters >= 1000 ? '${(meters / 1000).toStringAsFixed(1)}km' : '${meters.round()}m';

/// 预计送达(分钟)= 出餐 15 分钟 + 骑行(15km/h ≈ 250m/min)。
/// 首页卡片、点单页、订单追踪共用这一个公式,口径一致。
int etaMinutes(double distanceM) => 15 + (distanceM / 250).ceil();

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
