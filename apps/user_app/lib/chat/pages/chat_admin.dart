import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../identity_page.dart';
import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';

// 群 / 频道的管理页面(DEV-PROMPTS-40 §5.6)。按钮出不出现看服务端给的 perms,
// 接口也会再判一次 —— 两边同一张真值表(services/chat_perms.py)。

void _toast(BuildContext context, String s) {
  if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
}

/// 多选联系人(建群、加成员)。返回 user id 列表。
Future<List<int>?> pickContactsMulti(BuildContext context, {String title = '选择联系人', Set<int> exclude = const {}}) =>
    Navigator.of(context).push<List<int>>(
        MaterialPageRoute(builder: (_) => _ContactsMultiPage(title: title, exclude: exclude)));

class _ContactsMultiPage extends StatefulWidget {
  const _ContactsMultiPage({required this.title, required this.exclude});

  final String title;
  final Set<int> exclude;

  @override
  State<_ContactsMultiPage> createState() => _ContactsMultiPageState();
}

class _ContactsMultiPageState extends State<_ContactsMultiPage> {
  List<ChatUser>? _all;
  final Set<int> _picked = {};
  String _q = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final store = ChatStore.instance;
    final contacts = await store.api.contacts().catchError((_) => <ChatUser>[]);
    // 联系人之外,最近私聊过的人也列出来(没加联系人也能拉进群)
    final seen = {for (final u in contacts) u.id};
    final recent = [
      for (final c in store.sortedChats())
        if (c.isPrivate && c.peer != null && !seen.contains(c.peer!.id) && !c.peer!.isBot) c.peer!
    ];
    if (mounted) setState(() => _all = [...contacts, ...recent].where((u) => !widget.exclude.contains(u.id)).toList());
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final all = (_all ?? const <ChatUser>[])
        .where((u) => _q.isEmpty || u.displayName.contains(_q) || (u.username ?? '').contains(_q))
        .toList();
    return SzPageScaffold(
      appBar: AppBar(
        title: Text(_picked.isEmpty ? widget.title : '已选 ${_picked.length} 人'),
        actions: [
          TextButton(
            onPressed: _picked.isEmpty ? null : () => Navigator.pop(context, _picked.toList()),
            child: const Text('确定'),
          ),
        ],
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 8),
          child: TextField(
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: '搜索', isDense: true),
            onChanged: (v) => setState(() => _q = v.trim()),
          ),
        ),
        Expanded(
          child: _all == null
              ? const Center(child: CircularProgressIndicator())
              : all.isEmpty
                  ? Center(
                      child: Text('没有可选的人。先加联系人,或者用邀请链接',
                          style: TextStyle(color: sz.inkMuted)))
                  : ListView.builder(
                      itemCount: all.length,
                      itemBuilder: (context, i) {
                        final u = all[i];
                        final on = _picked.contains(u.id);
                        return ListTile(
                          leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 40),
                          title: Text(u.displayName),
                          subtitle: Text(u.lastSeen.label(), style: const TextStyle(fontSize: kFontNote)),
                          trailing: Icon(on ? Icons.check_circle : Icons.radio_button_unchecked,
                              color: on ? sz.clay : sz.inkFaint),
                          onTap: () => setState(() => on ? _picked.remove(u.id) : _picked.add(u.id)),
                        );
                      },
                    ),
        ),
      ]),
    );
  }
}

/// 改群 / 频道资料:头像、名称、简介、公开链接(用户名)。
class EditChatPage extends StatefulWidget {
  const EditChatPage({super.key, required this.chatId});

  final int chatId;

  @override
  State<EditChatPage> createState() => _EditChatPageState();
}

class _EditChatPageState extends State<EditChatPage> {
  late final ChatInfo c = ChatStore.instance.chats[widget.chatId]!;
  late final _title = TextEditingController(text: c.title);
  late final _about = TextEditingController(text: c.about);
  late final _username = TextEditingController(text: c.username ?? '');
  late bool _public = c.username != null;
  late String _photo = c.photo;
  bool _busy = false;

  @override
  void dispose() {
    _title.dispose();
    _about.dispose();
    _username.dispose();
    super.dispose();
  }

