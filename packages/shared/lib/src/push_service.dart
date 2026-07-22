/// 极光推送(JPush)客户端封装,三端共用。
///
/// 配置齐全才启用,缺任何一环都整体静默降级(不影响 WebSocket/轮询主通道):
///  1. Dart 侧:构建时传 --dart-define=SUPERZ_JPUSH_KEY=<AppKey>
///  2. Android 侧:各 App 的 build.gradle.kts 里 manifestPlaceholders
///     的 JPUSH_APPKEY 填同一个 AppKey(默认空)
///  3. 服务端:server/.env 填 jpush_app_key / jpush_master_secret
///
/// 别名规则与服务端约定一致:u{user_id}(见 server/app/services/push.py)。
library;

import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:jpush_flutter/jpush_flutter.dart';
import 'package:jpush_flutter/jpush_interface.dart';

class PushService {
  static const String _appKey = String.fromEnvironment('SUPERZ_JPUSH_KEY');

  static final JPushFlutterInterface _jpush = JPush.newJPush();
  static bool _ready = false;

  static bool get _supported =>
      _appKey.isNotEmpty && !kIsWeb && (Platform.isAndroid || Platform.isIOS);

  /// 各端 main() 里 runApp 前调用一次。
  static Future<void> init() async {
    if (!_supported) return;
    try {
      _jpush.setup(
        appKey: _appKey,
        channel: 'developer',
        production: kReleaseMode,
        debug: kDebugMode,
      );
      _jpush.applyPushAuthority(
          const NotificationSettingsIOS(sound: true, alert: true, badge: true));
      _ready = true;
    } catch (e) {
      debugPrint('JPush 初始化失败(不影响使用): $e');
    }
  }

  /// 登录成功后绑定别名,服务端按 u{userId} 定向推送。
  static Future<void> onLogin(int userId) async {
    if (!_ready) return;
    try {
      await _jpush.setAlias('u$userId');
    } catch (e) {
      debugPrint('JPush setAlias 失败: $e');
    }
  }

  /// 退出登录时解绑,防止推送发给已登出的设备。
  static Future<void> onLogout() async {
    if (!_ready) return;
    try {
      await _jpush.deleteAlias();
    } catch (e) {
      debugPrint('JPush deleteAlias 失败: $e');
    }
  }
}
