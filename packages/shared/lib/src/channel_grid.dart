import 'package:flutter/material.dart';

import 'brand.dart';
import 'channels.dart';
import 'sz_widgets.dart';

/// 首页金刚区。
///
/// ## 为什么在 shared 而不是在首页里
///
/// 排版规则([channelGridLayout] / [channelGridColumns])本来就在这儿,
/// 有测试锁着;但**渲染**留在首页时,聚合式那套代码在只有 4 个频道的今天
/// 一次都跑不到 —— 等于写完就搁着,等打车上线那天才第一次运行。
///
/// 搬过来之后,聚合式可以拿 5 个、8 个频道当场渲染,
/// 连长辈版 1.4× 下会不会撑爆都能测(见 `channel_grid_test.dart`)。
///
/// ## 只管长相,不管去哪
///
/// 点了跳哪个页面是各端自己的事(用户端有跑腿要接住订单去支付这种特例),
/// 所以路由通过 [onTap] 回调出去,这里一个页面都不 import。
class SzChannelGrid extends StatelessWidget {
  const SzChannelGrid({
    super.key,
    required this.onTap,
    this.channels = kChannels,
    this.gap = 9.0,
  });

  /// 点了某个频道。**入参是频道对象不是下标** —— 下标会随注册表顺序变。
  final void Function(SzChannel channel) onTap;

  /// 要显示哪些频道。默认全部;测试里传别的组合来验排版。
  final List<SzChannel> channels;

  final double gap;

  /// 频道字块:一个汉字画在自身 12% 的淡底上。
  ///
  /// 用汉字而不是图标,是因为中文语境里「碗/宿/券」比任何图标都直白,
  /// 而且不用为每个新频道画图。**这个字是频道的主标识,颜色只是加速器** ——
  /// 色觉缺陷下八个频道色最差只差 ΔE 8.7,光靠颜色分不开
  /// (见 brand.dart 里 channelTones 的文档)。任何时候都不许只留颜色去掉字。
  ///
  /// 做成方块底而不是让字裸着:单独一个字浮在卡片左上角、右边一大片空白,
  /// 看着就是"没排完"。加个底之后它是个图标,而不是一个掉队的字。
  static Widget glyph(BuildContext context, SzChannel ch, double size) {
    final c = channelColor(context, ch.key);
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(kRadiusSm),
      ),
      // 用 szDisplay 而不是 szFigure:szFigure 的中文回落是系统**黑**体 ——
      // 这个字块本来是照衬线数字的样子设计的,里面却坐着一个黑体字。
      // szDisplay 的中文走打包的宋体子集,字块和字终于是一套。
      // 尺寸 size*0.48 → 40/44px 的块里是 19~21px,是宋体撑得住的大小
      child: Text(ch.glyph,
          style: szDisplay(
              fontSize: size * 0.48,
              fontWeight: FontWeight.w600,
              color: c,
              height: 1.0)),
    );
  }

  /// 宽卡(卡片式 2 列时用):字块在左、标题副标题在右。
  /// 横过来排才用得上宽度 —— 竖着堆的话副标题旁边永远空着一半。
  Widget _wide(BuildContext context, SzChannel ch, VoidCallback tap) {
    final sz = Theme.of(context).sz;
    return SzCard(
      onTap: tap,
      padding: const EdgeInsets.all(12),
      child: Row(children: [
        glyph(context, ch, 40),
        const SizedBox(width: 11),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              // 频道名**允许折两行**。320 窄屏 + 长辈版 1.4× 下,
              // 字块和间距吃掉之后只剩 64px,「超值团购」要 81px ——
              // maxLines:1 会切成「超值团…」。频道名截断等于没写,
              // 宁可卡片高一点
              Text(ch.name,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      fontSize: 14.5,
                      fontWeight: FontWeight.w600,
                      height: 1.25,
                      color: sz.ink)),
              const SizedBox(height: 2),
              // 长辈版 1.4× 下窄卡放不下,允许折两行而不是切成省略号 ——
              // 「取件送件 · 收…」这种半截话不如换行
              Text(ch.sub,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      fontSize: 11.5, height: 1.35, color: sz.inkMuted)),
            ],
          ),
        ),
      ]),
    );
  }

  /// 窄卡(卡片式 3 列时用):竖排居中。宽度不够横排就别横排,
  /// 硬横排会把副标题挤成一列一个字。
  Widget _narrow(BuildContext context, SzChannel ch, VoidCallback tap) {
    final sz = Theme.of(context).sz;
    return SzCard(
      onTap: tap,
      padding: const EdgeInsets.fromLTRB(8, 12, 8, 12),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          glyph(context, ch, 36),
          const SizedBox(height: 8),
          // 同 _wide:宁可折行也不截断频道名
          Text(ch.name,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: TextStyle(
                  fontSize: 13.5,
                  fontWeight: FontWeight.w600,
                  height: 1.2,
                  color: sz.ink)),
          const SizedBox(height: 3),
          Text(ch.sub,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: TextStyle(
                  fontSize: 10.5, height: 1.3, color: sz.inkMuted)),
        ],
      ),
    );
  }

  /// 聚合式(≥5 个频道时用):只有字块和名称,没有卡片底、没有副标题。
  ///
  /// 聚合平台的首页都是这个排法,每行 4–5 个,一屏放得下十几个频道。
  /// 代价是没地方写「取件送件 · 收 2%」—— 所以频道少的时候不用它。
  Widget _compact(BuildContext context, SzChannel ch, VoidCallback tap) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: tap,
      borderRadius: BorderRadius.circular(kRadiusSm),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 8),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            glyph(context, ch, 44),
            const SizedBox(height: 7),
            // 放不下就换行,**不要 softWrap:false**。
            //
            // 5 列时每格只有 58px 宽(360 屏)。正常字号「超值团购」四个字
            // 约 46px 放得下,但这个 App 有长辈版 1.4× —— 那时是 64px,
            // 不换行就直接画到隔壁格子上去了(overflow:visible 不报错,
            // 只是默默画出界,比报错还难发现)。换行成两行,
            // 既没出界,也没把用户要的大字缩回去。
            Text(ch.name,
                maxLines: 2,
                textAlign: TextAlign.center,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    fontSize: 11.5,
                    fontWeight: FontWeight.w500,
                    height: 1.2,
                    color: sz.ink)),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(builder: (context, box) {
      final cols = channelGridColumns(channels.length);
      final cell = (box.maxWidth - gap * (cols - 1)) / cols;
      // 排法由**频道数**决定,不是由列数决定。
      // 卡片式内部再按宽度选横排还是竖排
      final entry = switch (channelGridLayout(channels.length)) {
        SzChannelLayout.compact => _compact,
        SzChannelLayout.card => cols <= 2 ? _wide : _narrow,
      };
      return Wrap(
        spacing: gap,
        runSpacing: gap,
        children: [
          for (final ch in channels)
            SizedBox(
                width: cell,
                child: entry(context, ch, () => onTap(ch))),
        ],
      );
    });
  }
}
