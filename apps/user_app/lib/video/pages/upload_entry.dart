import 'package:flutter/material.dart';

import '../../session.dart';

/// 投稿入口:要登录;实名在提交时由服务端判(403 时投稿页给「去认证」)。
Future<void> openUpload(BuildContext context) async {
  if (!await ensureLoggedIn(context)) return;
  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('投稿页面准备中')));
}
