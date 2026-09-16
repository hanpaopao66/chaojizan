import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../miniapp/container.dart' show openMiniApp;
import '../chat_page.dart';
import '../downloads.dart';
import '../models.dart';
import '../store.dart';
import '../ui/avatar.dart';
import '../ui/format.dart';
import '../ui/media_save.dart' show deleteDownloaded;
import 'pickers.dart';
import 'user_profile_page.dart';

/// 搜索页顶上那一排分类(对齐 Telegram)。
///
/// 第一格是「全部」—— Telegram 那里是「不选任何一格」,同一件事,
/// 但一排里有个明确选中的格子,比"哪个都没亮"更容易看懂现在在看什么。
///
/// 「下载内容」是**本机**的下载记录(chat/downloads.dart),不发请求:
/// 谁把哪个文件存进了自己手机,服务端不知道也不该知道。
const _tabs = <({String key, String label, IconData icon})>[
  (key: '', label: '全部', icon: Icons.search),
  (key: 'chats', label: '对话', icon: Icons.forum_outlined),
  (key: 'channels', label: '频道', icon: Icons.campaign_outlined),
  (key: 'apps', label: '应用', icon: Icons.apps_outlined),
  (key: 'media', label: '多媒体', icon: Icons.photo_library_outlined),
  (key: 'downloads', label: '下载内容', icon: Icons.download_outlined),
  (key: 'links', label: '链接', icon: Icons.link),
  (key: 'files', label: '文件', icon: Icons.insert_drive_file_outlined),
  (key: 'music', label: '音乐', icon: Icons.library_music_outlined),
  (key: 'voice', label: '语音', icon: Icons.mic_none),
];

/// 这几格不填关键词也有内容可看(点进「文件」就该看到全部文件)
const _browsable = {'media', 'downloads', 'links', 'files', 'music', 'voice'};

/// 全局搜索:会话、人(联系人和公开用户名)、公开群 / 频道、消息正文(只搜我能读的),
/// 以及顶上那一排分类。
class ChatSearchPage extends StatefulWidget {
  const ChatSearchPage({super.key});

  @override
  State<ChatSearchPage> createState() => _ChatSearchPageState();
}

class _ChatSearchPageState extends State<ChatSearchPage> {
  final _q = TextEditingController();
  final _scroll = ScrollController();
  Timer? _debounce;
  bool _loading = false;
  bool _more = false;
  int? _beforeId;
  String _tab = '';

  // 「全部」那一格的三坨(老形状)
  List<Map<String, dynamic>> _chats = [];
  List<ChatUser> _users = [];
  List<Map<String, dynamic>> _messages = [];

