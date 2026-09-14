import 'package:flutter/material.dart';

import 'api_client.dart';
import 'brand.dart';
import 'models.dart';
import 'sz_widgets.dart';

/// 顾客信用分在商家端、骑手端的样子:订单上一枚「顾客信用 92 · 良好」小签。
///
/// ## 只在接单之后出现
///
/// 服务端只给「商家接过、没取消」「这一单的骑手」的单带 `customer_credit`
/// (server/app/services/customer_credit.py 的 counterpart_may_see)。
/// 这里按订单状态**再兜一道**:哪天服务端在待接单上漏带了,商家端的新单卡、
/// 骑手端的抢单卡上也不会冒出来 —— 接单之前看得到,它就会被拿来挑顾客。
///
/// ## 只有分数和等级
///
/// 点开是一段说明,从 `/transparency/credit` 读(和透明中心、顾客自己看到的是同一份),
/// 没有明细。平台的派单、排序、价格里都没有它 —— 这是一个给人看的数,不是开关。
class CustomerCreditChip extends StatelessWidget {
  const CustomerCreditChip({
    super.key,
    required this.order,
    this.api,
    this.viewer = '商家',
  });

  final Order order;

  /// 点开说明时拉公式用。为空时小签不可点(测试、没有网络的场合)
  final ApiClient? api;

  /// 公式说明里挑哪一条「谁能看到」:商家 / 骑手
  final String viewer;

  @override
  Widget build(BuildContext context) {
    final credit = order.customerCredit;
    if (credit == null || !customerCreditVisible(order)) {
      return const SizedBox.shrink();
    }
    final sz = Theme.of(context).sz;
    final label = '顾客信用 ${credit.score} · ${credit.levelLabel}';
    final client = api;
    return Semantics(
      label: '$label,点开看这个分怎么来的',
      button: client != null,
      excludeSemantics: true,
      child: SzChip(
        label,
        dense: true,
        // 字色一律中性,不按等级染红:它是一条给人参考的信息,不是警报
        textColor: sz.inkMuted,
        onTap: client == null
            ? null
            : () => showCustomerCreditExplain(context, client, viewer: viewer),
      ),
    );
  }
}

/// 交易对方能看到顾客信用分的订单状态:接单之后、没取消。
///
/// 和服务端 customer_credit.COUNTERPART_STATUS_VALUES 同一组。
/// 待接单(新单提醒、新单详情)、待支付、已取消一律不显示
const Set<OrderStatus> kCustomerCreditStatuses = {
  OrderStatus.accepted,
  OrderStatus.ready,
  OrderStatus.pickedUp,
  OrderStatus.delivered,
  OrderStatus.completed,
};

/// 这一单上该不该显示顾客信用分。
bool customerCreditVisible(Order order) =>
    order.customerCredit != null &&
    kCustomerCreditStatuses.contains(order.status);

/// 点开小签:这个分怎么来的、我能拿它做什么、不能做什么。内容全从服务端读。
Future<void> showCustomerCreditExplain(BuildContext context, ApiClient api,
    {String viewer = '商家'}) {
  final spec = api.creditSpec();
  return showDialog<void>(
    context: context,
    builder: (context) => SzDialog(
      title: const Text('顾客信用分'),
      scrollable: true,
      content: FutureBuilder<Map<String, dynamic>>(
        future: spec,
        builder: (context, snap) {
          final sz = Theme.of(context).sz;
          final body = TextStyle(fontSize: kFontBody, height: 1.5, color: sz.ink);
          final note =
              TextStyle(fontSize: kFontNote, height: 1.45, color: sz.inkMuted);
          if (snap.hasError) {
            return Text('说明没加载出来。完整的公式在超级赞透明中心「信用分怎么算」。',
                style: body);
          }
          final s = snap.data;
          if (s == null) {
            return const SizedBox(
                height: 48, child: Center(child: CircularProgressIndicator()));
          }
          final seen = ((s['visibility'] as List?) ?? const [])
              .cast<Map>()
              .firstWhere((v) => v['who'] == viewer, orElse: () => const {});
          final never = ((s['never_used_for'] as List?) ?? const []).cast<String>();
          return Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (seen['what'] != null) Text('${seen['what']}', style: body),
              const SizedBox(height: 8),
              Text('${s['formula'] ?? ''}', style: note),
              if (s['level_rule'] != null) ...[
                const SizedBox(height: 4),
                Text('${s['level_rule']}', style: note),
              ],
              if (never.isNotEmpty) ...[
                const SizedBox(height: 10),
                for (final line in never)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('· $line', style: note),
                  ),
              ],
              const SizedBox(height: 6),
              Text('完整的公式在超级赞透明中心「信用分怎么算」。', style: note),
            ],
          );
        },
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('知道了')),
      ],
    ),
  );
}
