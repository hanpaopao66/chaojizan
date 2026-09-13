import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../store.dart';

/// 会话分组(Telegram 的 Chat Folders):最多 10 个;每个分组按类型包含,可以另外指定会话。
class FoldersPage extends StatefulWidget {
  const FoldersPage({super.key});

  @override
  State<FoldersPage> createState() => _FoldersPageState();
}

class _FoldersPageState extends State<FoldersPage> {
  late final List<ChatFolder> _items = [...ChatStore.instance.folders];
  bool _dirty = false;

  static const _presets = <(String, List<String>, bool)>[
    ('私聊', ['private'], false),
    ('群组', ['group'], false),
    ('频道', ['channel'], false),
    ('未读', ['private', 'group', 'channel', 'bot'], true),
  ];

  Future<void> _save() async {
    try {
      final r = await ChatStore.instance.api.saveFolders(_items);
      ChatStore.instance.folders = r;
      ChatStore.instance.notifyListeners();
      if (mounted) Navigator.pop(context);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _edit([int? index]) async {
    final f = index == null ? null : _items[index];
    final r = await Navigator.of(context).push<ChatFolder>(
        MaterialPageRoute(builder: (_) => _FolderEditPage(folder: f)));
    if (r == null) return;
    setState(() {
      if (index == null) {
        _items.add(r);
      } else {
        _items[index] = r;
      }
      _dirty = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final existing = {for (final f in _items) f.title};
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('会话分组'),
        actions: [TextButton(onPressed: _dirty ? _save : null, child: const Text('保存'))],
      ),
      body: ListView(children: [
        Padding(
          padding: const EdgeInsets.all(kPagePad),
          child: Text('分组会出现在「消息」顶部,点一下只看这一类会话。拖动右边的把手调整顺序。',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
        ReorderableListView(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          onReorderItem: (a, b) => setState(() {
            _items.insert(b, _items.removeAt(a));
            _dirty = true;
          }),
          children: [
            for (var i = 0; i < _items.length; i++)
              ListTile(
                key: ValueKey('f$i${_items[i].title}'),
                leading: const Icon(Icons.folder_outlined),
                title: Text(_items[i].title),
                onTap: () => _edit(i),
                trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                  IconButton(
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () => setState(() {
                      _items.removeAt(i);
                      _dirty = true;
                    }),
                  ),
                  const Icon(Icons.drag_handle),
                ]),
              ),
          ],
        ),
        if (_items.length < 10)
          ListTile(
            leading: Icon(Icons.create_new_folder_outlined, color: sz.clay),
            title: Text('新建分组', style: TextStyle(color: sz.clay)),
            onTap: () => _edit(),
          ),
        if (_items.length < 10) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 16, kPagePad, 4),
            child: Text('推荐', style: TextStyle(color: sz.clay, fontWeight: FontWeight.w600)),
          ),
          for (final (title, types, unreadOnly) in _presets)
            if (!existing.contains(title))
              ListTile(
                title: Text(title),
                trailing: TextButton(
                  onPressed: () => setState(() {
                    _items.add(ChatFolder(title: title, rules: {
                      'types': types,
                      'exclude_read': unreadOnly,
                      'exclude_archived': true,
                    }));
                    _dirty = true;
                  }),
                  child: const Text('添加'),
                ),
              ),
        ],
      ]),
    );
  }
}

class _FolderEditPage extends StatefulWidget {
  const _FolderEditPage({this.folder});

  final ChatFolder? folder;

  @override
  State<_FolderEditPage> createState() => _FolderEditPageState();
}

class _FolderEditPageState extends State<_FolderEditPage> {
  late final _title = TextEditingController(text: widget.folder?.title ?? '');
  late final Set<String> _types = {
    for (final t in (widget.folder?.rules['types'] as List? ?? const [])) '$t'
  };
  late final Set<int> _include = {
    for (final i in (widget.folder?.rules['include'] as List? ?? const [])) (i as num).toInt()
  };
  late bool _excludeMuted = widget.folder?.rules['exclude_muted'] == true;
  late bool _excludeRead = widget.folder?.rules['exclude_read'] == true;

  static const _typeLabels = {
    'contacts': '联系人',
    'non_contacts': '非联系人',
    'private': '全部私聊',
    'group': '群组',
    'channel': '频道',
    'bot': '机器人',
  };

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final chats = ChatStore.instance.sortedChats();
    return SzPageScaffold(
      appBar: AppBar(
        title: Text(widget.folder == null ? '新建分组' : '编辑分组'),
        actions: [
          TextButton(
            onPressed: () {
              if (_title.text.trim().isEmpty || (_types.isEmpty && _include.isEmpty)) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('填个名字,并至少选一类会话或一个会话')));
                return;
              }
              Navigator.pop(
                  context,
                  ChatFolder(id: widget.folder?.id, title: _title.text.trim(), rules: {
                    'types': _types.toList(),
                    'include': _include.toList(),
                    'exclude': const <int>[],
                    'exclude_muted': _excludeMuted,
                    'exclude_read': _excludeRead,
                    'exclude_archived': true,
                  }));
            },
            child: const Text('完成'),
          ),
        ],
      ),
      body: ListView(children: [
        Padding(
          padding: const EdgeInsets.all(kPagePad),
          child: TextField(controller: _title, maxLength: 12, decoration: const InputDecoration(labelText: '分组名')),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 4),
          child: Text('包含', style: TextStyle(color: sz.clay, fontWeight: FontWeight.w600)),
        ),
        for (final e in _typeLabels.entries)
          CheckboxListTile(
            value: _types.contains(e.key),
            onChanged: (v) => setState(() => v == true ? _types.add(e.key) : _types.remove(e.key)),
            title: Text(e.value),
          ),
        SwitchListTile(value: _excludeMuted, onChanged: (v) => setState(() => _excludeMuted = v), title: const Text('不含免打扰的')),
        SwitchListTile(value: _excludeRead, onChanged: (v) => setState(() => _excludeRead = v), title: const Text('只看未读')),
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
          child: Text('另外加上这些会话', style: TextStyle(color: sz.clay, fontWeight: FontWeight.w600)),
        ),
        for (final c in chats)
          CheckboxListTile(
            value: _include.contains(c.id),
            onChanged: (v) => setState(() => v == true ? _include.add(c.id) : _include.remove(c.id)),
            title: Text(c.title),
          ),
      ]),
    );
  }
}
