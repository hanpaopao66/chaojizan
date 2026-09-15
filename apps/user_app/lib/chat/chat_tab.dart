import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../main.dart' show OrderDetailPage;
import '../qr_login/qr_login.dart' show canScanHere;
import '../qr_login/qr_scan_page.dart' show openQrScanner;
import '../session.dart';
import '../video/notify/notifications_page.dart';
import '../video/notify/notify_format.dart' show notifyHeadline, notifyTime;
import '../video/notify/notify_prefs.dart';
import 'calls/calls_page.dart';
import 'chat_page.dart';
import 'extras.dart';
import 'models.dart';
import 'pages/chat_admin.dart' show pickContactsMulti;
import 'pages/chat_settings_page.dart';
import 'pages/contacts_page.dart';
import 'pages/folders_page.dart';
import 'pages/new_chat_page.dart';
import 'pages/pickers.dart';
import 'pages/search_page.dart';
import 'pages/service_account_page.dart';
import 'store.dart';
import 'ui/avatar.dart';
import 'ui/conv_row.dart';
import 'ui/format.dart';

/// 底部「消息」tab 的角标:有未读的会话数。**免打扰的会话不计** ——
/// 静音的群不该在底栏上一直喊你(Telegram 也是这么算的)。
/// 会话列表每次拉到数据、每收到一个事件都会更新它。
/// 平台服务号、订单群、视频互动那几行另算,见 [chatExtraBadge]
final ValueNotifier<int> chatUnreadBadge = ValueNotifier<int>(0);

/// 「消息」tab(DEV-PROMPTS-40 #348,设计稿 A)。
///
/// **万物皆会话**:原来列表顶上的三条固定入口(通知 / 订单消息 / 互动消息)取消了,
/// 它们和聊天一样是会话行 —— 平台通知是带认证标的服务号「超级赞」,每一单是一个订单群
/// (你、商家、骑手),视频的回复 / @ / 赞是「视频互动」机器人。
/// 排法照 Telegram:置顶的在前(服务号、还在送的订单群、自己置顶的会话),其余按最后一条消息的时间;
/// 有归档的会话时最上面多一行「归档」。
class ChatTab extends StatefulWidget {
  const ChatTab({super.key, required this.api});

  final ApiClient api;

  @override
  State<ChatTab> createState() => _ChatTabState();
}

class _ChatTabState extends State<ChatTab> {
  /// 选中的分组;-1 = 全部
  int _folder = -1;

  ChatStore get store => ChatStore.instance;
  ChatExtras get extras => ChatExtras.instance;

  @override
  void initState() {
    super.initState();
    authTick.addListener(_onAuth);
    store.addListener(_on);
    extras.addListener(_on);
    videoNotifyUnreadKinds.addListener(_on);
    VideoNotifyPrefs.instance.addListener(_on);
    // 首页已经把服务号、订单群拉过一次(底栏角标要用);这里再刷一遍,顺带拉视频互动的最近一条
    unawaited(extras.start(widget.api).then((_) => extras.refreshBot()));
  }

  @override
  void dispose() {
    authTick.removeListener(_onAuth);
    store.removeListener(_on);
    extras.removeListener(_on);
    videoNotifyUnreadKinds.removeListener(_on);
    VideoNotifyPrefs.instance.removeListener(_on);
    super.dispose();
  }

  void _onAuth() {
    if (mounted) setState(() {});
  }

  void _on() {
    if (mounted) setState(() {});
  }

  Future<void> _refresh() async {
    await Future.wait([extras.refresh(), if (store.started) store.refresh()]);
  }

