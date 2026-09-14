import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../chat_page.dart';
import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';
import '../ui/format.dart';
import 'pickers.dart';
import 'user_profile_page.dart';

/// 全局搜索:会话、人(联系人和公开用户名)、公开群 / 频道、消息正文(只搜我能读的)。
class ChatSearchPage extends StatefulWidget {
  const ChatSearchPage({super.key});

  @override
  State<ChatSearchPage> createState() => _ChatSearchPageState();
}

class _ChatSearchPageState extends State<ChatSearchPage> {
  final _q = TextEditingController();
  Timer? _debounce;
  bool _loading = false;
  List<Map<String, dynamic>> _chats = [];
  List<ChatUser> _users = [];
  List<Map<String, dynamic>> _messages = [];
  String _searched = '';

  @override
  void dispose() {
    _debounce?.cancel();
    _q.dispose();
    super.dispose();
  }

  void _onChanged(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () => _run(v.trim()));
  }

  Future<void> _run(String q) async {
    if (q.isEmpty) {
      setState(() {
        _chats = [];
        _users = [];
        _messages = [];
        _searched = '';
      });
      return;
    }
    setState(() => _loading = true);
    try {
      final r = await ChatStore.instance.api.search(q);
      if (!mounted || _q.text.trim() != q) return;
      setState(() {
        _chats = [for (final c in (r['chats'] as List? ?? const [])) (c as Map).cast<String, dynamic>()];
        _users = [for (final u in (r['users'] as List? ?? const [])) ChatUser.fromJson(u)];
        _messages = [for (final m in (r['messages'] as List? ?? const [])) (m as Map).cast<String, dynamic>()];
        _searched = q;
      });
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _header(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
        child: Text(t, style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600, color: Theme.of(context).sz.clay)),
      );

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final store = ChatStore.instance;
    // 本地先筛一遍会话标题:打字的时候就有结果,不等接口
    final q = _q.text.trim();
    final local = q.isEmpty
        ? const <ChatInfo>[]
        : [...store.sortedChats(), ...store.sortedChats(archived: true)].where((c) => c.title.contains(q)).take(8).toList();
    final localIds = {for (final c in local) c.id};
    final remoteChats = _chats.where((c) => !localIds.contains((c['id'] as num).toInt())).toList();
    final empty = _searched.isNotEmpty && local.isEmpty && remoteChats.isEmpty && _users.isEmpty && _messages.isEmpty;
    return SzPageScaffold(
      appBar: AppBar(
        title: TextField(
          controller: _q,
          autofocus: true,
          textInputAction: TextInputAction.search,
          onChanged: (v) {
            setState(() {});
            _onChanged(v);
          },
          decoration: const InputDecoration(hintText: '搜索会话、联系人、超级赞号、消息', border: InputBorder.none),
        ),
        actions: [
          if (_loading) const Padding(padding: EdgeInsets.all(16), child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))),
          // 一键清空,接着搜别的(手机上删一长串字很费事)
          if (!_loading && _q.text.isNotEmpty)
            IconButton(
              tooltip: '清空',
              icon: const Icon(Icons.close),
              onPressed: () {
                _q.clear();
                setState(() {});
                _onChanged('');
              },
            ),
        ],
      ),
      body: ListView(children: [
        if (local.isNotEmpty || remoteChats.isNotEmpty) _header('会话'),
        for (final c in local)
          ListTile(
            leading: ChatAvatar(name: c.title, url: c.photo, size: 44, saved: c.isSaved),
            title: Text(c.title),
            subtitle: Text(c.isGroup ? '${c.memberCount} 位成员' : (c.isChannel ? '${c.memberCount} 位订阅者' : '')),
            onTap: () => openChat(context, c.id),
          ),
        for (final c in remoteChats)
          ListTile(
            leading: ChatAvatar(name: '${c['title']}', url: '${c['photo'] ?? ''}', size: 44),
            title: Text('${c['title']}'),
            subtitle: Text(c['username'] != null ? '@${c['username']} · ${c['member_count']} 人' : '${c['member_count']} 人'),
            onTap: () => c.containsKey('is_member')
                ? openPublicChat(context, c)
                : openChat(context, (c['id'] as num).toInt()),
          ),
        if (_users.isNotEmpty) _header('人'),
        for (final u in _users)
          ListTile(
            leading: ChatAvatar(name: u.displayName, url: u.avatar, size: 44, online: u.lastSeen.online),
            title: Text(u.displayName),
            subtitle: Text(u.username != null ? '@${u.username}' : u.lastSeen.label()),
            onTap: () => openUserProfile(context, u.id),
          ),
        if (_messages.isNotEmpty) _header('消息'),
        for (final row in _messages)
          Builder(builder: (context) {
            final chat = (row['chat'] as Map).cast<String, dynamic>();
            final m = ChatMessage.fromJson(row['message']);
            return ListTile(
              leading: ChatAvatar(name: '${chat['title']}', url: '${chat['photo'] ?? ''}', size: 44),
              title: Row(children: [
                Expanded(child: Text('${chat['title']}', maxLines: 1, overflow: TextOverflow.ellipsis)),
                Text(listTime(m.createdAt), style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
              subtitle: Text('${ChatStore.instance.nameOf(m.sender)}: ${previewOf(m)}', maxLines: 2, overflow: TextOverflow.ellipsis),
              onTap: () => openChat(context, (chat['id'] as num).toInt(), jumpTo: m.seq),
            );
          }),
        if (empty)
          Padding(
            padding: const EdgeInsets.all(40),
            child: Center(child: Text('没有找到「$_searched」', style: TextStyle(color: sz.inkMuted))),
          ),
      ]),
    );
  }
}
