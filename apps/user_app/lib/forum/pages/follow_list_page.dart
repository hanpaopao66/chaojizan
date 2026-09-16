// 关注 / 粉丝列表(§8.4,全站一张表)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart' show CursorPager, PagedListView;
import '../models.dart';
import '../nav.dart';
import '../widgets/timeline.dart';
import 'people_page.dart' show FPersonTile;

class FollowListPage extends StatefulWidget {
  const FollowListPage({super.key, required this.userId, this.tab = 'followers'});

  final int userId;

  /// `followers` 粉丝 / `following` 关注
  final String tab;

  @override
  State<FollowListPage> createState() => _FollowListPageState();
}

class _FollowListPageState extends State<FollowListPage> with SingleTickerProviderStateMixin {
  late final TabController _tab =
      TabController(length: 2, vsync: this, initialIndex: widget.tab == 'following' ? 0 : 1);

  late final CursorPager<VPerson> _following =
      forumCursorPager((cursor) => forumApi.following(widget.userId, cursor: cursor));
  late final CursorPager<VPerson> _followers =
      forumCursorPager((cursor) => forumApi.followers(widget.userId, cursor: cursor));

  @override
  void initState() {
    super.initState();
    (widget.tab == 'following' ? _following : _followers).refresh();
    _tab.addListener(_onTab);
  }

  void _onTab() {
    if (_tab.indexIsChanging) return;
    final p = _tab.index == 0 ? _following : _followers;
    if (!p.loaded && !p.loading) p.refresh();
  }

  @override
  void dispose() {
    _tab.removeListener(_onTab);
    _tab.dispose();
    _following.dispose();
    _followers.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SzPageScaffold(
        appBar: AppBar(
          title: const Text('关注'),
          bottom: TabBar(controller: _tab, tabs: const [Tab(text: '关注'), Tab(text: '粉丝')]),
        ),
        body: TabBarView(controller: _tab, children: [
          PagedListView<VPerson>(
            pager: _following,
            emptyText: '还没有关注谁',
            itemBuilder: (context, p, _) => FPersonTile(person: p),
          ),
          PagedListView<VPerson>(
            pager: _followers,
            emptyText: '还没有人关注',
            itemBuilder: (context, p, _) => FPersonTile(person: p),
          ),
        ]),
      );
}
