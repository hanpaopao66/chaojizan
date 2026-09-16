// 论坛模块的数据对象(DEV-PROMPTS-41 #381)。字段和规格 §8.1 逐项对应;
// 解析都容错(缺字段给缺省值、类型不对不崩),服务端多加字段不会让旧客户端挂掉。
//
// 人的简卡和翻页壳子直接用视频那份(VPerson / VPage):§5.2 的 person 就是
// `video.people` 生成的 `{id, name, username, avatar}`,同一个形状不写第二遍。
import '../video/models.dart' show VPerson, VPage, vInt, vList, vMap;

/// 人物简卡、页壳子、整数缩写、相对时间都用视频那份,不重复写一遍。
export '../video/models.dart' show VPerson, VPage, vAgo, vCount, vInt, vList, vMap;

int _int(Object? v, [int d = 0]) => v is int ? v : (v is num ? v.toInt() : int.tryParse('$v') ?? d);
String _str(Object? v, [String d = '']) => v is String ? v : (v == null ? d : '$v');
bool _bool(Object? v) => v == true;
Map<String, dynamic> _map(Object? v) => v is Map ? v.cast<String, dynamic>() : <String, dynamic>{};
List<dynamic> _list(Object? v) => v is List ? v : const [];
DateTime? _time(Object? v) => v == null ? null : DateTime.tryParse('$v')?.toLocal();

/// 可空的整数:投票没投过时 `votes` / `total` 是 null(§8.1),
/// 不能拿 0 顶上 —— 0 票和「还看不到票数」是两回事。
///
/// 不是数也给 null(不是 0):`voted: false` 要是被读成 0,
/// 「没投过」就成了「投了第 1 项」,那一项会平白打上勾。
int? _intOrNull(Object? v) {
  if (v == null) return null;
  if (v is num) return v.toInt();
  return int.tryParse('$v');
}

/// 帖子里的一个话题。`tag` 是小写的规范形(跳转用),`display` 是作者原样写的(显示用)。
class FTag {
  const FTag(this.tag, this.display);

  final String tag;
  final String display;

  factory FTag.fromJson(Object? j) {
    final m = _map(j);
    final tag = _str(m['tag']);
    final display = _str(m['display'], tag);
    return FTag(tag, display.isEmpty ? tag : display);
  }
}

/// 帖子里的一个 @ 提及。
class FMention {
  const FMention(this.id, this.username);

  final int id;
  final String username;

  factory FMention.fromJson(Object? j) {
    final m = _map(j);
    return FMention(_int(m['id']), _str(m['username']));
  }
}

/// 服务端解析出来的实体(§5.6:客户端不许自己报,只照着它把正文切成可点片段)。
class FEntities {
  const FEntities({this.tags = const [], this.mentions = const [], this.links = const []});

  final List<FTag> tags;
  final List<FMention> mentions;
  final List<String> links;

  bool get isEmpty => tags.isEmpty && mentions.isEmpty && links.isEmpty;

  factory FEntities.fromJson(Object? j) {
    final m = _map(j);
    return FEntities(
      tags: [for (final t in _list(m['tags'])) FTag.fromJson(t)],
      mentions: [for (final x in _list(m['mentions'])) FMention.fromJson(x)],
      links: [for (final l in _list(m['links'])) '$l'],
    );
  }
}

/// 一张配图(≤4 张,F1)。宽高是上传时量的,用来先占好位置不跳版。
class FMedia {
  const FMedia({required this.url, this.w = 0, this.h = 0});

  final String url;
  final int w;
  final int h;

  /// 宽高比;服务端没给尺寸时按 4:3 摆(比按 1:1 更接近手机拍的照片)
  double get aspect => w > 0 && h > 0 ? w / h : 4 / 3;

  factory FMedia.fromJson(Object? j) {
    final m = _map(j);
    return FMedia(url: _str(m['url']), w: _int(m['w']), h: _int(m['h']));
  }
}

/// 帖子里带的一张站内卡片(歌、歌单、专辑、音乐人、帖子、视频)。
///
/// 服务端按 `{type, id}` 现查现下发快照;查不到(删了、没过审、私密)时只有
/// `type` / `id` 和 [unavailable] —— 这时候画一个灰条,不要装作卡片还在。
class FCard {
  const FCard({required this.type, required this.id, this.title = '', this.subtitle = '',
      this.cover = '', this.url = '', this.unavailable = false});

  final String type;
  final String id;
  final String title;
  final String subtitle;
  final String cover;
  final String url;
  final bool unavailable;

  /// 「歌曲」「歌单」…… 灰条上要写清楚是什么不见了
  String get typeName => const {
        'track': '歌曲',
        'release': '专辑',
        'playlist': '歌单',
        'artist': '音乐人',
        'post': '帖子',
        'video': '视频',
      }[type] ??
      '内容';

