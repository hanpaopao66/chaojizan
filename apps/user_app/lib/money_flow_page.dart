/// 「钱去哪了」独立页——账目透明是超级赞唯一别人抄不走的东西,
/// 从订单详情的一张折叠卡提升为一级页面(第八辑 #107)。
///
/// 三处入口都进这里:首页承诺条、订单详情的「钱去哪了」按钮、我的页「账目」组。
///
/// 金额全部由订单已有字段算出,不新增接口;各份之和必须对得上用户实付——
/// 这与服务端 services/audit.py 的恒等式是同一口径,对不上就是有 bug,
/// debug 模式下会打日志。分法本身在 [orderSplit]。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'five_percent.dart';
import 'trust_page.dart';

/// 分账里的一份钱。
class SplitPart {
  const SplitPart({
    required this.name,
    required this.short,
    required this.cents,
    required this.note,
    this.isHold = false,
  });

  /// 页面上的名字,如「商家实收」
  final String name;

  /// 订单列表那一行用的短名,如「商家」
  final String short;
  final int cents;
  final String note;

  /// 平台拿走的那一份(hold 色);其余是流到别人手里的钱
  final bool isHold;
}

/// 一单的钱怎么分。
class OrderSplit {
  const OrderSplit(this.parts, {this.extraCents = 0});

  /// 已经去掉金额为 0 的份,顺序就是页面上的顺序
  final List<SplitPart> parts;

  /// 帮买实付超出预估、事后向用户补收的那部分。不在 totalCents 里,
  /// 但同样经平台结给了骑手 —— 对账时要加回来
  final int extraCents;

  int get sumCents => parts.fold(0, (a, p) => a + p.cents);
}

/// 一单的钱怎么分 —— **和服务端 services/settlement.py 同一个分法**。
///
/// 原来三处(订单卡、详情分账卡、这一页)对所有单都用外卖那一个公式:
/// 商家 = 菜品 + 打包 − 满减 − 佣金、骑手 = 配送费 + 小费、平台 = 佣金。
/// 有两类单套不上:
///
/// - **跑腿单**:没有商家。平台收的是跑腿费的 2%(支付时落在 commission_cents 上),
///   骑手拿剩下的。套外卖公式的话「商家实收」是一个负数,
///   而「配送费 100% 归骑手」那句是错的。帮买的商品款存在 food_cents 里,
///   它是**替用户垫付的钱**,按小票实付结给骑手、多的退回,谁的收入都不是 —— 单列;
/// - **商家自送单**:没有骑手,配送费并进商家那一行
///   (settlement.credit_merchant_for_order)。原来它被写成「骑手所得」。
///
/// 对账口径:各份之和 = 用户实付 + 平台补贴 + 帮买补收([OrderSplit.extraCents])。
OrderSplit orderSplit(Order o) {
  if (o.isErrand) {
    final service = o.commissionCents;
    final parts = <SplitPart>[
      SplitPart(
          name: '骑手所得',
          short: '骑手',
          cents: o.deliveryFeeCents + o.tipCents - service,
          note: '跑腿费扣掉平台服务费,余下全归骑手'),
      SplitPart(
          name: '平台服务费',
          short: '平台',
          cents: service,
          note: '跑腿费的 2%。跑腿没有商家,这是平台在这条业务上唯一的收入',
          isHold: true),
    ];
    var extra = 0;
    if (o.isErrandBuy) {
      final goods = o.goodsActualCents ?? o.goodsBudgetCents;
      final back = o.goodsBudgetCents - goods;
      extra = back < 0 ? -back : 0;
      parts.add(SplitPart(
          name: '商品款',
          short: '商品款',
          cents: goods,
          note: o.goodsActualCents == null
              ? '骑手替你垫付,按小票实付结给他;小票还没传,先按预付算'
              : '骑手替你垫付,按小票实付结给他,平台一分不抽'));
      if (back > 0) {
        parts.add(SplitPart(
            name: '退回给你',
            short: '退回',
            cents: back,
            note: '预付的商品款比小票多出的部分,原路退回'));
      }
    }
    return OrderSplit([for (final p in parts) if (p.cents != 0) p],
        extraCents: extra);
  }
  // 商家侧毛额:佣金是按这个数收的,不是按用户实付
  final gross = o.merchantNetCents + o.commissionCents;
  final rider = o.selfDelivery ? 0 : o.deliveryFeeCents + o.tipCents;
  final parts = <SplitPart>[
    SplitPart(
        name: '商家实收',
        short: '商家',
        cents: o.merchantNetCents + (o.selfDelivery ? o.deliveryFeeCents : 0),
        note: o.selfDelivery
            ? '菜品 + 打包 − 满减,加上配送费(商家自己送),只扣 5% 服务费'
            : '菜品 + 打包 − 满减,只扣 5% 服务费'),
    if (rider > 0)
      SplitPart(
          name: '骑手所得',
          short: '骑手',
          cents: rider,
          note: o.tipCents > 0
              ? '配送费 + 小费 100% 归骑手,平台分文不取'
              : '配送费 100% 归骑手,平台分文不取'),
    SplitPart(
        name: '平台留存',
        short: '平台',
        cents: o.commissionCents,
        // 占实付 4.5%、占商家侧 5% —— 两个口径都写出来,
        // 只写一个数会被当成玩数字
        note: '服务器、客服与赔付池 · 按商家侧口径 '
            '${yuan(o.commissionCents)} / ${yuan(gross)} = '
            '${gross == 0 ? "5" : (o.commissionCents / gross * 100).toStringAsFixed(0)}%',
        isHold: true),
  ];
  return OrderSplit(parts);
}

