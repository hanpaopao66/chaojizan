import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../nav.dart';

/// 视频封面(公开封面 /img/… 直接缓存)。没有封面时画一块底色 + 播放图标。
class VideoCover extends StatelessWidget {
  const VideoCover({super.key, required this.card, this.radius = kRadiusSm, this.showDuration = true});

  final VideoCard card;
  final double radius;
  final bool showDuration;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final url = card.cover.isEmpty ? '' : videoResolve(card.cover);
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: Stack(fit: StackFit.expand, children: [
        if (url.isEmpty)
          Container(color: sz.surfaceAlt, child: Icon(Icons.smart_display_outlined, color: sz.inkFaint))
        else
          Image(
            image: szNetImage(url),
            fit: BoxFit.cover,
            errorBuilder: (_, __, ___) => Container(color: sz.surfaceAlt),
          ),
        // 底部一条渐变,上面压播放数、弹幕数、时长(和 B 站的卡片一样)
        if (showDuration)
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              padding: const EdgeInsets.fromLTRB(6, 14, 6, 4),
              decoration: const BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Color(0x00000000), Color(0x99000000)],
                ),
              ),
              child: Row(children: [
                const Icon(Icons.play_circle_outline, size: 13, color: Colors.white),
                const SizedBox(width: 2),
                Text(vCount(card.views), style: const TextStyle(color: Colors.white, fontSize: kFontMicro)),
                const SizedBox(width: 8),
                const Icon(Icons.subtitles_outlined, size: 13, color: Colors.white),
                const SizedBox(width: 2),
                Text(vCount(card.danmakuCount), style: const TextStyle(color: Colors.white, fontSize: kFontMicro)),
                const Spacer(),
                Text(vDuration(card.durationMs), style: const TextStyle(color: Colors.white, fontSize: kFontMicro)),
              ]),
            ),
          ),
        if (card.collab)
          Positioned(
            top: 6,
            left: 6,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
              decoration: BoxDecoration(color: sz.hold, borderRadius: BorderRadius.circular(4)),
              child: const Text('合作', style: TextStyle(color: Colors.white, fontSize: kFontMicro)),
            ),
          ),
      ]),
    );
  }
}

/// 双列卡片流里的一张(推荐 / 热门 / 关注 / 分区)。长按出菜单(为什么推荐、不感兴趣、稍后再看)。
class VideoGridCard extends StatelessWidget {
  const VideoGridCard({super.key, required this.card, this.onLongPress, this.onTap});

  final VideoCard card;
  final VoidCallback? onLongPress;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Material(
      color: sz.surface,
      borderRadius: BorderRadius.circular(kRadiusMd),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap ?? () => openVideo(context, card.vid),
        onLongPress: onLongPress,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          AspectRatio(aspectRatio: 16 / 10, child: VideoCover(card: card, radius: 0)),
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 6, 8, 2),
            child: Text(card.invalid ? '视频已失效' : card.title,
                maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: kFontBody, height: 1.3)),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
            child: Row(children: [
              Icon(Icons.account_box_outlined, size: 13, color: sz.inkFaint),
              const SizedBox(width: 3),
              Expanded(
                child: Text(card.uploader?.name ?? '',
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// 列表里的一行(搜索结果、历史、收藏夹、稍后再看、空间):左边封面、右边标题和数据。
class VideoRowTile extends StatelessWidget {
  const VideoRowTile({super.key, required this.card, this.subtitle, this.trailing, this.onTap, this.onLongPress,
      this.progress});

  final VideoCard card;
  final String? subtitle;
  final Widget? trailing;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;

  /// 看到哪了(0–1),历史里画在封面底下
  final double? progress;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: card.invalid ? null : (onTap ?? () => openVideo(context, card.vid)),
      onLongPress: onLongPress,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: kPagePad, vertical: 8),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
            width: 148,
            height: 84,
            child: Stack(fit: StackFit.expand, children: [
              VideoCover(card: card),
              if (progress != null)
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: ClipRRect(
                    borderRadius: const BorderRadius.vertical(bottom: Radius.circular(kRadiusSm)),
                    child: LinearProgressIndicator(
                      value: progress!.clamp(0, 1),
                      minHeight: 3,
                      backgroundColor: Colors.black26,
                      color: sz.clay,
                    ),
                  ),
                ),
            ]),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: SizedBox(
              height: 84,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(card.invalid ? '视频已失效' : card.title,
                    maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: kFontBody, height: 1.3)),
                const Spacer(),
                if (card.uploader != null)
                  Text(card.uploader!.name,
                      maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                Text(subtitle ?? '${vCount(card.views)} 播放 · ${vAgo(card.publishedAt)}',
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
            ),
          ),
          if (trailing != null) trailing!,
        ]),
      ),
    );
  }
}