  factory FCard.fromJson(Object? j) {
    final m = _map(j);
    return FCard(
      type: _str(m['type']),
      id: _str(m['id']),
      title: _str(m['title']),
      subtitle: _str(m['subtitle']),
      cover: _str(m['cover']),
      url: _str(m['url']),
      unavailable: _bool(m['unavailable']),
    );
  }
}

/// 投票的一项。[votes] 为 null = 还看不到票数(没投过、没结束、又不是作者,§8.1)。
class FPollOption {
  const FPollOption(this.text, this.votes);

  final String text;
  final int? votes;

  factory FPollOption.fromJson(Object? j) {
    final m = _map(j);
    return FPollOption(_str(m['text']), _intOrNull(m['votes']));
  }
}

/// 一次投票(F1:2–4 项、5 分钟–7 天;每人一票、不能改)。
class FPoll {
  const FPoll({this.options = const [], this.total, this.endsAt, this.closed = false, this.voted});

  final List<FPollOption> options;

  /// 总票数;和每项的 votes 一样,看不到结果时是 null
  final int? total;
  final DateTime? endsAt;
  final bool closed;

  /// 我投的是第几项(0 起);没投过是 null
  final int? voted;

  bool get didVote => voted != null;

  /// 票数已经能看了(投过、或者已结束、或者我是作者 —— 判断由服务端做,这里只看给没给数)
  bool get showResults => total != null || options.any((o) => o.votes != null);

  /// 还能投吗:没结束、没投过
  bool get canVote => !closed && !didVote;

  /// 某一项占的比例(0–1)。看不到结果或一票没有时给 0。
  double share(int i) {
    final t = total ?? 0;
    if (t <= 0 || i < 0 || i >= options.length) return 0;
    return (options[i].votes ?? 0) / t;
  }

  factory FPoll.fromJson(Object? j) {
    final m = _map(j);
    return FPoll(
      options: [for (final o in _list(m['options'])) FPollOption.fromJson(o)],
      total: _intOrNull(m['total']),
      endsAt: _time(m['ends_at']),
      closed: _bool(m['closed']),
      voted: _intOrNull(m['voted']),
    );
  }
}

/// 帖子上的各种计数。
class FCounts {
  FCounts({this.replies = 0, this.reposts = 0, this.quotes = 0, this.likes = 0,
      this.bookmarks = 0, this.views = 0});

  int replies;
  int reposts;
  int quotes;
  int likes;
  int bookmarks;
  int views;

  factory FCounts.fromJson(Object? j) {
    final m = _map(j);
    return FCounts(
      replies: _int(m['replies']),
      reposts: _int(m['reposts']),
      quotes: _int(m['quotes']),
      likes: _int(m['likes']),
      bookmarks: _int(m['bookmarks']),
      views: _int(m['views']),
    );
  }
}

/// 「我」对这条帖子做过什么。
class FViewer {
  FViewer({this.liked = false, this.reposted = false, this.bookmarked = false});

  bool liked;
  bool reposted;
  bool bookmarked;

  factory FViewer.fromJson(Object? j) {
    final m = _map(j);
    return FViewer(
      liked: _bool(m['liked']),
      reposted: _bool(m['reposted']),
      bookmarked: _bool(m['bookmarked']),
    );
  }
}

/// 谁能回复(F4)。
const fReplyPolicies = <String, String>{
  'all': '所有人',
  'following': '我关注的人',
  'mentioned': '我提到的人',
};

/// 占位帖子的原因(§8.1)。
const _unavailableText = <String, String>{
  'deleted': '这条帖子已删除',
  'removed': '这条帖子已下架',
  'blocked': '这条帖子看不到',
};

/// 一条帖子。
///
/// **占位也是一条帖子**:串里删了 / 下架了 / 有拉黑关系的位置,服务端只给
/// `{pid, unavailable: true, reason}`(§8.1);引用被引的那条不在了时给
/// `{pid, unavailable: true}`。都走这个类,[unavailable] 为真时除了 pid
/// 什么都别读 —— 页面照样按顺序摆,只是那一条画成灰条。
class FPost {
  FPost({
    required this.pid,
    this.author,
    this.text = '',
    this.entities = const FEntities(),
    this.media = const [],
    this.card,
    this.quote,
    this.replyToPid = '',
    this.replyToAuthor,
    this.rootPid = '',
    this.poll,
    this.replyPolicy = 'all',
    this.canReply = true,
    FCounts? counts,
    FViewer? viewer,
    this.edited = false,
    this.editedAt,
    this.editCount = 0,
    this.createdAt,
    this.pinned = false,
    this.unavailable = false,
    this.reason = '',
    this.rank = const {},
    this.raw = const {},
  })  : counts = counts ?? FCounts(),
        viewer = viewer ?? FViewer();

