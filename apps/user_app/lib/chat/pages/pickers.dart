import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../chat_page.dart';
import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';
import 'user_profile_page.dart';

// 聊天页里用到的各种小弹窗、选择器。

void _toast(BuildContext context, String s) {
  if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
}

/// 选一个位置发出去(复用收货地址那套地图选点:搜索、周边、拖图)。
Future<({double lat, double lng, String title, String address})?> pickLocation(
    BuildContext context, ApiClient api) async {
  final picked = await Navigator.of(context).push<PickedPlace>(MaterialPageRoute(
    builder: (_) => MapPickerPage(
      onReverse: (lat, lng) async {
        final t = await api.geoReverse(lat, lng);
        return (name: t.name, district: t.district);
      },
      // 周边地点列表:认地名比认坐标容易。搜索要绑城市,发位置时不知道对方在哪个城市,先不开
      onAround: api.geoAround,
    ),
  ));
  if (picked == null) return null;
  return (lat: picked.lat, lng: picked.lng, title: picked.name, address: picked.district);
}

/// 选一个联系人(发名片、拉人进群用)。
Future<ChatUser?> pickContact(BuildContext context, {String title = '选择联系人'}) async {
  final store = ChatStore.instance;
  final list = await store.api.contacts().catchError((_) => <ChatUser>[]);
  if (!context.mounted) return null;
  if (list.isEmpty) {
    _toast(context, '还没有联系人。先在「消息」右上角「添加联系人」');
    return null;
  }
  return szShowSheet<ChatUser>(
    context: context,
    builder: (ctx) => SafeArea(
      child: SzSheetScrollable(
        builder: (ctx, controller) => ListView(controller: controller, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 8),
            child: Text(title, style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
          ),
          for (final u in list)
            ListTile(
              leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 40),
              title: Text(u.displayName),
              subtitle: u.username == null ? null : Text('@${u.username}'),
              onTap: () => Navigator.pop(ctx, u),
            ),
        ]),
      ),
    ),
  );
}

/// 建一个投票 / 测验。返回服务端要的 poll 字段。
Future<Map<String, dynamic>?> createPoll(BuildContext context, {bool allowPublic = true}) {
  return Navigator.of(context).push<Map<String, dynamic>>(
      MaterialPageRoute(builder: (_) => _PollComposerPage(allowPublic: allowPublic)));
}

class _PollComposerPage extends StatefulWidget {
  const _PollComposerPage({required this.allowPublic});

  final bool allowPublic;

  @override
  State<_PollComposerPage> createState() => _PollComposerPageState();
}

class _PollComposerPageState extends State<_PollComposerPage> {
  final _q = TextEditingController();
  final List<TextEditingController> _opts = [TextEditingController(), TextEditingController()];
  final _explain = TextEditingController();
  bool _anonymous = true;
  bool _multiple = false;
  bool _quiz = false;
  int? _correct;

  @override
  void dispose() {
    _q.dispose();
    for (final c in _opts) {
      c.dispose();
    }
    _explain.dispose();
    super.dispose();
  }

