import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/cards.dart';
import 'common.dart';

/// 收藏夹名字 1–20 字(服务端 FOLDER_TITLE_MAX)
const _folderTitleMax = 20;

String? _checkFolderTitle(String s) {
  final t = s.trim().split(RegExp(r'\s+')).where((x) => x.isNotEmpty).join(' ');
  if (t.isEmpty) return '起个名字';
  if (t.runes.length > _folderTitleMax) return '收藏夹名字最多 $_folderTitleMax 个字';
  return null;
}

/// 新建收藏夹的对话框:名字 + 公开 / 私密。取消返回 null。
Future<({String title, bool public})?> _askNewFolder(BuildContext context) async {
  final c = TextEditingController();
  var public = false;
  String? err;
  final r = await showDialog<({String title, bool public})>(
    context: context,
    builder: (ctx) => SzDisposeWith(
      controllers: [c],
      child: StatefulBuilder(
        builder: (ctx, setLocal) => SzDialog(
          title: const Text('新建收藏夹'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(
              controller: c,
              autofocus: true,
              maxLength: _folderTitleMax,
              decoration: InputDecoration(hintText: '比如「学做菜」', errorText: err),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('公开'),
              subtitle: const Text('公开的收藏夹会出现在你的空间里'),
              value: public,
              onChanged: (v) => setLocal(() => public = v),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
            FilledButton(
              onPressed: () {
                final e = _checkFolderTitle(c.text);
                if (e != null) {
                  setLocal(() => err = e);
                  return;
                }
                Navigator.pop(ctx, (title: c.text.trim(), public: public));
              },
              child: const Text('建好了'),
            ),
          ],
        ),
      ),
    ),
  );
  return r;
}

/// 收藏夹的封面位:最近收进来的那个视频的封面;空夹子画个文件夹。
class _FolderCover extends StatelessWidget {
  const _FolderCover(this.f);

  final FavFolder f;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ClipRRect(
      borderRadius: BorderRadius.circular(kRadiusSm),
      child: SizedBox(
        width: 96,
        height: 60,
        child: f.cover.isEmpty
            ? ColoredBox(color: sz.surfaceAlt, child: Icon(Icons.folder_outlined, color: sz.inkFaint))
            : Image(
                image: szNetImage(videoResolve(f.cover)),
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => ColoredBox(color: sz.surfaceAlt),
              ),
      ),
    );
  }
}

/// 我的收藏夹(#366):默认收藏夹 + 自建的(最多 50 个),公开 / 私密,新建、改名、删除。
class FavoritesPage extends StatefulWidget {
  const FavoritesPage({super.key});

  @override
  State<FavoritesPage> createState() => _FavoritesPageState();
}

class _FavoritesPageState extends State<FavoritesPage> {
  List<FavFolder>? _folders;
  Object? _error;

  @override
  void initState() {
    super.initState();
    if (rootApi.isLoggedIn) unawaited(_load());
  }