  Future<void> _pickPhoto() async {
    final f = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 1024, imageQuality: 88);
    if (f == null) return;
    setState(() => _busy = true);
    try {
      final bytes = await f.readAsBytes();
      final m = await ChatStore.instance.client
          .uploadMediaBytes(bytes, f.name, kind: 'chat_photo', purpose: 'chat_photo');
      setState(() => _photo = '${m['public_url'] ?? ''}');
    } on ApiException catch (e) {
      if (mounted) _toast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      final body = <String, dynamic>{
        'title': _title.text.trim(),
        'about': _about.text.trim(),
        if (_photo != c.photo) 'photo': _photo,
        'username': _public ? _username.text.trim().replaceFirst('@', '') : '',
      };
      final n = await ChatStore.instance.api.patchChat(c.id, body);
      ChatStore.instance.putChat(n);
      if (mounted) Navigator.pop(context);
    } on ApiException catch (e) {
      if (!mounted) return;
      if (e.message.contains('实名认证')) {
        // 卡在实名上:给一个直接去认证的按钮,认证完回来再点保存
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e.message),
          action: SnackBarAction(
            label: '去认证',
            onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => IdentityPage(api: ChatStore.instance.client))),
          ),
        ));
      } else {
        _toast(context, e.message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(
        title: Text(c.isChannel ? '编辑频道' : '编辑群'),
        actions: [TextButton(onPressed: _busy ? null : _save, child: const Text('保存'))],
      ),
      body: ListView(padding: const EdgeInsets.all(kPagePad), children: [
        Center(
          child: GestureDetector(
            onTap: _busy ? null : _pickPhoto,
            child: Stack(children: [
              ChatAvatar(name: _title.text, url: _photo, size: 88),
              Positioned(
                right: 0,
                bottom: 0,
                child: CircleAvatar(radius: 14, backgroundColor: sz.clay, child: const Icon(Icons.photo_camera, size: 16, color: Colors.white)),
              ),
            ]),
          ),
        ),
        const SizedBox(height: 16),
        TextField(controller: _title, maxLength: 128, decoration: const InputDecoration(labelText: '名称')),
        TextField(controller: _about, maxLength: 255, maxLines: 3, decoration: const InputDecoration(labelText: '简介')),
        const SizedBox(height: 8),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: _public,
          onChanged: (v) => setState(() => _public = v),
          title: Text(c.isChannel ? '公开频道' : '公开群'),
          subtitle: const Text('公开后任何人都能搜到、用链接加入(要先完成实名认证)'),
        ),
        if (_public)
          TextField(
            controller: _username,
            decoration: const InputDecoration(labelText: '链接', prefixText: 'chaojizan.cc/@'),
          ),
      ]),
    );
  }
}

/// 管理员列表。
class AdminsPage extends StatefulWidget {
  const AdminsPage({super.key, required this.chatId});

  final int chatId;

  @override
  State<AdminsPage> createState() => _AdminsPageState();
}

class _AdminsPageState extends State<AdminsPage> {
  List<Map<String, dynamic>>? _rows;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await ChatStore.instance.api.members(widget.chatId, role: 'admins');
      if (mounted) setState(() => _rows = r);
    } on ApiException catch (e) {
      if (mounted) _toast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = ChatStore.instance.chats[widget.chatId];
    return SzPageScaffold(
      appBar: AppBar(title: const Text('管理员')),
      body: _rows == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(children: [
              for (final row in _rows!)
                Builder(builder: (context) {
                  final u = ChatUser.fromJson(row['user']);
                  final role = '${row['role']}';
                  final title = '${row['title'] ?? ''}';
                  return ListTile(
                    leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 40),
                    title: Text(u.displayName),
                    subtitle: Text(title.isNotEmpty
                        ? title
                        : (role == 'owner' ? (c?.isChannel == true ? '所有者' : '群主') : '管理员')),
                    onTap: c == null || role == 'owner' || !c.can('add_admins')
                        ? null
                        : () async {
                            final res = await Navigator.of(context).push<({Map<String, bool> rights, String title})>(
                                MaterialPageRoute(builder: (_) => AdminRightsPage(chat: c, user: u, current: row)));
                            if (res == null) return;
                            try {
                              await ChatStore.instance.api
                                  .memberAction(c.id, u.id, 'promote', rights: res.rights, title: res.title);
                              await _load();
                            } on ApiException catch (e) {
                              if (context.mounted) _toast(context, e.message);
                            }
                          },
                  );
                }),
              const Padding(
                padding: EdgeInsets.all(kPagePad),
                child: Text('在成员列表里点一个人,可以把他设为管理员。管理员只能授予自己拥有的权限。',
                    style: TextStyle(fontSize: kFontNote)),
              ),
            ]),
    );
  }
}

