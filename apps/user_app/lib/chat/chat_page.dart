import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import '../miniapp/container.dart';
import 'calls/call_controller.dart';
import 'links.dart';
import 'models.dart';
import 'pages/chat_info_page.dart';
import 'pages/forward_page.dart';
import 'pages/media_viewer.dart';
import 'pages/pickers.dart';
import 'pages/scheduled_page.dart';
import 'pages/shared_media_page.dart';
import 'pages/user_profile_page.dart';
import 'store.dart';
import 'ui/avatar.dart';
import 'ui/bubble.dart';
import 'ui/composer.dart';
import 'ui/emoji.dart';
import 'ui/format.dart';
import 'ui/rich_text.dart';

/// 打开一个会话。所有入口都走这里(会话列表、名片「发消息」、搜索结果、推送)。
Future<void> openChat(BuildContext context, int chatId, {int? jumpTo}) async {
  final c = await ChatStore.instance.ensureChat(chatId);
  if (c == null || !context.mounted) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('这个会话打不开了')));
    }
    return;
  }
  await Navigator.of(context).push(MaterialPageRoute<void>(
    settings: RouteSettings(name: '/chat/$chatId'),
    builder: (_) => ChatPage(chatId: chatId, jumpTo: jumpTo),
  ));
}

/// 和某人私聊(没有就建)。
Future<void> openPrivateWith(BuildContext context, int userId) async {
  try {
    final c = await ChatStore.instance.openPrivate(userId);
    if (context.mounted) await openChat(context, c.id);
  } on ApiException catch (e) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
  }
}

/// 显示在列表里的一项:一条消息(相册合成一项)、一行日期、未读分割线。
class _Item {
  _Item.msg(this.message, this.album, this.run) : day = null, unreadDivider = false;
  _Item.day(this.day) : message = null, album = const [], run = RunPos.single, unreadDivider = false;
  _Item.unread() : message = null, album = const [], run = RunPos.single, day = null, unreadDivider = true;

  final ChatMessage? message;
  final List<ChatMessage> album;
  final RunPos run;
  final DateTime? day;
  final bool unreadDivider;

  String get key {
    if (day != null) return 'd${day!.year}-${day!.month}-${day!.day}';
    if (unreadDivider) return 'unread';
    final m = message!;
    return m.seq > 0 ? 's${m.seq}' : 'r${m.randomId}';
  }
}

class ChatPage extends StatefulWidget {
  const ChatPage({super.key, required this.chatId, this.jumpTo});

  final int chatId;
  final int? jumpTo;

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final ScrollController _scroll = ScrollController();
  final Map<String, GlobalKey> _keys = {};
  final GlobalKey<ComposerState> _composer = GlobalKey();
  ChatMessage? _replyTo;
  ChatMessage? _editing;
  int? _highlight;
  bool _atBottom = true;
  bool _loading = true;
  Object? _error;

  /// 打开时读到哪:「以下为新消息」分割线画在它后面
  int _readAtOpen = 0;

  /// 打开时会话里最后一条的 seq:之后在看着的时候来的消息当场就读了,不画分割线
  int _lastSeqAtOpen = 0;
  bool _selecting = false;
  final Set<String> _selected = {};

  /// 搜索模式
  bool _searching = false;
  final TextEditingController _searchText = TextEditingController();
  List<ChatMessage> _hits = [];
  int _hitIndex = 0;

  /// 置顶
  List<ChatMessage> _pins = [];
  int _pinIndex = 0;
  bool _pinsHidden = false;

  ChatStore get store => ChatStore.instance;
  ChatInfo? get chat => store.chats[widget.chatId];

  @override
  void initState() {
    super.initState();
    store.viewing = widget.chatId;
    store.realtime.view(widget.chatId);
    _readAtOpen = chat?.my.lastReadSeq ?? 0;
    _lastSeqAtOpen = chat?.lastSeq ?? 0;
    store.addListener(_onStore);
    store.pinnedVersion.addListener(_loadPins);
    _scroll.addListener(_onScroll);
    _load();
  }

  @override
  void dispose() {
    if (store.viewing == widget.chatId) {
      store.viewing = null;
      store.realtime.view(null);
    }
    // 只是「先看看」的公开会话:退出就不留在本地(不在会话里,也收不到它的事件)
    final c = chat;
    if (c != null && !c.can('in_chat')) {
      store.chats.remove(widget.chatId);
      store.timelines.remove(widget.chatId);
    }
    store.removeListener(_onStore);
    store.pinnedVersion.removeListener(_loadPins);
    _viewsTimer?.cancel();
    _scroll.dispose();
    _searchText.dispose();
    super.dispose();
  }

  void _onStore() {
    if (!mounted) return;
    if (chat == null) {
      // 会话没了(被移出、解散、在另一台设备上删了)
      Navigator.of(context).maybePop();
      return;
    }
    setState(() {});
    if (_atBottom) store.markRead(widget.chatId);
    _scheduleViews();
  }

