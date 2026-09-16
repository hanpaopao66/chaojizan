// 一个曲风下的歌(§8.2 GET /genres/{key}/tracks,按热歌榜分数排,按页翻)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart';
import '../models.dart';
import '../nav.dart';
import '../player/music_player.dart';
import '../widgets/common.dart';

class MusicGenrePage extends StatefulWidget {
  const MusicGenrePage({super.key, required this.genreKey, required this.name});

  final String genreKey;
  final String name;

  @override
  State<MusicGenrePage> createState() => _MusicGenrePageState();
}

class _MusicGenrePageState extends State<MusicGenrePage> {
  late final CursorPager<MTrack> _pager = CursorPager<MTrack>((cursor) async {
    // 按分数排的用页码(§5.2);游标这里借来当页号,拿到最后一页就给 null
    final page = int.tryParse(cursor ?? '0') ?? 0;
    final r = await musicApi.genreTracks(widget.genreKey, page: page);
    return (items: r.items, next: r.hasMore ? '${page + 1}' : null, extra: r.extra);
  });

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: Text(widget.name),
        actions: [
          AnimatedBuilder(
            animation: _pager,
            builder: (context, _) => IconButton(
              icon: const Icon(Icons.play_circle_outline),
              tooltip: '播放全部',
              onPressed: _pager.items.isEmpty
                  ? null
                  : () => MusicPlayer.instance
                      .playContext(_pager.items, contextKey: 'genre:${widget.genreKey}'),
            ),
          ),
        ],
      ),
      body: PagedListView<MTrack>(
        pager: _pager,
        divider: false,
        emptyText: '「${widget.name}」下还没有歌',
        itemBuilder: (context, t, i) => MTrackTile(
          track: t,
          queue: _pager.items,
          contextKey: 'genre:${widget.genreKey}',
          showRank: true,
        ),
      ),
    );
  }
}
