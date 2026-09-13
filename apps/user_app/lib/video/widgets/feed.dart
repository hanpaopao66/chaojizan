import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../api.dart';
import '../models.dart';
import '../nav.dart';
import 'cards.dart';

/// 一页一页往下翻的卡片流(推荐 / 热门 / 关注 / 分区 / 空间投稿)。
///
/// [load] 给页号(page 分页)或游标(cursor 分页),两种都支持:第一次传 page=0、cursor=null,
/// 之后 page 分页的传 page+1,cursor 分页的传上一页的 next_cursor。按 vid 去重(推荐类翻页之间可能重复)。
class VideoFeed extends StatefulWidget {
  const VideoFeed({
    super.key,
    required this.load,
    this.emptyText = '还没有视频',
    this.header,
    this.showWhy = false,
    this.padding = const EdgeInsets.fromLTRB(10, 8, 10, 24),
    this.onPullRefresh,
    this.nested = false,
  });

  /// 放在 NestedScrollView 里(空间页的「投稿」):滚动交给外层协调,列表往上滑时头部跟着收起。
  /// 原来这里有自己的滚动控制器,外层协调不了,头部一直占着上半屏,列表只能在下面那一截里滚
  final bool nested;

  /// 下拉刷新时顺带刷新的东西(空间页头部的关注 / 粉丝 / 获赞):下拉的是整页,不能只刷下面这串卡片
  final Future<void> Function()? onPullRefresh;

  final Future<VPage<VideoCard>> Function(int page, String? cursor) load;
  final String emptyText;
  final Widget? header;

  /// 长按菜单里给「为什么推荐」(推荐、竖屏、相关)
  final bool showWhy;
  final EdgeInsets padding;

  @override
  State<VideoFeed> createState() => VideoFeedState();
}

class VideoFeedState extends State<VideoFeed> with AutomaticKeepAliveClientMixin {
  final List<VideoCard> _items = [];
  final Set<String> _seen = {};
  int _page = 0;
  String? _cursor;
  bool _more = true;
  bool _loading = false;
  Object? _error;
  bool _off = false;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  /// 离底部不到 600 就去拿下一页。听通知不挂控制器(嵌在 NestedScrollView 里时控制器归外层);
  /// 布局完成的 ScrollMetricsNotification 也听:一页没铺满屏幕时根本滑不动,不听它下一页永远不来
  bool _nearEnd(ScrollMetrics m, int depth) {
    if (depth == 0 && m.axis == Axis.vertical && m.extentAfter < 600) _loadMore();
    return false;
  }

  Future<void> _pullRefresh() => Future.wait([refresh(), if (widget.onPullRefresh != null) widget.onPullRefresh!()]);

  Future<void> refresh() async {
    _page = 0;
    _cursor = null;
    _more = true;
    _items.clear();
    _seen.clear();
    _error = null;
    await _loadMore(force: true);
  }

