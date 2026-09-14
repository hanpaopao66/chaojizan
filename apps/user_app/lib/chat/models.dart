/// 消息模块的数据形状(和服务端 DEV-PROMPTS-40 §5.2 逐字段对应)。
///
/// 解析一律宽松:服务端多给的字段忽略、少给的取缺省 —— 老版本 App 碰到新服务端不能崩。
library;

int _int(Object? v, [int d = 0]) => v is int ? v : (v is num ? v.toInt() : int.tryParse('$v') ?? d);
String _str(Object? v, [String d = '']) => v is String ? v : (v == null ? d : '$v');
bool _bool(Object? v, [bool d = false]) => v is bool ? v : d;
DateTime? _time(Object? v) => v is String ? DateTime.tryParse(v)?.toLocal() : null;
Map<String, dynamic> _map(Object? v) =>
    v is Map ? v.cast<String, dynamic>() : <String, dynamic>{};
List<Object?> _list(Object? v) => v is List ? v : const [];

/// 最后上线(隐私过滤之后的)。
class LastSeen {
  const LastSeen({this.online = false, this.at, this.approx});

  final bool online;
  final DateTime? at;

  /// recently / week / month / long;为空表示给了精确时间
  final String? approx;

  factory LastSeen.fromJson(Object? j) {
    final m = _map(j);
    return LastSeen(online: _bool(m['online']), at: _time(m['at']), approx: m['approx'] as String?);
  }

  /// 顶栏副标题那一句。
  String label({DateTime? now}) {
    if (online) return '在线';
    final t = at;
    if (t != null) {
      final n = now ?? DateTime.now();
      final d = n.difference(t);
      String hm(DateTime x) =>
          '${x.hour.toString().padLeft(2, '0')}:${x.minute.toString().padLeft(2, '0')}';
      if (d.inMinutes < 1) return '刚刚在线';
      if (d.inMinutes < 60) return '${d.inMinutes} 分钟前在线';
      if (t.year == n.year && t.month == n.month && t.day == n.day) return '今天 ${hm(t)} 在线';
      final y = n.subtract(const Duration(days: 1));
      if (t.year == y.year && t.month == y.month && t.day == y.day) return '昨天 ${hm(t)} 在线';
      return '${t.month}月${t.day}日 在线';
    }
    return switch (approx) {
      'recently' => '最近在线',
      'week' => '一周内在线',
      'month' => '一月内在线',
      _ => '很久以前在线',
    };
  }
}

/// 一个人的名片(按「我」的视角过滤过隐私;**永远没有手机号**)。
class ChatUser {
  ChatUser({
    required this.id,
    required this.name,
    this.username,
    this.avatar = '',
    this.bio = '',
    this.tagsBadges = const TagsBadges(),
    this.publicId,
    this.lastSeen = const LastSeen(),
    this.isContact = false,
    this.contactAlias = '',
    this.blocked = false,
    this.isBot = false,
    this.isSelf = false,
  });

  final int id;
  final String name;
  final String? username;
  final String avatar;
  final String bio;

  /// 标签和勋章。只有单人资料卡(`/social/v1/users/{id}` 那类)带,列表里的名片是空的
  final TagsBadges tagsBadges;
  final String? publicId;
  LastSeen lastSeen;
  final bool isContact;
  final String contactAlias;
  final bool blocked;
  final bool isBot;
  final bool isSelf;

  String get displayName => contactAlias.isNotEmpty ? contactAlias : name;

  factory ChatUser.fromJson(Object? j) {
    final m = _map(j);
    return ChatUser(
      id: _int(m['id']),
      name: _str(m['name']),
      username: m['username'] as String?,
      avatar: _str(m['avatar']),
      bio: _str(m['bio']),
      tagsBadges: TagsBadges.fromJson(m),
      publicId: m['public_id'] as String?,
      lastSeen: LastSeen.fromJson(m['last_seen']),
      isContact: _bool(m['is_contact']),
      contactAlias: _str(m['contact_alias']),
      blocked: _bool(m['blocked']),
      isBot: _bool(m['is_bot']),
      isSelf: _bool(m['is_self']),
    );
  }
}

