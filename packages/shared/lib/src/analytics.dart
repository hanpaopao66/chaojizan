/// 自建埋点客户端(三端共用)。
///
/// 原则与隐私政策第一.7 条一一对应:
///  - 只记录产品行为(页面浏览、搜索词、分享动作),不采集设备指纹;
///  - 只在登录后记录(服务端 /events/batch 也只收登录用户);
///  - 攒批上报、失败静默丢弃 —— 埋点永远不影响用户体验;
///  - 服务端已有的交易数据(下单/支付)不重复埋。
library;

import 'dart:async';

import 'api_client.dart';

class Analytics {
  Analytics._();

  static final Analytics instance = Analytics._();

  /// 便捷入口:`Analytics.track('search', {'q': kw})`
  static void track(String event, [Map<String, dynamic> props = const {}]) =>
      instance._track(event, props);

  ApiClient? _api;
  final List<Map<String, dynamic>> _queue = [];
  Timer? _timer;
  bool _sending = false;

  /// App 启动时调用一次(PrivacyGate 同意之后)。
  void init(ApiClient api) {
    _api = api;
    // 退出登录/换账号时清掉会话级去重(见 resetSession)
    ApiClient.onSessionCleared = resetSession;
  }

  /// 「每个会话只报一次」的去重键(如商家曝光:滚动列表来回划不该刷出几十条)
  final Set<String> _once = {};

  /// 同一个 [key] 在本次会话内只上报一次。
  static void trackOnce(String key, String event,
          [Map<String, dynamic> props = const {}]) =>
      instance._trackOnce(key, event, props);

  void _trackOnce(String key, String event, Map<String, dynamic> props) {
    if (_once.add(key)) _track(event, props);
  }

  /// 退出登录/换账号时清空会话级去重 —— 不清的话新账号对这些对象的
  /// 曝光永远不再上报,漏斗口径会一直偏
  static void resetSession() {
    instance._once.clear();
  }

  void _track(String event, Map<String, dynamic> props) {
    final api = _api;
    if (api == null || !api.isLoggedIn) return;
    _queue.add({'name': event, 'props': props});
    if (_queue.length >= 10) {
      _flush();
    } else {
      // 30 秒兜底:低频操作也能及时上报,不至于等到攒满一批
      _timer ??= Timer(const Duration(seconds: 30), _flush);
    }
  }

  Future<void> _flush() async {
    _timer?.cancel();
    _timer = null;
    if (_sending || _queue.isEmpty) return;
    final api = _api;
    if (api == null || !api.isLoggedIn) {
      _queue.clear();
      return;
    }
    _sending = true;
    final batch = List<Map<String, dynamic>>.of(_queue);
    _queue.clear();
    try {
      await api.trackEvents(batch);
    } catch (_) {
      // 静默丢弃:埋点丢了就丢了,不重试、不打扰用户
    } finally {
      _sending = false;
    }
  }
}
