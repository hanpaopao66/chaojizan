import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import '../chat_page.dart';
import '../links.dart';
import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';
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
              ? Center(
                  child: SzEmpty(
                    text: '还没有联系人\n用对方的用户名、手机号或名片二维码添加',
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

/// 添加联系人:@用户名、完整手机号、我的名片二维码(D2)。
class AddContactPage extends StatefulWidget {
  const AddContactPage({super.key});

  @override
  State<AddContactPage> createState() => _AddContactPageState();
}

class _AddContactPageState extends State<AddContactPage> {
  final _q = TextEditingController();
  bool _busy = false;
  String? _myLink;
  String? _myName;

  @override
  void initState() {
    super.initState();
    ChatStore.instance.api.me().then((m) {
      if (mounted) {
        setState(() {
          _myLink = '${m['link'] ?? ''}';
          _myName = '${m['name'] ?? ''}';
        });
      }
    }).catchError((_) {});
  }

  @override
  void dispose() {
    _q.dispose();
    super.dispose();
  }

  Future<void> _find() async {
    final raw = _q.text.trim();
    if (raw.isEmpty) return;
    setState(() => _busy = true);
    final store = ChatStore.instance;
    try {
      final digits = raw.replaceAll(RegExp(r'[\s-]'), '');
      if (RegExp(r'^1\d{10}$').hasMatch(digits)) {
        final u = await store.api.findByPhone(digits);
        if (mounted) await _show(u);
      } else if (raw.contains('chaojizan.cc/')) {
        // 站内链接:名片、@用户名、邀请链接都认
        final uri = Uri.tryParse(raw.startsWith('http') ? raw : 'https://$raw');
        if (uri != null && mounted && !await openAppLink(context, uri) && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('认不出这个链接')));
        }
      } else {
        if (mounted) await openUsername(context, raw.replaceFirst('@', ''));
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _show(ChatUser u) => openUserProfile(context, u.id);

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
          decoration: InputDecoration(
            labelText: '用户名、手机号或名片链接',
            hintText: '@xiaowang 或 13800000000',
            suffixIcon: IconButton(
              icon: _busy ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.search),
              onPressed: _busy ? null : _find,
            ),
          ),
        ),
        const SizedBox(height: 8),
        Text('按手机号只能精确找完整号码,每天 20 次;对方可以在隐私设置里关掉。我们不会上传你的通讯录。',
            style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        const SizedBox(height: 28),
        if (_myLink != null && _myLink!.isNotEmpty) ...[
          Center(child: Text('我的名片', style: TextStyle(color: sz.inkMuted))),
          const SizedBox(height: 10),
          Center(
            child: Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(kRadiusMd)),
              child: QrImageView(data: _myLink!, size: 180),
            ),
          ),
          const SizedBox(height: 8),
          Center(child: Text(_myName ?? '', style: const TextStyle(fontWeight: FontWeight.w600))),
          Center(child: SelectableText(_myLink!, style: TextStyle(color: sz.link, fontSize: kFontNote))),
          const SizedBox(height: 8),
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            TextButton.icon(
              icon: const Icon(Icons.copy, size: 18),
              label: const Text('复制链接'),
              onPressed: () async {
                await Clipboard.setData(ClipboardData(text: _myLink!));
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制')));
                }
              },
            ),
            TextButton.icon(
              icon: const Icon(Icons.share_outlined, size: 18),
              label: const Text('分享'),
              onPressed: () => SharePlus.instance.share(ShareParams(text: '在超级赞上加我:$_myLink')),
            ),
          ]),
        ],
      ]),
    );
  }
}
