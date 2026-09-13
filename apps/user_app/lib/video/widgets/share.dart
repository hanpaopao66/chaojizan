import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/pages/forward_page.dart';
import '../../chat/store.dart';
import '../../session.dart';
import '../models.dart';
import '../nav.dart';

/// 分享视频:发到消息(选会话,发一条带链接的消息)、复制链接、系统分享。
/// 分享数按人算一次(服务端去重),这里每种方式都报一下渠道。
Future<void> shareVideo(BuildContext context, VideoCard card) async {
  final link = 'https://chaojizan.cc/v/${card.vid}';
  final pick = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(title: Text(card.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
        const Divider(height: 1),
        ListTile(leading: const Icon(Icons.send_outlined), title: const Text('发到消息'), onTap: () => Navigator.pop(ctx, 'chat')),
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
      final store = ChatStore.instance;
      if (!store.started) return;
      final targets = await pickForwardTargets(context, title: '发给');
      if (targets == null || targets.isEmpty) return;
      for (final chatId in targets) {
        await store.outbox.sendText(chatId, '${card.title}\n$link');
      }
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('已发给 ${targets.length} 个会话')));
      }
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
