import 'dart:math';

import 'package:superz_shared/superz_shared.dart';

import 'models.dart';

/// 消息模块的接口(`/social/v1`、`/chat/v1`、`/media/v1`,DEV-PROMPTS-40 §8)。
class ChatApi {
  ChatApi(this.api);

  final ApiClient api;

  static final _rng = Random.secure();

  /// 63 位随机数,发送去重用(§5.4)。字符串传,JS 的 Number 装不下 63 位
  static String randomId() {
    final hi = _rng.nextInt(1 << 30);
    final lo = _rng.nextInt(0xFFFFFFFF); // 网页上 `1 << 32` 按 32 位算,别用移位写
    return (BigInt.from(hi) << 32 | BigInt.from(lo)).toString();
  }

  Future<dynamic> _get(String path, [Map<String, dynamic>? q]) =>
      api.requestJson('GET', path, query: q);
  Future<dynamic> _post(String path, [Object? body]) =>
      api.requestJson('POST', path, body: body ?? const {});
  Future<dynamic> _patch(String path, Object body) => api.requestJson('PATCH', path, body: body);
  Future<dynamic> _put(String path, Object body) => api.requestJson('PUT', path, body: body);
  Future<dynamic> _delete(String path, [Map<String, dynamic>? q]) =>
      api.requestJson('DELETE', path, query: q);

  // ---------------- 社交身份 ----------------

  Future<Map<String, dynamic>> me() async => (await _get('/social/v1/me') as Map).cast();

  Future<Map<String, dynamic>> patchMe(Map<String, dynamic> body) async =>
      (await _patch('/social/v1/me', body) as Map).cast();

  Future<Map<String, dynamic>> setUsername(String name) async =>
      (await _put('/social/v1/me/username', {'username': name}) as Map).cast();

  Future<({bool ok, String reason})> checkUsername(String name) async {
    final r = (await _get('/social/v1/username-check', {'u': name}) as Map);
    return (ok: r['ok'] == true, reason: '${r['reason'] ?? ''}');
  }

  Future<ChatUser> user(int id) async => ChatUser.fromJson(await _get('/social/v1/users/$id'));

  Future<Map<String, dynamic>> resolve(String username) async =>
      (await _get('/social/v1/resolve/${Uri.encodeComponent(username)}') as Map).cast();

  Future<ChatUser> resolvePublicId(String publicId) async => ChatUser.fromJson(
      (await _get('/social/v1/resolve-id/${Uri.encodeComponent(publicId)}') as Map)['user']);

  Future<ChatUser> findByPhone(String phone) async =>
      ChatUser.fromJson(await _post('/social/v1/find-by-phone', {'phone': phone}));

  Future<List<ChatUser>> contacts() async => [
        for (final u in ((await _get('/social/v1/contacts')) as Map)['items'] as List)
          ChatUser.fromJson(u)
      ];

  Future<ChatUser> addContact(int userId, {String alias = ''}) async =>
      ChatUser.fromJson(await _post('/social/v1/contacts', {'user_id': userId, 'alias': alias}));

  Future<void> removeContact(int userId) => _delete('/social/v1/contacts/$userId');

  Future<List<ChatUser>> blocks() async => [
        for (final u in ((await _get('/social/v1/blocks')) as Map)['items'] as List)
          ChatUser.fromJson(u)
      ];

  Future<void> block(int userId) => _post('/social/v1/blocks', {'user_id': userId});
  Future<void> unblock(int userId) => _delete('/social/v1/blocks/$userId');

  // ---------------- 会话 ----------------

  Future<({List<ChatInfo> items, int userPts})> dialogs() async {
    final r = (await _get('/chat/v1/dialogs')) as Map;
    return (
      items: [for (final c in r['items'] as List) ChatInfo.fromJson(c)],
      userPts: (r['user_pts'] as num?)?.toInt() ?? 0,
    );
  }

  Future<ChatInfo> chat(int id) async => ChatInfo.fromJson(await _get('/chat/v1/chats/$id'));

