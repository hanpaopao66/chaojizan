import 'package:flutter/material.dart';

import 'brand.dart';

/// 频道注册表(#132):聚合平台的频道是**开放集合**,这里是唯一事实来源。
///
/// ## 为什么要有这个文件
///
/// 老口径是首页手写三段入口、全部用 `sz.clay`,频道内页没有任何标识 ——
/// 用户从外卖进了住宿,除了内容变了,没有任何信号说明换了一个世界。
///
/// 更要命的是可扩展性:如果直接写死「外卖=橘 / 住宿=绿 / 团购=琥珀」,
/// 第四个频道(打车)来的时候要改色板、改金刚区、改每个内页,第五个再来一遍。
/// 三次之后就没人愿意加频道了。所以**按开放集合设计**:
/// 新频道在 [kChannels] 加一行,组件一行不改。
///
/// ## 平台色与频道色是两回事
///
/// `clay` 黏土橘是**平台色** —— 平台身份、承诺条、跨频道主 CTA(支付/确认下单)。
/// **它不属于外卖。** 如果外卖独占品牌色,后进的每个频道在视觉上都是二等公民,
/// 而聚合平台的前提是各频道地位平等。外卖和别人一样领一个频道色。
///
/// ## 频道色能出现在哪(白名单)
///
/// - 频道入口卡的字符与细节;
/// - 频道内页头部的标识条(细,不喧宾夺主);
/// - 频道归属 chip(订单卡上标「住宿」);
/// - 该频道空状态插画的着色。
///
/// **不能**用于实底主 CTA —— 那是平台色的位置,「一屏一个实底按钮」的纪律
/// 不能因为分频道就破掉。**不能**用于金额与状态 —— 那是 earn/hold/danger 的语义位。
@immutable
class SzChannel {
  const SzChannel({
    required this.key,
    required this.name,
    required this.glyph,
    required this.sub,
    required this.tone,
    this.bizType,
  });

  /// 稳定标识,服务端与埋点共用。**不要改已上线频道的 key。**
  final String key;

  /// 中文名(入口卡标题、归属 chip)
  final String name;

  /// 单字符标识。用一个汉字而不是图标:中文语境里「碗/宿/券」比任何图标都直白,
  /// 且不需要为每个新频道画图
  final String glyph;

  /// 入口卡副标题,一句话说清这个频道卖什么
  final String sub;

  /// 色槽序号,取 [SzColors.channelTones] 的下标。
  /// **按顺序领用,不许自由取色** —— 聚合平台变成彩虹糖,
  /// 就是从"这个频道想要个亮蓝"开始的
  final int tone;

  /// 对应服务端的 `merchants.biz_type`;纯前端频道(如团购)为空
  final String? bizType;
}

/// 已上线频道。**新增频道只改这里。**
const List<SzChannel> kChannels = [
  SzChannel(
    key: 'food', name: '点外卖', glyph: '碗', sub: '附近的店',
    tone: 0, bizType: 'food',
  ),
  SzChannel(
    // 超市、水果店、便利店。**和外卖是同一套下单流程** ——
    // 骑手接单、到店、拣货、取货、送达,只是货架上摆的东西不同。
    // 所以它复用 /merchants 那套接口(带 biz_type=retail),不另起一路。
    // 色槽取 5 —— 前五个是**语义绑定**的(0 外卖 1 住宿 2 团购
    // 3 打车 4 帮送),5 起才是预留槽。按顺序往下顺号会把住宿的苔绿
    // 挪成团购的赭金,整排颜色跟着错位。
    key: 'retail', name: '买菜买水果', glyph: '果', sub: '超市 / 水果 / 便利店',
    tone: 5, bizType: 'retail',
  ),
  SzChannel(
    key: 'stay', name: '住宿', glyph: '宿', sub: '钟点房 / 民宿',
    tone: 1, bizType: 'hotel',
  ),
  SzChannel(
    key: 'voucher', name: '超值团购', glyph: '券', sub: '到店核销',
    tone: 2,
  ),
  SzChannel(
    key: 'errand', name: '帮我送', glyph: '跑', sub: '取件送件 · 收 2%',
    tone: 3,
  ),
  // 下一个频道加在这里即可,例如:
  // SzChannel(key: 'ride', name: '打车', glyph: '车', sub: '一口价 · 不抽司机',
  //           tone: 3),
];

/// 按 key 取频道。**取不到返回 null 而不是抛异常** ——
/// 服务端将来下发一个客户端还不认识的新频道时,页面要能正常显示
/// (调用方回退到平台色),而不是白屏。
SzChannel? channelOf(String? key) {
  if (key == null || key.isEmpty) return null;
  for (final c in kChannels) {
    if (c.key == key) return c;
  }
  return null;
}

/// 按服务端的 biz_type 反查频道(订单/商家卡标频道归属用)。
SzChannel? channelOfBizType(String? bizType) {
  if (bizType == null || bizType.isEmpty) return null;
  for (final c in kChannels) {
    if (c.bizType == bizType) return c;
  }
  return null;
}

/// 取频道色。**频道未知或色槽越界时回退平台色**,永远给得出一个能用的颜色。
Color channelColor(BuildContext context, String? key) {
  final sz = Theme.of(context).sz;
  final ch = channelOf(key);
  if (ch == null || ch.tone < 0 || ch.tone >= sz.channelTones.length) {
    return sz.clay;
  }
  return sz.channelTones[ch.tone];
}

