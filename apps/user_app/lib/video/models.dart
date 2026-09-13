// 视频模块的数据对象(DEV-PROMPTS-40 #357–#367)。字段和 docs/VIDEO-API.md 逐项对应;
// 解析都容错(缺字段给缺省值),接口多加字段不会让旧客户端崩。
import 'dart:math';

int _int(Object? v, [int d = 0]) => v is int ? v : (v is num ? v.toInt() : int.tryParse('$v') ?? d);
double _dbl(Object? v, [double d = 0]) => v is num ? v.toDouble() : double.tryParse('$v') ?? d;
String _str(Object? v, [String d = '']) => v is String ? v : (v == null ? d : '$v');
bool _bool(Object? v) => v == true;
Map<String, dynamic> _map(Object? v) => v is Map ? v.cast<String, dynamic>() : <String, dynamic>{};
List<dynamic> _list(Object? v) => v is List ? v : const [];
DateTime? _time(Object? v) => v == null ? null : DateTime.tryParse('$v')?.toLocal();

/// 人的简卡(视频接口里没有手机号,S2)。
class VPerson {
  const VPerson({required this.id, required this.name, this.username, this.avatar = '', this.bio = '',
      this.fans = 0, this.videos = 0, this.followed = false, this.since});

  final int id;
  final String name;
  final String? username;
  final String avatar;
  final String bio;
  final int fans;
  final int videos;
  final bool followed;
  final DateTime? since;

  factory VPerson.fromJson(Object? j) {
    final m = _map(j);
    return VPerson(
      id: _int(m['id']),
      name: _str(m['name']),
      username: m['username'] as String?,
      avatar: _str(m['avatar']),
      bio: _str(m['bio']),
      fans: _int(m['fans']),
      videos: _int(m['videos']),
      followed: _bool(m['followed']),
      since: _time(m['since']),
    );
  }

  VPerson copyWith({bool? followed, int? fans}) => VPerson(
      id: id, name: name, username: username, avatar: avatar, bio: bio,
      fans: fans ?? this.fans, videos: videos, followed: followed ?? this.followed, since: since);
}

/// 视频卡片(推荐 / 热门 / 搜索 / 空间 / 历史 / 收藏夹共用)。
class VideoCard {
  VideoCard({
    required this.vid,
    required this.title,
    this.cover = '',
    this.durationMs = 0,
    this.isVertical = false,
    this.zone = '',
    this.zoneName = '',
    this.tags = const [],
    this.views = 0,
    this.likes = 0,
    this.coins = 0,
    this.favorites = 0,
    this.shares = 0,
    this.danmakuCount = 0,
    this.commentCount = 0,
    this.publishedAt,
    this.collab = false,
    this.uploader,
    this.invalid = false,
    this.rank = const {},
    this.why = const [],
    this.position,
    this.raw = const {},
  });

  final String vid;
  final String title;
  final String cover;
  final int durationMs;
  final bool isVertical;
  final String zone;
  final String zoneName;
  final List<String> tags;
  int views;
  int likes;
  int coins;
  int favorites;
  int shares;
  int danmakuCount;
  int commentCount;
  final DateTime? publishedAt;
  final bool collab;
  VPerson? uploader;

  /// 历史 / 收藏夹里已经看不了的(删了、下架、改私密)
  final bool invalid;

  /// 算分的中间量(推荐、热门、竖屏、相关、排行)
  final Map<String, dynamic> rank;

  /// 「为什么推荐」
  final List<String> why;

  /// 排行榜名次
  final int? position;
  final Map<String, dynamic> raw;

  factory VideoCard.fromJson(Object? j) {
    final m = _map(j);
    return VideoCard(
      vid: _str(m['vid']),
      title: _str(m['title']),
      cover: _str(m['cover']),
      durationMs: _int(m['duration_ms']),
      isVertical: _bool(m['is_vertical']),
      zone: _str(m['zone']),
      zoneName: _str(m['zone_name']),
      tags: [for (final t in _list(m['tags'])) '$t'],
      views: _int(m['views']),
      likes: _int(m['likes']),
      coins: _int(m['coins']),
      favorites: _int(m['favorites']),
      shares: _int(m['shares']),
      danmakuCount: _int(m['danmaku_count']),
      commentCount: _int(m['comment_count']),
      publishedAt: _time(m['published_at']),
      collab: _bool(m['collab']),
      uploader: m['uploader'] == null ? null : VPerson.fromJson(m['uploader']),
      invalid: _bool(m['invalid']),
      rank: _map(m['rank']),
      why: [for (final w in _list(m['why'])) '$w'],
      position: m['position'] == null ? null : _int(m['position']),
      raw: m,
    );
  }
}

