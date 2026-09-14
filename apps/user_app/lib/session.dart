import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'qr_login/qr_login.dart' show qrLoginHere;
import 'qr_login/qr_login_panel.dart';

/// 全端共用的 ApiClient 单例(会话持久化在它身上)
final rootApi = ApiClient();

/// 定位失败/所在区域未开通时的兜底坐标(演示城市)
const demoLat = 30.6612;
const demoLng = 104.0823;

/// 登录态变更通知:游客登录成功后 bump,各 tab 监听刷新
final authTick = ValueNotifier<int>(0);

/// 游客模式下点到需要登录的功能:先弹登录页,成功返回 true(原场景继续)。
/// 已登录直接放行。
///
/// 网页版、桌面版的登录页先显示扫码 / 一键登录(用已登录的手机 App 扫、或者在手机上确认),
/// 下面可以切到手机号;手机 App 上照旧只有手机号。
Future<bool> ensureLoggedIn(BuildContext context) async {
  if (rootApi.isLoggedIn) return true;
  final ok = await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => SmsLoginPage(
            title: '登录后继续',
            role: 'customer',
            api: rootApi,
            altLogin: qrLoginHere
                ? (context, host) => QrLoginPanel(api: rootApi, host: host)
                : null,
            // 手机浏览器里打开网页版:自己没法扫自己的屏幕,先给手机号,底下能切到扫码 / 一键登录。
            // 宽窄按可用宽度判(三端响应式的口径),和 qrLoginHere 按平台判的是两件事
            altLoginFirst: !kIsWeb || MediaQuery.sizeOf(context).width >= 600,
            onLoggedIn: (context, _) => Navigator.of(context).pop(true),
          )));
  if (ok == true) authTick.value++;
  return ok == true;
}
