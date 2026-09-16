import 'package:superz_shared/superz_shared.dart';

import 'models.dart';

/// 论坛接口(`/forum/v1`,DEV-PROMPTS-41 §8.3)和全站共用的关注(`/social/v1`,§8.4)。
///
/// 浏览类不登录也能调 —— ApiClient 没 token 时不带 Authorization 头,服务端按游客给数据。
/// 关注**不走论坛自己的路径**:§8.4 的 `/social/v1/users/{id}/follow` 是全站一张表,
/// 论坛、音乐、视频都调它,这里不另写一套。
class ForumApi {
  ForumApi(this.api);

  final ApiClient api;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) => api.requestJson('GET', path,
      query: q == null ? null : {for (final e in q.entries) if (e.value != null) e.key: '${e.value}'});
  Future<dynamic> _post(String path, [Object? body]) => api.requestJson('POST', path, body: body ?? const {});
  Future<dynamic> _patch(String path, Object body) => api.requestJson('PATCH', path, body: body);
  Future<dynamic> _delete(String path, [Object? body]) => api.requestJson('DELETE', path, body: body);

  /// 503:`forum_enabled` 关着(「论坛暂未开放」)或 `forum_post_enabled` 关着
  /// (「论坛发帖暂停中」)。文案用服务端原话,这里只判要不要给重试按钮 —— 不给。
  static bool isOff(Object e) => e is ApiException && e.statusCode == 503;

  static FPost _post_(Object? r) => FPost.fromJson(r);

  static VPage<FPost> _posts(Object? r) => fPage(r, FPost.fromJson);
  static VPage<FTimelineItem> _items(Object? r) => fPage(r, FTimelineItem.fromJson);
  static VPage<VPerson> _people(Object? r) => fPage(r, VPerson.fromJson);

  // ---------------- 时间线 ----------------

  /// 推荐(§5.7,按分数排,page 分页)
  Future<VPage<FTimelineItem>> foryou(int page) async =>
      _items(await _get('/forum/v1/timeline/foryou', {'page': page}));

  /// 关注的人的帖子和转发,倒序(cursor 分页)
  Future<VPage<FTimelineItem>> followingTimeline({String? cursor}) async =>
      _items(await _get('/forum/v1/timeline/following', {'cursor': cursor}));

  // ---------------- 帖子 ----------------

  /// 发帖 / 回复 / 引用。[media] 是 `/uploads?purpose=forum` 传上来的地址。
  Future<FPost> createPost({
    String text = '',
    List<String> media = const [],
    Map<String, dynamic>? card,
    String? quotePid,
    String? replyToPid,
    List<String>? pollOptions,
    int? pollMinutes,
    String? replyPolicy,
  }) async =>
      _post_(await _post('/forum/v1/posts', {
        'text': text,
        if (media.isNotEmpty) 'media': media,
        if (card != null) 'card': card,
        if (quotePid != null) 'quote_pid': quotePid,
        if (replyToPid != null) 'reply_to_pid': replyToPid,
        if (pollOptions != null && pollOptions.isNotEmpty)
          'poll': {'options': pollOptions, 'minutes': pollMinutes ?? kPollMinMinutes},
        if (replyPolicy != null) 'reply_policy': replyPolicy,
      }));

  /// 详情 + 上文串(`ancestors` 里可能夹着占位)
  Future<({FPost post, List<FPost> ancestors})> post(String pid) async {
    final m = vMap(await _get('/forum/v1/posts/$pid'));
    return (
      post: FPost.fromJson(m['post']),
      ancestors: [for (final x in vList(m['ancestors'])) FPost.fromJson(x)],
    );
  }

  Future<VPage<FPost>> replies(String pid, {String sort = 'top', String? cursor}) async =>
      _posts(await _get('/forum/v1/posts/$pid/replies', {'sort': sort, 'cursor': cursor}));

  /// 改正文(F3:30 分钟内、最多 5 次;投票和图片不能改)
  Future<FPost> editPost(String pid, String text) async =>
      _post_(await _patch('/forum/v1/posts/$pid', {'text': text}));

  Future<List<FEdit>> edits(String pid) async {
    final r = await _get('/forum/v1/posts/$pid/edits');
    // 这个接口直接返回数组(§8.3),不是 {items}
    final list = r is List ? r : vList(vMap(r)['items']);
    return [for (final x in list) FEdit.fromJson(x)];
  }

  Future<void> deletePost(String pid) => _delete('/forum/v1/posts/$pid');

  Future<Map<String, dynamic>> like(String pid, bool on) async =>
      vMap(await (on ? _post('/forum/v1/posts/$pid/like') : _delete('/forum/v1/posts/$pid/like')));

  Future<Map<String, dynamic>> repost(String pid, bool on) async =>
      vMap(await (on ? _post('/forum/v1/posts/$pid/repost') : _delete('/forum/v1/posts/$pid/repost')));

  Future<Map<String, dynamic>> bookmark(String pid, bool on) async =>
      vMap(await (on ? _post('/forum/v1/posts/$pid/bookmark') : _delete('/forum/v1/posts/$pid/bookmark')));

  Future<VPage<FPost>> quotes(String pid, {String? cursor}) async =>
      _posts(await _get('/forum/v1/posts/$pid/quotes', {'cursor': cursor}));

  Future<VPage<VPerson>> likers(String pid, {String? cursor}) async =>
      _people(await _get('/forum/v1/posts/$pid/likers', {'cursor': cursor}));

  /// 投票(每人一票、不能改),返回投完的 poll
  Future<FPoll> vote(String pid, int option) async =>
      FPoll.fromJson(await _post('/forum/v1/posts/$pid/vote', {'option': option}));

  /// 浏览上报(F5:客户端攒起来批量报,服务端按人按天去重)。没登录带 device_id。
  Future<void> reportViews(List<String> pids, {String? deviceId}) =>
      _post('/forum/v1/posts/views', {'pids': pids, if (deviceId != null) 'device_id': deviceId});

  Future<void> pin(String pid, bool on) =>
      on ? _post('/forum/v1/posts/$pid/pin') : _delete('/forum/v1/posts/$pid/pin');

  /// 被下架了,申诉一次(换人复核)
  Future<void> appeal(String pid, String text) => _post('/forum/v1/posts/$pid/appeal', {'text': text});

  Future<void> report(String pid, String reasonCode, {String note = ''}) =>
      _post('/forum/v1/reports', {'pid': pid, 'reason_code': reasonCode, 'note': note});

  // ---------------- 人 ----------------

  Future<FProfile> profile(int userId) async => FProfile.fromJson(await _get('/forum/v1/users/$userId/profile'));

  /// 主页四个页签。`posts` 含转发(是 timeline item),其余是裸帖子 —— 统一包成条目。
  Future<VPage<FTimelineItem>> userPosts(int userId, {String tab = 'posts', String? cursor}) async =>
      _items(await _get('/forum/v1/users/$userId/posts', {'tab': tab, 'cursor': cursor}));

  // ---------------- 我的 ----------------

  Future<VPage<FPost>> bookmarks({String? cursor}) async =>
      _posts(await _get('/forum/v1/me/bookmarks', {'cursor': cursor}));

  Future<List<String>> muteWords() async => _words(await _get('/forum/v1/me/mute-words'));
  Future<List<String>> addMuteWord(String word) async =>
      _words(await _post('/forum/v1/me/mute-words', {'word': word}));
  Future<List<String>> removeMuteWord(String word) async =>
      _words(await _delete('/forum/v1/me/mute-words', {'word': word}));

  static List<String> _words(Object? r) {
    final list = r is List ? r : vList(vMap(r)['items']);
    return [for (final x in list) '$x'];
  }

  Future<Map<String, dynamic>> settings() async => vMap(await _get('/forum/v1/me/settings'));
  Future<Map<String, dynamic>> putSettings({required bool personalize}) async =>
      vMap(await api.requestJson('PUT', '/forum/v1/me/settings', body: {'personalize': personalize}));

  // ---------------- 话题与搜索 ----------------

  Future<({List<FTrendingTag> items, DateTime? updatedAt})> trending() async {
    final m = vMap(await _get('/forum/v1/tags/trending'));
    return (
      items: [for (final x in vList(m['items'])) FTrendingTag.fromJson(x)],
      updatedAt: DateTime.tryParse('${m['updated_at']}')?.toLocal(),
    );
  }

  /// 话题下的帖子。`top` 按分数(page),`new` 按时间(cursor)。
  Future<VPage<FPost>> tagPosts(String tag, {String sort = 'top', String? cursor, int? page}) async =>
      _posts(await _get('/forum/v1/tags/${Uri.encodeComponent(tag)}/posts',
          {'sort': sort, 'cursor': cursor, 'page': page}));

  Future<VPage<FPost>> searchPosts(String q, {int page = 0}) async =>
      _posts(await _get('/forum/v1/search', {'q': q, 'type': 'posts', 'page': page}));

  Future<VPage<VPerson>> searchUsers(String q, {int page = 0}) async =>
      _people(await _get('/forum/v1/search', {'q': q, 'type': 'users', 'page': page}));

  Future<VPage<FTrendingTag>> searchTags(String q, {int page = 0}) async =>
      fPage(await _get('/forum/v1/search', {'q': q, 'type': 'tags', 'page': page}), FTrendingTag.fromJson);

  /// 推荐公式和参数(§5.7,原样摊给用户看)
  Future<Map<String, dynamic>> formula() async => vMap(await _get('/forum/v1/rank/formula'));

  // ---------------- 全站关注(§8.4,不挂论坛开关) ----------------

  Future<Map<String, dynamic>> follow(int userId, bool on) async => vMap(await (on
      ? _post('/social/v1/users/$userId/follow')
      : _delete('/social/v1/users/$userId/follow')));

  Future<Map<String, dynamic>> followStats(int userId) async =>
      vMap(await _get('/social/v1/users/$userId/follow-stats'));

  Future<VPage<VPerson>> followers(int userId, {String? cursor}) async =>
      _people(await _get('/social/v1/users/$userId/followers', {'cursor': cursor}));

  Future<VPage<VPerson>> following(int userId, {String? cursor}) async =>
      _people(await _get('/social/v1/users/$userId/following', {'cursor': cursor}));

  // ---------------- 图片 ----------------

  /// 发帖配图走公开图片用途 `forum`(§8.3),返回相对地址,展示时再补全。
  Future<String> uploadImage(List<int> bytes, String filename) =>
      api.uploadImage(bytes, filename, purpose: 'forum', timeout: const Duration(seconds: 60));
}
