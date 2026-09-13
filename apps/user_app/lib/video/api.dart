import 'dart:math';
import 'dart:typed_data';

import 'package:superz_shared/superz_shared.dart';

import 'models.dart';

/// 视频接口(`/video/v1`、`/social/v1/notifications`,docs/VIDEO-API.md)。
///
/// 没登录也能用的浏览类接口照样走这里 —— ApiClient 没 token 时不带 Authorization 头。
class VideoApi {
  VideoApi(this.api);

  final ApiClient api;

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) =>
      api.requestJson('GET', path, query: q?.map((k, v) => MapEntry(k, '$v')));
  Future<dynamic> _post(String path, [Object? body]) => api.requestJson('POST', path, body: body ?? const {});
  Future<dynamic> _patch(String path, Object body) => api.requestJson('PATCH', path, body: body);
  Future<dynamic> _delete(String path) => api.requestJson('DELETE', path);

  /// 503「视频功能暂未开放」(生产缺省关,等许可证,#375):视频 tab 显示空状态,不要重试
  static bool isOff(Object e) => e is ApiException && e.statusCode == 503;

  static List<VideoCard> _cards(Object? items) => [for (final x in vList(items)) VideoCard.fromJson(x)];

  static VPage<VideoCard> _pageOf(Object? r) {
    final m = vMap(r);
    return VPage(_cards(m['items']),
        hasMore: m['has_more'] == true, nextCursor: m['next_cursor'] as String?, extra: m);
  }

  // ---------------- 浏览 ----------------

  Future<VPage<VideoCard>> recommend(int page) async => _pageOf(await _get('/video/v1/feed/recommend', {'page': page}));
  Future<VPage<VideoCard>> hot(int page) async => _pageOf(await _get('/video/v1/feed/hot', {'page': page}));
  Future<VPage<VideoCard>> vertical(int page) async => _pageOf(await _get('/video/v1/feed/vertical', {'page': page}));
  Future<VPage<VideoCard>> following(String? cursor) async =>
      _pageOf(await _get('/video/v1/feed/following', {if (cursor != null) 'cursor': cursor}));

  Future<List<Map<String, dynamic>>> zones() async =>
      [for (final z in vList(vMap(await _get('/video/v1/zones'))['items'])) vMap(z)];

  Future<VPage<VideoCard>> zone(String zone, {String order = 'hot', int page = 0}) async =>
      _pageOf(await _get('/video/v1/zones/$zone', {'order': order, 'page': page}));

  Future<VPage<VideoCard>> rank({String? zone, int days = 1}) async =>
      _pageOf(await _get('/video/v1/rank', {if (zone != null && zone.isNotEmpty) 'zone': zone, 'days': days}));

  Future<Map<String, dynamic>> formula() async => vMap(await _get('/video/v1/rank/formula'));

  Future<VideoDetail> detail(String vid) async => VideoDetail.fromJson(await _get('/video/v1/videos/$vid'));

  Future<List<VideoCard>> related(String vid) async => _cards(vMap(await _get('/video/v1/videos/$vid/related'))['items']);

  Future<VPage<VideoCard>> search(String q, {String order = 'default', int duration = 0, String? zone, int page = 0}) async =>
      _pageOf(await _get('/video/v1/search', {
        'q': q,
        'order': order,
        'duration': duration,
        if (zone != null && zone.isNotEmpty) 'zone': zone,
        'page': page,
      }));

  Future<VPage<VPerson>> searchUsers(String q, {int page = 0}) async {
    final m = vMap(await _get('/video/v1/search/users', {'q': q, 'page': page}));
    return VPage([for (final x in vList(m['items'])) VPerson.fromJson(x)], hasMore: m['has_more'] == true);
  }

  Future<List<Map<String, dynamic>>> hotSearch() async =>
      [for (final x in vList(vMap(await _get('/video/v1/search/hot'))['items'])) vMap(x)];

  Future<Map<String, dynamic>> space(int userId) async => vMap(await _get('/video/v1/users/$userId/space'));

  Future<VPage<VideoCard>> userVideos(int userId, {String order = 'new', int page = 0}) async =>
      _pageOf(await _get('/video/v1/users/$userId/videos', {'order': order, 'page': page}));

  Future<VPage<VPerson>> fans(int userId, {String? cursor}) => _people('/video/v1/users/$userId/fans', cursor);
  Future<VPage<VPerson>> followingOf(int userId, {String? cursor}) =>
      _people('/video/v1/users/$userId/following', cursor);
  Future<VPage<VPerson>> myFollowing({String? cursor}) => _people('/video/v1/me/following', cursor);

  Future<VPage<VPerson>> _people(String path, String? cursor) async {
    final m = vMap(await _get(path, {if (cursor != null) 'cursor': cursor}));
    return VPage([for (final x in vList(m['items'])) VPerson.fromJson(x)], nextCursor: m['next_cursor'] as String?);
  }

  // ---------------- 播放 ----------------

  /// 播放心跳:每 15 秒一次(暂停时不报),退出时再报一次。[playedMs] 是这次打开以来实际播了多久。
  Future<Map<String, dynamic>> view(String vid, {required int partId, required int positionMs,
      required int playedMs, String? deviceId}) async =>
      vMap(await _post('/video/v1/videos/$vid/view', {
        'part_id': partId,
        'position_ms': positionMs,
        'played_ms': playedMs,
        if (deviceId != null) 'device_id': deviceId,
      }));

  // ---------------- 互动 ----------------

  Future<Map<String, dynamic>> like(String vid, bool like) async =>
      vMap(await _post('/video/v1/videos/$vid/like', {'like': like}));

  Future<Map<String, dynamic>> coin(String vid, int amount, {bool alsoLike = false}) async =>
      vMap(await _post('/video/v1/videos/$vid/coin', {'amount': amount, 'like': alsoLike}));

  /// [folderIds] 是这个视频要在的**全部**收藏夹;空 = 取消收藏;null = 收进默认收藏夹
  Future<Map<String, dynamic>> favorite(String vid, {List<int>? folderIds}) async =>
      vMap(await _post('/video/v1/videos/$vid/favorite', folderIds == null ? null : {'folder_ids': folderIds}));

  Future<Map<String, dynamic>> share(String vid, String channel) async =>
      vMap(await _post('/video/v1/videos/$vid/share', {'channel': channel}));

  Future<Map<String, dynamic>> triple(String vid) async => vMap(await _post('/video/v1/videos/$vid/triple'));

  Future<void> notInterested(String vid) => _post('/video/v1/videos/$vid/not-interested');

  Future<Map<String, dynamic>> follow(int userId, bool follow) async =>
      vMap(await _post('/video/v1/users/$userId/follow', {'follow': follow}));

  // ---------------- 我的 ----------------

  Future<Map<String, dynamic>> history({String? cursor}) async =>
      vMap(await _get('/video/v1/me/history', {if (cursor != null) 'cursor': cursor}));
  Future<void> deleteHistory(String vid) => _delete('/video/v1/me/history/$vid');
  Future<void> clearHistory() => _delete('/video/v1/me/history');

  Future<Map<String, dynamic>> watchLater() async => vMap(await _get('/video/v1/me/watch-later'));
  Future<Map<String, dynamic>> addWatchLater(String vid) async => vMap(await _post('/video/v1/me/watch-later', {'vid': vid}));
  Future<void> removeWatchLater(String vid) => _delete('/video/v1/me/watch-later/$vid');

  Future<List<FavFolder>> folders() async =>
      [for (final f in vList(vMap(await _get('/video/v1/me/favorites'))['items'])) FavFolder.fromJson(f)];
  Future<FavFolder> createFolder(String title, {bool public = false}) async =>
      FavFolder.fromJson(await _post('/video/v1/me/favorites', {'title': title, 'public': public}));
  Future<Map<String, dynamic>> folder(int id, {String? cursor}) async =>
      vMap(await _get('/video/v1/me/favorites/$id', {if (cursor != null) 'cursor': cursor}));
  Future<Map<String, dynamic>> publicFolder(int id, {String? cursor}) async =>
      vMap(await _get('/video/v1/favorites/$id', {if (cursor != null) 'cursor': cursor}));
  Future<FavFolder> patchFolder(int id, {String? title, bool? public}) async => FavFolder.fromJson(
      await _patch('/video/v1/me/favorites/$id', {if (title != null) 'title': title, if (public != null) 'public': public}));
  Future<void> deleteFolder(int id) => _delete('/video/v1/me/favorites/$id');
  Future<void> moveFavorites(int from, List<String> vids, {int? to}) =>
      _post('/video/v1/me/favorites/$from/move', {'vids': vids, if (to != null) 'to': to});

  Future<Map<String, dynamic>> coins({String? cursor}) async =>
      vMap(await _get('/video/v1/me/coins', {if (cursor != null) 'cursor': cursor}));
  Future<Map<String, dynamic>> claimDailyCoin() async => vMap(await _post('/video/v1/me/coins/daily'));

  Future<Map<String, dynamic>> settings() async => vMap(await _get('/video/v1/me/settings'));
  Future<Map<String, dynamic>> patchSettings({bool? personalize, bool? historyPaused}) async =>
      vMap(await _patch('/video/v1/me/settings', {
        if (personalize != null) 'personalize': personalize,
        if (historyPaused != null) 'history_paused': historyPaused,
      }));

  // ---------------- 弹幕 ----------------

  Future<Map<String, dynamic>> danmakuSegment(int partId, int segment) async =>
      vMap(await _get('/video/v1/parts/$partId/danmaku', {'segment': segment}));
  Future<Map<String, dynamic>> danmakuDensity(int partId) async =>
      vMap(await _get('/video/v1/parts/$partId/danmaku/density'));
  Future<Danmaku> sendDanmaku(int partId, {required int timeMs, required String text, int mode = 1,
      int color = 0xFFFFFF, int size = 25}) async =>
      Danmaku.fromJson(await _post('/video/v1/parts/$partId/danmaku',
          {'time_ms': timeMs, 'text': text, 'mode': mode, 'color': color, 'size': size}));
  Future<void> deleteDanmaku(int id) => _delete('/video/v1/danmaku/$id');

  // ---------------- 评论 ----------------

  Future<VPage<VComment>> comments(String vid, {String sort = 'hot', String? cursor}) async {
    final m = vMap(await _get('/video/v1/videos/$vid/comments', {'sort': sort, if (cursor != null) 'cursor': cursor}));
    return VPage([for (final x in vList(m['items'])) VComment.fromJson(x)],
        nextCursor: m['next_cursor'] as String?, extra: m);
  }

  Future<Map<String, dynamic>> replies(int commentId, {String? cursor}) async =>
      vMap(await _get('/video/v1/comments/$commentId/replies', {if (cursor != null) 'cursor': cursor}));

  Future<VComment> comment(String vid, String text, {int? parentId}) async =>
      VComment.fromJson(await _post('/video/v1/videos/$vid/comments', {'text': text, 'parent_id': parentId}));

  Future<Map<String, dynamic>> voteComment(int id, int vote) async =>
      vMap(await _post('/video/v1/comments/$id/vote', {'vote': vote}));
  Future<void> pinComment(int id, bool pinned) => _post('/video/v1/comments/$id/pin', {'pinned': pinned});
  Future<void> deleteComment(int id) => _delete('/video/v1/comments/$id');

  /// 举报视频 / 评论 / 弹幕(原因代码见 VIDEO-API 0.8)
  Future<Map<String, dynamic>> report({required String targetType, int? targetId, String? vid,
      required String reasonCode, String note = ''}) async =>
      vMap(await _post('/video/v1/reports', {
        'target_type': targetType,
        if (targetId != null) 'target_id': targetId,
        if (vid != null) 'vid': vid,
        'reason_code': reasonCode,
        'note': note,
      }));

  // ---------------- 投稿与创作中心 ----------------

  /// 传原片:≤ 8MB 一次传完,更大的分片(4MB 一片,可续传),[onProgress] 0–1。返回媒体对象。
  /// [read] 读文件的一段 `[start, end)`(XFile 用 `openRead(start, end)` 拼起来)。
  Future<Map<String, dynamic>> uploadSource(Future<Uint8List> Function(int start, int end) read, int size,
      String name, {String kind = 'video_source', void Function(double p)? onProgress}) async {
    if (size <= 8 * 1024 * 1024) {
      final m = await api.uploadMediaBytes(await read(0, size), name, kind: kind, purpose: 'video',
          timeout: const Duration(minutes: 10));
      onProgress?.call(1);
      return m;
    }
    final up = vMap(await _post('/media/v1/uploads', {'size': size, 'name': name, 'kind': kind, 'purpose': 'video'}));
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

  Future<Map<String, dynamic>> uploadCover(List<int> bytes, String name) =>
      api.uploadMediaBytes(bytes, name, kind: 'cover', purpose: 'video');

  Future<Map<String, dynamic>> createVideo(Map<String, dynamic> body) async =>
      vMap(await _post('/video/v1/uploads/videos', body));
  Future<Map<String, dynamic>> patchVideo(String vid, Map<String, dynamic> body) async =>
      vMap(await _patch('/video/v1/videos/$vid', body));
  Future<Map<String, dynamic>> addPart(String vid, int mediaId, String title) async =>
      vMap(await _post('/video/v1/videos/$vid/parts', {'media_id': mediaId, 'title': title}));
  Future<Map<String, dynamic>> deletePart(String vid, int partId) async =>
      vMap(await _delete('/video/v1/videos/$vid/parts/$partId'));
  Future<Map<String, dynamic>> submit(String vid) async => vMap(await _post('/video/v1/videos/$vid/submit'));
  Future<Map<String, dynamic>> discardChanges(String vid) async => vMap(await _delete('/video/v1/videos/$vid/changes'));
  Future<Map<String, dynamic>> appeal(String vid, String text) async =>
      vMap(await _post('/video/v1/videos/$vid/appeal', {'text': text}));
  Future<void> deleteVideo(String vid) => _delete('/video/v1/videos/$vid');

  Future<Map<String, dynamic>> creatorVideos({String status = 'all', String? cursor}) async =>
      vMap(await _get('/video/v1/creator/videos', {'status': status, if (cursor != null) 'cursor': cursor}));
  Future<Map<String, dynamic>> creatorVideo(String vid) async => vMap(await _get('/video/v1/creator/videos/$vid'));
  Future<Map<String, dynamic>> creatorStats(String vid, {int days = 30}) async =>
      vMap(await _get('/video/v1/creator/videos/$vid/stats', {'days': days}));
  Future<Map<String, dynamic>> creatorOverview() async => vMap(await _get('/video/v1/creator/overview'));

  // ---------------- 互动消息 ----------------

  Future<Map<String, dynamic>> notifications(String kind, {String? cursor}) async =>
      vMap(await _get('/social/v1/notifications', {'kind': kind, if (cursor != null) 'cursor': cursor}));
  Future<Map<String, dynamic>> notificationsUnread() async => vMap(await _get('/social/v1/notifications/unread'));
  Future<Map<String, dynamic>> markNotificationsRead({String? kind, List<int>? ids}) async =>
      vMap(await _post('/social/v1/notifications/read', {if (kind != null) 'kind': kind, if (ids != null) 'ids': ids}));
}
