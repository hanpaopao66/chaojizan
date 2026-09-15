import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../qr_login/qr_login.dart' show canScanHere;
import '../../qr_login/qr_scan_page.dart' show openQrScanner;
import '../chat_page.dart';
import '../links.dart';
import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';
import 'chat_settings_page.dart' show chatSettingsTitle;
import 'my_card_page.dart';
import 'pickers.dart';
import 'user_profile_page.dart';

/// 联系人列表(自己一个个加的,不上传通讯录 —— D2)。
class ContactsPage extends StatefulWidget {
  const ContactsPage({super.key});

  @override
  State<ContactsPage> createState() => _ContactsPageState();
}

class _ContactsPageState extends State<ContactsPage> {
  List<ChatUser>? _items;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await ChatStore.instance.api.contacts();
      if (mounted) setState(() => _items = r);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    final online = items?.where((u) => u.lastSeen.online).length ?? 0;
    return SzPageScaffold(
      appBar: AppBar(
        title: Text(items == null ? '联系人' : '联系人 ${items.length}${online > 0 ? ' · $online 人在线' : ''}'),
        actions: [
          IconButton(
            tooltip: '添加联系人',
            icon: const Icon(Icons.person_add_alt_1_outlined),
            onPressed: () async {
              await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const AddContactPage()));
              await _load();
            },
          ),
        ],
      ),
      body: items == null
          ? (_error != null ? SzError(error: _error, onRetry: _load) : const Center(child: CircularProgressIndicator()))
          : items.isEmpty
              ? SzRefreshableEmpty(
                  onRefresh: _load,
                  child: SzEmpty(
                    text: '还没有联系人\n用对方的超级赞号、手机号或名片二维码添加',
                    actionLabel: '添加联系人',
                    onAction: () => Navigator.of(context)
                        .push(MaterialPageRoute<void>(builder: (_) => const AddContactPage()))
                        .then((_) => _load()),
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView.separated(
                    itemCount: items.length,
                    separatorBuilder: (_, __) => Divider(height: 1, indent: 72, color: sz.line),
                    itemBuilder: (context, i) {
                      final u = items[i];
                      return ListTile(
                        leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 44, online: u.lastSeen.online),
                        title: Text(u.displayName),
                        subtitle: Text(u.lastSeen.label(),
                            style: TextStyle(fontSize: kFontNote, color: u.lastSeen.online ? sz.clay : sz.inkMuted)),
                        onTap: () => openPrivateWith(context, u.id),
                        onLongPress: () => openUserProfile(context, u.id),
                      );
                    },
                  ),
                ),
    );
  }
}

/// 添加联系人的输入框里是什么、按什么找。
enum ContactQueryKind { phone, username, publicId, link, invalid }

class ContactQuery {
  const ContactQuery(this.kind, this.value);

  final ContactQueryKind kind;

  /// phone:11 位号码;username:超级赞号(不带 @);publicId:名片编号;link:本站别的链接(邀请、视频);
  /// invalid:给人看的说明
  final String value;
}

/// 输 11 位手机号按手机号找,别的按超级赞号找;贴进来的本站名片链接当成号 / 名片编号。
/// 纯数字又不是 11 位的、不像超级赞号的,不发请求,直接说哪儿不对。
ContactQuery contactQueryOf(String raw) {
  final s = raw.trim();
  final compact = s.replaceAll(RegExp(r'[\s-]'), '');
  final phone = compact.startsWith('+86') ? compact.substring(3) : compact;
  if (RegExp(r'^1\d{10}$').hasMatch(phone)) return ContactQuery(ContactQueryKind.phone, phone);
  if (RegExp(r'^\+?\d+$').hasMatch(compact)) {
    return const ContactQuery(ContactQueryKind.invalid, '手机号要输完整的 11 位。超级赞号以字母开头,不会是纯数字');
  }
  if (s.contains('chaojizan.cc/')) {
    final url = s.startsWith('http') ? s : 'https://$s';
    final card = cardRefOf(url);
    if (card?.username != null) return ContactQuery(ContactQueryKind.username, card!.username!);
    if (card?.publicId != null) return ContactQuery(ContactQueryKind.publicId, card!.publicId!);
    return ContactQuery(ContactQueryKind.link, url);
  }
  final name = s.startsWith('@') ? s.substring(1) : s;
  if (RegExp(r'^[A-Za-z][A-Za-z0-9_]{4,31}$').hasMatch(name)) {
    return ContactQuery(ContactQueryKind.username, name);
  }
  return const ContactQuery(ContactQueryKind.invalid, '超级赞号是 5–32 位的英文字母、数字或下划线,以字母开头');
}

