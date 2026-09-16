// 音频原文件的上传任务:放在全局,离开作品编辑页也接着传,传完自动建歌。
//
// 照投稿原片那一套(video/creator/upload_tasks.dart):上传是这里的一个 Future,
// 不挂在页面的生命周期上 —— 页面关了它照样跑完。做不到的是 App 被杀之后续不上,
// 但作品是草稿状态存着的,重新选一次文件就行。
import 'dart:async';
import 'dart:typed_data';

import 'package:file_selector/file_selector.dart' show XFile;
import 'package:flutter/foundation.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/models.dart';
import '../nav.dart';

enum TrackUploadState { uploading, creating, done, failed, cancelled }

/// 一首在传的歌。
class TrackUpload {
  TrackUpload._(this.rid, this.file, this.name, this.size, this.title, this.declaration);

  final String rid;
  final XFile file;
  final String name;
  final int size;
  final String title;

  /// 原创 / 已获授权(§4 M1,上传时必选其一)
  final String declaration;

  double progress = 0;
  TrackUploadState state = TrackUploadState.uploading;
  String? error;
  String? tid;
  int attempts = 0;

  bool get active => state == TrackUploadState.uploading || state == TrackUploadState.creating;
}

class _Cancelled implements Exception {}

/// 单首上限 200MB(§4 M4)。服务端也会拦,但那要先把 200MB 传完才知道。
const int kAudioMaxBytes = 200 * 1024 * 1024;

/// 全部在传的歌(单例)。作品编辑页用 `AnimatedBuilder(animation: MusicUploads.instance)` 看进度。
class MusicUploads extends ChangeNotifier {
  MusicUploads._();

  static final MusicUploads instance = MusicUploads._();

  final List<TrackUpload> _tasks = [];

  List<TrackUpload> of(String rid) => [for (final t in _tasks) if (t.rid == rid) t];

  bool busy(String rid) => _tasks.any((t) => t.rid == rid && t.active);

  /// 开始传一首。[onDone] 传完建好歌之后回调(编辑页据此刷新列表)。
  TrackUpload start(
    String rid,
    XFile file,
    int size, {
    required String title,
    required String declaration,
    VoidCallback? onDone,
  }) {
    final t = TrackUpload._(rid, file, file.name.isNotEmpty ? file.name : 'audio.m4a', size, title, declaration);
    _tasks.add(t);
    if (size > kAudioMaxBytes) {
      t
        ..state = TrackUploadState.failed
        ..error = '单首最大 200MB';
      notifyListeners();
      return t;
    }
    notifyListeners();
    unawaited(_run(t, onDone));
    return t;
  }

  void retry(TrackUpload t, {VoidCallback? onDone}) {
    if (t.active || t.state == TrackUploadState.done) return;
    t
      ..state = TrackUploadState.uploading
      ..error = null
      ..progress = 0
      ..attempts = 0;
    notifyListeners();
    unawaited(_run(t, onDone));
  }

  /// 不传了:下一片读文件的时候停下(已经在飞的那一片没法撤回)
  void cancel(TrackUpload t) {
    if (t.active) t.state = TrackUploadState.cancelled;
    _tasks.remove(t);
    notifyListeners();
  }

  void dismiss(TrackUpload t) {
    if (t.active) return;
    if (_tasks.remove(t)) notifyListeners();
  }

  /// 退出登录时清掉:换了账号,别把上一个人的原文件挂到下一个人名下
  void clear() {
    for (final t in _tasks) {
      if (t.active) t.state = TrackUploadState.cancelled;
    }
    _tasks.clear();
    notifyListeners();
  }

  Future<Uint8List> _read(TrackUpload t, int start, int end) async {
    if (t.state == TrackUploadState.cancelled) throw _Cancelled();
    final out = BytesBuilder(copy: false);
    await for (final part in t.file.openRead(start, end)) {
      out.add(part);
    }
    return out.takeBytes();
  }

  Future<void> _run(TrackUpload t, VoidCallback? onDone) async {
    while (true) {
      t.attempts++;
      try {
        final media = await musicApi.uploadAudio((s, e) => _read(t, s, e), t.size, t.name, onProgress: (p) {
          if (t.state != TrackUploadState.uploading) return;
          t.progress = p;
          notifyListeners();
        });
        if (t.state == TrackUploadState.cancelled) return;
        t.state = TrackUploadState.creating;
        notifyListeners();
        final track = await musicApi.addTrack(
          t.rid,
          title: t.title.isNotEmpty ? t.title : _titleOf(t.name),
          mediaId: vInt(media['id']),
          declaration: t.declaration,
        );
        t
          ..tid = track.tid
          ..progress = 1
          ..state = TrackUploadState.done;
        notifyListeners();
        onDone?.call();
        // 编辑页开着的话它会马上拉最新的作品并把这条拿掉;没开着就过一会儿自己清掉
        Timer(const Duration(seconds: 30), () => dismiss(t));
        return;
      } on _Cancelled {
        return;
      } catch (e) {
        if (t.state == TrackUploadState.cancelled) return;
        // 断网、超时这类自己重试两次;服务端明确拒绝的(格式不对、太长、作品在审核中)
        // 不重试,原话告诉用户
        final network = e is ApiException && e.isNetwork;
        if (network && t.attempts < 3) {
          t.progress = 0;
          notifyListeners();
          await Future<void>.delayed(Duration(seconds: 2 * t.attempts));
          if (t.state == TrackUploadState.cancelled) return;
          continue;
        }
        t
          ..state = TrackUploadState.failed
          ..error = e is ApiException ? e.message : '上传失败,请重试';
        notifyListeners();
        return;
      }
    }
  }

  /// 没填歌名时拿文件名顶上(去掉扩展名)
  static String _titleOf(String filename) {
    final dot = filename.lastIndexOf('.');
    final base = dot > 0 ? filename.substring(0, dot) : filename;
    return base.trim().isEmpty ? '未命名' : base.trim();
  }
}
