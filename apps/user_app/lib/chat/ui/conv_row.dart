import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'format.dart' show badgeText;

/// 「消息」列表里的一行(设计稿 A)。**列表只有这一种行** —— 平台服务号、订单群、
/// 视频互动机器人、私聊 / 群 / 频道 / 收藏夹都是它,点进去各是一个会话。
///
/// 左边 50 的头像,右边两行:标题(可带前缀图标、认证标 / 机器人标、免打扰图标)+ 时间;
/// 预览 + 未读角标。置顶的行垫一层比页底深一点的底色(Telegram iOS 的置顶样子)。
class ConvRow extends StatelessWidget {
  const ConvRow({
    super.key,
    required this.avatar,
    required this.title,
    required this.preview,
    this.time = '',
    this.titlePrefix,
    this.titleSuffix = const [],
    this.timeLead,
    this.trailing,
    this.pinned = false,
    this.onTap,
    this.onLongPress,
  });

  final Widget avatar;
  final String title;
  final Widget preview;
  final String time;

  /// 标题前面的小图标(群:两个人)
  final IconData? titlePrefix;

  /// 标题后面紧跟的东西:认证标、「机器人」、免打扰的铃铛
  final List<Widget> titleSuffix;

  /// 时间前面的东西(自己最后一条的勾)
  final Widget? timeLead;

  /// 预览右边:未读角标、@、置顶图钉
  final Widget? trailing;
  final bool pinned;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Material(
      color: pinned ? convPinnedColor(sz) : Colors.transparent,
      child: InkWell(
        onTap: onTap,
        onLongPress: onLongPress,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: kPagePad, vertical: 9),
          child: Row(children: [
            avatar,
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Row(children: [
                  // 标题连同前后的小标占掉时间左边的全部宽度:时间永远贴右对齐,标题长了才省略
                  Expanded(
                    child: Row(children: [
                      if (titlePrefix != null)
                        Padding(
                          padding: const EdgeInsets.only(right: 5),
                          child: Icon(titlePrefix, size: 15, color: sz.inkMuted),
                        ),
                      Flexible(
                        child: Text(title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                                fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink, height: 1.3)),
                      ),
                      for (final w in titleSuffix) Padding(padding: const EdgeInsets.only(left: 5), child: w),
                    ]),
                  ),
                  if (timeLead != null) Padding(padding: const EdgeInsets.only(left: 6, right: 3), child: timeLead),
                  if (time.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(left: 6),
                      child: Text(time, style: szTabular(fontSize: kFontMicro, color: sz.inkMuted)),
                    ),
                ]),
                const SizedBox(height: 2),
                Row(children: [
                  Expanded(
                    child: DefaultTextStyle.merge(
                      style: TextStyle(fontSize: kFontBody, color: sz.inkMuted, height: 1.45),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      child: preview,
                    ),
                  ),
                  if (trailing != null) Padding(padding: const EdgeInsets.only(left: 6), child: trailing),
                ]),
              ]),
            ),
          ]),
        ),
      ),
    );
  }
}

/// 置顶行的底色:页底往发丝线的方向压一点。深色模式下同一个写法是提亮一点,也对。
Color convPinnedColor(SzColors sz) => Color.alphaBlend(sz.line.withValues(alpha: .4), sz.paper);

/// 未读角标:clay 实底;免打扰的会话走 inkMuted(灰角标,也不计入底栏)。
/// [marked] 是「标为未读」:没有数字,只是一个点那么大的实心角标。
class UnreadBadge extends StatelessWidget {
  const UnreadBadge({super.key, required this.count, this.muted = false, this.marked = false});

  final int count;
  final bool muted;
  final bool marked;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      height: 18,
      constraints: const BoxConstraints(minWidth: 18),
      padding: const EdgeInsets.symmetric(horizontal: 5),
      alignment: Alignment.center,
      decoration: BoxDecoration(color: muted ? sz.inkMuted : sz.clay, borderRadius: BorderRadius.circular(9)),
      child: marked
          ? null
          : Text(badgeText(count),
              style: szTabular(fontSize: kFontMicro, fontWeight: FontWeight.w600, color: sz.surface, height: 1)),
    );
  }
}

