import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// 自建分发渠道的安装器(#123)。仅 Android;其他平台一律返回"不支持",
/// 调用方据此退回到"跳浏览器下载"的老路。
class ApkInstaller {
  ApkInstaller._();

  static const _channel = MethodChannel('superz/apk_installer');

  static bool get supported =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android && Platform.isAndroid;

  /// 用户是否已授予本应用「安装未知应用」。Android 8.0 以下恒为 true。
  static Future<bool> canInstall() async {
    if (!supported) return false;
    try {
      return await _channel.invokeMethod<bool>('canInstall') ?? false;
    } catch (_) {
      return false;
    }
  }

  /// 跳到本应用的「安装未知应用」设置页。返回 false 表示这台机器上跳不过去
  /// (个别定制 ROM 没有这个页面),调用方应退回浏览器下载。
  static Future<bool> openInstallSettings() async {
    if (!supported) return false;
    try {
      return await _channel.invokeMethod<bool>('openInstallSettings') ?? false;
    } catch (_) {
      return false;
    }
  }

  /// 把下载好的 APK 交给系统安装器。抛异常表示拉不起来,调用方退回浏览器。
  static Future<void> install(String path) async {
    if (!supported) {
      throw UnsupportedError('当前平台不支持应用内安装');
    }
    await _channel.invokeMethod<bool>('install', {'path': path});
  }
}
