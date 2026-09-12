import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 视频 tab 在「竖屏」子页时为真:底部导航跟着换成深色(和抖音一样,
/// 黑底视频下面压一条白色导航,眼睛会被那条白边一直拽过去)
final ValueNotifier<bool> videoImmersive = ValueNotifier<bool>(false);

/// 底部「视频」tab:顶部搜索 + 投稿,下面「关注 / 推荐 / 热门 / 竖屏」四个子页。
class VideoTab extends StatefulWidget {
  const VideoTab({super.key, required this.api});

  final ApiClient api;

  @override
  State<VideoTab> createState() => _VideoTabState();
}

class _VideoTabState extends State<VideoTab> with SingleTickerProviderStateMixin {
  static const _tabs = ['关注', '推荐', '热门', '竖屏'];
  static const _vertical = 3;

  late final TabController _tc =
      TabController(length: _tabs.length, initialIndex: 1, vsync: this)
        ..addListener(_onTab);

  void _onTab() {
    final immersive = _tc.index == _vertical;
    if (videoImmersive.value != immersive) videoImmersive.value = immersive;
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
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
            padding: const EdgeInsets.fromLTRB(kPagePad, 8, 8, 0),
            child: Row(children: [
              Expanded(
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
                        style: TextStyle(
                            fontSize: kFontBody,
                            color: immersive ? Colors.white70 : sz.inkMuted)),
                  ]),
                ),
              ),
              IconButton(
                tooltip: '投稿',
                icon: Icon(Icons.add_circle_outline, color: fg),
                onPressed: null,
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
            children: [
              for (final t in _tabs)
                Center(
                  child: SzEmpty(text: t == '关注' ? '关注 UP 主后,他们的新视频会出现在这里' : '还没有视频'),
                ),
            ],
          ),
        ),
      ]),
    );
  }
}