/// 平台服务号名字后面的认证标。只有「超级赞」这一行会有 —— 用户自己建的群、频道、机器人一律没有,
/// 所以就算有人把群名起成「超级赞」,也仿不出这个标。
class VerifiedMark extends StatelessWidget {
  const VerifiedMark({super.key, this.size = 15});

  final double size;

  @override
  Widget build(BuildContext context) =>
      Icon(Icons.verified, size: size, color: Theme.of(context).sz.link, semanticLabel: '平台认证');
}

/// 名字后面的「机器人」小标(视频互动、开发者做的机器人)。
class BotTag extends StatelessWidget {
  const BotTag({super.key});

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
      decoration: BoxDecoration(color: sz.line, borderRadius: BorderRadius.circular(3)),
      child: Text('机器人', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted, height: 1.2)),
    );
  }
}

/// 固定会话的圆形图标头像:[soft] 是 clay 淡底 + clay 图标(平台服务号、订单群),
/// 否则是发丝线色的底 + 次要墨色图标(机器人、收藏夹、没头像的频道)。
class IconAvatar extends StatelessWidget {
  const IconAvatar({super.key, this.icon, this.child, this.size = 50, this.soft = false});

  final IconData? icon;
  final Widget? child;
  final double size;
  final bool soft;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: soft ? sz.claySoft : sz.line, shape: BoxShape.circle),
      child: child ?? Icon(icon, size: size * .46, color: soft ? sz.clay : sz.inkMuted),
    );
  }
}

/// 「以下为新消息」:两道发丝线夹一行 clay 小字。聊天页和「视频互动」用的是同一条。
class UnreadDivider extends StatelessWidget {
  const UnreadDivider({super.key});

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      child: Row(children: [
        Expanded(child: Container(height: 1, color: sz.line)),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10),
          child: Text('以下为新消息', style: TextStyle(fontSize: kFontNote, color: sz.clay)),
        ),
        Expanded(child: Container(height: 1, color: sz.line)),
      ]),
    );
  }
}

/// 固定会话页(平台服务号、视频互动)标题栏里的那一块:小头像 + 名字(+ 标)+ 一行说明。
class ConvHeaderTitle extends StatelessWidget {
  const ConvHeaderTitle({
    super.key,
    required this.avatar,
    required this.title,
    required this.subtitle,
    this.suffix = const [],
  });

  final Widget avatar;
  final String title;
  final String subtitle;
  final List<Widget> suffix;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Row(children: [
      avatar,
      const SizedBox(width: 10),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            Flexible(
              child: Text(title,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink, height: 1.25)),
            ),
            for (final w in suffix) Padding(padding: const EdgeInsets.only(left: 5), child: w),
          ]),
          Text(subtitle,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, fontWeight: FontWeight.w400)),
        ]),
      ),
    ]);
  }
}

/// 连接中 / 等待网络时标题后面的呼吸点(hold 色,一呼一吸)。系统关了动态效果就是一个不动的点。
class ConnDot extends StatefulWidget {
  const ConnDot({super.key});

  @override
  State<ConnDot> createState() => _ConnDotState();
}

class _ConnDotState extends State<ConnDot> with SingleTickerProviderStateMixin {
  // 一呼一吸各走一次「账本」时长:慢,但看得出在动 —— 这是「还在连」的意思,不是报错
  late final AnimationController _c = AnimationController(vsync: this, duration: SzMotion.ledger);

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (SzMotion.off(context)) {
      _c.stop();
      _c.value = 0;
    } else if (!_c.isAnimating) {
      _c.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hold = Theme.of(context).sz.hold;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, child) =>
          Opacity(opacity: 1 - .65 * SzMotion.standard.transform(_c.value), child: child),
      child: Container(width: 6, height: 6, decoration: BoxDecoration(color: hold, shape: BoxShape.circle)),
    );
  }
}
