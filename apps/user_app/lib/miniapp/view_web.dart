/// 小程序的 **web 传输层**:跨域 iframe + postMessage(#324)。
///
/// 浏览器不许父页面往跨域 iframe 注入脚本(同源策略本身),所以页面自己引 SDK,
/// 和 Telegram 要求引 telegram-web-app.js 同理。安全边界:
///
/// - 收:`event.source` 必须是**这个 iframe 的 window**(页面里再嵌的 iframe、第三方脚本都伪造不了),
///   `event.origin` 必须是这个应用的托管 origin;
/// - 发:`targetOrigin` 写**具体的托管 origin**,绝不用 `*` —— 应答里有身份包;
/// - 托管应用的 iframe 给 `allow-same-origin`:它在**自己的**子域名上,拿到的是自己的存储,
///   碰不到宿主的 localStorage(登录 token 在那儿)。宿主和托管地址同源时拒绝加载 ——
///   那种部署下 allow-same-origin 等于把宿主的存储交出去;
/// - 页面每次重新握手(hello)都换令牌:这里 source 已经验过是主框架,不怕别的 frame 冒充着换;
/// - 导航逃逸:页面自己跳去别的站,父页面拦不住也读不到地址。iframe 每次 load 之后发 ping
///   (targetOrigin 是托管 origin,只有托管页收得到),8 秒内没有 pong 就清空 iframe、报错
///   —— 见 bridge.dart 的 [EscapeWatch]。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';
import 'package:web/web.dart' as web;

import 'bridge.dart';
import 'controller.dart';

int _seq = 0;

class MiniAppView extends StatefulWidget {
  const MiniAppView({
    super.key,
    required this.controller,
    required this.onError,
    this.debug = false,
  });

  final MiniAppController controller;
  final void Function(String message) onError;
  final bool debug;

  @override
  State<MiniAppView> createState() => MiniAppViewState();
}

class MiniAppViewState extends State<MiniAppView> {
  late final String _viewType = 'superz-miniapp-v2-${_seq++}';
  late final web.HTMLIFrameElement _frame;
  web.EventListener? _listener;
  web.EventListener? _loadListener;
  final _escape = EscapeWatch();
  Timer? _pingTimer;
  bool _left = false;
  MiniAppController get _c => widget.controller;

  late final Set<String> _origins = _c.launch.allowedOrigins
      .map((o) => Uri.tryParse(o)?.origin)
      .whereType<String>()
      .toSet();
  late final String _target =
      Uri.tryParse(_c.launch.url)?.origin ?? (_origins.isEmpty ? '' : _origins.first);

  @override
  void initState() {
    super.initState();
    final hosted = _c.launch.bridge == 2;
    final sameOrigin = _target == web.window.location.origin;
    _frame = web.HTMLIFrameElement()
      ..style.border = 'none'
      ..style.width = '100%'
      ..style.height = '100%'
      ..style.background = _c.launch.backgroundColor
      ..setAttribute(
          'sandbox',
          hosted
              ? 'allow-scripts allow-same-origin allow-forms'
              : 'allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox')
      // 摄像头、麦克风、定位一概不给:要用得走桥,有确认、有记录
      ..setAttribute('allow', 'clipboard-write')
      ..setAttribute('referrerpolicy', 'no-referrer');
    if (hosted && sameOrigin) {
      scheduleMicrotask(() => widget.onError('托管地址和宿主同源,为了你的账号安全不加载'));
    } else {
      if (hosted) {
        _loadListener = ((web.Event _) => _onFrameLoad()).toJS;
        _frame.addEventListener('load', _loadListener);
      }
      _frame.src = _c.entryUrl;
    }
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int _) => _frame);
    _listener = _onMessage.toJS;
    web.window.addEventListener('message', _listener);
    _c.send = (msg) {
      if (_target.isEmpty) return;
      _frame.contentWindow?.postMessage(_jsonParse(jsonEncode({...msg, '__sz': 2})), _target.toJS);
    };
  }

  void reload() => _frame.src = _c.entryUrl;

  /// iframe 又加载了一个文档:问它还是不是这个小程序(见 [EscapeWatch])。
  /// 每秒问一次 —— async 引 SDK 的页面,监听装上之前的那几问会丢
  void _onFrameLoad() {
    if (_left || !mounted) return;
    final nonce = _escape.onLoad();
    void ping() => _c.send?.call({'v': 2, 'type': 'ping', 'nonce': nonce});
    var asked = 1;
    ping();
    _pingTimer?.cancel();
    _pingTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted || _left || !_escape.waiting) return t.cancel();
      if (asked >= _escape.deadline.inSeconds) {
        t.cancel();
        _left = true;
        _frame.src = 'about:blank';
        widget.onError('页面跳到了这个小程序以外的地址,为了安全已经停止显示');
        return;
      }
      asked++;
      ping();
    });
  }

  Future<void> clearLocalData() async {
    // 跨域 iframe 的存储宿主碰不到;托管页的 SDK 会在收到这个事件后自己清(见 SDK 文档)
    _c.emit('clearLocalData');
  }

  @override
  void dispose() {
    if (_listener != null) web.window.removeEventListener('message', _listener);
    if (_loadListener != null) _frame.removeEventListener('load', _loadListener);
    _pingTimer?.cancel();
    _c.send = null;
    super.dispose();
  }

  void _onMessage(web.Event event) {
    final e = event as web.MessageEvent;
    // 用 JS 的 ===,不用 Dart 的 ==:dart2js 的 == 会去读对象上的派发属性,
    // 而 source 是**跨域**的 window,一读就抛 SecurityError(整条消息被吞掉,桥就不通了)
    if (!e.source.strictEquals(_frame.contentWindow).toDart) return;
    if (!_origins.contains(e.origin)) return;
    final data = e.data;
    if (data == null) return;
    final obj = data as JSObject;
    if (obj.getProperty<JSAny?>('__sz'.toJS) != null) {
      final raw = _stringify(obj);
      unawaited(_v2(raw));
    } else if (_c.launch.bridge == 1 && obj.getProperty<JSAny?>('__superz'.toJS) != null) {
      final payload = obj.getProperty<JSObject?>('payload'.toJS);
      if (payload == null) return;
      final id = (payload.getProperty<JSNumber?>('id'.toJS))?.toDartInt;
      final method = (payload.getProperty<JSString?>('method'.toJS))?.toDart ?? '';
      unawaited(_v1(id, method, e.origin));
    }
  }

  Future<void> _v2(String raw) async {
    Object? msg;
    try {
      msg = jsonDecode(raw);
    } catch (_) {
      return;
    }
    if (msg is Map && msg['type'] == 'pong') return _escape.onPong(msg['nonce']);
    if (msg is Map && msg['type'] == 'hello') _c.dispatcher.rotate();
    final reply = await _c.receive(msg);
    if (reply != null && mounted) _c.send?.call(reply);
  }

  Future<void> _v1(int? id, String method, String origin) async {
    final r = await _c.legacyCall(method);
    if (r == null || id == null || !mounted) return;
    _frame.contentWindow?.postMessage(
        _jsonParse(jsonEncode({
          '__superz': 1,
          'reply': {'id': id, 'ok': r.ok, 'data': r.data},
        })),
        origin.toJS);
  }

  @override
  Widget build(BuildContext context) => HtmlElementView(viewType: _viewType);
}

JSObject get _json => web.window.getProperty<JSObject>('JSON'.toJS);

JSAny _jsonParse(String s) => _json.callMethod<JSAny>('parse'.toJS, s.toJS);

String _stringify(JSObject o) => (_json.callMethod<JSString>('stringify'.toJS, o)).toDart;
