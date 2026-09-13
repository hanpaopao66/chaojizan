/// 网页版进出浏览器真全屏;手机上什么也不做(手机的全屏是全屏路由 + 锁方向)。
///
/// 网页版单靠全屏路由只是「网页全屏」:地址栏、系统栏都还在。而且手机浏览器上
/// 锁屏幕方向(`screen.orientation.lock`,SystemChrome 在网页版就是调它)只在真全屏里才生效 ——
/// 所以横屏视频要先进浏览器全屏,再锁横屏。
library;

export 'browser_fullscreen_stub.dart' if (dart.library.js_interop) 'browser_fullscreen_web.dart';