  final String pid;
  final VPerson? author;
  final String text;
  final FEntities entities;
  final List<FMedia> media;
  final FCard? card;

  /// 引用的那条(不再嵌套引用);被引的删了 / 下架了时是一条 [unavailable] 的占位
  final FPost? quote;

  /// 回复的是哪条(详情页靠它拼上文串)
  final String replyToPid;
  final VPerson? replyToAuthor;
  final String rootPid;
  final FPoll? poll;
  final String replyPolicy;

  /// 「谁能回复」限制到我头上了:回复按钮置灰(F4)
  final bool canReply;
  final FCounts counts;
  final FViewer viewer;
  final bool edited;
  final DateTime? editedAt;
  final int editCount;
  final DateTime? createdAt;
  final bool pinned;

  /// 这一条看不见了(删了 / 下架了 / 拉黑),只有 pid 有效
  final bool unavailable;
  final String reason;

  /// 推荐分的中间量(§5.7,每条推荐都带)
  final Map<String, dynamic> rank;
  final Map<String, dynamic> raw;

  bool get isReply => replyToPid.isNotEmpty;

  String get replyPolicyName => fReplyPolicies[replyPolicy] ?? fReplyPolicies['all']!;

  /// 占位条目上那一行灰字
  String get unavailableText => _unavailableText[reason] ?? '这条帖子已不可见';

  factory FPost.fromJson(Object? j) {
    final m = _map(j);
    final pid = _str(m['pid']);
    if (_bool(m['unavailable'])) {
      return FPost(pid: pid, unavailable: true, reason: _str(m['reason']), raw: m);
    }
    final replyTo = m['reply_to'] == null ? null : _map(m['reply_to']);
    return FPost(
      pid: pid,
      author: m['author'] == null ? null : VPerson.fromJson(m['author']),
      text: _str(m['text']),
      entities: FEntities.fromJson(m['entities']),
      media: [for (final x in _list(m['media'])) FMedia.fromJson(x)],
      card: m['card'] == null ? null : FCard.fromJson(m['card']),
      quote: m['quote'] == null ? null : FPost.fromJson(m['quote']),
      replyToPid: replyTo == null ? '' : _str(replyTo['pid']),
      replyToAuthor: replyTo == null || replyTo['author'] == null ? null : VPerson.fromJson(replyTo['author']),
      rootPid: _str(m['root_pid']),
      poll: m['poll'] == null ? null : FPoll.fromJson(m['poll']),
      replyPolicy: _str(m['reply_policy'], 'all'),
      canReply: m['can_reply'] != false,
      counts: FCounts.fromJson(m['counts']),
      viewer: FViewer.fromJson(m['viewer']),
      edited: _bool(m['edited']),
      editedAt: _time(m['edited_at']),
      editCount: _int(m['edit_count']),
      createdAt: _time(m['created_at']),
      pinned: _bool(m['pinned']),
      rank: _map(m['rank']),
      raw: m,
    );
  }
}

/// 时间线上的一条(§8.1):自己发的帖,或者别人转发的一条帖。
class FTimelineItem {
  const FTimelineItem({required this.type, required this.post, this.by, this.at, this.rank = const {}});

  /// `post` | `repost`
  final String type;
  final FPost post;

  /// 转发条目:谁转的
  final VPerson? by;

  /// 转发条目:什么时候转的
  final DateTime? at;
  final Map<String, dynamic> rank;

  bool get isRepost => type == 'repost';

  factory FTimelineItem.fromJson(Object? j) {
    final m = _map(j);
    // 服务端有可能直接给一条裸帖子(话题页、书签、回复页签都是 page of post),
    // 那时候没有 type 和 post 两层 —— 当成普通条目,不要解析成空帖
    final inner = m['post'] == null ? m : _map(m['post']);
    final type = _str(m['type'], 'post');
    return FTimelineItem(
      type: type == 'repost' ? 'repost' : 'post',
      post: FPost.fromJson(inner),
      by: m['by'] == null ? null : VPerson.fromJson(m['by']),
      at: _time(m['at']),
      rank: _map(m['rank']),
    );
  }

  /// 把裸帖子包成条目(话题页、书签这些只返回帖子的接口用)
  factory FTimelineItem.of(FPost post) => FTimelineItem(type: 'post', post: post, rank: post.rank);
}

/// 热门话题一项(§8.3 `/tags/trending`)。
class FTrendingTag {
  const FTrendingTag({required this.tag, required this.display, this.authors24h = 0,
      this.authors3h = 0, this.score = 0});

  final String tag;
  final String display;
  final int authors24h;
  final int authors3h;
  final double score;

  factory FTrendingTag.fromJson(Object? j) {
    final m = _map(j);
    final tag = _str(m['tag']);
    final display = _str(m['display'], tag);
    return FTrendingTag(
      tag: tag,
      display: display.isEmpty ? tag : display,
      authors24h: _int(m['authors_24h']),
      authors3h: _int(m['authors_3h']),
      score: m['score'] is num ? (m['score'] as num).toDouble() : double.tryParse('${m['score']}') ?? 0,
    );
  }
}

