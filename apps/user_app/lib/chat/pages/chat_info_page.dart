import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';
import 'chat_admin.dart';
import 'pickers.dart';
import 'shared_media_page.dart';
import 'user_profile_page.dart';

/// 群 / 频道资料页:头像、名称、简介、链接;通知;共享媒体;管理(管理员);成员;退出。
class ChatInfoPage extends StatefulWidget {
  const ChatInfoPage({super.key, required this.chatId});

  final int chatId;

  @override
  State<ChatInfoPage> createState() => _ChatInfoPageState();
}

class _ChatInfoPageState extends State<ChatInfoPage> {
  List<Map<String, dynamic>> _members = [];
  bool _loadingMembers = false;
  String? _inviteUrl;

  ChatStore get store => ChatStore.instance;
  ChatInfo? get chat => store.chats[widget.chatId];

  @override
  void initState() {
    super.initState();
    store.addListener(_onStore);
    store.refreshChat(widget.chatId);
    _loadMembers();
    _loadInvite();
  }

  @override
  void dispose() {
    store.removeListener(_onStore);
    super.dispose();
  }

  void _onStore() {
    if (!mounted) return;
    if (chat == null) {
      Navigator.of(context).maybePop();
      return;
    }
    setState(() {});
  }

  Future<void> _loadMembers() async {
    final c = chat;
    if (c == null || (c.isChannel && !c.can('is_admin'))) return;
    setState(() => _loadingMembers = true);
    try {
      final r = await store.api.members(widget.chatId);
      if (mounted) setState(() => _members = r);
    } catch (_) {
    } finally {
      if (mounted) setState(() => _loadingMembers = false);
    }
  }

  Future<void> _loadInvite() async {
    final c = chat;
    if (c == null || c.username != null || !c.can('invite_users')) return;
    try {
      final r = await store.api.invites(widget.chatId);
      final primary = r.firstWhere((x) => x['is_primary'] == true && x['revoked'] != true, orElse: () => const {});
      if (mounted && primary.isNotEmpty) setState(() => _inviteUrl = '${primary['url']}');
    } catch (_) {}
  }

