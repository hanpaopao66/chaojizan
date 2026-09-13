import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/store.dart';
import '../../session.dart';
import '../me/coins_page.dart';
import '../me/common.dart';
import '../me/follow_list_page.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/cards.dart';
import 'creator_models.dart';
import 'creator_video_page.dart';
import 'upload_page.dart';
import 'upload_tasks.dart';

export 'creator_video_page.dart' show CreatorVideoPage;

/// 创作中心(#358):数据总览 + 稿件管理(按状态分页签)。
///
/// 稿件状态靠用户事件 `video` 实时更新(提交、转码完 / 失败、审核结果、下架、申诉结果、定时发布到点、
/// 另一台设备改了稿都会推):来一个就重拉那一条,改那一行、挪页签或者删掉,不整页刷新。
class CreatorCenterPage extends StatefulWidget {
  const CreatorCenterPage({super.key});

  @override
  State<CreatorCenterPage> createState() => _CreatorCenterPageState();
}

class _CreatorCenterPageState extends State<CreatorCenterPage> with SingleTickerProviderStateMixin {
  late final TabController _tc = TabController(length: creatorTabs.length, vsync: this)..addListener(_onTab);

  late final Map<String, CursorPager<CreatorVideo>> _pagers = {
    for (final (key, _) in creatorTabs)
      key: CursorPager<CreatorVideo>((cursor) async {
        final m = await videoApi.creatorVideos(status: key, cursor: cursor);
        return (
          items: [for (final x in vList(m['items'])) CreatorVideo.fromJson(x)],
          next: m['next_cursor'] as String?,
          extra: m,
        );
      }),
  };

  Map<String, dynamic>? _overview;

  /// 总览看哪一段:totals 累计 / today 今天 / last_7_days / last_30_days
  String _window = 'totals';
  StreamSubscription<({String type, Map<String, dynamic> data})>? _events;
  Timer? _overviewTimer;

  @override
  void initState() {
    super.initState();
    _events = ChatStore.instance.userEvents.stream.listen((e) {
      if (e.type != 'video') return;
      final vid = '${e.data['vid'] ?? ''}';
      if (vid.isNotEmpty) unawaited(_refreshOne(vid));
    });
    VideoUploads.instance.addListener(_onUploads);
    if (rootApi.isLoggedIn) _start();
  }

  void _start() {
    unawaited(_loadOverview());
    unawaited(_pagers['all']!.refresh());
  }

  @override
  void dispose() {
    _events?.cancel();
    _overviewTimer?.cancel();
    VideoUploads.instance.removeListener(_onUploads);
    _tc.dispose();
    for (final p in _pagers.values) {
      p.dispose();
    }
    super.dispose();
  }

  void _onUploads() {
    if (mounted) setState(() {});
  }

  void _onTab() {
    // 页签第一次点开才去拉,不一进来就发六个请求
    final p = _pagers[creatorTabs[_tc.index].$1]!;
    if (!p.loaded && !p.loading) unawaited(p.refresh());
  }

  Future<void> _loadOverview() async {
    try {
      final o = await videoApi.creatorOverview();
      if (mounted) setState(() => _overview = o);
    } catch (_) {
      // 总览拉不到只是少一块数字;列表自己会显示错误(比如 503 暂未开放)
    }
  }

  /// 数字一两秒内可能变好几次(一个稿件转码完马上进审核):攒一下再拉
  void _scheduleOverview() {
    _overviewTimer?.cancel();
    _overviewTimer = Timer(const Duration(milliseconds: 800), _loadOverview);
  }

  Future<void> _refreshOne(String vid) async {
    try {
      final v = CreatorVideo.fromJson(await videoApi.creatorVideo(vid));
      for (final (key, _) in creatorTabs) {
        final p = _pagers[key]!;
        if (!p.loaded) continue;
        if (inCreatorTab(key, v.status)) {
          p.upsert((x) => x.vid == vid, v, orInsert: true);
        } else {
          p.removeWhere((x) => x.vid == vid);
        }
      }
    } on ApiException catch (e) {
      // 删掉了(可能是另一台设备删的):各页签里都拿掉
      if (e.statusCode == 404) {
        for (final p in _pagers.values) {
          p.removeWhere((x) => x.vid == vid);
        }
      }
    } catch (_) {
      // 网络问题:下一个事件或下拉刷新再对齐
    }
    _scheduleOverview();
  }

