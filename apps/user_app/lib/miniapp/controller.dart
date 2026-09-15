/// 一个打开着的小程序:容器的状态 + 桥方法的实现(#324)。
///
/// 和界面、传输都分开:
/// - 画界面的是 container.dart(顶栏、底栏按钮、启动页、弹窗),它实现 [MiniAppUi];
/// - 搬消息的是 view_mobile.dart / view_web.dart,它们设置 [send] 并把收到的消息交给 [dispatcher];
/// - 这里只管「这个方法该做什么、状态怎么变」—— test/miniapp_controller_test.dart 直接测它。
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:superz_shared/superz_shared.dart';

import 'bridge.dart';

/// 宿主实现的桥协议版本(和 SDK 的 PROTOCOL_VERSION 是同一个数)。
///
/// 2.1:所有应用都能全屏、`setBottomBarColor`、主题色 16 个键。页面的 SDK 按它判断能力,
/// Telegram 兼容层也按它折算 `Telegram.WebApp.version`(2.1 起报 8.0)。
const kBridgeProtocolVersion = '2.1';

/// 启动地址片段里的 `szWebAppVersion` 换成宿主自己的协议版本。
///
/// 片段是服务端拼的,服务端不知道是哪个版本的 App 在开,只能写最低的 2.0;SDK 加载时同步读片段,
/// 页面启动时的同步探测(Telegram 代码常见的 `isVersionAtLeast('8.0')`)要在 init 到之前就看到真实版本。
/// 只改这一个参数,其余(尤其是 initData)一个字节都不动。没有片段的地址原样返回。
String withHostVersion(String url, [String version = kBridgeProtocolVersion]) {
  final i = url.indexOf('#');
  if (i < 0) return url;
  final frag = url.substring(i + 1);
  final re = RegExp(r'(^|&)szWebAppVersion=[^&]*');
  final next = re.hasMatch(frag)
      ? frag.replaceFirstMapped(re, (m) => '${m[1]}szWebAppVersion=$version')
      : '$frag&szWebAppVersion=$version';
  return '${url.substring(0, i + 1)}$next';
}

/// 底栏按钮(MainButton / SecondaryButton)的状态。宿主原生画,页面只能改文字和状态。
@immutable
class BottomButtonState {
  const BottomButtonState({
    this.text = '',
    this.color,
    this.textColor,
    this.visible = false,
    this.active = true,
    this.progress = false,
    this.position = 'left',
  });

  factory BottomButtonState.fromParams(Map<String, dynamic> p) => BottomButtonState(
        text: String.fromCharCodes('${p['text'] ?? ''}'.runes.take(64)),
        color: isHexColor(p['color']) ? p['color'] as String : null,
        textColor: isHexColor(p['text_color']) ? p['text_color'] as String : null,
        visible: p['is_visible'] == true,
        active: p['is_active'] != false,
        progress: p['is_progress_visible'] == true,
        position: '${p['position'] ?? 'left'}',
      );

  final String text;
  final String? color;
  final String? textColor;
  final bool visible;
  final bool active;
  final bool progress;
  final String position;
}

/// 容器替控制器做的那些「要画东西 / 要问用户」的事。
abstract class MiniAppUi {
  Future<String?> showPopup(String? title, String message, List<Map<String, dynamic>> buttons);

  /// 「即将离开超级赞」确认;用户同意后交系统浏览器打开
  Future<bool> openExternal(Uri url);
  Future<bool> share(String text);
  void haptic(String type, String? style);
  Future<bool> askProfileConsent();
  void close();
  void expand();
  Future<bool> setFullscreen(bool on);
  Future<bool> lockOrientation(bool lock);
}

/// 桥调用日志的一行(调试面板用,开发者选项里的「小程序调试」打开时显示)。
class BridgeLogEntry {
  BridgeLogEntry(this.method, this.ok, this.code) : at = DateTime.now();
  final String method;
  final bool ok;
  final int? code;
  final DateTime at;
}

class MiniAppController extends ChangeNotifier {
  MiniAppController({
    required this.api,
    required this.launch,
    required this.ui,
    required this.platform,
  }) {
    dispatcher = BridgeDispatcher(
      methods: _methods(),
      capabilities: () => launch.capabilities,
      buildInit: _init,
      onCall: (m, ok, code) {
        log.add(BridgeLogEntry(m, ok, code));
        if (log.length > 200) log.removeAt(0);
        if (code == BridgeCode.appSuspended) onSuspended?.call();
      },
      onNotice: (name, data) {
        if (name == 'csp') notices.add('CSP 拦截:$data');
        if (notices.length > 50) notices.removeAt(0);
      },
    );
  }

