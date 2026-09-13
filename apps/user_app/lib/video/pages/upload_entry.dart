import 'package:flutter/material.dart';

import '../../session.dart';
import '../creator/upload_page.dart';

/// 投稿入口:要登录;实名在建稿时由服务端判(403 时投稿页给「去认证」)。
Future<void> openUpload(BuildContext context) async {
  if (!await ensureLoggedIn(context)) return;
  if (!context.mounted) return;
  await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const VideoUploadPage()));
}
