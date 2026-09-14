import 'dart:io';

import 'package:file_selector/file_selector.dart' show getSaveLocation;
import 'package:flutter/material.dart';
import 'package:gal/gal.dart';
import 'package:http/http.dart' as http;
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart' show szIsDesktopApp;
import 'package:url_launcher/url_launcher.dart';

import '../models.dart';

/// 同一个文件同时只下一份(连点两下「保存」不下两遍)
final _inFlight = <int, Future<File?>>{};

/// 手机:下载到私有目录,然后存相册 / 交给系统应用打开;不行就交给分享面板。
/// 电脑:下载完弹系统的存储对话框,或者交给系统默认程序打开(见 [_onDesktop])。
Future<void> fetchThen(BuildContext context, String url, MediaInfo media, {required bool open}) async {
  final messenger = ScaffoldMessenger.maybeOf(context);
  // 回调要写成块:箭头写法会把 remove 拿到的 future(就是这个 future 自己)交回给 whenComplete,
  // 它会等那个 future —— 自己等自己,永远卡住
  final f = await (_inFlight[media.id] ??= _download(messenger, url, media).whenComplete(() {
    _inFlight.remove(media.id);
  }));
  if (f == null) return;
  if (szIsDesktopApp) return _onDesktop(messenger, f, open: open);
  if (open) {
    final r = await OpenFilex.open(f.path);
    if (r.type != ResultType.done) await _share(f); // 手机上没有能打开它的应用
    return;
  }
  try {
    if (_isVideo(f.path)) {
      await Gal.putVideo(f.path, album: Platform.isAndroid ? '超级赞' : null);
    } else {
      await Gal.putImage(f.path, album: Platform.isAndroid ? '超级赞' : null);
    }
    messenger?.showSnackBar(const SnackBar(content: Text('已保存到相册')));
  } on GalException {
    // 老系统上没有写相册的权限(我们不申请存储权限)、格式相册不认:让用户自己选存到哪
    await _share(f);
  }
}

/// 电脑上没有「相册」,分享面板也不是存文件的地方:
/// 「保存」弹系统的存储对话框让他自己选存哪;「打开文件」交给系统里默认打开它的程序,
/// 打不开(没有关联程序)再让他存一份。
///
/// 不走 gal:macOS 上写照片图库要单独的权限和用途说明(没配的话系统直接把 App 杀掉),
/// Linux 上 gal 根本没有实现。也不走 open_filex:它在桌面上是起一个 `open` / `xdg-open`
/// 子进程,macOS 沙箱里交给 NSWorkspace(url_launcher)更稳。
Future<void> _onDesktop(ScaffoldMessengerState? messenger, File f, {required bool open}) async {
  if (open) {
    try {
      if (await launchUrl(Uri.file(f.path))) return;
    } catch (_) {
      // 没有能打开它的程序:往下走,让他存一份
    }
  }
  final name = f.path.split(Platform.pathSeparator).last;
  final to = await getSaveLocation(suggestedName: name);
  if (to == null) return; // 对话框里点了取消
  try {
    await f.copy(to.path);
    messenger?.showSnackBar(SnackBar(content: Text('已保存到 ${to.path}')));
  } catch (_) {
    messenger?.showSnackBar(const SnackBar(content: Text('没存进去,换个位置再试')));
  }
}

bool _isVideo(String path) => RegExp(r'\.(mp4|mov|m4v|webm|3gp)$', caseSensitive: false).hasMatch(path);

Future<void> _share(File f) async {
  await SharePlus.instance.share(ShareParams(files: [XFile(f.path)]));
}

/// 按服务端回的类型补扩展名:相册按扩展名认格式,原文件名可能没有或者对不上(图片是重新编码过的)
String _fileName(MediaInfo media, String? contentType) {
  final ext = switch ((contentType ?? '').split(';').first.trim().toLowerCase()) {
    'image/jpeg' => '.jpg',
    'image/png' => '.png',
    'image/webp' => '.webp',
    'image/gif' => '.gif',
    'video/mp4' => '.mp4',
    'video/quicktime' => '.mov',
    'video/webm' => '.webm',
    _ => '',
  };
  var name = media.name.replaceAll(RegExp(r'[\\/:*?"<>|\x00-\x1f]'), '_').trim();
  if (name.isEmpty) name = '${media.kind.isEmpty ? 'file' : media.kind}_${media.id}';
  if (ext.isNotEmpty && media.kind != 'file') {
    final dot = name.lastIndexOf('.');
    name = '${dot > 0 ? name.substring(0, dot) : name}$ext';
  }
  return name;
}

Future<File?> _download(ScaffoldMessengerState? messenger, String url, MediaInfo media) async {
  final dir = Directory('${(await getTemporaryDirectory()).path}/chat_files/${media.id}');
  // 下过了就直接用(同一条消息的文件不会变)
  if (await dir.exists()) {
    final done = await dir.list().where((e) => e is File && !e.path.endsWith('.part')).toList();
    if (done.isNotEmpty) return done.first as File;
  }
  await dir.create(recursive: true);
  final progress = ValueNotifier<double?>(null);
  final bar = messenger?.showSnackBar(SnackBar(
    duration: const Duration(minutes: 30),
    content: ValueListenableBuilder<double?>(
      valueListenable: progress,
      builder: (_, p, __) => Text(p == null ? '正在下载…' : '正在下载 ${(p * 100).round()}%'),
    ),
  ));
  final client = http.Client();
  File? part;
  try {
    final resp = await client.send(http.Request('GET', Uri.parse(url)));
    if (resp.statusCode != 200) throw HttpException('HTTP ${resp.statusCode}');
    final target = File('${dir.path}/${_fileName(media, resp.headers['content-type'])}');
    part = File('${target.path}.part');
    final total = resp.contentLength ?? media.size;
    final sink = part.openWrite();
    var got = 0;
    try {
      await for (final chunk in resp.stream) {
        sink.add(chunk);
        got += chunk.length;
        if (total > 0) progress.value = (got / total).clamp(0.0, 1.0);
      }
    } finally {
      await sink.close();
    }
    return await part.rename(target.path);
  } catch (_) {
    try {
      await part?.delete();
    } catch (_) {}
    messenger?.showSnackBar(const SnackBar(content: Text('没下载下来,检查一下网络再试')));
    return null;
  } finally {
    client.close();
    bar?.close();
    // 进度条的提示条还在退场,里面的 ValueListenableBuilder 还挂着:等它真关掉再销毁
    if (bar == null) {
      progress.dispose();
    } else {
      bar.closed.whenComplete(progress.dispose);
    }
  }
}
