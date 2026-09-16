import 'package:flutter/material.dart';

import '../downloads.dart';
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
///
/// 电脑版(Windows / macOS / Ubuntu):下载完弹系统的存储对话框;打开文件交给系统默认程序。
/// 电脑上没有「相册」,macOS 写照片图库还要单独的权限 —— 见 media_save_io.dart 的 _onDesktop。
/// [from] 是这个文件所在的会话,只用来给「下载内容」那一格写上「哪来的」。
/// 不传也能用 —— 少一行来源好过少一条记录。
Future<void> saveChatMedia(BuildContext context, MediaInfo media, {ChatMeta? from}) =>
    _run(context, media, open: false, from: from);

Future<void> openChatFile(BuildContext context, MediaInfo media, {ChatMeta? from}) =>
    _run(context, media, open: true, from: from);

/// 删掉下载到本机的那份文件(「下载内容」里选了「连文件一起删」时用)。
/// 网页版没有这回事 —— 文件在浏览器的下载目录里,那份只能用户自己去删。
Future<void> deleteDownloaded(String path) => impl.deleteLocal(path);

/// 下载记录里的「哪来的」。只要两个字段,不把整个会话对象拖进来
class ChatMeta {
  const ChatMeta(this.id, this.title);

  final int id;
  final String title;
}

Future<void> _run(BuildContext context, MediaInfo media,
    {required bool open, ChatMeta? from}) async {
  final messenger = ScaffoldMessenger.maybeOf(context);
  final r = await resolveMediaNow(media);
  if (r == null) {
    messenger?.showSnackBar(const SnackBar(content: Text('没拿到文件地址,检查一下网络再试')));
    return;
  }
  if (!context.mounted) return;
  final sep = r.url.contains('?') ? '&' : '?';
  final path = await impl.fetchThen(context, '${r.url}${sep}download=1', media, open: open);
  // 下成了才记。取消存储对话框、没网、存相册被拒都拿不到路径,那就不算下载过
  if (path != null) {
    await Downloads.instance.record(media, path: path, chatId: from?.id, chatTitle: from?.title);
  }
}