/// 名片上的标签和勋章(服务端 services/badges.py)。已经按「我」的视角过滤过:
/// 别人隐藏了的这里就没有,和「没有」长得一样;自己看自己时隐藏了的也在,[tagsHidden] / [ProfileBadge.hidden] 标着。
class TagsBadges {
  const TagsBadges({this.tags = const [], this.tagsHidden = false, this.badges = const []});

  /// 用户自己写的标签
  final List<String> tags;

  /// 整组标签对别人隐藏了(只有自己看自己时才会是 true)
  final bool tagsHidden;

  /// 平台按公开条件发的勋章
  final List<ProfileBadge> badges;

  bool get isEmpty => tags.isEmpty && badges.isEmpty;

  /// 从资料卡、UP 主空间的 `user`(tags / tags_hidden / badges 三个字段)读
  factory TagsBadges.fromJson(Object? j) {
    final m = _map(j);
    return TagsBadges(
      tags: [for (final t in _list(m['tags'])) if (t is String && t.isNotEmpty) t],
      tagsHidden: _bool(m['tags_hidden']),
      badges: [
        for (final b in _list(m['badges']))
          if (_map(b)['key'] is String) ProfileBadge.fromJson(b),
      ],
    );
  }
}

/// 一枚勋章。[condition] 是平台发它的公开条件,和透明中心「勋章」那一栏一字不差。
class ProfileBadge {
  const ProfileBadge({
    required this.key,
    required this.name,
    required this.icon,
    this.condition = '',
    this.hidden = false,
    this.earned = true,
  });

  final String key;
  final String name;

  /// 一个汉字,画在小方块里
  final String icon;
  final String condition;

  /// 对别人隐藏了(只有自己看自己时才会是 true)
  final bool hidden;

  /// 拿到了没有。只有「标签和勋章」设置页会列出没拿到的,资料卡上的都是拿到了的
  final bool earned;

  factory ProfileBadge.fromJson(Object? j) {
    final m = _map(j);
    return ProfileBadge(
      key: _str(m['key']),
      name: _str(m['name']),
      icon: _str(m['icon']),
      condition: _str(m['condition']),
      hidden: _bool(m['hidden']),
      earned: _bool(m['earned'], true),
    );
  }
}

class MsgEntity {
  const MsgEntity(this.type, this.offset, this.length, {this.url, this.userId, this.language});

  final String type;
  final int offset;
  final int length;
  final String? url;
  final int? userId;
  final String? language;

  factory MsgEntity.fromJson(Object? j) {
    final m = _map(j);
    return MsgEntity(_str(m['type']), _int(m['offset']), _int(m['length']),
        url: m['url'] as String?,
        userId: m['user_id'] is int ? m['user_id'] as int : null,
        language: m['language'] as String?);
  }

  Map<String, dynamic> toJson() => {
        'type': type,
        'offset': offset,
        'length': length,
        if (url != null) 'url': url,
        if (userId != null) 'user_id': userId,
        if (language != null) 'language': language,
      };
}

class MediaInfo {
  const MediaInfo({
    required this.id,
    required this.kind,
    this.w = 0,
    this.h = 0,
    this.size = 0,
    this.mime = '',
    this.name = '',
    this.durationMs = 0,
    this.waveform = const [],
    this.url = '',
    this.thumb,
    this.loop = false,
  });

  final int id;
  final String kind;
  final int w;
  final int h;
  final int size;
  final String mime;
  final String name;
  final int durationMs;
  final List<int> waveform;
  final String url;
  final String? thumb;
  final bool loop;

  /// 地址能直接用:带了签名,或者本来就是公开图(贴纸走公开桶 /img/…)
  bool get signed => url.contains('?u=') || url.contains('&u=') || url.startsWith('/img/');

  factory MediaInfo.fromJson(Object? j) {
    final m = _map(j);
    return MediaInfo(
      id: _int(m['id']),
      kind: _str(m['kind']),
      w: _int(m['w']),
      h: _int(m['h']),
      size: _int(m['size']),
      mime: _str(m['mime']),
      name: _str(m['name']),
      durationMs: _int(m['duration_ms']),
      waveform: [for (final x in _list(m['waveform'])) _int(x)],
      url: _str(m['url']),
      thumb: m['thumb'] as String?,
      loop: _bool(m['loop']),
    );
  }

