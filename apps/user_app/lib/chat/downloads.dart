import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';

/// 下载过的东西 ——「搜索 → 下载内容」那一格的数据(对齐 Telegram 的「下载内容」)。
///
/// ## 为什么只在本机
///
/// 这是**这台设备上**的下载记录,不上传、不同步。服务端不知道谁把哪个文件存进了
/// 自己手机,也不该知道 —— 把它做成服务端的表,等于凭空多一份「谁下载了什么」的档案,
/// 而这件事对用户没有任何好处。换手机就没有,这是刻意的。
///
/// 存在 SharedPreferences 里的一串 JSON,最多留 [_max] 条,新的挤掉最旧的。
/// 记的是**下载这件事**(什么文件、多大、从哪个会话来、什么时候、存到哪),
/// 不复制文件内容。
class Downloads extends ChangeNotifier {
  Downloads._();

  static final Downloads instance = Downloads._();

  static const _key = 'sz_chat_downloads';

  /// 留多少条。手机上这份清单是给人翻的,不是归档 —— 太长了既占空间也没人看
  static const _max = 300;

  final List<DownloadItem> _items = [];
  bool _loaded = false;

  /// 新的在前
  List<DownloadItem> get items => List.unmodifiable(_items);

  bool get loaded => _loaded;

  Future<void> load() async {
    if (_loaded) return;
    _loaded = true;
    try {
      final sp = await SharedPreferences.getInstance();
      final raw = sp.getString(_key);
      if (raw == null || raw.isEmpty) return;
      final list = jsonDecode(raw);
      if (list is! List) return;
      _items
        ..clear()
        ..addAll(list.whereType<Map>().map((m) => DownloadItem.fromJson(m.cast())));
      notifyListeners();
    } catch (_) {
      // 读坏了当没有。下载记录丢了不影响任何别的事,不值得为它弹错
    }
  }

  /// 下完一个就记一条。同一个文件再下一次只更新时间和路径,不重复占一行。
  Future<void> record(MediaInfo media, {String path = '', int? chatId, String? chatTitle}) async {
    await load();
    _items.removeWhere((d) => d.mediaId == media.id);
    _items.insert(
        0,
        DownloadItem(
          mediaId: media.id,
          name: media.name.isNotEmpty ? media.name : _fallbackName(media),
          mime: media.mime,
          size: media.size,
          kind: media.kind,
          path: path,
          chatId: chatId ?? 0,
          chatTitle: chatTitle ?? '',
          at: DateTime.now(),
        ));
    if (_items.length > _max) _items.removeRange(_max, _items.length);
    notifyListeners();
    await _save();
  }

  /// 从清单里去掉一条,返回它(调用方要连本机文件一起删时拿它的 path)。
  ///
  /// **只管清单,不碰文件** —— 删文件是 media_save.deleteDownloaded 的事。
  /// 两件事分开是因为它们的后果不一样:清单删了还能再下一次,文件删了就没了。
  Future<DownloadItem?> remove(int mediaId) async {
    await load();
    final i = _items.indexWhere((d) => d.mediaId == mediaId);
    if (i < 0) return null;
    final item = _items.removeAt(i);
    notifyListeners();
    await _save();
    return item;
  }

  /// 清空清单,返回被清掉的那些(同上:不碰文件)。
  Future<List<DownloadItem>> clear() async {
    await load();
    final gone = List<DownloadItem>.from(_items);
    _items.clear();
    notifyListeners();
    await _save();
    return gone;
  }

  @visibleForTesting
  void resetForTest() {
    _items.clear();
    _loaded = false;
  }

  Future<void> _save() async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setString(_key, jsonEncode([for (final d in _items) d.toJson()]));
    } catch (_) {
      // 写失败就下次再说:清单本身是个方便,不是账
    }
  }

  static String _fallbackName(MediaInfo m) => switch (m.kind) {
        'photo' => '图片',
        'video' => '视频',
        'gif' => 'GIF',
        'voice' => '语音',
        'video_note' => '视频消息',
        _ => '文件',
      };
}

class DownloadItem {
  const DownloadItem({
    required this.mediaId,
    required this.name,
    required this.mime,
    required this.size,
    required this.kind,
    required this.path,
    required this.chatId,
    required this.chatTitle,
    required this.at,
  });

  factory DownloadItem.fromJson(Map<String, dynamic> j) => DownloadItem(
        mediaId: (j['media_id'] as num?)?.toInt() ?? 0,
        name: '${j['name'] ?? ''}',
        mime: '${j['mime'] ?? ''}',
        size: (j['size'] as num?)?.toInt() ?? 0,
        kind: '${j['kind'] ?? 'file'}',
        path: '${j['path'] ?? ''}',
        chatId: (j['chat_id'] as num?)?.toInt() ?? 0,
        chatTitle: '${j['chat_title'] ?? ''}',
        at: DateTime.tryParse('${j['at'] ?? ''}') ?? DateTime.fromMillisecondsSinceEpoch(0),
      );

  final int mediaId;
  final String name;
  final String mime;
  final int size;
  final String kind;

  /// 本机文件路径。网页版是空串 —— 文件在浏览器的下载目录里,App 碰不到
  final String path;
  final int chatId;
  final String chatTitle;
  final DateTime at;

  bool get onThisDevice => path.isNotEmpty;

  Map<String, dynamic> toJson() => {
        'media_id': mediaId,
        'name': name,
        'mime': mime,
        'size': size,
        'kind': kind,
        'path': path,
        'chat_id': chatId,
        'chat_title': chatTitle,
        'at': at.toIso8601String(),
      };
}