  void _toast(String s) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  Future<void> _addMembers(ChatInfo c) async {
    final ids = await pickContactsMulti(context, title: '添加成员', exclude: {for (final m in _members) ((m['user'] as Map)['id'] as num).toInt()});
    if (ids == null || ids.isEmpty) return;
    try {
      final r = await store.api.addMembers(c.id, ids);
      final skipped = (r['skipped'] as List? ?? const []);
      if (skipped.isNotEmpty) {
        _toast('有 ${skipped.length} 人设置了不让直接拉进群,把邀请链接发给他们吧');
      }
      await _loadMembers();
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final c = chat;
    if (c == null) return SzPageScaffold(appBar: AppBar(), body: const SizedBox.shrink());
    final link = c.username != null ? 'https://chaojizan.cc/@${c.username}' : _inviteUrl;
    final isAdmin = c.can('is_admin');
    return SzPageScaffold(
      appBar: AppBar(
        actions: [
          if (c.can('change_info'))
            IconButton(
              tooltip: '编辑',
              icon: const Icon(Icons.edit_outlined),
              onPressed: () => Navigator.of(context)
                  .push(MaterialPageRoute<void>(builder: (_) => EditChatPage(chatId: c.id))),
            ),
        ],
      ),
      body: ListView(children: [
        const SizedBox(height: 8),
        Center(child: ChatAvatar(name: c.title, url: c.photo, size: 96)),
        const SizedBox(height: 12),
        Center(child: Text(c.title, style: const TextStyle(fontSize: kFontLead, fontWeight: FontWeight.w700))),
        Center(
          child: Text(c.isChannel ? '${c.memberCount} 位订阅者' : '${c.memberCount} 位成员',
              style: TextStyle(color: sz.inkMuted, fontSize: kFontNote)),
        ),
        const SizedBox(height: 8),
        if (c.about.isNotEmpty)
          ListTile(leading: const Icon(Icons.info_outline), title: Text(c.about), subtitle: const Text('简介')),
        if (link != null)
          ListTile(
            leading: const Icon(Icons.link),
            title: Text(link, style: TextStyle(color: sz.link)),
            subtitle: Text(c.username != null ? '公开链接' : '邀请链接'),
            onTap: () async {
              await Clipboard.setData(ClipboardData(text: link));
              _toast('链接已复制');
            },
            trailing: IconButton(
              icon: const Icon(Icons.share_outlined),
              onPressed: () => SharePlus.instance.share(ShareParams(text: '加入「${c.title}」:$link')),
            ),
          ),
        ListTile(
          leading: Icon(c.my.muted ? Icons.notifications_off_outlined : Icons.notifications_outlined),
          title: const Text('消息通知'),
          trailing: Switch(
            value: !c.my.muted,
            onChanged: (on) async {
              final until = on ? null : await pickMuteUntil(context);
              if (!on && until == null) return;
              final n = await store.api.patchDialog(c.id, {'muted_until': muteParam(until)});
              store.putChat(n);
            },
          ),
        ),
        ListTile(
          leading: const Icon(Icons.perm_media_outlined),
          title: const Text('图片、文件和链接'),
          trailing: const Icon(Icons.chevron_right),
          onTap: () => Navigator.of(context)
              .push(MaterialPageRoute<void>(builder: (_) => SharedMediaPage(chatId: c.id))),
        ),
        if (isAdmin) ...[
          const Divider(),
          _Section('管理'),
          ListTile(
            leading: const Icon(Icons.admin_panel_settings_outlined),
            title: const Text('管理员'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context)
                .push(MaterialPageRoute<void>(builder: (_) => AdminsPage(chatId: c.id))),
          ),
          if (c.isGroup && c.can('ban_users'))
            ListTile(
              leading: const Icon(Icons.tune),
              title: const Text('成员权限'),
              subtitle: Text(_permsSummary(c)),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context)
                  .push(MaterialPageRoute<void>(builder: (_) => PermissionsPage(chatId: c.id))),
            ),
          if (c.can('invite_users'))
            ListTile(
              leading: const Icon(Icons.insert_link),
              title: const Text('邀请链接'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context)
                  .push(MaterialPageRoute<void>(builder: (_) => InviteLinksPage(chatId: c.id))),
            ),
          if (c.can('invite_users'))
            ListTile(
              leading: const Icon(Icons.how_to_reg_outlined),
              title: const Text('入群申请'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context)
                  .push(MaterialPageRoute<void>(builder: (_) => JoinRequestsPage(chatId: c.id))),
            ),
          if (c.can('ban_users'))
            ListTile(
              leading: const Icon(Icons.block),
              title: const Text('已封禁'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context)
                  .push(MaterialPageRoute<void>(builder: (_) => BannedPage(chatId: c.id))),
            ),
        ],
        if (!c.isChannel || isAdmin) ...[
          const Divider(),
          _Section(c.isChannel ? '订阅者' : '成员'),
          if (c.can('invite_users'))
            ListTile(
              leading: Icon(Icons.person_add_alt_1_outlined, color: sz.clay),
              title: Text(c.isChannel ? '添加订阅者' : '添加成员', style: TextStyle(color: sz.clay)),
              onTap: () => _addMembers(c),
            ),
          if (_loadingMembers && _members.isEmpty)
            const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
          for (final row in _members) _memberTile(c, row),
        ],
        const Divider(),
        ListTile(
          leading: Icon(Icons.flag_outlined, color: sz.inkMuted),
          title: const Text('举报'),
          onTap: () => reportChat(context, c),
        ),
        ListTile(
          leading: Icon(Icons.logout, color: sz.danger),
          title: Text(c.my.role == 'owner' ? (c.isChannel ? '解散频道' : '解散群') : (c.isChannel ? '退订' : '退出群'),
              style: TextStyle(color: sz.danger)),
          onTap: () async {
            final done = await leaveOrDelete(context, c);
            if (done && context.mounted) Navigator.of(context).popUntil((r) => r.isFirst);
          },
        ),
        const SizedBox(height: 24),
      ]),
    );
  }

  String _permsSummary(ChatInfo c) {
    final s = c.settings;
    final slow = (s['slow_mode'] as num?)?.toInt() ?? 0;
    final parts = <String>[
      if (slow > 0) '慢速 $slow 秒',
      if (s['join_by_request'] == true) '入群要审批',
      if (s['protected'] == true) '禁止转发',
    ];
    return parts.isEmpty ? '默认' : parts.join(' · ');
  }

  Widget _memberTile(ChatInfo c, Map<String, dynamic> row) {
    final sz = Theme.of(context).sz;
    final u = ChatUser.fromJson(row['user']);
    final role = '${row['role']}';
    final title = '${row['title'] ?? ''}';
    final roleLabel = switch (role) {
      'owner' => title.isNotEmpty ? title : (c.isChannel ? '所有者' : '群主'),
      'admin' => title.isNotEmpty ? title : '管理员',
      'restricted' => '被限制',
      _ => '',
    };
    return ListTile(
      leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 40, online: u.lastSeen.online),
      title: Text(u.isSelf ? '${u.displayName}(我)' : u.displayName, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text(u.lastSeen.label(), style: TextStyle(fontSize: kFontNote, color: u.lastSeen.online ? sz.clay : sz.inkMuted)),
      trailing: roleLabel.isEmpty ? null : Text(roleLabel, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      onTap: () => u.isSelf ? null : memberActions(context, c, row, onChanged: _loadMembers),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 4),
        child: Text(text,
            style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600, color: Theme.of(context).sz.clay)),
      );
}

