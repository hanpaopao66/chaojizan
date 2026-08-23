import 'dart:convert';
import 'dart:io';

import 'package:apk_installer/apk_installer.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api_client.dart';
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
/// 自建渠道走「应用内下载 → 校验 SHA-256 → 拉起系统安装器」;
/// 任何一步不成(没带 sha256、下载失败、校验不过、系统不给拉安装器),
/// 一律退回老路:跳浏览器下载。绝不能把用户卡在一个转圈的进度条上。
Future<void> checkForUpdate(
  BuildContext context, {
  required String baseUrl,
  required String app,
}) async {
  if (!_selfChannel) return; // 商店渠道:一句话都不说

  Map<String, dynamic> latest;
  int currentBuild;
  try {
    final resp = await http
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

class _UpdateDialogState extends State<_UpdateDialog> {
  double? _progress; // null = 未开始
  String? _error;

  void _fallbackToBrowser([String? why]) {
    if (why != null && mounted) setState(() => _error = why);
    launchUrl(Uri.parse(widget.url), mode: LaunchMode.externalApplication);
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

    setState(() {
      _error = null;
      _progress = 0;
    });
    try {
      final file = await _download();
      if (!mounted) return;
      await ApkInstaller.install(file.path);
      // 拉起安装器后弹框留着:安装被用户取消时还能再点一次
      if (mounted) setState(() => _progress = null);
    } catch (e) {
      if (!mounted) return;
      setState(() => _progress = null);
      _fallbackToBrowser('$e,已改用浏览器下载');
    }
  }

  Future<File> _download() async {
    final dir = Directory(
        '${(await getExternalStorageDirectory())!.path}/apk');
    if (!dir.existsSync()) dir.createSync(recursive: true);
    // 先清空:目录里的要么是已经装完的包,要么是上次失败的残骸,一律没用了。
    // 不清理的话每更新一版就在用户手机上多躺几十 MB,永远不会自己消失
    for (final f in dir.listSync()) {
      try {
        f.deleteSync();
      } catch (_) {}
    }
    final file = File('${dir.path}/superz-${widget.version}.apk');

    final req = http.Request('GET', Uri.parse(widget.url));
    final resp = await http.Client().send(req).timeout(
        const Duration(seconds: 30));
    if (resp.statusCode != 200) {
      throw Exception('下载失败(HTTP ${resp.statusCode})');
    }
    final total = resp.contentLength ?? 0;
    final sink = file.openWrite();
    var received = 0;
    try {
      await for (final chunk in resp.stream) {
        sink.add(chunk);
        received += chunk.length;
        if (total > 0 && mounted) {
          setState(() => _progress = received / total);
        }
      }
    } finally {
      await sink.close();
    }

    // 校验:不校验就等于给中间人一个装任意 APK 的口子。
    // 这是这条需求里唯一不能省的部分
    final digest = sha256.convert(await file.readAsBytes()).toString();
    if (digest.toLowerCase() != widget.sha256Hex) {
      try {
        file.deleteSync();
      } catch (_) {}
      throw Exception('安装包校验不通过(可能被篡改或下载不完整)');
    }
    return file;
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
            Text('正在下载 ${((_progress ?? 0) * 100).toStringAsFixed(0)}%',
                style: const TextStyle(fontSize: 12)),
          ] else
            Text(
                _error ??
                    (widget.inApp
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
        if (!widget.force && !downloading)
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('稍后再说'),
          ),
        FilledButton(
          onPressed: downloading ? null : _run,
          child: Text(downloading ? '下载中…' : '立即更新'),
        ),
      ],
    );
  }
}
