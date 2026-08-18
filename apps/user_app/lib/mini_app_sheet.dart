/// 小程序容器(#279,Telegram 模式):底部弹层 WebView + `window.superz` 桥。
///
/// 信任边界(DEV-PROMPTS-31 定死,改之前先读那篇):
/// - 登录 token 永远不进 WebView。页面拿身份只有一条路:桥的
///   `getInitData()`,返回服务端签的 HMAC 身份包(分钟级时效);
/// - 桥只对清单里 allowed_origins 的页面注入/应答,**每次导航都重查**,
///   redirect 逃逸到白名单外就甩给系统浏览器,容器内不加载;
/// - 支付不进小程序。桥没有任何收集卡号/密码的能力。
///
/// 已知边界:Android 清单 usesCleartextTraffic=false,http 的 entry_url
/// 在安卓上加载不出来 —— 生产清单全是 https,本地联调请配 https 入口。
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';

/// 半屏弹起、可拖到近全屏 —— 骨架抄 five_percent.dart 的现成模板,
/// 区别是 WebView 不是 Flutter 滚动体,拖拽只挂在顶栏上。
Future<void> showMiniAppSheet(BuildContext context,
    {required ApiClient api, required MiniAppInfo app}) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    builder: (_) => MiniAppSheet(api: api, app: app),
  );
}

class MiniAppSheet extends StatefulWidget {
  const MiniAppSheet({super.key, required this.api, required this.app});

  final ApiClient api;
  final MiniAppInfo app;

  @override
  State<MiniAppSheet> createState() => _MiniAppSheetState();
}

class _MiniAppSheetState extends State<MiniAppSheet> {
  late final WebViewController _web;
  final _sheet = DraggableScrollableController();
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

  @override
  void dispose() {
    _sheet.dispose();
    super.dispose();
  }

  /// 页面加载完成后注入 `window.superz`。**每次导航后都重走一遍**:
  /// 白名单外的页面(理论上进不来,防御纵深)什么都拿不到
  Future<void> _injectBridge() async {
    final url = await _web.currentUrl();
    if (url == null || !_allowed(url)) return;
    await _web.runJavaScript('''
(function () {
  if (window.superz) return;
  var cbs = {}, seq = 0;
  window.superz = {
    version: 1,
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
      switch (method) {
        case 'ready':
          _reply(id, true, true);
        case 'close':
          if (mounted) Navigator.of(context).pop();
        case 'expand':
          if (_sheet.isAttached) {
            _sheet.animateTo(0.96,
                duration: const Duration(milliseconds: 200),
                curve: Curves.easeOut);
          }
          _reply(id, true, true);
        case 'themeParams':
          if (!mounted) return;
          final sz = Theme.of(context).sz;
          String hex(Color c) =>
              '#${c.toARGB32().toRadixString(16).padLeft(8, '0').substring(2)}';
          _reply(id, true, {
            'brightness':
                Theme.of(context).brightness == Brightness.dark ? 'dark' : 'light',
            'paper': hex(sz.paper),
            'surface': hex(sz.surface),
            'ink': hex(sz.ink),
            'inkMuted': hex(sz.inkMuted),
            'line': hex(sz.line),
            'clay': hex(sz.clay),
            'link': hex(sz.link),
          });
        case 'getInitData':
          if (!widget.app.perms.contains('initData')) {
            _reply(id, false, '该小程序未申请 initData 权限');
            return;
          }
          final pack = await widget.api.miniAppInitData(widget.app.id);
          _reply(id, true, pack);
        default:
          _reply(id, false, '未知方法:$method');
      }
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
    final sz = Theme.of(context).sz;
    return DraggableScrollableSheet(
      controller: _sheet,
      expand: false,
      initialChildSize: 0.72,
      minChildSize: 0.45,
      maxChildSize: 0.96,
      builder: (context, scrollController) => Column(children: [
        // 顶栏是唯一的拖拽区:WebView 自己要滚页面,手势不能给它
        SingleChildScrollView(
          controller: scrollController,
          physics: const ClampingScrollPhysics(),
          child: Column(children: [
            const SizedBox(height: 8),
            Container(
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                  color: sz.line, borderRadius: BorderRadius.circular(2)),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 8, 6, 8),
              child: Row(children: [
                Text(widget.app.icon.startsWith('http') ? '🧩' : widget.app.icon,
                    style: const TextStyle(fontSize: 18)),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(widget.app.name,
                      style: const TextStyle(
                          fontSize: 15, fontWeight: FontWeight.w600)),
                ),
                IconButton(
                  onPressed: () => Navigator.of(context).pop(),
                  icon: const Icon(Icons.close),
                  tooltip: '关闭',
                ),
              ]),
            ),
          ]),
        ),
        if (_progress < 100 && _error == null)
          LinearProgressIndicator(value: _progress / 100, minHeight: 2),
        Expanded(
          child: _error != null
              ? SzError(
                  error: _error,
                  onRetry: () {
                    setState(() {
                      _error = null;
                      _progress = 0;
                    });
                    _web.reload();
                  })
              : WebViewWidget(controller: _web),
        ),
      ]),
    );
  }
}
