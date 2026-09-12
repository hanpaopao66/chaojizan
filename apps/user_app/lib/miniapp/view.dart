/// 手机端是原生 WebView,web 端是跨域 iframe:同一个 [MiniAppView],按平台选实现。
library;

export 'view_mobile.dart' if (dart.library.js_interop) 'view_web.dart';
