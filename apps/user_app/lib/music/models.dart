// 音乐模块的数据对象(DEV-PROMPTS-41 §8.1、§8.2)。字段和规格逐项对应;
// 解析都容错(缺字段给缺省值),服务端多加字段不会让旧客户端崩 —— 和 video/models.dart 同一个口径。
//
// 人物简卡、计数短写、时长、相对时间直接用视频那边的:全站只该有一套
// (`VPerson` 由 services/video.people 生成,音乐接口里的 owner / mentions 也是它)。
import '../video/models.dart';

/// 音质:标准 128k / 高品质 256k(§4 M4)。源码率低于 192k 的歌不出 hq。
const String kQualityStd = 'std';
const String kQualityHq = 'hq';

String mQualityName(String q) => q == kQualityHq ? '高品质' : '标准';

/// 作品类型(§4 M3)。
String mReleaseKindName(String kind) => switch (kind) {
      'album' => '专辑',
      'ep' => 'EP',
      _ => '单曲',
    };

/// 作品审核状态(§5.3 的状态机)。
String mReleaseStatusName(String status) => switch (status) {
      'reviewing' => '审核中',
      'published' => '已发布',
      'rejected' => '未通过',
      'withdrawn' => '已下架',
      'removed' => '被下架',
      _ => '草稿',
    };

/// 歌曲转码状态(§5.3)。
String mTranscodeName(String status) => switch (status) {
      'processing' => '转码中',
      'ready' => '已就绪',
      'failed' => '转码失败',
      _ => '排队中',
    };

/// 原创 / 已获授权声明(§4 M1,上传时必选其一)。
String mDeclarationName(String d) => d == 'authorized' ? '已获授权' : '原创';

/// 歌词形态(§4 M8)。
String mLyricsKindName(String k) => switch (k) {
      'lrc' => '带时间轴',
      'plain' => '纯文本',
      _ => '暂无歌词',
    };

/// 算分的中间量(§5.4:每一项都下发 `{score, parts, why}`)。
///
/// 榜单、每日推荐、推荐歌单、曲风页都带它 —— 公式公开是这一批的立场,
/// 界面上「怎么算的」点开就是 `/music/v1/rank/formula` 原样。
class MRank {
  const MRank({this.score = 0, this.parts = const {}, this.why = ''});

  final double score;
  final Map<String, dynamic> parts;
  final String why;

  bool get isEmpty => why.isEmpty && parts.isEmpty && score == 0;

  factory MRank.fromJson(Object? j) {
    final m = vMap(j);
    return MRank(score: vDouble(m['score']), parts: vMap(m['parts']), why: '${m['why'] ?? ''}');
  }
}

/// 歌曲里的音乐人简卡(track.artist)。完整的音乐人是 [MArtist]。
class MArtistRef {
  const MArtistRef({required this.aid, required this.name, this.userId = 0, this.avatar = ''});

  final String aid;
  final String name;
  final int userId;
  final String avatar;

  factory MArtistRef.fromJson(Object? j) {
    final m = vMap(j);
    return MArtistRef(
      aid: '${m['aid'] ?? ''}',
      name: '${m['name'] ?? ''}',
      userId: vInt(m['user_id']),
      avatar: '${m['avatar'] ?? ''}',
    );
  }
}

/// 歌曲里的作品简卡(track.release)。
class MReleaseRef {
  const MReleaseRef({required this.rid, required this.title, this.kind = 'single'});

  final String rid;
  final String title;
  final String kind;

  factory MReleaseRef.fromJson(Object? j) {
    final m = vMap(j);
    return MReleaseRef(
      rid: '${m['rid'] ?? ''}',
      title: '${m['title'] ?? ''}',
      kind: '${m['kind'] ?? 'single'}',
    );
  }
}

/// 签好的播放地址(§5.5:6 小时有效,到期要重签)。
class MStream {
  const MStream({this.std = '', this.hq, this.expiresAt});

  final String std;

  /// 源码率低于 192k 的歌没有高品质档,这里是 null
  final String? hq;
  final DateTime? expiresAt;

  bool get isEmpty => std.isEmpty && (hq ?? '').isEmpty;

  /// 按音质取地址;要的那一档没有就回落标准(§8.2 hq 可为 null)。
  String urlFor(String quality) {
    if (quality == kQualityHq && (hq ?? '').isNotEmpty) return hq!;
    return std.isNotEmpty ? std : (hq ?? '');
  }

