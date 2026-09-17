import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:apk_installer/apk_installer.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
import 'brand.dart' show kFontNote;
import 'platform_caps.dart';
import 'sz_widgets.dart';

/// 分发渠道:编译期由 --dart-define=SUPERZ_CHANNEL 指定。
///
/// - `self`(默认):自建分发(chaojizan.cc/download),走应用内下载安装;
/// - `store`:应用商店渠道,**整个更新检查直接关掉**。
///   商店明确禁止绕过审核自更新,商店包的更新只能由商店自己推。
const kChannel = String.fromEnvironment('SUPERZ_CHANNEL', defaultValue: 'self');

bool get _selfChannel => kChannel != 'store';

/// 应用内更新检查:启动时调用,服务端有更高 build 号就弹升级框。
///
/// 服务端接口 GET /app/latest?app=user|merchant|rider,发版脚本维护
/// versions.json。同签名 + build 号递增 → 手机上直接覆盖安装,无需卸载。
///
/// 自建渠道走「应用内下载 → 校验 SHA-256 → 拉起系统安装器」。
///
/// **「拿不到包」和「拿到了但现在装不了」是两件事,退路不一样:**
///
/// - 没带 sha256、下载失败、校验不过 —— 手里什么都没有,退回浏览器下载;
/// - **包下好了、也校验过了,只是拉不起安装界面** —— 这时候跳浏览器是错的,
///   等于让人把同一个 57MB 再下一遍。留着那个包,回到前台再装。
///
/// 第二种最常见的成因是**熄屏**:Android 10 起后台不许 startActivity,
/// 而熄屏时 App 就在后台。下载在后台是能跑完的,所以用户看到的是
/// 「下完了,却跳去浏览器重下」—— 2026-09-17 用户报的就是这个。
///
/// 绝不能把用户卡在一个转圈的进度条上。
///
/// 网页版和桌面版另走两条路,见下面。
Future<void> checkForUpdate(
  BuildContext context, {
  required String baseUrl,
  required String app,
  /// 只给测试用:**`flutter_test` 把真实 HTTP 全掐了**(所有请求一律回 400),
  /// 不留这个口子,连「有没有新版」这一跳都测不了。生产上永远是 null
  @visibleForTesting http.Client? client,
}) async {
  if (!_selfChannel) return; // 商店渠道:一句话都不说
  // 网页版:打开的永远是线上部署的那一版(刷新就是新的),没有「更新」这回事。
  // 不拦的话它会拿 APK 的版本号来比,弹一个让人在浏览器里下载安卓安装包的框
  if (kIsWeb) return;
  if (szIsDesktopApp) return _checkDesktop(context, baseUrl: baseUrl, app: app);

  Map<String, dynamic> latest;
  int currentBuild;
  try {
    final resp = await (client ?? http.Client())
        .get(Uri.parse('$baseUrl/app/latest?app=$app'))
        .timeout(const Duration(seconds: 8));
    if (resp.statusCode != 200) return;
    latest = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    // 版本号只取一次,和请求头 X-App-Build 用同一份缓存
    await ApiClient.loadAppBuild();
    currentBuild = int.tryParse(ApiClient.appBuild ?? '') ?? 0;
  } catch (_) {
    return; // 检查失败不打扰使用
  }

  final newBuild = (latest['build'] as num?)?.toInt() ?? 0;
  final version = latest['version'] as String? ?? '';
  final url = latest['url'] as String? ?? '';
  final notes = latest['notes'] as String? ?? '';
  final sha256Hex = (latest['sha256'] as String? ?? '').toLowerCase();
  final force = latest['force'] as bool? ?? false;
  if (newBuild <= currentBuild || url.isEmpty) return;
  if (!context.mounted) return;

  // 没带 sha256 的老 versions.json:不做应用内安装。
  // 装一个没校验过的 APK,比多点两下严重得多
  final canInApp = ApkInstaller.supported && sha256Hex.length == 64;

  await showDialog<void>(
    context: context,
    barrierDismissible: !force,
    builder: (dialogCtx) => PopScope(
      canPop: !force,
      child: _UpdateDialog(
        version: version,
        notes: notes,
        url: url,
        sha256Hex: sha256Hex,
        force: force,
        inApp: canInApp,
      ),
    ),
  );
}