  Future<void> _openService() async {
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ServiceAccountPage()));
  }

  /// 一单一个群:点进去就是这一单的群;群头置顶条上的「看订单」进订单详情
  Future<void> _openOrder(OrderThread t) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (ctx) => OrderChatPage(
            api: widget.api,
            orderNo: t.orderNo,
            title: t.title,
            quickReplies: kCustomerQuickReplies,
            onOpenOrder: () => Navigator.of(ctx).push(MaterialPageRoute<void>(
                builder: (_) => OrderDetailPage(api: widget.api, orderNo: t.orderNo))))));
    // 进去看过,未读就清了;回来刷一下这一行
    unawaited(extras.refreshOrders());
  }

  Future<void> _openBot() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const VideoNotificationsPage()));
    unawaited(extras.refreshBot());
  }

  Future<void> _compose() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          // 扫一扫(和微信「+」菜单里那个一样):扫网页版、电脑版的登录二维码,扫别人的名片码加联系人。只有手机上有
          if (canScanHere)
            ListTile(leading: const Icon(Icons.qr_code_scanner), title: const Text('扫一扫'), onTap: () => Navigator.pop(ctx, 'scan')),
          ListTile(leading: const Icon(Icons.group_add_outlined), title: const Text('新建群组'), onTap: () => Navigator.pop(ctx, 'group')),
          ListTile(leading: const Icon(Icons.campaign_outlined), title: const Text('新建频道'), onTap: () => Navigator.pop(ctx, 'channel')),
          ListTile(leading: const Icon(Icons.person_add_alt_1_outlined), title: const Text('添加联系人'), onTap: () => Navigator.pop(ctx, 'add')),
          ListTile(leading: const Icon(Icons.contacts_outlined), title: const Text('联系人'), onTap: () => Navigator.pop(ctx, 'contacts')),
          ListTile(leading: const Icon(Icons.bookmark_outline), title: const Text('收藏夹'), onTap: () => Navigator.pop(ctx, 'saved')),
          ListTile(leading: const Icon(Icons.call_outlined), title: const Text('通话记录'), onTap: () => Navigator.pop(ctx, 'calls')),
          ListTile(leading: const Icon(Icons.folder_outlined), title: const Text('会话分组'), onTap: () => Navigator.pop(ctx, 'folders')),
          ListTile(leading: const Icon(Icons.settings_outlined), title: const Text('消息设置'), onTap: () => Navigator.pop(ctx, 'settings')),
        ]),
      ),
    );
    if (!mounted || pick == null) return;
    switch (pick) {
      case 'scan':
        await openQrScanner(context, widget.api);
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
      case 'calls':
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const CallsPage()));
      case 'settings':
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ChatSettingsPage()));
    }
  }

  String _title() {
    // 标题跟着底部菜单那一格的名字走(后台「文案」页的 nav.chat,默认「聊天」)
    final name = RemoteCopy.text('nav.chat', '聊天');
    if (!store.started) return name;
    return switch (store.conn) {
      ConnState.online => name,
      ConnState.connecting => '连接中…',
      ConnState.offline => '等待网络…',
    };
  }

  /// 「全部」下的整张列表:置顶段(服务号、在送的订单群、自己置顶的会话)+ 其余按时间。
  List<Widget> _rows(List<ChatInfo> chats, bool loggedIn) {
    final pinnedChats = chats.where((c) => c.my.pinnedRank != null).toList();
    final restChats = chats.where((c) => c.my.pinnedRank == null);
    final threads = loggedIn ? extras.orderThreads : const <OrderThread>[];
    final live = threads.where((t) => t.active).toList()..sort((a, b) => b.time.compareTo(a.time));
    final showBot = loggedIn && !extras.botOff;

    // 置顶段之外的行按时间排:聊天、送完了的订单群、视频互动
    final timed = <(DateTime, Widget)>[
      for (final c in restChats) (c.sortTime, DialogRow(key: ValueKey('c${c.id}'), chat: c)),
      for (final t in threads.where((t) => !t.active))
        (t.time, _OrderRow(key: ValueKey('o${t.orderNo}'), thread: t, onTap: () => _openOrder(t))),
      if (showBot)
        (
          extras.botLast == null ? DateTime.fromMillisecondsSinceEpoch(0) : notifyTime(extras.botLast!),
          _BotRow(key: const ValueKey('bot'), onTap: _openBot),
        ),
    ]..sort((a, b) => b.$1.compareTo(a.$1));

    return [
      _ServiceRow(key: const ValueKey('svc'), onTap: _openService),
      for (final t in live) _OrderRow(key: ValueKey('o${t.orderNo}'), thread: t, onTap: () => _openOrder(t)),
      for (final c in pinnedChats) DialogRow(key: ValueKey('c${c.id}'), chat: c),
      for (final (_, w) in timed) w,
    ];
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final loggedIn = widget.api.isLoggedIn;
    final folders = store.folders;
    ChatFolder? folder;
    if (_folder >= 0 && _folder < folders.length) folder = folders[_folder];
    final chatOn = RemoteCopy.feature('chat');
    final chats = loggedIn && chatOn ? store.sortedChats(folder: folder) : const <ChatInfo>[];
    final archived = loggedIn && chatOn && folder == null ? store.sortedChats(archived: true) : const <ChatInfo>[];
    final archivedUnread = archived.fold<int>(0, (n, c) => n + (c.my.muted ? 0 : store.unreadOf(c)));

    final rows = <Widget>[
      if (archived.isNotEmpty)
        ConvRow(
          avatar: const IconAvatar(icon: Icons.archive_outlined),
          title: '归档',
          preview: Text(archived.take(3).map((c) => c.title).join('、')),
          trailing: archivedUnread > 0 ? UnreadBadge(count: archivedUnread, muted: true) : null,
          onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ArchivedPage())),
        ),
      if (folder == null) ..._rows(chats, loggedIn) else for (final c in chats) DialogRow(key: ValueKey('c${c.id}'), chat: c),
    ];

    // 聊天那一段的状态:没登录、急停闸、还在拉、拉不到、空着
    Widget? state;
    if (!chatOn) {
      // 平台拉了「消息」的急停闸(/config 的 features.chat):服务号、订单群照常,聊天这块说清楚在停着
      state = const SzEmpty(text: '消息功能暂停中,稍后再试\n平台公告、订单群不受影响');
    } else if (!loggedIn) {
      state = SzEmpty(
        text: '登录后和朋友聊天、建群、订阅频道',
        actionLabel: '登录 / 注册',
        onAction: () => ensureLoggedIn(context),
      );
    } else if (chats.isEmpty) {
      if (!store.loaded && store.loadError == null) {
        state = const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()));
      } else if (store.loadError != null && store.chats.isEmpty) {
        state = SzError(error: store.loadError, onRetry: store.refresh);
      } else if (folder != null) {
        state = const SzEmpty(text: '这个分组里还没有会话');
      } else {
        state = SzEmpty(
          text: '还没有聊天\n加个联系人,或者建一个群',
          actionLabel: '添加联系人',
          onAction: () =>
              Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const AddContactPage())),
        );
      }
    }
    if (state != null) rows.add(Padding(padding: const EdgeInsets.only(top: 24), child: state));

    return Column(children: [
      AppBar(
        toolbarHeight: 52,
        titleSpacing: kPagePad,
        title: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          Text(_title(), style: TextStyle(fontSize: kFontLead, fontWeight: FontWeight.w600, color: sz.ink)),
          if (store.started && store.conn != ConnState.online)
            const Padding(padding: EdgeInsets.only(left: 8), child: ConnDot()),
        ]),
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
          IconButton(tooltip: '新建', icon: const Icon(Icons.border_color_outlined), onPressed: _compose),
          const SizedBox(width: 4),
        ],
      ),
      if (loggedIn && chatOn && folders.isNotEmpty)
        SizedBox(
          height: 40,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 8),
            itemCount: folders.length + 1,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (context, i) {
              if (i == 0) return Center(child: SzChip('全部', selected: _folder < 0, onTap: () => setState(() => _folder = -1)));
              final f = folders[i - 1];
              final n = store.sortedChats(folder: f).where((c) => !c.my.muted && store.unreadOf(c) > 0).length;
              return Center(
                child: SzChip(n > 0 ? '${f.title} $n' : f.title,
                    selected: _folder == i - 1, onTap: () => setState(() => _folder = i - 1)),
              );
            },
          ),
        ),
      Expanded(
        // 标题栏已经让过状态栏了,列表别再按顶部安全区补一次 —— 不去掉的话
        // 安卓上第一行上面会空出一截状态栏高(网页版没有状态栏,看不出来)
        child: MediaQuery.removePadding(
          context: context,
          removeTop: true,
          child: RefreshIndicator(
            onRefresh: _refresh,
            child: ListView.builder(
              padding: const EdgeInsets.only(top: 2, bottom: 8),
              itemCount: rows.length,
              itemBuilder: (context, i) => rows[i],
            ),
          ),
        ),
      ),
    ]);
  }
}