/// 点群成员:看资料、设为管理员、限制、移出、封禁(按我的权限出现)。
Future<void> memberActions(BuildContext context, ChatInfo c, Map<String, dynamic> row,
    {required Future<void> Function() onChanged}) async {
  final store = ChatStore.instance;
  final u = ChatUser.fromJson(row['user']);
  final role = '${row['role']}';
  final canManage = role != 'owner' && (c.can('ban_users') || c.can('add_admins'));
  final pick = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(
          leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 40),
          title: Text(u.displayName),
          subtitle: u.username == null ? null : Text('@${u.username}'),
        ),
        const Divider(height: 1),
        ListTile(leading: const Icon(Icons.person_outline), title: const Text('查看资料'), onTap: () => Navigator.pop(ctx, 'profile')),
        if (canManage && c.can('add_admins') && role != 'admin')
          ListTile(leading: const Icon(Icons.admin_panel_settings_outlined), title: const Text('设为管理员'), onTap: () => Navigator.pop(ctx, 'promote')),
        if (canManage && c.can('add_admins') && role == 'admin')
          ListTile(leading: const Icon(Icons.edit_attributes_outlined), title: const Text('修改管理员权限'), onTap: () => Navigator.pop(ctx, 'promote')),
        if (canManage && c.can('add_admins') && role == 'admin')
          ListTile(leading: const Icon(Icons.remove_moderator_outlined), title: const Text('取消管理员'), onTap: () => Navigator.pop(ctx, 'demote')),
        if (canManage && c.can('ban_users') && c.isGroup && role != 'admin')
          ListTile(leading: const Icon(Icons.voice_over_off_outlined), title: Text(role == 'restricted' ? '解除限制' : '限制发言'), onTap: () => Navigator.pop(ctx, role == 'restricted' ? 'unrestrict' : 'restrict')),
        if (canManage && c.can('ban_users'))
          ListTile(leading: const Icon(Icons.person_remove_outlined), title: const Text('移出'), onTap: () => Navigator.pop(ctx, 'kick')),
        if (canManage && c.can('ban_users'))
          ListTile(
              leading: Icon(Icons.block, color: Theme.of(ctx).sz.danger),
              title: Text('封禁', style: TextStyle(color: Theme.of(ctx).sz.danger)),
              subtitle: const Text('移出并且不能通过链接再加入'),
              onTap: () => Navigator.pop(ctx, 'ban')),
        if (c.my.role == 'owner' && role != 'owner')
          ListTile(leading: const Icon(Icons.swap_horiz), title: Text(c.isChannel ? '转让频道' : '转让群主'), onTap: () => Navigator.pop(ctx, 'transfer')),
      ]),
    ),
  );
  if (pick == null || !context.mounted) return;
  try {
    switch (pick) {
      case 'profile':
        await openUserProfile(context, u.id);
        return;
      case 'promote':
        final res = await Navigator.of(context).push<({Map<String, bool> rights, String title})>(
            MaterialPageRoute(builder: (_) => AdminRightsPage(chat: c, user: u, current: row)));
        if (res == null) return;
        await store.api.memberAction(c.id, u.id, 'promote', rights: res.rights, title: res.title);
      case 'demote':
        await store.api.memberAction(c.id, u.id, 'demote');
      case 'restrict':
        final res = await pickRestriction(context);
        if (res == null) return;
        await store.api.memberAction(c.id, u.id, 'restrict', perms: res.perms, until: res.until);
      case 'unrestrict':
        await store.api.memberAction(c.id, u.id, 'unrestrict');
      case 'kick':
        await store.api.memberAction(c.id, u.id, 'kick');
      case 'ban':
        await store.api.memberAction(c.id, u.id, 'ban');
      case 'transfer':
        if (!context.mounted) return;
        final ok = await showDialog<bool>(
          context: context,
          builder: (ctx) => SzDialog(
            title: Text('把「${c.title}」转让给 ${u.displayName}?'),
            content: const Text('转让之后你变成普通管理员,不能再撤回。'),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('转让')),
            ],
          ),
        );
        if (ok != true) return;
        await store.api.transfer(c.id, u.id);
        await store.refreshChat(c.id);
    }
    await onChanged();
  } on ApiException catch (e) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
  }
}
