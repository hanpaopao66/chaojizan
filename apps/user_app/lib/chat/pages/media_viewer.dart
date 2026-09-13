import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:video_player/video_player.dart';

import '../models.dart';
import '../store.dart';
import '../ui/format.dart';
import '../ui/media_save.dart';
import '../ui/media_views.dart';

/// 全屏看图 / 视频:左右滑切这一串(会话里加载了的图片视频、共享媒体),双指缩放,保存。
/// [canSave] 为假(会话开了「禁止保存」)时不给保存按钮 —— 和长按菜单里藏掉复制 / 转发 / 收藏同一个口径
Future<void> openMediaViewer(BuildContext context, ChatMessage start, List<ChatMessage> items, {bool canSave = true}) {
  final list = items.where((m) => m.media.isNotEmpty && m.seq > 0).toList();
  if (list.isEmpty) return Future.value();
  final i = list.indexWhere((m) => m.seq == start.seq);
  return Navigator.of(context).push(PageRouteBuilder<void>(
    opaque: false,
    barrierColor: Colors.black,
    pageBuilder: (_, __, ___) => _Viewer(items: list, initial: i < 0 ? 0 : i, canSave: canSave),
    transitionsBuilder: (_, a, __, child) => FadeTransition(opacity: a, child: child),
  ));
}

class _Viewer extends StatefulWidget {
  const _Viewer({required this.items, required this.initial, required this.canSave});

  final List<ChatMessage> items;
  final int initial;
  final bool canSave;

  @override
  State<_Viewer> createState() => _ViewerState();
}

class _ViewerState extends State<_Viewer> {
  late final PageController _pc = PageController(initialPage: widget.initial);
  late int _index = widget.initial;
  bool _chrome = true;

  @override
  void dispose() {
    _pc.dispose();
    super.dispose();
  }

  Future<void> _save(ChatMessage m) => saveChatMedia(context, m.media.first);

  @override
  Widget build(BuildContext context) {
    final m = widget.items[_index];
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(children: [
        PageView.builder(
          controller: _pc,
          itemCount: widget.items.length,
          onPageChanged: (i) => setState(() => _index = i),
          itemBuilder: (context, i) {
            final it = widget.items[i];
            final media = it.media.first;
            final isVideo = media.kind == 'video' || media.kind == 'gif' || media.kind == 'video_note';
            return GestureDetector(
              onTap: () => setState(() => _chrome = !_chrome),
              child: isVideo ? _VideoPage(media: media, active: i == _index) : _PhotoPage(media: media),
            );
          },
        ),
        if (_chrome)
          Positioned(
            left: 0,
            right: 0,
            top: 0,
            child: Container(
              color: Colors.black.withValues(alpha: .45),
              child: SafeArea(
                bottom: false,
                child: Row(children: [
                  IconButton(
                      icon: const Icon(Icons.close, color: Colors.white), onPressed: () => Navigator.of(context).pop()),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(ChatStore.instance.nameOf(m.sender),
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                      Text('${dayLabel(m.createdAt)} ${hm(m.createdAt)}',
                          style: const TextStyle(color: Colors.white70, fontSize: kFontNote)),
                    ]),
                  ),
                  if (widget.items.length > 1)
                    Text('${_index + 1}/${widget.items.length}', style: const TextStyle(color: Colors.white70)),
                  if (widget.canSave)
                    IconButton(
                        tooltip: '保存',
                        icon: const Icon(Icons.download_outlined, color: Colors.white),
                        onPressed: () => _save(m)),
                ]),
              ),
            ),
          ),
        if (_chrome && m.text.isNotEmpty)
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              color: Colors.black.withValues(alpha: .45),
              padding: const EdgeInsets.all(kPagePad),
              child: SafeArea(
                top: false,
                child: Text(m.text, style: const TextStyle(color: Colors.white)),
              ),
            ),
          ),
      ]),
    );
  }
}

