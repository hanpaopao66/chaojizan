import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../channel_config.dart';
import '../../chat/pages/forward_page.dart';
import '../../forum/nav.dart' as forum;
import '../../session.dart';
import '../models.dart';
import '../nav.dart';

/// 分享视频:发到消息、发到动态、复制链接、系统分享。
/// 分享数按人算一次(服务端去重),这里每种方式都报一下渠道。
///
/// 发到消息走 §5.9 的卡片消息(不再是「标题 + 链接」那条纯文本):客户端只报
/// `{type:'video', id:vid}`,标题封面由服务端查出来存快照 —— 和音乐、论坛同一条路。
Future<void> shareVideo(BuildContext context, VideoCard card) async {
  final link = 'https://chaojizan.cc/v/${card.vid}';
  final toForum = ChannelConfig.current.contains('forum');
  final pick = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(title: Text(card.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
        const Divider(height: 1),
        ListTile(leading: const Icon(Icons.send_outlined), title: const Text('发到消息'), onTap: () => Navigator.pop(ctx, 'chat')),
        if (toForum)
          ListTile(
              leading: const Icon(Icons.forum_outlined),
              title: const Text('发到动态'),
              onTap: () => Navigator.pop(ctx, 'forum')),
        ListTile(leading: const Icon(Icons.link), title: const Text('复制链接'), onTap: () => Navigator.pop(ctx, 'link')),
        ListTile(leading: const Icon(Icons.ios_share), title: const Text('更多'), onTap: () => Navigator.pop(ctx, 'other')),
      ]),
    ),
  );
  if (pick == null || !context.mounted) return;
  switch (pick) {
    case 'chat':
      if (!await ensureLoggedIn(context)) return;
      if (!context.mounted) return;
      // 一个会话都没选(取消了)就不算一次分享
      if (await shareCardToChat(context, type: 'video', id: card.vid) == 0) return;
    case 'forum':
      final posted = await forum.openCompose(context, card: {'type': 'video', 'id': card.vid});
      if (posted == null) return;
    case 'link':
      await Clipboard.setData(ClipboardData(text: link));
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('链接已复制')));
    case 'other':
      await SharePlus.instance.share(ShareParams(text: '${card.title} $link'));
  }
  if (rootApi.isLoggedIn) {
    try {
      final r = await videoApi.share(card.vid, pick);
      card.shares = vInt(r['shares']);
    } catch (_) {}
  }
}
