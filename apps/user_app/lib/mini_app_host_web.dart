/// 小程序容器的 **web 实现**(#292):跨域 iframe + postMessage。
///
/// ## 为什么 web 上不能照搬手机端
///
/// 手机端是原生 WebView,宿主可以往页面里注入 JS,页面什么都不用做。
/// **web 上做不到** —— 小程序跑在跨域 iframe 里,而浏览器的同源策略
/// 明确禁止父页面往跨域 iframe 注入脚本。这不是权限没开,是安全模型本身。
///
/// Telegram Web 也是这么解决的:它要求小程序页面引 `telegram-web-app.js`,
/// 那个脚本用 postMessage 和宿主通信。我们照搬 —— 页面引
/// `/mini-app-bridge.js` 就有 `window.superz`,API 和手机端一字不差。
///
/// ## 安全边界(和手机端不同,但更硬)
///
/// 手机端靠**宿主自己比对 URL**判断页面在不在白名单;
/// web 上浏览器强制在每条消息上带 `origin`,伪造不了:
///
/// - 收消息:验 `event.source` 是不是那个 iframe 的 window,
///   再验 `event.origin` 在 `allowedOrigins` 里。两条都过才应答;
/// - 发消息:`targetOrigin` **写具体 origin,绝不用 `*`** ——
///   小程序页面可能 redirect 到别处,用 `*` 等于把应答(含 initData
///   身份包)广播给它跳到的任何地方;
/// - token 仍然不进页面:身份只有 getInitData 一条路。
///
/// ## 已知边界
///
/// iframe 跨域时宿主**读不到它的当前地址**,所以没法像手机端那样
/// "每次导航都重查白名单"。但这不要紧:导航之后 origin 变了,
/// 它发来的消息会在 `event.origin` 那一关被挡掉 —— 结果是一样的,
/// 而且不依赖宿主主动去查。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';
// getProperty / callMethod 在这个库里,不在 dart:js_interop
import 'dart:js_interop_unsafe';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:web/web.dart' as web;

import 'mini_app_bridge.dart';

/// 每个容器一个唯一的 view type,不能复用 —— 同时开两个小程序时会串。
int _seq = 0;

class MiniAppHost extends StatefulWidget {
  const MiniAppHost({
    super.key,
    required this.api,
    required this.app,
    required this.onClose,
    required this.onExpand,
  });

  final ApiClient api;
  final MiniAppInfo app;
  final VoidCallback onClose;
  final VoidCallback onExpand;

  @override
  State<MiniAppHost> createState() => _MiniAppHostState();
}

class _MiniAppHostState extends State<MiniAppHost> {
  late final String _viewType = 'superz-miniapp-${_seq++}';
  late final web.HTMLIFrameElement _frame;
  web.EventListener? _listener;

  /// 白名单 origin(规范化成 Uri.origin 的形态,端口归一)
  late final Set<String> _origins = widget.app.allowedOrigins
      .map((o) => Uri.tryParse(o)?.origin)
      .whereType<String>()
      .toSet();

  /// 入口地址的 origin。应答就发给它 —— **不能用 `*`**
  late final String? _entryOrigin = Uri.tryParse(widget.app.entryUrl)?.origin;

  @override
  void initState() {
    super.initState();
    _frame = web.HTMLIFrameElement()
      ..src = widget.app.entryUrl
      ..style.border = 'none'
      ..style.width = '100%'
      ..style.height = '100%'
      // sandbox:给到刚好够用,不多给。
      // - allow-scripts:小程序要跑 JS,不给就没得玩;
      // - allow-forms / allow-popups:表单和外链;
      // - **不给 allow-same-origin**:给了它就能拿到我们这个 origin 的
      //   localStorage 和 cookie —— 登录 token 就在那儿
      ..setAttribute('sandbox',
          'allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox')
      // 不给摄像头麦克风地理位置:小程序要用得走桥申请,不能自己伸手
      ..setAttribute('allow', '')
      ..setAttribute('referrerpolicy', 'no-referrer');

    ui_web.platformViewRegistry
        .registerViewFactory(_viewType, (int _) => _frame);

    _listener = _onMessage.toJS;
    web.window.addEventListener('message', _listener);
  }

  @override
  void dispose() {
    if (_listener != null) {
      web.window.removeEventListener('message', _listener);
    }
    super.dispose();
  }

  void _onMessage(web.Event event) {
    final e = event as web.MessageEvent;

    // ① 必须是**这个 iframe** 发来的。页面里别的 iframe、
    //    第三方脚本都伪造不了 source
    if (e.source != _frame.contentWindow) return;

    // ② origin 必须在白名单里。小程序 redirect 到别处之后,
    //    它发来的消息就会挂在这一关 —— 不用宿主主动去查地址
    if (!_origins.contains(e.origin)) {
      debugPrint('小程序桥:拒绝白名单外的 origin ${e.origin}');
      return;
    }

    final data = e.data;
    if (data == null) return;
    // 桥发的是 {__superz: 1, payload: {...}}
    final obj = data as JSObject;
    if (obj.getProperty('__superz'.toJS) == null) return;
    final payload = obj.getProperty('payload'.toJS) as JSObject?;
    if (payload == null) return;

    final id = (payload.getProperty('id'.toJS) as JSNumber?)?.toDartInt;
    final method =
        (payload.getProperty('method'.toJS) as JSString?)?.toDart ?? '';
    unawaited(_dispatch(id, method, e.origin));
  }

  Future<void> _dispatch(int? id, String method, String origin) async {
    if (!mounted) return;
    BridgeReply? reply;
    try {
      reply = await handleBridgeCall(
        context,
        api: widget.api,
        app: widget.app,
        method: method,
        onClose: widget.onClose,
        onExpand: widget.onExpand,
      );
    } catch (e) {
      reply = (ok: false, data: '$e');
    }
    if (reply == null || id == null) return;
    _reply(id, reply.ok, reply.data, origin);
  }

  void _reply(int id, bool ok, Object data, String origin) {
    final msg = jsonEncode({
      '__superz': 1,
      'reply': {'id': id, 'ok': ok, 'data': data},
    });
    // ⚠️ targetOrigin 用**收到消息的那个 origin**,不是 `*`。
    // 应答里可能带 initData 身份包,用 `*` 等于广播给页面跳到的任何地方
    _frame.contentWindow?.postMessage(
      _jsonParse(msg),
      (origin.isNotEmpty ? origin : (_entryOrigin ?? '')).toJS,
    );
  }

  @override
  Widget build(BuildContext context) => HtmlElementView(viewType: _viewType);
}

/// JSON 字符串 → JS 对象。
///
/// **不能直接把 Dart Map 传过去** —— 那样到页面那侧是 Dart 的内部表示,
/// 读不出字段。绕一趟 JSON.parse 得到的才是普通 JS 对象。
JSAny _jsonParse(String s) => _json.callMethod('parse'.toJS, s.toJS) as JSAny;

JSObject get _json => web.window.getProperty('JSON'.toJS) as JSObject;