  final ApiClient api;
  MiniAppLaunch launch;
  final MiniAppUi ui;
  final String platform;
  late final BridgeDispatcher dispatcher;

  /// 传输层设置:把一条消息送进页面(只送主框架)
  void Function(Map<String, dynamic> msg)? send;

  /// 应用被暂停 / 隔离(桥调用回 4009,或者轮询状态发现)
  VoidCallback? onSuspended;

  final log = <BridgeLogEntry>[];
  final notices = <String>[];

  // ---- 状态 ----
  bool ready = false;
  BottomButtonState mainButton = const BottomButtonState();
  BottomButtonState secondaryButton = const BottomButtonState();
  bool backButtonVisible = false;
  bool settingsButtonVisible = false;
  bool closingConfirmation = false;
  String? headerColor;
  String? backgroundColor;

  /// 页面 setBottomBarColor 设的底栏底色;null = 用主题的 bottom_bar_bg_color
  String? bottomBarColor;
  bool fullscreen = false;
  bool orientationLocked = false;

  // 由容器根据布局实时更新
  Map<String, String> themeParams = const {};
  String colorScheme = 'light';
  double viewportHeight = 0;
  bool expanded = false;
  Map<String, double> safeArea = const {'top': 0, 'bottom': 0, 'left': 0, 'right': 0};
  Map<String, double> contentSafeArea = const {'top': 0, 'bottom': 0, 'left': 0, 'right': 0};

  bool get isGame => launch.card.isGame;

  /// 真正加载的地址:启动片段里的协议版本换成宿主自己的(见 [withHostVersion])
  String get entryUrl => withHostVersion(launch.url);

  Map<String, dynamic> _init() => {
        'version': kBridgeProtocolVersion,
        'platform': platform,
        'colorScheme': colorScheme,
        'themeParams': themeParams,
        'viewport': {'height': viewportHeight, 'stableHeight': viewportHeight, 'isExpanded': expanded},
        'safeArea': safeArea,
        'contentSafeArea': contentSafeArea,
        'capabilities': launch.capabilities,
        'isFullscreen': fullscreen,
        'app': {'appid': launch.card.appid, 'name': launch.card.name},
      };

  void emit(String name, [Object? data]) => send?.call(BridgeDispatcher.event(name, data));

  void _changed() => notifyListeners();

  /// 页面发来的一条消息。返回的应答由传输层送回页面
  Future<Map<String, dynamic>?> receive(Object? raw) => dispatcher.handle(raw);

  /// 主框架导航到了新页面:换令牌,旧页面(和它可能藏着的 iframe)手里的令牌作废
  void onPageStarted() {
    dispatcher.rotate();
    ready = false;
    mainButton = const BottomButtonState();
    secondaryButton = const BottomButtonState();
    backButtonVisible = false;
    settingsButtonVisible = false;
    closingConfirmation = false;
    _changed();
  }

  // ---- 宿主 → 页面的事件 ----

  void updateTheme(Map<String, String> params, String scheme) {
    if (mapEquals(params, themeParams) && scheme == colorScheme) return;
    themeParams = params;
    colorScheme = scheme;
    emit('themeChanged', {'themeParams': params, 'colorScheme': scheme});
  }

  void updateViewport(double height, {required bool stable, bool? isExpanded}) {
    if (height == viewportHeight && (isExpanded == null || isExpanded == expanded)) return;
    viewportHeight = height;
    if (isExpanded != null) expanded = isExpanded;
    emit('viewportChanged', {'height': height, 'isStateStable': stable, 'isExpanded': expanded});
  }

  void updateSafeArea(Map<String, double> area, Map<String, double> content) {
    if (!mapEquals(area, safeArea)) {
      safeArea = area;
      emit('safeAreaChanged', area);
    }
    if (!mapEquals(content, contentSafeArea)) {
      contentSafeArea = content;
      emit('contentSafeAreaChanged', content);
    }
  }

  /// 宿主这边退出了全屏(网页版用户按 Esc 退出了浏览器全屏):和页面调 exitFullscreen 走同一条路
  Future<void> hostExitFullscreen() async {
    if (!fullscreen) return;
    if (await ui.setFullscreen(false)) {
      fullscreen = false;
      emit('fullscreenChanged', {'isFullscreen': false});
      _changed();
    }
  }