const adminRightLabels = <String, String>{
  'change_info': '修改群资料',
  'delete_messages': '删除别人的消息',
  'ban_users': '封禁和限制成员',
  'invite_users': '邀请成员、管理链接',
  'pin_messages': '置顶消息',
  'add_admins': '任免管理员',
  'post_messages': '发布消息(频道)',
  'edit_messages': '编辑别人的帖子(频道)',
  'anonymous': '匿名发言(显示为群)',
};

/// 设管理员:逐项权限 + 自定义头衔。
class AdminRightsPage extends StatefulWidget {
  const AdminRightsPage({super.key, required this.chat, required this.user, required this.current});

  final ChatInfo chat;
  final ChatUser user;
  final Map<String, dynamic> current;

  @override
  State<AdminRightsPage> createState() => _AdminRightsPageState();
}

class _AdminRightsPageState extends State<AdminRightsPage> {
  late final Map<String, bool> _rights = {
    for (final k in adminRightLabels.keys)
      if (_applies(k))
        k: widget.current['role'] == 'admin'
            ? ((widget.current['rights'] as Map?)?[k] == true)
            : const {'change_info', 'delete_messages', 'ban_users', 'invite_users', 'pin_messages', 'post_messages', 'edit_messages'}.contains(k),
  };
  late final _title = TextEditingController(text: '${widget.current['title'] ?? ''}');

  bool _applies(String k) {
    final ch = widget.chat.isChannel;
    if (k == 'post_messages' || k == 'edit_messages') return ch;
    if (k == 'anonymous') return !ch;
    return true;
  }

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final mine = widget.chat.my.role == 'owner' ? null : widget.chat.my.rights;
    return SzPageScaffold(
      appBar: AppBar(
        title: Text('${widget.user.displayName} 的权限'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, (rights: _rights, title: _title.text.trim())),
            child: const Text('保存'),
          ),
        ],
      ),
      body: ListView(children: [
        for (final e in _rights.entries)
          SwitchListTile(
            value: e.value,
            // 只能授予自己拥有的权限
            onChanged: mine != null && mine[e.key] != true ? null : (v) => setState(() => _rights[e.key] = v),
            title: Text(adminRightLabels[e.key]!),
          ),
        Padding(
          padding: const EdgeInsets.all(kPagePad),
          child: TextField(
            controller: _title,
            maxLength: 16,
            decoration: const InputDecoration(labelText: '头衔(可选)', hintText: '显示在他名字旁边,比如「值班」'),
          ),
        ),
      ]),
    );
  }
}

const memberPermLabels = <String, String>{
  'send_messages': '发消息',
  'send_media': '发图片、视频、文件',
  'send_stickers': '发贴纸和 GIF',
  'send_polls': '发投票',
  'embed_links': '带链接预览',
  'invite_users': '邀请成员',
  'pin_messages': '置顶消息',
  'change_info': '修改群资料',
};