/// versions.json 里某一端桌面版的条目;没有(老 versions.json、这一版没出桌面包)回 null。
///
/// 结构(发版脚本 scripts/sync_release_to_appdist.sh 写):
///
///     {"user": {...APK...}, "merchant": {...}, "rider": {...},
///      "desktop": {"user": {"version": "0.19.0", "build": 2061, "notes": "…",
///                           "page": "https://…/download#desktop",
///                           "files": {"windows": {"url": "…", "sha256": "…"}, …}}}}
///
/// 桌面版放在单独的 `desktop` 键下,**不动 user / merchant / rider 的结构** ——
/// 老版本 App 和 /app/latest 只认那三个键,新键它们看不见。
@visibleForTesting
Map<String, dynamic>? desktopReleaseOf(Object? versions, String app) {
  if (versions is! Map) return null;
  final desktop = versions['desktop'];
  if (desktop is! Map) return null;
  final entry = desktop[app];
  if (entry is! Map) return null;
  return entry.cast<String, dynamic>();
}

/// 桌面版(Windows / macOS / Ubuntu)的更新检查:**不下载、不安装**,
/// 只告诉他有新版,点一下打开官网下载页。
///
/// 手机上那套「下载 → 校验 → 拉起安装器」在桌面上不成立:APK 装不了,
/// 而三个系统的安装方式各不一样(解压 zip / 拖进「应用程序」/ 装 deb),
/// 让官网下载页按系统讲清楚比在 App 里做一遍稳。
///
/// 直接读 /appdist/versions.json,不走 /app/latest:那个接口对不认识的参数是忽略,
/// 服务端没更新的时候,问桌面版会拿到 APK 的条目 —— 那就又回到了「让电脑下安卓包」。
Future<void> _checkDesktop(
  BuildContext context, {
  required String baseUrl,
  required String app,
}) async {
  Map<String, dynamic>? latest;
  int currentBuild;
  try {
    final resp = await http
        .get(Uri.parse('$baseUrl/appdist/versions.json'))
        .timeout(const Duration(seconds: 8));
    if (resp.statusCode != 200) return;
    latest = desktopReleaseOf(jsonDecode(utf8.decode(resp.bodyBytes)), app);
    await ApiClient.loadAppBuild();
    currentBuild = int.tryParse(ApiClient.appBuild ?? '') ?? 0;
  } catch (_) {
    return; // 检查失败不打扰使用
  }
  if (latest == null) return;
  final newBuild = (latest['build'] as num?)?.toInt() ?? 0;
  // 读不到自己的版本号就不提示:宁可漏一次,也别每次打开都说「有新版」
  if (currentBuild <= 0 || newBuild <= currentBuild) return;
  final version = latest['version'] as String? ?? '';
  final notes = latest['notes'] as String? ?? '';
  final force = latest['force'] as bool? ?? false;
  final page = latest['page'] as String? ?? '$baseUrl/download#desktop';
  if (!context.mounted) return;
  await showDialog<void>(
    context: context,
    barrierDismissible: !force,
    builder: (dialogCtx) => PopScope(
      canPop: !force,
      child: SzDialog(
        title: Text('发现新版本 v$version'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (notes.isNotEmpty)
              Text(notes, style: const TextStyle(height: 1.6)),
            const SizedBox(height: 10),
            Text('电脑版要到官网下载新的安装包,装好后替换旧版即可。',
                style: TextStyle(
                    fontSize: kFontNote,
                    color: Theme.of(dialogCtx).colorScheme.outline)),
          ],
        ),
        actions: [
          if (!force)
            TextButton(
              onPressed: () => Navigator.pop(dialogCtx),
              child: const Text('稍后再说'),
            ),
          FilledButton(
            onPressed: () => launchUrl(Uri.parse(page),
                mode: LaunchMode.externalApplication),
            child: const Text('去官网下载'),
          ),
        ],
      ),
    ),
  );
}

class _UpdateDialog extends StatefulWidget {
  const _UpdateDialog({
    required this.version,
    required this.notes,
    required this.url,
    required this.sha256Hex,
    required this.force,
    required this.inApp,
  });

  final String version;
  final String notes;
  final String url;
  final String sha256Hex;
  final bool force;
  final bool inApp;

  @override
  State<_UpdateDialog> createState() => _UpdateDialogState();
}

