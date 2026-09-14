import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';

/// 资料页、UP 主空间上的标签和勋章(服务端 services/badges.py)。
///
/// 两样东西要一眼分得开:勋章是平台按公开条件发的,带一个小方块字(和平台服务号同一套 clay 淡底);
/// 标签是用户自己写的,就是一圈发丝线的小签。有人把「实名认证」写成标签,服务端会拦(冒充平台标志)。
///
/// 自己看自己时,隐藏了的也显示:勋章写「已隐藏」、整组标签淡下去并说一句,别人那边是没有的。
class TagsBadgesView extends StatelessWidget {
  const TagsBadgesView({super.key, required this.data, this.center = false, this.onEditTags});

  final TagsBadges data;

  /// 资料页居中排(名字下面);UP 主空间靠左
  final bool center;

  /// 自己看自己时,点标签去改。别人的标签不能点
  final VoidCallback? onEditTags;

  @override
  Widget build(BuildContext context) {
    if (data.isEmpty) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    final align = center ? WrapAlignment.center : WrapAlignment.start;
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: center ? CrossAxisAlignment.center : CrossAxisAlignment.start,
      children: [
        if (data.badges.isNotEmpty)
          Wrap(alignment: align, spacing: 6, runSpacing: 6, children: [
            for (final b in data.badges) BadgeChip(badge: b, onTap: () => showBadgeCondition(context, b)),
          ]),
        if (data.badges.isNotEmpty && data.tags.isNotEmpty) const SizedBox(height: 8),
        if (data.tags.isNotEmpty)
          Opacity(
            opacity: data.tagsHidden ? .55 : 1,
            child: Wrap(alignment: align, spacing: 6, runSpacing: 6, children: [
              for (final t in data.tags) SzChip(t, dense: true, textColor: sz.inkMuted, onTap: onEditTags),
            ]),
          ),
        if (data.tagsHidden && data.tags.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text('标签已隐藏,只有你自己看得到', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          ),
      ],
    );
  }
}

/// 勋章的图标:一个汉字画在小方块里(不引图片资源)。[muted] 是还没拿到的那种灰。
class BadgeGlyph extends StatelessWidget {
  const BadgeGlyph(this.icon, {super.key, this.size = 18, this.muted = false});

  final String icon;
  final double size;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: muted ? sz.surfaceAlt : sz.claySoft,
        borderRadius: BorderRadius.circular(size * .28),
      ),
      child: Text(icon,
          style: TextStyle(
              fontSize: size * .6, height: 1, fontWeight: FontWeight.w600, color: muted ? sz.inkMuted : sz.clay)),
    );
  }
}

/// 一枚勋章:小方块字 + 名字。点开看它的发放条件。
class BadgeChip extends StatelessWidget {
  const BadgeChip({super.key, required this.badge, this.onTap});

  final ProfileBadge badge;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    // 描边画在外面、水波纹在里面(和 SzChip 同一个搭法)
    return DecoratedBox(
      decoration: ShapeDecoration(shape: StadiumBorder(side: BorderSide(color: sz.line))),
      child: Material(
        type: MaterialType.transparency,
        shape: const StadiumBorder(),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(4, 4, 10, 4),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              // 读屏只读名字,不把方块里那个字再念一遍
              ExcludeSemantics(child: BadgeGlyph(badge.icon, muted: badge.hidden)),
              const SizedBox(width: 5),
              Text(badge.hidden ? '${badge.name} · 已隐藏' : badge.name,
                  style: TextStyle(fontSize: kFontNote, color: badge.hidden ? sz.inkMuted : sz.ink)),
            ]),
          ),
        ),
      ),
    );
  }
}

/// 一枚勋章的发放条件(和透明中心那一句一字不差)。
Future<void> showBadgeCondition(BuildContext context, ProfileBadge b) => szShowSheet<void>(
      context: context,
      builder: (ctx) {
        final sz = Theme.of(ctx).sz;
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 20),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                BadgeGlyph(b.icon, size: 30, muted: !b.earned),
                const SizedBox(width: 10),
                Text(b.name, style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
              ]),
              const SizedBox(height: 14),
              Text('平台按这个条件自动发', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              const SizedBox(height: 4),
              Text(b.condition, style: const TextStyle(fontSize: kFontBodyLg, height: 1.5)),
              const SizedBox(height: 12),
              Text('勋章不能买、不能申请,条件不再满足就不再显示。每一枚的条件都在透明中心公开。',
                  style: TextStyle(fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
              if (b.hidden) ...[
                const SizedBox(height: 8),
                // 不说「你把它设成了隐藏」:实名认证默认就不显示,没动过设置的人也是隐藏的
                Text('现在对别人隐藏,只有你自己看得到;在「标签和勋章」里可以打开。',
                    style: TextStyle(fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
              ],
            ]),
          ),
        );
      },
    );