  /// 还有多久过期。留 [slack] 的余量:刚好卡在到期那一秒去播必然 403。
  bool expiredBy(DateTime now, {Duration slack = const Duration(minutes: 2)}) {
    final e = expiresAt;
    if (e == null) return false;
    return now.add(slack).isAfter(e);
  }

  factory MStream.fromJson(Object? j) {
    final m = vMap(j);
    final hq = '${m['hq'] ?? ''}';
    return MStream(
      std: '${m['std'] ?? ''}',
      hq: hq.isEmpty ? null : hq,
      expiresAt: m['expires_at'] == null ? null : DateTime.tryParse('${m['expires_at']}')?.toLocal(),
    );
  }
}

/// 一首歌。卡片、详情、音乐人中心里的歌用同一个类 —— 多出来的字段各自可空。
class MTrack {
  MTrack({
    required this.tid,
    required this.title,
    this.durationMs = 0,
    this.cover = '',
    this.explicit = false,
    this.genre = '',
    this.genreName = '',
    this.plays = 0,
    this.likes = 0,
    this.comments = 0,
    this.liked = false,
    this.artist,
    this.release,
    this.publishedAt,
    this.rank,
    this.lyricsKind = '',
    this.credits = const {},
    this.declaration = '',
    this.stream,
    this.trackNo = 0,
    this.transcodeStatus = '',
    this.failReason = '',
    this.lyrics = '',
    this.raw = const {},
  });

  final String tid;
  final String title;
  final int durationMs;
  final String cover;
  final bool explicit;
  final String genre;
  final String genreName;

  // 计数和「我喜欢」会就地改(点一下喜欢不该整页重拉)
  int plays;
  int likes;
  int comments;
  bool liked;

  final MArtistRef? artist;
  final MReleaseRef? release;
  final DateTime? publishedAt;

  /// 榜单 / 推荐带的算分中间量;普通列表里是 null
  final MRank? rank;

  // ---- 详情才有 ----
  final String lyricsKind;
  final Map<String, dynamic> credits;
  final String declaration;

  /// 签好的播放地址;列表里是 null,播放前用 `/tracks/{tid}/stream` 现签
  MStream? stream;

  // ---- 音乐人中心才有 ----
  final int trackNo;
  final String transcodeStatus;
  final String failReason;
  final String lyrics;

  final Map<String, dynamic> raw;

  String get artistName => artist?.name ?? '';

  /// 转码好了才能提交审核(§5.3)
  bool get transcodeReady => transcodeStatus.isEmpty || transcodeStatus == 'ready';

  factory MTrack.fromJson(Object? j) {
    final m = vMap(j);
    return MTrack(
      tid: '${m['tid'] ?? ''}',
      title: '${m['title'] ?? ''}',
      durationMs: vInt(m['duration_ms']),
      cover: '${m['cover'] ?? ''}',
      explicit: m['explicit'] == true,
      genre: '${m['genre'] ?? ''}',
      genreName: '${m['genre_name'] ?? ''}',
      plays: vInt(m['plays']),
      likes: vInt(m['likes']),
      comments: vInt(m['comments']),
      liked: m['liked'] == true,
      artist: m['artist'] == null ? null : MArtistRef.fromJson(m['artist']),
      release: m['release'] == null ? null : MReleaseRef.fromJson(m['release']),
      publishedAt: m['published_at'] == null ? null : DateTime.tryParse('${m['published_at']}')?.toLocal(),
      rank: m['rank'] == null ? null : MRank.fromJson(m['rank']),
      lyricsKind: '${m['lyrics_kind'] ?? ''}',
      credits: vMap(m['credits']),
      declaration: '${m['declaration'] ?? ''}',
      stream: m['stream'] == null ? null : MStream.fromJson(m['stream']),
      trackNo: vInt(m['track_no']),
      transcodeStatus: '${m['transcode_status'] ?? ''}',
      failReason: '${m['fail_reason'] ?? ''}',
      lyrics: '${m['lyrics'] ?? ''}',
      raw: m,
    );
  }
}

/// 一个作品(单曲 / EP / 专辑)。审核的单位就是它(§4 M3)。
class MRelease {
  MRelease({
    required this.rid,
    required this.title,
    this.kind = 'single',
    this.cover = '',
    this.artist,
    this.trackCount = 0,
    this.releaseDate = '',
    this.collects = 0,
    this.collected = false,
    this.publishedAt,
    this.description = '',
    this.genre = '',
    this.language = '',
    this.tracks = const [],
    this.status = '',
    this.rejectCode = '',
    this.rejectNote = '',
    this.canAppeal = false,
    this.submittedAt,
    this.raw = const {},
  });

