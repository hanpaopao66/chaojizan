import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 接单大厅(设计稿 5a)的几块:今日所得卡、排序条、抢单卡。
///
/// 抢单卡的结构照稿子:**配送费大字 + 取送两点 + 一行备注 + 抢单**。
/// 稿子外的决策信息(顺路绕多少米、约几分钟、时薪、难度提示、酒类、
/// 帮买加价进展)一行都不许丢 —— 骑手靠它们判断值不值,
/// 只是收进备注行和条件行,不再每条占一整行加 emoji。

/// 今日所得。数来自 `/riders/me/worklog`(服务端全量聚合),不是客户端求和。
class HallTodayCard extends StatelessWidget {
  const HallTodayCard({
    super.key,
    required this.earnedCents,
    required this.orders,
    required this.onOpenLedger,
  });

  /// null = 还没拉到(显示「—」,不显示 0 —— 0 看起来像真值)
  final int? earnedCents;
  final int? orders;
  final VoidCallback onOpenLedger;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzCard(
      onTap: onOpenLedger,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            // 外卖配送费平台一分不抽;跑腿单那 2% 在每张卡上单列,
            // 所以这里说的是规矩,不是「今天的每一分都没被抽」
            Text('今日所得 · 配送费不抽成',
                style: TextStyle(
                    fontSize: kFontMicro, letterSpacing: 1, color: sz.inkMuted)),
            const SizedBox(height: 2),
            Text.rich(
              TextSpan(children: [
                TextSpan(
                    text: earnedCents == null ? '—' : szYuanText(earnedCents!),
                    style: szMoney(
                        fontSize: kFigureLg, color: sz.earn, height: 1.1)),
                TextSpan(
                    text: orders == null ? '' : ' · $orders 单',
                    style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
              ]),
            ),
          ]),
        ),
        Text('账本 →', style: TextStyle(fontSize: kFontNote, color: sz.clay)),
      ]),
    );
  }
}

/// 抢单池的五种看法。
///
/// 稿子上是四个(离我最近 / 配送费高 / 顺路 / 帮我送),这里多一个**综合**
/// 并且默认选它:综合是服务端的顺序(距离 − 等待加权),等久了的远单
/// 会被慢慢往前推。默认改成「离我最近」的话,远一点的单谁都不先抢,
/// 一直等到 30 分钟被系统取消 —— 吃亏的是那一单的顾客和商家。
enum HallSort {
  composite('综合'),
  nearest('离我最近'),
  highFee('配送费高'),
  sameWay('顺路'),
  errand('帮我送');

  const HallSort(this.label);
  final String label;
}

/// 排序条:胶囊一排 + 末尾一个「接单偏好」入口(半径 / 总览图 / 怎么排的都在里面)。
class HallSortBar extends StatelessWidget {
  const HallSortBar({
    super.key,
    required this.value,
    required this.onChanged,
    required this.onOpenPrefs,
  });

  final HallSort value;
  final ValueChanged<HallSort> onChanged;
  final VoidCallback onOpenPrefs;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SizedBox(
      height: 44,
      child: Row(children: [
        Expanded(
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.fromLTRB(kPagePad, 6, 0, 2),
            children: [
              for (final s in HallSort.values)
                Padding(
                  padding: const EdgeInsets.only(right: 7),
                  child: Center(
                    child: SzChip(s.label,
                        selected: value == s, onTap: () => onChanged(s)),
                  ),
                ),
            ],
          ),
        ),
        IconButton(
          tooltip: '接单偏好',
          icon: Icon(Icons.tune, size: 20, color: sz.inkMuted),
          onPressed: onOpenPrefs,
        ),
        const SizedBox(width: 6),
      ]),
    );
  }
}

/// 卡右上角的小标。**只标一件事**,优先级:顺路 > 费高 > 待抢。
enum HallTag { sameWay, highFee, open }

/// 5a 抢单卡。
class HallOrderCard extends StatelessWidget {
  const HallOrderCard({
    super.key,
    required this.order,
    required this.tag,
    required this.toShopText,
    required this.tripText,
    required this.note,
    required this.alerts,
    required this.grabbing,
    this.grabbed = false,
    required this.onGrab,
    required this.onOpenRoute,
  });

  final Order order;
  final HallTag tag;

  /// 「380m」「1.7km」;直线兜底时带「≈」。null = 算不出来
  final String? toShopText;
  final String? tripText;

  /// 底部一行:出餐状态 / 约几分钟 / 时薪 / 跑腿费口径
  final String note;

  /// 条件行(难度提示、酒类、帮买加价…)。空 = 不占高度
  final List<({String text, Color color})> alerts;
  final bool grabbing;

  /// 刚抢到:按钮换成 earn 色的「已抢到」(动效规范 06),上层停一下再切页
  final bool grabbed;
  final VoidCallback onGrab;

  /// 点卡片看路线(原来那个「看路线」按钮)
  final VoidCallback onOpenRoute;