  Future<void> _load() async {
    try {
      final t = store.timeline(widget.chatId);
      if (widget.jumpTo != null) {
        await store.loadAround(widget.chatId, widget.jumpTo!);
        if (!mounted) return;
        setState(() => _loading = false);
        WidgetsBinding.instance.addPostFrameCallback((_) => _jumpTo(widget.jumpTo!));
      } else {
        if (!t.loaded || t.hasNewer) await store.loadLatest(widget.chatId);
        if (!mounted) return;
        // 缓存里的卡片可能没有 last_seq:以拉到的最新一页为准
        if (t.lastSeq > _lastSeqAtOpen) _lastSeqAtOpen = t.lastSeq;
        setState(() => _loading = false);
        store.markRead(widget.chatId);
      }
      unawaited(_loadPins());
      _reportViews();
      final c = chat;
      // 机器人私聊、群:拉一次命令和菜单(频道里机器人只发帖,不接命令)
      if (c != null && ((c.isPrivate && c.peer?.isBot == true) || c.isGroup)) {
        unawaited(store.loadBots(widget.chatId, refresh: true));
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e;
        });
      }
    }
  }

  Future<void> _loadPins() async {
    try {
      final p = await store.api.pins(widget.chatId);
      if (!mounted) return;
      setState(() {
        _pins = p;
        if (_pinIndex >= p.length) _pinIndex = 0;
      });
    } catch (_) {}
  }

  /// 频道:看到的帖子报浏览量(服务端按人去重),顺便拿回这些帖子最新的浏览量。
  /// 打开时报一次;看着的时候来了新帖,攒 2 秒再报(不是每来一条就打一次接口)
  Timer? _viewsTimer;
  final Set<int> _viewsReported = {};

  void _reportViews() {
    final c = chat;
    if (c == null || !c.isChannel) return;
    final seqs = [
      for (final m in store.timeline(widget.chatId).messages)
        if (m.seq > 0 && !m.isService && !_viewsReported.contains(m.seq)) m.seq
    ];
    if (seqs.isEmpty) return;
    final batch = seqs.length > 100 ? seqs.sublist(seqs.length - 100) : seqs;
    _viewsReported.addAll(batch);
    unawaited(store.api.views(widget.chatId, batch).then((v) {
      final t = store.timeline(widget.chatId);
      for (final e in v.entries) {
        final m = t.bySeq(e.key);
        if (m != null && m.views != e.value) t.upsert(m.copyWith(views: e.value));
      }
      if (mounted) setState(() {});
    }, onError: (_) {}));
  }

  void _scheduleViews() {
    if (chat?.isChannel != true) return;
    _viewsTimer ??= Timer(const Duration(seconds: 2), () {
      _viewsTimer = null;
      if (mounted) _reportViews();
    });
  }

  void _onScroll() {
    final atBottom = _scroll.hasClients && _scroll.offset < 80;
    if (atBottom != _atBottom) {
      setState(() => _atBottom = atBottom);
      if (atBottom) store.markRead(widget.chatId);
    }
    if (_scroll.hasClients && _scroll.position.extentAfter < 600) {
      final t = store.timeline(widget.chatId);
      if (t.hasOlder && !t.loadingOlder) unawaited(store.loadOlder(widget.chatId));
    }
  }

  // ---------------- 列表 ----------------

  List<_Item> _items(ChatInfo c) {
    final msgs = store.timeline(widget.chatId).messages;
    final out = <_Item>[];
    var unreadPlaced = false;
    // 倒序构建(列表是 reverse 的,index 0 在最下面)
    var i = msgs.length - 1;
    while (i >= 0) {
      final m = msgs[i];
      var album = const <ChatMessage>[];
      var j = i;
      if (m.groupedId != null) {
        while (j - 1 >= 0 && msgs[j - 1].groupedId == m.groupedId) {
          j--;
        }
        album = msgs.sublist(j, i + 1);
      }
      final anchor = msgs[j];
      final prev = j - 1 >= 0 ? msgs[j - 1] : null;
      final next = i + 1 < msgs.length ? msgs[i + 1] : null;
      bool sameRun(ChatMessage? a, ChatMessage b) =>
          a != null &&
          !a.isService &&
          !b.isService &&
          a.sender?.id == b.sender?.id &&
          a.asChat == b.asChat &&
          sameDay(a.createdAt, b.createdAt) &&
          b.createdAt.difference(a.createdAt).inMinutes.abs() < 5;
      final withPrev = sameRun(prev, anchor);
      final withNext = sameRun(next, m);
      final run = withPrev && withNext
          ? RunPos.middle
          : (withPrev ? RunPos.last : (withNext ? RunPos.first : RunPos.single));
      out.add(_Item.msg(album.isEmpty ? m : anchor, album.length > 1 ? album : const [], run));
      // 未读分割线:放在「第一条没读的别人的消息」上面
      final mine = store.isMine(anchor) || anchor.isLocal;
      if (!unreadPlaced &&
          _readAtOpen > 0 &&
          anchor.seq > _readAtOpen &&
          anchor.seq <= _lastSeqAtOpen &&
          !mine &&
          (prev == null || prev.seq <= _readAtOpen)) {
        out.add(_Item.unread());
        unreadPlaced = true;
      }
      if (prev == null || !sameDay(prev.createdAt, anchor.createdAt)) {
        out.add(_Item.day(anchor.createdAt));
      }
      i = j - 1;
    }
    return out;
  }

  // ---------------- 跳转 ----------------

  Future<void> _jumpTo(int seq) async {
    final t = store.timeline(widget.chatId);
    if (t.bySeq(seq) == null) {
      try {
        await store.loadAround(widget.chatId, seq);
      } catch (_) {
        return;
      }
    }
    if (!mounted) return;
    setState(() => _highlight = seq);
    for (var attempt = 0; attempt < 30; attempt++) {
      await WidgetsBinding.instance.endOfFrame;
      if (!mounted) return;
      final ctx = _keys['s$seq']?.currentContext;
      if (ctx != null && ctx.mounted) {
        await Scrollable.ensureVisible(ctx, alignment: .5, duration: const Duration(milliseconds: 250));
        break;
      }
      // 还没画出来:往上翻一屏再找
      if (!_scroll.hasClients) return;
      final pos = _scroll.position;
      final target = (pos.pixels + pos.viewportDimension * .8).clamp(0.0, pos.maxScrollExtent);
      if (target == pos.pixels) break;
      _scroll.jumpTo(target);
    }
    Timer(const Duration(milliseconds: 1600), () {
      if (mounted && _highlight == seq) setState(() => _highlight = null);
    });
  }

  Future<void> _toBottom() async {
    final t = store.timeline(widget.chatId);
    if (t.hasNewer) {
      await store.loadLatest(widget.chatId);
    }
    if (_scroll.hasClients) {
      await _scroll.animateTo(0, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
    }
    store.markRead(widget.chatId);
  }

  // ---------------- 发送 ----------------

  int? _takeReply() {
    final r = _replyTo;
    if (r != null) setState(() => _replyTo = null);
    return r?.seq;
  }

  late final ComposerActions _composerActions = ComposerActions(
    onSendText: (text, ents, {bool silent = false}) async {
      await store.outbox.sendText(widget.chatId, text, entities: ents, replyTo: _takeReply(), silent: silent);
      _afterSend();
    },
    onSendAttachments: (files, caption, ents) async {
      await store.outbox.sendAttachments(widget.chatId, files,
          caption: caption, entities: ents, replyTo: _takeReply());
      _afterSend();
    },
    onSendVoice: (voice) async {
      await store.outbox.sendVoice(widget.chatId, voice, replyTo: _takeReply());
      _afterSend();
    },
    onSaveEdit: (m, text, ents) async {
      setState(() => _editing = null);
      try {
        final n = await store.api.edit(widget.chatId, m.seq, text, ents);
        store.timeline(widget.chatId).upsert(n);
        store.notifyListeners();
      } on ApiException catch (e) {
        _toast(e.message);
      }
    },
    onPickLocation: () async {
      final p = await pickLocation(context, store.client);
      if (p == null) return;
      await store.outbox.sendStructured(widget.chatId, 'location',
          {'location': {'lat': p.lat, 'lng': p.lng, 'title': p.title, 'address': p.address}},
          replyTo: _takeReply());
      _afterSend();
    },
    onPickContact: () async {
      final u = await pickContact(context);
      if (u == null) return;
      await store.outbox.sendStructured(widget.chatId, 'contact', {'contact': {'user_id': u.id}},
          replyTo: _takeReply());
      _afterSend();
    },
    onCreatePoll: () async {
      final poll = await createPoll(context, allowPublic: !(chat?.isChannel ?? false));
      if (poll == null) return;
      await store.outbox.sendStructured(widget.chatId, 'poll', {'poll': poll});
      _afterSend();
    },
    onDice: (e) async {
      await store.outbox.sendStructured(widget.chatId, 'dice', {'dice': {'emoji': e}}, replyTo: _takeReply());
      _afterSend();
    },
    onSendSticker: (s) async {
      // sticker_preview 只给本地「发送中」那条画图用,服务端不认这个字段
      await store.outbox.sendStructured(widget.chatId, 'sticker',
          {'sticker_id': s.id, 'sticker_preview': {'url': s.url, 'media_id': s.mediaId}}, replyTo: _takeReply());
      _afterSend();
    },
    onSchedule: (text, ents) async {
      final at = await pickScheduleTime(context);
      if (at == null) return;
      try {
        await store.api.schedule(
            widget.chatId, {'kind': 'text', 'text': text, 'entities': [for (final e in ents) e.toJson()]}, at);
        _toast('会在 ${at.month}月${at.day}日 ${hm(at)} 发出');
      } on ApiException catch (e) {
        _toast(e.message);
      }
    },
  );

  void _afterSend() {
    if (_scroll.hasClients && _scroll.offset > 0) {
      _scroll.animateTo(0, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
    }
  }

  void _toast(String s) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s), duration: const Duration(seconds: 2)));
  }

  // ---------------- 气泡上的动作 ----------------

  /// 气泡动作按「这个会话有没有机器人」缓存一份:有机器人时正文里的 `/命令` 才认成可点的命令
  BubbleActions? _actionsCache;
  bool _actionsWithBots = false;

  BubbleActions get _bubbleActions {
    final bots = store.botsOf(widget.chatId).isNotEmpty;
    if (_actionsCache == null || bots != _actionsWithBots) {
      _actionsWithBots = bots;
      _actionsCache = _makeActions(bots);
    }
    return _actionsCache!;
  }

  BubbleActions _makeActions(bool bots) => BubbleActions(
    onCallBack: (m) {
      final c = chat;
      if (!RemoteCopy.feature('calls')) {
        _toast('通话功能暂未开放');
        return;
      }
      if (c != null && c.isPrivate && c.peer != null) _call(c, video: m.call?['video'] == true);
    },
    onLongPress: _longPress,
    onTapReply: _jumpTo,
    onReact: _react,
    onRetry: _retryMenu,
    onOpenMedia: (m, album) => openMediaViewer(context, m, album.isEmpty ? [m] : album),
    onOpenUser: (uid) => openUserProfile(context, uid),
    onVote: (m, opts) async {
      try {
        final n = await store.api.vote(widget.chatId, m.seq, opts);
        store.timeline(widget.chatId).upsert(n);
        store.notifyListeners();
      } on ApiException catch (e) {
        _toast(e.message);
      }
    },
    onClosePoll: (m) async {
      try {
        final n = await store.api.closePoll(widget.chatId, m.seq);
        store.timeline(widget.chatId).upsert(n);
        store.notifyListeners();
      } on ApiException catch (e) {
        _toast(e.message);
      }
    },
    onShowVoters: (m) => showPollVoters(context, widget.chatId, m),
    onMarkup: _onMarkup,
    onSwipeReply: (m) => setState(() {
      _editing = null;
      _replyTo = m;
    }),
    onTapSelect: _toggleSelect,
    handlers: TextTapHandlers(
      onUrl: _openUrl,
      onMention: (name) => openUsername(context, name),
      onUserId: (uid) => openUserProfile(context, uid),
      onHashtag: (tag) {
        setState(() {
          _searching = true;
          _searchText.text = tag;
        });
        _runSearch();
      },
      onBotCommand: bots ? (cmd) => _composerActions.onSendText(cmd, const []) : null,
    ),
  );

  /// 语音 / 视频通话(#354)。先选类型;已经在通话里就提示。
  Future<void> _call(ChatInfo c, {bool? video}) async {
    final peer = c.peer;
    if (peer == null) return;
    final v = video ??
        await szShowSheet<bool>(
          context: context,
          builder: (ctx) => SafeArea(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              ListTile(leading: const Icon(Icons.call_outlined), title: const Text('语音通话'), onTap: () => Navigator.pop(ctx, false)),
              ListTile(leading: const Icon(Icons.videocam_outlined), title: const Text('视频通话'), onTap: () => Navigator.pop(ctx, true)),
            ]),
          ),
        );
    if (v == null || !mounted) return;
    final ok = await CallController.instance.start(peer.id, peer.displayName, peer.avatar, video: v);
    if (!ok) _toast('正在通话中,先挂掉这一通');
  }

  /// 机器人内联键盘(#355):链接按钮走 [_openUrl](问一句再用浏览器开),小程序按钮直接打开,
  /// 回调按钮问机器人要回话 —— 服务端最多等 10 秒,等不到就什么都不提示(Telegram 也是这样)
  Future<void> _onMarkup(ChatMessage m, Map<String, dynamic> b) async {
    if (b['url'] != null) {
      await _openUrl('${b['url']}');
      return;
    }
    final app = b['web_app'];
    if (app is Map && app['app_id'] != null) {
      await openMiniApp(context, store.api.api, appid: '${app['app_id']}');
      return;
    }
    final data = b['callback_data'];
    if (data == null || m.seq <= 0) return;
    try {
      final r = await store.api.botCallback(widget.chatId, m.seq, '$data');
      if (!mounted || r['answered'] != true) return;
      final text = '${r['text'] ?? ''}';
      if (text.isNotEmpty) {
        if (r['show_alert'] == true) {
          await showDialog<void>(
            context: context,
            builder: (ctx) => SzDialog(
              content: Text(text, style: const TextStyle(fontSize: kFontBody)),
              actions: [FilledButton(onPressed: () => Navigator.pop(ctx), child: const Text('好'))],
            ),
          );
        } else {
          _toast(text);
        }
      }
      final url = r['url'];
      if (url is String && url.isNotEmpty && mounted) await _openUrl(url);
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _openUrl(String url) async {
    final uri = Uri.tryParse(url.contains('://') ? url : 'https://$url');
    if (uri == null) return;
    // 站内链接(@用户名、邀请链接、名片)直接在 App 里打开
    if (await openAppLink(context, uri)) return;
    if (!mounted) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => SzDialog(
        title: const Text('打开链接'),
        content: Text('将用浏览器打开:\n${uri.host}\n\n这个网页不归超级赞管。', style: const TextStyle(fontSize: kFontBody)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('打开')),
        ],
      ),
    );
    if (ok == true) await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  Future<void> _react(ChatMessage m, String emoji) async {
    final had = m.reactions.any((r) => r.emoji == emoji && r.me);
    try {
      final n = await store.api.react(widget.chatId, m.seq, emoji, add: !had);
      store.timeline(widget.chatId).upsert(n);
      store.notifyListeners();
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _retryMenu(ChatMessage m) async {
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if ((m.localError ?? '').isNotEmpty)
            Padding(
              padding: const EdgeInsets.all(kPagePad),
              child: Text('没发出去:${m.localError}', style: TextStyle(color: Theme.of(ctx).sz.danger)),
            ),
          ListTile(leading: const Icon(Icons.refresh), title: const Text('重新发送'), onTap: () => Navigator.pop(ctx, 'retry')),
          ListTile(leading: const Icon(Icons.delete_outline), title: const Text('删除'), onTap: () => Navigator.pop(ctx, 'drop')),
        ]),
      ),
    );
    if (pick == 'retry' && m.randomId != null) await store.outbox.retry(m.randomId!);
    if (pick == 'drop' && m.randomId != null) await store.outbox.discard(m.randomId!);
  }

  void _toggleSelect(ChatMessage m) {
    final k = m.seq > 0 ? 's${m.seq}' : 'r${m.randomId}';
    setState(() {
      if (!_selected.remove(k)) _selected.add(k);
      if (_selected.isEmpty) _selecting = false;
    });
  }

  List<ChatMessage> _selectedMessages() {
    final t = store.timeline(widget.chatId);
    return [
      for (final m in t.messages)
        if (_selected.contains(m.seq > 0 ? 's${m.seq}' : 'r${m.randomId}') && m.seq > 0) m
    ];
  }

  Future<void> _longPress(ChatMessage m) async {
    final c = chat;
    if (c == null || _selecting) return;
    HapticFeedback.selectionClick();
    if (m.isLocal) {
      if (m.localStatus == LocalStatus.failed) await _retryMenu(m);
      return;
    }
    final mine = m.sender?.id == store.meId && !m.asChat;
    final age = DateTime.now().difference(m.createdAt).inHours;
    final canEdit = mine && m.kind != 'service' && age < 48 && ['text', 'photo', 'video', 'file', 'gif'].contains(m.kind) ||
        (c.isChannel && c.can('edit_others') && m.kind == 'text');
    final canPin = c.can('pin_messages') || c.isPrivate || c.isSaved;
    final canReact = !c.isSaved && !m.isService;
    final protected = c.settings['protected'] == true;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (canReact)
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 4, 8, 4),
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(children: [
                    for (final e in quickReactions)
                      InkResponse(
                        onTap: () => Navigator.pop(ctx, 'react:$e'),
                        child: Padding(
                            padding: const EdgeInsets.all(8), child: Text(e, style: const TextStyle(fontSize: kFigureMd))),
                      ),
                  ]),
                ),
              ),
            if (!m.isService) ...[
              ListTile(leading: const Icon(Icons.reply), title: const Text('回复'), onTap: () => Navigator.pop(ctx, 'reply')),
              if (m.text.isNotEmpty && !protected)
                ListTile(leading: const Icon(Icons.copy), title: const Text('复制'), onTap: () => Navigator.pop(ctx, 'copy')),
              if (!protected)
                ListTile(leading: const Icon(Icons.shortcut), title: const Text('转发'), onTap: () => Navigator.pop(ctx, 'forward')),
              if (!protected && !c.isSaved)
                ListTile(
                    leading: const Icon(Icons.bookmark_outline), title: const Text('存到收藏夹'), onTap: () => Navigator.pop(ctx, 'save')),
              if (canEdit)
                ListTile(leading: const Icon(Icons.edit_outlined), title: const Text('编辑'), onTap: () => Navigator.pop(ctx, 'edit')),
              if (canPin)
                ListTile(
                    leading: Icon(m.pinned ? Icons.push_pin : Icons.push_pin_outlined),
                    title: Text(m.pinned ? '取消置顶' : '置顶'),
                    onTap: () => Navigator.pop(ctx, 'pin')),
              if (c.isGroup && mine && c.memberCount <= 100)
                ListTile(leading: const Icon(Icons.done_all), title: const Text('已读名单'), onTap: () => Navigator.pop(ctx, 'readers')),
              if (m.reactions.isNotEmpty && !c.isChannel)
                ListTile(leading: const Icon(Icons.emoji_emotions_outlined), title: const Text('谁回应了'), onTap: () => Navigator.pop(ctx, 'reactors')),
              if (c.username != null)
                ListTile(leading: const Icon(Icons.link), title: const Text('复制消息链接'), onTap: () => Navigator.pop(ctx, 'link')),
              ListTile(leading: const Icon(Icons.check_circle_outline), title: const Text('多选'), onTap: () => Navigator.pop(ctx, 'select')),
            ],
            ListTile(
                leading: Icon(Icons.delete_outline, color: Theme.of(ctx).sz.danger),
                title: Text('删除', style: TextStyle(color: Theme.of(ctx).sz.danger)),
                onTap: () => Navigator.pop(ctx, 'delete')),
            if (!mine && !m.isService)
              ListTile(leading: const Icon(Icons.flag_outlined), title: const Text('举报'), onTap: () => Navigator.pop(ctx, 'report')),
          ]),
        ),
      ),
    );
    if (pick == null || !mounted) return;
    if (pick.startsWith('react:')) return _react(m, pick.substring(6));
    switch (pick) {
      case 'reply':
        setState(() {
          _editing = null;
          _replyTo = m;
        });
      case 'copy':
        await Clipboard.setData(ClipboardData(text: m.text));
        _toast('已复制');
      case 'forward':
        await _forward([m]);
      case 'save':
        try {
          final saved = await store.openSaved();
          await store.api.forward(widget.chatId, [m.seq], [saved.id]);
          _toast('已存到收藏夹');
        } on ApiException catch (e) {
          _toast(e.message);
        }
      case 'edit':
        setState(() {
          _replyTo = null;
          _editing = m;
        });
      case 'pin':
        try {
          await store.api.pin(widget.chatId, m.seq, pinned: !m.pinned);
          await _loadPins();
        } on ApiException catch (e) {
          _toast(e.message);
        }
      case 'readers':
        await showReaders(context, widget.chatId, m.seq);
      case 'reactors':
        await showReactors(context, widget.chatId, m.seq);
      case 'link':
        await Clipboard.setData(ClipboardData(text: 'https://chaojizan.cc/@${c.username}/${m.seq}'));
        _toast('链接已复制');
      case 'select':
        setState(() {
          _selecting = true;
          _selected
            ..clear()
            ..add('s${m.seq}');
        });
      case 'delete':
        await _delete([m]);
      case 'report':
        await reportMessages(context, chatId: widget.chatId, seqs: [m.seq]);
    }
  }

  Future<void> _forward(List<ChatMessage> msgs) async {
    final targets = await pickForwardTargets(context);
    if (targets == null || targets.isEmpty) return;
    try {
      await store.api.forward(widget.chatId, [for (final m in msgs) m.seq], targets);
      _toast(targets.length == 1 ? '已转发' : '已转发到 ${targets.length} 个会话');
      if (_selecting) setState(() => _selecting = false);
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _delete(List<ChatMessage> msgs) async {
    final c = chat!;
    final allMine = msgs.every((m) => m.sender?.id == store.meId && !m.asChat);
    final canRevoke = c.isPrivate || c.isSaved || (c.isGroup && (allMine || c.can('delete_others'))) ||
        (c.isChannel && c.can('delete_others'));
    final peerName = c.isPrivate ? c.title : '';
    bool revoke = c.isPrivate;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => SzDialog(
          title: Text(msgs.length == 1 ? '删除这条消息?' : '删除 ${msgs.length} 条消息?'),
          content: canRevoke && !c.isSaved
              ? CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: revoke,
                  onChanged: (v) => set(() => revoke = v ?? false),
                  title: Text(c.isPrivate ? '同时为 $peerName 删除' : '为所有人删除'),
                )
              : null,
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
            FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).sz.danger),
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('删除'),
            ),
          ],
        ),
      ),
    );
    if (ok != true) return;
    try {
      final gone = await store.api.deleteMessages(widget.chatId, [for (final m in msgs) m.seq],
          revoke: revoke && canRevoke);
      store.timeline(widget.chatId).removeSeqs(gone);
      store.notifyListeners();
      if (_selecting) setState(() => _selecting = false);
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  // ---------------- 搜索 ----------------

  Future<void> _runSearch() async {
    final q = _searchText.text.trim();
    if (q.isEmpty) {
      setState(() => _hits = []);
      return;
    }
    try {
      final r = await store.api.searchIn(widget.chatId, q: q);
      if (!mounted) return;
      setState(() {
        _hits = r.items;
        _hitIndex = 0;
      });
      if (_hits.isNotEmpty) await _jumpTo(_hits.first.seq);
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  // ---------------- 顶栏 ----------------

  String _subtitle(ChatInfo c) {
    if (store.conn != ConnState.online) return store.conn == ConnState.connecting ? '连接中…' : '等待网络…';
    final typing = store.typingLabel(c);
    if (typing != null) return typing;
    if (c.isPrivate) {
      final p = c.peer;
      if (p == null) return '';
      if (p.isBot) return '机器人';
      return p.lastSeen.label();
    }
    if (c.isGroup) return '${c.memberCount} 位成员';
    if (c.isChannel) return '${c.memberCount} 位订阅者';
    return '';
  }

  PreferredSizeWidget _appBar(ChatInfo c) {
    final sz = Theme.of(context).sz;
    if (_selecting) {
      return AppBar(
        leading: IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => _selecting = false)),
        title: Text('已选 ${_selected.length} 条'),
        actions: [
          if (c.settings['protected'] != true)
            IconButton(tooltip: '转发', icon: const Icon(Icons.shortcut), onPressed: () => _forward(_selectedMessages())),
          IconButton(
              tooltip: '复制',
              icon: const Icon(Icons.copy),
              onPressed: () async {
                final text = _selectedMessages().where((m) => m.text.isNotEmpty).map((m) => m.text).join('\n\n');
                await Clipboard.setData(ClipboardData(text: text));
                _toast('已复制');
              }),
          IconButton(tooltip: '删除', icon: const Icon(Icons.delete_outline), onPressed: () => _delete(_selectedMessages())),
        ],
      );
    }
    if (_searching) {
      return AppBar(
        leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            onPressed: () => setState(() {
                  _searching = false;
                  _hits = [];
                })),
        title: TextField(
          controller: _searchText,
          autofocus: true,
          textInputAction: TextInputAction.search,
          onSubmitted: (_) => _runSearch(),
          decoration: const InputDecoration(hintText: '在会话里搜', border: InputBorder.none),
        ),
        actions: [
          if (_hits.isNotEmpty)
            Center(child: Text('${_hitIndex + 1}/${_hits.length}', style: TextStyle(color: sz.inkMuted))),
          IconButton(
            icon: const Icon(Icons.keyboard_arrow_up),
            onPressed: _hits.isEmpty || _hitIndex >= _hits.length - 1
                ? null
                : () {
                    setState(() => _hitIndex++);
                    _jumpTo(_hits[_hitIndex].seq);
                  },
          ),
          IconButton(
            icon: const Icon(Icons.keyboard_arrow_down),
            onPressed: _hitIndex <= 0
                ? null
                : () {
                    setState(() => _hitIndex--);
                    _jumpTo(_hits[_hitIndex].seq);
                  },
          ),
        ],
      );
    }
    final online = c.isPrivate && (c.peer?.lastSeen.online ?? false);
    return AppBar(
      titleSpacing: 0,
      title: InkWell(
        onTap: () => _openInfo(c),
        child: Row(children: [
          ChatAvatar(name: c.title, url: c.photo, size: 38, online: online, saved: c.isSaved),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(c.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
              if (_subtitle(c).isNotEmpty)
                Text(_subtitle(c),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                        fontSize: kFontNote,
                        color: store.typingLabel(c) != null || online ? sz.clay : sz.inkMuted)),
            ]),
          ),
        ]),
      ),
      actions: [
        // 通话开关(/config 的 features.calls,生产缺省关:电信业务许可待定)关着时不出电话按钮
        if (c.isPrivate && c.peer != null && !c.peer!.isBot && RemoteCopy.feature('calls'))
          IconButton(tooltip: '通话', icon: const Icon(Icons.call_outlined), onPressed: () => _call(c)),
        IconButton(tooltip: '搜索', icon: const Icon(Icons.search), onPressed: () => setState(() => _searching = true)),
        PopupMenuButton<String>(
          onSelected: (v) => _menu(c, v),
          itemBuilder: (_) => [
            if (!c.isSaved)
              PopupMenuItem(value: 'mute', child: Text(c.my.muted ? '取消免打扰' : '免打扰')),
            const PopupMenuItem(value: 'media', child: Text('图片、文件和链接')),
            const PopupMenuItem(value: 'scheduled', child: Text('定时消息')),
            const PopupMenuItem(value: 'clear', child: Text('清空聊天记录')),
            if (c.isPrivate && c.peer != null)
              PopupMenuItem(value: 'block', child: Text(c.peer!.blocked ? '解除拉黑' : '拉黑')),
            if (!c.isSaved) const PopupMenuItem(value: 'report', child: Text('举报')),
            PopupMenuItem(
                value: 'leave',
                child: Text(c.isPrivate || c.isSaved ? '删除聊天' : (c.my.role == 'owner' ? '解散' : '退出'))),
          ],
        ),
      ],
    );
  }

  void _openInfo(ChatInfo c) {
    if (c.isPrivate && c.peer != null) {
      openUserProfile(context, c.peer!.id, fromChat: true);
    } else if (!c.isSaved) {
      Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => ChatInfoPage(chatId: c.id)));
    }
  }

  Future<void> _menu(ChatInfo c, String v) async {
    switch (v) {
      case 'mute':
        final until = c.my.muted ? null : await pickMuteUntil(context);
        if (!c.my.muted && until == null) return;
        final n = await store.api.patchDialog(c.id, {'muted_until': until?.toUtc().toIso8601String()});
        store.putChat(n);
      case 'media':
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => SharedMediaPage(chatId: c.id)));
      case 'scheduled':
        await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => ScheduledPage(chatId: c.id)));
      case 'clear':
        final revoke = await confirmClear(context, c);
        if (revoke == null) return;
        try {
          await store.api.clearHistory(c.id, revoke: revoke);
          store.timeline(c.id).clearUpTo(c.lastSeq);
          c.lastMessage = null;
          store.notifyListeners();
        } on ApiException catch (e) {
          _toast(e.message);
        }
      case 'block':
        final p = c.peer!;
        try {
          if (p.blocked) {
            await store.api.unblock(p.id);
          } else {
            await store.api.block(p.id);
          }
          await store.refreshChat(c.id);
          _toast(p.blocked ? '已解除拉黑' : '已拉黑,对方不能再给你发消息');
        } on ApiException catch (e) {
          _toast(e.message);
        }
      case 'report':
        await reportChat(context, c);
      case 'leave':
        final done = await leaveOrDelete(context, c);
        if (done && mounted) Navigator.of(context).pop();
    }
  }

  // ---------------- 界面 ----------------

  @override
  Widget build(BuildContext context) {
    final c = chat;
    final sz = Theme.of(context).sz;
    if (c == null) {
      return SzPageScaffold(appBar: AppBar(), body: const Center(child: CircularProgressIndicator()));
    }
    final items = _items(c);
    final t = store.timeline(widget.chatId);
    final pin = !_pinsHidden && _pins.isNotEmpty ? _pins[_pinIndex % _pins.length] : null;
    // 系统返回键先退出多选 / 会话内搜索,再退出聊天(和 Telegram 一样)
    return PopScope(
      canPop: !_selecting && !_searching,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) return;
        setState(() {
          if (_selecting) {
            _selecting = false;
          } else {
            _searching = false;
            _hits = [];
          }
        });
      },
      child: SzPageScaffold(
        appBar: _appBar(c),
        body: Column(children: [
          if (pin != null)
            _PinnedBar(
              message: pin,
              index: _pinIndex,
              total: _pins.length,
              onTap: () {
                _jumpTo(pin.seq);
                setState(() => _pinIndex = (_pinIndex + 1) % _pins.length);
              },
              onClose: () async {
                if (c.can('pin_messages') || c.isPrivate) {
                  try {
                    await store.api.pin(c.id, pin.seq, pinned: false);
                    await _loadPins();
                  } on ApiException catch (e) {
                    _toast(e.message);
                  }
                } else {
                  setState(() => _pinsHidden = true);
                }
              },
            ),
          Expanded(
            child: Stack(children: [
              if (_loading && t.messages.isEmpty)
                const Center(child: CircularProgressIndicator())
              else if (_error != null && t.messages.isEmpty)
                SzError(error: _error, onRetry: () {
                  setState(() {
                    _error = null;
                    _loading = true;
                  });
                  _load();
                })
              else if (items.isEmpty && c.isPrivate && c.peer?.isBot == true)
                _BotIntro(bot: store.botsOf(c.id).firstOrNull, name: c.peer!.displayName)
              else if (items.isEmpty)
                Center(
                  child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Text(
                        c.isSaved ? '把消息转发到这里,或者直接写给自己' : '还没有消息,说点什么吧',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: sz.inkMuted)),
                  ),
                )
              else
                ListView.builder(
                  controller: _scroll,
                  reverse: true,
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  itemCount: items.length + (t.loadingOlder ? 1 : 0),
                  itemBuilder: (context, i) {
                    if (i >= items.length) {
                      return const Padding(
                          padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator(strokeWidth: 2)));
                    }
                    final it = items[i];
                    if (it.day != null) return _DayChip(day: it.day!);
                    if (it.unreadDivider) return const _UnreadDivider();
                    final m = it.message!;
                    final key = _keys.putIfAbsent(it.key, GlobalKey.new);
                    final selKey = m.seq > 0 ? 's${m.seq}' : 'r${m.randomId}';
                    return KeyedSubtree(
                      key: key,
                      child: MessageRow(
                        message: m,
                        chat: c,
                        meId: store.meId,
                        actions: _bubbleActions,
                        album: it.album,
                        run: it.run,
                        selecting: _selecting,
                        // 退出多选的路径有好几条(叉、转发完、删除完、返回键)都不清集合:高亮只在多选中才算
                        selected: _selecting && _selected.contains(selKey),
                        highlighted: _highlight != null && (m.seq == _highlight || it.album.any((x) => x.seq == _highlight)),
                      ),
                    );
                  },
                ),
              if (!_atBottom || t.hasNewer)
                Positioned(
                  right: 12,
                  bottom: 12,
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    if (c.unreadMentions > 0)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: FloatingActionButton.small(
                          heroTag: 'mention',
                          onPressed: _toBottom,
                          child: Badge(label: Text('${c.unreadMentions}'), child: const Text('@')),
                        ),
                      ),
                    FloatingActionButton.small(
                      heroTag: 'bottom',
                      onPressed: _toBottom,
                      child: Badge(
                        isLabelVisible: c.unread > 0,
                        label: Text(badgeText(c.unread)),
                        child: const Icon(Icons.keyboard_arrow_down),
                      ),
                    ),
                  ]),
                ),
            ]),
          ),
          // 和机器人还没说过话:底下只有一个「开始」(发 /start),和 Telegram 一样
          if (!_selecting && !_searching && items.isEmpty && !_loading && c.isPrivate && c.peer?.isBot == true)
            _StartBar(onStart: () => _composerActions.onSendText('/start', const []))
          else if (!_selecting && !_searching)
            Composer(
              key: _composer,
              chat: c,
              actions: _composerActions,
              replyTo: _replyTo,
              editing: _editing,
              onCancelReply: () => setState(() => _replyTo = null),
              onCancelEdit: () => setState(() => _editing = null),
              bots: store.botsOf(c.id),
              onOpenBotApp: (b) => openMiniApp(context, store.api.api, appid: b.menuAppId),
            ),
        ]),
      ),
    );
  }
}

