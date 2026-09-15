import 'package:flutter/material.dart';

import '../../session.dart';
import '../creator/upload_page.dart';

/// 投稿入口:要登录。不要求实名(2026-09-15 起)。
Future<void> openUpload(BuildContext context) async {
  if (!await ensureLoggedIn(context)) return;
  if (!context.mounted) return;
  await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const VideoUploadPage()));
}