/// 限制某个成员:哪些不能做 + 到什么时候。
Future<({Map<String, bool> perms, DateTime? until})?> pickRestriction(BuildContext context) async {
  final perms = {for (final k in memberPermLabels.keys) k: k != 'send_messages'};
  perms['send_messages'] = false;
  Duration? d = const Duration(days: 1);
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) => SzDialog(
        scrollable: true,
        title: const Text('限制发言'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final e in memberPermLabels.entries)
            CheckboxListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              value: perms[e.key],
              onChanged: (v) => set(() => perms[e.key] = v ?? false),
              title: Text('可以${e.value}'),
            ),
          const Divider(),
          RadioGroup<Duration?>(
            groupValue: d,
            onChanged: (v) => set(() => d = v),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              for (final (label, dur) in const [
                ('1 小时', Duration(hours: 1)),
                ('1 天', Duration(days: 1)),
                ('7 天', Duration(days: 7)),
                ('永久', null),
              ])
                RadioListTile<Duration?>(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  value: dur,
                  title: Text(label),
                ),
            ]),
          ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('限制')),
        ],
      ),
    ),
  );
  if (ok != true) return null;
  return (perms: perms, until: d == null ? null : DateTime.now().add(d!));
}

/// 群设置:成员默认权限、慢速模式、入群审批、新成员看历史、禁止转发、可用回应;频道:署名。
class PermissionsPage extends StatefulWidget {
  const PermissionsPage({super.key, required this.chatId});

  final int chatId;

  @override
  State<PermissionsPage> createState() => _PermissionsPageState();
}

class _PermissionsPageState extends State<PermissionsPage> {
  late final ChatInfo c = ChatStore.instance.chats[widget.chatId]!;
  late final Map<String, bool> _perms = {
    for (final k in memberPermLabels.keys)
      k: ((c.settings['default_perms'] as Map?)?[k] ?? (k != 'pin_messages' && k != 'change_info')) == true,
  };
  late int _slow = (c.settings['slow_mode'] as num?)?.toInt() ?? 0;
  late bool _joinByRequest = c.settings['join_by_request'] == true;
  late bool _history = c.settings['history_visible'] != false;
  late bool _protected = c.settings['protected'] == true;
  late bool _signatures = c.settings['signatures'] == true;
  late bool _reactions = c.settings['reactions'] != 'none';

  Future<void> _save() async {
    try {
      final n = await ChatStore.instance.api.patchChat(c.id, {
        'settings': {
          'default_perms': _perms,
          'slow_mode': _slow,
          'join_by_request': _joinByRequest,
          'history_visible': _history,
          'protected': _protected,
          'signatures': _signatures,
          'reactions': _reactions ? 'all' : 'none',
        }
      });
      ChatStore.instance.putChat(n);
      if (mounted) Navigator.pop(context);
    } on ApiException catch (e) {
      if (mounted) _toast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('成员权限'), actions: [TextButton(onPressed: _save, child: const Text('保存'))]),
      body: ListView(children: [
        if (c.isGroup) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
            child: Text('成员可以', style: TextStyle(color: sz.clay, fontWeight: FontWeight.w600)),
          ),
          for (final e in memberPermLabels.entries)
            SwitchListTile(
                value: _perms[e.key]!, onChanged: (v) => setState(() => _perms[e.key] = v), title: Text(e.value)),
          const Divider(),
          ListTile(
            title: const Text('慢速模式'),
            subtitle: Text(_slow == 0 ? '关闭' : '每人每 ${_slowLabel(_slow)} 只能发一条'),
          ),
          Wrap(spacing: 8, children: [
            const SizedBox(width: kPagePad - 8),
            for (final s in const [0, 10, 30, 60, 300, 900, 3600])
              ChoiceChip(label: Text(s == 0 ? '关' : _slowLabel(s)), selected: _slow == s, onSelected: (_) => setState(() => _slow = s)),
          ]),
          const Divider(),
          SwitchListTile(value: _joinByRequest, onChanged: (v) => setState(() => _joinByRequest = v),
              title: const Text('入群要审批'), subtitle: const Text('通过链接进来的人要管理员同意')),
          SwitchListTile(value: _history, onChanged: (v) => setState(() => _history = v),
              title: const Text('新成员能看到之前的消息')),
        ],
        if (c.isChannel)
          SwitchListTile(value: _signatures, onChanged: (v) => setState(() => _signatures = v),
              title: const Text('帖子署名'), subtitle: const Text('帖子下面显示是哪位管理员发的')),
        SwitchListTile(value: _protected, onChanged: (v) => setState(() => _protected = v),
            title: const Text('禁止转发和保存'), subtitle: const Text('成员不能把消息转出去、不能复制')),
        SwitchListTile(value: _reactions, onChanged: (v) => setState(() => _reactions = v),
            title: const Text('允许表情回应')),
      ]),
    );
  }

  String _slowLabel(int s) => s < 60 ? '$s 秒' : (s < 3600 ? '${s ~/ 60} 分钟' : '${s ~/ 3600} 小时');
}