/// 和机器人的空会话:中间讲这个机器人能做什么(开发者在后台写的「描述」)。
class _BotIntro extends StatelessWidget {
  const _BotIntro({required this.bot, required this.name});

  final BotInfo? bot;
  final String name;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final desc = bot?.description.isNotEmpty == true ? bot!.description : (bot?.about ?? '');
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Container(
          constraints: const BoxConstraints(maxWidth: 360),
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(color: sz.surface, borderRadius: BorderRadius.circular(kRadiusLg), border: Border.all(color: sz.line)),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            ChatAvatar(name: name, url: bot?.avatar ?? '', size: 64),
            const SizedBox(height: 10),
            Text('这个机器人能做什么?', style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            Text(desc.isEmpty ? '点下面的「开始」和 $name 打个招呼。' : desc,
                textAlign: TextAlign.center, style: TextStyle(color: sz.inkMuted, height: 1.5)),
            const SizedBox(height: 8),
            Text('机器人由第三方开发者提供,平台不替它背书。', textAlign: TextAlign.center,
                style: TextStyle(fontSize: kFontNote, color: sz.inkFaint)),
          ]),
        ),
      ),
    );
  }
}

class _StartBar extends StatelessWidget {
  const _StartBar({required this.onStart});

  final VoidCallback onStart;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Theme.of(context).scaffoldBackgroundColor,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 8),
          child: SizedBox(width: double.infinity, child: FilledButton(onPressed: onStart, child: const Text('开始'))),
        ),
      ),
    );
  }
}