  MediaInfo withUrls(String url, String? thumb) => MediaInfo(
      id: id,
      kind: kind,
      w: w,
      h: h,
      size: size,
      mime: mime,
      name: name,
      durationMs: durationMs,
      waveform: waveform,
      url: url,
      thumb: thumb,
      loop: loop);
}

class ReactionCount {
  const ReactionCount(this.emoji, this.count, this.me);

  final String emoji;
  final int count;
  final bool me;

  factory ReactionCount.fromJson(Object? j) {
    final m = _map(j);
    return ReactionCount(_str(m['emoji']), _int(m['count']), _bool(m['me']));
  }
}

class PollOption {
  const PollOption(this.text, this.votes);
  final String text;
  final int? votes;
}

class PollInfo {
  PollInfo({
    required this.id,
    required this.question,
    required this.options,
    this.totalVoters = 0,
    this.multiple = false,
    this.quiz = false,
    this.correct,
    this.explanation = '',
    this.anonymous = true,
    this.closed = false,
    this.closeAt,
    this.myVotes = const [],
  });

  final int id;
  final String question;
  final List<PollOption> options;
  final int totalVoters;
  final bool multiple;
  final bool quiz;
  final int? correct;
  final String explanation;
  final bool anonymous;
  final bool closed;
  final DateTime? closeAt;
  final List<int> myVotes;

  bool get voted => myVotes.isNotEmpty;

  factory PollInfo.fromJson(Object? j) {
    final m = _map(j);
    return PollInfo(
      id: _int(m['id']),
      question: _str(m['question']),
      options: [
        for (final o in _list(m['options']))
          PollOption(_str(_map(o)['text']), _map(o)['votes'] is int ? _map(o)['votes'] as int : null)
      ],
      totalVoters: _int(m['total_voters']),
      multiple: _bool(m['multiple']),
      quiz: _bool(m['quiz']),
      correct: m['correct'] is int ? m['correct'] as int : null,
      explanation: _str(m['explanation']),
      anonymous: _bool(m['anonymous'], true),
      closed: _bool(m['closed']),
      closeAt: _time(m['close_at']),
      myVotes: [for (final x in _list(m['my_votes'])) _int(x)],
    );
  }

  /// 事件里广播的结果(只有计数)合进来,「我投了什么」保留本地的。
  PollInfo mergeResults(Map<String, dynamic> r) {
    final counts = [for (final x in _list(r['counts'])) _int(x)];
    final show = voted || _bool(r['closed']);
    return PollInfo(
      id: id,
      question: question,
      options: [
        for (var i = 0; i < options.length; i++)
          PollOption(options[i].text, show && i < counts.length ? counts[i] : options[i].votes)
      ],
      totalVoters: _int(r['total_voters'], totalVoters),
      multiple: multiple,
      quiz: quiz,
      correct: r['correct'] is int ? r['correct'] as int : correct,
      explanation: explanation,
      anonymous: anonymous,
      closed: _bool(r['closed'], closed),
      closeAt: closeAt,
      myVotes: myVotes,
    );
  }
}

class ReplyPreview {
  const ReplyPreview(this.seq, this.senderName, this.preview, this.kind, this.deleted);

  final int seq;
  final String senderName;
  final String preview;
  final String kind;
  final bool deleted;

  factory ReplyPreview.fromJson(Object? j) {
    final m = _map(j);
    return ReplyPreview(_int(m['seq']), _str(m['sender_name']), _str(m['preview']),
        _str(m['kind']), _bool(m['deleted']));
  }
}

class Sender {
  const Sender(this.id, this.name, this.username, this.avatar, this.isBot);

  final int id;
  final String name;
  final String? username;
  final String avatar;
  final bool isBot;

  factory Sender.fromJson(Object? j) {
    final m = _map(j);
    return Sender(_int(m['id']), _str(m['name']), m['username'] as String?, _str(m['avatar']),
        _bool(m['is_bot']));
  }
}