  Future<void> _load() async {
    try {
      final r = await videoApi.folders();
      if (!mounted) return;
      setState(() {
        _folders = r;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _act(Future<void> Function() f, [String? done]) async {
    try {
      await f();
      await _load();
      if (done != null && mounted) vToast(context, done);
    } catch (e) {
      if (mounted) vToast(context, e);
    }
  }

  Future<void> _create() async {
    final r = await _askNewFolder(context);
    if (r == null || !mounted) return;
    await _act(() => videoApi.createFolder(r.title, public: r.public));
  }

  Future<void> _rename(FavFolder f) async {
    final t = await vPrompt(context,
        title: '改名', initial: f.title, maxLength: _folderTitleMax, validate: _checkFolderTitle);
    if (t == null || t.trim() == f.title || !mounted) return;
    await _act(() => videoApi.patchFolder(f.id, title: t.trim()));
  }

  Future<void> _togglePublic(FavFolder f) =>
      _act(() => videoApi.patchFolder(f.id, public: !f.isPublic), f.isPublic ? '已设为私密' : '已设为公开,会出现在你的空间里');

  Future<void> _delete(FavFolder f) async {
    final ok = await vConfirm(context,
        title: '删除「${f.title}」?',
        body: f.count > 0 ? '夹里的 ${f.count} 个视频会一起移出这个收藏夹;放在别的收藏夹里的不受影响。' : null,
        ok: '删除',
        danger: true);
    if (!ok || !mounted) return;
    await _act(() => videoApi.deleteFolder(f.id), '收藏夹已删除');
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('我的收藏')),
        body: VideoLoginGate(text: '登录后收藏喜欢的视频', onLoggedIn: () => _load()),
      );
    }
    final folders = _folders;
    final own = folders?.where((f) => !f.isDefault).length ?? 0;
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('我的收藏'),
        actions: [
          IconButton(
            tooltip: '新建收藏夹',
            icon: const Icon(Icons.create_new_folder_outlined),
            onPressed: folders == null || own >= 50 ? null : _create,
          ),
        ],
      ),
      body: folders == null
          ? (_error != null ? videoErrorView(_error, _load) : const Center(child: CircularProgressIndicator()))
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
                for (final f in folders)
                  InkWell(
                    onTap: () async {
                      await Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => FolderPage(f.id)));
                      if (mounted) unawaited(_load());
                    },
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(kPagePad, 10, 4, 10),
                      child: Row(children: [
                        _FolderCover(f),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Row(children: [
                              Flexible(
                                child: Text(f.title,
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
                              ),
                              if (f.isDefault) ...[const SizedBox(width: 6), const VTag('默认')],
                            ]),
                            const SizedBox(height: 4),
                            Text('${f.count} 个视频 · ${f.isPublic ? '公开' : '私密'}',
                                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                          ]),
                        ),
                        PopupMenuButton<String>(
                          tooltip: '管理',
                          icon: Icon(Icons.more_vert, color: sz.inkMuted),
                          onSelected: (k) => switch (k) {
                            'rename' => _rename(f),
                            'public' => _togglePublic(f),
                            _ => _delete(f),
                          },
                          itemBuilder: (_) => [
                            const PopupMenuItem(value: 'rename', child: Text('改名')),
                            PopupMenuItem(value: 'public', child: Text(f.isPublic ? '设为私密' : '设为公开')),
                            if (!f.isDefault) const PopupMenuItem(value: 'delete', child: Text('删除')),
                          ],
                        ),
                      ]),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.all(kPagePad),
                  child: Text('自建收藏夹最多 50 个(已建 $own 个),每个最多 1,000 个视频。公开的收藏夹会出现在你的空间里,私密的只有你自己看得到。',
                      style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted, height: 1.5)),
                ),
              ]),
            ),
    );
  }
}

typedef _FolderItem = ({VideoCard video, DateTime? addedAt});

/// 一个收藏夹里的视频。[mine] 为真是自己的(能多选移动到别的夹、移出),
/// 假的是别人空间里的公开收藏夹(只能看)。
class FolderPage extends StatefulWidget {
  const FolderPage(this.folderId, {super.key, this.mine = true});

  final int folderId;
  final bool mine;

  @override
  State<FolderPage> createState() => _FolderPageState();
}

class _FolderPageState extends State<FolderPage> {
  late final CursorPager<_FolderItem> _pager = CursorPager((cursor) async {
    final m = widget.mine
        ? await videoApi.folder(widget.folderId, cursor: cursor)
        : await videoApi.publicFolder(widget.folderId, cursor: cursor);
    return (
      items: [
        for (final x in vList(m['items']))
          (video: VideoCard.fromJson(vMap(x)['video']), addedAt: DateTime.tryParse('${vMap(x)['added_at']}')?.toLocal()),
      ],
      next: m['next_cursor'] as String?,
      extra: m,
    );
  });

  bool _selecting = false;
  final Set<String> _picked = {};
  bool _busy = false;

  /// 移走之后夹子里还剩几个(接口给的 count 是进页面时的,移走了自己减)
  int _removed = 0;

