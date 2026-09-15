/// 小程序桥 v2 的**分发器**(DEV-PROMPTS-39 §5.4、#324)。纯逻辑,两端(手机 WebView、web iframe)共用。
///
/// 一条页面发来的消息走四道关:
///
/// 1. 协议版本(`v == 2`)—— 不是 v2 的一律不理;
/// 2. **会话令牌** —— 宿主每次页面加载生成一个,只发给主框架(init 消息)。
///    不带或带错令牌的调用**静默丢弃**:原生 JS 通道对页面里所有 frame 都可见,
///    光看主框架 URL 挡不住页面里嵌的第三方 iframe 冒充;
/// 3. **能力当场查** —— 每次调用都查(不是打开时查一次):平台随时可能收回能力;
/// 4. 处理函数;抛 [BridgeError] 回对应错误码,接口错误按 [ApiException.code] 透传。
///
/// 方法表(名字 → 所需能力 → 处理函数)由容器注册,见 container.dart。
library;

import 'dart:convert';
import 'dart:math';

import 'package:superz_shared/superz_shared.dart';

/// 桥错误码(§5.4)。页面按 code 判断。
abstract final class BridgeCode {
  static const capabilityNotGranted = 4001;
  static const userDenied = 4002;
  static const notSupported = 4003;
  static const invalidParams = 4004;
  static const rateLimited = 4005;
  static const quotaExceeded = 4006;
  static const revConflict = 4007;
  static const notInHost = 4008;
  static const appSuspended = 4009;
  static const internal = 5000;
  static const network = 5001;
}

class BridgeError implements Exception {
  const BridgeError(this.code, this.message);

  final int code;
  final String message;

  @override
  String toString() => 'BridgeError($code, $message)';
}

typedef BridgeHandler = Future<Object?> Function(Map<String, dynamic> params);

/// 一个桥方法:要什么能力([capability] 为 null = 所有应用都能调)、怎么处理。
class BridgeMethod {
  const BridgeMethod(this.handler, {this.capability});

  final BridgeHandler handler;
  final String? capability;
}

/// 生成会话令牌:128 位随机数的 base64url。
String newSessionToken([Random? random]) {
  final r = random ?? Random.secure();
  final bytes = List<int>.generate(16, (_) => r.nextInt(256));
  return base64Url.encode(bytes).replaceAll('=', '');
}

class BridgeDispatcher {
  BridgeDispatcher({
    required this.methods,
    required this.capabilities,
    required this.buildInit,
    this.onNotice,
    this.onCall,
    String? token,
  }) : token = token ?? newSessionToken();

  final Map<String, BridgeMethod> methods;

  /// 这个应用**此刻**有哪些能力(每次调用都重新读)
  final List<String> Function() capabilities;

  /// 握手时发给页面的 init 消息(不含 token,dispatcher 自己加)
  final Map<String, dynamic> Function() buildInit;

  /// 页面发来的 notice(CSP 违规等)。调试面板用
  final void Function(String name, Object? data)? onNotice;

  /// 每次被接受的调用(调试面板的桥调用日志)。不含参数原文里的大字段
  final void Function(String method, bool ok, int? code)? onCall;

  /// 当前页面的会话令牌。页面每次重新加载(主框架导航)时调 [rotate]
  String token;

  void rotate() => token = newSessionToken();

  /// 处理页面发来的一条消息,返回要回给页面的那一条(null = 不回)。
  Future<Map<String, dynamic>?> handle(Object? raw) async {
    final msg = raw is String ? _decode(raw) : raw;
    if (msg is! Map || msg['v'] != 2) return null;
    switch (msg['type']) {
      case 'hello':
        // hello 不需要令牌(页面还没有);回的 init 只会送到主框架 —— 传输层保证
        return {...buildInit(), 'v': 2, 'type': 'init', 'token': token};
      case 'notice':
        if (msg['token'] == token) onNotice?.call('${msg['name']}', msg['data']);
        return null;
      case 'call':
        break;
      default:
        return null;
    }
    if (msg['token'] != token) return null; // 冒充的、过期页面的:一律静默丢弃
    final id = msg['id'];
    final method = '${msg['method']}';
    final params = msg['params'] is Map
        ? Map<String, dynamic>.from(msg['params'] as Map)
        : <String, dynamic>{};
    final m = methods[method];
    if (m == null) {
      return _fail(id, method, const BridgeError(BridgeCode.notSupported, '宿主不支持这个方法'));
    }
    if (m.capability != null && !capabilities().contains(m.capability)) {
      return _fail(id, method,
          const BridgeError(BridgeCode.capabilityNotGranted, '这个小程序没有申请到这项能力'));
    }
    try {
      final data = await m.handler(params);
      onCall?.call(method, true, null);
      return {'v': 2, 'type': 'reply', 'id': id, 'ok': true, 'data': data};
    } on BridgeError catch (e) {
      return _fail(id, method, e);
    } on ApiException catch (e) {
      return _fail(id, method, BridgeError(
          e.code ?? (e.isNetwork ? BridgeCode.network : BridgeCode.internal), e.message));
    } catch (e) {
      return _fail(id, method, const BridgeError(BridgeCode.internal, '宿主内部错误'));
    }
  }

