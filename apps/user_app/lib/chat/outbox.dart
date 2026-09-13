import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:image_picker/image_picker.dart' show XFile;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'api.dart';
import 'models.dart';
import 'store.dart';

/// 一个待上传的附件。手机上是文件路径、网页上是内存里的字节,都包成 [XFile]:
/// 两边都能 `openRead(start, end)` 按区间读,大文件分片时不用整个读进内存。
class LocalAttachment {
  LocalAttachment({
    required this.file,
    required this.kind,
    required this.name,
    required this.size,
    this.w = 0,
    this.h = 0,
    this.durationMs = 0,
    this.waveform = const [],
    this.preview,
  });

  final XFile file;

  /// photo / video / file / voice / gif / video_note
  final String kind;
  final String name;
  final int size;
  final int w;
  final int h;
  final int durationMs;
  final List<int> waveform;

  /// 图片的原始字节:发送中的气泡先用它画出来,不用等上传完
  final Uint8List? preview;
}

/// 队列里的一项:一条要发的消息(可能带几个附件)。
class _OutItem {
  _OutItem({
    required this.randomId,
    required this.chatId,
    required this.body,
    this.attachments = const [],
    List<int>? uploaded,
  }) : uploaded = uploaded ?? [];

  final String randomId;
  final int chatId;

  /// 发送接口的请求体(不含 random_id、media_ids,发的时候再补)
  final Map<String, dynamic> body;
  final List<LocalAttachment> attachments;

  /// 已经上传好的媒体 id(和 attachments 一一对应;重发时不再传一遍)
  final List<int> uploaded;
  int attempts = 0;

  bool get needsUpload => uploaded.length < attachments.length;

  Map<String, dynamic> toJson() => {
        'random_id': randomId,
        'chat_id': chatId,
        'body': body,
        'uploaded': uploaded,
      };
}

/// 待发队列(DEV-PROMPTS-40 §5.4、#356)。
///
/// - 同一个会话按顺序发:先点的先到,和你在输入框里的顺序一致;
/// - 带同一个 random_id 重发 —— 服务端按它去重,网络抖一下重试不会发出两条;
/// - 附件先传完、等转码好(视频)再发消息,服务端只收 ready 的附件;
/// - 纯文字和附件已经传完的待发消息落本地:杀掉 App 再打开会接着发。
///   还没传完的附件不落(手机上选图的临时文件可能已经被系统清掉),重启后标成失败让人重选。
class Outbox {
  Outbox(this.store);

  final ChatStore store;

  static String keyFor(int uid) => 'chat_outbox_v1_$uid';

  final Map<int, List<_OutItem>> _queues = {};
  final Set<int> _running = {};
  final Map<String, _OutItem> _failed = {};
  final Map<int, Completer<Map<String, dynamic>>> _waitingMedia = {};

  /// 发送中消息的本地图片预览:randomId → 每个附件的字节
  final Map<String, List<Uint8List?>> _previews = {};

  static const _singleMax = 8 * 1024 * 1024;

  Uint8List? previewFor(String? randomId, int index) {
    if (randomId == null) return null;
    final list = _previews[randomId];
    if (list == null || index >= list.length) return null;
    return list[index];
  }

  // ---------------- 对外:发 ----------------

  Future<void> sendText(int chatId, String text,
      {List<MsgEntity> entities = const [], int? replyTo, bool silent = false, bool noPreview = false}) {
    return _enqueue(chatId, {
      'kind': 'text',
      'text': text,
      'entities': [for (final e in entities) e.toJson()],
      if (replyTo != null) 'reply_to_seq': replyTo,
      'silent': silent,
      'no_preview': noPreview,
    });
  }