  final String rid;
  final String title;
  final String kind;
  final String cover;
  final MArtistRef? artist;
  final int trackCount;
  final String releaseDate;
  int collects;
  bool collected;
  final DateTime? publishedAt;

  // ---- 详情 ----
  final String description;
  final String genre;
  final String language;
  final List<MTrack> tracks;

  // ---- 音乐人中心 ----
  final String status;
  final String rejectCode;
  final String rejectNote;
  final bool canAppeal;
  final DateTime? submittedAt;

  final Map<String, dynamic> raw;

  /// 只有这三个状态能改信息、增删歌曲(§5.3)
  bool get editable => status == 'draft' || status == 'rejected' || status == 'withdrawn';

  bool get submittable => editable;

  factory MRelease.fromJson(Object? j) {
    final m = vMap(j);
    return MRelease(
      rid: '${m['rid'] ?? ''}',
      title: '${m['title'] ?? ''}',
      kind: '${m['kind'] ?? 'single'}',
      cover: '${m['cover'] ?? ''}',
      artist: m['artist'] == null ? null : MArtistRef.fromJson(m['artist']),
      trackCount: m['track_count'] == null ? vList(m['tracks']).length : vInt(m['track_count']),
      releaseDate: '${m['release_date'] ?? ''}',
      collects: vInt(m['collects']),
      collected: m['collected'] == true,
      publishedAt: m['published_at'] == null ? null : DateTime.tryParse('${m['published_at']}')?.toLocal(),
      description: '${m['description'] ?? ''}',
      genre: '${m['genre'] ?? ''}',
      language: '${m['language'] ?? ''}',
      tracks: [for (final t in vList(m['tracks'])) MTrack.fromJson(t)],
      status: '${m['status'] ?? ''}',
      rejectCode: '${m['reject_code'] ?? ''}',
      rejectNote: '${m['reject_note'] ?? ''}',
      canAppeal: m['can_appeal'] == true,
      submittedAt: m['submitted_at'] == null ? null : DateTime.tryParse('${m['submitted_at']}')?.toLocal(),
      raw: m,
    );
  }
}

/// 歌单(自建的和收藏的都是它)。
class MPlaylist {
  MPlaylist({
    required this.pid,
    required this.title,
    this.cover = '',
    this.trackCount = 0,
    this.collects = 0,
    this.plays = 0,
    this.isPublic = true,
    this.owner,
    this.tags = const [],
    this.description = '',
    this.collected = false,
    this.tracks = const [],
    this.createdAt,
    this.updatedAt,
    this.rank,
    this.raw = const {},
  });

  final String pid;
  final String title;
  final String cover;
  int trackCount;
  int collects;
  final int plays;
  final bool isPublic;
  final VPerson? owner;
  final List<String> tags;

  // ---- 详情 ----
  final String description;
  bool collected;
  final List<MTrack> tracks;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  /// 推荐歌单带的中间量(§5.4)
  final MRank? rank;
  final Map<String, dynamic> raw;

  factory MPlaylist.fromJson(Object? j) {
    final m = vMap(j);
    return MPlaylist(
      pid: '${m['pid'] ?? ''}',
      title: '${m['title'] ?? ''}',
      cover: '${m['cover'] ?? ''}',
      trackCount: m['track_count'] == null ? vList(m['tracks']).length : vInt(m['track_count']),
      collects: vInt(m['collects']),
      plays: vInt(m['plays']),
      isPublic: m['is_public'] != false,
      owner: m['owner'] == null ? null : VPerson.fromJson(m['owner']),
      tags: [for (final t in vList(m['tags'])) '$t'],
      description: '${m['description'] ?? ''}',
      collected: m['collected'] == true,
      tracks: [for (final t in vList(m['tracks'])) MTrack.fromJson(t)],
      createdAt: m['created_at'] == null ? null : DateTime.tryParse('${m['created_at']}')?.toLocal(),
      updatedAt: m['updated_at'] == null ? null : DateTime.tryParse('${m['updated_at']}')?.toLocal(),
      rank: m['rank'] == null ? null : MRank.fromJson(m['rank']),
      raw: m,
    );
  }
}

/// 音乐人。开通不要求实名(§4 M2)。
class MArtist {
  MArtist({
    required this.aid,
    required this.name,
    this.bio = '',
    this.avatar = '',
    this.cover = '',
    this.genres = const [],
    this.userId = 0,
    this.fans = 0,
    this.followed = false,
    this.trackCount = 0,
    this.status = 'active',
    this.hotTracks = const [],
    this.releases = const [],
    this.raw = const {},
  });

