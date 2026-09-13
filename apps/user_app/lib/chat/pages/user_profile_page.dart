import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import '../chat_page.dart';
import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';
import 'pickers.dart';
import 'shared_media_page.dart';

/// 打开某人的资料页。
Future<void> openUserProfile(BuildContext context, int userId, {bool fromChat = false}) =>
    Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => UserProfilePage(userId: userId, fromChat: fromChat)));

/// 一个人的资料(Telegram 的用户资料页):头像、名字、@用户名、签名、最后上线;
/// 发消息 / 加联系人 / 拉黑 / 举报;和他的共享媒体。**没有手机号**(S2)。
class UserProfilePage extends StatefulWidget {
  const UserProfilePage({super.key, required this.userId, this.fromChat = false});

  final int userId;

  /// 从和他的聊天页点进来的:「发消息」直接返回聊天页
  final bool fromChat;

  @override
  State<UserProfilePage> createState() => _UserProfilePageState();
}

class _UserProfilePageState extends State<UserProfilePage> {
  ChatUser? _u;
  Object? _error;
  bool _busy = false;

  ChatStore get store => ChatStore.instance;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final u = await store.api.user(widget.userId);
      store.users[u.id] = u;
      if (mounted) setState(() => _u = u);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  ChatInfo? get _privateChat {
    for (final c in store.chats.values) {
      if (c.isPrivate && c.peer?.id == widget.userId) return c;
    }
    return null;
  }

  Future<void> _act(Future<void> Function() f, String done) async {
    setState(() => _busy = true);
    try {
      await f();
      await _load();
      if (mounted && done.isNotEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(done)));
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _editAlias(ChatUser u) async {
    final c = TextEditingController(text: u.contactAlias);
    final r = await showDialog<String>(
      context: context,
      builder: (ctx) => SzDialog(
        title: const Text('备注名'),
        content: TextField(controller: c, maxLength: 40, autofocus: true,
            decoration: InputDecoration(hintText: u.name)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('保存')),
        ],
      ),
    );
    c.dispose();
    if (r == null) return;
    await _act(() => store.api.addContact(u.id, alias: r), '');
    await store.refresh();
  }

