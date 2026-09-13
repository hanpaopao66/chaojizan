import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart' show vCount;

/// 视频详情那一排「赞 / 投币 / 收藏 / 分享」里的一格:22 的线图标 + 下面一行等宽数字,点亮了是 clay(设计稿 E)。
class VideoActionButton extends StatelessWidget {
  const VideoActionButton({
    super.key,
    required this.icon,
    required this.activeIcon,
    required this.active,
    required this.count,
    required this.onTap,
    required this.semantic,
    this.flip = false,
  });

  final IconData icon;
  final IconData activeIcon;
  final bool active;
  final int count;
  final VoidCallback onTap;
  final String semantic;

  /// 左右翻过来画(分享用回复箭头翻成往右,和竖屏流右侧栏同一个图标)
  final bool flip;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: semantic,
      child: InkResponse(
        onTap: onTap,
        radius: 30,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: _IconCount(icon: active ? activeIcon : icon, active: active, count: count, flip: flip),
        ),
      ),
    );
  }
}

class _IconCount extends StatelessWidget {
  const _IconCount({required this.icon, required this.active, required this.count, this.ring, this.flip = false});

  final IconData icon;
  final bool active;
  final int count;
  final Widget? ring;
  final bool flip;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final c = active ? sz.clay : sz.inkMuted;
    Widget i = Icon(icon, size: 22, color: c);
    if (flip) i = Transform.flip(flipX: true, child: i);
    return Column(mainAxisSize: MainAxisSize.min, children: [
      SizedBox(
        width: 40,
        height: 30,
        child: Stack(alignment: Alignment.center, children: [if (ring != null) ring!, i]),
      ),
      const SizedBox(height: 2),
      Text(vCount(count),
          style: szTabular(fontSize: kFontNote, color: c, fontWeight: active ? FontWeight.w600 : FontWeight.w400)),
    ]);
  }
}

/// 点赞:点一下是赞 / 取消;按住 1.5 秒转一圈 = 三连(赞 + 投币 + 收藏),和 B 站一样。
///
/// 按住的时候图标外面画一圈 clay 的进度;松手没到 1.5 秒就退回去,什么也不发。
class TripleLikeButton extends StatefulWidget {
  const TripleLikeButton({super.key, required this.liked, required this.count, required this.onTap, required this.onTriple});

  final bool liked;
  final int count;
  final VoidCallback onTap;
  final VoidCallback onTriple;

  /// 按多久算三连
  static const hold = Duration(milliseconds: 1500);

  @override
  State<TripleLikeButton> createState() => _TripleLikeButtonState();
}

class _TripleLikeButtonState extends State<TripleLikeButton> with SingleTickerProviderStateMixin {
  late final AnimationController _hold = AnimationController(vsync: this, duration: TripleLikeButton.hold)
    ..addStatusListener((s) {
      if (s == AnimationStatus.completed) {
        widget.onTriple();
        _hold.reset();
      }
    });

  @override
  void dispose() {
    _hold.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Semantics(
      button: true,
      label: '点赞,长按三连',
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: widget.onTap,
        onLongPressStart: (_) => _hold.forward(from: 0),
        onLongPressEnd: (_) {
          if (_hold.isAnimating) _hold.reset();
        },
        onLongPressCancel: () {
          if (_hold.isAnimating) _hold.reset();
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: AnimatedBuilder(
            animation: _hold,
            builder: (context, _) => _IconCount(
              icon: widget.liked ? Icons.thumb_up : Icons.thumb_up_outlined,
              active: widget.liked,
              count: widget.count,
              ring: _hold.value == 0
                  ? null
                  : SizedBox(
                      width: 30,
                      height: 30,
                      child: CircularProgressIndicator(value: _hold.value, strokeWidth: 2.2, color: sz.clay),
                    ),
            ),
          ),
        ),
      ),
    );
  }
}