  Future<ChatInfo> openPrivate(int userId) async =>
      ChatInfo.fromJson(await _post('/chat/v1/chats/private', {'user_id': userId}));

  Future<ChatInfo> openSaved() async => ChatInfo.fromJson(await _post('/chat/v1/chats/saved'));

  Future<(ChatInfo, List<int>)> createChat(String type, String title,
      {String about = '', List<int> memberIds = const []}) async {
    final r = (await _post('/chat/v1/chats',
        {'type': type, 'title': title, 'about': about, 'member_ids': memberIds})) as Map;
    return (
      ChatInfo.fromJson(r),
      [for (final x in (r['skipped_user_ids'] as List? ?? const [])) (x as num).toInt()]
    );
  }

  Future<ChatInfo> patchChat(int id, Map<String, dynamic> body) async =>
      ChatInfo.fromJson(await _patch('/chat/v1/chats/$id', body));

  Future<void> deleteChat(int id) => _delete('/chat/v1/chats/$id');
  Future<void> leaveChat(int id) => _post('/chat/v1/chats/$id/leave');
  Future<Map<String, dynamic>> joinPublic(int id) async =>
      (await _post('/chat/v1/chats/$id/join') as Map).cast();

  Future<ChatInfo> patchDialog(int id, Map<String, dynamic> body) async =>
      ChatInfo.fromJson(await _patch('/chat/v1/dialogs/$id', body));

  Future<void> clearHistory(int id, {bool revoke = false}) =>
      _post('/chat/v1/dialogs/$id/clear', {'revoke': revoke});

  Future<void> deleteDialog(int id, {bool revoke = false}) =>
      _delete('/chat/v1/dialogs/$id', {'revoke': '$revoke'});

  Future<void> read(int id, int seq) => _post('/chat/v1/dialogs/$id/read', {'seq': seq});

  // ---------------- 消息 ----------------

  Future<({List<ChatMessage> messages, bool hasOlder, bool hasNewer})> messages(int chatId,
      {int? before, int? after, int? around, int limit = 50}) async {
    final r = (await _get('/chat/v1/chats/$chatId/messages', {
      'limit': '$limit',
      if (before != null) 'before': '$before',
      if (after != null) 'after': '$after',
      if (around != null) 'around': '$around',
    })) as Map;
    return (
      messages: [for (final m in r['messages'] as List) ChatMessage.fromJson(m)],
      hasOlder: r['has_older'] == true,
      hasNewer: r['has_newer'] == true,
    );
  }

  Future<ChatMessage> send(int chatId, Map<String, dynamic> body) async =>
      ChatMessage.fromJson(await _post('/chat/v1/chats/$chatId/messages', body));

  Future<ChatMessage> edit(int chatId, int seq, String text, List<MsgEntity> entities) async =>
      ChatMessage.fromJson(await _patch('/chat/v1/chats/$chatId/messages/$seq',
          {'text': text, 'entities': [for (final e in entities) e.toJson()]}));

  Future<List<int>> deleteMessages(int chatId, List<int> seqs, {required bool revoke}) async {
    final r = (await _post('/chat/v1/chats/$chatId/messages/delete',
        {'seqs': seqs, 'revoke': revoke})) as Map;
    return [for (final x in r['seqs'] as List) (x as num).toInt()];
  }

  Future<void> forward(int fromChat, List<int> seqs, List<int> toChats,
          {bool hideSender = false}) =>
      _post('/chat/v1/chats/$fromChat/messages/forward',
          {'seqs': seqs, 'to_chat_ids': toChats, 'hide_sender': hideSender});

  Future<ChatMessage> react(int chatId, int seq, String emoji, {required bool add}) async =>
      ChatMessage.fromJson(await _post(
          '/chat/v1/chats/$chatId/messages/$seq/reactions', {'emoji': emoji, 'add': add}));

  Future<List<Map<String, dynamic>>> reactors(int chatId, int seq) async => [
        for (final x in ((await _get('/chat/v1/chats/$chatId/messages/$seq/reactions')) as Map)
            ['items'] as List)
          (x as Map).cast<String, dynamic>()
      ];

