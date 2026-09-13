import 'package:flutter/material.dart';

import '../models.dart';
import 'media_save_io.dart' if (dart.library.js_interop) 'media_save_web.dart' as impl;
import 'media_views.dart' show resolveMediaNow;

/// 聊天里的「保存」(看图 / 看视频右上角)和「打开文件」(文件消息)。
///
/// 网页:交给浏览器下载(签名地址带 download=1,服务端回 Content-Disposition)。
///
/// 手机:原来也是交给外部浏览器 —— 用户被带出 App,还要在浏览器的下载列表里找文件。
/// 现在在 App 里下载到私有目录(提示条上有进度),图片、视频存进相册,文件交给系统里能打开它的应用;
/// 存不进 / 没有能打开它的应用时,退回系统分享面板,让用户自己选存到哪、用什么打开。
///
/// 不申请存储权限(清单里是故意去掉的):安卓 10 起写相册走 MediaStore 不需要权限,
/// 更老的系统存不进,就走分享面板。
Future<void> saveChatMedia(BuildContext context, MediaInfo media) => _run(context, media, open: false);

Future<void> openChatFile(BuildContext context, MediaInfo media) => _run(context, media, open: true);

Future<void> _run(BuildContext context, MediaInfo media, {required bool open}) async {
  final messenger = ScaffoldMessenger.maybeOf(context);
  final r = await resolveMediaNow(media);
  if (r == null) {
    messenger?.showSnackBar(const SnackBar(content: Text('没拿到文件地址,检查一下网络再试')));
    return;
  }
  if (!context.mounted) return;
  final sep = r.url.contains('?') ? '&' : '?';
  await impl.fetchThen(context, '${r.url}${sep}download=1', media, open: open);
}
