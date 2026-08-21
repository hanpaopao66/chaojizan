import 'dart:async';

import 'package:flutter/foundation.dart' show defaultTargetPlatform, TargetPlatform;
import 'package:geolocator/geolocator.dart';
import 'package:superz_shared/superz_shared.dart';

/// 一次定位:坐标 + **拿到它的时刻**。
///
/// 时间戳不是可有可无的元数据,是这一批要修的核心 ——
/// 没有它就分不清「骑手停在这儿没动」和「定位半小时前就死了」,
/// 而这两件事在界面上、在上报数据里长得一模一样。
typedef Fix = ({double lat, double lng, DateTime at});

/// 位置多久没更新就不能再当「当前位置」用。
///
/// 骑手在路上走,超过两分钟一个新点都没有,基本就是定位出问题了。
/// 服务端的位置过期是 5 分钟(Redis),这里取更严 —— 宁可早一点闭嘴,
/// 让服务端的过期保护自然生效
const kFixFreshWithin = Duration(minutes: 2);

/// 保活定时器每一跳该干什么。
enum PositionReport {
  /// 位置是新的,照报
  fix,

  /// 压根没有真 GPS(演示模式/权限没给),报兜底坐标 ——
  /// 这条路径本来就不声称自己是真实位置
  fallback,

  /// GPS 说自己活着但还没出第一个点:等,别报
  waiting,

  /// **位置过期了:什么都不报。**
  ///
  /// 这是这一批要修的核心。定位死掉之后 `lastFix` 会永远停在最后一个点,
  /// 原来的保活定时器每 15 秒照报不误 —— 服务端于是一直收到
  /// 「他还在这儿」,那套「位置过期就停用接单半径筛选」的保护
  /// **永远不会触发**。骑手被一个假心跳挡在筛选外面,还以为是今天没单。
  ///
  /// 不报,服务端的位置就会自然过期,保护按设计生效。
  stale,
}

/// 抽成纯函数是为了**能单测** ——
/// 「陈年坐标不许上报」这条规则塞在 Timer 回调里,没有任何办法验证。
PositionReport keepAliveDecision({
  required Fix? fix,
  required bool gpsActive,
  DateTime? now,
  Duration freshWithin = kFixFreshWithin,
}) {
  final at = now ?? DateTime.now();
  if (fix != null && at.difference(fix.at) <= freshWithin) {
    return PositionReport.fix;
  }
  if (!gpsActive) return PositionReport.fallback;
  return fix == null ? PositionReport.waiting : PositionReport.stale;
}

/// 骑手实时定位:GPS(WGS-84)→ GCJ-02 → 回调。
/// 移动超过 10 米触发一次;上层负责节流上报后端。
class LocationService {
  StreamSubscription<Position>? _subscription;

  /// 最后一次定位。**带时间戳** —— 判新鲜度用,见 [isFresh]
  Fix? lastFix;

  /// 定位流出错时的通知。
  ///
  /// 之前 `listen` 只挂了 onData:关定位、进地库、权限被撤销都会让这条流
  /// 出错,而出错的流**就地终止** —— 订阅悄悄死掉,没有任何人知道。
  /// 于是 `lastFix` 停在最后一个坐标上,保活定时器每 15 秒还在把这个
  /// 陈年坐标当新位置上报,服务端那套「位置过期就停用接单半径筛选」的保护
  /// 因此**永远不会触发**。骑手看到的只是「今天怎么没单」,猜不到是定位死了。
  void Function(String message)? onError;

  /// 定位是不是还活着(有订阅)。UI 用它决定要不要说「定位异常」
  bool get isActive => _subscription != null;

  /// 位置够不够新。拿一个过期的坐标当「当前位置」上报是在编数据
  bool isFresh({Duration within = kFixFreshWithin}) =>
      keepAliveDecision(fix: lastFix, gpsActive: true, freshWithin: within) ==
      PositionReport.fix;

  /// 启动定位。返回 null 表示成功,否则返回给用户看的错误提示。
  Future<String?> start(void Function(double lat, double lng) onFix) async {
    // 先把上一次的订阅停掉。重复 start(切换上线状态、权限弹窗走一遍回来)
    // 会叠出两条流:两条都在回调、都在上报,而 stop() 只认得最后一条
    await _subscription?.cancel();
    _subscription = null;

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
        lastFix = (lat: gcj.lat, lng: gcj.lng, at: DateTime.now());
        onFix(gcj.lat, gcj.lng);
      },
      // 流一出错就终止,所以这里必须把订阅清干净并**告诉上层** ——
      // 静默终止 = 骑手一整天在跑一个已经死掉的定位
      onError: (Object e) {
        _subscription?.cancel();
        _subscription = null;
        onError?.call(_friendly(e));
      },
      // onDone:系统主动关掉了这条流(权限被撤、定位服务被关)。
      // 和出错一样是"从此不再有新位置",一样要说
      onDone: () {
        _subscription = null;
        onError?.call('定位已停止,可能是定位权限或定位服务被关掉了');
      },
    );
    return null;
  }

  /// 底层异常不许原样给骑手看(和 ApiClient 同一个立场)
  static String _friendly(Object e) {
    final raw = e.toString();
    if (e is LocationServiceDisabledException ||
        raw.contains('LocationServiceDisabled')) {
      return '手机定位服务被关掉了,打开后才能继续接单';
    }
    if (e is PermissionDeniedException || raw.contains('PermissionDenied')) {
      return '定位权限被收回了,去系统设置里重新允许';
    }
    return '定位中断了,检查一下定位开关和权限';
  }

  void stop() {
    _subscription?.cancel();
    _subscription = null;
    // 位置作废:停了之后再拿这个坐标上报就是在报一个过去的位置
    lastFix = null;
  }
}