  void clickMain() => emit('mainButtonClicked');
  void clickSecondary() => emit('secondaryButtonClicked');
  void clickBack() => emit('backButtonClicked');
  void clickSettings() => emit('settingsButtonClicked');

  // ---- 方法表 ----

  Map<String, BridgeMethod> _methods() {
    BridgeMethod m(String name, BridgeHandler h) => BridgeMethod(h, capability: kMethodCapability[name]);
    return {
      'ready': m('ready', (_) async {
        ready = true;
        _changed();
        return true;
      }),
      'expand': m('expand', (_) async {
        ui.expand();
        return true;
      }),
      'close': m('close', (_) async {
        ui.close();
        return true;
      }),
      'setHeaderColor': m('setHeaderColor', (p) async {
        if (!isHexColor(p['color'])) throw const BridgeError(BridgeCode.invalidParams, '颜色要写 #RRGGBB');
        headerColor = p['color'] as String;
        _changed();
        return true;
      }),
      'setBackgroundColor': m('setBackgroundColor', (p) async {
        if (!isHexColor(p['color'])) throw const BridgeError(BridgeCode.invalidParams, '颜色要写 #RRGGBB');
        backgroundColor = p['color'] as String;
        _changed();
        return true;
      }),
      // 协议 2.1:底栏(主按钮 / 次按钮那一条)的底色,和 Telegram 的 setBottomBarColor 一样
      'setBottomBarColor': m('setBottomBarColor', (p) async {
        if (!isHexColor(p['color'])) throw const BridgeError(BridgeCode.invalidParams, '颜色要写 #RRGGBB');
        bottomBarColor = p['color'] as String;
        _changed();
        return true;
      }),
      'setClosingConfirmation': m('setClosingConfirmation', (p) async {
        closingConfirmation = p['enabled'] == true;
        return true;
      }),
      'mainButton': m('mainButton', (p) async {
        mainButton = BottomButtonState.fromParams(p);
        _changed();
        return true;
      }),
      'secondaryButton': m('secondaryButton', (p) async {
        secondaryButton = BottomButtonState.fromParams(p);
        _changed();
        return true;
      }),
      'backButton': m('backButton', (p) async {
        backButtonVisible = p['is_visible'] == true;
        _changed();
        return true;
      }),
      'settingsButton': m('settingsButton', (p) async {
        settingsButtonVisible = p['is_visible'] == true;
        _changed();
        return true;
      }),
      'haptic': m('haptic', (p) async {
        ui.haptic('${p['type']}', p['style'] as String?);
        return true;
      }),
      'showPopup': m('showPopup', (p) async {
        final message = '${p['message'] ?? ''}'.trim();
        final buttons = (p['buttons'] as List? ?? const [])
            .whereType<Map>()
            .map((b) => Map<String, dynamic>.from(b))
            .toList();
        if (message.isEmpty || message.length > 256 || buttons.length > 3) {
          throw const BridgeError(BridgeCode.invalidParams, 'message 必填(≤ 256 字),按钮最多 3 个');
        }
        final id = await ui.showPopup(p['title'] as String?, message,
            buttons.isEmpty ? [{'type': 'close'}] : buttons);
        return {'button_id': id};
      }),
      'openLink': m('openLink', (p) async {
        final url = Uri.tryParse('${p['url'] ?? ''}');
        if (url == null || !(url.isScheme('https') || url.isScheme('http'))) {
          throw const BridgeError(BridgeCode.invalidParams, '只能打开 http(s) 链接');
        }
        final ok = await ui.openExternal(url);
        if (!ok) throw const BridgeError(BridgeCode.userDenied, '用户取消了');
        return true;
      }),
      'share': m('share', (p) async {
        final text = '${p['text'] ?? ''}'.trim();
        final url = '${p['url'] ?? ''}'.trim();
        if (text.isEmpty && url.isEmpty) throw const BridgeError(BridgeCode.invalidParams, 'text 必填');
        final link = url.isNotEmpty ? url : launchLink;
        return {'shared': await ui.share([text, link].where((s) => s.isNotEmpty).join('\n'))};
      }),
      'CloudStorage.getItems': m('CloudStorage.getItems', (p) => _storage('get', {'keys': p['keys']})),
      'CloudStorage.setItem': m('CloudStorage.setItem', (p) => _storage('set', {
            'key': p['key'],
            'value': p['value'],
            if (p.containsKey('if_rev')) 'if_rev': p['if_rev'],
          })),
      'CloudStorage.removeItems': m('CloudStorage.removeItems', (p) => _storage('remove', {'keys': p['keys']})),
      'CloudStorage.getKeys': m('CloudStorage.getKeys', (p) => _storage('keys', {
            'prefix': p['prefix'] ?? '',
            'cursor': p['cursor'] ?? '',
            'limit': p['limit'] ?? 500,
          })),
      // 全屏(协议 2.1 起所有应用都能用)。事件和 Telegram 一样:成了发 fullscreenChanged,
      // 没成发 fullscreenFailed 带 error —— 已经是全屏 ALREADY_FULLSCREEN,宿主做不到 UNSUPPORTED
      'requestFullscreen': m('requestFullscreen', (_) async {
        if (fullscreen) {
          // 网页版的小游戏打开时只是在窗口里铺满:页面再要一次,顺手试浏览器全屏(状态不变)
          await ui.setFullscreen(true);
          emit('fullscreenFailed', {'error': 'ALREADY_FULLSCREEN', 'isFullscreen': true});
          return true;
        }
        final ok = await ui.setFullscreen(true);
        if (ok) {
          fullscreen = true;
          emit('fullscreenChanged', {'isFullscreen': true});
        } else {
          emit('fullscreenFailed', {'error': 'UNSUPPORTED', 'isFullscreen': false});
        }
        _changed();
        return ok;
      }),
      'exitFullscreen': m('exitFullscreen', (_) async {
        if (!fullscreen) return true;
        final ok = await ui.setFullscreen(false);
        if (ok) {
          fullscreen = false;
          emit('fullscreenChanged', {'isFullscreen': false});
          _changed();
        }
        return ok;
      }),
      'lockOrientation': m('lockOrientation', (_) async {
        orientationLocked = await ui.lockOrientation(true);
        return orientationLocked;
      }),
      'unlockOrientation': m('unlockOrientation', (_) async {
        await ui.lockOrientation(false);
        orientationLocked = false;
        return true;
      }),
      'requestProfile': m('requestProfile', (_) async {
        // 首次弹确认;同意过的(设置里没撤回)不再问。**授权记在服务端**,换设备也算数
        if (!await ui.askProfileConsent()) {
          throw const BridgeError(BridgeCode.userDenied, '用户没有同意');
        }
        return {'init_data': await api.miniAppProfile(launch.card.appid)};
      }),
      'legacy.getInitData': m('legacy.getInitData', (_) async {
        if (launch.bridge != 1) {
          throw const BridgeError(BridgeCode.notSupported, '托管应用请用启动片段里的 initData(v2)');
        }
        return api.miniAppInitData(launch.card.id);
      }),
    };
  }

