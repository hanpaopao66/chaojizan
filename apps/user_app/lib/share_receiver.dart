import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart' show XFile;

import 'chat/outbox.dart';
import 'chat/pages/forward_page.dart';
import 'chat/store.dart';
import 'session.dart';

/// 从系统分享面板收进来的内容(Android 的 ACTION_SEND)。
class IncomingShare {
  const IncomingShare({this.text = '', this.files = const []});

  final String text;

  /// 原生已经拷进应用 cache 的文件路径。**必须在原生侧先拷出来**:
  /// 分享方给的是 content:// URI,读取授权只在这个 intent 还活着的时候有效
  final List<String> files;

  /// 原生 map → 对象。公开给测试:解析规则(只有字、只有图、空分享)
  /// 不该靠真机试
  static IncomingShare? fromMap(Object? raw) {
    if (raw is! Map) return null;
    final text = (raw['text'] as String?) ?? '';
    final files = (raw['files'] as List?)
            ?.whereType<String>()
            .where((f) => f.isNotEmpty)
            .toList() ??
        const <String>[];
    if (text.trim().isEmpty && files.isEmpty) return null;
    return IncomingShare(text: text, files: files);
  }
}

/// 系统分享接收器。
///
/// ## 为什么要有它
///
/// 系统分享面板只列**声明过接收分享**的 App(Android 的 ACTION_SEND
/// intent-filter,见 AndroidManifest.xml)。不声明的话,不管有没有聊天功能,
/// 超级赞都不会出现在分享面板里。
///
/// ## 两条路
///
/// 冷启动(分享时 App 没开)的原生 intent 等 Flutter 起来后由这里主动取;
/// 热启动(App 已在后台/前台)的原生侧直接推过来。两条路都落在 [pending]
/// 上,UI 只监听它 —— 发到哪个会话由用户选,收到就发是不礼貌的。
class ShareReceiver {
  ShareReceiver._();

  static final ShareReceiver instance = ShareReceiver._();

  static const _channel = MethodChannel('com.chaojizan.user/share');

  /// 待处理的分享;null = 没有
  final ValueNotifier<IncomingShare?> pending = ValueNotifier(null);

  /// 在 App 外壳起来时调一次。非 Android 平台是空操作
  Future<void> init() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    _channel.setMethodCallHandler((call) async {
      if (call.method == 'onShare') {
        final share = IncomingShare.fromMap(call.arguments);
        if (share != null) pending.value = share;
      }
    });
    try {
      final initial = await _channel.invokeMethod<Object?>('takeInitialShare');
      final share = IncomingShare.fromMap(initial);
      if (share != null) pending.value = share;
    } catch (_) {
      // 没有原生实现(桌面/网页/老包)就当作没有分享,不打扰
    }
  }
}

/// 把收进来的分享发到用户选的会话。返回发给了几个会话;取消返回 0。
///
/// 和 [shareCardToChat] 同一套「选会话 → 发」,只是内容来自系统分享:
/// 文字直接发;图片带说明当附件发(说明挂第一条,和输入栏那条口径一致)。
Future<int> sendIncomingShare(BuildContext context, IncomingShare share) async {
  if (!await ensureLoggedIn(context)) return 0;
  if (!context.mounted) return 0;
  final store = ChatStore.instance;
  if (!store.started) {
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('消息模块还没准备好,稍后再试')));
    return 0;
  }
  final targets = await pickForwardTargets(context, title: '分享到');
  if (targets == null || targets.isEmpty) return 0;
  final text = share.text.trim();
  final attachments = await _attachmentsFrom(share.files);
  for (final chatId in targets) {
    if (attachments.isEmpty) {
      await store.outbox.sendText(chatId, text);
    } else {
      await store.outbox.sendAttachments(chatId, attachments, caption: text);
    }
  }
  if (context.mounted) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content:
            Text(targets.length > 1 ? '已分享到 ${targets.length} 个会话' : '已分享')));
  }
  return targets.length;
}

/// 原生拷出来的文件 → 发送附件。图片读字节算尺寸、当发送中的预览;
/// 读不出来(非图片/损坏)就按文件发,不挡发送
Future<List<LocalAttachment>> _attachmentsFrom(List<String> paths) async {
  final out = <LocalAttachment>[];
  for (final path in paths) {
    final f = XFile(path);
    final size = await f.length();
    // 和输入栏同一条上限:超过 20MB 不读进内存
    final bytes = size <= 20 * 1024 * 1024 ? await f.readAsBytes() : null;
    var w = 0, h = 0;
    if (bytes != null) {
      try {
        final img = await decodeImageFromList(bytes);
        w = img.width;
        h = img.height;
      } catch (_) {}
    }
    final name = path.split(RegExp(r'[\\/]')).last;
    final isImage = w > 0 ||
        RegExp(r'\.(jpg|jpeg|png|webp|gif|heic)$').hasMatch(name.toLowerCase());
    out.add(LocalAttachment(
      file: f,
      kind: isImage ? 'photo' : 'file',
      name: name,
      size: size,
      w: w,
      h: h,
      preview: isImage ? bytes : null,
    ));
  }
  return out;
}
