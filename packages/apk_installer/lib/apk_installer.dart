import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// 自建分发渠道的安装器(#123)。仅 Android;其他平台一律返回"不支持",
/// 调用方据此退回到"跳浏览器下载"的老路。
class ApkInstaller {
  ApkInstaller._();

  static const _channel = MethodChannel('superz/apk_installer');

  /// 判据和 `platform_caps.dart` 里那几个保持一致:`!kIsWeb` + `defaultTargetPlatform`。
  ///
  /// 原来还加了一个 `Platform.isAndroid`。生产上它和前一个条件永远同真同假
  /// (`defaultTargetPlatform` 只在 debug 下可被覆盖),**但它让整条应用内安装的
  /// 路径没法写测试** —— 测试进程跑在 mac/linux 上,`Platform.isAndroid` 恒假,
  /// 于是任何用例都只能走到「跳浏览器」那一支。这条路径 2026-09-17 出过一个
  /// 真 bug(熄屏下好了包却跳浏览器重下),而它一条测试都没有。
  static bool get supported =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  /// 用户是否已授予本应用「安装未知应用」。Android 8.0 以下恒为 true。
  static Future<bool> canInstall() async {
    if (!supported) return false;
    try {
      return await _channel.invokeMethod<bool>('canInstall') ?? false;
    } catch (_) {
      return false;
    }
  }

  /// 跳到本应用的「安装未知应用」设置页。返回 false 表示这台机器上跳不过去
  /// (个别定制 ROM 没有这个页面),调用方应退回浏览器下载。
  static Future<bool> openInstallSettings() async {
    if (!supported) return false;
    try {
      return await _channel.invokeMethod<bool>('openInstallSettings') ?? false;
    } catch (_) {
      return false;
    }
  }

  /// 把下载好的 APK 交给系统安装器。抛异常表示拉不起来(比如 App 在后台 ——
  /// Android 10 起后台不许起 Activity),**这时候包还是好的**,调用方别扔。
  static Future<void> install(String path) async {
    if (!supported) {
      throw UnsupportedError('当前平台不支持应用内安装');
    }
    await _channel.invokeMethod<bool>('install', {'path': path});
  }

  // ---------- 后台下载(交给系统的 DownloadManager) ----------
  //
  // **为什么不在 Dart 里下**:Dart 那份活在 Flutter 引擎里,App 被系统回收就断了,
  // 而且没法在通知栏画进度。DownloadManager 退到后台、熄屏、进程被杀都继续下,
  // 进度由系统自己显示 —— 那是系统的通知,不占我们的通知权限。
  //
  // 「下载完成」那条系统通知是**刻意关掉**的:点它会直接装,绕过 SHA-256 校验。

  /// 排进系统下载队列,返回这条下载的编号。[fileName] 是落地文件名
  /// (和 FileProvider 声明的 `apk/` 目录同一个地方,下完就地能装)。
  static Future<int> download(String url, String fileName,
      {String? title}) async {
    if (!supported) throw UnsupportedError('当前平台不支持后台下载');
    final id = await _channel.invokeMethod<int>('download', {
      'url': url,
      'fileName': fileName,
      if (title != null) 'title': title,
    });
    if (id == null) throw Exception('排不进下载队列');
    return id;
  }

  /// 查一条下载现在怎么样了。
  ///
  /// [status] 取 `running` / `paused` / `done` / `failed` / `gone`
  /// (`gone` = 用户在通知栏划掉了,或者系统清了记录 —— 不是错误,重新下就是)。
  static Future<ApkDownloadStatus> downloadStatus(int id) async {
    final m = await _channel
        .invokeMapMethod<String, dynamic>('downloadStatus', {'id': id});
    return ApkDownloadStatus(
      status: m?['status'] as String? ?? 'gone',
      soFar: (m?['soFar'] as num?)?.toInt() ?? 0,
      total: (m?['total'] as num?)?.toInt() ?? 0,
      path: m?['path'] as String?,
      reason: (m?['reason'] as num?)?.toInt() ?? 0,
    );
  }

  static Future<void> cancelDownload(int id) async {
    if (!supported) return;
    try {
      await _channel.invokeMethod<bool>('cancelDownload', {'id': id});
    } catch (_) {}
  }
}

/// 一条后台下载的现状。
class ApkDownloadStatus {
  const ApkDownloadStatus({
    required this.status,
    required this.soFar,
    required this.total,
    required this.path,
    required this.reason,
  });

  final String status;
  final int soFar;

  /// 总字节。**可能是 -1**:服务器没给 Content-Length 时 DownloadManager
  /// 就不知道总量。这时候只能画个不确定的进度条,别拿它做除数
  final int total;

  /// 落地路径。只有 `done` 时才有
  final String? path;

  /// 失败原因(DownloadManager 的 ERROR_* 码)
  final int reason;

  bool get done => status == 'done';
  bool get failed => status == 'failed' || status == 'gone';

  /// 0–1;总量不知道时回 null(交给不确定进度条)
  double? get fraction =>
      total > 0 ? (soFar / total).clamp(0.0, 1.0) : null;
}
