/// 「钱去哪了」独立页——账目透明是超级赞唯一别人抄不走的东西,
/// 从订单详情的一张折叠卡提升为一级页面(第八辑 #107)。
///
/// 三处入口都进这里:首页承诺条、订单详情的「钱去哪了」按钮、我的页「账目」组。
///
/// 金额全部由订单已有字段算出,不新增接口;三条之和必须等于用户实付——
/// 这与服务端 services/audit.py 的恒等式是同一口径,对不上就是有 bug,
/// debug 模式下会打日志。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'five_percent.dart';
import 'trust_page.dart';

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
  static const _promises = [
    '不做竞价排名,钱买不到靠前的位置',
    '不抽配送费和小费,这两项 100% 归骑手',
    '不做大数据杀熟,同一时刻同一家店,所有人同价',
    '不靠补贴换增长,也就不会有断补后的涨价',
  ];

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final total = order.totalCents;
    final riderGot = order.deliveryFeeCents + order.tipCents;
    // 商家侧毛额:佣金是按这个数收 5%,不是按用户实付
    final merchantGross = order.merchantNetCents + order.commissionCents;

    assert(() {
      final sum = order.merchantNetCents + riderGot + order.commissionCents;
      if (sum != total) {
        debugPrint('分账对不上:$sum != $total(订单 ${order.orderNo})'
            ' —— 与 services/audit.py 的恒等式同口径,请查后端');
      }
      return true;
    }());

    return Scaffold(
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

          SzCard(
            padding: const EdgeInsets.symmetric(
                horizontal: kCardPad, vertical: 2),
            child: SzMoneyFlow(
              whyLabel: '为什么是 5%',
              items: [
                SzFlowItem(
                  name: '商家实收',
                  amountCents: order.merchantNetCents,
                  fraction: total == 0 ? 0 : order.merchantNetCents / total,
                  note: '菜品 + 打包 − 满减,只扣 5% 服务费',
                ),
                if (riderGot > 0)
                  SzFlowItem(
                    name: '骑手所得',
                    amountCents: riderGot,
                    fraction: total == 0 ? 0 : riderGot / total,
                    note: order.tipCents > 0
                        ? '配送费 + 小费 100% 归骑手,平台分文不取'
                        : '配送费 100% 归骑手,平台分文不取',
                  ),
                SzFlowItem(
                  name: '平台留存',
                  amountCents: order.commissionCents,
                  fraction: total == 0 ? 0 : order.commissionCents / total,
                  // 占实付 4.5%、占商家侧 5%——两个口径都写出来,
                  // 只写一个数会被当成玩数字
                  note: '服务器、客服与赔付池 · 按商家侧口径 '
                      '${yuan(order.commissionCents)} / ${yuan(merchantGross)} = '
                      '${merchantGross == 0 ? "5" : (order.commissionCents / merchantGross * 100).toStringAsFixed(0)}%',
                  isHold: true,
                  onWhy: () => showFivePercentSheet(context),
                ),
              ],
            ),
          ),

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
          const SzSectionTitle('平台留存的 5% 用在哪'),
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
                for (final (i, line) in _promises.indexed) ...[
                  if (i > 0) const SizedBox(height: 9),
                  Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('—', style: TextStyle(color: sz.inkFaint)),
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
                  TextStyle(fontSize: 11.5, height: 1.6, color: sz.inkFaint)),
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
