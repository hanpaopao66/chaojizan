// 书签(F2:只有自己看得见)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart' show CursorPager, VideoLoginGate;
import '../models.dart';
import '../nav.dart';
import '../widgets/timeline.dart';

class BookmarksPage extends StatefulWidget {
  const BookmarksPage({super.key});

  @override
  State<BookmarksPage> createState() => _BookmarksPageState();
}

class _BookmarksPageState extends State<BookmarksPage> {
  late final CursorPager<FPost> _pager = forumCursorPager((cursor) => forumApi.bookmarks(cursor: cursor));

  @override
  void initState() {
    super.initState();
    if (rootApi.isLoggedIn) _pager.refresh();
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SzPageScaffold(
        contentMaxWidth: kFeedMaxWidth,
        appBar: AppBar(title: const Text('书签')),
        body: rootApi.isLoggedIn
            ? ForumPostList(pager: _pager, emptyText: '还没有加过书签。书签只有你看得到')
            : VideoLoginGate(text: '登录后能收藏帖子,只有你看得到', onLoggedIn: _pager.refresh),
      );
}
