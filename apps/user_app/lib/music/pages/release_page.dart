// 作品详情(单曲 / EP / 专辑,§8.2 GET /releases/{rid})。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../player/music_player.dart';
import '../widgets/common.dart';

class MusicReleasePage extends StatefulWidget {
  const MusicReleasePage({super.key, required this.rid});

  final String rid;

  @override
  State<MusicReleasePage> createState() => _MusicReleasePageState();
}

class _MusicReleasePageState extends State<MusicReleasePage> {
  final _key = GlobalKey<MLoaderState<MRelease>>();

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: const Text('作品'),
        actions: [
          IconButton(
            icon: const Icon(Icons.more_horiz),
            tooltip: '更多',
            onPressed: () {
              final r = _key.currentState?.data;
              if (r != null) _menu(r);
            },
          ),
        ],
      ),
      body: MLoader<MRelease>(
        load: () => musicApi.release(widget.rid),
        key: _key,
        builder: (context, r, reload) => ListView(
          padding: const EdgeInsets.only(bottom: 24),
          children: [
            Padding(
              padding: const EdgeInsets.all(kPagePad),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                MCover(url: r.cover, name: r.title, size: 108, radius: kRadiusMd),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(r.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: kFontLead, color: sz.ink, fontWeight: FontWeight.w600)),
                    const SizedBox(height: 4),
                    if (r.artist != null)
                      InkWell(
                        onTap: () => openArtist(context, r.artist!.aid),
                        child: Text(r.artist!.name,
                            style: TextStyle(fontSize: kFontBodyLg, color: sz.link)),
                      ),
                    const SizedBox(height: 2),
                    Text(
                      [
                        mReleaseKindName(r.kind),
                        '${r.tracks.length} 首',
                        if (r.releaseDate.isNotEmpty) r.releaseDate,
                      ].join(' · '),
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted),
                    ),
                    if (r.genre.isNotEmpty || r.language.isNotEmpty)
                      Text([if (r.genre.isNotEmpty) r.genre, if (r.language.isNotEmpty) r.language].join(' · '),
                          style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ]),
                ),
              ]),
            ),
            if (r.description.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 10),
                child: Text(r.description, style: TextStyle(fontSize: kFontBody, color: sz.inkMuted, height: 1.6)),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 8),
              child: Row(children: [
                FilledButton.icon(
                  onPressed: r.tracks.isEmpty
                      ? null
                      : () => MusicPlayer.instance.playContext(r.tracks, contextKey: 'release:${r.rid}'),
                  icon: const Icon(Icons.play_arrow, size: 18),
                  label: const Text('播放全部'),
                ),
                const SizedBox(width: 10),
                OutlinedButton.icon(
                  onPressed: () => _collect(r),
                  icon: Icon(r.collected ? Icons.check : Icons.add, size: 18),
                  label: Text(r.collected ? '已收藏 ${vCount(r.collects)}' : '收藏'),
                ),
              ]),
            ),
            const Divider(height: 1),
            if (r.tracks.isEmpty)
              Padding(padding: const EdgeInsets.only(top: 32), child: SzEmpty(text: '这个作品里还没有歌'))
            else
              for (var i = 0; i < r.tracks.length; i++)
                MTrackTile(
                  track: r.tracks[i],
                  queue: r.tracks,
                  contextKey: 'release:${r.rid}',
                  // 专辑里按曲序排,封面都一样,列个号比重复贴 12 张一样的图清楚
                  leading: SizedBox(
                    width: 34,
                    child: Text('${r.tracks[i].trackNo > 0 ? r.tracks[i].trackNo : i + 1}',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: kFontBodyLg, color: sz.inkFaint)),
                  ),
                  subtitle: vDuration(r.tracks[i].durationMs),
                ),
          ],
        ),
      ),
    );
  }

  Future<void> _collect(MRelease r) async {
    if (!await ensureLoggedIn(context)) return;
    try {
      final x = await musicApi.collectRelease(r.rid, !r.collected);
      if (!mounted) return;
      r
        ..collected = x.collected
        ..collects = x.collects;
      _key.currentState?.refreshUi();
    } catch (e) {
      if (mounted) mToast(context, e);
    }
  }

  Future<void> _menu(MRelease r) async {
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.ios_share), title: const Text('分享'), onTap: () => Navigator.pop(ctx, 'share')),
          if (r.artist != null)
            ListTile(
                leading: const Icon(Icons.person_outline),
                title: const Text('查看音乐人'),
                onTap: () => Navigator.pop(ctx, 'artist')),
          ListTile(
              leading: const Icon(Icons.flag_outlined), title: const Text('举报'), onTap: () => Navigator.pop(ctx, 'report')),
        ]),
      ),
    );
    if (pick == null || !mounted) return;
    switch (pick) {
      case 'share':
        await shareMusic(context, 'release', r.rid, r.title);
      case 'artist':
        await openArtist(context, r.artist!.aid);
      case 'report':
        await reportSheet(context, targetType: 'release', targetId: r.rid);
    }
  }
}