/// 本地发送状态(服务端的消息都是 [sent])。
enum LocalStatus { sent, sending, failed }

class ChatMessage {
  ChatMessage({
    required this.chatId,
    required this.seq,
    required this.kind,
    this.sender,
    this.asChat = false,
    this.senderChat,
    this.text = '',
    this.entities = const [],
    this.media = const [],
    this.replyTo,
    this.replyToSeq,
    this.forward,
    this.groupedId,
    this.poll,
    this.location,
    this.contact,
    this.dice,
    this.service,
    this.call,
    this.preview,
    this.sticker,
    this.signature,
    this.reactions = const [],
    this.views,
    this.silent = false,
    this.pinned = false,
    this.editedAt,
    required this.createdAt,
    this.markup,
    this.randomId,
    this.localStatus = LocalStatus.sent,
    this.progress,
    this.localError,
  });

  final int chatId;

  /// 本地待发的消息 seq 为 0(排在最后,确认后换成服务端的)
  final int seq;
  final String kind;
  final Sender? sender;
  final bool asChat;
  final Map<String, dynamic>? senderChat;
  final String text;
  final List<MsgEntity> entities;
  final List<MediaInfo> media;
  final ReplyPreview? replyTo;
  final int? replyToSeq;
  final Map<String, dynamic>? forward;
  final String? groupedId;
  final PollInfo? poll;
  final Map<String, dynamic>? location;
  final Map<String, dynamic>? contact;
  final Map<String, dynamic>? dice;
  final Map<String, dynamic>? service;
  final Map<String, dynamic>? call;
  final Map<String, dynamic>? preview;
  final Map<String, dynamic>? sticker;
  final String? signature;
  final List<ReactionCount> reactions;
  final int? views;
  final bool silent;
  final bool pinned;
  final DateTime? editedAt;
  final DateTime createdAt;
  final Map<String, dynamic>? markup;
  final String? randomId;
  final LocalStatus localStatus;

  /// 上传进度 0–1(本地待发的媒体消息)
  final double? progress;
  final String? localError;

  bool get isLocal => localStatus != LocalStatus.sent;
  bool get isService => kind == 'service';

  factory ChatMessage.fromJson(Object? j) {
    final m = _map(j);
    return ChatMessage(
      chatId: _int(m['chat_id']),
      seq: _int(m['seq']),
      kind: _str(m['kind'], 'text'),
      sender: m['sender'] == null ? null : Sender.fromJson(m['sender']),
      asChat: _bool(m['as_chat']),
      senderChat: m['sender_chat'] == null ? null : _map(m['sender_chat']),
      text: _str(m['text']),
      entities: [for (final e in _list(m['entities'])) MsgEntity.fromJson(e)],
      media: [for (final x in _list(m['media'])) MediaInfo.fromJson(x)],
      replyTo: m['reply_to'] == null ? null : ReplyPreview.fromJson(m['reply_to']),
      replyToSeq: m['reply_to_seq'] is int ? m['reply_to_seq'] as int : null,
      forward: m['forward'] == null ? null : _map(m['forward']),
      groupedId: m['grouped_id'] as String?,
      poll: m['poll'] == null ? null : PollInfo.fromJson(m['poll']),
      location: m['location'] == null ? null : _map(m['location']),
      contact: m['contact'] == null ? null : _map(m['contact']),
      dice: m['dice'] == null ? null : _map(m['dice']),
      service: m['service'] == null ? null : _map(m['service']),
      call: m['call'] == null ? null : _map(m['call']),
      preview: m['preview'] == null ? null : _map(m['preview']),
      sticker: m['sticker'] == null ? null : _map(m['sticker']),
      signature: m['signature'] as String?,
      reactions: [for (final r in _list(m['reactions'])) ReactionCount.fromJson(r)],
      views: m['views'] is int ? m['views'] as int : null,
      silent: _bool(m['silent']),
      pinned: _bool(m['pinned']),
      editedAt: _time(m['edited_at']),
      createdAt: _time(m['created_at']) ?? DateTime.now(),
      markup: m['markup'] == null ? null : _map(m['markup']),
      randomId: m['random_id'] as String?,
    );
  }

