import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:video_player/video_player.dart';

/// 明厨亮灶的实时画面播放器(#155)。
///
/// 只有用户端需要看直播,所以播放器放在这里而不是 shared ——
/// 骑手端和商家端跟着装一个几 MB 的原生播放器不划算。
/// shared 的 [KitchenCamPage] 通过 `playerBuilder` 把它注进去。
///
/// ## 这个播放器最要紧的不是好看,是失败时说人话
///
/// 行业里的乱象是"标着明厨亮灶,点开是黑屏"。用户点进来是想看后厨,
/// **转三十秒圈然后什么都没有,比一开始就说「这家现在连不上」更糟**。
///
/// 所以:初始化失败就立刻给一句解释 + 一个重试,不留黑框让他自己猜。
class KitchenCamPlayer extends StatefulWidget {
  const KitchenCamPlayer({super.key, required this.url});

  final String url;

  @override
  State<KitchenCamPlayer> createState() => _KitchenCamPlayerState();
}

class _KitchenCamPlayerState extends State<KitchenCamPlayer> {
  VideoPlayerController? _c;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _open();
  }

  @override
  void didUpdateWidget(KitchenCamPlayer old) {
    super.didUpdateWidget(old);
    if (old.url != widget.url) {
      _c?.dispose();
      _c = null;
      _failed = false;
      _open();
    }
  }

  @override
  void dispose() {
    _c?.dispose();
    super.dispose();
  }

  Future<void> _open() async {
    final c = VideoPlayerController.networkUrl(Uri.parse(widget.url));
    try {
      await c.initialize();
      if (!mounted) {
        await c.dispose();
        return;
      }
      await c.setLooping(true);
      await c.play();
      // 直播画面不放声音:后厨的对话是员工的,顾客没有理由听
      await c.setVolume(0);
      setState(() => _c = c);
    } catch (_) {
      await c.dispose();
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _retry() async {
    setState(() {
      _failed = false;
      _c = null;
    });
    await _open();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;

    if (_failed) {
      // 服务端说在线,但这边播不出来 —— 如实说,不要留个黑框转圈
      return AspectRatio(
        aspectRatio: 16 / 9,
        child: Container(
          color: Colors.black,
          padding: const EdgeInsets.all(18),
          child: Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.videocam_off_outlined,
                  size: 34, color: Colors.white70),
              const SizedBox(height: 10),
              Text(
                '画面加载不出来,这家的摄像头可能刚掉线。\n'
                '平台每半小时探一次,确认不可用会把标识改回「无明厨亮灶」',
                textAlign: TextAlign.center,
                style: TextStyle(
                    fontSize: 12,
                    height: 1.55,
                    color: Colors.white.withValues(alpha: .8)),
              ),
              const SizedBox(height: 12),
              TextButton(onPressed: _retry, child: const Text('再试一次')),
            ]),
          ),
        ),
      );
    }

    final c = _c;
    if (c == null || !c.value.isInitialized) {
      return AspectRatio(
        aspectRatio: 16 / 9,
        child: Container(
          color: Colors.black,
          child: const Center(
            child: SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: Colors.white70),
            ),
          ),
        ),
      );
    }

    return Stack(children: [
      AspectRatio(aspectRatio: c.value.aspectRatio, child: VideoPlayer(c)),
      // 「实时」角标:让人知道这不是一张预先拍好的照片 ——
      // 而"预先拍好的照片"正是这个功能最常见的作弊方式
      Positioned(
        left: 8,
        top: 8,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
          decoration: BoxDecoration(
            color: Colors.black.withValues(alpha: .45),
            borderRadius: BorderRadius.circular(4),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(color: sz.earn, shape: BoxShape.circle),
            ),
            const SizedBox(width: 5),
            const Text('实时',
                style: TextStyle(fontSize: 10.5, color: Colors.white)),
          ]),
        ),
      ),
    ]);
  }
}
