// 话题页:这个话题下的帖子,热门 / 最新两种排法(§8.3)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart' show CursorPager;
import '../models.dart';
import '../nav.dart';
import '../widgets/timeline.dart';

class TagPage extends StatefulWidget {
  const TagPage({super.key, required this.tag, required this.display});

  final String tag;
  final String display;

  @override
  State<TagPage> createState() => _TagPageState();
}

class _TagPageState extends State<TagPage> {
  String _sort = 'top';
  late CursorPager<FPost> _pager = _make();

  /// 热门按分数走 page,最新按时间走 cursor(§5.2)
  CursorPager<FPost> _make() => _sort == 'top'
      ? forumPagePager((page) => forumApi.tagPosts(widget.tag, sort: 'top', page: page))
      : forumCursorPager((cursor) => forumApi.tagPosts(widget.tag, sort: 'new', cursor: cursor));

  @override
  void initState() {
    super.initState();
    _pager.refresh();
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  void _setSort(String sort) {
    if (_sort == sort) return;
    setState(() {
      _sort = sort;
      _pager.dispose();
      _pager = _make()..refresh();
    });
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(title: Text('#${widget.display}')),
      floatingActionButton: FloatingActionButton(
        tooltip: '发一条带这个话题的',
        onPressed: () async {
          final made = await openCompose(context);
          if (made != null && mounted) await _pager.refresh();
        },
        child: const Icon(Icons.edit_outlined),
      ),
      body: ForumPostList(
        pager: _pager,
        emptyText: '这个话题下还没有帖子',
        header: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: kPagePad, vertical: 4),
            child: Row(children: [
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
          ),
          Divider(height: 1, color: sz.line),
        ],
      ),
    );
  }
}