/// 个人主页头部(§8.3 `/users/{uid}/profile`)。
class FProfile {
  const FProfile({required this.user, this.bio = '', this.joinedAt, this.posts = 0,
      this.following = 0, this.fans = 0, this.followed = false, this.followsYou = false, this.pinned});

  final VPerson user;
  final String bio;
  final DateTime? joinedAt;
  final int posts;
  final int following;
  final int fans;
  final bool followed;
  final bool followsYou;
  final FPost? pinned;

  factory FProfile.fromJson(Object? j) {
    final m = _map(j);
    return FProfile(
      user: VPerson.fromJson(m['user']),
      bio: _str(m['bio']),
      joinedAt: _time(m['joined_at']),
      posts: _int(m['posts']),
      following: _int(m['following']),
      fans: _int(m['fans']),
      followed: _bool(m['followed']),
      followsYou: _bool(m['follows_you']),
      pinned: m['pinned'] == null ? null : FPost.fromJson(m['pinned']),
    );
  }

  FProfile copyWith({bool? followed, int? fans}) => FProfile(
      user: user, bio: bio, joinedAt: joinedAt, posts: posts, following: following,
      fans: fans ?? this.fans, followed: followed ?? this.followed,
      followsYou: followsYou, pinned: pinned);
}

/// 一次编辑留下的旧正文(§8.3 `/posts/{pid}/edits`)。
class FEdit {
  const FEdit({this.text = '', this.createdAt});

  final String text;
  final DateTime? createdAt;

  factory FEdit.fromJson(Object? j) {
    final m = _map(j);
    return FEdit(text: _str(m['text']), createdAt: _time(m['created_at']));
  }
}

/// 编辑窗口:发出后 30 分钟内、最多 5 次(F3)。
const int kEditWindowMinutes = 30;
const int kEditMaxCount = 5;

/// 正文上限、图片上限、投票项数和时长(F1)。
const int kPostMaxChars = 500;
const int kPostMaxImages = 4;
const int kPollMinOptions = 2;
const int kPollMaxOptions = 4;
const int kPollOptionMaxChars = 25;
const int kPollMinMinutes = 5;
const int kPollMaxMinutes = 7 * 24 * 60;

/// 屏蔽词每人最多 100 个(§7.2)。
const int kMuteWordsMax = 100;

/// 这条帖子还能不能编辑(F3:作者本人、30 分钟内、不超过 5 次)。
/// 「是不是本人」由调用方判断 —— 这里只管时间和次数。
bool fCanEdit(FPost post, {DateTime? now}) {
  final t = post.createdAt;
  if (t == null || post.unavailable) return false;
  if (post.editCount >= kEditMaxCount) return false;
  return (now ?? DateTime.now()).difference(t).inMinutes < kEditWindowMinutes;
}

/// 投票还剩多久:「还有 2 天」「还有 3 小时」「还有 12 分钟」「已结束」。
String fPollLeft(FPoll poll, {DateTime? now}) {
  if (poll.closed) return '已结束';
  final end = poll.endsAt;
  if (end == null) return '';
  final d = end.difference(now ?? DateTime.now());
  if (d.isNegative || d.inMinutes < 1) return '已结束';
  if (d.inDays >= 1) return '还有 ${d.inDays} 天';
  if (d.inHours >= 1) return '还有 ${d.inHours} 小时';
  return '还有 ${d.inMinutes} 分钟';
}

/// 把帖子里的一段中间量摊成一句「为什么推荐」。服务端给了 `why` 就用它的。
String fRankWhy(Map<String, dynamic> rank) {
  final why = rank['why'];
  if (why is String && why.isNotEmpty) return why;
  final parts = vMap(rank['parts']);
  if (parts.isEmpty) return '';
  final bits = <String>[
    if (vInt(parts['likes']) > 0) '${vInt(parts['likes'])} 人赞',
    if (vInt(parts['reposts']) > 0) '${vInt(parts['reposts'])} 人转发',
    if (vInt(parts['quotes']) > 0) '${vInt(parts['quotes'])} 人引用',
    if (vInt(parts['repliers']) > 0) '${vInt(parts['repliers'])} 人回复',
  ];
  return bits.join('、');
}

/// 把一页 `{items, has_more, next_cursor}` 拆成条目 + 翻页信息(和视频 VPage 同一个口径)。
VPage<T> fPage<T>(Object? r, T Function(Object? item) of) {
  final m = vMap(r);
  return VPage([for (final x in vList(m['items'])) of(x)],
      hasMore: m['has_more'] == true, nextCursor: m['next_cursor'] as String?, extra: m);
}