  Future<void> _loadMore({bool force = false}) async {
    if (_loading || (!_more && !force)) return;
    setState(() => _loading = true);
    try {
      final r = await widget.load(_page, _cursor);
      if (!mounted) return;
      setState(() {
        for (final c in r.items) {
          if (_seen.add(c.vid)) _items.add(c);
        }
        _more = r.more && r.items.isNotEmpty;
        _page += 1;
        _cursor = r.nextCursor;
        _error = null;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e;
          _off = VideoApi.isOff(e);
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _menu(VideoCard c) async {
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(title: Text(c.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
          const Divider(height: 1),
          if (widget.showWhy && c.why.isNotEmpty)
            ListTile(leading: const Icon(Icons.help_outline), title: const Text('为什么推荐给我'), onTap: () => Navigator.pop(ctx, 'why')),
          ListTile(leading: const Icon(Icons.watch_later_outlined), title: const Text('稍后再看'), onTap: () => Navigator.pop(ctx, 'later')),
          if (widget.showWhy)
            ListTile(leading: const Icon(Icons.not_interested), title: const Text('不感兴趣'), onTap: () => Navigator.pop(ctx, 'no')),
        ]),
      ),
    );
    if (pick == null || !mounted) return;
    if (pick == 'why') {
      await showWhySheet(context, c);
      return;
    }
    if (!await ensureLoggedIn(context)) return;
    try {
      if (pick == 'later') {
        await videoApi.addWatchLater(c.vid);
        _toast('已加入稍后再看');
      } else if (pick == 'no') {
        await videoApi.notInterested(c.vid);
        setState(() => _items.removeWhere((x) => x.vid == c.vid));
        _toast('好的,以后少推这类');
      }
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  void _toast(String s) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final sz = Theme.of(context).sz;
    if (_items.isEmpty) {
      Widget body;
      if (_loading) {
        body = const Center(child: CircularProgressIndicator());
      } else if (_off) {
        body = const SzEmpty(text: '视频功能暂未开放\n等拿到网络视听许可之后就会上线');
      } else if (_error != null) {
        body = SzError(error: _error, onRetry: refresh);
      } else {
        body = SzEmpty(text: widget.emptyText);
      }
      return RefreshIndicator(
        onRefresh: _pullRefresh,
        // 空着也能下拉刷新(不满一屏的列表默认滚不动,拖动不出滚动通知,下拉刷新就不会触发)
        child: ListView(physics: const AlwaysScrollableScrollPhysics(), children: [
          if (widget.header != null) widget.header!,
          SizedBox(height: 360, child: Center(child: body)),
        ]),
      );
    }
    return RefreshIndicator(
      onRefresh: _pullRefresh,
      // 只有一两条也能下拉刷新(比如空间页只有一个投稿):不满一屏时默认滚不动,下拉刷新收不到通知
      child: NotificationListener<ScrollMetricsNotification>(
        onNotification: (n) => _nearEnd(n.metrics, n.depth),
        child: NotificationListener<ScrollNotification>(
          onNotification: (n) => _nearEnd(n.metrics, n.depth),
          child: CustomScrollView(
              primary: widget.nested, physics: const AlwaysScrollableScrollPhysics(), slivers: [
            if (widget.header != null) SliverToBoxAdapter(child: widget.header),
            SliverPadding(
              padding: widget.padding,
              // 列数照「每列不超过 260」算(和 MaxCrossAxisExtent 同一个算法),格子高 = 封面 + 下面那块字
              sliver: SliverLayoutBuilder(builder: (context, constraints) {
                const gap = 10.0;
                final w = constraints.crossAxisExtent;
                final cols = math.max(1, (w / (260 + gap)).ceil());
                final cardW = (w - gap * (cols - 1)) / cols;
                return SliverGrid(
                  gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: cols,
                    mainAxisSpacing: gap,
                    crossAxisSpacing: gap,
                    mainAxisExtent: cardW / VideoGridCard.coverAspect + VideoGridCard.textBlockHeight(context),
                  ),
                  delegate: SliverChildBuilderDelegate(
                    (context, i) => VideoGridCard(card: _items[i], onLongPress: () => _menu(_items[i])),
                    childCount: _items.length,
                  ),
                );
              }),
            ),
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.only(bottom: 24),
                child: Center(
                  child: _loading
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : Text(_more ? '' : '没有更多了', style: TextStyle(color: sz.inkFaint, fontSize: kFontNote)),
                ),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}

/// 「为什么推荐」:把算分的中间量摊开给人看(推荐公式是公开的,S3 / D12)。
Future<void> showWhySheet(BuildContext context, VideoCard c) {
  final r = c.rank;
  final counts = vMap(r['counts']);
  String n(Object? v) => '${v ?? 0}';
  return szShowSheet<void>(
    context: context,
    builder: (ctx) {
      final sz = Theme.of(ctx).sz;
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(kPagePad),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            const Text('为什么推荐给你', style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
            const SizedBox(height: 10),
            for (final w in c.why) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('· $w')),
            if (counts.isNotEmpty) ...[
              const SizedBox(height: 10),
              Text(
                '近 72 小时:播放 ${n(counts['views'])} · 赞 ${n(counts['likes'])} · 硬币 ${n(counts['coins'])} · '
                '收藏 ${n(counts['favorites'])} · 评论 ${n(counts['comments'])} · 弹幕 ${n(counts['danmaku'])} · 分享 ${n(counts['shares'])}',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
              ),
              const SizedBox(height: 4),
              Text(
                '互动分 ${n(r['interaction'])},热度 ${(vDouble(r['hot'])).toStringAsFixed(2)},'
                '推荐分 ${(vDouble(r['recommend'])).toStringAsFixed(2)}',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
              ),
            ],
            const SizedBox(height: 12),
            Text(
              '推荐只按公开的公式排:互动分 ÷(发布小时数 + 2)^1.5,关注的 UP 主 +30%、常看的分区 +15%。'
              '没有任何付费或运营加权。不想要个性化可以在「视频设置」里关掉。',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
            ),
          ]),
        ),
      );
    },
  );
}

/// 每天第一次打开视频 tab 领 1 枚硬币(D13;服务端按北京日期一天一次,这里只是触发)。
Future<void> claimDailyCoin(BuildContext context) async {
  if (!rootApi.isLoggedIn) return;
  try {
    final r = await videoApi.claimDailyCoin();
    if (r['granted'] == true && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('今天第一次看视频,硬币 +1(现在 ${r['coins']} 枚)')));
    }
  } catch (_) {}
}

/// 不重复触发:一个进程里只领一次(tab 切来切去不用每次都打接口)
bool _dailyAsked = false;
void claimDailyCoinOnce(BuildContext context) {
  // 游客打开不算:登录之后再打开要能领到
  if (_dailyAsked || !rootApi.isLoggedIn) return;
  _dailyAsked = true;
  unawaited(claimDailyCoin(context));
}
