/// 小程序容器(#279 / #292,Telegram 模式)。
///
/// 信任边界(DEV-PROMPTS-31 定死,改之前先读那篇):
/// - 登录 token 永远不进小程序。页面拿身份只有一条路:桥的
///   `getInitData()`,返回服务端签的 HMAC 身份包(分钟级时效);
/// - 桥只对清单里 allowed_origins 的页面应答;
/// - 支付不进小程序。桥没有任何收集卡号/密码的能力。
///
/// ## 三个文件的分工
///
/// - `mini_app_bridge.dart` —— **业务层**:五个方法怎么应答。两端共用。
///   小程序开发者不该为了不同宿主写两套;
/// - `mini_app_host_mobile.dart` —— 手机端:原生 WebView + 注入 JS;
/// - `mini_app_host_web.dart` —— web 端:跨域 iframe + postMessage。
///   浏览器不许父页面往跨域 iframe 注入脚本,所以页面要自己引
///   `/mini-app-bridge.js`(和 Telegram 要求引 telegram-web-app.js 同理)。
///
/// 这个文件只剩弹层外壳,两端一样。
///
/// ## 已知边界
///
/// - 安卓清单 `usesCleartextTraffic=false`,http 的 entry_url 在安卓上
///   加载不出来 —— 生产清单全是 https,本地联调请配 https 入口;
/// - 桌面端(macOS / Windows / Linux)两套宿主都没有:WebView 插件不支持,
///   而桌面上没有 iframe。见 [miniAppSupported]。
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'mini_app_host_mobile.dart'
    if (dart.library.js_interop) 'mini_app_host_web.dart';

/// 这个平台有没有小程序容器。
///
/// 手机端是原生 WebView,web 端是跨域 iframe —— **桌面端两样都没有**:
/// `webview_flutter` 不支持桌面,而桌面不是浏览器环境也就没有 iframe。
///
/// 桌面上不显示小程序入口:显示了点不开比不显示更糟。
bool get miniAppSupported =>
    kIsWeb ||
    defaultTargetPlatform == TargetPlatform.android ||
    defaultTargetPlatform == TargetPlatform.iOS;

Future<void> showMiniAppSheet(BuildContext context,
    {required ApiClient api, required MiniAppInfo app}) {
  return szShowSheet<void>(
    context: context,
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
  final _sheet = DraggableScrollableController();

  @override
  void dispose() {
    _sheet.dispose();
    super.dispose();
  }

  void _expand() {
    if (_sheet.isAttached) {
      _sheet.animateTo(0.96,
          duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final bottom = isSheetBottom(context);

    Widget content(ScrollController? scrollController) => Column(children: [
          // 顶栏是唯一的拖拽区:容器自己要滚页面,手势不能给它
          SingleChildScrollView(
            controller: scrollController,
            physics: const ClampingScrollPhysics(),
            child: Column(children: [
              const SizedBox(height: 8),
              // 拖拽条只有底部弹层用得上 —— 对话框浮在屏幕中间,拖不动
              if (bottom)
                Container(
                  width: 36,
                  height: 4,
                  decoration: BoxDecoration(
                      color: sz.line, borderRadius: BorderRadius.circular(2)),
                ),
              Padding(
                padding: const EdgeInsets.fromLTRB(kPagePad, 8, 6, 8),
                child: Row(children: [
                  Text(
                      widget.app.icon.startsWith('http')
                          ? '🧩'
                          : widget.app.icon,
                      style: const TextStyle(fontSize: 18)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(widget.app.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
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
              Divider(height: 1, color: sz.line),
            ]),
          ),
          Expanded(
            child: MiniAppHost(
              api: widget.api,
              app: widget.app,
              onClose: () {
                if (mounted) Navigator.of(context).pop();
              },
              onExpand: _expand,
            ),
          ),
        ]);

    // 对话框那边必须给个**确定的高度**:上面 Column 里有 Expanded,
    // 而对话框给的是宽松约束(高度上限 0.85 屏,下限 0)——
    // Expanded 撞上无界高度会直接抛 RenderFlex 异常
    if (!bottom) {
      return SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.8,
        child: content(null),
      );
    }
    return DraggableScrollableSheet(
      controller: _sheet,
      expand: false,
      initialChildSize: 0.72,
      minChildSize: 0.45,
      maxChildSize: 0.96,
      builder: (context, scrollController) => content(scrollController),
    );
  }
}
