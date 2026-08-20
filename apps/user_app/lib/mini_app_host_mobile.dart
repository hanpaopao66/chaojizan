/// 小程序容器的**手机端实现**:原生 WebView + 注入的 JS 桥。
///
/// web 端的实现在 `mini_app_host_web.dart`(跨域 iframe + postMessage),
/// 两边的差别和为什么必须有两套,写在那个文件开头。
///
/// 业务层(五个方法怎么应答)在 `mini_app_bridge.dart`,两端共用 ——
/// 小程序开发者不该为了不同宿主写两套。
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'mini_app_bridge.dart';

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
  late final WebViewController _web;
  int _progress = 0;
  String? _error;

  /// 白名单 origin 集合(规范化成 Uri.origin 的形态,端口归一)
  late final Set<String> _origins = widget.app.allowedOrigins
      .map((o) => Uri.tryParse(o)?.origin)
      .whereType<String>()
      .toSet();

  bool _allowed(String url) {
    final uri = Uri.tryParse(url);
    if (uri == null || !(uri.isScheme('https') || uri.isScheme('http'))) {
      return false;
    }
    return _origins.contains(uri.origin);
  }

  @override
  void initState() {
    super.initState();
    _web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..addJavaScriptChannel('SuperzBridge', onMessageReceived: _onBridge)
      ..setNavigationDelegate(NavigationDelegate(
        onProgress: (p) => setState(() => _progress = p),
        onPageFinished: (_) => _injectBridge(),
        onWebResourceError: (e) {
          // 只认主文档失败;页面里挂一张图不该整页报错
          if (e.isForMainFrame ?? true) {
            setState(() => _error = e.description);
          }
        },
        onNavigationRequest: (req) {
          if (_allowed(req.url)) return NavigationDecision.navigate;
          // 白名单外(含 redirect 逃逸):容器内不加载,交给系统浏览器,
          // 让用户在地址栏里看清自己到了谁家
          launchUrl(Uri.parse(req.url), mode: LaunchMode.externalApplication);
          return NavigationDecision.prevent;
        },
      ))
      ..loadRequest(Uri.parse(widget.app.entryUrl));
  }

  /// 页面加载完成后注入 `window.superz`。**每次导航后都重走一遍**:
  /// 白名单外的页面(理论上进不来,防御纵深)什么都拿不到。
  ///
  /// 注入的这份和 `/mini-app-bridge.js` 是同一套 API —— 页面引了那个脚本
  /// 也能在手机上跑(脚本会检测到 SuperzBridge 通道并走它)。
  Future<void> _injectBridge() async {
    final url = await _web.currentUrl();
    if (url == null || !_allowed(url)) return;
    await _web.runJavaScript('''
(function () {
  if (window.superz) return;
  var cbs = {}, seq = 0;
  window.superz = {
    version: 1,
    inHost: true,
    _resolve: function (id, ok, data) {
      var c = cbs[id]; if (!c) return; delete cbs[id];
      (ok ? c[0] : c[1])(data);
    },
    _call: function (m, p) {
      return new Promise(function (res, rej) {
        var id = ++seq; cbs[id] = [res, rej];
        SuperzBridge.postMessage(JSON.stringify({id: id, method: m, params: p || {}}));
      });
    },
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

  Future<void> _onBridge(JavaScriptMessage msg) async {
    int? id;
    try {
      final req = jsonDecode(msg.message) as Map<String, dynamic>;
      id = req['id'] as int?;
      final method = req['method'] as String? ?? '';
      // 应答前再验一次当前页面还在白名单内 —— 消息可能是导航离开前发的
      final url = await _web.currentUrl();
      if (url == null || !_allowed(url)) return;
      if (!mounted) return;
      final reply = await handleBridgeCall(
        context,
        api: widget.api,
        app: widget.app,
        method: method,
        onClose: widget.onClose,
        onExpand: widget.onExpand,
      );
      if (reply != null) _reply(id, reply.ok, reply.data);
    } catch (e) {
      _reply(id, false, '$e');
    }
  }

  void _reply(int? id, bool ok, Object data) {
    if (id == null) return;
    _web.runJavaScript(
        'window.superz && window.superz._resolve($id, $ok, ${jsonEncode(data)})');
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return _MiniAppError(message: _error!);
    }
    return Stack(children: [
      WebViewWidget(controller: _web),
      if (_progress < 100)
        const Align(
          alignment: Alignment.topCenter,
          child: LinearProgressIndicator(minHeight: 2),
        ),
    ]);
  }
}

class _MiniAppError extends StatelessWidget {
  const _MiniAppError({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(kPagePad),
        child: Text('小程序没打开:$message',
            textAlign: TextAlign.center,
            style: TextStyle(color: sz.inkMuted)),
      ),
    );
  }
}