  final String aid;
  final String name;
  final String bio;
  final String avatar;
  final String cover;
  final List<String> genres;
  final int userId;
  int fans;
  bool followed;
  final int trackCount;
  final String status;
  final List<MTrack> hotTracks;
  final List<MRelease> releases;
  final Map<String, dynamic> raw;

  /// 被停用的音乐人(后台 suspend),主页只读
  bool get suspended => status == 'suspended';

  factory MArtist.fromJson(Object? j) {
    final m = vMap(j);
    return MArtist(
      aid: '${m['aid'] ?? ''}',
      name: '${m['name'] ?? ''}',
      bio: '${m['bio'] ?? ''}',
      avatar: '${m['avatar'] ?? ''}',
      cover: '${m['cover'] ?? ''}',
      genres: [for (final g in vList(m['genres'])) '$g'],
      userId: vInt(m['user_id']),
      fans: vInt(m['fans']),
      followed: m['followed'] == true,
      trackCount: vInt(m['track_count']),
      status: '${m['status'] ?? 'active'}',
      hotTracks: [for (final t in vList(m['hot_tracks'])) MTrack.fromJson(t)],
      releases: [for (final r in vList(m['releases'])) MRelease.fromJson(r)],
      raw: m,
    );
  }
}

/// 一条歌曲评论(先发后审,§2.1)。
class MComment {
  MComment({
    required this.id,
    required this.user,
    required this.text,
    this.likes = 0,
    this.liked = false,
    this.replyCount = 0,
    this.replyTo,
    this.createdAt,
    this.mine = false,
    this.replies = const [],
  });

  final int id;
  final VPerson user;
  final String text;
  int likes;
  bool liked;
  int replyCount;

  /// 回复的是楼里某一条时:被回复的人
  final VPerson? replyTo;
  final DateTime? createdAt;

  /// 我自己发的(能删)
  final bool mine;

  /// 楼主那条带出来的前几条回复(服务端给了才有)
  List<MComment> replies;

  factory MComment.fromJson(Object? j) {
    final m = vMap(j);
    return MComment(
      id: vInt(m['id']),
      user: VPerson.fromJson(m['user']),
      text: '${m['text'] ?? ''}',
      likes: vInt(m['likes']),
      liked: m['liked'] == true,
      replyCount: vInt(m['reply_count']),
      replyTo: m['reply_to'] == null ? null : VPerson.fromJson(m['reply_to']),
      createdAt: m['created_at'] == null ? null : DateTime.tryParse('${m['created_at']}')?.toLocal(),
      mine: m['mine'] == true,
      replies: [for (final r in vList(m['replies'])) MComment.fromJson(r)],
    );
  }
}

/// 一个曲风。
class MGenre {
  const MGenre({required this.key, required this.name});

  final String key;
  final String name;

  factory MGenre.fromJson(Object? j) {
    final m = vMap(j);
    return MGenre(key: '${m['key'] ?? ''}', name: '${m['name'] ?? ''}');
  }
}

/// 榜单摘要 / 榜单全表(§4 M7:热歌、新歌、飙升)。
class MChart {
  const MChart({
    required this.key,
    required this.name,
    this.updatedAt,
    this.top = const [],
    this.items = const [],
  });

  final String key;
  final String name;
  final DateTime? updatedAt;

  /// 摘要里的前三首
  final List<MTrack> top;

  /// 全表:带名次
  final List<MChartEntry> items;

  factory MChart.fromJson(Object? j) {
    final m = vMap(j);
    return MChart(
      key: '${m['key'] ?? ''}',
      name: '${m['name'] ?? ''}',
      updatedAt: m['updated_at'] == null ? null : DateTime.tryParse('${m['updated_at']}')?.toLocal(),
      top: [for (final t in vList(m['top'])) MTrack.fromJson(t)],
      items: [for (final e in vList(m['items'])) MChartEntry.fromJson(e)],
    );
  }
}

/// 榜单里的一行:名次 + 歌 + 算分中间量。
class MChartEntry {
  const MChartEntry({required this.rankNo, required this.track, this.rank});

  final int rankNo;
  final MTrack track;
  final MRank? rank;

  factory MChartEntry.fromJson(Object? j) {
    final m = vMap(j);
    // 服务端把 rank 放在条目上;歌本身也可能自带一份,两边都认
    final t = MTrack.fromJson(m['track']);
    return MChartEntry(
      rankNo: vInt(m['rank_no']),
      track: t,
      rank: m['rank'] == null ? t.rank : MRank.fromJson(m['rank']),
    );
  }
}

