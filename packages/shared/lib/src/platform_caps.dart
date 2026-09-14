/// 这个平台上某项**原生能力**有没有实现。
///
/// 用户端要发 Windows / macOS / Ubuntu 三个桌面包,而不少插件只做了手机端:
/// 腾讯地图、极光推送只有安卓 / iOS,video_player 没有 Windows / Linux,
/// image_picker 在桌面上不能拍照…… 调了没实现的插件,轻则静默没反应,
/// 重则一直转圈(见 [szCanPlayVideo])。这里把「能不能」集中成几个判据。
///
/// ## 和 responsive.dart 那条「别按平台判断」不冲突
///
/// 那边管**布局**:按可用宽度分三档,手机横屏、平板、网页、桌面都一样处理;
/// 这里管**插件在这个操作系统上有没有实现** —— 这件事只能按平台判断,和窗口多宽无关。
///
/// ## 写法
///
/// 一律先看 kIsWeb:网页上 `defaultTargetPlatform` 报的是**浏览器所在的系统**
/// (Windows 上的 Chrome 报 windows),不先排除网页会把网页版当成桌面版。
/// 用 `defaultTargetPlatform` 而不是 dart:io 的 `Platform`:网页版编得过,
/// 测试里也能用 `debugDefaultTargetPlatformOverride` 改。
library;

import 'package:flutter/foundation.dart';

bool _is(TargetPlatform p) => !kIsWeb && defaultTargetPlatform == p;

/// 桌面系统上的原生包(Windows / macOS / Linux)。网页版不算,不管浏览器开在什么系统上。
bool get szIsDesktopApp =>
    _is(TargetPlatform.windows) ||
    _is(TargetPlatform.macOS) ||
    _is(TargetPlatform.linux);

/// 能不能放视频(video_player):安卓、iOS、macOS、网页有实现,**Windows 和 Linux 没有**。
///
/// 没实现的平台上不是「报个错」那么简单:`initialize()` 抛 UnimplementedError 之后,
/// `dispose()` 会一直等一个永远不完成的 future —— 失败分支里 `await c.dispose()`
/// 再置失败状态的写法,表现是**转圈转到天荒地老**。所以要在建播放器之前就拦下。
bool get szCanPlayVideo =>
    kIsWeb ||
    _is(TargetPlatform.android) ||
    _is(TargetPlatform.iOS) ||
    _is(TargetPlatform.macOS);

/// 放不了视频时给用户看的那句话(几处播放器共用,说法一致)。
const String kVideoUnsupportedHint = '这个平台暂不支持播放,请在手机或网页版上看';

/// 能不能直接调相机拍照 / 拍视频(image_picker 的 `ImageSource.camera`)。
///
/// 桌面上 image_picker 只会弹选文件的框,拍照要另外接相机插件,不接的话一点就抛异常 ——
/// 入口直接不显示。网页照旧:手机浏览器会调起相机,电脑浏览器退成选文件。
bool get szCanUseCamera =>
    kIsWeb || _is(TargetPlatform.android) || _is(TargetPlatform.iOS);

/// 能不能把**文件**交给系统分享面板(share_plus 带 files):Linux 上没有实现,
/// 一调就抛 UnimplementedError(纯文字的分享在 Linux 上会变成打开邮件客户端)。
bool get szCanShareFiles => !_is(TargetPlatform.linux);

/// 「扫一扫」入口显不显示:桌面包上不显示。
///
/// 电脑没有举着摄像头对二维码这种用法;扫码插件(mobile_scanner)在 Windows / Linux 上
/// 也没有实现。网页版在手机浏览器里能扫,交给用到它的地方自己决定。
bool get szShowScanEntry => !szIsDesktopApp;