/// 一档清晰度。
class Rendition {
  const Rendition({required this.q, required this.w, required this.h, required this.url, this.size = 0, this.bitrate = 0});

  final int q;
  final int w;
  final int h;
  final int size;
  final int bitrate;
  final String url;

  factory Rendition.fromJson(Object? j) {
    final m = _map(j);
    return Rendition(q: _int(m['q']), w: _int(m['w']), h: _int(m['h']), url: _str(m['url']),
        size: _int(m['size']), bitrate: _int(m['bitrate']));
  }

  String get label => q >= 1080 ? '1080P 高清' : (q >= 720 ? '720P 准高清' : (q >= 480 ? '480P 标清' : '360P 流畅'));
}

/// 进度条缩略图(雪碧图)。坐标算法见 VIDEO-API 1.4。
class SpriteInfo {
  const SpriteInfo({required this.intervalMs, required this.cols, required this.rows, required this.w,
      required this.h, required this.count, required this.urls});

  final int intervalMs;
  final int cols;
  final int rows;
  final int w;
  final int h;
  final int count;
  final List<String> urls;

  factory SpriteInfo.fromJson(Object? j) {
    final m = _map(j);
    return SpriteInfo(
      intervalMs: max(1, _int(m['interval_ms'], 1000)),
      cols: max(1, _int(m['cols'], 10)),
      rows: max(1, _int(m['rows'], 10)),
      w: _int(m['w'], 160),
      h: _int(m['h'], 90),
      count: _int(m['count']),
      urls: [for (final u in _list(m['urls'])) '$u'],
    );
  }

  /// 拖到 [ms] 毫秒时取哪一张的哪一格。没有缩略图时返回 null。
  ({int sheet, int row, int col})? cellAt(int ms) {
    if (count <= 0 || urls.isEmpty) return null;
    final i = min(max(0, ms) ~/ intervalMs, count - 1);
    final per = cols * rows;
    final sheet = i ~/ per;
    if (sheet >= urls.length) return null;
    final inSheet = i % per;
    return (sheet: sheet, row: inSheet ~/ cols, col: inSheet % cols);
  }
}

/// 一 P。
class VideoPart {
  const VideoPart({required this.id, required this.idx, required this.title, this.status = 'ready',
      this.durationMs = 0, this.w = 0, this.h = 0, this.renditions = const [], this.sprite,
      this.live = true, this.error = '', this.coverCandidates = const []});

  final int id;
  final int idx;
  final String title;
  final String status;
  final int durationMs;
  final int w;
  final int h;
  final List<Rendition> renditions;
  final SpriteInfo? sprite;

  /// 创作中心:是否在线上版本里
  final bool live;
  final String error;

  /// 创作中心:自动截的三帧 `{media_id, url}`
  final List<Map<String, dynamic>> coverCandidates;

  bool get isVertical => w > 0 && h > 0 && w < h;

  factory VideoPart.fromJson(Object? j) {
    final m = _map(j);
    return VideoPart(
      id: _int(m['id']),
      idx: _int(m['idx']),
      title: _str(m['title']),
      status: _str(m['status'], 'ready'),
      durationMs: _int(m['duration_ms']),
      w: _int(m['w']),
      h: _int(m['h']),
      renditions: [for (final r in _list(m['renditions'])) Rendition.fromJson(r)],
      sprite: m['sprite'] == null ? null : SpriteInfo.fromJson(m['sprite']),
      live: m['live'] != false,
      error: _str(m['error']),
      coverCandidates: [for (final c in _list(m['cover_candidates'])) _map(c)],
    );
  }
}

/// 续播进度。
class VProgress {
  const VProgress({required this.partIdx, required this.positionMs, required this.durationMs, this.watchedAt});

  final int partIdx;
  final int positionMs;
  final int durationMs;
  final DateTime? watchedAt;