  Future<List<Map<String, dynamic>>> readers(int chatId, int seq) async => [
        for (final x in ((await _get('/chat/v1/chats/$chatId/messages/$seq/readers')) as Map)
            ['items'] as List)
          (x as Map).cast<String, dynamic>()
      ];

  Future<void> pin(int chatId, int? seq, {required bool pinned, bool notify = true}) =>
      _post('/chat/v1/chats/$chatId/pins', {'seq': seq, 'pinned': pinned, 'notify': notify});

  Future<List<ChatMessage>> pins(int chatId) async => [
        for (final m in ((await _get('/chat/v1/chats/$chatId/pins')) as Map)['items'] as List)
          ChatMessage.fromJson(m)
      ];

  Future<ChatMessage> vote(int chatId, int seq, List<int> options) async =>
      ChatMessage.fromJson(
          await _post('/chat/v1/chats/$chatId/polls/$seq/vote', {'options': options}));

  Future<ChatMessage> closePoll(int chatId, int seq) async =>
      ChatMessage.fromJson(await _post('/chat/v1/chats/$chatId/polls/$seq/close'));

  /// 报「我看过这些帖子」,返回这些帖子现在的浏览量(seq → 次数)。
  Future<Map<int, int>> views(int chatId, List<int> seqs) async {
    final r = await _post('/chat/v1/chats/$chatId/views', {'seqs': seqs}) as Map;
    return {
      for (final e in ((r['views'] as Map?) ?? const {}).entries)
        int.parse('${e.key}'): (e.value as num).toInt(),
    };
  }

  // ---------------- 成员与邀请 ----------------

  Future<List<Map<String, dynamic>>> members(int chatId, {String q = '', String role = ''}) async =>
      [
        for (final x in ((await _get('/chat/v1/chats/$chatId/members',
                {if (q.isNotEmpty) 'q': q, if (role.isNotEmpty) 'role': role, 'limit': '200'}))
                as Map)['items'] as List)
          (x as Map).cast<String, dynamic>()
      ];

  Future<Map<String, dynamic>> addMembers(int chatId, List<int> ids) async =>
      (await _post('/chat/v1/chats/$chatId/members', {'user_ids': ids}) as Map).cast();

  Future<Map<String, dynamic>> memberAction(int chatId, int userId, String action,
          {Map<String, bool>? rights, String? title, Map<String, bool>? perms, DateTime? until}) async =>
      (await _patch('/chat/v1/chats/$chatId/members/$userId', {
        'action': action,
        if (rights != null) 'rights': rights,
        if (title != null) 'title': title,
        if (perms != null) 'perms': perms,
        if (until != null) 'until': until.toUtc().toIso8601String(),
      }) as Map)
          .cast();

  Future<void> transfer(int chatId, int userId) =>
      _post('/chat/v1/chats/$chatId/transfer', {'user_id': userId});

  Future<List<Map<String, dynamic>>> invites(int chatId) async => [
        for (final x in ((await _get('/chat/v1/chats/$chatId/invites')) as Map)['items'] as List)
          (x as Map).cast<String, dynamic>()
      ];

  Future<Map<String, dynamic>> createInvite(int chatId,
          {String title = '', DateTime? expireAt, int? usageLimit, bool approval = false}) async =>
      (await _post('/chat/v1/chats/$chatId/invites', {
        'title': title,
        if (expireAt != null) 'expire_at': expireAt.toUtc().toIso8601String(),
        if (usageLimit != null) 'usage_limit': usageLimit,
        'requires_approval': approval,
      }) as Map)
          .cast();

  Future<void> revokeInvite(int chatId, String code) =>
      _delete('/chat/v1/chats/$chatId/invites/$code');

  Future<Map<String, dynamic>> invitePreview(String code) async =>
      (await _get('/chat/v1/join/$code') as Map).cast();

  Future<Map<String, dynamic>> join(String code) async =>
      (await _post('/chat/v1/join/$code', {'about': ''}) as Map).cast();