/// 频道标识条:频道内页头部用。细一条,只是"你在哪个世界"的提示,
/// 不抢内容的戏 —— 所以是 3px 而不是一整块色带。
class SzChannelBar extends StatelessWidget {
  const SzChannelBar(this.channelKey, {super.key});

  final String channelKey;

  @override
  Widget build(BuildContext context) => Container(
        height: 3,
        color: channelColor(context, channelKey),
      );
}

/// 频道归属标:订单卡、搜索结果里标明"这条属于哪个频道"。
class SzChannelChip extends StatelessWidget {
  const SzChannelChip(this.channelKey, {super.key, this.dense = true});

  final String channelKey;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final ch = channelOf(channelKey);
    if (ch == null) return const SizedBox.shrink();
    final c = channelColor(context, channelKey);
    return Container(
      padding: EdgeInsets.symmetric(
          horizontal: dense ? 6 : 9, vertical: dense ? 2 : 3),
      decoration: BoxDecoration(
        border: Border.all(color: c),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text('${ch.glyph} ${ch.name}',
          style: TextStyle(
              fontSize: dense ? 10.5 : 12,
              fontWeight: FontWeight.w500,
              color: c)),
    );
  }
}

/// 金刚区的两种排法。
///
/// 参考聚合平台(盒马、美团买菜、千岛)的首页,金刚区一律是
/// **每行 4–5 个、图标在上标签在下、没有副标题**。密度高,扩到十几个也不塌。
///
/// 但那个排法有个前提:**用户已经知道每个频道是什么**。
/// 美团能把副标题去掉,是因为所有人都知道「外卖」是什么。
/// 我们的「帮我送」「超值团购」还没有这个认知基础 ——
/// 「取件送件 · 收 2%」这句话现在是在干活的,不是装饰。
///
/// 所以按频道数切:少的时候把话说清楚,多的时候保证排得下。
enum SzChannelLayout {
  /// 卡片式:2–3 列,图标 + 名称 + 一句话说明。频道少时用。
  card,

  /// 聚合式:4–5 列,只有图标和名称。频道多到卡片排不下时用。
  compact,
}

/// 卡片式最多撑几个频道。
///
/// 5 个开始,卡片式要么排成 3+2(第二行空一半)、要么每格窄到
/// 副标题折三行 —— 那时候副标题已经不"在干活"了,不如换排法。
const int kChannelCardMax = 4;

/// 该用哪种排法。**页面不要自己判断频道数**,问这里。
SzChannelLayout channelGridLayout(int count) =>
    count <= kChannelCardMax ? SzChannelLayout.card : SzChannelLayout.compact;

/// 金刚区每行排几格。
///
/// **唯一的目标是避开「末行只剩一个」。** 上线频道曾经是 4 个,而首页写死
/// 3 列 —— 排出来是 3+1,第二行一张卡孤零零靠左,右边整整空掉三分之二,
/// 看着就像页面没加载完。
///
/// 卡片式规则:优先 3 列;**3 列会剩 1 个、而 2 列不会**时退到 2 列。
///
/// | 频道数 | 3 列 | 选择 | 结果 |
/// |---|---|---|---|
/// | 3 | 3 | 3 列 | 一满行 |
/// | 4 | 3+1 ✗ | 2 列 | 2×2 |
///
/// 聚合式规则:优先 5 列,5 列会剩 1 个就退 4 列。
///
/// | 频道数 | 选择 | 结果 |
/// |---|---|---|
/// | 5 | 5 列 | 一满行 |
/// | 6 | 5 列剩 1 ✗ → 4 列 | 4+2 |
/// | 7 | 5 列 | 5+2 |
/// | 9 | 5 列 | 5+4 |
/// | 11 | 5 列剩 1 ✗ → 4 列 | 4+4+3 |
///
/// 放在 shared 而不是首页里,是为了**能被测试锁住** ——
/// 加频道时排版会不会退化成孤儿行,不该靠人肉数。
int channelGridColumns(int count, {double? width}) {
  if (count <= 0) return 1;
  // 宽屏(#295):格子太宽会让图标和字全挤在最左边,右边一大片空 ——
  // 1440px 上四个频道排两列,每格 550px,而内容只占前 200px。
  //
  // 判据是**每格多宽**不是屏幕多宽:一格超过 ~260 就该多排一列。
  // 上限 6 列 —— 再多一行扫过去就找不着了。
  if (width != null && width > 0) {
    var cols = (width / 260).floor();
    if (cols > 2) {
      // 先夹到频道数:列数比频道还多就会留空格子
      if (cols > count) cols = count;
      if (cols > 6) cols = 6;
      // 末行不许只剩一个。**要一直往下找**,不是减一次就完 ——
      // 7 个频道排 4 列剩 3(好),排 3 列剩 1(坏),减到 2 列又剩 1。
      // 减一次的写法在这里会停在坏的那一档
      while (cols > 2 && count > cols && count % cols == 1) {
        cols--;
      }
      if (cols > 2) return cols;
      // 落到 2 列以下就交给下面的窄屏规则,别硬凑
    }
  }
  if (count <= 2) return count;
  if (channelGridLayout(count) == SzChannelLayout.compact) {
    // 5 列剩 1 个就退 4 列。4 列也剩 1 的情况(count=13、17…)认了 ——
    // 真到那时候该做分组或者二级页,不是继续在一个网格里挤
    return count % 5 == 1 && count % 4 != 1 ? 4 : 5;
  }
  // 3 列剩 1 个、2 列整除 → 退 2 列(4、10、16…)
  if (count % 3 == 1 && count % 2 == 0) return 2;
  return 3;
}