  String? _problem() {
    final q = _q.text.trim();
    final opts = [for (final c in _opts) c.text.trim()].where((s) => s.isNotEmpty).toList();
    if (q.isEmpty) return '写一个问题';
    if (opts.length < 2) return '至少两个选项';
    if (opts.toSet().length != opts.length) return '选项不能重复';
    if (_quiz && _correct == null) return '测验要选出正确答案';
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final problem = _problem();
    return SzPageScaffold(
      appBar: AppBar(
        title: Text(_quiz ? '新建测验' : '新建投票'),
        actions: [
          TextButton(
            onPressed: problem != null
                ? null
                : () {
                    final opts = [for (final c in _opts) c.text.trim()].where((s) => s.isNotEmpty).toList();
                    Navigator.pop(context, {
                      'question': _q.text.trim(),
                      'options': opts,
                      'anonymous': _anonymous || !widget.allowPublic,
                      'multiple': _multiple && !_quiz,
                      'quiz': _quiz,
                      if (_quiz) 'correct': _correct,
                      if (_quiz && _explain.text.trim().isNotEmpty) 'explanation': _explain.text.trim(),
                    });
                  },
            child: const Text('发送'),
          ),
        ],
      ),
      body: RadioGroup<int>(
        groupValue: _correct,
        onChanged: (v) => setState(() => _correct = v),
        child: ListView(padding: const EdgeInsets.all(kPagePad), children: [
        TextField(
          controller: _q,
          maxLength: 255,
          decoration: const InputDecoration(labelText: '问题'),
          onChanged: (_) => setState(() {}),
        ),
        const SizedBox(height: 8),
        Text('选项', style: TextStyle(color: sz.inkMuted)),
        for (var i = 0; i < _opts.length; i++)
          Row(children: [
            if (_quiz) Radio<int>(value: i),
            Expanded(
              child: TextField(
                controller: _opts[i],
                maxLength: 100,
                decoration: InputDecoration(hintText: '选项 ${i + 1}', counterText: ''),
                onChanged: (_) => setState(() {}),
              ),
            ),
            if (_opts.length > 2)
              IconButton(
                icon: const Icon(Icons.remove_circle_outline),
                onPressed: () => setState(() {
                  _opts.removeAt(i).dispose();
                  if (_correct == i) _correct = null;
                }),
              ),
          ]),
        if (_opts.length < 10)
          TextButton.icon(
            onPressed: () => setState(() => _opts.add(TextEditingController())),
            icon: const Icon(Icons.add),
            label: const Text('加一个选项'),
          ),
        const Divider(),
        if (widget.allowPublic)
          SwitchListTile(
            value: _anonymous,
            onChanged: (v) => setState(() => _anonymous = v),
            title: const Text('匿名投票'),
            subtitle: const Text('关掉后,大家能看到每个人投了什么'),
          ),
        SwitchListTile(
          value: _multiple && !_quiz,
          onChanged: _quiz ? null : (v) => setState(() => _multiple = v),
          title: const Text('可以多选'),
        ),
        SwitchListTile(
          value: _quiz,
          onChanged: (v) => setState(() {
            _quiz = v;
            if (v) _multiple = false;
          }),
          title: const Text('测验模式'),
          subtitle: const Text('只有一个正确答案,投完才揭晓'),
        ),
        if (_quiz)
          TextField(
            controller: _explain,
            maxLength: 200,
            decoration: const InputDecoration(labelText: '解析(可选)', hintText: '答错的人会看到这段说明'),
          ),
        if (problem != null)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(problem, style: TextStyle(color: sz.inkMuted, fontSize: kFontNote)),
          ),
      ]),
      ),
    );
  }
}

/// 选定时发送的时间(至少 1 分钟后,最多 365 天)。
Future<DateTime?> pickScheduleTime(BuildContext context) async {
  final now = DateTime.now();
  final day = await showDatePicker(
    context: context,
    firstDate: DateTime(now.year, now.month, now.day),
    lastDate: now.add(const Duration(days: 365)),
    initialDate: now,
    helpText: '哪天发',
  );
  if (day == null || !context.mounted) return null;
  final t = await showTimePicker(
    context: context,
    initialTime: TimeOfDay.fromDateTime(now.add(const Duration(minutes: 10))),
    helpText: '几点发',
  );
  if (t == null) return null;
  final at = DateTime(day.year, day.month, day.day, t.hour, t.minute);
  if (at.isBefore(now.add(const Duration(seconds: 50)))) {
    if (context.mounted) _toast(context, '要选一个以后的时间');
    return null;
  }
  return at;
}

/// 免打扰多久。
Future<DateTime?> pickMuteUntil(BuildContext context) async {
  final pick = await szShowSheet<Duration>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        for (final (label, d) in const [
          ('1 小时', Duration(hours: 1)),
          ('8 小时', Duration(hours: 8)),
          ('2 天', Duration(days: 2)),
          ('永久', Duration(days: 3650)),
        ])
          ListTile(title: Text(label), onTap: () => Navigator.pop(ctx, d)),
      ]),
    ),
  );
  return pick == null ? null : DateTime.now().add(pick);
}

/// 清空聊天记录:私聊可以选同时为对方清空。返回 revoke;取消返回 null。
Future<bool?> confirmClear(BuildContext context, ChatInfo c) {
  var revoke = false;
  return showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) => SzDialog(
        title: const Text('清空聊天记录?'),
        content: c.isPrivate
            ? CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: revoke,
                onChanged: (v) => set(() => revoke = v ?? false),
                title: Text('同时为 ${c.title} 清空'),
              )
            : const Text('只清你这边,别人看到的不受影响'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, revoke), child: const Text('清空')),
        ],
      ),
    ),
  );
}