  ChatMessage copyWith({
    List<ReactionCount>? reactions,
    PollInfo? poll,
    bool? pinned,
    int? views,
    List<MediaInfo>? media,
    LocalStatus? localStatus,
    double? progress,
    String? localError,
  }) =>
      ChatMessage(
        chatId: chatId,
        seq: seq,
        kind: kind,
        sender: sender,
        asChat: asChat,
        senderChat: senderChat,
        text: text,
        entities: entities,
        media: media ?? this.media,
        replyTo: replyTo,
        replyToSeq: replyToSeq,
        forward: forward,
        groupedId: groupedId,
        poll: poll ?? this.poll,
        location: location,
        contact: contact,
        dice: dice,
        service: service,
        call: call,
        preview: preview,
        sticker: sticker,
        signature: signature,
        reactions: reactions ?? this.reactions,
        views: views ?? this.views,
        silent: silent,
        pinned: pinned ?? this.pinned,
        editedAt: editedAt,
        createdAt: createdAt,
        markup: markup,
        randomId: randomId,
        localStatus: localStatus ?? this.localStatus,
        progress: progress ?? this.progress,
        localError: localError ?? this.localError,
      );
}

/// 会话里「我」这边的状态。
class MyState {
  MyState({
    this.role,
    this.rights = const {},
    this.title = '',
    this.mutedUntil,
    this.pinned = false,
    this.pinnedRank,
    this.archived = false,
    this.markedUnread = false,
    this.draft,
    this.lastReadSeq = 0,
    this.clearedSeq = 0,
  });

  String? role;
  Map<String, dynamic> rights;
  String title;
  DateTime? mutedUntil;
  bool pinned;
  int? pinnedRank;
  bool archived;
  bool markedUnread;
  Map<String, dynamic>? draft;
  int lastReadSeq;
  int clearedSeq;

  bool get muted => mutedUntil != null && mutedUntil!.isAfter(DateTime.now());

  factory MyState.fromJson(Object? j) {
    final m = _map(j);
    return MyState(
      role: m['role'] as String?,
      rights: _map(m['rights']),
      title: _str(m['title']),
      mutedUntil: _time(m['muted_until']),
      pinned: _bool(m['pinned']),
      pinnedRank: m['pinned_rank'] is int ? m['pinned_rank'] as int : null,
      archived: _bool(m['archived']),
      markedUnread: _bool(m['marked_unread']),
      draft: m['draft'] == null ? null : _map(m['draft']),
      lastReadSeq: _int(m['last_read_seq']),
      clearedSeq: _int(m['cleared_seq']),
    );
  }

  /// 用户事件 `dialog` 里只带变了的字段。
  void merge(Map<String, dynamic> d) {
    if (d.containsKey('pinned')) pinned = _bool(d['pinned']);
    if (d.containsKey('pinned_rank')) {
      pinnedRank = d['pinned_rank'] is int ? d['pinned_rank'] as int : null;
    }
    if (d.containsKey('archived')) archived = _bool(d['archived']);
    if (d.containsKey('muted_until')) mutedUntil = _time(d['muted_until']);
    if (d.containsKey('marked_unread')) markedUnread = _bool(d['marked_unread']);
    if (d.containsKey('draft')) draft = d['draft'] == null ? null : _map(d['draft']);
    if (d['last_read_seq'] is int && (d['last_read_seq'] as int) > lastReadSeq) {
      lastReadSeq = d['last_read_seq'] as int;
    }
    if (d['cleared_seq'] is int) clearedSeq = d['cleared_seq'] as int;
  }
}

/// 一个会话(私聊 / 群 / 频道 / 收藏夹)在我这边的全貌。
class ChatInfo {
  ChatInfo({
    required this.id,
    required this.type,
    required this.title,
    this.publicId = '',
    this.about = '',
    this.photo = '',
    this.username,
    this.memberCount = 0,
    this.lastSeq = 0,
    this.pts = 0,
    this.settings = const {},
    required this.my,
    this.perms = const {},
    this.readFloor = 0,
    this.peer,
    this.peerReadSeq = 0,
    this.lastMessage,
    this.unread = 0,
    this.unreadMentions = 0,
    this.createdAt,
  });

