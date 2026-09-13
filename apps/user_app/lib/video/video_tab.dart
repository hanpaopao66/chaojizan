import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../chat/store.dart';
import '../chat/ui/avatar.dart';
import '../session.dart';
import 'me/video_me_page.dart';
import 'nav.dart';
import 'pages/search_page.dart';
import 'pages/upload_entry.dart';
import 'pages/zones_page.dart';
import 'vertical/vertical_feed.dart';
import 'widgets/feed.dart';

/// 视频 tab 在「竖屏」子页时为真:底部导航跟着换成深色(和抖音一样,
/// 黑底视频下面压一条白色导航,眼睛会被那条白边一直拽过去)
final ValueNotifier<bool> videoImmersive = ValueNotifier<bool>(false);

/// 底部「视频」tab(DEV-PROMPTS-40 #364):顶部搜索 + 分区 + 投稿,下面「关注 / 推荐 / 热门 / 竖屏」四个子页。
class VideoTab extends StatefulWidget {
  const VideoTab({super.key, required this.api});

  final ApiClient api;

  @override
  State<VideoTab> createState() => _VideoTabState();
}

class _VideoTabState extends State<VideoTab> with SingleTickerProviderStateMixin {
  static const _tabs = ['关注', '推荐', '热门', '竖屏'];
  static const _vertical = 3;

  late final TabController _tc = TabController(length: _tabs.length, initialIndex: 1, vsync: this)
    ..addListener(_onTab);

  /// 登录状态变了,关注页要重拉(没登录时它显示的是「登录后看关注」)
  Key _followKey = UniqueKey();

  void _onTab() {
    final immersive = _tc.index == _vertical;
    if (videoImmersive.value != immersive) videoImmersive.value = immersive;
    if (mounted) setState(() {});
  }

  @override
  void initState() {
    super.initState();
    authTick.addListener(_onAuth);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) claimDailyCoinOnce(context);
    });
  }

  void _onAuth() {
    if (!mounted) return;
    setState(() => _followKey = UniqueKey());
    claimDailyCoinOnce(context);
  }

  @override
  void dispose() {
    authTick.removeListener(_onAuth);
    _tc.dispose();
    videoImmersive.value = false;
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final immersive = _tc.index == _vertical;
    final fg = immersive ? Colors.white : sz.ink;
    return ColoredBox(
      color: immersive ? Colors.black : Theme.of(context).scaffoldBackgroundColor,
      child: Column(children: [
        SafeArea(
          bottom: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 8, 4, 0),
            child: Row(children: [
              // 左上角头像 = 「我的视频」(B 站首页的位置):历史、收藏、稍后再看、创作中心都在里面
              Padding(
                padding: const EdgeInsets.only(right: 10),
                child: Semantics(
                  button: true,
                  label: '我的视频',
                  child: GestureDetector(
                    onTap: () => openVideoMe(context),
                    child: ChatAvatar(
                        name: rootApi.userName ?? '我',
                        url: ChatStore.instance.users[rootApi.userId]?.avatar ?? '',
                        size: 32),
                  ),
                ),
              ),
              Expanded(
                child: Semantics(
                  button: true,
                  label: '搜索视频、UP 主',
                  child: GestureDetector(
                    onTap: () => Navigator.of(context)
                        .push(MaterialPageRoute<void>(builder: (_) => const VideoSearchPage())),
                    child: Container(
                      height: 36,
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      decoration: BoxDecoration(
                        color: immersive ? Colors.white.withValues(alpha: .14) : sz.surfaceAlt,
                        borderRadius: BorderRadius.circular(18),
                      ),
                      child: Row(children: [
                        Icon(Icons.search, size: 18, color: immersive ? Colors.white70 : sz.inkMuted),
                        const SizedBox(width: 6),
                        Text('搜索视频、UP 主',
                            style: TextStyle(fontSize: kFontBody, color: immersive ? Colors.white70 : sz.inkMuted)),
                      ]),
                    ),
                  ),
                ),
              ),
              IconButton(
                tooltip: '分区和排行榜',
                icon: Icon(Icons.grid_view_outlined, color: fg),
                onPressed: () =>
                    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ZonesPage())),
              ),
              IconButton(
                tooltip: '投稿',
                icon: Icon(Icons.add_circle_outline, color: fg),
                onPressed: () => openUpload(context),
              ),
            ]),
          ),
        ),
        TabBar(
          controller: _tc,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          labelColor: fg,
          unselectedLabelColor: immersive ? Colors.white60 : sz.inkMuted,
          indicatorColor: immersive ? Colors.white : sz.clay,
          dividerColor: Colors.transparent,
          tabs: [for (final t in _tabs) Tab(text: t)],
        ),
        Expanded(
          child: TabBarView(
            controller: _tc,
            // 竖屏页自己吃上下滑;左右滑切页签会和它的「左滑进 UP 主空间」打架,所以禁掉整体左右滑
            physics: immersive ? const NeverScrollableScrollPhysics() : null,
            children: [
              _FollowingFeed(key: _followKey),
              VideoFeed(
                load: (page, _) => videoApi.recommend(page),
                showWhy: true,
                emptyText: '还没有视频\n投第一个稿吧',
              ),
              VideoFeed(
                load: (page, _) => videoApi.hot(page),
                header: _HotHeader(),
                emptyText: '还没有热门视频',
              ),
              VerticalFeed(active: immersive, onGoHot: () => _tc.animateTo(2)),
            ],
          ),
        ),
      ]),
    );
  }
}

class _FollowingFeed extends StatelessWidget {
  const _FollowingFeed({super.key});

  @override
  Widget build(BuildContext context) {
    if (!rootApi.isLoggedIn) {
      return Center(
        child: SzEmpty(
          text: '登录后,关注的 UP 主的新视频会出现在这里',
          actionLabel: '登录',
          onAction: () => ensureLoggedIn(context),
        ),
      );
    }
    return VideoFeed(
      load: (_, cursor) => videoApi.following(cursor),
      emptyText: '关注 UP 主后,他们的新视频会出现在这里',
    );
  }
}

/// 热门页顶上:排行榜入口(热门和排行榜同一套公开公式,D12)
class _HotHeader extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 0),
      child: Material(
        color: sz.claySoft,
        borderRadius: BorderRadius.circular(kRadiusMd),
        child: InkWell(
          borderRadius: BorderRadius.circular(kRadiusMd),
          onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const RankPage())),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            child: Row(children: [
              Icon(Icons.leaderboard_outlined, color: sz.clay),
              const SizedBox(width: 10),
              const Expanded(child: Text('排行榜 · 全站和各分区,1 / 3 / 7 天', style: TextStyle(fontWeight: FontWeight.w600))),
              Icon(Icons.chevron_right, color: sz.inkMuted),
            ]),
          ),
        ),
      ),
    );
  }
}
