// 帖子的 1–4 张配图(F1)和大图查看。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../nav.dart';

/// 九宫格式的配图:1 张按原比例(限高)、2 张并排、3 张左大右二、4 张两行两列。
///
/// 为什么不是一律方格:一张竖图压成方的,人脸就被切掉了;而四张缩略图排成
/// 一长条又会各自太小。X 也是按张数换布局的。
class PostMedia extends StatelessWidget {
  const PostMedia(this.media, {super.key, this.radius = kRadiusMd});

  final List<FMedia> media;
  final double radius;

  @override
  Widget build(BuildContext context) {
    if (media.isEmpty) return const SizedBox.shrink();
    final list = media.length > kPostMaxImages ? media.sublist(0, kPostMaxImages) : media;
    const gap = 3.0;
    Widget grid;
    switch (list.length) {
      case 1:
        // 一张:按自己的比例摆,过高的截到 4:5(否则一张长图就占满一屏)
        grid = AspectRatio(
          aspectRatio: list[0].aspect.clamp(0.8, 2.0),
          child: _Tile(list, 0),
        );
      case 2:
        grid = AspectRatio(
          aspectRatio: 2,
          child: Row(children: [
            Expanded(child: _Tile(list, 0)),
            const SizedBox(width: gap),
            Expanded(child: _Tile(list, 1)),
          ]),
        );
      case 3:
        grid = AspectRatio(
          aspectRatio: 1.6,
          child: Row(children: [
            Expanded(child: _Tile(list, 0)),
            const SizedBox(width: gap),
            Expanded(
              child: Column(children: [
                Expanded(child: _Tile(list, 1)),
                const SizedBox(height: gap),
                Expanded(child: _Tile(list, 2)),
              ]),
            ),
          ]),
        );
      default:
        grid = AspectRatio(
          aspectRatio: 1.35,
          child: Column(children: [
            Expanded(
              child: Row(children: [
                Expanded(child: _Tile(list, 0)),
                const SizedBox(width: gap),
                Expanded(child: _Tile(list, 1)),
              ]),
            ),
            const SizedBox(height: gap),
            Expanded(
              child: Row(children: [
                Expanded(child: _Tile(list, 2)),
                const SizedBox(width: gap),
                Expanded(child: _Tile(list, 3)),
              ]),
            ),
          ]),
        );
    }
    return ClipRRect(borderRadius: BorderRadius.circular(radius), child: grid);
  }
}

class _Tile extends StatelessWidget {
  const _Tile(this.media, this.index);

  final List<FMedia> media;
  final int index;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final url = forumResolve(media[index].url);
    return GestureDetector(
      onTap: () => openForumPhotos(context, media, index),
      child: Container(
        color: sz.surfaceAlt,
        child: url.isEmpty
            ? Icon(Icons.image_outlined, color: sz.inkFaint)
            : Image(
                image: szNetImage(url),
                fit: BoxFit.cover,
                errorBuilder: (_, __, ___) => Icon(Icons.broken_image_outlined, color: sz.inkFaint),
              ),
      ),
    );
  }
}

/// 大图查看:左右翻、双指缩放、点一下退出。
Future<void> openForumPhotos(BuildContext context, List<FMedia> media, int index) =>
    Navigator.of(context).push(MaterialPageRoute<void>(
      fullscreenDialog: true,
      builder: (_) => _PhotoPage(media: media, index: index),
    ));

class _PhotoPage extends StatefulWidget {
  const _PhotoPage({required this.media, required this.index});

  final List<FMedia> media;
  final int index;

  @override
  State<_PhotoPage> createState() => _PhotoPageState();
}

class _PhotoPageState extends State<_PhotoPage> {
  late final PageController _page = PageController(initialPage: widget.index);
  late int _at = widget.index;

  @override
  void dispose() {
    _page.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // 看大图这一页故意不限宽:图就是要大。黑底也不走主题令牌 ——
    // 看图的底色是内容的一部分,浅色底会把照片的白边和背景混在一起
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(children: [
        PageView.builder(
          controller: _page,
          itemCount: widget.media.length,
          onPageChanged: (i) => setState(() => _at = i),
          itemBuilder: (context, i) => GestureDetector(
            onTap: () => Navigator.of(context).maybePop(),
            child: InteractiveViewer(
              minScale: 1,
              maxScale: 4,
              child: Center(
                child: Image(
                  image: szNetImage(forumResolve(widget.media[i].url)),
                  fit: BoxFit.contain,
                  errorBuilder: (_, __, ___) =>
                      const Icon(Icons.broken_image_outlined, color: Colors.white54, size: 48),
                ),
              ),
            ),
          ),
        ),
        Positioned(
          top: 0,
          left: 0,
          right: 0,
          child: SafeArea(
            child: Row(children: [
              IconButton(
                onPressed: () => Navigator.of(context).maybePop(),
                icon: const Icon(Icons.close, color: Colors.white),
              ),
              const Spacer(),
              if (widget.media.length > 1)
                Padding(
                  padding: const EdgeInsets.only(right: kPagePad),
                  child: Text('${_at + 1} / ${widget.media.length}',
                      style: szTabular(color: Colors.white, fontSize: kFontBodyLg)),
                ),
            ]),
          ),
        ),
      ]),
    );
  }
}