  final int id;
  final String type;
  String title;
  String publicId;
  String about;
  String photo;
  String? username;
  int memberCount;
  int lastSeq;
  int pts;
  Map<String, dynamic> settings;
  MyState my;
  Map<String, dynamic> perms;
  int readFloor;
  ChatUser? peer;
  int peerReadSeq;
  ChatMessage? lastMessage;
  int unread;
  int unreadMentions;
  DateTime? createdAt;

  bool get isPrivate => type == 'private';
  bool get isGroup => type == 'group';
  bool get isChannel => type == 'channel';
  bool get isSaved => type == 'saved';

  bool can(String p) => perms[p] == true;

  DateTime get sortTime => lastMessage?.createdAt ?? createdAt ?? DateTime(2000);

  factory ChatInfo.fromJson(Object? j) {
    final m = _map(j);
    return ChatInfo(
      id: _int(m['id']),
      type: _str(m['type'], 'private'),
      title: _str(m['title']),
      publicId: _str(m['public_id']),
      about: _str(m['about']),
      photo: _str(m['photo']),
      username: m['username'] as String?,
      memberCount: _int(m['member_count']),
      lastSeq: _int(m['last_seq']),
      pts: _int(m['pts']),
      settings: _map(m['settings']),
      my: MyState.fromJson(m['my']),
      perms: _map(m['perms']),
      readFloor: _int(m['read_floor']),
      peer: m['peer'] == null ? null : ChatUser.fromJson(m['peer']),
      peerReadSeq: _int(m['peer_read_seq']),
      lastMessage: m['last_message'] == null ? null : ChatMessage.fromJson(m['last_message']),
      unread: _int(m['unread']),
      unreadMentions: _int(m['unread_mentions']),
      createdAt: _time(m['created_at']),
    );
  }

  /// 服务端的新卡片覆盖进来,本地算出来的未读、最后一条在新卡片没有时保留。
  void absorb(ChatInfo n) {
    title = n.title;
    publicId = n.publicId;
    about = n.about;
    photo = n.photo;
    username = n.username;
    memberCount = n.memberCount;
    if (n.lastSeq > lastSeq) lastSeq = n.lastSeq;
    if (n.pts > pts) pts = n.pts;
    settings = n.settings;
    my = n.my;
    perms = n.perms;
    readFloor = n.readFloor;
    peer = n.peer ?? peer;
    if (n.peerReadSeq > peerReadSeq) peerReadSeq = n.peerReadSeq;
    if (n.lastMessage != null) lastMessage = n.lastMessage;
    createdAt = n.createdAt ?? createdAt;
  }
}

/// 分组(TG 的 Chat Folders)。
class ChatFolder {
  ChatFolder({this.id, required this.title, required this.rules});

  final int? id;
  String title;
  Map<String, dynamic> rules;

  factory ChatFolder.fromJson(Object? j) {
    final m = _map(j);
    return ChatFolder(id: m['id'] as int?, title: _str(m['title']), rules: _map(m['rules']));
  }

  Map<String, dynamic> toJson() => {if (id != null) 'id': id, 'title': title, 'rules': rules};

  bool matches(ChatInfo c) {
    final include = [for (final x in _list(rules['include'])) _int(x)];
    final exclude = [for (final x in _list(rules['exclude'])) _int(x)];
    if (exclude.contains(c.id)) return false;
    if (include.contains(c.id)) return true;
    if (_bool(rules['exclude_archived'], true) && c.my.archived) return false;
    if (_bool(rules['exclude_muted']) && c.my.muted) return false;
    if (_bool(rules['exclude_read']) && c.unread == 0 && !c.my.markedUnread) return false;
    final types = [for (final x in _list(rules['types'])) _str(x)];
    final t = c.peer?.isBot == true ? 'bot' : c.type;
    if (types.contains(t)) return true;
    if (c.isPrivate && types.contains('contacts') && (c.peer?.isContact ?? false)) return true;
    if (c.isPrivate && types.contains('non_contacts') && !(c.peer?.isContact ?? false)) {
      return true;
    }
    return false;
  }
}