  /// 图片 / 视频 / 文件 / GIF。多张图、视频一起选时发成相册(共享 grouped_id,≤ 10 个一组)。
  Future<void> sendAttachments(int chatId, List<LocalAttachment> files,
      {String caption = '',
      List<MsgEntity> entities = const [],
      int? replyTo,
      bool silent = false,
      bool asAlbum = true}) async {
    if (files.isEmpty) return;
    final albumable = asAlbum &&
        files.length > 1 &&
        files.every((f) => f.kind == 'photo' || f.kind == 'video');
    for (var i = 0; i < files.length; i += albumable ? 10 : 1) {
      final group = files.sublist(i, min(files.length, i + (albumable ? 10 : 1)));
      final gid = albumable && group.length > 1 ? ChatApi.randomId() : null;
      for (var k = 0; k < group.length; k++) {
        final f = group[k];
        // 说明文字只挂在第一条上(和 Telegram 一样)
        final first = i == 0 && k == 0;
        await _enqueue(
            chatId,
            {
              'kind': f.kind,
              'text': first ? caption : '',
              'entities': first ? [for (final e in entities) e.toJson()] : const [],
              if (replyTo != null && first) 'reply_to_seq': replyTo,
              if (gid != null) 'grouped_id': gid,
              'silent': silent,
            },
            attachments: [f]);
      }
    }
  }

  Future<void> sendVoice(int chatId, LocalAttachment voice, {int? replyTo}) =>
      _enqueue(chatId, {'kind': 'voice', if (replyTo != null) 'reply_to_seq': replyTo},
          attachments: [voice]);

  Future<void> sendStructured(int chatId, String kind, Map<String, dynamic> payload,
          {int? replyTo, bool silent = false}) =>
      _enqueue(chatId, {
        'kind': kind,
        ...payload,
        if (replyTo != null) 'reply_to_seq': replyTo,
        'silent': silent,
      });

  // ---------------- 失败的:重发 / 丢掉 ----------------

  Future<void> retry(String randomId) async {
    final it = _failed.remove(randomId);
    if (it == null) return;
    it.attempts = 0;
    _setLocal(it, LocalStatus.sending, error: '');
    _queues.putIfAbsent(it.chatId, () => []).add(it);
    await _persist();
    _pump(it.chatId);
  }

  Future<void> discard(String randomId) async {
    final it = _failed.remove(randomId);
    _previews.remove(randomId);
    if (it != null) {
      store.timelines[it.chatId]?.messages
          .removeWhere((m) => m.isLocal && m.randomId == randomId);
      store.notifyListeners();
    }
    await _persist();
  }

  // ---------------- 转码完成的用户事件 ----------------

  void onMediaEvent(Map<String, dynamic> d) {
    final id = (d['id'] as num?)?.toInt();
    if (id == null) return;
    final c = _waitingMedia.remove(id);
    if (c != null && !c.isCompleted) c.complete(d);
  }

  // ---------------- 内部 ----------------

  Future<void> _enqueue(int chatId, Map<String, dynamic> body,
      {List<LocalAttachment> attachments = const []}) async {
    final it = _OutItem(
        randomId: ChatApi.randomId(), chatId: chatId, body: body, attachments: attachments);
    _previews[it.randomId] = [for (final a in attachments) a.preview];
    _showLocal(it);
    _queues.putIfAbsent(chatId, () => []).add(it);
    await _persist();
    _pump(chatId);
  }

  /// 在时间线里先放一条「发送中」
  void _showLocal(_OutItem it) {
    store.rememberSent(it.randomId);
    final t = store.timeline(it.chatId);
    final replySeq = it.body['reply_to_seq'] as int?;
    final replied = replySeq == null ? null : t.bySeq(replySeq);
    t.addLocal(ChatMessage(
      chatId: it.chatId,
      seq: 0,
      kind: '${it.body['kind']}',
      sender: Sender(store.meId, '我', store.myUsername, '', false),
      text: '${it.body['text'] ?? ''}',
      entities: [
        for (final e in (it.body['entities'] as List? ?? const [])) MsgEntity.fromJson(e)
      ],
      media: [
        // 贴纸:图是公开地址,本地这条直接画出来,不用等服务端确认
        if (it.body['sticker_preview'] is Map)
          MediaInfo(
            id: ((it.body['sticker_preview'] as Map)['media_id'] as num?)?.toInt() ?? 0,
            kind: 'sticker',
            url: '${(it.body['sticker_preview'] as Map)['url'] ?? ''}',
            w: 512,
            h: 512,
          ),
        for (final a in it.attachments)
          MediaInfo(
              id: 0,
              kind: a.kind,
              w: a.w,
              h: a.h,
              size: a.size,
              name: a.name,
              durationMs: a.durationMs,
              waveform: a.waveform)
      ],
      replyTo: replied == null
          ? null
          : ReplyPreview(replied.seq, store.nameOf(replied.sender), replied.text, replied.kind, false),
      replyToSeq: replySeq,
      groupedId: it.body['grouped_id'] as String?,
      location: it.body['location'] is Map ? (it.body['location'] as Map).cast() : null,
      contact: it.body['contact'] is Map ? (it.body['contact'] as Map).cast() : null,
      silent: it.body['silent'] == true,
      createdAt: DateTime.now(),
      randomId: it.randomId,
      localStatus: LocalStatus.sending,
      progress: it.attachments.isEmpty ? null : 0,
    ));
    store.notifyListeners();
  }