/// 添加联系人(D2):一个输入框,11 位手机号按手机号找(照旧受对方「按手机号找到我」约束),
/// 别的按超级赞号找(受对方「按超级赞号找到我」约束)。找到了在这一页摆出名片,点「添加到联系人」;
/// 找不到照实说为什么。和 Telegram 一样**直接加,不用对方同意**,也只加在自己这边。
class AddContactPage extends StatefulWidget {
  const AddContactPage({super.key});

  @override
  State<AddContactPage> createState() => _AddContactPageState();
}

class _AddContactPageState extends State<AddContactPage> {
  final _q = TextEditingController();
  bool _busy = false;

  /// 找到的人 / 公开群、频道 / 没找到时的说明,三者最多一个
  ChatUser? _user;
  Map<String, dynamic>? _chat;
  String? _miss;

  /// 没找到(404)时多给一句当面怎么加
  bool _missTip = false;
  String? _myUsername;

  ChatStore get _store => ChatStore.instance;

  @override
  void initState() {
    super.initState();
    _store.api.me().then((m) {
      if (mounted) setState(() => _myUsername = m['username'] as String?);
    }).catchError((_) {});
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  void _clear() {
    _user = null;
    _chat = null;
    _miss = null;
    _missTip = false;
  }

  Future<void> _find() async {
    final raw = _q.text.trim();
    if (raw.isEmpty || _busy) return;
    final q = contactQueryOf(raw);
    setState(_clear);
    switch (q.kind) {
      case ContactQueryKind.invalid:
        setState(() => _miss = q.value);
        return;
      case ContactQueryKind.link:
        // 邀请链接、视频这些站内链接照旧在 App 里打开
        final ok = await openAppLink(context, Uri.parse(q.value));
        if (!ok && mounted) setState(() => _miss = '认不出这个链接');
        return;
      case ContactQueryKind.phone:
      case ContactQueryKind.username:
      case ContactQueryKind.publicId:
        break;
    }
    setState(() => _busy = true);
    try {
      if (q.kind == ContactQueryKind.phone) {
        final u = await _store.api.findByPhone(q.value);
        if (mounted) setState(() => _user = u);
      } else if (q.kind == ContactQueryKind.publicId) {
        final u = await _store.api.resolvePublicId(q.value);
        if (mounted) setState(() => _user = u);
      } else {
        final r = await _store.api.resolve(q.value);
        if (!mounted) return;
        setState(() {
          if (r['type'] == 'user') {
            _user = ChatUser.fromJson(r['user']);
          } else {
            _chat = (r['chat'] as Map).cast<String, dynamic>();
          }
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _miss = e.message;
          _missTip = e.statusCode == 404;
        });
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _add(ChatUser u) async {
    setState(() => _busy = true);
    try {
      final n = await _store.api.addContact(u.id);
      _store.users[n.id] = n;
      if (!mounted) return;
      setState(() => _user = n);
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已添加到联系人')));
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  BoxDecoration _cardBox(SzColors sz) => BoxDecoration(
      color: sz.surface, border: Border.all(color: sz.line), borderRadius: BorderRadius.circular(kRadiusMd));

  Widget _userCard(ChatUser u) {
    final sz = Theme.of(context).sz;
    final Widget action;
    if (u.isSelf) {
      action = Text('这是你自己', textAlign: TextAlign.center, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted));
    } else if (u.isBot) {
      // 机器人不进通讯录(和资料页一样),点进去再说
      action = OutlinedButton(onPressed: () => openUserProfile(context, u.id), child: const Text('查看机器人'));
    } else if (u.isContact) {
      action = Row(children: [
        Expanded(
          child: Text('已在你的联系人里', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
        FilledButton(onPressed: () => openPrivateWith(context, u.id), child: const Text('发消息')),
      ]);
    } else {
      action = FilledButton(onPressed: _busy ? null : () => _add(u), child: const Text('添加到联系人'));
    }
    return Container(
      padding: const EdgeInsets.all(kCardPad),
      decoration: _cardBox(sz),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        InkWell(
          onTap: () => openUserProfile(context, u.id),
          child: Row(children: [
            ChatAvatar(name: u.displayName, url: u.avatar, size: 52),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(u.displayName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
                const SizedBox(height: 2),
                Text(u.username != null ? '超级赞号:@${u.username}' : '没有设超级赞号',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                if (u.bio.isNotEmpty)
                  Text(u.bio,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
            ),
            Icon(Icons.chevron_right, size: 18, color: sz.inkFaint),
          ]),
        ),
        const SizedBox(height: 12),
        action,
      ]),
    );
  }

  Widget _chatCard(Map<String, dynamic> c) {
    final sz = Theme.of(context).sz;
    final channel = c['type'] == 'channel';
    return Container(
      padding: const EdgeInsets.all(kCardPad),
      decoration: _cardBox(sz),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          ChatAvatar(name: '${c['title'] ?? ''}', url: '${c['photo'] ?? ''}', size: 52),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${c['title'] ?? ''}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
              const SizedBox(height: 2),
              Text('${channel ? '公开频道' : '公开群'} · ${c['member_count'] ?? 0} 人',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ]),
          ),
        ]),
        const SizedBox(height: 12),
        FilledButton(onPressed: () => openPublicChat(context, c), child: const Text('查看')),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('添加联系人')),
      body: ListView(padding: const EdgeInsets.all(kPagePad), children: [
        TextField(
          controller: _q,
          autofocus: true,
          textInputAction: TextInputAction.search,
          onSubmitted: (_) => _find(),
          // 改了输入,上一次的结果就不对应了
          onChanged: (_) {
            if (_user != null || _chat != null || _miss != null) setState(_clear);
          },
          decoration: InputDecoration(
            labelText: '超级赞号或手机号',
            hintText: '比如 xiaowang_01 或 13800000000',
            suffixIcon: IconButton(
              tooltip: '查找',
              icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.search),
              onPressed: _busy ? null : _find,
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text(
            '输入 11 位手机号按手机号找(每天 20 次),别的按超级赞号找;对方可以在隐私设置里关掉这两种找法。'
            '加联系人不用对方同意,只加在你这边。我们不会上传你的通讯录。',
            style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5)),
        const SizedBox(height: 16),
        if (_user != null) _userCard(_user!),
        if (_chat != null) _chatCard(_chat!),
        if (_miss != null)
          Container(
            padding: const EdgeInsets.all(kCardPad),
            decoration: BoxDecoration(color: sz.surfaceAlt, borderRadius: BorderRadius.circular(kRadiusMd)),
            child: Text(
              !_missTip
                  ? _miss!
                  // 网页版、电脑版没有「扫一扫」(只有手机 App 有),别让人去找一个不存在的按钮
                  : canScanHere
                      ? '$_miss\n当面加的话,请对方打开「${chatSettingsTitle()} → 我的名片」,你用「扫一扫」扫他的码。'
                      : '$_miss\n也可以请对方打开「${chatSettingsTitle()} → 我的名片」,把名片链接发给你。',
              style: TextStyle(fontSize: kFontBody, color: sz.ink, height: 1.6),
            ),
          ),
        const SizedBox(height: 16),
        SzEntryGroup(children: [
          if (canScanHere)
            SzEntryTile(
              title: '扫一扫',
              icon: Icons.qr_code_scanner,
              hint: '扫对方的名片二维码',
              onTap: () => openQrScanner(context, _store.client),
            ),
          SzEntryTile(
            title: '我的名片',
            icon: Icons.qr_code_2,
            value: _myUsername != null ? '@$_myUsername' : null,
            hint: '二维码和链接,发给别人加你',
            onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const MyCardPage())),
          ),
        ]),
      ]),
    );
  }
}
