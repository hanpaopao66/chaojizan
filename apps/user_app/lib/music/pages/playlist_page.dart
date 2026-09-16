// 歌单详情与编辑(§8.2 /playlists/*)。自己的歌单能改名、改简介、公开 / 私密、
// 拖着换顺序、移歌、删歌单;别人的公开歌单能收藏。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart';
import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../player/music_player.dart';
import '../widgets/common.dart';

class MusicPlaylistPage extends StatefulWidget {
  const MusicPlaylistPage({super.key, required this.pid});

  final String pid;

  @override
  State<MusicPlaylistPage> createState() => _MusicPlaylistPageState();
}

class _MusicPlaylistPageState extends State<MusicPlaylistPage> {
  final _key = GlobalKey<MLoaderState<MPlaylist>>();

  /// 正在整理(拖顺序、移歌)
  bool _editing = false;

  MPlaylist? get _p => _key.currentState?.data;

  bool get _mine {
    final p = _p;
    return p?.owner != null && rootApi.userId != null && p!.owner!.id == rootApi.userId;
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: const Text('歌单'),
        actions: [
          if (_mine)
            TextButton(
              onPressed: () => setState(() => _editing = !_editing),
              child: Text(_editing ? '完成' : '整理'),
            ),
          IconButton(
            icon: const Icon(Icons.more_horiz),
            tooltip: '更多',
            onPressed: _p == null ? null : _menu,
          ),
        ],
      ),
      body: MLoader<MPlaylist>(
        key: _key,
        load: () => musicApi.playlist(widget.pid),
        builder: (context, p, reload) => _body(context, p, reload),
      ),
    );
  }

  Widget _body(BuildContext context, MPlaylist p, Future<void> Function() reload) {
    final sz = Theme.of(context).sz;
    final header = <Widget>[
      Padding(
        padding: const EdgeInsets.all(kPagePad),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          MCover(url: p.cover, name: p.title, size: 96, radius: kRadiusMd),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(
                  child: Text(p.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontLead, color: sz.ink, fontWeight: FontWeight.w600)),
                ),
                if (!p.isPublic) ...[const SizedBox(width: 6), const VTag('私密')],
              ]),
              const SizedBox(height: 4),
              if (p.owner != null)
                Text(p.owner!.name, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              Text('${p.trackCount} 首 · ${vCount(p.collects)} 收藏',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              if (p.tags.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Wrap(spacing: 6, runSpacing: 6, children: [for (final t in p.tags) SzChip(t, dense: true)]),
                ),
            ]),
          ),
        ]),
      ),
      if (p.description.isNotEmpty)
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 10),
          child: Text(p.description, style: TextStyle(fontSize: kFontBody, color: sz.inkMuted, height: 1.6)),
        ),
      Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 8),
        child: Row(children: [
          FilledButton.icon(
            onPressed: p.tracks.isEmpty
                ? null
                : () => MusicPlayer.instance.playContext(p.tracks, contextKey: 'playlist:${p.pid}'),
            icon: const Icon(Icons.play_arrow, size: 18),
            label: Text('播放全部(${p.tracks.length})'),
          ),
          const SizedBox(width: 10),
          if (!_mine)
            OutlinedButton.icon(
              onPressed: () => _collect(p),
              icon: Icon(p.collected ? Icons.check : Icons.add, size: 18),
              label: Text(p.collected ? '已收藏' : '收藏'),
            ),
        ]),
      ),
      const Divider(height: 1),
    ];

    if (p.tracks.isEmpty) {
      return ListView(children: [
        ...header,
        Padding(padding: const EdgeInsets.only(top: 32), child: SzEmpty(text: '这个歌单里还没有歌')),
      ]);
    }

    if (_editing && _mine) {
      return CustomScrollView(slivers: [
        SliverList(delegate: SliverChildListDelegate(header)),
        SliverReorderableList(
          itemCount: p.tracks.length,
          onReorderItem: (from, to) => _reorder(p, from, to),
          itemBuilder: (context, i) {
            final t = p.tracks[i];
            return ListTile(
              key: ValueKey(t.tid),
              dense: true,
              leading: IconButton(
                icon: Icon(Icons.remove_circle_outline, color: sz.danger),
                tooltip: '从歌单移出',
                onPressed: () => _remove(p, t),
              ),
              title: Text(t.title, maxLines: 1, overflow: TextOverflow.ellipsis),
              subtitle: t.artistName.isEmpty
                  ? null
                  : Text(t.artistName, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              trailing: ReorderableDragStartListener(index: i, child: const Icon(Icons.drag_handle)),
            );
          },
        ),
      ]);
    }

    return ListView.builder(
      itemCount: p.tracks.length + header.length,
      itemBuilder: (context, i) {
        if (i < header.length) return header[i];
        final t = p.tracks[i - header.length];
        return MTrackTile(track: t, queue: p.tracks, contextKey: 'playlist:${p.pid}');
      },
    );
  }

  Future<void> _collect(MPlaylist p) async {
    if (!await ensureLoggedIn(context)) return;
    try {
      final r = await musicApi.collectPlaylist(p.pid, !p.collected);
      if (!mounted) return;
      p
        ..collected = r.collected
        ..collects = r.collects;
      _key.currentState?.refreshUi();
    } catch (e) {
      if (mounted) mToast(context, e);
    }
  }

  /// [to] 是拔掉之后的落点(`onReorderItem` 的口径),不用再自己减一。
  Future<void> _reorder(MPlaylist p, int from, int to) async {
    if (to == from) return;
    final t = p.tracks.removeAt(from);
    p.tracks.insert(to, t);
    _key.currentState?.refreshUi();
    try {
      await musicApi.orderPlaylist(p.pid, [for (final x in p.tracks) x.tid]);
    } catch (e) {
      if (!mounted) return;
      mToast(context, e);
      // 服务端没认这次排序,把界面拉回和服务端一致的样子 —— 不能让人以为改成了
      await _key.currentState?.reload();
    }
  }

  Future<void> _remove(MPlaylist p, MTrack t) async {
    try {
      final count = await musicApi.removeFromPlaylist(p.pid, t.tid);
      if (!mounted) return;
      p
        ..tracks.removeWhere((x) => x.tid == t.tid)
        ..trackCount = count;
      _key.currentState?.refreshUi();
    } catch (e) {
      if (mounted) mToast(context, e);
    }
  }

  Future<void> _menu() async {
    final p = _p!;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (_mine) ...[
            ListTile(leading: const Icon(Icons.edit_outlined), title: const Text('改歌单信息'), onTap: () => Navigator.pop(ctx, 'edit')),
            ListTile(
              leading: Icon(p.isPublic ? Icons.lock_outline : Icons.public),
              title: Text(p.isPublic ? '设为私密' : '设为公开'),
              onTap: () => Navigator.pop(ctx, 'visibility'),
            ),
            ListTile(
                leading: const Icon(Icons.delete_outline),
                title: const Text('删除歌单'),
                onTap: () => Navigator.pop(ctx, 'delete')),
          ],
          ListTile(leading: const Icon(Icons.ios_share), title: const Text('分享'), onTap: () => Navigator.pop(ctx, 'share')),
          if (!_mine)
            ListTile(
                leading: const Icon(Icons.flag_outlined),
                title: const Text('举报'),
                onTap: () => Navigator.pop(ctx, 'report')),
        ]),
      ),
    );
    if (pick == null || !mounted) return;
    switch (pick) {
      case 'edit':
        await _edit(p);
      case 'visibility':
        await _patch(p, isPublic: !p.isPublic);
      case 'delete':
        if (!await vConfirm(context, title: '删除「${p.title}」?', body: '歌单删了就没了,里面的歌不受影响', ok: '删除', danger: true)) {
          return;
        }
        try {
          await musicApi.deletePlaylist(p.pid);
          if (mounted) Navigator.pop(context);
        } catch (e) {
          if (mounted) mToast(context, e);
        }
      case 'share':
        await shareMusic(context, 'playlist', p.pid, p.title);
      case 'report':
        await reportSheet(context, targetType: 'playlist', targetId: p.pid);
    }
  }

  Future<void> _edit(MPlaylist p) async {
    final title = await vPrompt(context,
        title: '歌单名', initial: p.title, maxLength: 30, validate: (t) => t.trim().isEmpty ? '起个名字吧' : null);
    if (title == null || !mounted) return;
    final desc = await vPrompt(context, title: '歌单简介', initial: p.description, maxLength: 200, maxLines: 4);
    if (desc == null || !mounted) return;
    await _patch(p, title: title.trim(), description: desc.trim());
  }

  Future<void> _patch(MPlaylist p, {String? title, String? description, bool? isPublic}) async {
    try {
      await musicApi.patchPlaylist(p.pid, title: title, description: description, isPublic: isPublic);
      await _key.currentState?.reload();
    } catch (e) {
      if (mounted) mToast(context, e);
    }
  }
}