  /// 骑手这一单实际拿多少:配送费 + 小费;跑腿单扣掉平台那 2%
  static int riderTakeCents(Order o) =>
      o.deliveryFeeCents + o.tipCents - (o.isErrand ? o.commissionCents : 0);

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final accent = Theme.of(context).colorScheme.primary;
    final channel = order.isErrand
        ? 'errand'
        : (channelOfBizType(order.bizType)?.key ?? 'food');
    final (tagText, tagFg) = switch (tag) {
      HallTag.sameWay => ('顺路', sz.earn),
      HallTag.highFee => ('费高', sz.clay),
      HallTag.open => ('待抢', sz.inkMuted),
    };
    final feeLabel = order.isErrand
        ? '跑腿费 − 2%'
        : (order.tipCents > 0 ? '配送费 + 小费' : '配送费全额');

    return Material(
      color: sz.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        side: BorderSide(color: sz.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onOpenRoute,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SzChannelBar(channel),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic, children: [
                Text(szYuanText(riderTakeCents(order)),
                    style: szMoney(
                        fontSize: kFigureLg, color: sz.earn, height: 1)),
                const SizedBox(width: 8),
                Flexible(
                  child: Text(feeLabel,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ),
                const Spacer(),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: tagFg.withValues(alpha: .12),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(tagText,
                      style: TextStyle(
                          fontSize: kFontNote,
                          fontWeight: FontWeight.w600,
                          color: tagFg)),
                ),
              ]),
              const SizedBox(height: 10),
              _PointRow(
                pickup: true,
                text: order.isErrand
                    ? '取件 · ${order.merchantAddress}'
                    : '${order.merchantName} · ${order.merchantAddress}',
                trailing: toShopText,
              ),
              const SizedBox(height: 6),
              _PointRow(pickup: false, text: order.address, trailing: tripText),
              for (final a in alerts) ...[
                const SizedBox(height: 6),
                Text(a.text,
                    style: TextStyle(
                        fontSize: kFontNote,
                        fontWeight: FontWeight.w600,
                        height: 1.4,
                        color: a.color)),
              ],
              const SizedBox(height: 10),
              Row(children: [
                Expanded(
                  child: Text(note,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: kFontNote, height: 1.35, color: sz.inkMuted)),
                ),
                const SizedBox(width: 8),
                SzSuccessSwap(
                  done: grabbed,
                  button: SzPressScale(
                    enabled: !grabbing,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                        backgroundColor: accent,
                        // 视觉 32 高照稿子;点击区由 padded 撑到 48 ——
                        // 戴手套按不准的是点击区,不是看起来多大
                        minimumSize: const Size(72, 32),
                        padding: const EdgeInsets.symmetric(horizontal: 14),
                        tapTargetSize: MaterialTapTargetSize.padded,
                        textStyle: const TextStyle(
                            fontSize: kFontBody, fontWeight: FontWeight.w600),
                      ),
                      onPressed: grabbing ? null : onGrab,
                      child: Text(grabbing ? '抢单中…' : '抢单'),
                    ),
                  ),
                  success: Center(
                    child: Container(
                      height: 32,
                      padding: const EdgeInsets.symmetric(horizontal: 10),
                      decoration: BoxDecoration(
                        color: sz.earn,
                        borderRadius: BorderRadius.circular(kRadiusSm),
                      ),
                      child: Row(mainAxisSize: MainAxisSize.min, children: [
                        Icon(Icons.check, size: 16, color: sz.surface),
                        const SizedBox(width: 4),
                        Text('已抢到',
                            style: TextStyle(
                                fontSize: kFontBody,
                                fontWeight: FontWeight.w600,
                                color: sz.surface)),
                      ]),
                    ),
                  ),
                ),
              ]),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// 取 / 送两个点。取:空心墨圈;送:clay 实心点。
class _PointRow extends StatelessWidget {
  const _PointRow({required this.pickup, required this.text, this.trailing});

  final bool pickup;
  final String text;
  final String? trailing;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Row(children: [
      SzPointDot(pickup: pickup),
      const SizedBox(width: 8),
      Expanded(
        child: Text(text,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
                fontSize: kFontBody, color: pickup ? sz.ink : sz.inkMuted)),
      ),
      if (trailing != null) ...[
        const SizedBox(width: 8),
        Text(trailing!,
            style: szFigure(fontSize: kFontNote, color: sz.inkMuted)),
      ],
    ]);
  }
}

/// 取件点 / 送达点的小圆点:取 = 2px 墨色空心圈,送 = clay 实心。
/// 抢单卡、新单弹层、进行中任务卡三处同一个画法。
class SzPointDot extends StatelessWidget {
  const SzPointDot({super.key, required this.pickup});

  final bool pickup;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: pickup ? null : sz.clay,
        border: pickup ? Border.all(color: sz.ink, width: 2) : null,
      ),
    );
  }
}
