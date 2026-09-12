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
    // 跑腿单没有真商家,挂在本城一个 biz_type='errand' 的服务主体上
    // (server/app/services/errand.py)—— 所以订单页能按 biz_type 把它认出来
    key: 'errand', name: '帮我送', glyph: '跑', sub: '取件送件 · 收 2%',
    tone: 3, bizType: 'errand',
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

/// 金刚区每行排几格。**一律聚合式**:字块在上、名字在下,没有卡片底、没有副标题。
///
/// ## 为什么不再按频道数切卡片式
///
/// 以前是「≤4 个频道用卡片式(带一句说明),5 个往上换聚合式」,理由是
/// 「帮我送」「超值团购」还没有认知基础,「取件送件 · 收 2%」那句话在干活。
/// 2026-09 的浅色定稿(设计稿 1b / 2a)把金刚区定成了聚合式,不分频道数 ——
/// 频道只开了两个的时候,两张大卡占掉首屏三分之一,真正要选的店被挤到折线下面。
/// 那句说明挪进了频道页和官网的费率表,首页只负责「从哪进」。
///
/// ## 两条规则
///
/// 1. **不留空格子**:5 个以内有几个排几列。只开两个频道时是两格平分一行,
///    不是左边两格、右边空三格 —— 那样看着像页面没加载完;
/// 2. **末行不孤单**:5 个往上优先 5 列,5 列会剩 1 个就退 4 列。
///
/// | 频道数 | 选择 | 结果 |
/// |---|---|---|
/// | 1–5 | 个数 | 一满行 |
/// | 6 | 5 列剩 1 ✗ → 4 列 | 4+2 |
/// | 7 | 5 列 | 5+2 |
/// | 9 | 5 列 | 5+4 |
/// | 11 | 5 列剩 1 ✗ → 4 列 | 4+4+3 |
///
/// 宽屏(#295):每格超过 ~120 就该多排一列(聚合式的格子只有一个字块加一行字,
/// 再宽就是两边空着),上限 8 列,同样不许末行只剩一个。
///
/// 放在 shared 而不是首页里,是为了**能被测试锁住** ——
/// 加频道时排版会不会退化成孤儿行,不该靠人肉数。
int channelGridColumns(int count, {double? width}) {
  if (count <= 0) return 1;
  if (width != null && width > 0) {
    var cols = (width / 120).floor();
    if (cols > 5) {
      // 先夹到频道数:列数比频道还多就会留空格子
      if (cols > count) cols = count;
      if (cols > 8) cols = 8;
      // 末行不许只剩一个。**要一直往下找**,不是减一次就完
      while (cols > 5 && count > cols && count % cols == 1) {
        cols--;
      }
      if (cols > 5) return cols;
      // 落到 5 列以下就交给下面的手机规则
    }
  }
  if (count <= 5) return count;
  // 5 列剩 1 个就退 4 列。4 列也剩 1 的情况(count=21、41…)认了 ——
  // 真到那时候该做分组或者二级页,不是继续在一个网格里挤
  return count % 5 == 1 && count % 4 != 1 ? 4 : 5;
}