/// 发现页一屏(§8.2 `GET /home`)。
class MHome {
  const MHome({
    this.daily = const [],
    this.dailyPersonalized = true,
    this.playlists = const [],
    this.newTracks = const [],
    this.charts = const [],
    this.genres = const [],
  });

  final List<MTrack> daily;
  final bool dailyPersonalized;
  final List<MPlaylist> playlists;
  final List<MTrack> newTracks;
  final List<MChart> charts;
  final List<MGenre> genres;

  factory MHome.fromJson(Object? j) {
    final m = vMap(j);
    return MHome(
      daily: [for (final t in vList(m['daily'])) MTrack.fromJson(t)],
      dailyPersonalized: m['daily_personalized'] != false,
      playlists: [for (final p in vList(m['playlists'])) MPlaylist.fromJson(p)],
      newTracks: [for (final t in vList(m['new_tracks'])) MTrack.fromJson(t)],
      charts: [for (final c in vList(m['charts'])) MChart.fromJson(c)],
      genres: [for (final g in vList(m['genres'])) MGenre.fromJson(g)],
    );
  }
}

/// 每日推荐(§8.2 `GET /daily`)。
class MDaily {
  const MDaily({this.date = '', this.personalized = true, this.items = const []});

  final String date;
  final bool personalized;
  final List<MTrack> items;

  factory MDaily.fromJson(Object? j) {
    final m = vMap(j);
    return MDaily(
      date: '${m['date'] ?? ''}',
      personalized: m['personalized'] != false,
      items: [for (final t in vList(m['items'])) MTrack.fromJson(t)],
    );
  }
}

/// 我的歌单一页(§8.2 `GET /me/playlists`)。
class MMyPlaylists {
  const MMyPlaylists({this.created = const [], this.collected = const [], this.collectedReleases = const []});

  final List<MPlaylist> created;
  final List<MPlaylist> collected;
  final List<MRelease> collectedReleases;

  factory MMyPlaylists.fromJson(Object? j) {
    final m = vMap(j);
    return MMyPlaylists(
      created: [for (final p in vList(m['created'])) MPlaylist.fromJson(p)],
      collected: [for (final p in vList(m['collected'])) MPlaylist.fromJson(p)],
      collectedReleases: [for (final r in vList(m['collected_releases'])) MRelease.fromJson(r)],
    );
  }
}

/// 音乐人中心的数据卡(§8.2 `GET /studio/stats`)。
class MStudioStats {
  const MStudioStats({
    this.plays = 0,
    this.listeners = 0,
    this.likes = 0,
    this.fans = 0,
    this.perDay = const [],
    this.topTracks = const [],
  });

  final int plays;
  final int listeners;
  final int likes;
  final int fans;

  /// 每天一行 `{day, plays, listeners}`
  final List<Map<String, dynamic>> perDay;
  final List<MTrack> topTracks;

  factory MStudioStats.fromJson(Object? j) {
    final m = vMap(j);
    return MStudioStats(
      plays: vInt(m['plays']),
      listeners: vInt(m['listeners']),
      likes: vInt(m['likes']),
      fans: vInt(m['fans']),
      perDay: [for (final d in vList(m['per_day'])) vMap(d)],
      topTracks: [for (final t in vList(m['top_tracks'])) MTrack.fromJson(t)],
    );
  }
}

/// 一页结果。分数排的带 `has_more`,时间排的带 `next_cursor`(§5.2)——
/// 直接用视频那边的 [VPage],全站一套翻页约定。
typedef MPage<T> = VPage<T>;

/// 歌名 + 歌手,一行里显示用:「歌名 - 歌手」。
String mTrackLine(MTrack t) => t.artistName.isEmpty ? t.title : '${t.title} - ${t.artistName}';

/// 署名(词曲编制作)摊成几行:`{lyricist:[], composer:[], arranger:[], producer:[]}`。
List<({String label, String names})> mCreditLines(Map<String, dynamic> credits) {
  const labels = {'lyricist': '作词', 'composer': '作曲', 'arranger': '编曲', 'producer': '制作人'};
  final out = <({String label, String names})>[];
  for (final e in labels.entries) {
    final names = [for (final n in vList(credits[e.key])) '$n'].where((s) => s.trim().isNotEmpty).toList();
    if (names.isNotEmpty) out.add((label: e.value, names: names.join('、')));
  }
  return out;
}