  Map<String, dynamic> _fail(Object? id, String method, BridgeError e) {
    onCall?.call(method, false, e.code);
    return {
      'v': 2, 'type': 'reply', 'id': id, 'ok': false,
      'error': {'code': e.code, 'message': e.message},
    };
  }

  static Map<String, dynamic> event(String name, [Object? data]) =>
      {'v': 2, 'type': 'event', 'name': name, if (data != null) 'data': data};

  static Object? _decode(String s) {
    try {
      return jsonDecode(s);
    } catch (_) {
      return null;
    }
  }
}

/// 桥方法 → 能力名(和服务端 miniapp_platform 的 BASIC/GAME/REQUESTABLE 同一套名字)。
const kMethodCapability = <String, String?>{
  'ready': null,
  'expand': null,
  'close': null,
  'setHeaderColor': null,
  'setBackgroundColor': null,
  'setBottomBarColor': null,
  'setClosingConfirmation': null,
  'mainButton': null,
  'secondaryButton': null,
  'backButton': null,
  'settingsButton': null,
  'haptic': 'haptics',
  'showPopup': 'popup',
  'openLink': 'openLink',
  'share': 'share',
  'CloudStorage.getItems': 'storage',
  'CloudStorage.setItem': 'storage',
  'CloudStorage.removeItems': 'storage',
  'CloudStorage.getKeys': 'storage',
  'requestFullscreen': 'fullscreen',
  'exitFullscreen': 'fullscreen',
  'lockOrientation': 'orientation',
  'unlockOrientation': 'orientation',
  'requestProfile': 'profile',
  'legacy.getInitData': 'initData',
};

/// 颜色参数只收 #RRGGBB
bool isHexColor(Object? v) => v is String && RegExp(r'^#[0-9A-Fa-f]{6}$').hasMatch(v);

/// 导航白名单:托管应用只许本应用的托管 origin。
bool originAllowed(String url, Iterable<String> allowed) {
  final uri = Uri.tryParse(url);
  if (uri == null || !(uri.isScheme('https') || uri.isScheme('http'))) return false;
  final set = allowed.map((o) => Uri.tryParse(o)?.origin).whereType<String>().toSet();
  return set.contains(uri.origin);
}

/// 网页版宿主的「导航逃逸」判定(#335)。
///
/// 手机上 WebView 的导航回调拦得住页面跳去别的站;网页版是跨域 iframe,页面自己
/// `location.href = 别的站` 父页面既拦不住、也读不到新地址。
///
/// 办法:iframe 每次 load 之后,宿主用 postMessage 发一条带新 nonce 的 `ping`,
/// **targetOrigin 写托管 origin** —— 浏览器只在 iframe 当前文档正是这个 origin 时才投递。
/// SDK 收到就回 `pong`(同一个 nonce)。[deadline] 内等不到,现在显示的就不是这个小程序:
/// 别的站根本收不到这一问;没引 SDK 的页面也答不上(所以文档要求托管的每个 HTML 页都引 SDK)。
/// nonce 每次 load 都换:上一个文档的回答顶不了这一个。
class EscapeWatch {
  EscapeWatch({this.deadline = const Duration(seconds: 8), Random? random}) : _random = random;

  final Duration deadline;
  final Random? _random;
  String? _nonce;

  /// iframe 又 load 了一次:换一个 nonce,返回它(拿去发 ping)。
  String onLoad() => _nonce = newSessionToken(_random);

  void onPong(Object? nonce) {
    if (nonce != null && nonce == _nonce) _nonce = null;
  }

  /// 还在等这次 load 的回答
  bool get waiting => _nonce != null;
}