/// 平台服务号「超级赞」:带认证标,置顶。内容是平台公告,点进去是只读的会话。
class _ServiceRow extends StatelessWidget {
  const _ServiceRow({super.key, required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final x = ChatExtras.instance;
    final latest = x.notices.isEmpty ? null : x.notices.first;
    final unread = x.noticeUnread;
    final at = latest?.createdAt;
    return ConvRow(
      pinned: true,
      avatar: const IconAvatar(soft: true, child: BrandMark(size: 26)),
      title: '超级赞',
      titleSuffix: const [VerifiedMark()],
      time: at == null ? '' : listTime(at),
      preview: Text(latest == null ? '平台公告' : (latest.title.isNotEmpty ? latest.title : latest.content)),
      trailing: unread > 0 ? UnreadBadge(count: unread) : null,
      onTap: onTap,
    );
  }
}

/// 一单一个群:「订单 #xxxxxx · 张记面馆」、群图标、「配送中 · 骑手:到楼下了……」、未读数。
/// 还在送的置顶;送完的和别的会话一起按时间排。
class _OrderRow extends StatelessWidget {
  const _OrderRow({super.key, required this.thread, required this.onTap});

  final OrderThread thread;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final t = thread;
    final last = t.last;
    final content = last == null ? '' : (last.kind == 'image' ? '[图片]' : last.content.replaceAll('\n', ' '));
    final who = last == null ? '' : (last.from == 'customer' ? '我' : last.senderName);
    return ConvRow(
      pinned: t.active,
      avatar: const IconAvatar(soft: true, icon: Icons.receipt_long_outlined),
      title: t.title,
      titlePrefix: Icons.group_outlined,
      time: listTime(t.time),
      preview: Text.rich(TextSpan(children: [
        if (t.statusLabel.isNotEmpty)
          TextSpan(text: '${t.statusLabel} · ', style: TextStyle(color: t.active ? sz.earn : sz.inkMuted)),
        if (last == null)
          const TextSpan(text: '还没有消息')
        else ...[
          if (who.isNotEmpty) TextSpan(text: '$who: ', style: TextStyle(color: sz.ink)),
          TextSpan(text: content),
        ],
      ])),
      trailing: t.unread > 0 ? UnreadBadge(count: t.unread) : null,
      onTap: onTap,
    );
  }
}