  factory VProgress.fromJson(Object? j) {
    final m = _map(j);
    return VProgress(partIdx: _int(m['part_idx']), positionMs: _int(m['position_ms']),
        durationMs: _int(m['duration_ms']), watchedAt: _time(m['watched_at']));
  }
}

/// 详情里「我」的状态。
class VideoMe {
  VideoMe({this.liked = false, this.coins = 0, this.coinMax = 2, this.favorited = false,
      this.folderIds = const [], this.watchLater = false, this.coinBalance = 0, this.progress});

  bool liked;
  int coins;
  int coinMax;
  bool favorited;
  List<int> folderIds;
  bool watchLater;
  int coinBalance;
  VProgress? progress;

  factory VideoMe.fromJson(Object? j) {
    final m = _map(j);
    return VideoMe(
      liked: _bool(m['liked']),
      coins: _int(m['coins']),
      coinMax: _int(m['coin_max'], 2),
      favorited: _bool(m['favorited']),
      folderIds: [for (final x in _list(m['folder_ids'])) _int(x)],
      watchLater: _bool(m['watch_later']),
      coinBalance: _int(m['coin_balance']),
      progress: m['progress'] == null ? null : VProgress.fromJson(m['progress']),
    );
  }
}

/// 视频详情。
class VideoDetail {
  VideoDetail({required this.card, this.description = '', this.copyright = 'original', this.sourceUrl = '',
      this.status = 'published', this.statusLabel = '', this.visibility = 'public', this.allowDanmaku = true,
      this.allowComments = true, this.shop, this.shopCollab, this.link = '', this.parts = const [],
      this.isOwner = false, this.me});

  final VideoCard card;
  final String description;
  final String copyright;
  final String sourceUrl;
  final String status;
  final String statusLabel;
  final String visibility;
  final bool allowDanmaku;
  final bool allowComments;

  /// 挂的店铺 `{id, name, logo}`(D16)
  final Map<String, dynamic>? shop;
  final bool? shopCollab;
  final String link;
  final List<VideoPart> parts;
  final bool isOwner;

  /// 没登录是 null
  VideoMe? me;

  String get vid => card.vid;
  VPerson? get uploader => card.uploader;

  factory VideoDetail.fromJson(Object? j) {
    final m = _map(j);
    return VideoDetail(
      card: VideoCard.fromJson(m),
      description: _str(m['description']),
      copyright: _str(m['copyright'], 'original'),
      sourceUrl: _str(m['source_url']),
      status: _str(m['status'], 'published'),
      statusLabel: _str(m['status_label']),
      visibility: _str(m['visibility'], 'public'),
      allowDanmaku: m['allow_danmaku'] != false,
      allowComments: m['allow_comments'] != false,
      shop: m['shop'] == null ? null : _map(m['shop']),
      shopCollab: m['shop_collab'] as bool?,
      link: _str(m['link']),
      parts: [for (final p in _list(m['parts'])) VideoPart.fromJson(p)],
      isOwner: _bool(m['is_owner']),
      me: m['me'] == null ? null : VideoMe.fromJson(m['me']),
    );
  }
}

/// 一条弹幕(§5.10)。
class Danmaku {
  const Danmaku({required this.id, required this.timeMs, required this.text, this.mode = 1,
      this.color = 0xFFFFFF, this.size = 25, this.userHash = '', this.mine = false});

  final int id;
  final int timeMs;
  final int mode;
  final int color;
  final int size;
  final String text;
  final String userHash;
  final bool mine;

  static const scroll = 1;
  static const bottom = 4;
  static const top = 5;

  factory Danmaku.fromJson(Object? j) {
    final m = _map(j);
    return Danmaku(
      id: _int(m['id']),
      timeMs: _int(m['time_ms']),
      mode: _int(m['mode'], 1),
      color: _int(m['color'], 0xFFFFFF),
      size: _int(m['size'], 25),
      text: _str(m['text']),
      userHash: _str(m['user_hash']),
      mine: _bool(m['mine']),
    );
  }
}

/// 一条评论(一级评论带最早 3 条回复)。
class VComment {
  VComment({required this.id, required this.vid, required this.user, required this.text, this.rootId,
      this.parentId, this.replyTo, this.mentions = const [], this.likes = 0, this.myVote = 0,
      this.replyCount = 0, this.pinned = false, this.isUp = false, this.createdAt, this.replies = const []});

