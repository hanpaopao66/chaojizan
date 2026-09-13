import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/cards.dart';
import 'common.dart';

/// 稍后再看(#366,最多 100 个):左滑或点右边的 × 移出,失效的灰着、可以一键清掉。
class WatchLaterPage extends StatefulWidget {
  const WatchLaterPage({super.key});

  @override
  State<WatchLaterPage> createState() => _WatchLaterPageState();
}

typedef _Item = ({VideoCard video, DateTime? addedAt});

class _WatchLaterPageState extends State<WatchLaterPage> {
  // 接口一次给全部(最多 100 个),没有游标:包成只有一页的翻页器,好和别的列表共用下拉刷新、空状态、错误态
  late final CursorPager<_Item> _pager = CursorPager((_) async {
    final m = await videoApi.watchLater();
    return (
      items: [
        for (final x in vList(m['items']))
          (video: VideoCard.fromJson(vMap(x)['video']), addedAt: DateTime.tryParse('${vMap(x)['added_at']}')?.toLocal()),
      ],
      next: null,
      extra: m,
    );
  });

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

  Future<bool> _remove(VideoCard v, {bool drop = false}) async {
    try {
      await videoApi.removeWatchLater(v.vid);
      if (drop) _pager.removeWhere((x) => x.video.vid == v.vid);
      return true;
    } catch (e) {
      if (mounted) vToast(context, e);
      return false;
    }
  }

  Future<void> _clearInvalid() async {
    final bad = [for (final x in _pager.items) if (x.video.invalid) x.video];
    if (bad.isEmpty) return;
    final ok = await vConfirm(context, title: '清掉 ${bad.length} 个失效视频?', ok: '清掉');
    if (!ok) return;
    for (final v in bad) {
      if (!await _remove(v, drop: true)) break;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('稍后再看')),
        body: VideoLoginGate(text: '登录后把想看的视频先存在这里', onLoggedIn: () => setState(() => _pager.refresh())),
      );
    }
    return AnimatedBuilder(
      animation: _pager,
      builder: (context, _) {
        final sz = Theme.of(context).sz;
        final count = _pager.items.length;
        final max = vInt(_pager.extra['max']) > 0 ? vInt(_pager.extra['max']) : 100;
        final anyInvalid = _pager.items.any((x) => x.video.invalid);
        return SzPageScaffold(
          appBar: AppBar(
            title: Text(_pager.loaded ? '稍后再看($count/$max)' : '稍后再看'),
            actions: [
              if (anyInvalid) TextButton(onPressed: _clearInvalid, child: const Text('清掉失效的')),
            ],
          ),
          body: PagedListView<_Item>(
            pager: _pager,
            emptyText: '还没有要稍后再看的视频\n在视频卡片上长按,或者在播放页点「稍后再看」',
            itemBuilder: (context, x, _) => Dismissible(
              key: ValueKey('wl-${x.video.vid}'),
              direction: DismissDirection.endToStart,
              background: Container(
                color: sz.danger,
                alignment: Alignment.centerRight,
                padding: const EdgeInsets.only(right: 24),
                child: const Icon(Icons.delete_outline, color: Colors.white),
              ),
              confirmDismiss: (_) => _remove(x.video),
              onDismissed: (_) => _pager.removeWhere((y) => y.video.vid == x.video.vid),
              child: Opacity(
                opacity: x.video.invalid ? .45 : 1,
                child: VideoRowTile(
                  card: x.video,
                  subtitle: x.video.invalid ? '视频已失效' : null,
                  onTap: x.video.invalid ? null : () => openVideo(context, x.video.vid),
                  trailing: IconButton(
                    tooltip: '移出稍后再看',
                    icon: Icon(Icons.close, size: 18, color: sz.inkMuted),
                    onPressed: () => _remove(x.video, drop: true),
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
