import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../messages_page.dart';
import '../session.dart';
import 'chat_page.dart';
import 'models.dart';
import 'order_chats_page.dart';
import 'pages/chat_admin.dart' show pickContactsMulti;
import 'pages/chat_settings_page.dart';
import 'pages/contacts_page.dart';
import 'pages/folders_page.dart';
import 'pages/new_chat_page.dart';
import 'pages/pickers.dart';
import 'pages/search_page.dart';
import 'store.dart';
import 'ui/avatar.dart';
import 'ui/format.dart';

/// 底部「消息」tab 的角标:有未读的会话数。**免打扰的会话不计** ——
/// 静音的群不该在底栏上一直喊你(Telegram 也是这么算的)。
/// 会话列表每次拉到数据、每收到一个事件都会更新它
final ValueNotifier<int> chatUnreadBadge = ValueNotifier<int>(0);

/// 「消息」tab(DEV-PROMPTS-40 #348)。
///
/// 顶部固定行(D24):「通知」是原来右上角铃铛里的消息中心,「订单消息」是进行中订单里
/// 和商家、骑手的对话;有归档的会话时再多一行「归档」。下面是聊天会话:
/// 置顶的在前,其余按最后一条消息的时间。
class ChatTab extends StatefulWidget {
  const ChatTab({super.key, required this.api});

  final ApiClient api;

