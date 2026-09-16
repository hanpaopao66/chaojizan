import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../music/nav.dart' as music;
import '../../video/nav.dart' show openUpSpace;

import '../calls/call_controller.dart';
import '../chat_page.dart';
import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';
import '../ui/tags_badges.dart';
import 'pickers.dart';
import 'shared_media_page.dart';
import 'tags_badges_page.dart';

/// 打开某人的资料页。
Future<void> openUserProfile(BuildContext context, int userId, {bool fromChat = false}) =>
    Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => UserProfilePage(userId: userId, fromChat: fromChat)));

/// 一个人的资料(Telegram 的用户资料页):头像、名字、@超级赞号、签名、最后上线;
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

  /// `GET /social/v1/users/{id}/follow-stats`:`{fans, following, followed, follows_you}`
  Map<String, dynamic>? _follow;

  /// 这个人的音乐人主页(不是音乐人就是 null)。关注是全站一张表,所以三个板块的入口都摆在这一页
  Map<String, dynamic>? _artist;

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
    await _loadFollow();
    await _loadArtist();
  }

  /// 是不是音乐人:不是就 404(接口关着、老服务端也当不是),这一行不显示
  Future<void> _loadArtist() async {
    try {
      final a = await music.musicApi.artistOfUser(widget.userId);
      if (mounted && a != null) setState(() => _artist = a);
    } catch (_) {
      // 音乐没开、老服务端:不显示这个入口
    }
  }

  /// 关注关系是全站一张表(#377):这里读到的粉丝数、关注数,和视频、动态、音乐里看到的是同一份。
  /// 接口挂在 /social/v1 下、不受各模块开关影响;拉不到就不显示这一行,不挡资料页。
  Future<void> _loadFollow() async {
    try {
      final r = await store.api.api.requestJson('GET', '/social/v1/users/${widget.userId}/follow-stats');
      if (mounted && r is Map) setState(() => _follow = r.cast<String, dynamic>());
    } catch (_) {
      // 没登录、老服务端:这一行不显示
    }
  }

  Future<void> _toggleFollow() async {
    final cur = _follow?['followed'] == true;
    setState(() => _busy = true);
    try {
      final r = await store.api.api
          .requestJson(cur ? 'DELETE' : 'POST', '/social/v1/users/${widget.userId}/follow');
      if (r is Map) {
        final m = r.cast<String, dynamic>();
        setState(() => _follow = {...?_follow, 'followed': m['followed'] == true, 'fans': m['fans']});
      }
      if (mounted && !cur) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('已关注:他的视频、动态和歌都会出现在你的关注里')));
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
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
      builder: (ctx) => SzDisposeWith(
        controllers: [c],
        child: SzDialog(
          title: const Text('备注名'),
          content: TextField(controller: c, maxLength: 40, autofocus: true,
              decoration: InputDecoration(hintText: u.name)),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
            FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('保存')),
          ],
        ),
      ),
    );
    if (r == null) return;
    await _act(() => store.api.addContact(u.id, alias: r), '');
    await store.refresh();
  }

  /// 把机器人拉进一个我能邀请人的群
  Future<void> _call(ChatUser u, {required bool video}) async {
    if (!await PermissionRationale.ensureCall(context, video: video)) return;
    final ok = await CallController.instance.start(u.id, u.displayName, u.avatar, video: video);
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('正在通话中,先挂掉这一通')));
    }
  }

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
    // 分享别人的名片用名片编号(/u/…),不用 @超级赞号:对方关了「按超级赞号找到我」时 @ 链接打不开,
    // 而且超级赞号一年能改一次、换下来的号冷冻期过后会归别人,编号链接一直指着这个人
    final link = u.publicId != null
        ? 'https://chaojizan.cc/u/${u.publicId}'
        : (u.username != null ? 'https://chaojizan.cc/@${u.username}' : null);
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
        // 关注 / 粉丝:全站一张表,视频、动态、音乐是同一份(#377)
        if (_follow != null && !u.isBot) ...[
          const SizedBox(height: 8),
          Center(
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              _FollowCount(label: '关注', value: vCount(_follow!['following'])),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14),
                child: Container(width: 1, height: 18, color: sz.line),
              ),
              _FollowCount(label: '粉丝', value: vCount(_follow!['fans'])),
            ]),
          ),
          if (_follow!['follows_you'] == true && !u.isSelf)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Center(
                child: Text('他关注了你', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ),
            ),
        ],
        // 勋章和标签(别人隐藏了的服务端就不给;自己看自己时隐藏的也在,标着「已隐藏」)
        if (!u.tagsBadges.isEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 10, kPagePad, 0),
            child: TagsBadgesView(
              data: u.tagsBadges,
              center: true,
              onEditTags: u.isSelf
                  ? () async {
                      await Navigator.of(context)
                          .push(MaterialPageRoute<void>(builder: (_) => const TagsBadgesPage()));
                      await _load();
                    }
                  : null,
            ),
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
              // 关注:一次关注,他的视频、动态、歌都跟着来(#377)。机器人不关注,拉黑了也不给关注
              if (!u.isBot && !u.blocked && _follow != null) ...[
                const SizedBox(width: 10),
                Expanded(
                  child: _ActionButton(
                    icon: _follow!['followed'] == true ? Icons.how_to_reg_outlined : Icons.person_add_outlined,
                    label: _follow!['followed'] == true ? '已关注' : '关注',
                    onTap: _busy ? null : _toggleFollow,
                  ),
                ),
              ],
              // 语音 / 视频通话(Telegram 的资料页也能直接打);机器人、拉黑了、通话没开放时不出
              if (!u.isBot && !u.blocked && RemoteCopy.feature('calls')) ...[
                const SizedBox(width: 10),
                Expanded(child: _ActionButton(icon: Icons.call_outlined, label: '语音', onTap: () => _call(u, video: false))),
                const SizedBox(width: 10),
                Expanded(child: _ActionButton(icon: Icons.videocam_outlined, label: '视频', onTap: () => _call(u, video: true))),
              ],
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
        // 他在别的板块的东西(#382 打通):关注一次,三处都跟着来
        if (!u.isSelf && !u.isBot) ...[
          const SizedBox(height: 4),
          SzEntryGroup(children: [
            SzEntryTile(
              icon: Icons.smart_display_outlined,
              title: '${u.displayName} 的视频',
              onTap: () => openUpSpace(context, u.id),
            ),
            if (_artist != null)
              SzEntryTile(
                icon: Icons.library_music_outlined,
                title: '${u.displayName} 的音乐',
                value: '音乐人 · ${_artist!['tracks'] ?? 0} 首歌',
                onTap: () => music.openArtist(context, '${_artist!['aid']}'),
              ),
          ]),
        ],
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
            subtitle: const Text('超级赞号'),
            onTap: () async {
              await Clipboard.setData(ClipboardData(text: '@${u.username}'));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制')));
              }
            },
          ),
        if (u.bio.isNotEmpty)
          // 机器人的这一行是开发者填的简介
          ListTile(leading: const Icon(Icons.info_outline), title: Text(u.bio), subtitle: Text(u.isBot ? '简介' : '签名')),
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
                final n = await store.api.patchDialog(chat.id, {'muted_until': muteParam(until)});
                store.putChat(n);
                if (mounted) setState(() {});
              },
            ),
          ),
      ]),
    );
  }
}

/// 关注 / 粉丝数:上面是数,下面是字。一万起写「1.2 万」,和视频、动态里一个口径
class _FollowCount extends StatelessWidget {
  const _FollowCount({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Text(value, style: szTabular(fontSize: kFontTitle, fontWeight: FontWeight.w700, color: sz.ink)),
      const SizedBox(height: 2),
      Text(label, style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
    ]);
  }
}

String vCount(Object? raw) {
  final n = raw is int ? raw : int.tryParse('${raw ?? 0}') ?? 0;
  if (n < 10000) return '$n';
  final w = n / 10000;
  return '${w >= 100 ? w.toStringAsFixed(0) : w.toStringAsFixed(1)} 万';
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
