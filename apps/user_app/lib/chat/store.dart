import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'api.dart';
import 'calls/call_controller.dart';
import 'chat_tab.dart' show chatUnreadBadge;
import 'models.dart';
import 'outbox.dart';
import 'realtime.dart';
import 'ui/stickers.dart' show StickerCache;

/// 一个会话里已经拉到本地的一段消息(按 seq 升序;本地待发的排在最后,seq 为 0)。
class ChatTimeline {
  ChatTimeline(this.chatId);

  final int chatId;
  final List<ChatMessage> messages = [];
  bool loaded = false;
  bool hasOlder = true;
  bool hasNewer = false;
  bool loadingOlder = false;

  int get lastSeq {
    for (var i = messages.length - 1; i >= 0; i--) {
      if (messages[i].seq > 0) return messages[i].seq;
    }
    return 0;
  }

  int? indexOfSeq(int seq) {
    // 消息按 seq 有序,二分
    var lo = 0, hi = messages.length - 1;
    while (lo <= hi) {
      final mid = (lo + hi) >> 1;
      final s = messages[mid].seq;
      if (s == 0) {
        hi = mid - 1;
        continue;
      }
      if (s == seq) return mid;
      if (s < seq) {
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    for (var i = 0; i < messages.length; i++) {
      if (messages[i].seq == seq) return i;
    }
    return null;
  }

  ChatMessage? bySeq(int seq) {
    final i = indexOfSeq(seq);
    return i == null ? null : messages[i];
  }

  /// 放进一条服务端消息:同 seq 替换;同 random_id 的本地待发消息被它顶掉。
  void upsert(ChatMessage m) {
    if (m.randomId != null) {
      messages.removeWhere((x) => x.isLocal && x.randomId == m.randomId);
    }
    final i = indexOfSeq(m.seq);
    if (i != null) {
      messages[i] = m;
      return;
    }
    // 插到第一个比它大的 seq 之前(本地待发的 seq=0 永远在最后)
    var at = messages.length;
    for (var k = 0; k < messages.length; k++) {
      final s = messages[k].seq;
      if (s == 0 || s > m.seq) {
        at = k;
        break;
      }
    }
    messages.insert(at, m);
  }

  void addLocal(ChatMessage m) => messages.add(m);

  void replaceLocal(String randomId, ChatMessage m) {
    final i = messages.indexWhere((x) => x.isLocal && x.randomId == randomId);
    if (i >= 0) messages[i] = m;
  }

  void removeSeqs(Iterable<int> seqs) {
    final s = seqs.toSet();
    messages.removeWhere((m) => m.seq > 0 && s.contains(m.seq));
  }

  void clearUpTo(int seq) => messages.removeWhere((m) => m.seq > 0 && m.seq <= seq);
}

class _Typing {
  _Typing(this.action, this.until);
  final String action;
  final DateTime until;
}

/// 实时连接状态(顶栏「连接中…」用)。
enum ConnState { offline, connecting, online }

/// 消息模块的客户端状态(单例)。页面用 `AnimatedBuilder(animation: ChatStore.instance)` 听它。
///
/// 数据流:接口拉快照(会话列表、一页消息)→ 实时事件增量改 → 断线后 `sync` 补齐。
/// 事件按会话的 pts 应用:等于本地 pts+1 就应用,小于等于就是重复(丢掉),
/// 大于说明中间漏了(去补齐)—— 所以同一个事件从 WebSocket 和补齐接口各来一次也不会出错。
class ChatStore extends ChangeNotifier {
  ChatStore._();

  static final ChatStore instance = ChatStore._();

  ApiClient? _client;
  ChatApi? _api;
  ChatApi get api => _api!;
  ApiClient get client => _client!;
  bool get started => _api != null;

  int meId = 0;
  String? myUsername;

  final Map<int, ChatInfo> chats = {};
  final Map<int, ChatTimeline> timelines = {};
  final Map<int, ChatUser> users = {};
  List<ChatFolder> folders = [];
  int userPts = 0;

  bool loaded = false;
  bool loading = false;
  Object? loadError;
  ConnState conn = ConnState.offline;

  /// 正在看的会话(已读、推送去重用)
  int? viewing;

  final Map<int, Map<int, _Typing>> _typing = {};
  final Map<int, ({String url, String? thumb})> _signed = {};
  final Set<int> _signing = {};
  Timer? _signTimer;

  late final ChatRealtime realtime = ChatRealtime(this);
  late final Outbox outbox = Outbox(this);

  /// 这台设备发出去的 random_id。频道帖子以频道名义发出,事件里没有发送人 ——
  /// 靠它认出「这条是我发的」,别给自己记未读、别在自己的帖子上面画「以下为新消息」
  final Set<String> _sentRandomIds = <String>{};

  void rememberSent(String randomId) {
    _sentRandomIds.add(randomId);
    if (_sentRandomIds.length > 500) _sentRandomIds.remove(_sentRandomIds.first);
  }

  /// 显示的人名:我给他写了备注就用备注(和 Telegram 一样,群里、引用、服务消息都按我的备注叫)。
  String nameOf(Sender? s, [String fallback = '']) {
    if (s == null) return fallback;
    final alias = users[s.id]?.contactAlias ?? '';
    return alias.isNotEmpty ? alias : (s.name.isEmpty ? fallback : s.name);
  }

  bool isMine(ChatMessage m) =>
      (m.sender?.id == meId && !m.asChat) || (m.randomId != null && _sentRandomIds.contains(m.randomId));

  /// 给页面弹提示用的一次性消息(被踢出群、定时消息发不出去……)
  final StreamController<String> notices = StreamController<String>.broadcast();

  /// 发消息被平台处罚挡住(禁言、封号、群被封):原样把服务端的处罚说明转出去,
  /// 首页弹一条带「查看 / 申诉」的提示(S6:每个处罚都能申诉)
  final StreamController<Map<String, dynamic>> sanctioned = StreamController<Map<String, dynamic>>.broadcast();

  /// 同一个人切换账号时要清干净
  Future<void> start(ApiClient client) async {
    if (_client == client && started && client.userId == meId) return;
    stop();
    _client = client;
    _api = ChatApi(client);
    meId = client.userId ?? 0;
    await _loadCache();
    unawaited(refresh());
    realtime.start();
    CallController.instance.attach();
    unawaited(outbox.restore());
  }

  void stop() {
    CallController.instance.detach();
    realtime.stop();
    StickerCache.reset();
    _bots.clear();
    chats.clear();
    timelines.clear();
    users.clear();
    folders = [];
    userPts = 0;
    loaded = false;
    _api = null;
    _client = null;
    meId = 0;
    _updateBadge();
    notifyListeners();
  }

  // ---------------- 列表 ----------------

  /// 会话列表(置顶在前,其余按最后一条消息时间)。archived=true 取归档里的。
  List<ChatInfo> sortedChats({bool archived = false, ChatFolder? folder}) {
    final list = chats.values.where((c) {
      // 公开群 / 频道「先看看」时卡片也在 chats 里,但我不在里面:不进列表
      if (!c.can('in_chat')) return false;
      if (folder != null) return folder.matches(c);
      return c.my.archived == archived;
    }).toList();
    list.sort((a, b) {
      final pa = a.my.pinnedRank, pb = b.my.pinnedRank;
      if (pa != null || pb != null) {
        if (pa == null) return 1;
        if (pb == null) return -1;
        if (pa != pb) return pa.compareTo(pb);
      }
      return b.sortTime.compareTo(a.sortTime);
    });
    return list;
  }

  int unreadOf(ChatInfo c) => c.unread > 0 ? c.unread : (c.my.markedUnread ? 1 : 0);

  void _updateBadge() {
    var n = 0;
    for (final c in chats.values) {
      if (!c.my.muted && !c.my.archived && unreadOf(c) > 0) n++;
    }
    if (chatUnreadBadge.value != n) chatUnreadBadge.value = n;
  }

  @override
  void notifyListeners() {
    _updateBadge();
    super.notifyListeners();
    _scheduleCacheSave();
  }

  Future<void> refresh() async {
    if (!started) return;
    loading = true;
    try {
      final r = await api.dialogs();
      final seen = <int>{};
      for (final c in r.items) {
        seen.add(c.id);
        final old = chats[c.id];
        if (old == null) {
          chats[c.id] = c;
        } else {
          old.absorb(c);
          old.unread = c.unread;
          old.unreadMentions = c.unreadMentions;
          old.lastMessage = c.lastMessage;
        }
        if (c.peer != null) users[c.peer!.id] = c.peer!;
      }
      // 列表里没有的就是退出 / 被移出 / 删掉了的;「先看看」的公开会话本来就不在列表里,别误删
      chats.removeWhere((id, c) => !seen.contains(id) && c.can('in_chat'));
      if (r.userPts > userPts) userPts = r.userPts;
      final first = !loaded;
      loaded = true;
      loadError = null;
      // 拉列表的这段时间里来的事件在快照之后:补一次齐,别漏
      if (first && conn == ConnState.online) unawaited(sync());
      unawaited(_loadFolders());
      unawaited(_loadMe());
      unawaited(_loadContacts());
    } catch (e) {
      loadError = e;
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> _loadFolders() async {
    try {
      folders = await api.folders();
      notifyListeners();
    } catch (_) {}
  }

  /// 联系人(带我写的备注)放进 users:群里、引用里显示名字时用得上
  Future<void> _loadContacts() async {
    try {
      for (final u in await api.contacts()) {
        users[u.id] = u;
      }
      notifyListeners();
    } catch (_) {}
  }

  Future<void> _loadMe() async {
    try {
      final me = await api.me();
      myUsername = me['username'] as String?;
    } catch (_) {}
  }

  Future<ChatInfo?> ensureChat(int id) async {
    final c = chats[id];
    if (c != null) return c;
    try {
      final n = await api.chat(id);
      chats[id] = n;
      if (n.peer != null) users[n.peer!.id] = n.peer!;
      notifyListeners();
      return n;
    } catch (_) {
      return null;
    }
  }

  Future<void> refreshChat(int id) async {
    try {
      final n = await api.chat(id);
      final old = chats[id];
      if (old == null) {
        chats[id] = n;
      } else {
        old.absorb(n);
      }
      notifyListeners();
    } catch (_) {}
  }

  /// 打开 / 建一个私聊,放进列表。
  Future<ChatInfo> openPrivate(int userId) async {
    final c = await api.openPrivate(userId);
    final old = chats[c.id];
    if (old == null) {
      chats[c.id] = c;
    } else {
      old.absorb(c);
    }
    notifyListeners();
    return chats[c.id]!;
  }

  Future<ChatInfo> openSaved() async {
    final c = await api.openSaved();
    chats.putIfAbsent(c.id, () => c);
    notifyListeners();
    return chats[c.id]!;
  }

  void putChat(ChatInfo c) {
    final old = chats[c.id];
    if (old == null) {
      chats[c.id] = c;
    } else {
      old.absorb(c);
    }
    notifyListeners();
  }

  // ---------------- 消息 ----------------

  ChatTimeline timeline(int chatId) => timelines.putIfAbsent(chatId, () => ChatTimeline(chatId));

  Future<void> loadLatest(int chatId) async {
    final t = timeline(chatId);
    final r = await api.messages(chatId, limit: 50);
    final locals = t.messages.where((m) => m.isLocal).toList();
    t.messages
      ..clear()
      ..addAll(r.messages);
    for (final m in locals) {
      if (!r.messages.any((x) => x.randomId != null && x.randomId == m.randomId)) {
        t.messages.add(m);
      }
    }
    t.hasOlder = r.hasOlder;
    t.hasNewer = false;
    t.loaded = true;
    _rememberMedia(r.messages);
    notifyListeners();
  }

  Future<void> loadOlder(int chatId) async {
    final t = timeline(chatId);
    if (t.loadingOlder || !t.hasOlder) return;
    final first = t.messages.firstWhere((m) => m.seq > 0,
        orElse: () => ChatMessage(chatId: chatId, seq: 0, kind: 'text', createdAt: DateTime.now()));
    if (first.seq == 0) return;
    t.loadingOlder = true;
    notifyListeners();
    try {
      final r = await api.messages(chatId, before: first.seq, limit: 50);
      for (final m in r.messages) {
        t.upsert(m);
      }
      t.hasOlder = r.hasOlder;
      _rememberMedia(r.messages);
    } finally {
      t.loadingOlder = false;
      notifyListeners();
    }
  }

  /// 跳到某一条(回复引用、搜索结果、置顶条):拉那一条附近的一页,替换本地时间线。
  Future<void> loadAround(int chatId, int seq) async {
    final t = timeline(chatId);
    if (t.bySeq(seq) != null) return;
    final r = await api.messages(chatId, around: seq, limit: 60);
    t.messages
      ..removeWhere((m) => !m.isLocal)
      ..insertAll(0, r.messages);
    t.hasOlder = r.hasOlder;
    t.hasNewer = r.hasNewer;
    t.loaded = true;
    _rememberMedia(r.messages);
    notifyListeners();
  }

  /// 把会话标成读到最后一条(节流:同一个会话 1 秒内只报一次)。
  final Map<int, Timer> _readTimers = {};

  void markRead(int chatId) {
    final c = chats[chatId];
    if (c == null) return;
    final t = timelines[chatId];
    final last = t?.lastSeq ?? c.lastSeq;
    if (last <= c.my.lastReadSeq && !c.my.markedUnread && c.unread == 0) return;
    c.unread = 0;
    c.unreadMentions = 0;
    c.my.markedUnread = false;
    if (last > c.my.lastReadSeq) c.my.lastReadSeq = last;
    notifyListeners();
    _readTimers[chatId]?.cancel();
    _readTimers[chatId] = Timer(const Duration(milliseconds: 600), () {
      _readTimers.remove(chatId);
      api.read(chatId, last).catchError((_) {});
    });
  }

  // ---------------- 正在输入、在线 ----------------

  List<(int, String)> typingIn(int chatId) {
    final m = _typing[chatId];
    if (m == null) return const [];
    final now = DateTime.now();
    m.removeWhere((_, t) => t.until.isBefore(now));
    return [for (final e in m.entries) (e.key, e.value.action)];
  }

  String? typingLabel(ChatInfo c) {
    final t = typingIn(c.id);
    if (t.isEmpty) return null;
    final verb = switch (t.first.$2) {
      'record_voice' => '正在录音',
      'upload_photo' => '正在发图片',
      'upload_video' => '正在发视频',
      'upload_file' => '正在发文件',
      'choose_sticker' => '正在挑贴纸',
      _ => '正在输入',
    };
    if (c.isPrivate) return '$verb…';
    final names = [for (final x in t.take(2)) users[x.$1]?.displayName ?? '有人'];
    return t.length > 2 ? '${names.join('、')} 等 ${t.length} 人$verb…' : '${names.join('、')} $verb…';
  }

  // ---------------- 机器人(#355) ----------------

  final Map<int, List<BotInfo>> _bots = {};
  final Map<int, Future<List<BotInfo>>> _botsLoading = {};

  /// 这个会话里的机器人(命令、菜单按钮、简介);还没拉过是空列表
  List<BotInfo> botsOf(int chatId) => _bots[chatId] ?? const [];

  /// 拉一次会话里的机器人。进会话时刷新一次就够 —— 群里加减机器人不常见,
  /// 不值得为它在每条成员变动事件上都去问一遍
  Future<List<BotInfo>> loadBots(int chatId, {bool refresh = false}) {
    if (!refresh && _bots.containsKey(chatId)) return Future.value(_bots[chatId]!);
    return _botsLoading[chatId] ??= api
        .botInfo(chatId)
        .then((v) {
          _bots[chatId] = v;
          notifyListeners();
          return v;
        })
        .catchError((Object _) => _bots[chatId] ?? const <BotInfo>[])
        .whenComplete(() => _botsLoading.remove(chatId));
  }

  // ---------------- 媒体地址 ----------------

  /// 事件里来的媒体没有签名:攒一批去换(80ms 内的一起换)。
  ({String url, String? thumb})? signedMedia(MediaInfo m) {
    if (m.signed) return (url: m.url, thumb: m.thumb);
    final s = _signed[m.id];
    if (s != null) return s;
    if (_signing.add(m.id)) {
      _signTimer ??= Timer(const Duration(milliseconds: 80), _flushSigning);
    }
    return null;
  }

  Future<void> _flushSigning() async {
    _signTimer = null;
    final ids = _signing.toList();
    if (ids.isEmpty || !started) return;
    try {
      final r = await api.signMedia(ids);
      for (final e in r.entries) {
        _signed[int.parse(e.key)] = (url: '${e.value['url']}', thumb: e.value['thumb'] as String?);
      }
    } catch (_) {
    } finally {
      _signing.removeAll(ids);
      notifyListeners();
    }
  }

  void _rememberMedia(Iterable<ChatMessage> msgs) {
    for (final m in msgs) {
      for (final x in m.media) {
        if (x.signed) _signed[x.id] = (url: x.url, thumb: x.thumb);
      }
    }
  }

  // ---------------- 实时事件 ----------------

  void onConnState(ConnState s) {
    conn = s;
    notifyListeners();
  }

  /// 连上(或重连上)之后:补齐断线期间漏掉的。
  Future<void> onReady(int serverUserPts) async {
    if (!loaded) {
      await refresh();
      return;
    }
    await sync();
  }

  bool _syncing = false;
  bool _syncAgain = false;

  Future<void> sync() async {
    if (!started) return;
    if (_syncing) {
      _syncAgain = true;
      return;
    }
    _syncing = true;
    try {
      do {
        _syncAgain = false;
        final r = await api.sync(userPts, {for (final c in chats.values) c.id: c.pts});
        if (r['user_reset'] == true) {
          await refresh();
        } else {
          for (final e in (r['user_events'] as List? ?? const [])) {
            final m = (e as Map).cast<String, dynamic>();
            _applyUser((m['pts'] as num).toInt(), '${m['type']}', _asMap(m['data']));
          }
          if ((r['user_pts'] as num? ?? 0) > userPts) userPts = (r['user_pts'] as num).toInt();
        }
        final cs = (r['chats'] as Map? ?? const {});
        for (final e in cs.entries) {
          final id = int.parse('${e.key}');
          final v = (e.value as Map).cast<String, dynamic>();
          if (v['gone'] == true) {
            chats.remove(id);
            timelines.remove(id);
            continue;
          }
          if (v['reset'] == true) {
            await refreshChat(id);
            if (timelines[id]?.loaded == true) await loadLatest(id);
            continue;
          }
          for (final ev in (v['events'] as List? ?? const [])) {
            final m = (ev as Map).cast<String, dynamic>();
            _applyChat(id, (m['pts'] as num).toInt(), '${m['type']}', _asMap(m['data']),
                force: true);
          }
          final pts = (v['pts'] as num?)?.toInt();
          if (pts != null && chats[id] != null && pts > chats[id]!.pts) chats[id]!.pts = pts;
        }
      } while (_syncAgain);
    } catch (_) {
      // 补齐失败:下次连上再补
    } finally {
      _syncing = false;
      notifyListeners();
    }
  }

  static Map<String, dynamic> _asMap(Object? v) =>
      v is Map ? v.cast<String, dynamic>() : <String, dynamic>{};

  void handleFrame(Map<String, dynamic> f) {
    switch (f['t']) {
      case 'ev':
        _applyChat((f['chat_id'] as num).toInt(), (f['pts'] as num).toInt(), '${f['type']}',
            _asMap(f['data']));
      case 'uev':
        final pts = (f['pts'] as num).toInt();
        if (pts <= userPts) return;
        if (pts > userPts + 1) {
          unawaited(sync());
          return;
        }
        _applyUser(pts, '${f['type']}', _asMap(f['data']));
      case 'typing':
        final chatId = (f['chat_id'] as num).toInt();
        final uid = (f['user_id'] as num).toInt();
        final action = '${f['action']}';
        final m = _typing.putIfAbsent(chatId, () => {});
        if (action == 'cancel') {
          m.remove(uid);
        } else {
          m[uid] = _Typing(action, DateTime.now().add(const Duration(seconds: 6)));
          Timer(const Duration(seconds: 6, milliseconds: 100), notifyListeners);
        }
        notifyListeners();
      case 'presence':
        final uid = (f['user_id'] as num).toInt();
        final ls = LastSeen.fromJson(f);
        users[uid]?.lastSeen = ls;
        for (final c in chats.values) {
          if (c.peer?.id == uid) c.peer!.lastSeen = ls;
        }
        notifyListeners();
      default:
        realtime.onOtherFrame(f);
    }
  }

  void _applyChat(int chatId, int pts, String type, Map<String, dynamic> d, {bool force = false}) {
    // 列表还没拉到(冷启动只有缓存):不应用,拉完列表会补一次齐
    if (!loaded) return;
    // 对方的消息到了,他的「正在输入」就该消失 —— 不等 6 秒超时。
    // 放在认不认识这个会话的判断前面:新私聊的第一条走的是 _adopt,不经过下面的 msg 分支
    if (type == 'msg') {
      final sid = (_asMap(d['sender'])['id'] as num?)?.toInt();
      if (sid != null && _typing[chatId]?.remove(sid) != null) notifyListeners();
    }
    final c = chats[chatId];
    if (c == null) {
      // 不认识的会话(新私聊、被拉进群、删了的私聊对方又发来):拉卡片
      if (type == 'msg' || type == 'member') unawaited(_adopt(chatId));
      return;
    }
    if (pts <= c.pts) return; // 重复
    if (pts > c.pts + 1 && !force) {
      unawaited(sync());
      return;
    }
    c.pts = pts;
    final t = timelines[chatId];
    switch (type) {
      case 'msg':
        final m = ChatMessage.fromJson(d);
        if (m.seq > c.lastSeq) c.lastSeq = m.seq;
        c.lastMessage = m;
        final mine = isMine(m);
        if (t != null && t.loaded && !t.hasNewer) t.upsert(m);
        if (mine) {
          if (m.seq > c.my.lastReadSeq) c.my.lastReadSeq = m.seq;
          c.unread = 0;
        } else if (viewing != chatId) {
          c.unread += 1;
          if (_mentionsMe(m, t)) c.unreadMentions += 1;
        } else {
          markRead(chatId);
        }
        _typing[chatId]?.remove(m.sender?.id);
        if (m.isService) _onService(c, m);
      case 'edit':
        final m = ChatMessage.fromJson(d);
        t?.upsert(m);
        if (c.lastMessage?.seq == m.seq) c.lastMessage = m;
      case 'del':
        final seqs = [for (final x in (d['seqs'] as List? ?? const [])) (x as num).toInt()];
        t?.removeSeqs(seqs);
        if (c.lastMessage != null && seqs.contains(c.lastMessage!.seq)) {
          c.lastMessage = t?.messages.lastWhere((x) => x.seq > 0,
              orElse: () => c.lastMessage!);
          if (c.lastMessage != null && seqs.contains(c.lastMessage!.seq)) {
            c.lastMessage = null;
            unawaited(refreshChat(chatId));
          }
        }
      case 'clear':
        final upto = (d['upto'] as num?)?.toInt() ?? c.lastSeq;
        t?.clearUpTo(upto);
        c.lastMessage = null;
        c.unread = 0;
      case 'react':
        final seq = (d['seq'] as num).toInt();
        final m = t?.bySeq(seq);
        if (m != null) {
          final actorMe = (d['actor'] as num?)?.toInt() == meId;
          final emoji = '${d['emoji']}';
          final added = d['added'] == true;
          final mineBefore = {for (final r in m.reactions) if (r.me) r.emoji};
          if (actorMe) {
            added ? mineBefore.add(emoji) : mineBefore.remove(emoji);
          }
          final list = [
            for (final r in (d['reactions'] as List? ?? const []))
              ReactionCount('${(r as Map)['emoji']}', (r['count'] as num).toInt(),
                  mineBefore.contains('${r['emoji']}'))
          ];
          t!.upsert(m.copyWith(reactions: list));
        }
      case 'read':
        final uid = (d['user_id'] as num).toInt();
        final seq = (d['seq'] as num).toInt();
        if (uid != meId && seq > c.peerReadSeq) c.peerReadSeq = seq;
      case 'pin':
        final seqs = [for (final x in (d['seqs'] as List? ?? const [])) (x as num).toInt()];
        final pinned = d['pinned'] == true;
        if (t != null) {
          for (final s in seqs) {
            final m = t.bySeq(s);
            if (m != null) t.upsert(m.copyWith(pinned: pinned));
          }
          if (!pinned && seqs.isEmpty) {
            for (final m in [...t.messages.where((x) => x.pinned)]) {
              t.upsert(m.copyWith(pinned: false));
            }
          }
        }
        pinnedVersion.value++;
      case 'poll':
        final seq = (d['seq'] as num).toInt();
        final m = t?.bySeq(seq);
        if (m?.poll != null) {
          t!.upsert(m!.copyWith(poll: m.poll!.mergeResults(_asMap(d['poll']))));
        }
      case 'views':
        final seq = (d['seq'] as num).toInt();
        final m = t?.bySeq(seq);
        if (m != null) t!.upsert(m.copyWith(views: (d['views'] as num).toInt()));
      case 'chat':
        if (d['deleted'] == true) {
          chats.remove(chatId);
          timelines.remove(chatId);
          notices.add('「${c.title}」已经解散了');
        } else {
          if (d['title'] is String) c.title = d['title'] as String;
          if (d['about'] is String) c.about = d['about'] as String;
          if (d['photo'] is String) c.photo = d['photo'] as String;
          if (d.containsKey('username')) c.username = d['username'] as String?;
          if (d['settings'] is Map) {
            c.settings = _asMap(d['settings']);
            // 成员默认权限、慢速模式改了:我能做什么(perms)是服务端按角色算的,拉一次卡片
            unawaited(refreshChat(chatId));
          }
        }
      case 'member':
        final uid = (d['user_id'] as num).toInt();
        if (uid == meId) {
          final role = '${d['role']}';
          if (role == 'left' || role == 'banned') {
            if (role == 'banned') notices.add('你已被移出「${c.title}」');
            chats.remove(chatId);
            timelines.remove(chatId);
          } else {
            unawaited(refreshChat(chatId));
          }
        } else {
          unawaited(refreshChat(chatId));
        }
    }
    notifyListeners();
  }

  /// 置顶消息有变化(聊天页顶部的置顶条据此重拉)
  final ValueNotifier<int> pinnedVersion = ValueNotifier<int>(0);

  bool _mentionsMe(ChatMessage m, ChatTimeline? t) {
    for (final e in m.entities) {
      if (e.type == 'text_mention' && e.userId == meId) return true;
      if (e.type == 'mention' && myUsername != null) {
        final s = _utf16Slice(m.text, e.offset, e.length).replaceFirst('@', '').toLowerCase();
        if (s == myUsername!.toLowerCase()) return true;
      }
    }
    if (m.replyToSeq != null) {
      final r = t?.bySeq(m.replyToSeq!);
      if (r?.sender?.id == meId) return true;
    }
    return false;
  }

  static String _utf16Slice(String s, int offset, int length) {
    // Dart 的 String 下标本来就是 UTF-16 码元
    if (offset < 0 || offset + length > s.length) return '';
    return s.substring(offset, offset + length);
  }

  void _onService(ChatInfo c, ChatMessage m) {
    final a = m.service?['action'];
    if (a == 'title_change' && m.service?['title'] is String) {
      c.title = m.service!['title'] as String;
    }
  }

  Future<void> _adopt(int chatId) async {
    try {
      final n = await api.chat(chatId);
      chats[chatId] = n;
      if (n.peer != null) users[n.peer!.id] = n.peer!;
      // 卡片里的 unread 是服务端算好的
      final r = await api.dialogs();
      for (final x in r.items) {
        if (x.id == chatId) {
          n.unread = x.unread;
          n.unreadMentions = x.unreadMentions;
          n.lastMessage = x.lastMessage;
        }
      }
      notifyListeners();
    } catch (_) {}
  }

  /// 所有用户事件(实时来的和补齐来的)原样转一份出去:视频模块听 `notify`(互动消息角标)、
  /// `video`(我的稿件状态变了),不用各自再连一条 WebSocket
  final StreamController<({String type, Map<String, dynamic> data})> userEvents =
      StreamController.broadcast();

  void _applyUser(int pts, String type, Map<String, dynamic> d) {
    if (pts > userPts) userPts = pts;
    userEvents.add((type: type, data: d));
    switch (type) {
      case 'chat_join':
        final chat = _asMap(d['chat']);
        final id = (chat['id'] as num?)?.toInt();
        if (id != null && d['hidden'] != true) unawaited(_adopt(id));
      case 'chat_leave':
        final id = (d['chat_id'] as num?)?.toInt();
        if (id != null) {
          chats.remove(id);
          if (d['role'] != 'hidden') timelines.remove(id);
        }
      case 'dialog':
        final id = (d['chat_id'] as num?)?.toInt();
        final c = id == null ? null : chats[id];
        if (c != null) {
          c.my.merge(d);
          if (d['last_read_seq'] is int && c.my.lastReadSeq >= c.lastSeq) {
            c.unread = 0;
            c.unreadMentions = 0;
          }
        }
      case 'hide':
        final id = (d['chat_id'] as num?)?.toInt();
        final seqs = [for (final x in (d['seqs'] as List? ?? const [])) (x as num).toInt()];
        if (id != null) timelines[id]?.removeSeqs(seqs);
      case 'folders':
        unawaited(_loadFolders());
      case 'block':
        final uid = (d['user_id'] as num?)?.toInt();
        if (uid != null) {
          unawaited(api.user(uid).then((u) {
            users[uid] = u;
            for (final c in chats.values) {
              if (c.peer?.id == uid) c.peer = u;
            }
            notifyListeners();
          }).catchError((_) {}));
        }
      case 'media':
        outbox.onMediaEvent(d);
      case 'join_request':
        notices.add('有人申请加入你管理的群');
      case 'join_decided':
        notices.add(d['approved'] == true ? '入群申请通过了' : '入群申请没有通过');
        if (d['approved'] == true) unawaited(refresh());
      case 'scheduled_failed':
        notices.add('一条定时消息没发出去:${d['reason'] ?? ''}');
    }
    notifyListeners();
  }

  // ---------------- 本地缓存 ----------------
  //
  // 会话列表(带每个会话的最后一条)落本地:冷启动先画缓存、再拿接口数据覆盖,
  // 不用对着一个转圈等;没网的时候列表也还在。

  // v2:卡片里带上 perms(列表按 in_chat 过滤,没有 perms 的旧缓存画不出来)
  static String _cacheKey(int uid) => 'chat_cache_v2_$uid';
  Timer? _saveTimer;

  void _scheduleCacheSave() {
    if (!started || !loaded) return;
    _saveTimer?.cancel();
    _saveTimer = Timer(const Duration(seconds: 2), _saveCache);
  }

  Future<void> _saveCache() async {
    if (!started) return;
    try {
      final sp = await SharedPreferences.getInstance();
      final data = {
        'user_pts': 0, // 缓存不参与补齐:冷启动总是先拉一次完整列表
        'chats': [for (final c in chats.values.where((c) => c.can('in_chat')).take(200)) _chatToCache(c)],
      };
      await sp.setString(_cacheKey(meId), jsonEncode(data));
    } catch (_) {}
  }

  Map<String, dynamic> _chatToCache(ChatInfo c) => {
        'id': c.id,
        'type': c.type,
        'title': c.title,
        'photo': c.photo,
        'username': c.username,
        'member_count': c.memberCount,
        'perms': c.perms,
        'my': {
          'role': c.my.role,
          'pinned': c.my.pinned,
          'pinned_rank': c.my.pinnedRank,
          'archived': c.my.archived,
          'muted_until': c.my.mutedUntil?.toUtc().toIso8601String(),
          'marked_unread': c.my.markedUnread,
          'last_read_seq': c.my.lastReadSeq,
        },
        'unread': c.unread,
        'last_message': c.lastMessage == null ? null : messageToCache(c.lastMessage!),
        if (c.peer != null)
          'peer': {'id': c.peer!.id, 'name': c.peer!.name, 'avatar': c.peer!.avatar,
                   'username': c.peer!.username, 'contact_alias': c.peer!.contactAlias,
                   'is_contact': c.peer!.isContact},
      };

  Future<void> _loadCache() async {
    try {
      final sp = await SharedPreferences.getInstance();
      final raw = sp.getString(_cacheKey(meId));
      if (raw == null) return;
      final data = jsonDecode(raw) as Map;
      for (final c in data['chats'] as List) {
        final info = ChatInfo.fromJson(c);
        // 缓存里的会话 pts 置 0:接口数据来之前不拿它去补齐
        info.pts = 0;
        chats[info.id] = info;
      }
      notifyListeners();
    } catch (_) {}
  }

  /// 会话被清空(退出登录、换账号、token 失效)时断开实时连接、清掉内存和本地缓存。
  ///
  /// `ApiClient.onSessionCleared` 只有一个槽,埋点也挂在上面(Analytics.init 每次进首页
  /// 都会重新赋值),所以这里是「串」上去而不是覆盖:发现槽里不是自己就把原来的记下来再换。
  static void installSessionHook() {
    final cur = ApiClient.onSessionCleared;
    if (cur == _onSessionCleared) return;
    _prevSessionHook = cur;
    ApiClient.onSessionCleared = _onSessionCleared;
  }

  static void Function()? _prevSessionHook;

  static void _onSessionCleared() {
    _prevSessionHook?.call();
    final uid = instance.meId;
    instance._saveTimer?.cancel();
    instance.stop();
    if (uid > 0) unawaited(clearCacheFor(uid));
  }

  /// 退出登录时清掉这台设备上的聊天缓存(S5:用户的数据用户说了算)。
  static Future<void> clearCacheFor(int uid) async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.remove(_cacheKey(uid));
      await sp.remove('chat_cache_v1_$uid');
      await sp.remove(Outbox.keyFor(uid));
    } catch (_) {}
  }
}


/// 会话列表缓存里的「最后一条」:只存列表预览([previewOf])用得到的字段。
///
/// 少存一样,离线打开时预览就和在线时不一样:原来没存剧透实体,离线时剧透的字在列表里直接露出来;
/// 没存通话详情和语音时长,显示成「[通话]」「[语音] 0:00」。守卫见 test/chat_cache_test.dart
Map<String, dynamic> messageToCache(ChatMessage m) => {
      'chat_id': m.chatId,
      'seq': m.seq,
      'kind': m.kind,
      'text': m.text,
      'created_at': m.createdAt.toUtc().toIso8601String(),
      if (m.sender != null) 'sender': {'id': m.sender!.id, 'name': m.sender!.name},
      if (m.service != null) 'service': m.service,
      // 预览只看剧透那几段(要打码);别的样式不影响一行预览
      'entities': [for (final e in m.entities) if (e.type == 'spoiler') e.toJson()],
      'media': [
        for (final x in m.media) {'id': x.id, 'kind': x.kind, 'name': x.name, 'duration_ms': x.durationMs},
      ],
      if (m.call != null) 'call': m.call,
      if (m.poll != null) 'poll': {'id': m.poll!.id, 'question': m.poll!.question},
      if (m.dice != null) 'dice': m.dice,
      if (m.sticker != null) 'sticker': {'emoji': m.sticker!['emoji']},
      if (m.location != null) 'location': {'title': m.location!['title']},
      if (m.contact != null) 'contact': {'name': m.contact!['name']},
    };