/// 邀请链接:主链接 + 附加链接(名称、过期、次数、需审批)。
class InviteLinksPage extends StatefulWidget {
  const InviteLinksPage({super.key, required this.chatId});

  final int chatId;

  @override
  State<InviteLinksPage> createState() => _InviteLinksPageState();
}

class _InviteLinksPageState extends State<InviteLinksPage> {
  List<Map<String, dynamic>>? _rows;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await ChatStore.instance.api.invites(widget.chatId);
      if (mounted) setState(() => _rows = r);
    } on ApiException catch (e) {
      if (mounted) _toast(context, e.message);
    }
  }

  Future<void> _create() async {
    final title = TextEditingController();
    int? limit;
    Duration? expire;
    var approval = false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => SzDisposeWith(
        controllers: [title],
        child: StatefulBuilder(
          builder: (ctx, set) => SzDialog(
            scrollable: true,
            title: const Text('新建邀请链接'),
            content: Column(mainAxisSize: MainAxisSize.min, children: [
              TextField(controller: title, maxLength: 32, decoration: const InputDecoration(labelText: '名称(可选)')),
              DropdownButtonFormField<Duration?>(
                initialValue: expire,
                decoration: const InputDecoration(labelText: '有效期'),
                items: const [
                  DropdownMenuItem(value: null, child: Text('不过期')),
                  DropdownMenuItem(value: Duration(hours: 1), child: Text('1 小时')),
                  DropdownMenuItem(value: Duration(days: 1), child: Text('1 天')),
                  DropdownMenuItem(value: Duration(days: 7), child: Text('7 天')),
                ],
                onChanged: (v) => set(() => expire = v),
              ),
              DropdownButtonFormField<int?>(
                initialValue: limit,
                decoration: const InputDecoration(labelText: '可用次数'),
                items: const [
                  DropdownMenuItem(value: null, child: Text('不限')),
                  DropdownMenuItem(value: 1, child: Text('1 次')),
                  DropdownMenuItem(value: 10, child: Text('10 次')),
                  DropdownMenuItem(value: 100, child: Text('100 次')),
                ],
                onChanged: (v) => set(() => limit = v),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: approval,
                onChanged: (v) => set(() => approval = v),
                title: const Text('要管理员审批'),
              ),
            ]),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('创建')),
            ],
          ),
        ),
      ),
    );
    final t = title.text.trim();
    if (ok != true) return;
    try {
      await ChatStore.instance.api.createInvite(widget.chatId,
          title: t, expireAt: expire == null ? null : DateTime.now().add(expire!), usageLimit: limit, approval: approval);
      await _load();
    } on ApiException catch (e) {
      if (mounted) _toast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('邀请链接')),
      floatingActionButton: FloatingActionButton(onPressed: _create, child: const Icon(Icons.add_link)),
      body: _rows == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(children: [
              for (final r in _rows!)
                ListTile(
                  leading: Icon(r['revoked'] == true ? Icons.link_off : Icons.link,
                      color: r['revoked'] == true ? sz.inkFaint : sz.clay),
                  title: Text('${r['url']}',
                      style: TextStyle(
                          decoration: r['revoked'] == true ? TextDecoration.lineThrough : null,
                          color: r['revoked'] == true ? sz.inkFaint : sz.ink)),
                  subtitle: Text([
                    if (r['is_primary'] == true) '主链接',
                    if ('${r['title'] ?? ''}'.isNotEmpty) '${r['title']}',
                    '已用 ${r['usage_count']}${r['usage_limit'] == null ? '' : '/${r['usage_limit']}'} 次',
                    if (r['requires_approval'] == true) '需审批',
                    if (r['expire_at'] != null) '到期 ${DateTime.tryParse('${r['expire_at']}')?.toLocal().toString().substring(0, 16) ?? ''}',
                  ].join(' · ')),
                  trailing: r['revoked'] == true
                      ? null
                      : PopupMenuButton<String>(
                          onSelected: (v) async {
                            if (v == 'copy') {
                              await Clipboard.setData(ClipboardData(text: '${r['url']}'));
                              if (context.mounted) _toast(context, '已复制');
                            } else if (v == 'share') {
                              await SharePlus.instance.share(ShareParams(text: '${r['url']}'));
                            } else {
                              try {
                                await ChatStore.instance.api.revokeInvite(widget.chatId, '${r['code']}');
                                await _load();
                              } on ApiException catch (e) {
                                if (context.mounted) _toast(context, e.message);
                              }
                            }
                          },
                          itemBuilder: (_) => [
                            const PopupMenuItem(value: 'copy', child: Text('复制')),
                            const PopupMenuItem(value: 'share', child: Text('分享')),
                            PopupMenuItem(value: 'revoke', child: Text(r['is_primary'] == true ? '换一个新链接' : '作废')),
                          ],
                        ),
                ),
            ]),
    );
  }
}

