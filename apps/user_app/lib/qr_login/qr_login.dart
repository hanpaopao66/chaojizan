import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 扫码登录 / 一键登录(用户端网页版、桌面版)在客户端这一侧的几样东西。
///
/// 服务端的流程和安全规矩见 server/app/services/qr_login.py。这边:
/// - 网页版、桌面版的登录页先显示扫码 / 一键登录([qrLoginHere],面板在 qr_login_panel.dart);
/// - 手机 App 「扫一扫」(qr_scan_page.dart)扫到登录码 → 确认页(qr_confirm_page.dart);
/// - 一键登录的确认请求:[QrLoginWatcher] 收到用户事件、回到前台时去查,有就弹确认页;
/// - 「设置 → 已登录的网页和电脑」(login_devices_page.dart)。

/// 登录页要不要先显示扫码 / 一键登录:网页版、桌面版要,手机 App 上照旧手机号。
///
/// 判据是**平台**不是屏幕宽度:问的是「这台设备旁边有没有一台已登录的手机能扫它 / 能确认」。
bool get qrLoginHere =>
    kIsWeb ||
    defaultTargetPlatform == TargetPlatform.macOS ||
    defaultTargetPlatform == TargetPlatform.windows ||
    defaultTargetPlatform == TargetPlatform.linux;

/// 这台设备能「扫一扫」、能批准别的设备登录:只有手机 App(安卓、iOS)
bool get canScanHere =>
    !kIsWeb &&
    (defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS);

/// 建会话时报给服务端的客户端类型和系统(服务端只认 web / desktop,和 macos / windows / linux)
String get qrClientKind => kIsWeb ? 'web' : 'desktop';

String get qrDesktopPlatform => kIsWeb
    ? ''
    : switch (defaultTargetPlatform) {
        TargetPlatform.macOS => 'macos',
        TargetPlatform.windows => 'windows',
        TargetPlatform.linux => 'linux',
        _ => '',
      };

/// 这台网页 / 电脑记住的「上次扫码登录的是谁」,一键登录用。
///
/// device_key **自己登不了录**:拿着它只能让服务端去问一次那个人的手机,手机上点了确认才进得去。
/// 所以放在本地存储里(网页版就是浏览器的 localStorage):被人读走,对方也只能往你手机上弹确认框。
/// 名字和头像只是给「一键登录」那一屏看的,服务端不看它们。
/// 退出登录**不清**它 —— 下次打开还认得出这个账号,这正是一键登录要的;点「切换账号」换人扫码登录后被替换。
class QrLoginMemory {
  const QrLoginMemory({
    required this.deviceKey,
    required this.deviceId,
    required this.userId,
    required this.name,
    required this.avatarUrl,
  });

  final String deviceKey;

  /// 服务端 login_devices 的 id:手机上移除了哪一台,靠它认出是不是自己
  final int deviceId;
  final int userId;
  final String name;
  final String avatarUrl;

  static const _prefsKey = 'qr_login_device_v1';

  static Future<QrLoginMemory?> load() async {
    try {
      final raw = (await SharedPreferences.getInstance()).getString(_prefsKey);
      if (raw == null || raw.isEmpty) return null;
      final m = jsonDecode(raw) as Map<String, dynamic>;
      final key = m['key'] as String? ?? '';
      if (key.isEmpty) return null;
      return QrLoginMemory(
        deviceKey: key,
        deviceId: (m['device_id'] as num?)?.toInt() ?? 0,
        userId: (m['user_id'] as num?)?.toInt() ?? 0,
        name: m['name'] as String? ?? '',
        avatarUrl: m['avatar_url'] as String? ?? '',
      );
    } catch (_) {
      return null;
    }
  }

  Future<void> save() async {
    try {
      await (await SharedPreferences.getInstance()).setString(
          _prefsKey,
          jsonEncode({
            'key': deviceKey,
            'device_id': deviceId,
            'user_id': userId,
            'name': name,
            'avatar_url': avatarUrl,
          }));
    } catch (_) {}
  }

  static Future<void> clear() async {
    try {
      await (await SharedPreferences.getInstance()).remove(_prefsKey);
    } catch (_) {}
  }
}

