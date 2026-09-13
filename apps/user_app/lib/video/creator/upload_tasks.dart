// 投稿原片的上传任务:放在全局,离开投稿页也接着传,传完自动挂到稿件上(#358「可后台继续」)。
//
// 为什么能后台继续:上传是这里的一个 Future,不挂在页面的生命周期上 —— 页面关了它照样跑完,
// 然后调「挂分 P」。投稿页、创作中心都只是来这里看进度。
// 做不到的:App 被杀掉之后续不上(浏览器关掉标签页同理)。稿件是在选完视频那一刻就建好的草稿,
// 所以杀掉之后草稿还在,重新选一次文件就行。
import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:image_picker/image_picker.dart' show XFile;
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../nav.dart';
import 'upload_form.dart';

enum UploadState { uploading, attaching, done, failed, cancelled }

/// 一个在传的分 P。
class PartUpload {
  PartUpload._(this.vid, this.file, this.name, this.size, this.title);

  final String vid;
  final XFile file;
  final String name;
  final int size;

  /// 挂上去时这一 P 的标题(空 = 服务端用文件名)
  final String title;

  double progress = 0;
  UploadState state = UploadState.uploading;
  String? error;
  int? partId;
  int attempts = 0;

  bool get active => state == UploadState.uploading || state == UploadState.attaching;
}

class _Cancelled implements Exception {}

/// 全部上传任务(单例)。页面用 `AnimatedBuilder(animation: VideoUploads.instance)` 看进度。
class VideoUploads extends ChangeNotifier {
  VideoUploads._();

  static final VideoUploads instance = VideoUploads._();

  final List<PartUpload> _tasks = [];

  List<PartUpload> of(String vid) => [for (final t in _tasks) if (t.vid == vid) t];

  bool busy(String vid) => _tasks.any((t) => t.vid == vid && t.active);

  /// 这个稿件在传的总进度(几个分 P 一起传时按字节数加权);没有在传的返回 null
  double? progressOf(String vid) {
    final ts = [for (final t in _tasks) if (t.vid == vid && t.active) t];
    if (ts.isEmpty) return null;
    final total = ts.fold<int>(0, (s, t) => s + t.size);
    if (total <= 0) return 0;
    return ts.fold<double>(0, (s, t) => s + t.progress * t.size) / total;
  }

  /// 开始传一 P。超过 1GB 的直接拒掉(服务端也会拦,但那要先传完 1GB 才知道)。
  PartUpload start(String vid, XFile file, int size, {String title = ''}) {
    final t = PartUpload._(vid, file, file.name.isNotEmpty ? file.name : 'video.mp4', size, title);
    _tasks.add(t);
    if (size > kPartMaxBytes) {
      t
        ..state = UploadState.failed
        ..error = '单个分 P 最大 1GB';
      notifyListeners();
      return t;
    }
    notifyListeners();
    unawaited(_run(t));
    return t;
  }

  void retry(PartUpload t) {
    if (t.active || t.state == UploadState.done) return;
    t
      ..state = UploadState.uploading
      ..error = null
      ..progress = 0
      ..attempts = 0;
    notifyListeners();
    unawaited(_run(t));
  }

  /// 不传了:下一片读文件的时候停下(已经在飞的那一片没法撤回)
  void cancel(PartUpload t) {
    if (t.active) {
      t.state = UploadState.cancelled;
    }
    _tasks.remove(t);
    notifyListeners();
  }

  /// 失败 / 做完的从列表里拿掉
  void dismiss(PartUpload t) {
    if (t.active) return;
    if (_tasks.remove(t)) notifyListeners();
  }

  /// 退出登录时清掉(换了账号,别把上一个人的原片挂到下一个人名下 —— 服务端也会拒,这里别白传)
  void clear() {
    for (final t in _tasks) {
      if (t.active) t.state = UploadState.cancelled;
    }
    _tasks.clear();
    notifyListeners();
  }

  Future<Uint8List> _read(PartUpload t, int start, int end) async {
    if (t.state == UploadState.cancelled) throw _Cancelled();
    final out = BytesBuilder(copy: false);
    await for (final part in t.file.openRead(start, end)) {
      out.add(part);
    }
    return out.takeBytes();
  }

  Future<void> _run(PartUpload t) async {
    while (true) {
      t.attempts++;
      try {
        final media = await videoApi.uploadSource((s, e) => _read(t, s, e), t.size, t.name,
            onProgress: (p) {
          if (t.state != UploadState.uploading) return;
          t.progress = p;
          notifyListeners();
        });
        if (t.state == UploadState.cancelled) return;
        t.state = UploadState.attaching;
        notifyListeners();
        final r = await videoApi.addPart(t.vid, vInt(media['id']), t.title);
        t
          ..partId = vInt(r['added_part_id'])
          ..progress = 1
          ..state = UploadState.done;
        notifyListeners();
        // 投稿页开着的话它会马上拉最新的稿件并把这条拿掉;没开着就过一会儿自己清掉
        Timer(const Duration(seconds: 30), () => dismiss(t));
        return;
      } on _Cancelled {
        return;
      } catch (e) {
        if (t.state == UploadState.cancelled) return;
        // 断网、超时这类自己重试两次(每次都是从头传:uploadSource 每次新建一个上传);
        // 服务端明确拒绝的(超长、格式不对、稿件在审核中)不重试,原话告诉用户
        final network = e is ApiException && e.isNetwork;
        if (network && t.attempts < 3) {
          t.progress = 0;
          notifyListeners();
          await Future<void>.delayed(Duration(seconds: 2 * t.attempts));
          if (t.state == UploadState.cancelled) return;
          continue;
        }
        t
          ..state = UploadState.failed
          ..error = e is ApiException ? e.message : '上传失败,请重试';
        notifyListeners();
        return;
      }
    }
  }
}