  @override
  State<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends State<ChatTab> {
  /// 有新公告(和原来铃铛红点同一个判据:最新公告 id 比本地看过的新)
  bool _noticeUnread = false;

  /// 选中的分组;null = 全部
  int _folder = -1;

  ChatStore get store => ChatStore.instance;

  @override
  void initState() {
    super.initState();
    authTick.addListener(_onAuth);
    store.addListener(_onStore);
    _refreshNotice();
  }

  @override
  void dispose() {
    authTick.removeListener(_onAuth);
    store.removeListener(_onStore);
    super.dispose();
  }

  void _onAuth() {
    if (mounted) setState(() {});
  }

  void _onStore() {
    if (mounted) setState(() {});
  }

  Future<void> _refreshNotice() async {
    final v = await MessageCenterPage.hasUnread(widget.api);
    if (mounted && v != _noticeUnread) setState(() => _noticeUnread = v);
  }

  Future<void> _refresh() async {
    await Future.wait([_refreshNotice(), if (store.started) store.refresh()]);
  }

  Future<void> _openNotice() async {
    setState(() => _noticeUnread = false); // 打开即已读(和原铃铛一样)
    await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => MessageCenterPage(api: widget.api)));
  }

  Future<void> _openOrderChats() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => OrderChatsPage(api: widget.api)));
  }

  Future<void> _compose() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.group_add_outlined), title: const Text('新建群组'), onTap: () => Navigator.pop(ctx, 'group')),
          ListTile(leading: const Icon(Icons.campaign_outlined), title: const Text('新建频道'), onTap: () => Navigator.pop(ctx, 'channel')),
          ListTile(leading: const Icon(Icons.person_add_alt_1_outlined), title: const Text('添加联系人'), onTap: () => Navigator.pop(ctx, 'add')),
          ListTile(leading: const Icon(Icons.contacts_outlined), title: const Text('联系人'), onTap: () => Navigator.pop(ctx, 'contacts')),
          ListTile(leading: const Icon(Icons.bookmark_outline), title: const Text('收藏夹'), onTap: () => Navigator.pop(ctx, 'saved')),
          ListTile(leading: const Icon(Icons.folder_outlined), title: const Text('会话分组'), onTap: () => Navigator.pop(ctx, 'folders')),
          ListTile(leading: const Icon(Icons.settings_outlined), title: const Text('消息设置'), onTap: () => Navigator.pop(ctx, 'settings')),
        ]),
      ),
    );
    if (!mounted || pick == null) return;
    switch (pick) {
      case 'group':
        final ids = await pickContactsMulti(context, title: '选择群成员');
        if (ids == null || !mounted) return;
        await Navigator.of(context).push(MaterialPageRoute<void>(
            builder: (_) => NewChatPage(type: 'group', memberIds: ids)));
      case 'channel':
        await Navigator.of(context)
            .push(MaterialPageRoute<void>(builder: (_) => const NewChatPage(type: 'channel')));
      case 'add':
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const AddContactPage()));
      case 'contacts':
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ContactsPage()));
      case 'saved':
        try {
          final c = await store.openSaved();
          if (mounted) await openChat(context, c.id);
        } on ApiException catch (e) {
          if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
        }
      case 'folders':
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const FoldersPage()));
      case 'settings':
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ChatSettingsPage()));
    }
  }

  String _title() {
    if (!store.started) return '消息';
    return switch (store.conn) {
      ConnState.online => '消息',
      ConnState.connecting => '连接中…',
      ConnState.offline => '等待网络…',
    };
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final loggedIn = widget.api.isLoggedIn;
    final folders = store.folders;
    ChatFolder? folder;
    if (_folder >= 0 && _folder < folders.length) folder = folders[_folder];
    final chats = loggedIn ? store.sortedChats(folder: folder) : const <ChatInfo>[];
    final archived = loggedIn && folder == null ? store.sortedChats(archived: true) : const <ChatInfo>[];
    final archivedUnread = archived.fold<int>(0, (n, c) => n + (c.my.muted ? 0 : store.unreadOf(c)));
    return Column(children: [
      AppBar(
        title: Text(_title()),
        actions: [
          IconButton(
            tooltip: '搜索',
            icon: const Icon(Icons.search),
            onPressed: () async {
              if (!await ensureLoggedIn(context)) return;
              if (context.mounted) {
                await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ChatSearchPage()));
              }
            },
          ),
          IconButton(tooltip: '新建', icon: const Icon(Icons.edit_square), onPressed: _compose),
        ],
      ),
      if (loggedIn && folders.isNotEmpty)
        SizedBox(
          height: 44,
          child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
            _FolderChip(label: '全部', selected: _folder < 0, onTap: () => setState(() => _folder = -1)),
            for (var i = 0; i < folders.length; i++)
              _FolderChip(
                label: folders[i].title,
                badge: store.sortedChats(folder: folders[i]).where((c) => !c.my.muted && store.unreadOf(c) > 0).length,
                selected: _folder == i,
                onTap: () => setState(() => _folder = i),
              ),
          ]),
        ),
      Expanded(
        child: RefreshIndicator(
          onRefresh: _refresh,
          child: ListView.builder(
            // 没登录、或者列表为空时,分隔线下面多一格放提示(登录引导 / 转圈 / 空状态)
            itemCount: (folder == null ? 2 : 0) + (archived.isNotEmpty ? 1 : 0) + 1 + chats.length +
                (chats.isEmpty ? 1 : 0),
            itemBuilder: (context, i) {
              var k = i;
              if (folder == null) {
                if (k == 0) {
                  return _PinnedRow(
                      icon: Icons.campaign_outlined, title: '通知', subtitle: '平台公告和订单状态', dot: _noticeUnread, onTap: _openNotice);
                }
                if (k == 1) {
                  return _PinnedRow(
                      icon: Icons.receipt_long_outlined, title: '订单消息', subtitle: '和商家、骑手的对话', onTap: _openOrderChats);
                }
                k -= 2;
              }
              if (archived.isNotEmpty) {
                if (k == 0) {
                  return _PinnedRow(
                    icon: Icons.archive_outlined,
                    title: '归档',
                    subtitle: archived.take(3).map((c) => c.title).join('、'),
                    badge: archivedUnread,
                    onTap: () => Navigator.of(context)
                        .push(MaterialPageRoute<void>(builder: (_) => const ArchivedPage())),
                  );
                }
                k -= 1;
              }
              if (k == 0) return Divider(height: 1, color: sz.line);
              k -= 1;
              if (!loggedIn) {
                return Padding(
                  padding: const EdgeInsets.only(top: 48),
                  child: SzEmpty(
                    text: '登录后和朋友聊天、建群、订阅频道',
                    actionLabel: '登录 / 注册',
                    onAction: () => ensureLoggedIn(context),
                  ),
                );
              }
              if (chats.isEmpty) {
                if (!store.loaded && store.loadError == null) {
                  return const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()));
                }
                if (store.loadError != null && store.chats.isEmpty) {
                  return SzError(error: store.loadError, onRetry: store.refresh);
                }
                return Padding(
                  padding: const EdgeInsets.only(top: 40),
                  child: SzEmpty(
                    text: folder == null ? '还没有聊天\n加个联系人,或者建一个群' : '这个分组里还没有会话',
                    actionLabel: folder == null ? '添加联系人' : null,
                    onAction: folder == null
                        ? () => Navigator.of(context)
                            .push(MaterialPageRoute<void>(builder: (_) => const AddContactPage()))
                        : null,
                  ),
                );
              }
              return DialogRow(chat: chats[k]);
            },
          ),
        ),
      ),
    ]);
  }
}

class _FolderChip extends StatelessWidget {
  const _FolderChip({required this.label, required this.selected, required this.onTap, this.badge = 0});

