import 'package:flutter/material.dart';

import 'brand.dart';
import 'channels.dart';

/// 首页金刚区:一律聚合式(字块 + 名字),排几列问 [channelGridColumns]。
///
/// ## 为什么在 shared 而不是在首页里
///
/// 排版规则本来就在这儿,有测试锁着;渲染也放在这儿,
/// 就能拿 1 个、5 个、12 个频道当场渲染,
/// 连长辈版 1.4× 下会不会撑爆都能测(见 `channel_grid_render_test.dart`)。
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

  /// 一格:字块 44 + 名字,没有卡片底、没有副标题(设计稿 1b / 2a 的聚合式)。
  ///
  /// 聚合平台的首页都是这个排法,每行 4–5 个,一屏放得下十几个频道。
  /// 「取件送件 · 收 2%」这类说明放在频道页和官网费率表里,不占首页。
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
            Text(ch.title,
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
      // 把可用宽度传进去:宽屏上格子太宽是浪费,该多排几列(#295)
      final cols = channelGridColumns(channels.length, width: box.maxWidth);
      final cell = (box.maxWidth - gap * (cols - 1)) / cols;
      return Wrap(
        spacing: gap,
        runSpacing: gap,
        children: [
          for (final ch in channels)
            SizedBox(
                width: cell,
                child: _compact(context, ch, () => onTap(ch))),
        ],
      );
    });
  }
}