class _UpdateDialogState extends State<_UpdateDialog>
    with WidgetsBindingObserver {
  double? _progress; // null = 未开始
  String? _error;

  /// 下好并且**校验过**的安装包。非空 = 手里有货,任何情况下都不该再跳浏览器
  File? _ready;

  /// 用户点过「更新」但还没装上 —— 回到前台时替他把安装器拉起来
  bool _wantInstall = false;

  /// 正在跑的那条系统下载。非空 = 后台下着,这一页关掉也不影响
  int? _downloadId;

  bool get _background => _downloadId != null;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 熄屏时拉不起安装界面(后台 startActivity 被系统挡着)。亮屏回到前台
    // 这一刻正是能拉起来的时候,替他补上 —— 否则他得自己想到再点一次
    if (state == AppLifecycleState.resumed && _ready != null && _wantInstall) {
      unawaited(_install(_ready!));
    }
  }

  /// **只在手里什么都没有的时候走这条**(下载失败、校验不过)。
  /// 包已经下好了就绝不能来这儿:那等于让人把同一个包再下一遍
  void _fallbackToBrowser([String? why]) {
    if (why != null && mounted) setState(() => _error = why);
    launchUrl(Uri.parse(widget.url), mode: LaunchMode.externalApplication);
  }

  /// 拉起系统安装器。**拉不起来不算失败**,包还在手里,回到前台再试
  Future<void> _install(File file) async {
    try {
      await ApkInstaller.install(file.path);
      // 拉起安装器后弹框留着:安装被用户取消时还能再点一次
      if (mounted) setState(() => _error = null);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = '已经下好了(校验通过),但现在装不了:'
          '手机息屏或 App 在后台时,系统不让弹安装界面。'
          '回到这一页点「立即安装」即可,不用重新下载。');
    }
  }

  Future<void> _run() async {
    if (!widget.inApp) {
      _fallbackToBrowser();
      return;
    }
    // 先问「安装未知应用」授权:没有它,下完 20MB 也是白下
    if (!await ApkInstaller.canInstall()) {
      if (!mounted) return;
      final go = await showDialog<bool>(
        context: context,
        builder: (ctx) => SzDialog(
          title: const Text('需要允许安装应用'),
          content: const Text(
              '用于安装超级赞的新版本安装包。\n'
              '系统会跳到设置页,打开「允许来自此来源的应用」后返回即可。\n'
              '拒绝也可以,我们会改用浏览器下载。'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('用浏览器下载')),
            FilledButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('去设置')),
          ],
        ),
      );
      if (go != true) {
        _fallbackToBrowser();
        return;
      }
      if (!await ApkInstaller.openInstallSettings()) {
        _fallbackToBrowser('这台手机打不开该设置页,已改用浏览器下载');
        return;
      }
      // 用户从设置页回来还要再点一次「立即更新」:这里不做自动续跑,
      // 授权是异步的,猜时机不如让用户自己点
      if (mounted) {
        setState(() => _error = '授权后请再点一次「立即更新」');
      }
      return;
    }

    _wantInstall = true;

    // 上一轮已经下好并校验过了(多半是当时熄屏、安装界面弹不出来)——
    // 直接装,**不要重新下**
    if (_ready != null) {
      await _install(_ready!);
      return;
    }

    setState(() {
      _error = null;
      _progress = 0;
    });
    File file;
    try {
      file = await _download();
    } catch (e) {
      // 走到这儿说明**手里什么都没有**:下载失败或校验不过。这才该退回浏览器
      if (!mounted) return;
      setState(() => _progress = null);
      _fallbackToBrowser('$e,已改用浏览器下载');
      return;
    }
    if (!mounted) return;
    setState(() {
      _progress = null;
      _ready = file;
    });
    await _install(file);
  }

  /// 走系统的后台下载队列。**退出这一页、切走 App、熄屏都继续下。**
  ///
  /// 返回下好的文件(已过 SHA-256 校验);排不进队列或下载失败就抛,
  /// 由调用方决定退回浏览器。
  Future<File> _downloadInBackground(File file) async {
    final id = await ApkInstaller.download(
        widget.url, file.uri.pathSegments.last,
        title: '超级赞 v${widget.version}');
    _downloadId = id;
    try {
      while (true) {
        final st = await ApkInstaller.downloadStatus(id);
        if (st.failed) {
          throw Exception(st.status == 'gone'
              ? '下载被取消了'
              : '下载失败(系统错误码 ${st.reason})');
        }
        if (st.done) break;
        if (mounted) setState(() => _progress = st.fraction ?? 0);
        await Future<void>.delayed(const Duration(milliseconds: 400));
      }
    } finally {
      _downloadId = null;
    }
    // 落点就是 FileProvider 那份 apk/ 目录,不用再挪
    final got = File(file.path);
    if (!got.existsSync()) {
      throw Exception('下载完了却找不到安装包');
    }
    await _verify(got);
    return got;
  }

  /// **不校验就等于给中间人一个装任意 APK 的口子。** 这是这条需求里唯一不能省的部分。
  ///
  /// 也正因为这个,系统那条「下载完成」通知是关掉的 —— 点它会直接装,绕过这里。
  Future<void> _verify(File file) async {
    final digest = sha256.convert(await file.readAsBytes()).toString();
    if (digest.toLowerCase() != widget.sha256Hex) {
      try {
        file.deleteSync();
      } catch (_) {}
      throw Exception('安装包校验不通过(可能被篡改或下载不完整)');
    }
  }

  Future<File> _download() async {
    final dir = Directory(
        '${(await getExternalStorageDirectory())!.path}/apk');
    if (!dir.existsSync()) dir.createSync(recursive: true);
    final file = File('${dir.path}/superz-${widget.version}.apk');

    // **这一版的包已经躺在这儿、而且校验得过,就直接用。**
    // 熄屏那一次装不上、App 又被系统回收之后,再点一次不该让人重下 57MB。
    // 判据是哈希不是「文件在不在」——半截的残骸也"在"
    if (file.existsSync() &&
        sha256.convert(await file.readAsBytes()).toString().toLowerCase() ==
            widget.sha256Hex) {
      return file;
    }

    // 剩下的都没用了:别的版本的包(已经装过)、这一版下了一半的残骸。
    // 不清理的话每更新一版就在用户手机上多躺几十 MB,永远不会自己消失
    for (final f in dir.listSync()) {
      try {
        f.deleteSync();
      } catch (_) {}
    }

    // 交给系统的后台下载队列。**这是唯一的下载路径** ——
    // 走到这儿一定有 ApkInstaller.supported(inApp 就是这么判的),
    // 再留一份「进程内下载」只会是永远跑不到、也没人测的死代码
    return _downloadInBackground(file);
  }

  @override
  Widget build(BuildContext context) {
    final downloading = _progress != null;
    return SzDialog(
      title: Text('发现新版本 v${widget.version}'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (widget.notes.isNotEmpty)
            Text(widget.notes, style: const TextStyle(height: 1.6)),
          const SizedBox(height: 10),
          if (downloading) ...[
            LinearProgressIndicator(
                value: _progress == 0 ? null : _progress),
            const SizedBox(height: 6),
            Text(
                _background
                    // 下载归系统管了,这一页只是在看着。说清楚可以走开,
                    // 不然人会守着这个进度条
                    ? '正在后台下载 ${((_progress ?? 0) * 100).toStringAsFixed(0)}%'
                        ' · 可以关掉这一页,下载不受影响'
                    : '正在下载 ${((_progress ?? 0) * 100).toStringAsFixed(0)}%',
                style: const TextStyle(fontSize: 12)),
          ] else
            Text(
                _error ??
                    (_ready != null
                        // 包在手里了:别再说「会下载」,那会让人以为要重来一遍
                        ? '安装包已下好并校验通过,点「立即安装」即可(无需卸载)。'
                        : widget.inApp
                            ? '下载完成后会自动打开安装,覆盖安装即可(无需卸载)。'
                            : '点击更新后在浏览器下载,下载完成直接安装即可(无需卸载)。'),
                style: TextStyle(
                    fontSize: 12,
                    color: _error != null
                        ? Theme.of(context).colorScheme.error
                        : Theme.of(context).colorScheme.outline)),
        ],
      ),
      actions: [
        // **下载中也让他走。** 下载归系统的队列管,关掉这一页照样下完;
        // 拦着不让关,等于逼人守着一个进度条 —— 而这正是「后台下载」的意义。
        // 下完之后回到 App 会直接弹安装(包已经在本地、哈希也对得上)
        if (!widget.force && (!downloading || _background))
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(downloading ? '后台下载' : '稍后再说'),
          ),
        FilledButton(
          onPressed: downloading ? null : _run,
          child: Text(downloading
              ? '下载中…'
              // 已经下好了就说「安装」——点它不会再产生一次下载
              : _ready != null
                  ? '立即安装'
                  : '立即更新'),
        ),
      ],
    );
  }
}
