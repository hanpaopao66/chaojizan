// 一条时间线:下拉刷新、滚到底续页、浏览上报、空状态、失败可重试。
// 首页两条线、话题页、书签、主页四个页签、搜索结果全走它。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart' show CursorPager, PagedListView;
import '../models.dart';
import '../nav.dart';
import '../view_reporter.dart';
import 'post_tile.dart';

/// 按 `page` 翻的接口(推荐、搜索、话题热门)也塞进 [CursorPager]:
/// 把页码当游标用 —— 服务端只给 `has_more`,页码是客户端自己数的。
CursorPager<T> forumPagePager<T>(Future<VPage<T>> Function(int page) fetch) {
  return CursorPager<T>((cursor) async {
    final page = int.tryParse(cursor ?? '0') ?? 0;
    final r = await fetch(page);
    return (items: r.items, next: r.hasMore ? '${page + 1}' : null, extra: r.extra);
  });
}

/// 按 `cursor` 翻的接口(关注、回复、书签、话题最新)。
CursorPager<T> forumCursorPager<T>(Future<VPage<T>> Function(String? cursor) fetch) {
  return CursorPager<T>((cursor) async {
    final r = await fetch(cursor);
    return (items: r.items, next: r.nextCursor, extra: r.extra);
  });
}

/// 帖子列表。条目一露面就攒进浏览上报(F5)。
class ForumTimeline extends StatefulWidget {
  const ForumTimeline({
    super.key,
    required this.pager,
    this.header = const [],
    this.emptyText = '这里还没有帖子',
    this.showRank = false,
    this.deviceId,
  });

  final CursorPager<FTimelineItem> pager;
  final List<Widget> header;
  final String emptyText;

  /// 推荐时间线:每条底下给一行「为什么推荐」(§5.7 的中间量)
  final bool showRank;

  /// 没登录时浏览上报带的设备号
  final String? deviceId;

  @override
  State<ForumTimeline> createState() => _ForumTimelineState();
}

class _ForumTimelineState extends State<ForumTimeline> {
  late final ForumViewReporter _views = ForumViewReporter(
    (pids, deviceId) => forumApi.reportViews(pids, deviceId: deviceId),
    deviceId: widget.deviceId,
  );

  @override
  void dispose() {
    _views.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return PagedListView<FTimelineItem>(
      pager: widget.pager,
      header: widget.header,
      emptyText: widget.emptyText,
      divider: false,
      itemBuilder: (context, item, i) {
        // 画出来就算展示过了。攒够 50 条或者 5 秒发一次,不是一条一个请求
        _views.saw(item.post);
        return Column(children: [
          if (i > 0) Divider(height: 1, color: sz.line),
          PostTile(
            post: item.post,
            repostBy: item.isRepost ? item.by : null,
            repostAt: item.isRepost ? item.at : null,
            showRank: widget.showRank,
            onTap: item.post.unavailable ? null : () => openPost(context, item.post.pid),
            onChanged: widget.pager.touch,
            onDeleted: (pid) => widget.pager.removeWhere((x) => x.post.pid == pid),
          ),
        ]);
      },
    );
  }
}

/// 裸帖子的列表(书签、话题、搜索结果):包成条目后走同一套。
class ForumPostList extends StatelessWidget {
  const ForumPostList({
    super.key,
    required this.pager,
    this.header = const [],
    this.emptyText = '这里还没有帖子',
  });

  final CursorPager<FPost> pager;
  final List<Widget> header;
  final String emptyText;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return PagedListView<FPost>(
      pager: pager,
      header: header,
      emptyText: emptyText,
      divider: false,
      itemBuilder: (context, post, i) => Column(children: [
        if (i > 0) Divider(height: 1, color: sz.line),
        PostTile(
          post: post,
          onTap: post.unavailable ? null : () => openPost(context, post.pid),
          onChanged: pager.touch,
          onDeleted: (pid) => pager.removeWhere((x) => x.pid == pid),
        ),
      ]),
    );
  }
}