/// 「视频互动」机器人:视频的回复 / @ / 赞 / 投稿审核结果。静音了角标变灰、不进底栏。
class _BotRow extends StatelessWidget {
  const _BotRow({super.key, required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final last = ChatExtras.instance.botLast;
    final muted = VideoNotifyPrefs.instance.muted;
    final n = videoNotifyBadge();
    String preview = '回复、@、赞和投稿审核结果';
    if (last != null) {
      final head = notifyHeadline(last);
      preview = (last.kind == 'reply' || last.kind == 'at') && last.text.isNotEmpty ? '$head:${last.text}' : head;
    }
    return ConvRow(
      avatar: const IconAvatar(icon: Icons.smart_toy_outlined),
      title: '视频互动',
      titleSuffix: [
        const BotTag(),
        if (muted) Icon(Icons.notifications_off, size: 13, color: sz.inkFaint),
      ],
      time: last == null ? '' : listTime(notifyTime(last)),
      preview: Text(preview.replaceAll('\n', ' ')),
      trailing: n > 0 ? UnreadBadge(count: n, muted: muted) : null,
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
          final n = await store.api.patchDialog(c.id, {'muted_until': muteParam(until)});
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
      preview = Text(typing, style: TextStyle(color: sz.clay));
    } else if (draft.isNotEmpty && store.viewing != c.id) {
      preview = Text.rich(TextSpan(children: [
        TextSpan(text: '草稿:', style: TextStyle(color: sz.danger)),
        TextSpan(text: draft.replaceAll('\n', ' ')),
      ]));
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
      preview = Text.rich(TextSpan(children: [
        if (who.isNotEmpty) TextSpan(text: who, style: TextStyle(color: sz.ink)),
        TextSpan(text: text),
      ]));
    } else {
      preview = Text(c.isSaved ? '转发到这里的消息只有你看得到' : '');
    }
    // 没头像的收藏夹、频道画一个图标:收藏夹是书签,频道是喇叭(设计稿里「开城公告」那一行)
    final Widget avatar = c.isSaved
        ? const IconAvatar(icon: Icons.bookmark_outline)
        : (c.isChannel && c.photo.isEmpty
            ? const IconAvatar(icon: Icons.campaign_outlined)
            : ChatAvatar(name: c.title, url: c.photo, size: 50, online: online));
    final badges = <Widget>[
      if (c.unreadMentions > 0)
        Container(
          width: 18,
          height: 18,
          alignment: Alignment.center,
          decoration: BoxDecoration(color: sz.clay, shape: BoxShape.circle),
          child: Text('@', style: TextStyle(color: sz.surface, fontSize: kFontMicro, fontWeight: FontWeight.w600, height: 1)),
        ),
      if (unread > 0)
        UnreadBadge(count: unread, muted: c.my.muted, marked: c.my.markedUnread && c.unread == 0)
      else if (c.my.pinnedRank != null)
        Icon(Icons.push_pin, size: 15, color: sz.inkFaint),
    ];
    return ConvRow(
      pinned: c.my.pinnedRank != null,
      avatar: avatar,
      title: c.title,
      titlePrefix: c.isGroup ? Icons.group_outlined : null,
      titleSuffix: [
        if (c.peer?.isBot == true) const BotTag(),
        if (c.my.muted) Icon(Icons.notifications_off, size: 13, color: sz.inkFaint),
      ],
      timeLead: mineLast && !c.isChannel && !c.isSaved
          ? Icon(last.seq <= c.peerReadSeq ? Icons.done_all : Icons.done,
              size: 15, color: last.seq <= c.peerReadSeq ? sz.clay : sz.inkMuted)
          : null,
      time: last == null ? '' : listTime(last.createdAt),
      preview: preview,
      trailing: badges.isEmpty
          ? null
          : Row(mainAxisSize: MainAxisSize.min, children: [
              for (var i = 0; i < badges.length; i++) ...[if (i > 0) const SizedBox(width: 4), badges[i]],
            ]),
      onTap: () => openChat(context, c.id),
      onLongPress: () => _menu(context),
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
