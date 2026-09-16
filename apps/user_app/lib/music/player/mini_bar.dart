// 迷你播放条(§4 I5):有歌在放时,App 底部导航上方常驻一条;点开进播放页。
//
// 主会话会把它挂到全 App 的底部(见 nav.dart 顶上的说明)。这里只管:
// 没歌的时候**一点地方都不占**(高度 0),有歌的时候一行。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';
import 'music_player.dart';
import 'queue_sheet.dart';

/// 迷你播放条。挂在底部导航上方:
///
/// ```dart
/// Column(children: [Expanded(child: body), const MusicMiniBar(), bottomNav])
/// ```
class MusicMiniBar extends StatelessWidget {
  const MusicMiniBar({super.key, this.player});

  /// 不给就是全 App 那一个
  final MusicPlayer? player;

  static const double height = 58;

  @override
  Widget build(BuildContext context) {
    final p = player ?? MusicPlayer.instance;
    return AnimatedBuilder(
      animation: p,
      builder: (context, _) {
        final t = p.current;
        // 没歌就彻底不占位。留一条空条的话,每个页面底下都凭空矮一截
        if (t == null) return const SizedBox.shrink();
        final sz = Theme.of(context).sz;
        return Material(
          color: sz.surface,
          child: InkWell(
            onTap: () => openMusicPlayer(context),
            child: SizedBox(
              height: height,
              child: Column(mainAxisSize: MainAxisSize.min, children: [
                // 进度画成顶上一条发丝线:迷你条上没地方放能拖的条,
                // 但「放到哪了」这件事一眼要看得见
                LinearProgressIndicator(
                  value: p.progress,
                  minHeight: 2,
                  backgroundColor: sz.line,
                  valueColor: AlwaysStoppedAnimation<Color>(sz.clay),
                ),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: Row(children: [
                      MCover(url: t.cover, name: t.title, size: 38),
                      const SizedBox(width: 10),
                      Expanded(child: _Titles(track: t, notice: p.notice)),
                      IconButton(
                        icon: Icon(p.playing ? Icons.pause : Icons.play_arrow),
                        tooltip: p.playing ? '暂停' : '播放',
                        onPressed: p.toggle,
                      ),
                      IconButton(
                        icon: const Icon(Icons.skip_next),
                        tooltip: '下一首',
                        onPressed: p.queue.length > 1 ? () => p.next() : null,
                      ),
                      IconButton(
                        icon: const Icon(Icons.queue_music),
                        tooltip: '播放队列',
                        onPressed: () => showMusicQueue(context, player: p),
                      ),
                    ]),
                  ),
                ),
              ]),
            ),
          ),
        );
      },
    );
  }
}

class _Titles extends StatelessWidget {
  const _Titles({required this.track, this.notice});

  final MTrack track;
  final String? notice;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(track.title,
            maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: kFontBodyLg)),
        Text(
          // 出过岔子(这首放不了)时那句话顶掉歌手名:它更要紧
          notice ?? track.artistName,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(fontSize: kFontMicro, color: notice != null ? sz.danger : sz.inkMuted),
        ),
      ],
    );
  }
}
