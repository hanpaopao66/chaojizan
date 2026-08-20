/// 小程序桥的**业务层**:五个方法怎么应答。两端共用。
///
/// ## 为什么要把这一层单独拆出来
///
/// 手机端和 web 端的**传输**完全不同:
///
/// - 手机端:原生 WebView,宿主注入 JS,消息走 `SuperzBridge` 通道;
/// - web 端:跨域 iframe,宿主**注入不了**(同源策略禁止),
///   页面自己引 `/mini-app-bridge.js`,消息走 `postMessage`。
///
/// 但 `ready` / `close` / `expand` / `themeParams` / `getInitData`
/// 这五个方法该返回什么,两端**必须一模一样** —— 不然小程序开发者
/// 要针对宿主写两套,那这个平台就没人接了。
///
/// 所以这里只放业务:传输由各自的宿主实现。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 一次桥调用的结果。
typedef BridgeReply = ({bool ok, Object data});

/// 处理一次桥调用。
///
/// [onClose] / [onExpand] 是宿主动作(关弹层、拉高弹层),各端自己实现;
/// 返回 null 表示**不需要应答**(close 之后弹层没了,应答给谁都没意义)。
Future<BridgeReply?> handleBridgeCall(
  BuildContext context, {
  required ApiClient api,
  required MiniAppInfo app,
  required String method,
  required VoidCallback onClose,
  required VoidCallback onExpand,
}) async {
  switch (method) {
    case 'ready':
      return (ok: true, data: true);

    case 'close':
      onClose();
      // 弹层已经关了,应答没有意义
      return null;

    case 'expand':
      onExpand();
      return (ok: true, data: true);

    case 'themeParams':
      if (!context.mounted) return null;
      final sz = Theme.of(context).sz;
      String hex(Color c) =>
          '#${c.toARGB32().toRadixString(16).padLeft(8, '0').substring(2)}';
      return (
        ok: true,
        data: {
          'brightness':
              Theme.of(context).brightness == Brightness.dark ? 'dark' : 'light',
          'paper': hex(sz.paper),
          'surface': hex(sz.surface),
          'ink': hex(sz.ink),
          'inkMuted': hex(sz.inkMuted),
          'line': hex(sz.line),
          'clay': hex(sz.clay),
          'link': hex(sz.link),
        }
      );

    case 'getInitData':
      // 权限是**每次调用都查**的,不是打开时查一次 ——
      // 清单可以在服务端随时改,不该等下次打开才生效
      if (!app.perms.contains('initData')) {
        return (ok: false, data: '该小程序未申请 initData 权限');
      }
      final pack = await api.miniAppInitData(app.id);
      return (ok: true, data: pack);

    default:
      return (ok: false, data: '未知方法:$method');
  }
}