/// 把 [orderSplit] 画成分账条(这一页和订单详情的分账卡共用)。
///
/// 平台那一份在外卖 / 买菜单上挂「为什么是 5%」的追问;
/// 跑腿单那一份是跑腿费的 2%,5% 那张说明对不上它,不挂
List<SzFlowItem> flowItems(
    BuildContext context, Order order, OrderSplit split) {
  final total = order.totalCents;
  return [
    for (final p in split.parts)
      SzFlowItem(
        name: p.name,
        amountCents: p.cents,
        fraction: total == 0 ? 0 : p.cents / total,
        note: p.note,
        isHold: p.isHold,
        onWhy: p.isHold && !order.isErrand
            ? () => showFivePercentSheet(context)
            : null,
      ),
  ];
}

/// 无订单上下文的入口(首页承诺条、我的页「账目」组)。
///
/// 拿最近一笔有分账的订单展示真实数字;一单都没有(新用户/游客)时
/// 退回平台口径的说明弹层——不编一笔假订单来演示透明。
Future<void> openMoneyFlow(BuildContext context, ApiClient api) async {
  Order? latest;
  try {
    final orders = await api.myOrders();
    for (final o in orders) {
      if (o.commissionCents > 0 && o.totalCents > 0) {
        latest = o;
        break;
      }
    }
  } catch (_) {
    // 拉单失败不该把入口变成死路,退回说明弹层
  }
  if (!context.mounted) return;
  if (latest == null) {
    await showFivePercentSheet(context);
    return;
  }
  await Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => MoneyFlowPage(api: api, order: latest!)));
}

class MoneyFlowPage extends StatelessWidget {
  const MoneyFlowPage({super.key, required this.api, required this.order});

  final ApiClient api;
  final Order order;

  /// 平台留存的去向。比例写死在这里而不是接口下发——它是平台的口径承诺,
  /// 改动应该走发版和公示,不该是运营后台随手能调的数字。
  /// 与 five_percent.dart 的说明弹层、官网 transparency 页同源。
  static const _breakdown = [
    ('服务器与带宽', '≈ 42%'),
    ('客服与售后赔付池', '≈ 33%'),
    ('支付通道手续费', '≈ 15%'),
    ('其余留存', '≈ 10%'),
  ];

  /// 用「不做什么」写,比「我们致力于」有力。
  ///
  /// 第二条看单子说:跑腿单上平台确实从跑腿费里收了 2%,
  /// 这时候还写「不抽配送费」,就是在同一页上自相矛盾
  List<String> _promisesFor(Order o) => [
        '不做竞价排名,钱买不到靠前的位置',
        o.isErrand
            ? '跑腿只收跑腿费的 2%,账单上单列;帮买的商品款一分不抽'
            : '不抽配送费和小费,这两项 100% 归骑手',
        '不做大数据杀熟,同一时刻同一家店,所有人同价',
        '不靠补贴换增长,也就不会有断补后的涨价',
      ];

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final total = order.totalCents;
    final split = orderSplit(order);

