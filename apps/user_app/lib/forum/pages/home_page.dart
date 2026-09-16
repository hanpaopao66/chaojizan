// 论坛首页:推荐 / 关注两条时间线(§8.3),顶栏进我的主页 / 探索 / 书签 / 设置,右下角发帖。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart' show CursorPager, VideoLoginGate;
import '../models.dart';
import '../nav.dart';
import '../view_reporter.dart';
import '../widgets/common.dart';
import '../widgets/timeline.dart';

class ForumHomePage extends StatefulWidget {
  const ForumHomePage({super.key});

  @override
  State<ForumHomePage> createState() => _ForumHomePageState();
}

class _ForumHomePageState extends State<ForumHomePage> with SingleTickerProviderStateMixin {
  late final TabController _tab = TabController(length: 2, vsync: this);

  late final CursorPager<FTimelineItem> _foryou = forumPagePager((page) => forumApi.foryou(page));
  late final CursorPager<FTimelineItem> _following =
      forumCursorPager((cursor) => forumApi.followingTimeline(cursor: cursor));

  String? _device;

  @override
  void initState() {
    super.initState();
    _foryou.refresh();
    if (rootApi.isLoggedIn) _following.refresh();
    // 没登录也要上报浏览(F5 按设备去重),设备号异步取,取到之前先不带
    if (!rootApi.isLoggedIn) {
      forumDeviceId().then((id) {
        if (mounted) setState(() => _device = id);
      });
    }
    authTick.addListener(_onAuth);
  }

  void _onAuth() {
    if (!mounted) return;
    setState(() => _device = null);
    _foryou.refresh();
    _following.refresh();
  }

  @override
  void dispose() {
    authTick.removeListener(_onAuth);
    _tab.dispose();
    _foryou.dispose();
    _following.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: const Text('论坛'),
        actions: [
          IconButton(
            tooltip: '搜索和热门话题',
            onPressed: () => openExplore(context),
            icon: const Icon(Icons.search),
          ),
          PopupMenuButton<String>(
            tooltip: '更多',
            onSelected: (v) async {
              switch (v) {
                case 'me':
                  if (!await ensureLoggedIn(context)) return;
                  if (context.mounted && rootApi.userId != null) {
                    await openForumProfile(context, rootApi.userId!);
                  }
                case 'bookmarks':
                  if (!await ensureLoggedIn(context)) return;
                  if (context.mounted) await openBookmarks(context);
                case 'settings':
                  await openForumSettings(context);
              }
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'me', child: Text('我的主页')),
              PopupMenuItem(value: 'bookmarks', child: Text('书签')),
              PopupMenuItem(value: 'settings', child: Text('设置')),
            ],
          ),
        ],
        bottom: TabBar(
          controller: _tab,
          tabs: const [Tab(text: '推荐'), Tab(text: '关注')],
        ),
      ),
      floatingActionButton: FloatingActionButton(
        tooltip: '发帖',
        onPressed: _compose,
        child: const Icon(Icons.edit_outlined),
      ),
      body: TabBarView(
        controller: _tab,
        children: [
          ForumTimeline(
            pager: _foryou,
            showRank: true,
            deviceId: _device,
            emptyText: '还没有可推荐的帖子,去探索看看',
          ),
          rootApi.isLoggedIn
              ? ForumTimeline(
                  pager: _following,
                  emptyText: '关注几个人,他们的帖子会出现在这里',
                )
              : VideoLoginGate(text: '登录后能看到你关注的人发了什么', onLoggedIn: _onAuth),
        ],
      ),
    );
  }

  Future<void> _compose() async {
    final made = await openCompose(context);
    if (made == null || !mounted) return;
    fToast(context, '已发布');
    // 刚发的那条插到关注线最前面,推荐线整页重来(推荐分要服务端算)
    _following.upsert((x) => x.post.pid == made.pid, FTimelineItem.of(made), orInsert: true);
    await _foryou.refresh();
  }
}
