// 榜单(§4 M7:热歌、新歌、飙升)与公式页(§5.4)。
//
// 榜单和推荐的立场和视频那边一样:**公式公开**,每一首都带算分的中间量,
// 「怎么算的」点开就是服务端 `/music/v1/rank/formula` 原样下发的公式和全部参数 ——
// 不是我们在客户端重写一遍,那样两边会慢慢对不上。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../player/music_player.dart';
import '../widgets/common.dart';

/// 三个榜的摘要。
class MusicChartsPage extends StatelessWidget {
  const MusicChartsPage({super.key});

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: const Text('榜单'),
        actions: [
          TextButton(onPressed: () => openMusicFormula(context), child: const Text('怎么算的')),
        ],
      ),
      body: MLoader<List<MChart>>(
        load: () => musicApi.charts(),
        builder: (context, charts, reload) => ListView(
          padding: const EdgeInsets.only(bottom: 24),
          children: [
            if (charts.isEmpty)
              Padding(padding: const EdgeInsets.only(top: 40), child: SzEmpty(text: '榜单还没有算出来')),
            for (final c in charts)
              ListTile(
                title: Text(c.name),
                subtitle: Text(
                    c.top.isEmpty
                        ? (c.updatedAt == null ? '' : '${vAgo(c.updatedAt)}更新')
                        : c.top.map(mTrackLine).join(' / '),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontNote, color: Theme.of(context).sz.inkMuted)),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => openMusicChart(context, c.key, c.name),
              ),
          ],
        ),
      ),
    );
  }
}

/// 一个榜的全表。每行显示名次和算分的中间量。
class MusicChartPage extends StatelessWidget {
  const MusicChartPage({super.key, required this.chartKey, required this.name});

  final String chartKey;
  final String name;

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: Text(name),
        actions: [TextButton(onPressed: () => openMusicFormula(context), child: const Text('怎么算的'))],
      ),
      body: MLoader<MChart>(
        load: () => musicApi.chart(chartKey),
        builder: (context, chart, reload) {
          final tracks = [for (final e in chart.items) e.track];
          final sz = Theme.of(context).sz;
          return ListView(
            padding: const EdgeInsets.only(bottom: 24),
            children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 4),
                child: Row(children: [
                  Expanded(
                    child: Text(
                      chart.updatedAt == null ? '共 ${chart.items.length} 首' : '${vAgo(chart.updatedAt)}更新 · 共 ${chart.items.length} 首',
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
                    ),
                  ),
                  if (tracks.isNotEmpty)
                    TextButton.icon(
                      onPressed: () =>
                          MusicPlayer.instance.playContext(tracks, contextKey: 'chart:$chartKey'),
                      icon: const Icon(Icons.play_circle_outline, size: 18),
                      label: const Text('播放全部', style: TextStyle(fontSize: kFontNote)),
                    ),
                ]),
              ),
              if (chart.items.isEmpty)
                Padding(padding: const EdgeInsets.only(top: 32), child: SzEmpty(text: '这个榜上暂时还没有歌')),
              for (final e in chart.items)
                MTrackTile(
                  track: e.track,
                  queue: tracks,
                  contextKey: 'chart:$chartKey',
                  showRank: true,
                  leading: SizedBox(
                    width: 34,
                    child: Text('${e.rankNo}',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: kFontTitle,
                          color: e.rankNo <= 3 ? sz.clay : sz.inkFaint,
                          fontWeight: FontWeight.w700,
                        )),
                  ),
                ),
            ],
          );
        },
      ),
    );
  }
}

/// 公式页:服务端下发的公式原文和全部参数,一字不改地摆出来。
class MusicFormulaPage extends StatelessWidget {
  const MusicFormulaPage({super.key});

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('榜单和推荐是怎么算的')),
      body: MLoader<Map<String, dynamic>>(
        load: () => musicApi.formula(),
        builder: (context, data, reload) {
          final params = vMap(data['params']);
          return ListView(
            padding: const EdgeInsets.all(kPagePad),
            children: [
              Text('这份公式和服务端跑的是同一份',
                  style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              Text('每首歌旁边那句「近 7 天多少人收听」就是按它算的。我们不按人情、不按付费改名次 —— 这里也没有推广位可买。',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.6)),
              const SizedBox(height: 14),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(kCardPad),
                decoration: BoxDecoration(
                  color: sz.surfaceAlt,
                  borderRadius: BorderRadius.circular(kRadiusMd),
                  border: Border.all(color: sz.line),
                ),
                child: SelectableText('${data['formula'] ?? ''}',
                    style: TextStyle(fontSize: kFontBody, height: 1.9, color: sz.ink)),
              ),
              if (params.isNotEmpty) ...[
                const SizedBox(height: 18),
                Text('参数', style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, fontWeight: FontWeight.w600)),
                const SizedBox(height: 6),
                for (final e in params.entries)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      SizedBox(
                        width: 170,
                        child: Text(e.key, style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
                      ),
                      Expanded(child: Text('${e.value}', style: TextStyle(fontSize: kFontBody, color: sz.ink))),
                    ]),
                  ),
              ],
            ],
          );
        },
      ),
    );
  }
}