  @override
  void initState() {
    super.initState();
    unawaited(_pager.refresh());
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  FavFolder? get _folder => _pager.extra['folder'] == null ? null : FavFolder.fromJson(_pager.extra['folder']);

  void _toggle(String vid) => setState(() => _picked.contains(vid) ? _picked.remove(vid) : _picked.add(vid));

  Future<void> _moveTo() async {
    final vids = _picked.toList();
    if (vids.isEmpty) return;
    final target = await szShowSheet<FavFolder>(
      context: context,
      builder: (_) => _TargetFolderSheet(exclude: widget.folderId),
    );
    if (target == null || !mounted) return;
    await _run(() => videoApi.moveFavorites(widget.folderId, vids, to: target.id), vids, '已移到「${target.title}」');
  }

  Future<void> _removePicked() async {
    final vids = _picked.toList();
    if (vids.isEmpty) return;
    final ok = await vConfirm(context, title: '把选中的 ${vids.length} 个视频移出这个收藏夹?', ok: '移出', danger: true);
    if (!ok || !mounted) return;
    await _run(() => videoApi.moveFavorites(widget.folderId, vids), vids, '已移出');
  }

  Future<void> _run(Future<void> Function() f, List<String> vids, String done) async {
    setState(() => _busy = true);
    try {
      await f();
      _pager.removeWhere((x) => vids.contains(x.video.vid));
      setState(() {
        _removed += vids.length;
        _picked.clear();
        _selecting = false;
      });
      if (mounted) vToast(context, done);
    } catch (e) {
      if (mounted) vToast(context, e);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _pager,
      builder: (context, _) {
        final f = _folder;
        final count = f == null ? null : (f.count - _removed).clamp(0, 1 << 30);
        return SzPageScaffold(
          appBar: AppBar(
            title: Text(_selecting
                ? '已选 ${_picked.length} 个'
                : f == null
                    ? '收藏夹'
                    : '${f.title}(${count ?? 0})'),
            actions: [
              if (widget.mine && _pager.items.isNotEmpty) ...[
                if (_selecting)
                  TextButton(
                    onPressed: () => setState(() {
                      final all = {for (final x in _pager.items) x.video.vid};
                      if (_picked.length == all.length) {
                        _picked.clear();
                      } else {
                        _picked
                          ..clear()
                          ..addAll(all);
                      }
                    }),
                    child: Text(_picked.length == _pager.items.length ? '全不选' : '全选'),
                  ),
                TextButton(
                  onPressed: () => setState(() {
                    _selecting = !_selecting;
                    _picked.clear();
                  }),
                  child: Text(_selecting ? '完成' : '管理'),
                ),
              ],
            ],
          ),
          // 多选时的按钮条放在 body 里,不走 bottomNavigationBar:宽屏下那个槽会被撑满整屏(见投稿页同样的注释)
          body: Column(children: [
            Expanded(
              child: PagedListView<_FolderItem>(
                pager: _pager,
                emptyText: widget.mine ? '这个收藏夹还是空的\n在视频下面点「收藏」就能放进来' : '这个收藏夹还是空的',
                itemBuilder: (context, x, _) {
                  final v = x.video;
                  final row = VideoRowTile(
                    card: v,
                    subtitle: v.invalid ? '视频已失效' : null,
                    onTap: _selecting ? () => _toggle(v.vid) : (v.invalid ? null : () => openVideo(context, v.vid)),
                    trailing: _selecting
                        ? Checkbox(value: _picked.contains(v.vid), onChanged: (_) => _toggle(v.vid))
                        : null,
                  );
                  return Opacity(opacity: v.invalid && !_selecting ? .45 : 1, child: row);
                },
              ),
            ),
            if (_selecting)
              SafeArea(
                top: false,
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 8),
                  child: Row(children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: _picked.isEmpty || _busy ? null : _removePicked,
                        child: const Text('移出收藏夹'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: FilledButton(
                        onPressed: _picked.isEmpty || _busy ? null : _moveTo,
                        child: const Text('移动到…'),
                      ),
                    ),
                  ]),
                ),
              ),
          ]),
        );
      },
    );
  }
}

/// 「移动到…」选目标收藏夹。
class _TargetFolderSheet extends StatefulWidget {
  const _TargetFolderSheet({required this.exclude});

  final int exclude;

  @override
  State<_TargetFolderSheet> createState() => _TargetFolderSheetState();
}

