// 「加到歌单」弹层:挑一个自己建的歌单,或者当场新建一个(§8.2 POST /playlists/{pid}/tracks)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart';
import '../models.dart';
import '../nav.dart';
import 'common.dart';

/// 把 [tids] 加到某个歌单。加成功返回 true。
///
/// 加歌要登录(§5.2 写接口一律登录):没登录先引导登录,登录完了接着加,
/// 而不是把人丢在登录页自己找回来。
Future<bool> addToPlaylistSheet(BuildContext context, List<String> tids) async {
  if (tids.isEmpty) return false;
  if (!await ensureLoggedIn(context)) return false;
  if (!context.mounted) return false;
  final picked = await szShowSheet<String>(
    context: context,
    builder: (ctx) => _PickPlaylist(count: tids.length),
  );
  if (picked == null || picked.isEmpty || !context.mounted) return false;
  try {
    final r = await musicApi.addToPlaylist(picked, tids);
    if (context.mounted) {
      // 服务端会去重:重复加的时候说清楚「加了几首」,不然用户以为没成功
      mToast(context, r.added > 0 ? '已加 ${r.added} 首' : '这些歌已经在歌单里了');
    }
    return r.added > 0;
  } catch (e) {
    if (context.mounted) mToast(context, e);
    return false;
  }
}

class _PickPlaylist extends StatefulWidget {
  const _PickPlaylist({required this.count});

  final int count;

  @override
  State<_PickPlaylist> createState() => _PickPlaylistState();
}

class _PickPlaylistState extends State<_PickPlaylist> {
  List<MPlaylist>? _items;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await musicApi.myPlaylists();
      if (mounted) {
        setState(() {
          _items = r.created;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _create() async {
    final title = await vPrompt(context,
        title: '新建歌单',
        hint: '歌单名',
        maxLength: 30,
        validate: (t) => t.trim().isEmpty ? '起个名字吧' : null);
    if (title == null || !mounted) return;
    try {
      final p = await musicApi.createPlaylist(title.trim());
      if (mounted) Navigator.pop(context, p.pid);
    } catch (e) {
      if (mounted) mToast(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    return SafeArea(
      child: SzSheetScrollable(
        builder: (ctx, controller) => Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            title: Text('加到歌单', style: TextStyle(fontSize: kFontTitle, color: sz.ink)),
            subtitle: Text('共 ${widget.count} 首', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            trailing: TextButton.icon(onPressed: _create, icon: const Icon(Icons.add), label: const Text('新建')),
          ),
          const Divider(height: 1),
          Flexible(
            child: items == null
                ? Padding(
                    padding: const EdgeInsets.all(32),
                    child: Center(
                      child: _error != null
                          ? musicErrorView(_error, _load)
                          : const CircularProgressIndicator(),
                    ),
                  )
                : ListView(
                    controller: controller,
                    // 对话框形态给的是宽松约束,不 shrinkWrap 会贪到 0.85 屏高
                    shrinkWrap: controller == null,
                    physics: const AlwaysScrollableScrollPhysics(),
                    children: [
                      if (items.isEmpty)
                        Padding(
                          padding: const EdgeInsets.all(32),
                          child: Center(
                            child: Text('还没有自己建的歌单,点右上角新建一个',
                                style: TextStyle(color: sz.inkMuted)),
                          ),
                        ),
                      for (final p in items)
                        ListTile(
                          leading: MCover(url: p.cover, name: p.title, size: 44),
                          title: Text(p.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                          subtitle: Text('${p.trackCount} 首',
                              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                          onTap: () => Navigator.pop(ctx, p.pid),
                        ),
                    ],
                  ),
          ),
        ]),
      ),
    );
  }
}
