// 论坛个人主页:头像签名、关注 / 粉丝、关注按钮、发消息、置顶、
// 帖子 / 回复 / 媒体 / 喜欢四个页签(§8.3)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/chat_page.dart' show openPrivateWith;
import '../../session.dart';
import '../../video/me/common.dart' show CursorPager, vDateTime;
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';
import '../widgets/post_tile.dart';
import '../widgets/timeline.dart';

/// 主页的四个页签(§8.3 `tab=`)。
const _tabs = <String, String>{
  'posts': '帖子',
  'replies': '回复',
  'media': '媒体',
  'likes': '喜欢',
};

class ForumProfilePage extends StatefulWidget {
  const ForumProfilePage({super.key, required this.userId});

  final int userId;

  @override
  State<ForumProfilePage> createState() => _ForumProfilePageState();
}

class _ForumProfilePageState extends State<ForumProfilePage> with SingleTickerProviderStateMixin {
  late final TabController _tab = TabController(length: _tabs.length, vsync: this);
  late final Map<String, CursorPager<FTimelineItem>> _pagers = {
    for (final key in _tabs.keys)
      key: forumCursorPager((cursor) => forumApi.userPosts(widget.userId, tab: key, cursor: cursor)),
  };

  FProfile? _profile;
  Object? _error;
  bool _busy = false;

  bool get _isMe => rootApi.userId != null && rootApi.userId == widget.userId;

  @override
  void initState() {
    super.initState();
    _load();
    _pagers['posts']!.refresh();
    _tab.addListener(_onTab);
  }

  void _onTab() {
    if (_tab.indexIsChanging) return;
    final key = _tabs.keys.elementAt(_tab.index);
    final p = _pagers[key]!;
    if (!p.loaded && !p.loading) p.refresh();
  }

  @override
  void dispose() {
    _tab.removeListener(_onTab);
    _tab.dispose();
    for (final p in _pagers.values) {
      p.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final p = await forumApi.profile(widget.userId);
      if (mounted) setState(() => _profile = p);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _toggleFollow() async {
    if (!await ensureLoggedIn(context)) return;
    final p = _profile;
    if (p == null || !mounted) return;
    setState(() => _busy = true);
    try {
      // 关注走全站那张表(§8.4),不是论坛自己的接口
      final r = await forumApi.follow(widget.userId, !p.followed);
      if (mounted) {
        setState(() => _profile = p.copyWith(followed: r['followed'] == true, fans: vInt(r['fans'])));
      }
    } on ApiException catch (e) {
      if (mounted) fToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 私信直接用聊天,不另做(§2.2)。要登录 —— 聊天没登录根本没启动。
  Future<void> _message() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    await openPrivateWith(context, widget.userId);
  }

  @override
  Widget build(BuildContext context) {
    final p = _profile;
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: Text(p?.user.name ?? '主页'),
        bottom: p == null
            ? null
            : TabBar(controller: _tab, tabs: [for (final t in _tabs.values) Tab(text: t)]),
      ),
      body: p == null
          ? (_error != null
              ? forumErrorView(_error, () {
                  setState(() => _error = null);
                  _load();
                })
              : const Center(child: CircularProgressIndicator()))
          : TabBarView(
              controller: _tab,
              children: [
                for (final key in _tabs.keys)
                  ForumTimeline(
                    pager: _pagers[key]!,
                    emptyText: _emptyOf(key),
                    header: key == 'posts' ? _header(context, p) : const [],
                  ),
              ],
            ),
    );
  }

  String _emptyOf(String key) => switch (key) {
        'replies' => '还没有回复过别人',
        'media' => '还没有发过带图的帖子',
        'likes' => _isMe ? '你还没有赞过谁' : '他还没有赞过谁',
        _ => _isMe ? '你还没有发过帖' : '他还没有发过帖',
      };

  List<Widget> _header(BuildContext context, FProfile p) {
    final sz = Theme.of(context).sz;
    return [
      Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SzImage(url: forumResolve(p.user.avatar), name: p.user.name, size: 64, circle: true),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(
                    child: Text(p.user.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: kFontLead, fontWeight: FontWeight.w700)),
                  ),
                  if (p.followsYou)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                      decoration: BoxDecoration(
                        border: Border.all(color: sz.line),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text('关注了你', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
                    ),
                ]),
                if ((p.user.username ?? '').isNotEmpty)
                  Text('@${p.user.username}', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
            ),
          ]),
          if (p.bio.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(p.bio, style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, height: 1.5)),
            ),
          if (p.joinedAt != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(children: [
                Icon(Icons.schedule, size: 14, color: sz.inkFaint),
                const SizedBox(width: 4),
                Text('${vDateTime(p.joinedAt!)} 加入',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
            ),
          const SizedBox(height: 10),
          Row(children: [
            _stat(context, p.following, '关注', () => openFollowList(context, widget.userId, tab: 'following')),
            const SizedBox(width: 16),
            _stat(context, p.fans, '粉丝', () => openFollowList(context, widget.userId, tab: 'followers')),
            const SizedBox(width: 16),
            _stat(context, p.posts, '帖子', null),
          ]),
          const SizedBox(height: 12),
          if (!_isMe)
            Row(children: [
              Expanded(
                child: p.followed
                    ? OutlinedButton(onPressed: _busy ? null : _toggleFollow, child: const Text('已关注'))
                    : FilledButton(onPressed: _busy ? null : _toggleFollow, child: const Text('+ 关注')),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _message,
                  icon: const Icon(Icons.chat_bubble_outline, size: 16),
                  label: const Text('发消息'),
                ),
              ),
            ])
          else
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: () => openForumSettings(context),
                icon: const Icon(Icons.tune, size: 16),
                label: const Text('论坛设置'),
              ),
            ),
          const SizedBox(height: 12),
        ]),
      ),
      if (p.pinned != null) ...[
        Divider(height: 1, color: sz.line),
        PostTile(
          post: p.pinned!,
          onTap: p.pinned!.unavailable ? null : () => openPost(context, p.pinned!.pid),
          onChanged: () => setState(() {}),
          onDeleted: (_) => _load(),
        ),
      ],
      Divider(height: 1, color: sz.line),
    ];
  }

  Widget _stat(BuildContext context, int n, String label, VoidCallback? onTap) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Text('$n', style: szTabular(fontSize: kFontBodyLg, fontWeight: FontWeight.w700, color: sz.ink)),
          const SizedBox(width: 3),
          Text(label, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ]),
      ),
    );
  }
}