  /// 把机器人拉进一个我能邀请人的群
  Future<void> _addBotToGroup(ChatUser bot) async {
    final groups = [for (final c in store.sortedChats()) if (c.isGroup && c.can('invite_users')) c];
    if (groups.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('你还没有能拉人进来的群')));
      return;
    }
    final pick = await szShowSheet<ChatInfo>(
      context: context,
      builder: (ctx) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(ctx).height * .6),
          child: ListView(shrinkWrap: true, children: [
            ListTile(title: Text('把 ${bot.displayName} 加到', style: const TextStyle(fontWeight: FontWeight.w600))),
            for (final g in groups)
              ListTile(
                leading: ChatAvatar(name: g.title, url: g.photo, size: 36),
                title: Text(g.title),
                onTap: () => Navigator.pop(ctx, g),
              ),
          ]),
        ),
      ),
    );
    if (pick == null || !mounted) return;
    await _act(() => store.api.addMembers(pick.id, [bot.id]), '已加到「${pick.title}」');
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final u = _u;
    if (u == null) {
      return SzPageScaffold(
        appBar: AppBar(),
        body: _error != null
            ? SzError(error: _error, onRetry: () {
                setState(() => _error = null);
                _load();
              })
            : const Center(child: CircularProgressIndicator()),
      );
    }
    final chat = _privateChat;
    final link = u.username != null ? 'https://chaojizan.cc/@${u.username}' : null;
    return SzPageScaffold(
      appBar: AppBar(
        actions: [
          if (!u.isSelf)
            PopupMenuButton<String>(
              onSelected: (v) async {
                switch (v) {
                  case 'alias':
                    await _editAlias(u);
                  case 'share':
                    if (link != null) await SharePlus.instance.share(ShareParams(text: '${u.displayName} $link'));
                  case 'block':
                    await _act(() => u.blocked ? store.api.unblock(u.id) : store.api.block(u.id),
                        u.blocked ? '已解除拉黑' : '已拉黑');
                  case 'report':
                    await reportUser(context, u.id);
                }
              },
              itemBuilder: (_) => [
                if (u.isContact) const PopupMenuItem(value: 'alias', child: Text('改备注名')),
                if (link != null) const PopupMenuItem(value: 'share', child: Text('分享名片')),
                PopupMenuItem(value: 'block', child: Text(u.blocked ? '解除拉黑' : '拉黑')),
                const PopupMenuItem(value: 'report', child: Text('举报')),
              ],
            ),
        ],
      ),
      body: ListView(children: [
        const SizedBox(height: 8),
        Center(child: ChatAvatar(name: u.displayName, url: u.avatar, size: 96, online: u.lastSeen.online)),
        const SizedBox(height: 12),
        Center(
          child: Text(u.displayName,
              style: const TextStyle(fontSize: kFontLead, fontWeight: FontWeight.w700)),
        ),
        if (u.contactAlias.isNotEmpty)
          Center(child: Text(u.name, style: TextStyle(color: sz.inkMuted))),
        const SizedBox(height: 4),
        Center(
          child: Text(u.isBot ? '机器人' : u.lastSeen.label(),
              style: TextStyle(color: u.lastSeen.online ? sz.clay : sz.inkMuted, fontSize: kFontNote)),
        ),
        const SizedBox(height: 16),
        if (!u.isSelf)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: kPagePad),
            child: Row(children: [
              Expanded(
                child: _ActionButton(
                  icon: Icons.chat_bubble_outline,
                  label: '发消息',
                  onTap: u.blocked
                      ? null
                      : () async {
                          if (widget.fromChat) {
                            Navigator.of(context).pop();
                          } else {
                            await openPrivateWith(context, u.id);
                          }
                        },
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: u.isBot
                    // 机器人不进通讯录;它的第二个按钮是「添加到群组」(Telegram 的 Add to Group)
                    ? _ActionButton(icon: Icons.group_add_outlined, label: '添加到群组', onTap: _busy ? null : () => _addBotToGroup(u))
                    : _ActionButton(
                        icon: u.isContact ? Icons.person_remove_outlined : Icons.person_add_alt_1_outlined,
                        label: u.isContact ? '删除联系人' : '加为联系人',
                        onTap: _busy
                            ? null
                            : () => _act(
                                () => u.isContact ? store.api.removeContact(u.id) : store.api.addContact(u.id).then((_) {}),
                                u.isContact ? '已从联系人删除' : '已加为联系人'),
                      ),
              ),
            ]),
          ),
        const SizedBox(height: 12),
        if (u.blocked)
          Container(
            margin: const EdgeInsets.symmetric(horizontal: kPagePad, vertical: 4),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: sz.danger.withValues(alpha: .08), borderRadius: BorderRadius.circular(kRadiusMd)),
            child: Text('你已拉黑对方:他不能给你发消息、拉你进群、看你的在线状态。',
                style: TextStyle(color: sz.danger, fontSize: kFontNote)),
          ),
        if (u.username != null)
          ListTile(
            leading: const Icon(Icons.alternate_email),
            title: Text('@${u.username}'),
            subtitle: const Text('用户名'),
            onTap: () async {
              await Clipboard.setData(ClipboardData(text: '@${u.username}'));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制')));
              }
            },
          ),
        if (u.bio.isNotEmpty)
          ListTile(leading: const Icon(Icons.info_outline), title: Text(u.bio), subtitle: const Text('签名')),
        if (chat != null)
          ListTile(
            leading: const Icon(Icons.perm_media_outlined),
            title: const Text('图片、文件和链接'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context)
                .push(MaterialPageRoute<void>(builder: (_) => SharedMediaPage(chatId: chat.id))),
          ),
        if (chat != null && !u.isSelf)
          ListTile(
            leading: Icon(chat.my.muted ? Icons.notifications_off_outlined : Icons.notifications_outlined),
            title: Text(chat.my.muted ? '已免打扰' : '消息通知'),
            trailing: Switch(
              value: !chat.my.muted,
              onChanged: (on) async {
                final until = on ? null : await pickMuteUntil(context);
                if (!on && until == null) return;
                final n = await store.api.patchDialog(chat.id, {'muted_until': until?.toUtc().toIso8601String()});
                store.putChat(n);
                if (mounted) setState(() {});
              },
            ),
          ),
      ]),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({required this.icon, required this.label, required this.onTap});

  final IconData icon;
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Material(
      color: sz.surface,
      borderRadius: BorderRadius.circular(kRadiusMd),
      child: InkWell(
        borderRadius: BorderRadius.circular(kRadiusMd),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
              border: Border.all(color: sz.line), borderRadius: BorderRadius.circular(kRadiusMd)),
          child: Column(children: [
            Icon(icon, color: onTap == null ? sz.inkFaint : sz.clay),
            const SizedBox(height: 4),
            Text(label, style: TextStyle(fontSize: kFontNote, color: onTap == null ? sz.inkFaint : sz.ink)),
          ]),
        ),
      ),
    );
  }
}
