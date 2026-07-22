import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

/// 应用内更新检查:启动时调用,服务端有更高 build 号就弹升级框。
///
/// 服务端接口 GET /app/latest?app=user|merchant|rider,发版脚本维护
/// versions.json。同签名 + build 号递增 → 手机上直接覆盖安装,无需卸载。
Future<void> checkForUpdate(
  BuildContext context, {
  required String baseUrl,
  required String app,
}) async {
  Map<String, dynamic> latest;
  int currentBuild;
  try {
    final resp = await http
        .get(Uri.parse('$baseUrl/app/latest?app=$app'))
        .timeout(const Duration(seconds: 8));
    if (resp.statusCode != 200) return;
    latest = jsonDecode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    final info = await PackageInfo.fromPlatform();
    currentBuild = int.tryParse(info.buildNumber) ?? 0;
  } catch (_) {
    return; // 检查失败不打扰使用
  }

  final newBuild = (latest['build'] as num?)?.toInt() ?? 0;
  final version = latest['version'] as String? ?? '';
  final url = latest['url'] as String? ?? '';
  final notes = latest['notes'] as String? ?? '';
  final force = latest['force'] as bool? ?? false;
  if (newBuild <= currentBuild || url.isEmpty) return;
  if (!context.mounted) return;

  await showDialog<void>(
    context: context,
    barrierDismissible: !force,
    builder: (dialogCtx) => PopScope(
      canPop: !force,
      child: AlertDialog(
        title: Text('发现新版本 v$version'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (notes.isNotEmpty) Text(notes, style: const TextStyle(height: 1.6)),
            const SizedBox(height: 10),
            Text('点击更新后在浏览器下载,下载完成直接安装即可(无需卸载)。',
                style: TextStyle(
                    fontSize: 12,
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
            onPressed: () =>
                launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication),
            child: const Text('立即更新'),
          ),
        ],
      ),
    ),
  );
}
