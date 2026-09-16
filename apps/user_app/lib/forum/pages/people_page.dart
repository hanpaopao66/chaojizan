// 人的列表:点赞这条的人、引用这条的人,和列表里一行人长什么样。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart' show CursorPager, PagedListView;
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';
import '../widgets/timeline.dart';

/// 列表里的一个人:头像、名字、@号,右边一个关注按钮(§8.4 的全站关注)。
class FPersonTile extends StatefulWidget {
  const FPersonTile({super.key, required this.person, this.showFollow = true});

  final VPerson person;
  final bool showFollow;

  @override
  State<FPersonTile> createState() => _FPersonTileState();
}

class _FPersonTileState extends State<FPersonTile> {
  late VPerson _p = widget.person;
  bool _busy = false;

  bool get _isMe => rootApi.userId != null && rootApi.userId == _p.id;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ListTile(
      leading: SzImage(url: forumResolve(_p.avatar), name: _p.name, size: 40, circle: true),
      title: Text(_p.name, maxLines: 1, overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: (_p.username ?? '').isEmpty
          ? (_p.bio.isEmpty ? null : Text(_p.bio, maxLines: 1, overflow: TextOverflow.ellipsis))
          : Text('@${_p.username}', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      trailing: widget.showFollow && !_isMe
          ? (_p.followed
              ? OutlinedButton(
                  style: OutlinedButton.styleFrom(visualDensity: VisualDensity.compact),
                  onPressed: _busy ? null : _toggle,
                  child: const Text('已关注'))
              : FilledButton(
                  style: FilledButton.styleFrom(visualDensity: VisualDensity.compact),
                  onPressed: _busy ? null : _toggle,
                  child: const Text('+ 关注')))
          : null,
      onTap: () => openForumProfile(context, _p.id),
    );
  }

  Future<void> _toggle() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    setState(() => _busy = true);
    try {
      final r = await forumApi.follow(_p.id, !_p.followed);
      if (mounted) {
        setState(() => _p = _p.copyWith(followed: r['followed'] == true, fans: vInt(r['fans'])));
      }
    } on ApiException catch (e) {
      if (mounted) fToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

/// 点赞这条帖子的人。
class LikersPage extends StatefulWidget {
  const LikersPage({super.key, required this.pid});

  final String pid;

  @override
  State<LikersPage> createState() => _LikersPageState();
}

class _LikersPageState extends State<LikersPage> {
  late final CursorPager<VPerson> _pager =
      forumCursorPager((cursor) => forumApi.likers(widget.pid, cursor: cursor))..refresh();

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SzPageScaffold(
        appBar: AppBar(title: const Text('赞过的人')),
        body: PagedListView<VPerson>(
          pager: _pager,
          emptyText: '还没有人赞过',
          itemBuilder: (context, p, _) => FPersonTile(person: p),
        ),
      );
}

/// 引用这条帖子的帖子。
class QuotesPage extends StatefulWidget {
  const QuotesPage({super.key, required this.pid});

  final String pid;

  @override
  State<QuotesPage> createState() => _QuotesPageState();
}

class _QuotesPageState extends State<QuotesPage> {
  late final CursorPager<FPost> _pager =
      forumCursorPager((cursor) => forumApi.quotes(widget.pid, cursor: cursor))..refresh();

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SzPageScaffold(
        contentMaxWidth: kFeedMaxWidth,
        appBar: AppBar(title: const Text('引用')),
        body: ForumPostList(pager: _pager, emptyText: '还没有人引用过这条'),
      );
}