class _DayChip extends StatelessWidget {
  const _DayChip({required this.day});

  final DateTime day;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Center(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
          decoration: BoxDecoration(color: sz.ink.withValues(alpha: .08), borderRadius: BorderRadius.circular(10)),
          child: Text(dayLabel(day), style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
      ),
    );
  }
}

class _UnreadDivider extends StatelessWidget {
  const _UnreadDivider();

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.symmetric(vertical: 4),
      color: sz.clay.withValues(alpha: .08),
      alignment: Alignment.center,
      child: Text('以下为新消息', style: TextStyle(fontSize: kFontNote, color: sz.clay)),
    );
  }
}

class _PinnedBar extends StatelessWidget {
  const _PinnedBar({required this.message, required this.index, required this.total, required this.onTap, required this.onClose});

  final ChatMessage message;
  final int index;
  final int total;
  final VoidCallback onTap;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Material(
      color: sz.surface,
      child: InkWell(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: sz.line))),
          padding: const EdgeInsets.fromLTRB(12, 6, 4, 6),
          child: Row(children: [
            Container(width: 3, height: 30, color: sz.clay),
            const SizedBox(width: 8),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(total > 1 ? '置顶消息 ${total - index % total}/$total' : '置顶消息',
                    style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600, color: sz.clay)),
                Text(previewOf(message), maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
            ),
            IconButton(icon: const Icon(Icons.close, size: 18), onPressed: onClose),
          ]),
        ),
      ),
    );
  }
}