  Future<List<Map<String, dynamic>>> joinRequests(int chatId) async => [
        for (final x in ((await _get('/chat/v1/chats/$chatId/join-requests')) as Map)['items']
            as List)
          (x as Map).cast<String, dynamic>()
      ];

  Future<void> decideJoin(int chatId, int userId, bool approve) =>
      _post('/chat/v1/chats/$chatId/join-requests/$userId', {'approve': approve});

  // ---------------- 同步、搜索、其他 ----------------

  Future<Map<String, dynamic>> sync(int userPts, Map<int, int> chats) async =>
      (await _post('/chat/v1/sync', {
        'user_pts': userPts,
        'chats': {for (final e in chats.entries) '${e.key}': e.value},
      }) as Map)
          .cast();

  Future<Map<String, dynamic>> search(String q) async =>
      (await _get('/chat/v1/search', {'q': q}) as Map).cast();

  Future<({List<ChatMessage> items, bool hasMore})> searchIn(int chatId,
      {String q = '', String kind = '', int? before}) async {
    final r = (await _get('/chat/v1/chats/$chatId/search', {
      if (q.isNotEmpty) 'q': q,
      if (kind.isNotEmpty) 'kind': kind,
      if (before != null) 'before': '$before',
    })) as Map;
    return (
      items: [for (final m in r['items'] as List) ChatMessage.fromJson(m)],
      hasMore: r['has_more'] == true
    );
  }

  Future<Map<String, dynamic>> linkPreview(String url) async =>
      (await _get('/chat/v1/link-preview', {'url': url}) as Map).cast();

  Future<List<ChatFolder>> folders() async => [
        for (final f in ((await _get('/chat/v1/folders')) as Map)['items'] as List)
          ChatFolder.fromJson(f)
      ];

  Future<List<ChatFolder>> saveFolders(List<ChatFolder> items) async => [
        for (final f in ((await _put('/chat/v1/folders',
                {'items': [for (final f in items) f.toJson()]})) as Map)['items'] as List)
          ChatFolder.fromJson(f)
      ];

  Future<List<Map<String, dynamic>>> scheduled(int chatId) async => [
        for (final x in ((await _get('/chat/v1/chats/$chatId/scheduled')) as Map)['items'] as List)
          (x as Map).cast<String, dynamic>()
      ];

  Future<void> schedule(int chatId, Map<String, dynamic> body, DateTime at) => _post(
      '/chat/v1/chats/$chatId/scheduled', {...body, 'send_at': at.toUtc().toIso8601String()});

  Future<void> unschedule(int chatId, int id) => _delete('/chat/v1/chats/$chatId/scheduled/$id');

  Future<void> sendScheduledNow(int chatId, int id) =>
      _post('/chat/v1/chats/$chatId/scheduled/$id/send-now');

  Future<void> report(Map<String, dynamic> body) => _post('/chat/v1/reports', body);

  // ---------------- 处罚与申诉(S6) ----------------

  /// `{"active": [SanctionOut…], "history": [SanctionOut…]}`(形状见 docs/COMMUNITY-GOVERNANCE.md §4.1)
  Future<Map<String, dynamic>> mySanctions() async => (await _get('/social/v1/me/sanctions') as Map).cast();

  Future<Map<String, dynamic>> appealSanction(int id, String text) async =>
      (await _post('/social/v1/sanctions/$id/appeal', {'text': text}) as Map).cast();

  // ---------------- 导出我的数据(S5) ----------------

  /// `{"state": none|running|failed|ready, "progress"?, "error"?, "url"?, "size"?, "summary"?, "last"?}`
  Future<Map<String, dynamic>> exportStatus() async => (await _get('/chat/v1/export') as Map).cast();

  Future<Map<String, dynamic>> startExport() async => (await _post('/chat/v1/export') as Map).cast();

  // ---------------- 机器人(#355) ----------------

  /// 会话里的机器人:命令、菜单按钮、简介。没有机器人就是空列表
  Future<List<BotInfo>> botInfo(int chatId) async {
    final r = (await _get('/chat/v1/chats/$chatId/bot-info') as Map).cast<String, dynamic>();
    return [for (final b in (r['bots'] as List? ?? const [])) BotInfo.fromJson(b)];
  }

