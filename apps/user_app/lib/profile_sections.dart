import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 「我的」页的板块卡与板块聚合页(2026-09-17)。
///
/// ## 为什么要按板块归类
///
/// 改版前这一页把券、地址、收藏、帮助混在一张网格卡里,和订单、账目并列。
/// 用户找「外卖的东西」要在几块之间来回扫,而各板块自己其实是有主场的
/// (外卖有订单、券、地址、收藏;住宿有住宿单和发票;团购有券包)。
///
/// 现在一个板块一张卡:标题一行(频道字 + 名字 + 查看更多),下面一行图标。
/// 图标只放最高频的几格,放不下的、低频的进「查看更多」——
/// **不让卡片无限变长,也不让入口消失**。
///
/// ## 判据没变
///
/// 一行图标仍然是 [SzIconGrid] 的那条:标题两三个字就说清、彼此平级、
/// 给不出状态值。给得出状态值或需要一句说明的入口([hint] 非空且在聚合页里
/// 才显示说明)留在聚合页的 [SzEntryTile] 里。
class ProfileSectionEntry {
  const ProfileSectionEntry({
    required this.icon,
    required this.label,
    this.hint = '',
    this.badge = 0,
    this.badgeColor,
    required this.onTap,
  });

  final IconData icon;

  /// 两三个字说清的标题(进网格)。
  final String label;

  /// 聚合页那一行的说明。入口列表回答「这是什么」,
  /// 目的页回答「为什么重要」—— 所以这里**只允许一行**,多了会被切掉。
  final String hint;

  /// 角标数字。0 = 不显示。含义跟 [SzIconGridItem.badge] 同一条:
  /// **只给「你还有事要做」或「手里还有几张」的格子用**。
  final int badge;

  final Color? badgeColor;

  final VoidCallback onTap;
}

/// 一个板块的卡片:标题行(频道字 + 板块名 + 查看更多)+ 一行图标。
///
/// 「查看更多」只在**入口多到一行放不下**时出现 —— 放得下还挂一个
/// 「查看更多」,点进去是同一批入口,那是把一次点击卖给用户。
/// 板块入口不超过 [rowSize] 个时标题行整行不可点。
class ProfileSectionCard extends StatelessWidget {
  const ProfileSectionCard({
    super.key,
    required this.title,
    required this.glyph,
    required this.channelKey,
    required this.entries,
    this.onBrowse,
    this.browseLabel = '去逛逛',
    this.rowSize = 4,
  });

  /// 板块名(频道名 / 内容板块名)。
  final String title;

  /// 频道单字标识,画在标题前,颜色取频道色 ——
  /// 和首页金刚区、订单卡的频道归属是同一套色,扫一眼就知道是哪个世界。
  final String glyph;

  /// 频道 key,取色用。视频这类不是频道的板块会回落到平台色。
  final String channelKey;

  /// 全部入口,**顺序就是聚合页的顺序**;前 [rowSize] 个进第一行。
  final List<ProfileSectionEntry> entries;

  /// 聚合页顶上的回流入口(去点外卖 / 去逛团购)。
  ///
  /// 没有它,聚合页只有「我的」侧入口:用户看完券想再下一单得退回首页。
  /// 各板块的**主入口仍然是金刚区那一格**,这里只是补一条回路。
  /// null = 这个板块还没有可去的列表页(或测试里没接外壳),不画按钮。
  final VoidCallback? onBrowse;

  /// 回流按钮的文案。默认「去逛逛」,各板块给更具体的说法
  final String browseLabel;

  final int rowSize;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final color = channelColor(context, channelKey);
    final shown = entries.length > rowSize ? rowSize : entries.length;
    final hasMore = entries.length > shown;
    void openMore() {
      Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => ProfileSectionPage(
              title: title,
              glyph: glyph,
              channelKey: channelKey,
              entries: entries,
              onBrowse: onBrowse,
              browseLabel: browseLabel)));
    }

    return Card(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        InkWell(
          onTap: hasMore ? openMore : null,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(kCardPad, 12, kCardPad, 0),
            child: Row(children: [
              Text(glyph,
                  style: TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w600, color: color)),
              const SizedBox(width: 6),
              Text(title,
                  style: TextStyle(
                      fontSize: kFontBodyLg,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
              const Spacer(),
              if (hasMore) ...[
                Text('查看更多',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                Icon(Icons.chevron_right, size: 16, color: sz.inkFaint),
              ],
            ]),
          ),
        ),
        SzIconGrid(
          columns: shown,
          items: [
            for (final e in entries.take(shown))
              SzIconGridItem(
                icon: e.icon,
                label: e.label,
                badge: e.badge,
                badgeColor: e.badgeColor,
                onTap: e.onTap,
              ),
          ],
        ),
        const SizedBox(height: 6),
      ]),
    );
  }
}

/// 板块聚合页:「查看更多」的去处,列出该板块**全部**入口。
///
/// 为什么不复用原来的卡片继续往下摊:那一张卡会从「一行」变成两三行,
/// 把「我的」页整体顶长,而低频入口(开发票、食安投诉)一年点一次,
/// 不该占首屏以下每一屏的位置。收进这里,名字和说明反而给得全。
class ProfileSectionPage extends StatelessWidget {
  const ProfileSectionPage({
    super.key,
    required this.title,
    required this.glyph,
    required this.channelKey,
    required this.entries,
    this.onBrowse,
    this.browseLabel = '去逛逛',
  });

  final String title;
  final String glyph;
  final String channelKey;
  final List<ProfileSectionEntry> entries;

  /// 顶上的回流入口,见 [ProfileSectionCard.onBrowse]
  final VoidCallback? onBrowse;
  final String browseLabel;

  @override
  Widget build(BuildContext context) {
    final color = channelColor(context, channelKey);
    return SzPageScaffold(
      contentMaxWidth: kContentMaxWidth,
      appBar: AppBar(
        title: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(glyph,
              style: TextStyle(
                  fontSize: 15, fontWeight: FontWeight.w600, color: color)),
          const SizedBox(width: 6),
          Text(title),
        ]),
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 24),
        children: [
          // 回流入口放顶上:看完「我的」想再买一单,不用退回首页找金刚区。
          // 实底按钮全页只有这一个 —— 它是这个板块的主 CTA,不和入口列表抢
          if (onBrowse != null) ...[
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: onBrowse,
                icon: const Icon(Icons.storefront_outlined, size: 18),
                label: Text(browseLabel),
              ),
            ),
            const SizedBox(height: 12),
          ],
          SzEntryGroup(children: [
            for (final e in entries)
              SzEntryTile(
                  icon: e.icon, title: e.label, hint: e.hint, onTap: e.onTap),
          ]),
        ],
      ),
    );
  }
}