  void _setLocal(_OutItem it, LocalStatus s, {double? progress, String? error}) {
    final t = store.timelines[it.chatId];
    if (t == null) return;
    final i = t.messages.indexWhere((m) => m.isLocal && m.randomId == it.randomId);
    if (i < 0) return;
    t.messages[i] =
        t.messages[i].copyWith(localStatus: s, progress: progress, localError: error);
    store.notifyListeners();
  }

  void _pump(int chatId) {
    if (_running.contains(chatId)) return;
    _running.add(chatId);
    unawaited(_drain(chatId).whenComplete(() => _running.remove(chatId)));
  }

  Future<void> _drain(int chatId) async {
    final q = _queues[chatId];
    while (q != null && q.isNotEmpty) {
      final it = q.first;
      final ok = await _process(it);
      q.removeAt(0);
      if (!ok) {
        _failed[it.randomId] = it;
      }
      await _persist();
    }
  }

  /// 传附件 → 等转码 → 发。成功返回 true;失败标红返回 false。
  Future<bool> _process(_OutItem it) async {
    while (true) {
      try {
        if (!store.started) return false;
        while (it.needsUpload) {
          final idx = it.uploaded.length;
          final media = await _upload(it, idx);
          it.uploaded.add((media['id'] as num).toInt());
        }
        final msg = await store.api.send(it.chatId, {
          ...it.body,
          'random_id': it.randomId,
          if (it.uploaded.isNotEmpty) 'media_ids': it.uploaded,
        });
        _previews.remove(it.randomId);
        final t = store.timeline(it.chatId);
        t.messages.removeWhere((m) => m.isLocal && m.randomId == it.randomId);
        if (t.loaded && !t.hasNewer) t.upsert(msg);
        final c = store.chats[it.chatId];
        if (c != null) {
          if (msg.seq > c.lastSeq) c.lastSeq = msg.seq;
          if (c.lastMessage == null || msg.seq >= c.lastMessage!.seq) c.lastMessage = msg;
          if (msg.seq > c.my.lastReadSeq) c.my.lastReadSeq = msg.seq;
          c.my.draft = null;
        }
        store.notifyListeners();
        return true;
      } on ApiException catch (e) {
        // 慢速模式(「慢速模式:N 秒后才能再发」):等得不久就排着,到点自动发,并告诉他为什么还没发;
        // 要等很久(1 小时档)就直接标红,别让一条消息挂在那里转一个小时
        final slow = e.statusCode == 429 ? RegExp(r'(\d+) 秒').firstMatch(e.message) : null;
        if (slow != null) {
          final secs = int.parse(slow.group(1)!);
          if (secs > 60) {
            _setLocal(it, LocalStatus.failed, error: e.message);
            return false;
          }
          store.notices.add('${e.message},到时间会自动发出');
          await Future<void>.delayed(Duration(seconds: secs + 1));
          continue;
        }
        final retriable = e.isNetwork || e.statusCode >= 500 || e.statusCode == 429 ||
            (e.statusCode == 409 && e.message.contains('处理中'));
        it.attempts++;
        if (!retriable || it.attempts >= 5) {
          _setLocal(it, LocalStatus.failed, error: e.message);
          return false;
        }
        await Future<void>.delayed(Duration(seconds: min(30, 1 << it.attempts)));
      } catch (e) {
        _setLocal(it, LocalStatus.failed, error: '$e');
        return false;
      }
    }
  }