  final int id;
  final String vid;
  final int? rootId;
  final int? parentId;
  final VPerson user;

  /// 回复的是「回复」时:`{id, name}`(显示「回复 @某人」)
  final Map<String, dynamic>? replyTo;
  final String text;
  final List<Map<String, dynamic>> mentions;
  int likes;
  int myVote;
  int replyCount;
  bool pinned;
  final bool isUp;
  final DateTime? createdAt;
  List<VComment> replies;

  factory VComment.fromJson(Object? j) {
    final m = _map(j);
    return VComment(
      id: _int(m['id']),
      vid: _str(m['vid']),
      rootId: m['root_id'] == null ? null : _int(m['root_id']),
      parentId: m['parent_id'] == null ? null : _int(m['parent_id']),
      user: VPerson.fromJson(m['user']),
      replyTo: m['reply_to'] == null ? null : _map(m['reply_to']),
      text: _str(m['text']),
      mentions: [for (final x in _list(m['mentions'])) _map(x)],
      likes: _int(m['likes']),
      myVote: _int(m['my_vote']),
      replyCount: _int(m['reply_count']),
      pinned: _bool(m['pinned']),
      isUp: _bool(m['is_up']),
      createdAt: _time(m['created_at']),
      replies: [for (final r in _list(m['replies'])) VComment.fromJson(r)],
    );
  }
}

/// 收藏夹。
class FavFolder {
  const FavFolder({required this.id, required this.title, this.isDefault = false, this.isPublic = false,
      this.count = 0, this.cover = '', this.updatedAt});

  final int id;
  final String title;
  final bool isDefault;
  final bool isPublic;
  final int count;
  final String cover;
  final DateTime? updatedAt;

  factory FavFolder.fromJson(Object? j) {
    final m = _map(j);
    return FavFolder(
      id: _int(m['id']),
      title: _str(m['title']),
      isDefault: _bool(m['is_default']),
      isPublic: _bool(m['public']),
      count: _int(m['count']),
      cover: _str(m['cover']),
      updatedAt: _time(m['updated_at']),
    );
  }
}

/// 一页结果:`page` 分页的带 has_more,`cursor` 分页的带 next_cursor(VIDEO-API 0.5)。
class VPage<T> {
  const VPage(this.items, {this.hasMore = false, this.nextCursor, this.extra = const {}});

  final List<T> items;
  final bool hasMore;
  final String? nextCursor;

  /// 响应里的其他字段(personalized、ranked_at、count、unread……)
  final Map<String, dynamic> extra;

  bool get more => hasMore || nextCursor != null;
}

/// 播放数、点赞数这些的短写:1.2万、3.4亿(和 B 站一样)。
String vCount(int n) {
  if (n < 10000) return '$n';
  if (n < 100000000) {
    final w = n / 10000;
    return '${w >= 100 ? w.toStringAsFixed(0) : w.toStringAsFixed(1)}万';
  }
  return '${(n / 100000000).toStringAsFixed(1)}亿';
}

/// 时长:1:05、12:30、1:02:03。
String vDuration(int ms) {
  final s = (ms / 1000).floor();
  final h = s ~/ 3600, m = (s % 3600) ~/ 60, sec = s % 60;
  String two(int x) => x.toString().padLeft(2, '0');
  return h > 0 ? '$h:${two(m)}:${two(sec)}' : '$m:${two(sec)}';
}

/// 发布时间:刚刚 / N 分钟前 / N 小时前 / 昨天 / M-D / YYYY-M-D。
String vAgo(DateTime? t, [DateTime? now]) {
  if (t == null) return '';
  final n = now ?? DateTime.now();
  final d = n.difference(t);
  if (d.inMinutes < 1) return '刚刚';
  if (d.inHours < 1) return '${d.inMinutes} 分钟前';
  if (d.inHours < 24 && n.day == t.day) return '${d.inHours} 小时前';
  final y = n.subtract(const Duration(days: 1));
  if (y.year == t.year && y.month == t.month && y.day == t.day) return '昨天';
  if (t.year == n.year) return '${t.month}-${t.day}';
  return '${t.year}-${t.month}-${t.day}';
}

int vInt(Object? v) => _int(v);
double vDouble(Object? v) => _dbl(v);
Map<String, dynamic> vMap(Object? v) => _map(v);
List<dynamic> vList(Object? v) => _list(v);
