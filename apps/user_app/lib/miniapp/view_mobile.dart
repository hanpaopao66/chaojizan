/// 小程序的**手机端传输层**:原生 WebView + 注入的 `SuperzBridge` 通道(#324)。
///
/// - 页面 → 宿主:SDK 调 `SuperzBridge.postMessage(json)`;
/// - 宿主 → 页面:`runJavaScript('window.__szReceive(...)')` —— **只在主框架执行**,
///   页面里嵌的 iframe 拿不到会话令牌;
/// - 主框架每次开始加载新页面都换令牌(controller.onPageStarted);
/// - 导航白名单:只许本应用的托管 origin;外链一律先问「即将离开超级赞」再交系统浏览器,
///   容器里绝不加载别家页面(302 逃逸也挡在这里)。
///
/// 外部地址的老条目(bridge = 1)照旧注入 v1 的 `window.superz`,老页面不用改。
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:webview_flutter_wkwebview/webview_flutter_wkwebview.dart';

import 'bridge.dart';
import 'controller.dart';
import 'theme.dart';

class MiniAppView extends StatefulWidget {
  const MiniAppView({
    super.key,
    required this.controller,
    required this.onError,
    this.debug = false,
  });

  final MiniAppController controller;
  final void Function(String message) onError;

  /// 「我的 → 设置 → 开发者选项 → 小程序调试」:安卓开远程调试(chrome://inspect)、iOS 设 inspectable
  final bool debug;

  @override
  State<MiniAppView> createState() => MiniAppViewState();
}

class MiniAppViewState extends State<MiniAppView> {
  late final WebViewController _web;
  MiniAppController get _c => widget.controller;

  bool _allowed(String url) => originAllowed(url, _c.launch.allowedOrigins);

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel('SuperzBridge', onMessageReceived: _onMessage)
      ..setNavigationDelegate(NavigationDelegate(
        onPageStarted: (url) {
          if (_allowed(url)) _c.onPageStarted();
        },
        onPageFinished: (_) {
          if (_c.launch.bridge == 1) _injectV1();
        },
        onWebResourceError: (e) {
          // 只认主文档失败;页面里一张图挂了不该整页报错
          if (e.isForMainFrame ?? true) widget.onError(e.description);
        },
        onNavigationRequest: (req) {
          if (!req.isMainFrame) return NavigationDecision.navigate;
          if (_allowed(req.url)) return NavigationDecision.navigate;
          final uri = Uri.tryParse(req.url);
          if (uri != null && (uri.isScheme('https') || uri.isScheme('http'))) {
            _c.ui.openExternal(uri);
          }
          return NavigationDecision.prevent;
        },
      ));
    final bg = colorOf(_c.launch.backgroundColor);
    if (bg != null) _web.setBackgroundColor(bg);
    _debugging();
    _c.send = (msg) {
      if (!mounted) return;
      // 双层 jsonEncode:外层把整条消息变成一个 JS 字符串字面量,页面那侧再 JSON.parse
      _web.runJavaScript(
          'window.__szReceive && window.__szReceive(${jsonEncode(jsonEncode(msg))})');
    };
    _web.loadRequest(Uri.parse(_c.launch.url));
  }

  void _debugging() {
    if (!widget.debug) return;
    final p = _web.platform;
    if (p is AndroidWebViewController) {
      AndroidWebViewController.enableDebugging(true);
    } else if (p is WebKitWebViewController) {
      p.setInspectable(true);
    }
  }

  /// 「重新进入」:按新的启动地址重新加载
  void reload() => _web.loadRequest(Uri.parse(_c.launch.url));

  /// 「清除数据」:页面自己的 localStorage / IndexedDB 在它自己的 origin 里清
  Future<void> clearLocalData() async {
    try {
      await _web.runJavaScript('''
try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}
try { indexedDB.databases && indexedDB.databases().then(function (dbs) {
  dbs.forEach(function (d) { d.name && indexedDB.deleteDatabase(d.name) }) }) } catch (e) {}
''');
    } catch (_) {}
  }

  Future<void> _onMessage(JavaScriptMessage m) async {
    Object? raw;
    try {
      raw = jsonDecode(m.message);
    } catch (_) {
      return;
    }
    // 应答前再验一次主框架还在白名单里 —— 消息可能是导航离开前发的
    final url = await _web.currentUrl();
    if (url == null || !_allowed(url) || !mounted) return;
    if (raw is Map && raw['v'] == 2) {
      final reply = await _c.receive(raw);
      if (reply != null) _c.send?.call(reply);
      return;
    }
    if (_c.launch.bridge == 1 && raw is Map) {
      final id = raw['id'];
      final r = await _c.legacyCall('${raw['method'] ?? ''}');
      if (r != null && id is int && mounted) {
        _web.runJavaScript(
            'window.superz && window.superz._resolve($id, ${r.ok}, ${jsonEncode(r.data)})');
      }
    }
  }

  /// v1 桥(外部地址的老条目)。和 /mini-app-bridge.js 是同一套 API
  Future<void> _injectV1() async {
    final url = await _web.currentUrl();
    if (url == null || !_allowed(url)) return;
    await _web.runJavaScript('''
(function () {
  if (window.superz) return;
  var cbs = {}, seq = 0;
  window.superz = {
    version: 1, inHost: true,
    _resolve: function (id, ok, data) { var c = cbs[id]; if (!c) return; delete cbs[id]; (ok ? c[0] : c[1])(data); },
    _call: function (m, p) { return new Promise(function (res, rej) {
      var id = ++seq; cbs[id] = [res, rej];
      SuperzBridge.postMessage(JSON.stringify({id: id, method: m, params: p || {}})); }); },
    ready: function () { return this._call('ready'); },
    close: function () { return this._call('close'); },
    expand: function () { return this._call('expand'); },
    themeParams: function () { return this._call('themeParams'); },
    getInitData: function () { return this._call('getInitData'); }
  };
  document.dispatchEvent(new Event('superzready'));
})();
''');
  }

  @override
  void dispose() {
    _c.send = null;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => WebViewWidget(controller: _web);
}