  Future<Map<String, dynamic>> _upload(_OutItem it, int idx) async {
    final a = it.attachments[idx];
    void progress(double p) {
      final whole = (idx + p) / it.attachments.length;
      _setLocal(it, LocalStatus.sending, progress: whole.clamp(0, 1).toDouble());
    }

    progress(0);
    Map<String, dynamic> media;
    if (a.size <= _singleMax) {
      final bytes = a.preview ?? await a.file.readAsBytes();
      media = await store.client.uploadMediaBytes(bytes, a.name, kind: a.kind);
      progress(1);
    } else {
      final up = await store.api.createUpload(a.size, a.name, a.kind);
      final id = '${up['id']}';
      final chunk = (up['chunk_size'] as num?)?.toInt() ?? 4 * 1024 * 1024;
      final total = (a.size + chunk - 1) ~/ chunk;
      final have = {for (final x in (up['received'] as List? ?? const [])) (x as num).toInt()};
      for (var n = 0; n < total; n++) {
        if (have.contains(n)) continue;
        final start = n * chunk;
        final end = min(a.size, start + chunk);
        final bytes = await _readRange(a.file, start, end);
        await store.client.putMediaChunk(id, n, bytes);
        progress((n + 1) / total);
      }
      media = await store.api.completeUpload(id, a.kind);
    }
    if (media['status'] == 'processing') {
      media = await _waitReady((media['id'] as num).toInt());
    }
    if (media['status'] == 'failed') {
      throw ApiException(422, '附件处理失败:${media['error'] ?? '格式不支持'}');
    }
    return media;
  }

  Future<Uint8List> _readRange(XFile f, int start, int end) async {
    final out = BytesBuilder(copy: false);
    await for (final part in f.openRead(start, end)) {
      out.add(part);
    }
    return out.takeBytes();
  }

  /// 等转码:用户事件 `media` 到了就结束;事件丢了也有每 5 秒一次的查询兜底,最多等 10 分钟
  Future<Map<String, dynamic>> _waitReady(int mediaId) async {
    final c = _waitingMedia.putIfAbsent(mediaId, Completer.new);
    final deadline = DateTime.now().add(const Duration(minutes: 10));
    while (!c.isCompleted && DateTime.now().isBefore(deadline)) {
      try {
        final m = await store.api.media(mediaId);
        if (m['status'] != 'processing') {
          _waitingMedia.remove(mediaId);
          return m;
        }
      } catch (_) {}
      await Future.any([c.future, Future<void>.delayed(const Duration(seconds: 5))]);
    }
    if (c.isCompleted) return c.future;
    _waitingMedia.remove(mediaId);
    throw ApiException(504, '视频处理太久了,稍后重发试试');
  }

  // ---------------- 落本地 ----------------

  Future<void> _persist() async {
    if (!store.started || store.meId == 0) return;
    final items = <Map<String, dynamic>>[];
    for (final q in _queues.values) {
      for (final it in q) {
        if (!it.needsUpload) items.add(it.toJson());
      }
    }
    for (final it in _failed.values) {
      if (!it.needsUpload) items.add({...it.toJson(), 'failed': true});
    }
    try {
      final sp = await SharedPreferences.getInstance();
      if (items.isEmpty) {
        await sp.remove(keyFor(store.meId));
      } else {
        await sp.setString(keyFor(store.meId), jsonEncode(items));
      }
    } catch (_) {}
  }

  /// 冷启动:把上次没发出去的接着发(失败的保持失败,等人点重发)。
  Future<void> restore() async {
    try {
      final sp = await SharedPreferences.getInstance();
      final raw = sp.getString(keyFor(store.meId));
      if (raw == null) return;
      for (final x in jsonDecode(raw) as List) {
        final m = (x as Map).cast<String, dynamic>();
        final it = _OutItem(
          randomId: '${m['random_id']}',
          chatId: (m['chat_id'] as num).toInt(),
          body: (m['body'] as Map).cast<String, dynamic>(),
          uploaded: [for (final i in (m['uploaded'] as List? ?? const [])) (i as num).toInt()],
        );
        _showLocal(it);
        if (m['failed'] == true) {
          _failed[it.randomId] = it;
          _setLocal(it, LocalStatus.failed, error: '没发出去,点一下重发');
        } else {
          _queues.putIfAbsent(it.chatId, () => []).add(it);
        }
      }
      for (final chatId in [..._queues.keys]) {
        _pump(chatId);
      }
    } catch (e) {
      debugPrint('恢复待发消息失败:$e');
    }
  }
}
