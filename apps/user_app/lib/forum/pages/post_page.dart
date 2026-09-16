// 帖子详情:上文串 + 本帖 + 回复(热门 / 最新)+ 底下的回复框(§8.3)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart' show CursorPager;
import '../models.dart';
import '../nav.dart';
import '../view_reporter.dart';
import '../widgets/common.dart';
import '../widgets/post_tile.dart';
import '../widgets/timeline.dart';

class PostPage extends StatefulWidget {
  const PostPage({super.key, required this.pid});

  final String pid;

  @override
  State<PostPage> createState() => _PostPageState();
}

class _PostPageState extends State<PostPage> {
  FPost? _post;

  /// 上文串:从最早那条到被回复的那条(中间可能夹着占位)
  List<FPost> _ancestors = const [];
  Object? _error;
  String _sort = 'top';
  CursorPager<FPost>? _replies;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _replies?.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await forumApi.post(widget.pid);
      if (!mounted) return;
      setState(() {
        _post = r.post;
        _ancestors = r.ancestors;
        _error = null;
        _replies?.dispose();
        _replies = forumCursorPager((cursor) => forumApi.replies(widget.pid, sort: _sort, cursor: cursor))
          ..refresh();
      });
      // 详情页也算一次浏览(F5,服务端按人按天去重)
      final device = rootApi.isLoggedIn ? null : await forumDeviceId();
      await forumApi.reportViews([widget.pid], deviceId: device);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  void _setSort(String sort) {
    if (_sort == sort) return;
    setState(() {
      _sort = sort;
      _replies?.dispose();
      _replies = forumCursorPager((cursor) => forumApi.replies(widget.pid, sort: _sort, cursor: cursor))
        ..refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final post = _post;
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(title: const Text('帖子')),
      body: post == null
          ? (_error != null
              ? forumErrorView(_error, () {
                  setState(() => _error = null);
                  _load();
                })
              : const Center(child: CircularProgressIndicator()))
          : Column(children: [
              Expanded(
                child: ForumPostList(
                  pager: _replies!,
                  emptyText: post.canReply ? '还没有人回复,来说第一句' : '还没有人回复',
                  header: [
                    // 上文串:每条底下连一条竖线,一眼看出是一串
                    for (final a in _ancestors)
                      PostTile(
                        post: a,
                        threadLine: true,
                        onTap: a.unavailable ? null : () => openPost(context, a.pid),
                      ),
                    PostTile(
                      post: post,
                      detail: true,
                      onChanged: () => setState(() {}),
                      onDeleted: (_) => Navigator.of(context).maybePop(),
                    ),
                    Divider(height: 1, color: sz.line),
                    _sortRow(sz),
                    Divider(height: 1, color: sz.line),
                  ],
                ),
              ),
              Divider(height: 1, color: sz.line),
              _replyBar(context, sz, post),
            ]),
    );
  }

  Widget _sortRow(SzColors sz) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: kPagePad, vertical: 4),
        child: Row(children: [
          Text('回复', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          const Spacer(),
          for (final e in const {'top': '热门', 'new': '最新'}.entries)
            TextButton(
              style: TextButton.styleFrom(
                foregroundColor: _sort == e.key ? sz.clay : sz.inkMuted,
                visualDensity: VisualDensity.compact,
              ),
              onPressed: () => _setSort(e.key),
              child: Text(e.value,
                  style: TextStyle(fontSize: kFontNote, fontWeight: _sort == e.key ? FontWeight.w700 : null)),
            ),
        ]),
      );

  /// 底下那条回复框。「谁能回复」限制到我头上时置灰,并写清楚只有谁能回(F4)。
  Widget _replyBar(BuildContext context, SzColors sz, FPost post) {
    final can = post.canReply;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 6, kPagePad, 6),
        child: Row(children: [
          Expanded(
            child: GestureDetector(
              onTap: can ? () => _reply(post) : () => fToast(context, '这条帖子只有${post.replyPolicyName}能回复'),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: sz.surfaceAlt,
                  borderRadius: BorderRadius.circular(kRadiusLg),
                  border: Border.all(color: sz.line),
                ),
                child: Text(
                  can ? '说点什么…' : '只有${post.replyPolicyName}能回复',
                  style: TextStyle(fontSize: kFontBody, color: can ? sz.inkMuted : sz.inkFaint),
                ),
              ),
            ),
          ),
          const SizedBox(width: 8),
          IconButton(
            tooltip: can ? '回复' : '只有${post.replyPolicyName}能回复',
            onPressed: can ? () => _reply(post) : null,
            icon: const Icon(Icons.send_outlined),
          ),
        ]),
      ),
    );
  }

  Future<void> _reply(FPost post) async {
    final made = await openCompose(context, replyToPid: post.pid, origin: post);
    if (made == null || !mounted) return;
    post.counts.replies++;
    // 刚回的那条插到最前面,不等下一次刷新
    _replies?.upsert((x) => x.pid == made.pid, made, orInsert: true);
    setState(() {});
  }
}
