import 'dart:async';

import 'package:flutter/foundation.dart' show defaultTargetPlatform, TargetPlatform;
import 'package:geolocator/geolocator.dart';
import 'package:superz_shared/superz_shared.dart';

/// 骑手实时定位:GPS(WGS-84)→ GCJ-02 → 回调。
/// 移动超过 10 米触发一次;上层负责节流上报后端。
class LocationService {
  StreamSubscription<Position>? _subscription;

  ({double lat, double lng})? lastFix;

  /// 启动定位。返回 null 表示成功,否则返回给用户看的错误提示。
  Future<String?> start(void Function(double lat, double lng) onFix) async {
    if (!await Geolocator.isLocationServiceEnabled()) {
      return '手机定位服务未开启,请到系统设置打开';
    }
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      return '未授予定位权限,无法接单配送';
    }

    // 平台专属配置:锁屏/切后台也持续定位
    //  - Android:前台服务 + 常驻通知(系统要求,骑手也能看到"接单中")
    //  - iOS:后台定位 + 状态栏蓝条指示
    final LocationSettings settings;
    if (defaultTargetPlatform == TargetPlatform.android) {
      settings = AndroidSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 10,
        foregroundNotificationConfig: const ForegroundNotificationConfig(
          notificationTitle: '超级赞接单中',
          notificationText: '正在持续定位,顾客可以看到你的配送进度',
          notificationIcon:
              AndroidResource(name: 'ic_launcher', defType: 'mipmap'),
          enableWakeLock: true,
        ),
      );
    } else if (defaultTargetPlatform == TargetPlatform.iOS) {
      settings = AppleSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 10,
        allowBackgroundLocationUpdates: true,
        showBackgroundLocationIndicator: true,
        pauseLocationUpdatesAutomatically: false,
      );
    } else {
      settings = const LocationSettings(
          accuracy: LocationAccuracy.high, distanceFilter: 10);
    }

    _subscription =
        Geolocator.getPositionStream(locationSettings: settings).listen(
      (position) {
        final gcj = wgs84ToGcj02(position.latitude, position.longitude);
        lastFix = gcj;
        onFix(gcj.lat, gcj.lng);
      },
    );
    return null;
  }

  void stop() {
    _subscription?.cancel();
    _subscription = null;
  }
}
