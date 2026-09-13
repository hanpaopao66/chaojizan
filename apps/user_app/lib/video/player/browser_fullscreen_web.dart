import 'dart:js_interop';

import 'package:web/web.dart' as web;

/// 让整个页面进浏览器全屏。必须在点击事件里**同步**发起(浏览器只认用户手势),
/// 所以调用方要在第一个 await 之前调它。浏览器拒绝(比如 iframe 里没给权限)就算了,全屏路由照样铺满窗口。
Future<void> enterBrowserFullscreen() async {
  try {
    if (web.document.fullscreenElement != null) return;
    await web.document.documentElement?.requestFullscreen().toDart;
  } catch (_) {}
}

Future<void> exitBrowserFullscreen() async {
  try {
    if (web.document.fullscreenElement == null) return;
    await web.document.exitFullscreen().toDart;
  } catch (_) {}
}