  /// 点内联键盘的回调按钮。服务端最多等机器人 10 秒:
  /// `{"answered":true,"text":…,"show_alert":…,"url":…}`,没等到是 `{"answered":false}`
  Future<Map<String, dynamic>> botCallback(int chatId, int seq, String data) async =>
      (await _post('/chat/v1/chats/$chatId/messages/$seq/callback', {'data': data}) as Map).cast();

  Future<Map<String, Map<String, dynamic>>> signMedia(List<int> ids) async {
    final r = (await _post('/media/v1/sign', {'ids': ids})) as Map;
    return {
      for (final e in (r['items'] as Map).entries)
        '${e.key}': (e.value as Map).cast<String, dynamic>()
    };
  }

  Future<Map<String, dynamic>> media(int id) async =>
      (await _get('/media/v1/media/$id') as Map).cast();

  Future<Map<String, dynamic>> createUpload(int size, String name, String kind,
          {String purpose = 'chat'}) async =>
      (await _post('/media/v1/uploads',
              {'size': size, 'name': name, 'kind': kind, 'purpose': purpose}) as Map)
          .cast();

  Future<Map<String, dynamic>> completeUpload(String id, String kind) async =>
      (await _post('/media/v1/uploads/$id/complete', {'kind': kind}) as Map).cast();

  // ---------------- 通话 ----------------

  /// WebRTC 的 STUN / TURN(TURN 用户名密码是临时的,每次打电话前取)。
  Future<List<Map<String, dynamic>>> iceServers() async {
    final r = await _get('/chat/v1/calls/ice-servers') as Map;
    return [for (final x in (r['ice_servers'] as List? ?? const [])) (x as Map).cast<String, dynamic>()];
  }

  Future<List<Map<String, dynamic>>> callHistory({int? beforeId}) async {
    final r = await _get('/chat/v1/calls', {if (beforeId != null) 'before_id': '$beforeId'}) as Map;
    return [for (final x in (r['items'] as List? ?? const [])) (x as Map).cast<String, dynamic>()];
  }

  // ---------------- 贴纸 ----------------

  /// 贴纸面板用:官方包 + 我添加的包(带全部贴纸),另附我自己建的包(不带贴纸)。
  Future<({List<StickerSetInfo> installed, List<StickerSetInfo> created})> stickerSets() async {
    final r = await _get('/chat/v1/stickers/sets') as Map;
    return (
      installed: [for (final x in (r['installed'] as List? ?? const [])) StickerSetInfo.fromJson(x)],
      created: [for (final x in (r['created'] as List? ?? const [])) StickerSetInfo.fromJson(x)],
    );
  }

  Future<StickerSetInfo> stickerSet(int id) async =>
      StickerSetInfo.fromJson(await _get('/chat/v1/stickers/sets/$id'));

  Future<StickerSetInfo> createStickerSet(String title) async =>
      StickerSetInfo.fromJson(await _post('/chat/v1/stickers/sets', {'title': title}));

  Future<StickerSetInfo> renameStickerSet(int id, String title) async =>
      StickerSetInfo.fromJson(await _patch('/chat/v1/stickers/sets/$id', {'title': title}));

  Future<void> deleteStickerSet(int id) => _delete('/chat/v1/stickers/sets/$id');

  Future<StickerItem> addSticker(int setId, int mediaId, String emoji) async => StickerItem.fromJson(
      await _post('/chat/v1/stickers/sets/$setId/stickers', {'media_id': mediaId, 'emoji': emoji}));

  Future<void> removeSticker(int setId, int stickerId) =>
      _delete('/chat/v1/stickers/sets/$setId/stickers/$stickerId');

  Future<void> installStickerSet(int id) => _post('/chat/v1/stickers/sets/$id/install');

  Future<void> uninstallStickerSet(int id) => _delete('/chat/v1/stickers/sets/$id/install');
}
