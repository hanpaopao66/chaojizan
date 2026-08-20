import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 顾客对我的评价(#148)。
///
/// 骑手此前**完全看不到自己的评价** —— 商家早就有评价页,骑手没有,是个疏漏。
/// 顾客怎么说,直接影响骑手的心情与改进方向。
///
/// ## 这一页最容易滑向评分体系,所以边界要写死
///
/// **不做排名、不做与其他骑手的对比、不做等级。**
///
/// 判断标准很简单:**这个数字会不会影响他能看到的单?**
/// 会,就是绳索;不会,才是反馈。
///
/// 一旦骑手看到「你排第 87 名」,他就会开始为名次跑单,而名次是平台
/// 单方面控制的 —— 那正是竞品的「服务分 / 安全分 / 派单分 / 段位」在做的事,
/// 也正是 #144 要防的「算法困住人」。
///
/// 所以本页顶部**第一眼就要告诉骑手:评价不影响派单**。
/// 不写的话他会默认它影响,然后开始为分数跑单。
class RiderReviewsPage extends StatefulWidget {
  const RiderReviewsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderReviewsPage> createState() => _RiderReviewsPageState();
}

class _RiderReviewsPageState extends State<RiderReviewsPage> {
  Map<String, dynamic>? _data;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await widget.api.riderReviews();
      if (mounted) setState(() => _data = d);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('顾客评价')),
      body: _error != null
          ? Center(
              child: Padding(
                padding: const EdgeInsets.all(kPagePad),
                child: Text('拿不到评价:$_error',
                    style: TextStyle(color: sz.inkMuted)),
              ),
            )
          : _data == null
              ? const Center(child: CircularProgressIndicator())
              : _content(sz),
    );
  }

  Widget _content(SzColors sz) {
    final items = (_data!['items'] as List).cast<Map<String, dynamic>>();
    final avg = _data!['average'];
    final count = _data!['count'] as int;

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
        children: [
          // **第一眼就说清楚**:不写的话骑手会默认评价影响派单,
          // 然后开始为分数跑单 —— 那正是我们要避免的
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: sz.earn.withValues(alpha: .10),
              borderRadius: BorderRadius.circular(kRadiusSm),
            ),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Icon(Icons.verified_outlined, size: 18, color: sz.earn),
              const SizedBox(width: 8),
              Expanded(
                child: Text('${_data!["note"]}',
                    style: TextStyle(
                        fontSize: 12.5, height: 1.5, color: sz.ink)),
              ),
            ]),
          ),
          const SizedBox(height: 16),

          if (count == 0)
            SzCard(
              child: Column(children: [
                Text('还没有顾客评价',
                    style: TextStyle(fontSize: 14, color: sz.ink)),
                const SizedBox(height: 4),
                Text('顾客评价是自愿的,没有评价不代表送得不好',
                    style: TextStyle(fontSize: 12, color: sz.inkMuted)),
              ]),
            )
          else ...[
            SzCard(
              child: Row(children: [
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${avg ?? "—"}',
                      style: szMoney(
                          fontSize: 30,
                          fontWeight: FontWeight.w600,
                          color: sz.ink)),
                  Text('我的平均分', style: TextStyle(fontSize: 12, color: sz.inkMuted)),
                ]),
                const Spacer(),
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text('$count',
                      style: szFigure(fontSize: 20, color: sz.ink)),
                  Text('条评价', style: TextStyle(fontSize: 12, color: sz.inkMuted)),
                ]),
              ]),
            ),
            const SizedBox(height: 6),
            // 明确不给对比:给了就等于建了排名
            Text('只显示你自己的评价,不做排名、不与其他骑手比较',
                style: TextStyle(fontSize: 11, color: sz.inkMuted)),
            const SizedBox(height: 16),
            const SzSectionTitle('每一条'),
            const SizedBox(height: 8),
            for (final r in items) ...[
              SzCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      for (var i = 0; i < 5; i++)
                        Icon(
                            i < (r['rating'] as int)
                                ? Icons.star_rounded
                                : Icons.star_outline_rounded,
                            size: 17,
                            color: i < (r['rating'] as int)
                                ? sz.hold
                                : sz.inkMuted),
                      const Spacer(),
                      Text('${r["created_at"]}'.substring(0, 10),
                          style: szFigure(fontSize: 11, color: sz.inkMuted)),
                    ]),
                    if ((r['comment'] as String).isNotEmpty) ...[
                      const SizedBox(height: 6),
                      // 评价正文是顾客写给「这一单」的,可能同时提到商家和骑手。
                      // 原样展示不做摘录 —— 断章取义比不给更糟
                      Text(r['comment'] as String,
                          style: TextStyle(
                              fontSize: 13, height: 1.5, color: sz.ink)),
                    ],
                    const SizedBox(height: 6),
                    Row(children: [
                      Text('订单 ${r["order_no"]}'.length > 18
                          ? '订单 ${(r["order_no"] as String).substring((r["order_no"] as String).length - 6)}'
                          : '订单 ${r["order_no"]}',
                          style: TextStyle(fontSize: 11, color: sz.inkMuted)),
                      const Spacer(),
                      if ((r['rating'] as int) <= 2)
                        Text('有异议可申诉',
                            style: TextStyle(fontSize: 11.5, color: sz.link)),
                    ]),
                  ],
                ),
              ),
              const SizedBox(height: 8),
            ],
            const SizedBox(height: 6),
            Text('${_data!["appeal_hint"]}',
                style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
          ],
        ],
      ),
    );
  }
}
