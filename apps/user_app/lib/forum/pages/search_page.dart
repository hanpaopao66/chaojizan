// 搜索结果:帖子 / 用户 / 话题三个页签(§8.3 `/search?type=`)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart' show CursorPager, PagedListView;
import '../models.dart';
import '../nav.dart';
import '../widgets/timeline.dart';
import 'people_page.dart' show FPersonTile;

class ForumSearchPage extends StatefulWidget {
  const ForumSearchPage({super.key, this.initial = ''});

  final String initial;

  @override
  State<ForumSearchPage> createState() => _ForumSearchPageState();
}

class _ForumSearchPageState extends State<ForumSearchPage> with SingleTickerProviderStateMixin {
  late final TabController _tab = TabController(length: 3, vsync: this);
  late final TextEditingController _q = TextEditingController(text: widget.initial);

  /// 真正在搜的那个词。输入框里改字不立刻搜 —— 回车或点搜索才搜(搜索每分钟 60 次,§5.10)
  String _term = '';

  CursorPager<FPost>? _posts;
  CursorPager<VPerson>? _users;
  CursorPager<FTrendingTag>? _tags;

  @override
  void initState() {
    super.initState();
    if (widget.initial.trim().isNotEmpty) _search(widget.initial);
  }

  @override
  void dispose() {
    _tab.dispose();
    _q.dispose();
    _posts?.dispose();
    _users?.dispose();
    _tags?.dispose();
    super.dispose();
  }

  void _search(String raw) {
    final q = raw.trim();
    if (q.isEmpty) return;
    setState(() {
      _term = q;
      _posts?.dispose();
      _users?.dispose();
      _tags?.dispose();
      _posts = forumPagePager((page) => forumApi.searchPosts(q, page: page))..refresh();
      _users = forumPagePager((page) => forumApi.searchUsers(q, page: page))..refresh();
      _tags = forumPagePager((page) => forumApi.searchTags(q, page: page))..refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: TextField(
          controller: _q,
          autofocus: widget.initial.isEmpty,
          textInputAction: TextInputAction.search,
          onSubmitted: _search,
          decoration: const InputDecoration(border: InputBorder.none, hintText: '搜帖子、人、话题'),
        ),
        actions: [
          IconButton(onPressed: () => _search(_q.text), icon: const Icon(Icons.search)),
        ],
        bottom: TabBar(
          controller: _tab,
          tabs: const [Tab(text: '帖子'), Tab(text: '用户'), Tab(text: '话题')],
        ),
      ),
      body: _term.isEmpty
          ? const SzEmpty(text: '输入几个字,回车开始搜')
          : TabBarView(
              controller: _tab,
              children: [
                ForumPostList(pager: _posts!, emptyText: '没有搜到帖子'),
                PagedListView<VPerson>(
                  pager: _users!,
                  emptyText: '没有搜到人',
                  itemBuilder: (context, p, _) => FPersonTile(person: p),
                ),
                PagedListView<FTrendingTag>(
                  pager: _tags!,
                  emptyText: '没有搜到话题',
                  itemBuilder: (context, t, _) => ListTile(
                    title: Text('#${t.display}', style: const TextStyle(fontWeight: FontWeight.w600)),
                    subtitle: t.authors24h > 0
                        ? Text('近 24 小时 ${t.authors24h} 人用过',
                            style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))
                        : null,
                    onTap: () => openTag(context, t.tag, display: t.display),
                  ),
                ),
              ],
            ),
    );
  }
}
