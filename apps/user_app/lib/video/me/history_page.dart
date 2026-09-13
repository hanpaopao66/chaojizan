import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/cards.dart';
import 'common.dart';
import 'me_format.dart';

/// 观看历史(#366):按天分组、封面带进度条、左滑或长按删一条、清空、暂停记录。
class VideoHistoryPage extends StatefulWidget {
  const VideoHistoryPage({super.key});

  @override
  State<VideoHistoryPage> createState() => _VideoHistoryPageState();
}

class _VideoHistoryPageState extends State<VideoHistoryPage> {
  late final CursorPager<HistoryEntry> _pager = CursorPager((cursor) async {
    final m = await videoApi.history(cursor: cursor);
    return (
      items: [for (final x in vList(m['items'])) HistoryEntry.fromJson(x)],
      next: m['next_cursor'] as String?,
      extra: m,
    );
  });

  /// 刚在这一页拨过的开关(在接口回来之前先按用户拨的显示)
  bool? _paused;
  bool _savingPause = false;

  @override
  void initState() {
    super.initState();
    if (rootApi.isLoggedIn) unawaited(_pager.refresh());
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  bool get _isPaused => _paused ?? (_pager.extra['paused'] == true);

  Future<void> _setPaused(bool v) async {
    setState(() {
      _paused = v;
      _savingPause = true;
    });
    try {
      final s = await videoApi.patchSettings(historyPaused: v);
      if (mounted) setState(() => _paused = s['history_paused'] == true);
    } catch (e) {
      if (mounted) {
        setState(() => _paused = !v);
        vToast(context, e);
      }
    } finally {
      if (mounted) setState(() => _savingPause = false);
    }
  }

  Future<bool> _delete(HistoryEntry e) async {
    try {
      await videoApi.deleteHistory(e.video.vid);
      return true;
    } catch (err) {
      if (mounted) vToast(context, err);
      return false;
    }
  }

  Future<void> _deleteByMenu(HistoryEntry e) async {
    final k = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: const Icon(Icons.delete_outline),
            title: const Text('删除这条记录'),
            onTap: () => Navigator.pop(ctx, 'delete'),
          ),
        ]),
      ),
    );
    if (k != 'delete' || !mounted) return;
    if (await _delete(e)) _pager.removeWhere((x) => identical(x, e));
  }

  Future<void> _clear() async {
    final ok = await vConfirm(context,
        title: '清空全部观看历史?', body: '续播进度也一起清掉,不能恢复。', ok: '清空', danger: true);
    if (!ok || !mounted) return;
    try {
      await videoApi.clearHistory();
      await _pager.refresh();
      if (mounted) vToast(context, '观看历史已清空');
    } catch (e) {
      if (mounted) vToast(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('观看历史')),
        body: VideoLoginGate(text: '登录后能看到自己的观看历史', onLoggedIn: () => setState(() => _pager.refresh())),
      );
    }
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('观看历史'),
        actions: [
          AnimatedBuilder(
            animation: _pager,
            builder: (context, _) => IconButton(
              tooltip: '清空',
              icon: const Icon(Icons.delete_sweep_outlined),
              onPressed: _pager.items.isEmpty ? null : _clear,
            ),
          ),
        ],
      ),
      body: PagedListView<HistoryEntry>(
        pager: _pager,
        header: [_pauseBar()],
        emptyText: '还没有看过的视频',
        rowsBuilder: (context, items) => _rows(context, items),
      ),
    );
  }

  Widget _pauseBar() {
    return AnimatedBuilder(
      animation: _pager,
      builder: (context, _) => Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 4),
        child: SzEntryGroup(
          footnote: _isPaused ? '已暂停:这之后看的视频不进历史,续播进度也不记。' : null,
          children: [
            SzEntryTile(
              title: '暂停记录观看历史',
              icon: Icons.history_toggle_off,
              dense: true,
              trailing: Switch(value: _isPaused, onChanged: _savingPause ? null : _setPaused),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _rows(BuildContext context, List<HistoryEntry> items) {
    final sz = Theme.of(context).sz;
    final groups = groupHistoryByDay(items, DateTime.now());
    return [
      for (final g in groups) ...[
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 2),
          child: Text(g.label, style: TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600, color: sz.inkMuted)),
        ),
        for (final e in g.items)
          Dismissible(
            key: ValueKey('h-${e.video.vid}-${e.watchedAt?.microsecondsSinceEpoch}'),
            direction: DismissDirection.endToStart,
            background: Container(
              color: sz.danger,
              alignment: Alignment.centerRight,
              padding: const EdgeInsets.only(right: 24),
              child: const Icon(Icons.delete_outline, color: Colors.white),
            ),
            confirmDismiss: (_) => _delete(e),
            onDismissed: (_) => _pager.removeWhere((x) => identical(x, e)),
            child: Opacity(
              // 失效的(删了、下架了、改私密了)灰着,点不进去,但留着让人知道看过
              opacity: e.video.invalid ? .45 : 1,
              child: VideoRowTile(
                card: e.video,
                progress: e.video.invalid ? null : e.progress,
                subtitle: historySubtitle(e),
                onTap: e.video.invalid ? null : () => openVideo(context, e.video.vid, partIdx: e.partIdx),
                onLongPress: () => _deleteByMenu(e),
              ),
            ),
          ),
      ],
    ];
  }
}
