/// 权限申请"先告知目的、后调系统弹窗"封装(应用商店合规,三端共用)。
///
/// 商店要求:调起系统权限弹窗前,必须先用应用内弹窗说明申请目的,
/// 用户点"去授权"才触发系统弹窗;拒绝不影响其他功能。
/// 用法:所有定位/相机/相册/蓝牙/通知的调用点,先
/// `if (!await PermissionRationale.ensure(context, AppPermissionKind.photos)) return;`
/// 再调 ImagePicker/Geolocator 等。已同意过说明的直接放行,不重复弹。
///
/// 各权限的目的文案与隐私政策附录(legal.dart)同源,改动要一起改。
library;

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

enum AppPermissionKind { location, locationRider, camera, photos, bluetooth, notification }

class PermissionRationale {
  PermissionRationale._();

  static const _prefsPrefix = 'perm_rationale_v1_';

  /// 与隐私政策附录一致的默认文案:(标题, 目的说明)
  static (String, String) _copy(AppPermissionKind kind) => switch (kind) {
        AppPermissionKind.location => (
            '需要使用定位权限',
            '用于展示附近商家、计算配送费。\n拒绝后将展示演示区域内容,你仍可手动选择收货地址。'
          ),
        AppPermissionKind.locationRider => (
            '需要使用定位权限',
            '接单配送期间记录配送轨迹,用于订单展示与配送费计算;下线后不收集位置。\n拒绝后无法接单配送。'
          ),
        AppPermissionKind.camera => (
            '需要使用相机权限',
            '用于拍摄照片并上传。\n拒绝不影响其他功能。'
          ),
        AppPermissionKind.photos => (
            '需要访问相册',
            '用于选取图片并上传。\n拒绝不影响其他功能。'
          ),
        AppPermissionKind.bluetooth => (
            '需要使用蓝牙权限',
            '用于连接蓝牙小票打印机,打印订单小票。\n拒绝不影响其他功能。'
          ),
        AppPermissionKind.notification => (
            '需要开启通知',
            '用于接收新订单与订单状态提醒。\n拒绝后无法收到提醒,可在 App 内查看。'
          ),
      };

  /// 先告知后申请:返回 true 表示可以继续调起系统权限/相应功能。
  ///
  /// 首次调用弹应用内说明弹窗;用户点过"去授权"后本地记住,之后直接放行
  /// (系统弹窗只会出现一次,说明弹窗也只需要出现在它之前)。
  static Future<bool> ensure(BuildContext context, AppPermissionKind kind,
      {String? reason}) async {
    final prefs = await SharedPreferences.getInstance();
    final key = '$_prefsPrefix${kind.name}';
    if (prefs.getBool(key) == true) return true;
    if (!context.mounted) return false;

    final (title, defaultReason) = _copy(kind);
    final agreed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(reason ?? defaultReason, style: const TextStyle(height: 1.6)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('暂不')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('去授权')),
        ],
      ),
    );
    if (agreed == true) {
      await prefs.setBool(key, true);
      return true;
    }
    return false;
  }

  /// 系统层已永久拒绝时的引导:弹窗解释并提供"去系统设置"。
  /// [openSettings] 传各端插件的打开设置方法(如 Geolocator.openAppSettings)。
  static Future<void> showSettingsGuide(BuildContext context,
      {required String message,
      required Future<void> Function() openSettings}) async {
    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('权限未开启'),
        content: Text(message, style: const TextStyle(height: 1.6)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('去系统设置')),
        ],
      ),
    );
    if (go == true) await openSettings();
  }
}
