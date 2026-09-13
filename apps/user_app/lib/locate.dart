import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';

/// 用户端所有「拿当前位置 / 最后已知位置」都走这里,别直接调 Geolocator 的取位置方法
/// (scripts/check_location_manager.sh 会拦)。
///
/// 安卓上强制用系统的 LocationManager,不走 Google Play 服务的融合定位:geolocator 在装了
/// Google Play 服务的手机上默认走 FusedLocationProvider(play-services-location),
/// 那条路没列在隐私政策的第三方 SDK 表里。国内手机大多没有 Google Play 服务,本来走的
/// 就是 LocationManager —— 统一成一条路,SDK 表那句「未接入其他收集个人信息的第三方 SDK」
/// 才成立(2026-09-13 定)。iOS 走 CoreLocation、网页走浏览器定位,不受影响。
LocationSettings deviceLocationSettings(
        {LocationAccuracy accuracy = LocationAccuracy.best,
        Duration? timeLimit}) =>
    !kIsWeb && defaultTargetPlatform == TargetPlatform.android
        ? AndroidSettings(
            accuracy: accuracy,
            timeLimit: timeLimit,
            forceLocationManager: true)
        : LocationSettings(accuracy: accuracy, timeLimit: timeLimit);

/// 现在的位置(要已经有定位权限;没权限会抛错,和 Geolocator 一样)
Future<Position> deviceCurrentPosition(
        {LocationAccuracy accuracy = LocationAccuracy.best,
        Duration? timeLimit}) =>
    Geolocator.getCurrentPosition(
        locationSettings:
            deviceLocationSettings(accuracy: accuracy, timeLimit: timeLimit));

/// 系统缓存的最后一次位置:不等 GPS,拿不到回 null
Future<Position?> deviceLastKnownPosition() =>
    Geolocator.getLastKnownPosition(forceAndroidLocationManager: true);
