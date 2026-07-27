import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'stay_aftersales_page.dart';
import 'stay_reviews_page.dart';

/// 酒店 tab:酒店信息与通用服务入口。
/// 餐饮专属设置(起送价/打包费/出餐时长/满减满赠)在这里天然不存在——
/// 业态分叉后各看各的,不靠隐藏开关。
class HotelTab extends StatelessWidget {
  const HotelTab({super.key, required this.api, required this.shop});

  final ApiClient api;
  final Merchant shop;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Expanded(
                      child: Text(shop.name,
                          style: Theme.of(context).textTheme.titleLarge)),
                  Chip(label: Text('佣金 ${(shop.commissionRate * 100).toStringAsFixed(0)}%·离店才收')),
                ]),
                const SizedBox(height: 4),
                Text(shop.address,
                    style: Theme.of(context).textTheme.bodyMedium),
                if (shop.description.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text(shop.description,
                      style: Theme.of(context).textTheme.bodySmall),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),
        const Card(
          child: ListTile(
            leading: Icon(Icons.desktop_windows_outlined),
            title: Text('电脑上管店'),
            subtitle: SelectableText('网页版商家后台:chaojizan.cc/merchant\n'
                '前台电脑管房态日历、办理入住离店更顺手,与 App 同一账号'),
            isThreeLine: true,
          ),
        ),
        const SizedBox(height: 8),
        Card(
          child: ListTile(
            leading: const Icon(Icons.gavel_outlined),
            title: const Text('售后处理'),
            subtitle: const Text('到店无房 2 小时内必须响应,超时按成立处理'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => StayAftersalesPage(api: api))),
          ),
        ),
        const SizedBox(height: 8),
        Card(
          child: ListTile(
            leading: const Icon(Icons.rate_review_outlined),
            title: const Text('住客点评'),
            subtitle: const Text('查看与回复;评分取近 180 天滚动均分'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => StayReviewsPage(api: api))),
          ),
        ),
        const SizedBox(height: 8),
        Card(
          child: ListTile(
            leading: const Icon(Icons.support_agent_outlined),
            title: const Text('联系平台客服'),
            subtitle: const Text('对账疑问、审核进度、任何问题都可以问'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => SupportPage(api: api))),
          ),
        ),
        const SizedBox(height: 8),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('平台承诺', style: Theme.of(context).textTheme.titleSmall),
                const SizedBox(height: 8),
                const Text('· 佣金 5%,离店(核销)后才产生\n'
                    '· 订单取消/客人未入住,平台分文不取\n'
                    '· 无排他协议、无竞价排名、无年费\n'
                    '· 每一笔分账都可在对账页逐单核对'),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
