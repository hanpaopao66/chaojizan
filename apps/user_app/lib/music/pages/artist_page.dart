// 音乐人主页(§8.2 GET /artists/{aid}):横幅、头像、简介、曲风、关注,
// 热门歌曲、全部作品,再往下是全部歌曲(按收听翻页)。
//
// 关注走的是**全站那一张关注表**(§8.4 `/social/v1/users/{id}/follow`),
// 不是音乐自己的一套 —— 关注一位音乐人,他的视频、动态、歌都跟着来。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart';
import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../player/music_player.dart';
import '../widgets/common.dart';
import 'home_page.dart';

class MusicArtistPage extends StatefulWidget {
  const MusicArtistPage({super.key, required this.aid});

  final String aid;

  @override
  State<MusicArtistPage> createState() => _MusicArtistPageState();
}

class _MusicArtistPageState extends State<MusicArtistPage> {
  final _key = GlobalKey<MLoaderState<MArtist>>();
  bool _following = false;

  /// 「全部歌曲」那一段:主页只给热门 10 首,更多的按页翻
  CursorPager<MTrack>? _all;

  @override
  void dispose() {
    _all?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: const Text('音乐人'),
        actions: [
          IconButton(
            icon: const Icon(Icons.more_horiz),
            tooltip: '更多',
            onPressed: () {
              final a = _key.currentState?.data;
              if (a != null) _menu(a);
            },
          ),
        ],
      ),
      body: MLoader<MArtist>(
        key: _key,
        load: () => musicApi.artist(widget.aid),
        builder: _body,
      ),
    );
  }

  Widget _body(BuildContext context, MArtist a, Future<void> Function() reload) {
    final sz = Theme.of(context).sz;
    return ListView(
      padding: const EdgeInsets.only(bottom: 24),
      children: [
        if (a.cover.isNotEmpty) SzCover(url: musicResolve(a.cover), name: a.name, height: 132),
        Padding(
          padding: const EdgeInsets.all(kPagePad),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SzImage(
                url: a.avatar.isEmpty ? '' : musicResolve(a.avatar), name: a.name, size: 64, circle: true),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Flexible(
                    child: Text(a.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: kFontLead, color: sz.ink, fontWeight: FontWeight.w600)),
                  ),
                  if (a.suspended) ...[const SizedBox(width: 6), VTag('已停用', color: sz.danger)],
                ]),
                Text('${vCount(a.fans)} 粉丝 · ${a.trackCount} 首歌',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                if (a.genres.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 6),
                    child: Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [for (final g in a.genres) SzChip(g, dense: true)],
                    ),
                  ),
              ]),
            ),
            const SizedBox(width: 8),
            if (a.userId > 0)
              _following
                  ? const SizedBox(width: 64, child: Center(child: SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))))
                  : (a.followed
                      ? OutlinedButton(onPressed: () => _follow(a, false), child: const Text('已关注'))
                      : FilledButton(onPressed: () => _follow(a, true), child: const Text('关注'))),
          ]),
        ),
        if (a.bio.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 10),
            child: Text(a.bio, style: TextStyle(fontSize: kFontBody, color: sz.inkMuted, height: 1.6)),
          ),
        if (a.hotTracks.isNotEmpty) ...[
          MSection(
            '热门歌曲',
            onMore: () => MusicPlayer.instance.playContext(a.hotTracks, contextKey: 'artist:${a.aid}'),
            moreLabel: '播放全部',
          ),
          for (final t in a.hotTracks)
            MTrackTile(track: t, queue: a.hotTracks, contextKey: 'artist:${a.aid}'),
        ],
        if (a.releases.isNotEmpty) ...[
          const MSection('作品'),
          MusicCardRow(
            height: 176,
            children: [for (final r in a.releases) MReleaseCard(release: r)],
          ),
        ],
        if (a.trackCount > a.hotTracks.length) ...[
          const MSection('全部歌曲'),
          _AllTracks(aid: a.aid, onPager: (p) => _all = p),
        ],
        if (a.hotTracks.isEmpty && a.releases.isEmpty)
          Padding(padding: const EdgeInsets.only(top: 32), child: SzEmpty(text: '这位音乐人还没有上架的作品')),
      ],
    );
  }

  Future<void> _follow(MArtist a, bool follow) async {
    if (!await ensureLoggedIn(context)) return;
    setState(() => _following = true);
    try {
      final r = await musicApi.followUser(a.userId, follow);
      if (!mounted) return;
      a
        ..followed = r.followed
        ..fans = r.fans;
      _key.currentState?.refreshUi();
    } catch (e) {
      if (mounted) mToast(context, e);
    } finally {
      if (mounted) setState(() => _following = false);
    }
  }

  Future<void> _menu(MArtist a) async {
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.ios_share), title: const Text('分享'), onTap: () => Navigator.pop(ctx, 'share')),
          ListTile(
              leading: const Icon(Icons.flag_outlined), title: const Text('举报'), onTap: () => Navigator.pop(ctx, 'report')),
        ]),
      ),
    );
    if (pick == null || !mounted) return;
    if (pick == 'share') {
      await shareMusic(context, 'artist', a.aid, a.name);
    } else {
      await reportSheet(context, targetType: 'artist', targetId: a.aid);
    }
  }
}

/// 「全部歌曲」那一段。嵌在外层 ListView 里,所以自己不滚 —— 靠外层滚到底时加载下一页。
class _AllTracks extends StatefulWidget {
  const _AllTracks({required this.aid, required this.onPager});

  final String aid;
  final void Function(CursorPager<MTrack> pager) onPager;

  @override
  State<_AllTracks> createState() => _AllTracksState();
}

class _AllTracksState extends State<_AllTracks> {
  late final CursorPager<MTrack> _pager = CursorPager<MTrack>((cursor) async {
    final page = int.tryParse(cursor ?? '0') ?? 0;
    final r = await musicApi.artistTracks(widget.aid, page: page);
    return (items: r.items, next: r.hasMore ? '${page + 1}' : null, extra: r.extra);
  });

  @override
  void initState() {
    super.initState();
    widget.onPager(_pager);
    _pager.refresh();
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return AnimatedBuilder(
      animation: _pager,
      builder: (context, _) {
        if (!_pager.loaded) {
          if (_pager.error != null) return musicErrorView(_pager.error, _pager.refresh);
          return const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator()));
        }
        return Column(children: [
          for (final t in _pager.items)
            MTrackTile(track: t, queue: _pager.items, contextKey: 'artist:${widget.aid}'),
          if (_pager.hasMore)
            Padding(
              padding: const EdgeInsets.all(12),
              child: _pager.loading
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                  : TextButton(onPressed: _pager.more, child: const Text('加载更多')),
            )
          else if (_pager.items.isNotEmpty)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text('没有更多了', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
            ),
        ]);
      },
    );
  }
}