/// 删除私聊 / 退群 / 解散。做了返回 true。
Future<bool> leaveOrDelete(BuildContext context, ChatInfo c) async {
  final store = ChatStore.instance;
  final owner = c.my.role == 'owner' && !c.isPrivate && !c.isSaved;
  var revoke = false;
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) => SzDialog(
        title: Text(c.isPrivate || c.isSaved
            ? '删除这个聊天?'
            : (owner ? '解散「${c.title}」?' : '退出「${c.title}」?')),
        content: c.isPrivate
            ? CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: revoke,
                onChanged: (v) => set(() => revoke = v ?? false),
                title: Text('同时为 ${c.title} 删除'),
              )
            : (owner ? Text(c.isChannel ? '频道和全部帖子会被删除,订阅者都会失去它' : '所有成员都会被移出,聊天记录一起删除') : null),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Theme.of(ctx).sz.danger),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(owner ? '解散' : (c.isPrivate || c.isSaved ? '删除' : '退出')),
          ),
        ],
      ),
    ),
  );
  if (ok != true) return false;
  try {
    if (c.isPrivate || c.isSaved) {
      await store.api.deleteDialog(c.id, revoke: revoke);
    } else if (owner) {
      await store.api.deleteChat(c.id);
    } else {
      await store.api.leaveChat(c.id);
    }
    store.chats.remove(c.id);
    store.timelines.remove(c.id);
    store.notifyListeners();
    return true;
  } on ApiException catch (e) {
    if (context.mounted) _toast(context, e.message);
    return false;
  }
}

const reportReasons = <(String, String)>[
  ('C101', '骚扰、辱骂'),
  ('C102', '垃圾广告、引流'),
  ('C103', '诈骗'),
  ('C104', '色情、低俗'),
  ('C105', '暴力、血腥'),
  ('C106', '违法违规'),
  ('C107', '侵犯隐私'),
  ('C108', '冒充他人或官方'),
  ('C109', '未成年人不宜'),
  ('X999', '其他'),
];

Future<void> _report(BuildContext context, Map<String, dynamic> body) async {
  final code = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: SzSheetScrollable(
        builder: (ctx, controller) => ListView(controller: controller, children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
            child: Text('举报原因', style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
          ),
          const Padding(
            padding: EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 8),
            child: Text('平台审核员会看被举报的这几条消息;对方不会知道是谁举报的。', style: TextStyle(fontSize: kFontNote)),
          ),
          for (final (c, label) in reportReasons)
            ListTile(title: Text(label), onTap: () => Navigator.pop(ctx, c)),
        ]),
      ),
    ),
  );
  if (code == null || !context.mounted) return;
  var note = '';
  if (code == 'X999') {
    final c = TextEditingController();
    final r = await showDialog<String>(
      context: context,
      builder: (ctx) => SzDisposeWith(
        controllers: [c],
        child: SzDialog(
          title: const Text('写明原因'),
          content: TextField(controller: c, maxLength: 500, maxLines: 3, autofocus: true),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
            FilledButton(onPressed: () => Navigator.pop(ctx, c.text), child: const Text('提交')),
          ],
        ),
      ),
    );
    if (r == null) return;
    note = r;
  }
  try {
    await ChatStore.instance.api.report({...body, 'reason_code': code, 'note': note});
    if (context.mounted) _toast(context, '收到了,平台会尽快处理');
  } on ApiException catch (e) {
    if (context.mounted) _toast(context, e.message);
  }
}

Future<void> reportMessages(BuildContext context, {required int chatId, required List<int> seqs}) =>
    _report(context, {'target_type': 'message', 'chat_id': chatId, 'seqs': seqs});

Future<void> reportChat(BuildContext context, ChatInfo c) => c.isPrivate && c.peer != null
    ? _report(context, {'target_type': 'user', 'user_id': c.peer!.id, 'chat_id': c.id})
    : _report(context, {'target_type': 'chat', 'chat_id': c.id});

Future<void> reportUser(BuildContext context, int userId) =>
    _report(context, {'target_type': 'user', 'user_id': userId});

Future<void> _peopleSheet(BuildContext context, String title, Future<List<(ChatUser, String)>> loader) async {
  List<(ChatUser, String)> rows;
  try {
    rows = await loader;
  } on ApiException catch (e) {
    if (context.mounted) _toast(context, e.message);
    return;
  }
  if (!context.mounted) return;
  await szShowSheet<void>(
    context: context,
    builder: (ctx) => SafeArea(
      child: SzSheetScrollable(
        builder: (ctx, controller) => ListView(controller: controller, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 8),
            child: Text(title, style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
          ),
          if (rows.isEmpty)
            const Padding(padding: EdgeInsets.all(kPagePad), child: Text('还没有人')),
          for (final (u, trailing) in rows)
            ListTile(
              leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 40),
              title: Text(u.displayName),
              trailing: Text(trailing, style: const TextStyle(fontSize: kFontBodyLg)),
              onTap: () {
                Navigator.pop(ctx);
                openUserProfile(context, u.id);
              },
            ),
        ]),
      ),
    ),
  );
}

