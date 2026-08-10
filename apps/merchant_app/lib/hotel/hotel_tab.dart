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
    final sz = Theme.of(context).sz;
    return ListView(
      padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
      children: [
        SzCard(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                    child: Text(shop.name,
                        style: TextStyle(
                            fontSize: 19,
                            fontWeight: FontWeight.w600,
                            color: sz.ink))),
                const SizedBox(width: 8),
                // 佣金是"被抽走的",走 hold 不走强调色
                SzChip(
                    '佣金 ${(shop.commissionRate * 100).toStringAsFixed(0)}% · 离店才收',
                    color: sz.hold,
                    dense: true),
              ]),
              const SizedBox(height: 6),
              Text(shop.address,
                  style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
              if (shop.description.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(shop.description,
                    style: TextStyle(
                        fontSize: 11.5, height: 1.55, color: sz.inkMuted)),
              ],
            ],
          ),
        ),

        const SizedBox(height: 18),
        const SzSectionTitle('日常经营'),
        const SizedBox(height: 9),
        SzCard(
          padding: EdgeInsets.zero,
          child: Column(children: [
            _navRow(context, '售后处理', '到店无房 2 小时内必须响应,超时按成立处理',
                () => StayAftersalesPage(api: api)),
            _sep(context),
            _navRow(context, '住客点评', '查看与回复;评分取近 180 天滚动均分',
                () => StayReviewsPage(api: api)),
            _sep(context),
            _navRow(context, '联系平台客服', '对账疑问、审核进度、任何问题都可以问',
                () => SupportPage(api: api)),
          ]),
        ),

        const SizedBox(height: 18),
        const SzSectionTitle('电脑上管店'),
        const SizedBox(height: 9),
        SzCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SelectableText('chaojizan.cc/merchant',
                  style: szFigure(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
              const SizedBox(height: 4),
              Text('前台电脑管房态日历、办理入住离店更顺手,与 App 同一账号',
                  style: TextStyle(
                      fontSize: 11.5, height: 1.55, color: sz.inkMuted)),
            ],
          ),
        ),

        const SizedBox(height: 18),
        const PledgeCard(
          title: '住宿口径:佣金 5%,离店才收',
          body: '订单取消、客人未入住,平台分文不取;'
              '无排他协议、无竞价排名、无年费;'
              '每一笔分账都可在对账页逐单核对。',
        ),
      ],
    );
  }

  Widget _sep(BuildContext context) =>
      Divider(height: 1, color: Theme.of(context).sz.line);

  /// 入口行:标题 + 一句说明 + 右箭头。整行热区,高度不小于 48。
  Widget _navRow(BuildContext context, String title, String desc,
      Widget Function() page) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: () => Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => page())),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 13),
        child: Row(children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: TextStyle(fontSize: 14, color: sz.ink)),
                const SizedBox(height: 2),
                Text(desc,
                    style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
              ],
            ),
          ),
          Icon(Icons.chevron_right, size: 16, color: sz.inkFaint),
        ]),
      ),
    );
  }
}
