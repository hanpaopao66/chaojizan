import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 「5% 去哪了」官方说明弹层。
///
/// 挂在「钱去哪了」透明卡的"平台留存"行与账目透明页的 5% 卡上——
/// 让质疑者在产品里自己找到答案,而不是去评论区吵。
Future<void> showFivePercentSheet(BuildContext context) {
  return showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    builder: (context) {
      final theme = Theme.of(context);
      Widget item(IconData icon, String title, String desc) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icon, size: 18, color: kBrandOrange),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title,
                          style: const TextStyle(
                              fontWeight: FontWeight.w600, fontSize: 13.5)),
                      Text(desc,
                          style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.outline, height: 1.5)),
                    ],
                  ),
                ),
              ],
            ),
          );
      Widget promise(String title, String desc) => Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.check_circle_outline,
                    size: 18, color: kMoneyGreen),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title,
                          style: const TextStyle(
                              fontWeight: FontWeight.w600, fontSize: 13.5)),
                      Text(desc,
                          style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.outline, height: 1.5)),
                    ],
                  ),
                ),
              ],
            ),
          );
      return DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.78,
        maxChildSize: 0.95,
        builder: (context, controller) => ListView(
          controller: controller,
          padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
          children: [
            Text('我们为什么收 5%,以及这 5% 去了哪',
                style: theme.textTheme.titleMedium
                    ?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Text(
              '超级赞的初心不是赚钱,是再分配——不让利润都留在平台手里。'
              '但平台要活着,才谈得上再分配。所以我们收 5%,并把它的去向摊开:'
              '一单 30 元的外卖,平台留存 1.5 元,它要覆盖——',
              style: theme.textTheme.bodySmall?.copyWith(height: 1.6),
            ),
            const SizedBox(height: 10),
            item(Icons.payment_outlined, '支付通道费',
                '每笔交易,支付机构要收千分之几的手续费,这是刚性成本'),
            item(Icons.dns_outlined, '基础设施',
                '服务器、带宽、数据库、地图定位、短信验证码、消息推送——你每下一单,这些都在计费'),
            item(Icons.support_agent_outlined, '人工',
                '商家证照审核、骑手实名审核、客服工单、提现打款复核,都要人来做'),
            item(Icons.build_outlined, '开发维护',
                '修 bug、加功能、保证每天凌晨 4 点的自动查账正常跑'),
            const Divider(height: 28),
            Text('三条承诺',
                style: theme.textTheme.titleSmall
                    ?.copyWith(fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            promise('不靠别的赚钱',
                '不卖用户数据、不做竞价排名、不收商家推广费、不抽配送费。'
                '5% 是唯一收入——正因为如此,我们不需要坑任何一方'),
            promise('平台自己的账也公开',
                '我们要求每一单分账透明,也会定期公示平台整体收支:'
                '5% 收了多少、花在了哪、剩没剩,大家盯着'),
            promise('5% 是上限,不是目标',
                '如果规模上来、成本摊薄,盈余不分红——优先用于骑手保障'
                '(意外险/恶劣天气补贴)、商家扶持和降低费率。'
                '哪天 3% 能活,我们就降到 3%'),
            const SizedBox(height: 16),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: kBrandOrange.withValues(alpha: .08),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                '行业平台的抽成,进的是财报;超级赞的 5%,进的是公开账本。',
                style: theme.textTheme.bodySmall
                    ?.copyWith(fontWeight: FontWeight.w600, height: 1.5),
              ),
            ),
          ],
        ),
      );
    },
  );
}