Future<void> showReaders(BuildContext context, int chatId, int seq) => _peopleSheet(
      context,
      '已读',
      ChatStore.instance.api.readers(chatId, seq).then((rows) => [
            for (final r in rows)
              (ChatUser.fromJson(r['user']), _shortTime(DateTime.tryParse('${r['read_at'] ?? ''}')?.toLocal()))
          ]),
    );

String _shortTime(DateTime? t) {
  if (t == null) return '';
  final n = DateTime.now();
  final hm = '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  if (t.year == n.year && t.month == n.month && t.day == n.day) return hm;
  return '${t.month}/${t.day} $hm';
}

Future<void> showReactors(BuildContext context, int chatId, int seq) => _peopleSheet(
      context,
      '回应',
      ChatStore.instance.api
          .reactors(chatId, seq)
          .then((rows) => [for (final r in rows) (ChatUser.fromJson(r['user']), '${r['emoji']}')]),
    );

Future<void> showPollVoters(BuildContext context, int chatId, ChatMessage m) async {
  final store = ChatStore.instance;
  try {
    final r = (await store.api.api.requestJson('GET', '/chat/v1/chats/$chatId/polls/${m.seq}/voters')) as Map;
    final rows = <(ChatUser, String)>[];
    final opts = m.poll?.options ?? const [];
    for (final o in (r['options'] as List)) {
      final idx = ((o as Map)['index'] as num).toInt();
      for (final v in (o['voters'] as List)) {
        rows.add((ChatUser.fromJson(v), idx < opts.length ? opts[idx].text : ''));
      }
    }
    if (context.mounted) await _peopleSheet(context, '投票人', Future.value(rows));
  } on ApiException catch (e) {
    if (context.mounted) _toast(context, e.message);
  }
}

/// 点了 @用户名:人就打开资料页,公开群 / 频道就打开预览。
Future<void> openUsername(BuildContext context, String username) async {
  final store = ChatStore.instance;
  try {
    final r = await store.api.resolve(username);
    if (!context.mounted) return;
    if (r['type'] == 'user') {
      final u = ChatUser.fromJson(r['user']);
      await openUserProfile(context, u.id);
    } else {
      final chat = (r['chat'] as Map).cast<String, dynamic>();
      await openPublicChat(context, chat);
    }
  } on ApiException catch (e) {
    if (context.mounted) _toast(context, e.message);
  }
}

/// 公开群 / 频道:已经在里面就直接打开,不在就先看预览(可以加入)。
Future<void> openPublicChat(BuildContext context, Map<String, dynamic> chat) async {
  final store = ChatStore.instance;
  final id = (chat['id'] as num).toInt();
  if (chat['is_member'] == true) {
    await openChat(context, id);
    return;
  }
  // 和 Telegram 一样:公开的群 / 频道不加入也能先看(服务端 can_read_chat 放行公开会话),
  // 聊天页底部是「订阅 / 加入」按钮
  final join = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(kPagePad),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ChatAvatar(name: '${chat['title'] ?? ''}', url: '${chat['photo'] ?? ''}', size: 72),
          const SizedBox(height: 10),
          Text('${chat['title'] ?? ''}', style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
          Text(chat['type'] == 'channel' ? '${chat['member_count']} 位订阅者' : '${chat['member_count']} 位成员'),
          if ('${chat['about'] ?? ''}'.isNotEmpty)
            Padding(padding: const EdgeInsets.only(top: 8), child: Text('${chat['about']}', textAlign: TextAlign.center)),
          const SizedBox(height: 16),
          if (chat['banned'] == true)
            const Text('你已被移出,不能再加入')
          else ...[
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: () => Navigator.pop(ctx, 'join'),
                child: Text(chat['type'] == 'channel' ? '订阅' : '加入'),
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton(onPressed: () => Navigator.pop(ctx, 'preview'), child: const Text('先看看')),
            ),
          ],
        ]),
      ),
    ),
  );
  if (join == null || !context.mounted) return;
  if (join == 'preview') {
    await openChat(context, id);
    return;
  }
  try {
    await store.api.joinPublic(id);
    await store.refresh();
    if (context.mounted) await openChat(context, id);
  } on ApiException catch (e) {
    if (context.mounted) _toast(context, e.message);
  }
}
