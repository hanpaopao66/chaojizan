// 音乐首页(§8.2 GET /home):「发现 / 我的」两页签,顶上一个搜索框。
//
// 发现页照网易云的骨架:每日推荐、推荐歌单、新歌、榜单前三、曲风。
// 不接商业曲库 —— 这里所有的歌都是音乐人自己传上来的原创或已获授权作品(§2.1)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';
import 'my_music_page.dart';

class MusicHomePage extends StatefulWidget {
  const MusicHomePage({super.key});

  @override
  State<MusicHomePage> createState() => _MusicHomePageState();
}

class _MusicHomePageState extends State<MusicHomePage> with SingleTickerProviderStateMixin {
  late final TabController _tc = TabController(length: 2, vsync: this);

  @override
  void dispose() {
    _tc.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: const Text('音乐'),
        actions: [
          IconButton(
            icon: const Icon(Icons.search),
            tooltip: '搜索',
            onPressed: () => openMusicSearch(context),
          ),
          IconButton(
            icon: const Icon(Icons.mic_external_on_outlined),
            tooltip: '音乐人中心',
            onPressed: () => openMusicStudio(context),
          ),
        ],
        bottom: TabBar(controller: _tc, tabs: const [Tab(text: '发现'), Tab(text: '我的')]),
      ),
      body: TabBarView(controller: _tc, children: const [MusicDiscoverView(), MyMusicView()]),
    );
  }
}

/// 「发现」那一页。
class MusicDiscoverView extends StatelessWidget {
  const MusicDiscoverView({super.key});

  @override
  Widget build(BuildContext context) {
    return MLoader<MHome>(
      load: () => musicApi.home(),
      builder: (context, home, reload) => ListView(
        padding: const EdgeInsets.only(bottom: 24),
        children: [
          _SearchBox(onTap: () => openMusicSearch(context)),
          if (home.genres.isNotEmpty) _Genres(genres: home.genres),
          if (home.daily.isNotEmpty) ...[
            MSection(
              '每日推荐',
              note: home.dailyPersonalized ? '按你听过、喜欢过的算,公式公开' : '已关掉个性化,按热歌榜分数排',
              onMore: () => openMusicDaily(context),
              moreLabel: '全部 >',
            ),
            for (final t in home.daily) MTrackTile(track: t, queue: home.daily, contextKey: 'daily', showRank: true),
          ],
          if (home.charts.isNotEmpty) ...[
            MSection('榜单', note: '公式公开,每首歌都带算分的中间量', onMore: () => openMusicCharts(context), moreLabel: '全部 >'),
            for (final c in home.charts) _ChartCard(chart: c),
          ],
          if (home.playlists.isNotEmpty) ...[
            const MSection('推荐歌单', note: '至少 5 首歌的公开歌单才推荐'),
            _Row(
              height: 186,
              children: [for (final p in home.playlists) MPlaylistCard(playlist: p, showRank: true)],
            ),
          ],
          if (home.newTracks.isNotEmpty) ...[
            const MSection('新歌'),
            for (final t in home.newTracks) MTrackTile(track: t, queue: home.newTracks, contextKey: 'new'),
          ],
          if (home.daily.isEmpty && home.charts.isEmpty && home.newTracks.isEmpty && home.playlists.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 40),
              child: SzEmpty(
                text: '还没有上架的作品。\n音乐人传上来、过了审就会出现在这里',
                actionLabel: '开通音乐人',
                onAction: () => openMusicStudio(context),
              ),
            ),
        ],
      ),
    );
  }
}

class _SearchBox extends StatelessWidget {
  const _SearchBox({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(kRadiusLg),
        child: Container(
          height: 40,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: ShapeDecoration(
            color: sz.surfaceAlt,
            shape: StadiumBorder(side: BorderSide(color: sz.line)),
          ),
          child: Row(children: [
            Icon(Icons.search, size: 18, color: sz.inkFaint),
            const SizedBox(width: 8),
            Text('搜歌曲、歌手、专辑、歌单', style: TextStyle(fontSize: kFontBody, color: sz.inkFaint)),
          ]),
        ),
      ),
    );
  }
}

class _Genres extends StatelessWidget {
  const _Genres({required this.genres});

  final List<MGenre> genres;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 0),
      child: Wrap(spacing: 8, runSpacing: 8, children: [
        for (final g in genres) SzChip(g.name, dense: true, onTap: () => openMusicGenre(context, g.key, g.name)),
      ]),
    );
  }
}

/// 榜单摘要:名字 + 前三首。
class _ChartCard extends StatelessWidget {
  const _ChartCard({required this.chart});

  final MChart chart;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 10),
      child: SzCard(
        child: InkWell(
          onTap: () => openMusicChart(context, chart.key, chart.name),
          child: Padding(
            padding: const EdgeInsets.all(kCardPad),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(
                  child: Text(chart.name,
                      style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, fontWeight: FontWeight.w600)),
                ),
                if (chart.updatedAt != null)
                  Text('${vAgo(chart.updatedAt)}更新', style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
                Icon(Icons.chevron_right, size: 18, color: sz.inkFaint),
              ]),
              const SizedBox(height: 6),
              for (var i = 0; i < chart.top.length; i++)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Row(children: [
                    SizedBox(
                      width: 20,
                      child: Text('${i + 1}',
                          style: TextStyle(
                              fontSize: kFontNote,
                              color: i < 3 ? sz.clay : sz.inkFaint,
                              fontWeight: FontWeight.w600)),
                    ),
                    Expanded(
                      child: Text(mTrackLine(chart.top[i]),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: kFontBody, color: sz.ink)),
                    ),
                  ]),
                ),
            ]),
          ),
        ),
      ),
    );
  }
}

/// 横着一排卡片。
class _Row extends StatelessWidget {
  const _Row({required this.height, required this.children});

  final double height;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: height,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: kPagePad),
          itemCount: children.length,
          separatorBuilder: (_, __) => const SizedBox(width: 12),
          itemBuilder: (context, i) => children[i],
        ),
      );
}

/// 发现页里横排卡片的外部入口(音乐人主页也用同一个排法)。
class MusicCardRow extends StatelessWidget {
  const MusicCardRow({super.key, required this.height, required this.children});

  final double height;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => _Row(height: height, children: children);
}