/// 扫到的东西是不是超级赞的登录码,是的话返回 sid。
///
/// 认的是 `/l/<sid>` 这个路径,域名得是官方的,或者就是这个 App 连的那台服务器(开发、自部署时和官方不一样)。
/// 别的域名上长得一样的链接不认 —— 那不是我们发的码,当普通内容给人看、让人自己决定。
String? loginSidOf(String raw, {required String apiBase}) {
  final uri = Uri.tryParse(raw.trim());
  if (uri == null || (uri.scheme != 'https' && uri.scheme != 'http')) return null;
  final hosts = <String>{'chaojizan.cc', 'www.chaojizan.cc'};
  final own = Uri.tryParse(apiBase)?.host ?? '';
  if (own.isNotEmpty) hosts.add(own.toLowerCase());
  if (!hosts.contains(uri.host.toLowerCase())) return null;
  final seg = uri.pathSegments.where((s) => s.isNotEmpty).toList();
  if (seg.length != 2 || seg[0] != 'l') return null;
  return RegExp(r'^[A-Za-z0-9_-]{32,64}$').hasMatch(seg[1]) ? seg[1] : null;
}

/// token 里写的那台设备(`ld`)。只读不验 —— 验签是服务端的事,这里只是认一认「被移除的是不是我」
int? loginDeviceOfToken(String? token) {
  if (token == null) return null;
  final parts = token.split('.');
  if (parts.length != 3) return null;
  try {
    final body = parts[1].padRight((parts[1].length + 3) ~/ 4 * 4, '=');
    final claims = jsonDecode(utf8.decode(base64Url.decode(body))) as Map<String, dynamic>;
    return (claims['ld'] as num?)?.toInt();
  } catch (_) {
    return null;
  }
}

/// 一键登录的确认请求、和「这台设备在手机上被移除了」,两件事都靠用户事件实时知道。
///
/// - **手机 App**:收到 `qr_login` 事件、回到前台、刚启动(从推送点进来)的时候,查一次
///   /auth/qr/pending,有就弹确认页。**以查到的为准,不以事件为准** —— 断线补齐会把几个小时前的
///   事件也补过来,那些早就过期了;
/// - **网页版 / 桌面版**:收到 `login_device` 事件,而且被移除的正是现在这个会话的那台设备,当场退出登录。
///   收不到也会退(下一次请求就 401),这里只是让它不用等。
class QrLoginWatcher with WidgetsBindingObserver {
  QrLoginWatcher._();

  static final QrLoginWatcher instance = QrLoginWatcher._();

  ApiClient? _api;
  StreamSubscription<({String type, Map<String, dynamic> data})>? _sub;

  /// 弹确认页(首页挂上;确认页关掉之后才返回)
  Future<void> Function(Map<String, dynamic> request)? presenter;

  /// 这台网页 / 电脑被手机移除、已经退出登录之后调(首页挂上,弹一句提示、切回游客)
  void Function()? onSignedOut;

  bool _showing = false;
  bool _checking = false;
  bool _observing = false;

  void start(ApiClient api,
      Stream<({String type, Map<String, dynamic> data})> userEvents) {
    _api = api;
    _sub ??= userEvents.listen(_onEvent);
    if (!_observing) {
      WidgetsBinding.instance.addObserver(this);
      _observing = true;
    }
    unawaited(check());
  }

  void stop() {
    _sub?.cancel();
    _sub = null;
    if (_observing) {
      WidgetsBinding.instance.removeObserver(this);
      _observing = false;
    }
    _api = null;
  }

  void _onEvent(({String type, Map<String, dynamic> data}) e) {
    if (e.type == 'qr_login') {
      unawaited(check());
    } else if (e.type == 'login_device' && e.data['revoked'] == true) {
      unawaited(_maybeSignOut((e.data['id'] as num?)?.toInt()));
    }
  }

  Future<void> _maybeSignOut(int? deviceId) async {
    final api = _api;
    if (api == null || deviceId == null) return;
    final memory = await QrLoginMemory.load();
    if (memory?.deviceId == deviceId) await QrLoginMemory.clear();
    if (loginDeviceOfToken(api.token) != deviceId) return;
    await api.clearSession();
    onSignedOut?.call();
  }

  /// 有没有待确认的一键登录,有就弹确认页(只在手机 App 上)
  Future<void> check() async {
    final api = _api;
    if (api == null || !canScanHere || !api.isLoggedIn) return;
    if (_showing || _checking || presenter == null) return;
    _checking = true;
    try {
      final items = await api.pendingQrLogins();
      if (items.isEmpty || presenter == null) return;
      _showing = true;
      try {
        await presenter!(items.first);
      } finally {
        _showing = false;
      }
    } catch (_) {
      // 查不到就等下一次事件 / 回到前台
    } finally {
      _checking = false;
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) unawaited(check());
  }
}