  Future<void> _refreshAll() async {
    await Future.wait([
      _loadOverview(),
      for (final p in _pagers.values)
        if (p.loaded) p.refresh(),
    ]);
  }

  Future<void> _newUpload() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => const VideoUploadPage()));
    if (mounted) await _refreshAll();
  }

  Future<void> _open(CreatorVideo v) async {
    await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => CreatorVideoPage(v.vid)));
    if (mounted) await _refreshOne(v.vid);
  }

  Future<void> _editItem(CreatorVideo v) async {
    await Navigator.of(context).push<bool>(MaterialPageRoute(builder: (_) => VideoUploadPage(vid: v.vid)));
    if (mounted) await _refreshOne(v.vid);
  }

  Future<void> _delete(CreatorVideo v) async {
    final ok = await vConfirm(context,
        title: '删除「${v.displayTitle}」?',
        body: '删除后立即从所有地方消失、播放地址失效,不能恢复。收到的硬币不会退回。',
        ok: '删除',
        danger: true);
    if (!ok || !mounted) return;
    try {
      await videoApi.deleteVideo(v.vid);
      for (final p in _pagers.values) {
        p.removeWhere((x) => x.vid == v.vid);
      }
      _scheduleOverview();
      if (mounted) vToast(context, '稿件已删除');
    } catch (e) {
      if (mounted) vToast(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('创作中心')),
        body: VideoLoginGate(text: '登录后管理你的投稿', onLoggedIn: () => setState(_start)),
      );
    }
    final byStatus = vMap(_overview?['videos']);
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('创作中心'),
        actions: [
          TextButton.icon(onPressed: _newUpload, icon: const Icon(Icons.add, size: 18), label: const Text('投稿')),
        ],
      ),
      body: Column(children: [
        TabBar(
          controller: _tc,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: [
            for (final (key, label) in creatorTabs)
              Tab(
                text: _overview == null || key == 'all'
                    ? label
                    : '$label${creatorTabCount(key, byStatus) > 0 ? ' ${creatorTabCount(key, byStatus)}' : ''}',
              ),
          ],
        ),
        Expanded(
          child: TabBarView(controller: _tc, children: [
            for (final (key, _) in creatorTabs)
              PagedListView<CreatorVideo>(
                pager: _pagers[key]!,
                // 总览只放在「全部」的列表头上、跟着列表滚走:固定在顶上的话,矮屏上稿件列表只剩一小条
                header: [if (key == 'all' && _overview != null) _overviewCard(_overview!)],
                emptyText: key == 'all' ? '还没有投稿\n点右上角「投稿」发第一个视频' : '这里没有稿件',
                itemBuilder: (context, v, _) => _row(v),
              ),
          ]),
        ),
      ]),
    );
  }

  Widget _overviewCard(Map<String, dynamic> o) {
    final sz = Theme.of(context).sz;
    final nums = vMap(o[_window]);
    final me = rootApi.userId;
    Widget link(String label, int n, VoidCallback onTap) => InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(kRadiusSm),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
            child: Text.rich(TextSpan(children: [
              TextSpan(text: '$label ', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              TextSpan(text: vCount(n), style: szFigure(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
            ])),
          ),
        );
    return Container(
      margin: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 4),
      padding: const EdgeInsets.fromLTRB(10, 10, 10, 8),
      decoration: BoxDecoration(color: sz.surface, borderRadius: BorderRadius.circular(kRadiusMd), border: Border.all(color: sz.line)),
      child: Column(children: [
        Row(children: [
          link('粉丝', vInt(o['fans']), () {
            if (me != null) {
              Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => FollowListPage(userId: me, fans: true)));
            }
          }),
          const SizedBox(width: 8),
          link('硬币', vInt(o['coins']),
              () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const CoinsPage()))),
          const Spacer(),
          for (final (key, label) in const [('totals', '累计'), ('today', '今天'), ('last_7_days', '7 天'), ('last_30_days', '30 天')])
            Padding(
              padding: const EdgeInsets.only(left: 4),
              child: SzChip(label, dense: true, selected: _window == key, onTap: () => setState(() => _window = key)),
            ),
        ]),
        const SizedBox(height: 8),
        Row(children: [
          for (final (key, label) in statMetrics)
            Expanded(
              child: Column(children: [
                FittedBox(
                  child: Text(vCount(vInt(nums[key])),
                      style: szFigure(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
                ),
                Text(label, style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ]),
            ),
        ]),
      ]),
    );
  }

  Color _tone(CreatorTone t) {
    final sz = Theme.of(context).sz;
    return switch (t) {
      CreatorTone.neutral => sz.inkMuted,
      CreatorTone.busy => sz.hold,
      CreatorTone.good => sz.earn,
      CreatorTone.bad => sz.danger,
    };
  }

  Widget _row(CreatorVideo v) {
    final sz = Theme.of(context).sz;
    final tags = creatorTags(v);
    final uploading = VideoUploads.instance.progressOf(v.vid);
    final uploadFailed = VideoUploads.instance.of(v.vid).any((t) => t.state == UploadState.failed);
    final reason = tags.firstWhere((t) => t.detail.isNotEmpty && t.tone == CreatorTone.bad,
        orElse: () => const CreatorTag('', CreatorTone.neutral));
    final String meta;
    if (v.status == 'scheduled' && v.scheduledAt != null) {
      meta = '${vDateTime(v.scheduledAt!)} 公开';
    } else if (v.card.publishedAt != null) {
      meta = '${vCount(v.card.views)} 播放 · ${vCount(v.card.commentCount)} 评论 · ${vAgo(v.card.publishedAt)}';
    } else {
      meta = v.createdAt == null ? '' : '创建于 ${vDateTime(v.createdAt!)}';
    }
    return InkWell(
      onTap: () => _open(v),
      onLongPress: () => _menu(v),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 10, 4, 10),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
            width: 128,
            height: 80,
            child: Stack(fit: StackFit.expand, children: [
              VideoCover(card: v.card, showDuration: v.card.durationMs > 0),
              if (uploading != null)
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: ClipRRect(
                    borderRadius: const BorderRadius.vertical(bottom: Radius.circular(kRadiusSm)),
                    child: LinearProgressIndicator(value: uploading, minHeight: 3, backgroundColor: Colors.black26),
                  ),
                ),
            ]),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(v.displayTitle,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontBody, height: 1.3, color: v.title.trim().isEmpty ? sz.inkMuted : sz.ink)),
              const SizedBox(height: 4),
              Wrap(spacing: 4, runSpacing: 4, children: [
                if (uploading != null) VTag('上传中 ${(uploading * 100).toStringAsFixed(0)}%', color: sz.hold),
                if (uploadFailed) VTag('上传失败', color: sz.danger),
                for (final t in tags) VTag(t.label, color: _tone(t.tone)),
              ]),
              if (reason.detail.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Text(reason.detail,
                      maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontMicro, color: sz.danger)),
                ),
              if (meta.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Text(meta, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
                ),
            ]),
          ),
          PopupMenuButton<String>(
            tooltip: '更多',
            icon: Icon(Icons.more_vert, color: sz.inkMuted),
            onSelected: (k) => switch (k) {
              'edit' => _editItem(v),
              'watch' => openVideo(context, v.vid),
              'delete' => _delete(v),
              _ => _open(v),
            },
            itemBuilder: (_) => [
              const PopupMenuItem(value: 'open', child: Text('详情和数据')),
              if (v.status != 'removed') const PopupMenuItem(value: 'edit', child: Text('编辑')),
              if (v.watchable) const PopupMenuItem(value: 'watch', child: Text('去看看')),
              const PopupMenuItem(value: 'delete', child: Text('删除')),
            ],
          ),
        ]),
      ),
    );
  }

  Future<void> _menu(CreatorVideo v) async {
    final k = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.insights_outlined), title: const Text('详情和数据'), onTap: () => Navigator.pop(ctx, 'open')),
          if (v.status != 'removed')
            ListTile(leading: const Icon(Icons.edit_outlined), title: const Text('编辑'), onTap: () => Navigator.pop(ctx, 'edit')),
          if (v.watchable)
            ListTile(leading: const Icon(Icons.play_circle_outline), title: const Text('去看看'), onTap: () => Navigator.pop(ctx, 'watch')),
          ListTile(
            leading: Icon(Icons.delete_outline, color: Theme.of(ctx).sz.danger),
            title: Text('删除', style: TextStyle(color: Theme.of(ctx).sz.danger)),
            onTap: () => Navigator.pop(ctx, 'delete'),
          ),
        ]),
      ),
    );
    if (!mounted || k == null) return;
    switch (k) {
      case 'open':
        await _open(v);
      case 'edit':
        await _editItem(v);
      case 'watch':
        await openVideo(context, v.vid);
      case 'delete':
        await _delete(v);
    }
  }
}
