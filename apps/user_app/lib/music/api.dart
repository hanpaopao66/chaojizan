// 音乐接口(`/music/v1`,DEV-PROMPTS-41 §8.2)。照 video/api.dart 的写法:
// 一个方法对一条路由,返回解析好的模型;没登录也能调的浏览类接口照样走这里
// (ApiClient 没 token 时不带 Authorization 头,§4 M5「不登录也能听」)。
import 'dart:math';
import 'dart:typed_data';

import 'package:superz_shared/superz_shared.dart';

import '../video/models.dart';
import 'models.dart';

class MusicApi {
  MusicApi(this.api);

  final ApiClient api;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) =>
      api.requestJson('GET', path, query: q?.map((k, v) => MapEntry(k, '$v')));
  Future<dynamic> _post(String path, [Object? body]) => api.requestJson('POST', path, body: body ?? const {});
  Future<dynamic> _patch(String path, Object body) => api.requestJson('PATCH', path, body: body);
  Future<dynamic> _put(String path, Object body) => api.requestJson('PUT', path, body: body);
  Future<dynamic> _delete(String path) => api.requestJson('DELETE', path);

  /// 503「音乐暂未开放」/「音乐投稿暂未开放」(§5.2:开关关着时整个前缀 503)。
  /// 这不是故障,是急停闸 —— 页面给空状态、**不给重试按钮**。
  static bool isOff(Object e) => e is ApiException && e.statusCode == 503;

  static List<MTrack> _tracks(Object? items) => [for (final x in vList(items)) MTrack.fromJson(x)];

  static MPage<MTrack> _trackPage(Object? r) {
    final m = vMap(r);
    return MPage(_tracks(m['items']),
        hasMore: m['has_more'] == true, nextCursor: m['next_cursor'] as String?, extra: m);
  }

  // ---------------- 发现 ----------------

  Future<MHome> home() async => MHome.fromJson(await _get('/music/v1/home'));

  Future<List<MGenre>> genres() async {
    final r = await _get('/music/v1/genres');
    // 曲风表是个裸数组(§8.2),兼容包一层 items 的写法
    final list = r is List ? r : vList(vMap(r)['items']);
    return [for (final g in list) MGenre.fromJson(g)];
  }

  Future<MPage<MTrack>> genreTracks(String key, {int page = 0}) async =>
      _trackPage(await _get('/music/v1/genres/$key/tracks', {'page': page}));

  Future<List<MChart>> charts() async {
    final r = await _get('/music/v1/charts');
    final list = r is List ? r : vList(vMap(r)['items']);
    return [for (final c in list) MChart.fromJson(c)];
  }

  Future<MChart> chart(String key) async => MChart.fromJson(await _get('/music/v1/charts/$key'));

  Future<MDaily> daily() async => MDaily.fromJson(await _get('/music/v1/daily'));

  Future<Map<String, dynamic>> formula() async => vMap(await _get('/music/v1/rank/formula'));

  Future<MPage<MPlaylist>> recommendedPlaylists({int page = 0}) async {
    final m = vMap(await _get('/music/v1/playlists/recommended', {'page': page}));
    return MPage([for (final p in vList(m['items'])) MPlaylist.fromJson(p)],
        hasMore: m['has_more'] == true, extra: m);
  }

  /// 搜索:`type ∈ track|artist|release|playlist`。返回的原始一页,由调用方按 type 解析。
  Future<MPage<dynamic>> search(String q, {String type = 'track', int page = 0}) async {
    final m = vMap(await _get('/music/v1/search', {'q': q, 'type': type, 'page': page}));
    return MPage(vList(m['items']), hasMore: m['has_more'] == true, nextCursor: m['next_cursor'] as String?, extra: m);
  }

  // ---------------- 歌曲 ----------------

  Future<MTrack> track(String tid) async => MTrack.fromJson(await _get('/music/v1/tracks/$tid'));

  /// 歌词 `{kind, text}`(§4 M8:LRC 或纯文本)
  Future<({String kind, String text})> lyrics(String tid) async {
    final m = vMap(await _get('/music/v1/tracks/$tid/lyrics'));
    return (kind: '${m['kind'] ?? 'none'}', text: '${m['text'] ?? ''}');
  }

  /// 重新签播放地址(§5.5:6 小时有效,过期或 403/404 时重签)
  Future<MStream> stream(String tid) async => MStream.fromJson(await _get('/music/v1/tracks/$tid/stream'));

  /// 收听上报:切歌或播完时报一次**实际听了多少毫秒**(不是拖到的位置,§5.5)
  Future<bool> reportPlay(String tid, {required int msListened, String? deviceId, String? context}) async {
    final r = vMap(await _post('/music/v1/tracks/$tid/play', {
      'ms_listened': msListened,
      if (deviceId != null && deviceId.isNotEmpty) 'device_id': deviceId,
      if (context != null && context.isNotEmpty) 'context': context,
    }));
    return r['counted'] == true;
  }

  Future<({bool liked, int likes})> likeTrack(String tid, bool like) async {
    final r = vMap(like ? await _post('/music/v1/tracks/$tid/like') : await _delete('/music/v1/tracks/$tid/like'));
    return (liked: r['liked'] == true, likes: vInt(r['likes']));
  }

  // ---------------- 评论 ----------------

  /// 评论列表。第一页带 `hot:[≤3]`(热评),`sort ∈ hot|new`。
  Future<MPage<MComment>> comments(String tid, {String sort = 'hot', int? page, String? cursor}) async {
    final m = vMap(await _get('/music/v1/tracks/$tid/comments', {
      'sort': sort,
      if (page != null) 'page': page,
      if (cursor != null) 'cursor': cursor,
    }));
    return MPage([for (final c in vList(m['items'])) MComment.fromJson(c)],
        hasMore: m['has_more'] == true, nextCursor: m['next_cursor'] as String?, extra: m);
  }

  /// 第一页里的热评(没有就是空)
  static List<MComment> hotOf(MPage<MComment> page) =>
      [for (final c in vList(page.extra['hot'])) MComment.fromJson(c)];

  Future<MPage<MComment>> commentReplies(int commentId, {String? cursor}) async {
    final m = vMap(await _get('/music/v1/comments/$commentId/replies', {if (cursor != null) 'cursor': cursor}));
    return MPage([for (final c in vList(m['items'])) MComment.fromJson(c)],
        hasMore: m['has_more'] == true, nextCursor: m['next_cursor'] as String?, extra: m);
  }

  Future<MComment> comment(String tid, String text, {int? parentId}) async => MComment.fromJson(
      await _post('/music/v1/tracks/$tid/comments', {'text': text, if (parentId != null) 'parent_id': parentId}));

  Future<void> deleteComment(int id) => _delete('/music/v1/comments/$id');

  Future<({bool liked, int likes})> likeComment(int id, bool like) async {
    final r = vMap(like ? await _post('/music/v1/comments/$id/like') : await _delete('/music/v1/comments/$id/like'));
    return (liked: r['liked'] == true, likes: vInt(r['likes']));
  }

  // ---------------- 我的 ----------------

  Future<MPage<MTrack>> myLikes({String? cursor}) async =>
      _trackPage(await _get('/music/v1/me/likes', {if (cursor != null) 'cursor': cursor}));

  Future<List<MTrack>> history() async => _tracks(vMap(await _get('/music/v1/me/history'))['items']);

  Future<void> clearHistory() => _delete('/music/v1/me/history');

  Future<MMyPlaylists> myPlaylists() async => MMyPlaylists.fromJson(await _get('/music/v1/me/playlists'));

  Future<bool> personalize() async => vMap(await _get('/music/v1/me/settings'))['personalize'] != false;

  Future<bool> setPersonalize(bool on) async =>
      vMap(await _put('/music/v1/me/settings', {'personalize': on}))['personalize'] != false;

  // ---------------- 歌单 ----------------

  Future<MPlaylist> createPlaylist(String title,
          {String? description, bool isPublic = true, List<String>? tags, String? coverUrl}) async =>
      MPlaylist.fromJson(await _post('/music/v1/playlists', {
        'title': title,
        if (description != null) 'description': description,
        'is_public': isPublic,
        if (tags != null) 'tags': tags,
        if (coverUrl != null && coverUrl.isNotEmpty) 'cover_url': coverUrl,
      }));

  Future<MPlaylist> playlist(String pid) async => MPlaylist.fromJson(await _get('/music/v1/playlists/$pid'));

  Future<MPlaylist> patchPlaylist(String pid,
          {String? title, String? description, bool? isPublic, List<String>? tags, String? coverUrl}) async =>
      MPlaylist.fromJson(await _patch('/music/v1/playlists/$pid', {
        if (title != null) 'title': title,
        if (description != null) 'description': description,
        if (isPublic != null) 'is_public': isPublic,
        if (tags != null) 'tags': tags,
        if (coverUrl != null) 'cover_url': coverUrl,
      }));

  Future<void> deletePlaylist(String pid) => _delete('/music/v1/playlists/$pid');

  /// 加歌(服务端去重,一个歌单最多 1000 首)
  Future<({int added, int trackCount})> addToPlaylist(String pid, List<String> tids) async {
    final r = vMap(await _post('/music/v1/playlists/$pid/tracks', {'tids': tids}));
    return (added: vInt(r['added']), trackCount: vInt(r['track_count']));
  }

  Future<int> removeFromPlaylist(String pid, String tid) async =>
      vInt(vMap(await _delete('/music/v1/playlists/$pid/tracks/$tid'))['track_count']);

  /// 全量新顺序
  Future<void> orderPlaylist(String pid, List<String> tids) => _put('/music/v1/playlists/$pid/order', {'tids': tids});

  Future<({bool collected, int collects})> collectPlaylist(String pid, bool collect) async {
    final r = vMap(collect
        ? await _post('/music/v1/playlists/$pid/collect')
        : await _delete('/music/v1/playlists/$pid/collect'));
    return (collected: r['collected'] == true, collects: vInt(r['collects']));
  }

  // ---------------- 作品与音乐人 ----------------

  Future<MRelease> release(String rid) async => MRelease.fromJson(await _get('/music/v1/releases/$rid'));

  Future<({bool collected, int collects})> collectRelease(String rid, bool collect) async {
    final r = vMap(
        collect ? await _post('/music/v1/releases/$rid/collect') : await _delete('/music/v1/releases/$rid/collect'));
    return (collected: r['collected'] == true, collects: vInt(r['collects']));
  }

  Future<MArtist> artist(String aid) async => MArtist.fromJson(await _get('/music/v1/artists/$aid'));

  Future<MPage<MTrack>> artistTracks(String aid, {int page = 0}) async =>
      _trackPage(await _get('/music/v1/artists/$aid/tracks', {'page': page}));

  /// 关注音乐人 = 关注他的超级赞账号(§8.4,全站一张关注表,不挂模块开关)
  Future<({bool followed, int fans})> followUser(int userId, bool follow) async {
    final r = vMap(follow
        ? await _post('/social/v1/users/$userId/follow')
        : await _delete('/social/v1/users/$userId/follow'));
    return (followed: r['followed'] == true, fans: vInt(r['fans']));
  }

  // ---------------- 举报 ----------------

  /// `target_type ∈ track|release|comment|playlist|artist`;版权投诉要留联系方式(§7.1)
  Future<void> report({
    required String targetType,
    required String targetId,
    required String reasonCode,
    String note = '',
    String contact = '',
  }) =>
      _post('/music/v1/reports', {
        'target_type': targetType,
        'target_id': targetId,
        'reason_code': reasonCode,
        if (note.isNotEmpty) 'note': note,
        if (contact.isNotEmpty) 'contact': contact,
      });

  // ---------------- 音乐人中心 ----------------

  /// 没开通时 `artist` 是 null
  Future<MArtist?> studioMe() async {
    final m = vMap(await _get('/music/v1/studio/me'));
    return m['artist'] == null ? null : MArtist.fromJson(m['artist']);
  }

  Future<MArtist> openArtist({required String name, String bio = '', List<String> genres = const []}) async =>
      MArtist.fromJson(await _post('/music/v1/studio/artist', {'name': name, 'bio': bio, 'genres': genres}));

  Future<MArtist> patchArtist(
          {String? name, String? bio, List<String>? genres, String? avatarUrl, String? coverUrl}) async =>
      MArtist.fromJson(await _patch('/music/v1/studio/artist', {
        if (name != null) 'name': name,
        if (bio != null) 'bio': bio,
        if (genres != null) 'genres': genres,
        if (avatarUrl != null) 'avatar_url': avatarUrl,
        if (coverUrl != null) 'cover_url': coverUrl,
      }));

  Future<List<MRelease>> studioReleases() async {
    final r = await _get('/music/v1/studio/releases');
    final list = r is List ? r : vList(vMap(r)['items']);
    return [for (final x in list) MRelease.fromJson(x)];
  }

  /// 一个作品的详情(编辑页要它)。
  ///
  /// §8.2 的表里只列了 `GET /studio/releases`(全部),没有单个的那一条。
  /// 所以这里**先试单个,不认就退回从列表里挑** —— 服务端那边实现了哪一种都能用,
  /// 不用两个 agent 先对一次口径。
  Future<MRelease> studioRelease(String rid) async {
    try {
      return MRelease.fromJson(await _get('/music/v1/studio/releases/$rid'));
    } on ApiException catch (e) {
      // 开关关着(503)、没权限(403)这些是真的错,原样抛出去;
      // 只有「没这条路由」才退回列表
      if (e.statusCode != 404 && e.statusCode != 405) rethrow;
      final all = await studioReleases();
      final hit = all.where((r) => r.rid == rid);
      if (hit.isEmpty) rethrow;
      return hit.first;
    }
  }

  Future<MRelease> createRelease({
    required String title,
    required String kind,
    required String genre,
    required String language,
    String description = '',
    String releaseDate = '',
    int? coverMediaId,
  }) async =>
      MRelease.fromJson(await _post('/music/v1/studio/releases', {
        'title': title,
        'kind': kind,
        'genre': genre,
        'language': language,
        if (description.isNotEmpty) 'description': description,
        if (releaseDate.isNotEmpty) 'release_date': releaseDate,
        if (coverMediaId != null) 'cover_media_id': coverMediaId,
      }));

  Future<MRelease> patchRelease(String rid, Map<String, dynamic> body) async =>
      MRelease.fromJson(await _patch('/music/v1/studio/releases/$rid', body));

  Future<void> deleteRelease(String rid) => _delete('/music/v1/studio/releases/$rid');

  /// 加歌:[mediaId] 是 `/media/v1` 用途 `music`、类型 `audio_source` 传上来的
  Future<MTrack> addTrack(
    String rid, {
    required String title,
    required int mediaId,
    required String declaration,
    String lyrics = '',
    Map<String, dynamic>? credits,
    bool explicit = false,
  }) async =>
      MTrack.fromJson(await _post('/music/v1/studio/releases/$rid/tracks', {
        'title': title,
        'media_id': mediaId,
        'declaration': declaration,
        if (lyrics.isNotEmpty) 'lyrics': lyrics,
        if (credits != null) 'credits': credits,
        'explicit': explicit,
      }));

  Future<MTrack> patchTrack(String tid, Map<String, dynamic> body) async =>
      MTrack.fromJson(await _patch('/music/v1/studio/tracks/$tid', body));

  Future<void> deleteTrack(String tid) => _delete('/music/v1/studio/tracks/$tid');

  Future<void> orderTracks(String rid, List<String> tids) =>
      _put('/music/v1/studio/releases/$rid/order', {'tids': tids});

  Future<MRelease> submitRelease(String rid) async =>
      MRelease.fromJson(await _post('/music/v1/studio/releases/$rid/submit'));

  /// 撤回提交(还在审核队列里时)
  Future<MRelease> cancelSubmit(String rid) async =>
      MRelease.fromJson(await _post('/music/v1/studio/releases/$rid/cancel'));

  /// 已发布的自己下架
  Future<MRelease> withdrawRelease(String rid) async =>
      MRelease.fromJson(await _post('/music/v1/studio/releases/$rid/withdraw'));

  /// 申诉最近一次驳回或下架(每个决定只能申诉一次,§5.3)
  Future<void> appeal(String rid, String text) => _post('/music/v1/studio/releases/$rid/appeal', {'text': text});

  Future<MStudioStats> studioStats({int days = 30}) async =>
      MStudioStats.fromJson(await _get('/music/v1/studio/stats', {'days': days}));

  // ---------------- 上传 ----------------

  /// 传音频原文件:≤ 8MB 一次传完,更大的分片(4MB 一片,可续传),[onProgress] 0–1。
  /// 和投稿原片走同一套 `/media/v1`,只是用途换成 `music`(§8.2 末尾)。
  Future<Map<String, dynamic>> uploadAudio(
    Future<Uint8List> Function(int start, int end) read,
    int size,
    String name, {
    void Function(double p)? onProgress,
  }) async {
    const kind = 'audio_source';
    if (size <= 8 * 1024 * 1024) {
      final m = await api.uploadMediaBytes(await read(0, size), name,
          kind: kind, purpose: 'music', timeout: const Duration(minutes: 10));
      onProgress?.call(1);
      return m;
    }
    final up = vMap(await _post('/media/v1/uploads', {'size': size, 'name': name, 'kind': kind, 'purpose': 'music'}));
    final id = '${up['id']}';
    final chunk = vInt(up['chunk_size']) > 0 ? vInt(up['chunk_size']) : 4 * 1024 * 1024;
    final total = (size + chunk - 1) ~/ chunk;
    final have = {for (final x in vList(up['received'])) vInt(x)};
    for (var n = 0; n < total; n++) {
      if (!have.contains(n)) {
        final start = n * chunk;
        await api.putMediaChunk(id, n, await read(start, min(size, start + chunk)));
      }
      onProgress?.call((n + 1) / total);
    }
    return vMap(await _post('/media/v1/uploads/$id/complete', {'kind': kind}));
  }

  /// 作品封面:审核前是私密的,所以走 `/media/v1` 拿 media_id,不是公开图片
  Future<Map<String, dynamic>> uploadReleaseCover(List<int> bytes, String name) =>
      api.uploadMediaBytes(bytes, name, kind: 'cover', purpose: 'music');

  /// 音乐人头像 / 横幅、歌单封面:公开图片走现有的 `POST /uploads`,用途 `music_cover`
  /// (§8.2 末尾;这些图过审前后都公开,和作品封面不是一回事)。返回图片地址。
  Future<String> uploadPublicImage(List<int> bytes, String name) =>
      api.uploadImage(bytes, name, purpose: 'music_cover');
}
