// 播放队列弹层:这一队有哪些歌、在放第几首、拖着换顺序、划掉一首、全部清空。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart';
import '../widgets/common.dart';
import 'music_player.dart';

/// 播放队列。[player] 不给就是全 App 那一个。
class MusicQueueSheet extends StatelessWidget {
  const MusicQueueSheet({super.key, this.player});

  final MusicPlayer? player;

  @override
  Widget build(BuildContext context) {
    final p = player ?? MusicPlayer.instance;
    final sz = Theme.of(context).sz;
    return SafeArea(
      child: AnimatedBuilder(
        animation: p,
        builder: (context, _) => SzSheetScrollable(
          builder: (ctx, controller) => Column(mainAxisSize: MainAxisSize.min, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 6, 6, 6),
              child: Row(children: [
                Expanded(
                  child: Row(children: [
                    Text('播放队列', style: TextStyle(fontSize: kFontTitle, color: sz.ink)),
                    const SizedBox(width: 8),
                    Text('${p.queue.length} 首', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ]),
                ),
                TextButton.icon(
                  onPressed: () => p.cycleMode(),
                  icon: Icon(_modeIcon(p.mode), size: 18),
                  label: Text(p.mode.label, style: const TextStyle(fontSize: kFontNote)),
                ),
                IconButton(
                  icon: const Icon(Icons.delete_outline),
                  tooltip: '清空',
                  onPressed: p.queue.isEmpty
                      ? null
                      : () async {
                          if (await vConfirm(context, title: '清空播放队列?', ok: '清空', danger: true)) {
                            await p.clearQueue();
                            if (context.mounted) Navigator.pop(context);
                          }
                        },
                ),
              ]),
            ),
            const Divider(height: 1),
            Flexible(
              child: p.queue.isEmpty
                  ? Padding(
                      padding: const EdgeInsets.all(40),
                      child: Center(child: Text('队列是空的', style: TextStyle(color: sz.inkMuted))),
                    )
                  : ReorderableListView.builder(
                      scrollController: controller,
                      shrinkWrap: controller == null,
                      physics: const AlwaysScrollableScrollPhysics(),
                      buildDefaultDragHandles: false,
                      itemCount: p.queue.length,
                      onReorderItem: (from, to) => p.reorder(from, to),
                      itemBuilder: (context, i) {
                        final t = p.queue[i];
                        final current = i == p.index;
                        return ListTile(
                          key: ValueKey(t.tid),
                          dense: true,
                          leading: current
                              ? Icon(Icons.volume_up, size: 18, color: sz.clay)
                              : SizedBox(
                                  width: 18,
                                  child: Text('${i + 1}',
                                      textAlign: TextAlign.center,
                                      style: TextStyle(fontSize: kFontNote, color: sz.inkFaint)),
                                ),
                          title: Text(t.title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: kFontBodyLg,
                                color: current ? sz.clay : sz.ink,
                              )),
                          subtitle: t.artistName.isEmpty
                              ? null
                              : Text(t.artistName,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                          trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                            IconButton(
                              icon: const Icon(Icons.close, size: 18),
                              tooltip: '移出队列',
                              onPressed: () => p.removeAt(i),
                            ),
                            ReorderableDragStartListener(
                              index: i,
                              child: Padding(
                                padding: const EdgeInsets.symmetric(horizontal: 4),
                                child: Icon(Icons.drag_handle, size: 20, color: sz.inkFaint),
                              ),
                            ),
                          ]),
                          onTap: () => p.playAt(i),
                        );
                      },
                    ),
            ),
          ]),
        ),
      ),
    );
  }
}

IconData _modeIcon(MusicMode m) => switch (m) {
      MusicMode.listLoop => Icons.repeat,
      MusicMode.single => Icons.repeat_one,
      MusicMode.shuffle => Icons.shuffle,
    };

/// 播放模式的图标,播放页也用
IconData musicModeIcon(MusicMode m) => _modeIcon(m);

/// 队列弹层的入口(迷你条、播放页都从这里开)。
Future<void> showMusicQueue(BuildContext context, {MusicPlayer? player}) =>
    szShowSheet<void>(context: context, builder: (_) => MusicQueueSheet(player: player));

/// 在队列里没有歌时提一句,免得弹出一个空框
Future<void> showQueueOrToast(BuildContext context, {MusicPlayer? player}) async {
  final p = player ?? MusicPlayer.instance;
  if (p.queue.isEmpty) {
    mToast(context, '还没有在放的歌');
    return;
  }
  await showMusicQueue(context, player: p);
}