/// 入群申请。
class JoinRequestsPage extends StatefulWidget {
  const JoinRequestsPage({super.key, required this.chatId});

  final int chatId;

  @override
  State<JoinRequestsPage> createState() => _JoinRequestsPageState();
}

class _JoinRequestsPageState extends State<JoinRequestsPage> {
  List<Map<String, dynamic>>? _rows;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await ChatStore.instance.api.joinRequests(widget.chatId);
      if (mounted) setState(() => _rows = r);
    } on ApiException catch (e) {
      if (mounted) _toast(context, e.message);
    }
  }

  Future<void> _decide(int uid, bool approve) async {
    try {
      await ChatStore.instance.api.decideJoin(widget.chatId, uid, approve);
      await _load();
    } on ApiException catch (e) {
      if (mounted) _toast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('入群申请')),
      body: _rows == null
          ? const Center(child: CircularProgressIndicator())
          : _rows!.isEmpty
              ? Center(child: Text('没有待处理的申请', style: TextStyle(color: sz.inkMuted)))
              : ListView(children: [
                  for (final r in _rows!)
                    Builder(builder: (_) {
                      final u = ChatUser.fromJson(r['user']);
                      return ListTile(
                        leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 40),
                        title: Text(u.displayName),
                        subtitle: '${r['about'] ?? ''}'.isEmpty ? null : Text('${r['about']}'),
                        trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                          IconButton(tooltip: '拒绝', icon: Icon(Icons.close, color: sz.danger), onPressed: () => _decide(u.id, false)),
                          IconButton(tooltip: '通过', icon: Icon(Icons.check, color: sz.earn), onPressed: () => _decide(u.id, true)),
                        ]),
                      );
                    }),
                ]),
    );
  }
}

/// 已封禁的人,可以解封。
class BannedPage extends StatefulWidget {
  const BannedPage({super.key, required this.chatId});

  final int chatId;

  @override
  State<BannedPage> createState() => _BannedPageState();
}

class _BannedPageState extends State<BannedPage> {
  List<Map<String, dynamic>>? _rows;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await ChatStore.instance.api.members(widget.chatId, role: 'banned');
      if (mounted) setState(() => _rows = r);
    } on ApiException catch (e) {
      if (mounted) _toast(context, e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('已封禁')),
      body: _rows == null
          ? const Center(child: CircularProgressIndicator())
          : _rows!.isEmpty
              ? Center(child: Text('没有封禁的人', style: TextStyle(color: sz.inkMuted)))
              : ListView(children: [
                  for (final r in _rows!)
                    Builder(builder: (_) {
                      final u = ChatUser.fromJson(r['user']);
                      return ListTile(
                        leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 40),
                        title: Text(u.displayName),
                        trailing: TextButton(
                          onPressed: () async {
                            try {
                              await ChatStore.instance.api.memberAction(widget.chatId, u.id, 'unban');
                              await _load();
                            } on ApiException catch (e) {
                              if (context.mounted) _toast(context, e.message);
                            }
                          },
                          child: const Text('解封'),
                        ),
                      );
                    }),
                ]),
    );
  }
}