class _PhotoPage extends StatelessWidget {
  const _PhotoPage({required this.media});

  final MediaInfo media;

  @override
  Widget build(BuildContext context) {
    final r = resolvedMedia(media);
    if (r == null) return const Center(child: CircularProgressIndicator(color: Colors.white));
    return InteractiveViewer(
      maxScale: 5,
      child: Center(
        child: Image(
          image: szNetImageKeyed(r.url, 'm${media.id}o'),
          fit: BoxFit.contain,
          loadingBuilder: (context, child, p) => p == null
              ? child
              : Stack(alignment: Alignment.center, children: [
                  if (r.thumb != null)
                    Image(image: szNetImageKeyed(r.thumb!, 'm${media.id}t'), fit: BoxFit.contain),
                  const CircularProgressIndicator(color: Colors.white),
                ]),
          errorBuilder: (_, __, ___) =>
              const Center(child: Icon(Icons.broken_image_outlined, color: Colors.white54, size: 48)),
        ),
      ),
    );
  }
}

class _VideoPage extends StatefulWidget {
  const _VideoPage({required this.media, required this.active});

  final MediaInfo media;
  final bool active;

  @override
  State<_VideoPage> createState() => _VideoPageState();
}

class _VideoPageState extends State<_VideoPage> {
  VideoPlayerController? _c;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    final r = resolvedMedia(widget.media);
    if (r == null) {
      await Future<void>.delayed(const Duration(milliseconds: 300));
      if (mounted) _init();
      return;
    }
    final c = VideoPlayerController.networkUrl(Uri.parse(r.url));
    try {
      await c.initialize();
      await c.setLooping(widget.media.kind == 'gif');
      if (widget.media.kind == 'gif') await c.setVolume(0);
      if (!mounted) {
        await c.dispose();
        return;
      }
      setState(() => _c = c);
      if (widget.active) await c.play();
      c.addListener(() {
        if (mounted) setState(() {});
      });
    } catch (_) {
      await c.dispose();
      if (mounted) setState(() => _failed = true);
    }
  }

  @override
  void didUpdateWidget(_VideoPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.active) _c?.pause();
  }

  @override
  void dispose() {
    _c?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = _c;
    if (_failed) {
      return const Center(child: Text('视频放不了', style: TextStyle(color: Colors.white70)));
    }
    if (c == null || !c.value.isInitialized) {
      return const Center(child: CircularProgressIndicator(color: Colors.white));
    }
    final v = c.value;
    return Stack(alignment: Alignment.center, children: [
      // 网页上 <video> 平台视图会抢走单击(外面点一下切换顶栏的手势就失灵),画面本身不接指针
      Center(child: IgnorePointer(child: AspectRatio(aspectRatio: v.aspectRatio, child: VideoPlayer(c)))),
      if (!v.isPlaying)
        IconButton(
          iconSize: 64,
          icon: const Icon(Icons.play_circle_fill, color: Colors.white70),
          onPressed: () => c.play(),
        ),
      Positioned(
        left: 12,
        right: 12,
        bottom: 24,
        child: SafeArea(
          top: false,
          child: Row(children: [
            IconButton(
              icon: Icon(v.isPlaying ? Icons.pause : Icons.play_arrow, color: Colors.white),
              onPressed: () => v.isPlaying ? c.pause() : c.play(),
            ),
            Text(duration(v.position.inMilliseconds), style: const TextStyle(color: Colors.white70, fontSize: kFontNote)),
            Expanded(
              child: Slider(
                value: v.position.inMilliseconds.clamp(0, v.duration.inMilliseconds).toDouble(),
                max: v.duration.inMilliseconds.toDouble().clamp(1, double.infinity),
                onChanged: (x) => c.seekTo(Duration(milliseconds: x.round())),
              ),
            ),
            Text(duration(v.duration.inMilliseconds), style: const TextStyle(color: Colors.white70, fontSize: kFontNote)),
          ]),
        ),
      ),
    ]);
  }
}