class _TargetFolderSheetState extends State<_TargetFolderSheet> {
  List<FavFolder>? _folders;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await videoApi.folders();
      if (mounted) setState(() => _folders = r);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _create() async {
    final r = await _askNewFolder(context);
    if (r == null || !mounted) return;
    try {
      final f = await videoApi.createFolder(r.title, public: r.public);
      if (mounted) Navigator.pop(context, f);
    } catch (e) {
      if (mounted) vToast(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final folders = _folders?.where((f) => f.id != widget.exclude).toList();
    return SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(title: const Text('移动到', style: TextStyle(fontWeight: FontWeight.w600))),
        if (folders == null)
          Padding(
            padding: const EdgeInsets.all(24),
            child: _error != null
                ? Text(videoErrorText(_error!), style: TextStyle(color: sz.danger))
                : const CircularProgressIndicator(),
          )
        else
          Flexible(
            child: ListView(shrinkWrap: true, children: [
              for (final f in folders)
                ListTile(
                  leading: Icon(f.isPublic ? Icons.folder_open_outlined : Icons.folder_outlined),
                  title: Text(f.title),
                  subtitle: Text('${f.count} 个视频'),
                  onTap: () => Navigator.pop(context, f),
                ),
              ListTile(
                leading: Icon(Icons.create_new_folder_outlined, color: sz.clay),
                title: Text('新建收藏夹', style: TextStyle(color: sz.clay)),
                onTap: _create,
              ),
            ]),
          ),
      ]),
    );
  }
}

/// 给视频详情页用的收藏选择面板:勾上要放进的收藏夹(可以当场新建),返回**全部**选中的 id
/// (照 `POST /videos/{vid}/favorite` 的口径:这个视频要在的全部收藏夹;一个都不勾 = 取消收藏)。
/// 取消返回 null。
Future<List<int>?> pickFavoriteFolders(BuildContext context, {required List<int> current}) async {
  if (!await ensureLoggedIn(context)) return null;
  if (!context.mounted) return null;
  return szShowSheet<List<int>>(context: context, builder: (_) => _FavoritePickerSheet(current: current));
}

class _FavoritePickerSheet extends StatefulWidget {
  const _FavoritePickerSheet({required this.current});

  final List<int> current;

  @override
  State<_FavoritePickerSheet> createState() => _FavoritePickerSheetState();
}

class _FavoritePickerSheetState extends State<_FavoritePickerSheet> {
  List<FavFolder>? _folders;
  Object? _error;
  late final Set<int> _picked = {...widget.current};
  bool _creating = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final r = await videoApi.folders();
      if (mounted) setState(() => _folders = r);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _create() async {
    final r = await _askNewFolder(context);
    if (r == null || !mounted) return;
    setState(() => _creating = true);
    try {
      final f = await videoApi.createFolder(r.title, public: r.public);
      if (!mounted) return;
      setState(() {
        _folders = [...?_folders, f];
        _picked.add(f.id);
      });
    } catch (e) {
      if (mounted) vToast(context, e);
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final folders = _folders;
    final none = _picked.isEmpty;
    final wasIn = widget.current.isNotEmpty;
    return SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(
          title: const Text('收藏到', style: TextStyle(fontWeight: FontWeight.w600)),
          trailing: _creating
              ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
              : TextButton.icon(
                  onPressed: folders == null ? null : _create,
                  icon: const Icon(Icons.add, size: 18),
                  label: const Text('新建'),
                ),
        ),
        if (folders == null)
          Padding(
            padding: const EdgeInsets.all(24),
            child: _error != null ? videoErrorView(_error, _load) : const CircularProgressIndicator(),
          )
        else
          Flexible(
            child: ListView(shrinkWrap: true, children: [
              for (final f in folders)
                CheckboxListTile(
                  value: _picked.contains(f.id),
                  onChanged: (v) => setState(() => v == true ? _picked.add(f.id) : _picked.remove(f.id)),
                  title: Text(f.title),
                  subtitle: Text('${f.count} 个视频 · ${f.isPublic ? '公开' : '私密'}${f.isDefault ? ' · 默认' : ''}',
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ),
            ]),
          ),
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 12),
          child: SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: folders == null || (none && !wasIn)
                  ? null
                  : () => Navigator.pop(context, [
                        for (final f in folders)
                          if (_picked.contains(f.id)) f.id,
                      ]),
              child: Text(none ? (wasIn ? '取消收藏' : '选一个收藏夹') : '确定(${_picked.length} 个收藏夹)'),
            ),
          ),
        ),
      ]),
    );
  }
}