  /// 分类下的结果(每条自报 kind)
  List<Map<String, dynamic>> _items = [];
  String _searched = '';

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 400) _loadMore();
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _scroll.dispose();
    _q.dispose();
    super.dispose();
  }

  void _onChanged(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () => _run(v.trim()));
  }

  void _pick(String tab) {
    if (_tab == tab) return;
    setState(() {
      _tab = tab;
      _items = [];
      _beforeId = null;
      _more = false;
    });
    _run(_q.text.trim());
  }

  Future<void> _run(String q) async {
    if (_tab == 'downloads') {
      await Downloads.instance.load();
      if (mounted) setState(() => _searched = q);
      return;
    }
    // 不分类时没关键词就什么都不搜;分类里「可浏览」的那几格空着也有内容
    if (q.isEmpty && !_browsable.contains(_tab)) {
      setState(() {
        _chats = [];
        _users = [];
        _messages = [];
        _items = [];
        _searched = '';
      });
      return;
    }
    setState(() => _loading = true);
    try {
      if (_tab.isEmpty) {
        final r = await ChatStore.instance.api.search(q);
        if (!mounted || _q.text.trim() != q) return;
        setState(() {
          _chats = [
            for (final c in (r['chats'] as List? ?? const [])) (c as Map).cast<String, dynamic>()
          ];
          _users = [for (final u in (r['users'] as List? ?? const [])) ChatUser.fromJson(u)];
          _messages = [
            for (final m in (r['messages'] as List? ?? const [])) (m as Map).cast<String, dynamic>()
          ];
          _searched = q;
        });
      } else {
        final r = await ChatStore.instance.api.searchTab(_tab, q: q);
        if (!mounted || _q.text.trim() != q) return;
        setState(() {
          _items = r.items;
          _more = r.hasMore;
          _beforeId = r.nextBeforeId;
          _searched = q;
        });
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    if (_loading || !_more || _tab.isEmpty || _tab == 'downloads' || _beforeId == null) return;
    setState(() => _loading = true);
    try {
      final r = await ChatStore.instance.api
          .searchTab(_tab, q: _q.text.trim(), beforeId: _beforeId);
      if (!mounted) return;
      setState(() {
        _items = [..._items, ...r.items];
        _more = r.hasMore;
        _beforeId = r.nextBeforeId;
      });
    } on ApiException {
      // 翻页失败不弹错:上面那一页还在,下拉到底再试一次就是了
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Widget _header(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
        child: Text(t,
            style: TextStyle(
                fontSize: kFontNote,
                fontWeight: FontWeight.w600,
                color: Theme.of(context).sz.clay)),
      );

  Widget _filters() {
    final sz = Theme.of(context).sz;
    // 十格固定不变,**一次全建出来**:横向 ListView 是懒的,窄屏上后面几格
    // 要滚过去才存在 —— 那样「跳到某一格」(将来从别处带 tab 进来)和自动化点击都会落空,
    // 而十个 chip 的开销本来就可以忽略
    return SizedBox(
      height: 44,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: kPagePad, vertical: 4),
        child: Row(children: [
          for (final t in _tabs) ...[
            ChoiceChip(
              selected: _tab == t.key,
              onSelected: (_) => _pick(t.key),
              avatar: Icon(t.icon,
                  size: 16, color: _tab == t.key ? sz.paper : sz.inkMuted),
              label: Text(t.label),
              labelStyle:
                  TextStyle(fontSize: kFontNote, color: _tab == t.key ? sz.paper : sz.ink),
              selectedColor: sz.clay,
              showCheckmark: false,
            ),
            if (t.key != _tabs.last.key) const SizedBox(width: 8),
          ],
        ]),
      ),
    );
  }

  // ---------------- 各类结果 ----------------

  Widget _messageTile(Map<String, dynamic> row) {
    final sz = Theme.of(context).sz;
    final chat = (row['chat'] as Map).cast<String, dynamic>();
    final m = ChatMessage.fromJson(row['message']);
    final media = m.media.isNotEmpty ? m.media.first : null;
    final name = media?.name ?? '';
    return ListTile(
      leading: ChatAvatar(name: '${chat['title']}', url: '${chat['photo'] ?? ''}', size: 44),
      title: Row(children: [
        Expanded(
            child: Text(name.isNotEmpty ? name : '${chat['title']}',
                maxLines: 1, overflow: TextOverflow.ellipsis)),
        Text(listTime(m.createdAt), style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      ]),
      subtitle: Text(
          name.isNotEmpty
              ? '${chat['title']} · ${fileSize(media?.size ?? 0)}'
              : '${ChatStore.instance.nameOf(m.sender)}: ${previewOf(m)}',
          maxLines: 2,
          overflow: TextOverflow.ellipsis),
      onTap: () => openChat(context, (chat['id'] as num).toInt(), jumpTo: m.seq),
    );
  }

  Widget _appTile(Map<String, dynamic> a) {
    final isBot = a['kind'] == 'bot';
    final name = '${a['name'] ?? a['display_name'] ?? ''}';
    return ListTile(
      leading: ChatAvatar(name: name, url: '${a['icon'] ?? a['avatar'] ?? ''}', size: 44),
      title: Text(name),
      subtitle: Text(isBot
          ? (a['username'] != null ? '机器人 · @${a['username']}' : '机器人')
          : '小程序${a['developer'] != null && '${a['developer']}'.isNotEmpty ? ' · ${a['developer']}' : ''}'),
      onTap: () => isBot
          ? openUserProfile(context, (a['id'] as num).toInt())
          : openMiniApp(context, ChatStore.instance.api.api, appid: '${a['appid']}'),
    );
  }

  Widget _downloadTile(DownloadItem d) {
    final sz = Theme.of(context).sz;
    return ListTile(
      leading: CircleAvatar(
          backgroundColor: sz.clay.withValues(alpha: .12),
          child: Icon(_iconFor(d), color: sz.clay)),
      title: Text(d.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text([
        if (d.chatTitle.isNotEmpty) d.chatTitle,
        fileSize(d.size),
        listTime(d.at),
        if (!d.onThisDevice) '在浏览器的下载目录里',
      ].join(' · '), maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: IconButton(
        tooltip: '删除',
        icon: const Icon(Icons.close),
        onPressed: () => _removeDownload(d),
      ),
      onTap: d.chatId == 0 ? null : () => openChat(context, d.chatId),
    );
  }

  IconData _iconFor(DownloadItem d) => switch (d.kind) {
        'photo' => Icons.image_outlined,
        'video' || 'video_note' => Icons.movie_outlined,
        'gif' => Icons.gif_box_outlined,
        'voice' => Icons.mic_none,
        _ => d.mime.startsWith('audio/')
            ? Icons.library_music_outlined
            : Icons.insert_drive_file_outlined,
      };

  /// 删清单里那一行,再问要不要连本机那份文件一起删 —— 这两件事后果不一样:
  /// 清单删了还能再下一次,文件删了就没了,所以不合成一个动作
  Future<void> _removeDownload(DownloadItem d) async {
    final alsoFile = d.onThisDevice
        ? await showDialog<bool>(
            context: context,
            builder: (ctx) => SzDialog(
              title: const Text('从下载内容里移除'),
              content: Text('「${d.name}」已经存在这台设备上。要连这个文件一起删掉吗?'),
              actions: [
                TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
                TextButton(
                    onPressed: () => Navigator.pop(ctx, false), child: const Text('只从清单移除')),
                TextButton(
                    onPressed: () => Navigator.pop(ctx, true), child: const Text('连文件一起删')),
              ],
            ),
          )
        : false;
    if (alsoFile == null) return; // 取消
    await Downloads.instance.remove(d.mediaId);
    if (alsoFile) await deleteDownloaded(d.path);
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final store = ChatStore.instance;
    final q = _q.text.trim();
    // 「全部」里本地先筛一遍会话标题:打字的时候就有结果,不等接口
    final local = (_tab.isNotEmpty || q.isEmpty)
        ? const <ChatInfo>[]
        : [...store.sortedChats(), ...store.sortedChats(archived: true)]
            .where((c) => c.title.contains(q))
            .take(8)
            .toList();
    final localIds = {for (final c in local) c.id};
    final remoteChats =
        _chats.where((c) => !localIds.contains((c['id'] as num).toInt())).toList();
    final downloads = _tab == 'downloads'
        ? Downloads.instance.items
            .where((d) => q.isEmpty || d.name.toLowerCase().contains(q.toLowerCase()))
            .toList()
        : const <DownloadItem>[];
    final empty = _tab == 'downloads'
        ? downloads.isEmpty
        : _tab.isNotEmpty
            ? _items.isEmpty && !_loading && (q.isNotEmpty || _browsable.contains(_tab))
            : _searched.isNotEmpty &&
                local.isEmpty &&
                remoteChats.isEmpty &&
                _users.isEmpty &&
                _messages.isEmpty;
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
          decoration:
              const InputDecoration(hintText: '搜索会话、联系人、超级赞号、消息', border: InputBorder.none),
        ),
        actions: [
          if (_loading)
            const Padding(
                padding: EdgeInsets.all(16),
                child: SizedBox(
                    width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))),
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
        bottom: PreferredSize(preferredSize: const Size.fromHeight(44), child: _filters()),
      ),
      body: ListView(controller: _scroll, children: [
        if (_tab == 'downloads') ...[
          for (final d in downloads) _downloadTile(d),
          if (downloads.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 16),
              child: Text('只在这台设备上,不会同步到别的地方',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ),
        ] else if (_tab == 'apps')
          for (final a in _items) _appTile(a)
        else if (_tab == 'chats' || _tab == 'channels')
          for (final it in _items)
            if (it['kind'] == 'user')
              Builder(builder: (context) {
                final u = ChatUser.fromJson(it);
                return ListTile(
                  leading: ChatAvatar(
                      name: u.displayName, url: u.avatar, size: 44, online: u.lastSeen.online),
                  title: Text(u.displayName),
                  subtitle: Text(u.username != null ? '@${u.username}' : u.lastSeen.label()),
                  onTap: () => openUserProfile(context, u.id),
                );
              })
            else
              ListTile(
                leading: ChatAvatar(
                    name: '${it['title']}', url: '${it['photo'] ?? ''}', size: 44),
                title: Text('${it['title']}'),
                subtitle: Text(it['username'] != null
                    ? '@${it['username']} · ${it['member_count']} 人'
                    : '${it['member_count']} 人'),
                onTap: () => it.containsKey('is_member')
                    ? openPublicChat(context, it)
                    : openChat(context, (it['id'] as num).toInt()),
              )
        else if (_tab.isNotEmpty)
          for (final row in _items) _messageTile(row)
        else ...[
          if (local.isNotEmpty || remoteChats.isNotEmpty) _header('会话'),
          for (final c in local)
            ListTile(
              leading: ChatAvatar(name: c.title, url: c.photo, size: 44, saved: c.isSaved),
              title: Text(c.title),
              subtitle: Text(
                  c.isGroup ? '${c.memberCount} 位成员' : (c.isChannel ? '${c.memberCount} 位订阅者' : '')),
              onTap: () => openChat(context, c.id),
            ),
          for (final c in remoteChats)
            ListTile(
              leading: ChatAvatar(name: '${c['title']}', url: '${c['photo'] ?? ''}', size: 44),
              title: Text('${c['title']}'),
              subtitle: Text(c['username'] != null
                  ? '@${c['username']} · ${c['member_count']} 人'
                  : '${c['member_count']} 人'),
              onTap: () => c.containsKey('is_member')
                  ? openPublicChat(context, c)
                  : openChat(context, (c['id'] as num).toInt()),
            ),
          if (_users.isNotEmpty) _header('人'),
          for (final u in _users)
            ListTile(
              leading: ChatAvatar(
                  name: u.displayName, url: u.avatar, size: 44, online: u.lastSeen.online),
              title: Text(u.displayName),
              subtitle: Text(u.username != null ? '@${u.username}' : u.lastSeen.label()),
              onTap: () => openUserProfile(context, u.id),
            ),
          if (_messages.isNotEmpty) _header('消息'),
          for (final row in _messages) _messageTile(row),
        ],
        if (empty)
          Padding(
            padding: const EdgeInsets.all(40),
            child: Center(
                child: Text(_emptyText(q), style: TextStyle(color: sz.inkMuted))),
          ),
      ]),
    );
  }

  String _emptyText(String q) {
    if (_tab == 'downloads') {
      return q.isEmpty ? '还没有下载过什么' : '下载记录里没有「$q」';
    }
    if (q.isEmpty) {
      return switch (_tab) {
        'media' => '这里还没有图片和视频',
        'links' => '这里还没有链接',
        'files' => '这里还没有文件',
        'music' => '这里还没有音乐',
        'voice' => '这里还没有语音',
        _ => '搜点什么',
      };
    }
    return '没有找到「$q」';
  }
}