  String get launchLink => '${api.baseUrl}/m/${launch.card.appid}';

  Future<Object?> _storage(String op, Map<String, dynamic> body) async {
    return api.miniAppStorage(launch.card.appid, op, body);
  }

  // ---- v1 兼容(外部地址的老条目,页面用的是 window.superz) ----

  Future<({bool ok, Object data})?> legacyCall(String method) async {
    switch (method) {
      case 'ready':
        ready = true;
        _changed();
        return (ok: true, data: true);
      case 'close':
        ui.close();
        return null;
      case 'expand':
        ui.expand();
        return (ok: true, data: true);
      case 'themeParams':
        return (ok: true, data: {'brightness': colorScheme, ...themeParams});
      case 'getInitData':
        if (!launch.capabilities.contains('initData')) {
          return (ok: false, data: '该小程序未申请 initData 权限');
        }
        try {
          return (ok: true, data: await api.miniAppInitData(launch.card.id));
        } catch (e) {
          return (ok: false, data: '$e');
        }
      default:
        return (ok: false, data: '未知方法:$method');
    }
  }

  // ---- 状态轮询:被暂停或隔离了就关 ----

  Timer? _poll;

  void startPolling({Duration every = const Duration(seconds: 60)}) {
    _poll?.cancel();
    _poll = Timer.periodic(every, (_) => checkStatus());
  }

  Future<void> checkStatus() async {
    try {
      if (await api.miniAppBlocked(launch.card.appid)) onSuspended?.call();
    } catch (_) {
      // 查不到状态(离线)不关应用 —— 离线也要能用
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }
}
