import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 全端共用的 ApiClient 单例(会话持久化在它身上)
final rootApi = ApiClient();

/// 定位失败/所在区域未开通时的兜底坐标(演示城市)
const demoLat = 30.6612;
const demoLng = 104.0823;

/// 登录态变更通知:游客登录成功后 bump,各 tab 监听刷新
final authTick = ValueNotifier<int>(0);

/// 游客模式下点到需要登录的功能:先弹登录页,成功返回 true(原场景继续)。
/// 已登录直接放行。
Future<bool> ensureLoggedIn(BuildContext context) async {
  if (rootApi.isLoggedIn) return true;
  final ok = await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => SmsLoginPage(
            title: '登录后继续',
            role: 'customer',
            api: rootApi,
            onLoggedIn: (context, _) => Navigator.of(context).pop(true),
          )));
  if (ok == true) authTick.value++;
  return ok == true;
}