/// 一张贴纸(公开图,512px WebP,带透明)。
class StickerItem {
  const StickerItem({required this.id, required this.setId, required this.emoji, required this.url,
      this.mediaId = 0, this.w = 512, this.h = 512});

  final int id;
  final int setId;
  final String emoji;
  final String url;
  final int mediaId;
  final int w;
  final int h;

  factory StickerItem.fromJson(Object? j) {
    final m = _map(j);
    final media = _map(m['media']);
    return StickerItem(
      id: _int(m['id']),
      setId: _int(m['set_id']),
      emoji: _str(m['emoji'], '🙂'),
      url: _str(media['url']),
      mediaId: _int(media['id']),
      w: _int(media['w'], 512),
      h: _int(media['h'], 512),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'set_id': setId,
        'emoji': emoji,
        'media': {'id': mediaId, 'url': url, 'w': w, 'h': h},
      };
}

/// 一个贴纸包。
class StickerSetInfo {
  StickerSetInfo({
    required this.id,
    required this.shortName,
    required this.title,
    this.isOfficial = false,
    this.isMine = false,
    this.installed = false,
    this.count = 0,
    this.cover,
    this.stickers = const [],
  });

  final int id;
  final String shortName;
  String title;
  final bool isOfficial;
  final bool isMine;
  bool installed;
  int count;
  final StickerItem? cover;
  List<StickerItem> stickers;

  factory StickerSetInfo.fromJson(Object? j) {
    final m = _map(j);
    return StickerSetInfo(
      id: _int(m['id']),
      shortName: _str(m['short_name']),
      title: _str(m['title']),
      isOfficial: m['is_official'] == true,
      isMine: m['is_mine'] == true,
      installed: m['installed'] == true,
      count: _int(m['count']),
      cover: m['cover'] == null ? null : StickerItem.fromJson(m['cover']),
      stickers: [for (final x in (m['stickers'] as List? ?? const [])) StickerItem.fromJson(x)],
    );
  }
}

/// 机器人的一条命令(输入 `/` 联想、菜单里列的就是这些)。
class BotCommand {
  const BotCommand(this.command, this.description);

  final String command;
  final String description;
}

/// 会话里的机器人(`GET /chat/v1/chats/{id}/bot-info`,#355):私聊里是对面那一个,群里是群里所有机器人。
class BotInfo {
  BotInfo({
    required this.id,
    required this.name,
    this.username,
    this.avatar = '',
    this.about = '',
    this.description = '',
    this.commands = const [],
    this.menuType,
    this.menuText = '',
    this.menuAppId = '',
    this.menuAppName = '',
  });

  final int id;
  final String name;
  final String? username;
  final String avatar;
  final String about;

  /// 空会话中间那段「这个机器人能做什么」
  final String description;
  final List<BotCommand> commands;

  /// 输入栏左边的菜单按钮:null(没有)/ commands(列命令)/ web_app(打开小程序)
  final String? menuType;
  final String menuText;
  final String menuAppId;
  final String menuAppName;

  factory BotInfo.fromJson(Object? j) {
    final m = _map(j);
    final menu = m['menu_button'] == null ? null : _map(m['menu_button']);
    final app = menu == null || menu['app'] == null ? const <String, dynamic>{} : _map(menu['app']);
    final type = menu == null ? null : _str(menu['type']);
    return BotInfo(
      id: _int(m['id']),
      name: _str(m['name']),
      username: m['username'] as String?,
      avatar: _str(m['avatar']),
      about: _str(m['about']),
      description: _str(m['description']),
      commands: [
        for (final c in (m['commands'] as List? ?? const []))
          BotCommand(_str(_map(c)['command']), _str(_map(c)['description'])),
      ],
      menuType: type == 'commands' || type == 'web_app' ? type : null,
      menuText: _str(menu?['text']),
      menuAppId: _str(menu?['app_id']),
      menuAppName: _str(app['name']),
    );
  }
}