    assert(() {
      // 平台补贴(平台券抵掉的,以前的单还有首单立减)用户没付、商家照收;帮买超支是事后补收的
      final expect = total + order.subsidyCents + split.extraCents;
      if (split.sumCents != expect) {
        debugPrint('分账对不上:${split.sumCents} != $expect(订单 ${order.orderNo})'
            ' —— 与 services/audit.py 的恒等式同口径,请查后端');
      }
      return true;
    }());

    return SzPageScaffold(
      // 限宽用宽档:资金流向图挤在 720 里看不清 —— 
      // 宽度上限按**内容形态**选,不是统一限死
      contentMaxWidth: kWideMaxWidth,
      appBar: AppBar(title: const Text('钱去哪了')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 28),
        children: [
          Text.rich(
            TextSpan(children: [
              const TextSpan(text: '你付的 '),
              TextSpan(
                  text: yuan(total),
                  style: szMoney(
                      fontSize: 25, fontWeight: FontWeight.w600, color: sz.ink)),
              const TextSpan(text: ',\n拆到分。'),
            ]),
            style: TextStyle(
                fontSize: 25,
                height: 1.3,
                fontWeight: FontWeight.w500,
                color: sz.ink),
          ),
          const SizedBox(height: 7),
          Text('${_dateOf(order)} · 订单 ${order.orderNo}',
              style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
          const SizedBox(height: 18),

          // 账目台面(#133):账目透明是唯一抄不走的差异点,
          // 用一张更"硬"的深色台面把它从页面里托出来
          SzLedgerCard(
            padding: const EdgeInsets.symmetric(
                horizontal: kCardPad, vertical: 2),
            child: SzMoneyFlow(
              whyLabel: '为什么是 5%',
              items: flowItems(context, order, split),
            ),
          ),

          // 退过款的单:上面是原始分法,退款怎么从各方扣回来在账本里
          if (order.refundCents > 0) ...[
            const SizedBox(height: 8),
            Text('这一单退过 ${yuan(order.refundCents)}。上面是退款前的分法,'
                '退款从哪一方扣回,以账本存证为准。',
                style: TextStyle(
                    fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
          ],

          if (order.discountCents > 0 || order.subsidyCents > 0) ...[
            const SizedBox(height: 10),
            SzCard(
              padding: const EdgeInsets.symmetric(
                  horizontal: kCardPad, vertical: 4),
              child: Column(children: [
                if (order.discountCents > 0)
                  SzFeeRow(
                      label: '商家让利',
                      note: '满减,商家承担',
                      amountCents: order.discountCents,
                      negative: true),
                if (order.subsidyCents > 0)
                  SzFeeRow(
                      label: '平台补贴',
                      note: '平台承担',
                      amountCents: order.subsidyCents,
                      negative: true),
              ]),
            ),
          ],

          const SizedBox(height: 22),
          SzSectionTitle(order.isErrand ? '平台收的服务费用在哪' : '平台留存的 5% 用在哪'),
          const SizedBox(height: 9),
          SzCard(
            padding: const EdgeInsets.symmetric(
                horizontal: kCardPad, vertical: 4),
            child: Column(children: [
              for (final (name, pct) in _breakdown)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Row(children: [
                    Expanded(
                        child: Text(name,
                            style: TextStyle(
                                fontSize: 13, color: sz.inkMuted))),
                    Text(pct, style: szFigure(fontSize: 13, color: sz.ink)),
                  ]),
                ),
            ]),
          ),

          const SizedBox(height: 22),
          const SzSectionTitle('我们承诺不做的事'),
          const SizedBox(height: 9),
          SzCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final (i, line) in _promisesFor(order).indexed) ...[
                  if (i > 0) const SizedBox(height: 9),
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('—', style: TextStyle(color: sz.inkMuted)),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(line,
                          style: TextStyle(
                              fontSize: 12.5, height: 1.6, color: sz.ink)),
                    ),
                  ]),
                ],
              ],
            ),
          ),

          const SizedBox(height: 20),
          OutlinedButton(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => TrustPage(api: api))),
            child: const Text('查看账本存证'),
          ),
          const SizedBox(height: 10),
          Text('账目对用户、商家、骑手三方公开;每日账本上链存证,'
              '第三方见证节点可独立复核。',
              textAlign: TextAlign.center,
              style:
                  TextStyle(fontSize: 11.5, height: 1.6, color: sz.inkMuted)),
        ],
      ),
    );
  }

  String _dateOf(Order o) {
    final t = DateTime.tryParse(o.createdAt)?.toLocal();
    if (t == null) return '';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${t.year}-${two(t.month)}-${two(t.day)}';
  }
}