  final String label;
  final bool selected;
  final VoidCallback onTap;
  final int badge;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
      child: ChoiceChip(
        label: Text(badge > 0 ? '$label $badge' : label),
        selected: selected,
        onSelected: (_) => onTap(),
        visualDensity: VisualDensity.compact,
      ),
    );
  }
}

/// 列表顶部固定的一行:圆形图标 + 标题 + 一句说明 + 红点 / 数字。
class _PinnedRow extends StatelessWidget {
  const _PinnedRow({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
    this.dot = false,
    this.badge = 0,
  });

  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
  final bool dot;
  final int badge;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ListTile(
      leading: Badge(
        isLabelVisible: dot,
        smallSize: 9,
        child: CircleAvatar(
          radius: 24,
          backgroundColor: sz.claySoft,
          child: Icon(icon, color: sz.clay),
        ),
      ),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(subtitle,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      trailing: badge > 0 ? Badge(label: Text(badgeText(badge))) : Icon(Icons.chevron_right, color: sz.inkFaint),
      onTap: onTap,
    );
  }
}

/// 一行会话。
class DialogRow extends StatelessWidget {
  const DialogRow({super.key, required this.chat});

  final ChatInfo chat;

  ChatStore get store => ChatStore.instance;

  Future<void> _menu(BuildContext context) async {
    final c = chat;
    final unread = store.unreadOf(c) > 0;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(title: Text(c.title, style: const TextStyle(fontWeight: FontWeight.w600))),
          const Divider(height: 1),
          ListTile(
              leading: Icon(c.my.pinnedRank != null ? Icons.push_pin : Icons.push_pin_outlined),
              title: Text(c.my.pinnedRank != null ? '取消置顶' : '置顶'),
              onTap: () => Navigator.pop(ctx, 'pin')),
          if (!c.isSaved)
            ListTile(
                leading: Icon(c.my.muted ? Icons.notifications_outlined : Icons.notifications_off_outlined),
                title: Text(c.my.muted ? '取消免打扰' : '免打扰'),
                onTap: () => Navigator.pop(ctx, 'mute')),
          ListTile(
              leading: Icon(c.my.archived ? Icons.unarchive_outlined : Icons.archive_outlined),
              title: Text(c.my.archived ? '移出归档' : '归档'),
              onTap: () => Navigator.pop(ctx, 'archive')),
          ListTile(
              leading: Icon(unread ? Icons.mark_chat_read_outlined : Icons.mark_chat_unread_outlined),
              title: Text(unread ? '标为已读' : '标为未读'),
              onTap: () => Navigator.pop(ctx, 'read')),
          ListTile(
              leading: Icon(Icons.delete_outline, color: Theme.of(ctx).sz.danger),
              title: Text(c.isPrivate || c.isSaved ? '删除聊天' : (c.my.role == 'owner' ? '解散' : '退出'),
                  style: TextStyle(color: Theme.of(ctx).sz.danger)),
              onTap: () => Navigator.pop(ctx, 'delete')),
        ]),
      ),
    );
    if (pick == null || !context.mounted) return;
    try {
      switch (pick) {
        case 'pin':
          final n = await store.api.patchDialog(c.id, {'pinned': c.my.pinnedRank == null});
          store.putChat(n);
        case 'mute':
          final until = c.my.muted ? null : await pickMuteUntil(context);
          if (!c.my.muted && until == null) return;
          final n = await store.api.patchDialog(c.id, {'muted_until': until?.toUtc().toIso8601String()});
          store.putChat(n);
        case 'archive':
          final n = await store.api.patchDialog(c.id, {'archived': !c.my.archived});
          store.putChat(n);
        case 'read':
          if (unread) {
            store.markRead(c.id);
            await store.api.read(c.id, c.lastSeq);
          } else {
            final n = await store.api.patchDialog(c.id, {'marked_unread': true});
            store.putChat(n);
          }
        case 'delete':
          if (context.mounted) await leaveOrDelete(context, c);
      }
    } on ApiException catch (e) {
      if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final c = chat;
    final last = c.lastMessage;
    final unread = store.unreadOf(c);
    final typing = store.typingLabel(c);
    final draft = '${c.my.draft?['text'] ?? ''}'.trim();
    final mineLast = last != null && last.sender?.id == store.meId && !last.asChat;
    final online = c.isPrivate && (c.peer?.lastSeen.online ?? false);
    Widget preview;
    if (typing != null) {
      preview = Text(typing, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: sz.clay));
    } else if (draft.isNotEmpty && store.viewing != c.id) {
      preview = Text.rich(
        TextSpan(children: [
          TextSpan(text: '草稿:', style: TextStyle(color: sz.danger)),
          TextSpan(text: draft.replaceAll('\n', ' ')),
        ]),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(color: sz.inkMuted),
      );
    } else if (last != null) {
      final who = last.isService || c.isPrivate || c.isChannel || c.isSaved
          ? ''
          : (mineLast ? '我: ' : '${store.nameOf(last.sender)}: ');
      final text = last.isService
          ? serviceText(last,
              actor: last.sender?.id == store.meId ? '你' : store.nameOf(last.sender, '有人'),
              meId: store.meId,
              channel: c.isChannel)
          : previewOf(last);
      preview = Text.rich(
        TextSpan(children: [
          if (who.isNotEmpty) TextSpan(text: who, style: TextStyle(color: sz.ink)),
          TextSpan(text: text),
        ]),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(color: sz.inkMuted),
      );
    } else {
      preview = Text(c.isSaved ? '转发到这里的消息只有你看得到' : '', style: TextStyle(color: sz.inkMuted));
    }
    return InkWell(
      onTap: () => openChat(context, c.id),
      onLongPress: () => _menu(context),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(children: [
          ChatAvatar(name: c.title, url: c.photo, size: 52, online: online, saved: c.isSaved),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                if (c.isGroup) Padding(padding: const EdgeInsets.only(right: 4), child: Icon(Icons.group, size: 15, color: sz.inkMuted)),
                if (c.isChannel) Padding(padding: const EdgeInsets.only(right: 4), child: Icon(Icons.campaign, size: 15, color: sz.inkMuted)),
                if (c.peer?.isBot == true)
                  Padding(padding: const EdgeInsets.only(right: 4), child: Icon(Icons.smart_toy_outlined, size: 15, color: sz.inkMuted)),
                Flexible(
                  child: Text(c.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600)),
                ),
                if (c.my.muted)
                  Padding(padding: const EdgeInsets.only(left: 4), child: Icon(Icons.notifications_off, size: 14, color: sz.inkFaint)),
                const Spacer(),
                if (mineLast && !c.isChannel && !c.isSaved)
                  Padding(
                    padding: const EdgeInsets.only(right: 3),
                    child: Icon(last.seq <= c.peerReadSeq ? Icons.done_all : Icons.done,
                        size: 15, color: last.seq <= c.peerReadSeq ? sz.clay : sz.inkMuted),
                  ),
                Text(last == null ? '' : listTime(last.createdAt),
                    style: TextStyle(fontSize: kFontNote, color: unread > 0 && !c.my.muted ? sz.clay : sz.inkMuted)),
              ]),
              const SizedBox(height: 3),
              Row(children: [
                Expanded(child: preview),
                if (c.unreadMentions > 0)
                  Padding(
                    padding: const EdgeInsets.only(left: 4),
                    child: CircleAvatar(radius: 10, backgroundColor: sz.clay,
                        child: const Text('@', style: TextStyle(color: Colors.white, fontSize: kFontNote))),
                  ),
                if (unread > 0)
                  Padding(
                    padding: const EdgeInsets.only(left: 4),
                    child: Container(
                      constraints: const BoxConstraints(minWidth: 20),
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                      decoration: BoxDecoration(
                          color: c.my.muted ? sz.inkFaint : sz.clay, borderRadius: BorderRadius.circular(10)),
                      child: Text(c.my.markedUnread && c.unread == 0 ? '' : badgeText(unread),
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Colors.white, fontSize: kFontNote, fontWeight: FontWeight.w600)),
                    ),
                  )
                else if (c.my.pinnedRank != null)
                  Padding(padding: const EdgeInsets.only(left: 4), child: Icon(Icons.push_pin, size: 15, color: sz.inkFaint)),
              ]),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// 归档的会话。
class ArchivedPage extends StatefulWidget {
  const ArchivedPage({super.key});

  @override
  State<ArchivedPage> createState() => _ArchivedPageState();
}

class _ArchivedPageState extends State<ArchivedPage> {
  ChatStore get store => ChatStore.instance;

  @override
  void initState() {
    super.initState();
    store.addListener(_on);
  }

  @override
  void dispose() {
    store.removeListener(_on);
    super.dispose();
  }

  void _on() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final list = store.sortedChats(archived: true);
    return SzPageScaffold(
      appBar: AppBar(title: const Text('归档')),
      body: list.isEmpty
          ? const Center(child: Text('没有归档的会话'))
          : ListView(children: [for (final c in list) DialogRow(chat: c)]),
    );
  }
}
