/// 苹果推送(APNs)直连的客户端这一半(#384)。
///
/// **不接任何第三方 SDK**:token 是 iOS 系统直接交给 App 的,原生那边
/// (ios/Runner/AppDelegate.swift)把它转成十六进制从 `superz/push` 这条通道送过来,
/// 这里报给自己的服务端。中间没有别人,也就没有配额和费用。
///
/// 安卓在这条路上什么都不做 —— 国内安卓被杀进程之后只有厂商通道叫得醒,那是下一批的事;
/// 在那之前安卓靠已有的 WebSocket 长连接(App 活着就收得到)。
///
/// 全程**静默降级**:没授权、模拟器、注册失败,都只是没有离线推送,
/// 不影响任何别的功能 —— 主通道从来不是它。
library;

import 'dart:io' show Platform;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

typedef PushRegister = Future<void> Function(String channel, String token, bool sandbox);
typedef PushUnregister = Future<void> Function(String channel, String token);

class ApnsService {
  ApnsService._();

  static const _ch = MethodChannel('superz/push');

  static String? _token;
  static bool _sandbox = false;
  static bool _wired = false;

  /// 这台设备上最近拿到的 token(还没拿到是 null)。排查用
  static String? get token => _token;

  static bool get supported => !kIsWeb && Platform.isIOS;

  /// 哪个端。服务端据此选 bundle id —— 填错是静默收不到,所以由各端自己传
  static String app = 'user';

  /// 报给服务端的两个动作。由各 App 在启动时接上自己的 ApiClient ——
  /// shared 包不认识业务接口,不在这里直接发请求
  static PushRegister? onRegister;
  static PushUnregister? onUnregister;

  /// 启动时调一次:接上原生那条通道。**不要求已登录** ——
  /// token 可能比登录先到,先存着,登录之后再报上去
  static void wire() {
    if (!supported || _wired) return;
    _wired = true;
    _ch.setMethodCallHandler((call) async {
      switch (call.method) {
        case 'onToken':
          final args = (call.arguments as Map).cast<String, dynamic>();
          _token = '${args['token']}';
          _sandbox = args['sandbox'] == true;
          await _report();
        case 'onError':
          // 模拟器、没配推送能力的包会走到这儿:不弹、不崩,照常用长连接
          debugPrint('APNs 注册失败(不影响使用): ${call.arguments}');
      }
      return null;
    });
  }

  /// 登录成功后调:问授权 + 注册。已经有 token 就直接报上去。
  static Future<void> onLogin() async {
    if (!supported) return;
    wire();
    if (_token != null) {
      await _report();
      return;
    }
    try {
      await _ch.invokeMethod('register');
    } on PlatformException catch (e) {
      // 用户拒绝通知是**正常选择**,不是错误:安静收场
      debugPrint('APNs 没拿到授权(不影响使用): ${e.code}');
    } on MissingPluginException {
      // 老版本原生壳子里没有这条通道
      debugPrint('APNs 通道不在(老版本外壳),跳过');
    }
  }

  /// 退出登录时调:把这台设备从服务端下线,免得推送继续发到这台手机。
  static Future<void> onLogout() async {
    final t = _token;
    if (!supported || t == null) return;
    try {
      await onUnregister?.call('apns', t);
    } catch (e) {
      debugPrint('APNs 下线失败(下次登录会覆盖): $e');
    }
  }

  static Future<void> _report() async {
    final t = _token;
    if (t == null || t.isEmpty) return;
    try {
      await onRegister?.call('apns', t, _sandbox);
    } catch (e) {
      // 报不上去就下次启动再报 —— 每次启动都会重新注册一遍
      debugPrint('APNs 登记失败(下次启动重试): $e');
    }
  }

  @visibleForTesting
  static void resetForTest() {
    _token = null;
    _sandbox = false;
    _wired = false;
    onRegister = null;
    onUnregister = null;
  }

  @visibleForTesting
  static Future<void> handleForTest(MethodCall call) async {
    if (call.method == 'onToken') {
      final args = (call.arguments as Map).cast<String, dynamic>();
      _token = '${args['token']}';
      _sandbox = args['sandbox'] == true;
      await _report();
    }
  }
}
