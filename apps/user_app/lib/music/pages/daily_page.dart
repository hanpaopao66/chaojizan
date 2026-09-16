// 每日推荐(§5.4:20 首,近 7 天听过的不推,同一位音乐人最多 3 首)。
// 关掉个性化之后只按热歌榜分数排 —— 页面上把这件事说出来,而不是悄悄换一套结果。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../nav.dart';
import '../player/music_player.dart';
import '../widgets/common.dart';

class MusicDailyPage extends StatelessWidget {
  const MusicDailyPage({super.key});

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: const Text('每日推荐'),
        actions: [TextButton(onPressed: () => openMusicFormula(context), child: const Text('怎么算的'))],
      ),
      body: MLoader<MDaily>(
        load: () => musicApi.daily(),
        builder: (context, daily, reload) => ListView(
          padding: const EdgeInsets.only(bottom: 24),
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    if (daily.date.isNotEmpty)
                      Text(daily.date, style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
                    Text(
                      daily.personalized
                          ? '按你听过、喜欢过的算;近 7 天听过的不再推给你'
                          : '你关掉了个性化推荐,这里只按热歌榜分数排',
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
                    ),
                  ]),
                ),
                if (daily.items.isNotEmpty)
                  TextButton.icon(
                    onPressed: () => MusicPlayer.instance.playContext(daily.items, contextKey: 'daily'),
                    icon: const Icon(Icons.play_circle_outline, size: 18),
                    label: const Text('播放全部', style: TextStyle(fontSize: kFontNote)),
                  ),
              ]),
            ),
            if (daily.items.isEmpty)
              Padding(padding: const EdgeInsets.only(top: 32), child: SzEmpty(text: '今天还没有能推给你的歌')),
            for (final t in daily.items)
              MTrackTile(track: t, queue: daily.items, contextKey: 'daily', showRank: true),
          ],
        ),
      ),
    );
  }
}
