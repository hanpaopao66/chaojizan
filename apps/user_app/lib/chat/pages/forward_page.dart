import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';

/// 选转发到哪些会话(最多 10 个,§5.7)。返回会话 id;取消返回 null。
Future<List<int>?> pickForwardTargets(BuildContext context, {String title = '转发到'}) =>
    Navigator.of(context).push<List<int>>(
        MaterialPageRoute(builder: (_) => _ForwardPage(title: title)));

class _ForwardPage extends StatefulWidget {
  const _ForwardPage({required this.title});

  final String title;

  @override
  State<_ForwardPage> createState() => _ForwardPageState();
}

class _ForwardPageState extends State<_ForwardPage> {
  final Set<int> _picked = {};
  String _q = '';
  ChatInfo? _saved;

  ChatStore get store => ChatStore.instance;

  @override
  void initState() {
    super.initState();
    store.openSaved().then((c) {
      if (mounted) setState(() => _saved = c);
    }).catchError((_) {});
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final all = [
      if (_saved != null) _saved!,
      ...store.sortedChats().where((c) => !c.isSaved),
      ...store.sortedChats(archived: true),
    ].where((c) => c.can('send_messages')).where((c) => _q.isEmpty || c.title.contains(_q)).toList();
    return SzPageScaffold(
      appBar: AppBar(
        title: Text(_picked.isEmpty ? widget.title : '已选 ${_picked.length} 个'),
        actions: [
          TextButton(
            onPressed: _picked.isEmpty ? null : () => Navigator.pop(context, _picked.toList()),
            child: const Text('发送'),
          ),
        ],
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 8),
          child: TextField(
            decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: '搜索会话', isDense: true),
            onChanged: (v) => setState(() => _q = v.trim()),
          ),
        ),
        Expanded(
          child: ListView.builder(
            itemCount: all.length,
            itemBuilder: (context, i) {
              final c = all[i];
              final on = _picked.contains(c.id);
              return ListTile(
                leading: ChatAvatar(name: c.title, url: c.photo, size: 40, saved: c.isSaved),
                title: Text(c.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(c.isGroup
                    ? '${c.memberCount} 位成员'
                    : (c.isChannel ? '频道' : (c.isSaved ? '转给自己' : '私聊'))),
                trailing: Icon(on ? Icons.check_circle : Icons.radio_button_unchecked,
                    color: on ? sz.clay : sz.inkFaint),
                onTap: () => setState(() {
                  if (on) {
                    _picked.remove(c.id);
                  } else if (_picked.length < 10) {
                    _picked.add(c.id);
                  } else {
                    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('一次最多转发到 10 个会话')));
                  }
                }),
              );
            },
          ),
        ),
      ]),
    );
  }
}
