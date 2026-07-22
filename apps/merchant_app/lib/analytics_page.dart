import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 经营分析:近 7/30 天只读统计。不做建议不做排名对比(不制造焦虑),
/// 口径与对账一致(完成单),赠品行不计销量金额。
class AnalyticsPage extends StatefulWidget {
  const AnalyticsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<AnalyticsPage> createState() => _AnalyticsPageState();
}

class _AnalyticsPageState extends State<AnalyticsPage> {
  int _days = 7;
  Map<String, dynamic>? _data;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await widget.api.merchantAnalytics(days: _days);
      if (mounted) setState(() => _data = d);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Widget _section(String title, Widget child) => Card(
        margin: const EdgeInsets.only(bottom: 12),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 10),
              child,
            ],
          ),
        ),
      );

  /// 24 小时下单柱状(简易 Container 柱,不引图表库)
  Widget _hourlyBars(List<dynamic> hourly) {
    final max = hourly.fold<int>(1, (m, v) => (v as int) > m ? v : m);
    return SizedBox(
      height: 96,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          for (final (h, v) in hourly.indexed)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 1),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    Container(
                      height: 72.0 * (v as int) / max,
                      decoration: BoxDecoration(
                        color: v == max && v > 0
                            ? kMoneyGreen
                            : kMoneyGreen.withValues(alpha: .35),
                        borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(2)),
                      ),
                    ),
                    if (h % 6 == 0)
                      Text('$h',
                          style: const TextStyle(
                              fontSize: 9, color: Colors.grey))
                    else
                      const SizedBox(height: 12),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final d = _data;
    return Scaffold(
      appBar: AppBar(title: const Text('经营分析'), actions: [
        SegmentedButton<int>(
          segments: const [
            ButtonSegment(value: 7, label: Text('近7天')),
            ButtonSegment(value: 30, label: Text('近30天')),
          ],
          selected: {_days},
          onSelectionChanged: (s) {
            setState(() => _days = s.first);
            _load();
          },
        ),
        const SizedBox(width: 12),
      ]),
      body: d == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  _section(
                    '总览(完成单口径,与对账一致)',
                    Wrap(spacing: 18, runSpacing: 8, children: [
                      Text('完成 ${d['orders']} 单'),
                      Text('复购率 '
                          '${((d['repurchase_rate'] as num) * 100).toStringAsFixed(0)}%'),
                      Text('配送 ${d['delivery_orders']} / '
                          '自取 ${d['pickup_orders']}'),
                    ]),
                  ),
                  _section('时段分布(24 小时下单)',
                      _hourlyBars(d['hourly'] as List)),
                  _section(
                    '菜品销量 TOP10',
                    Column(children: [
                      if ((d['top_dishes'] as List).isEmpty)
                        const Text('窗口内还没有完成单'),
                      for (final (i, t)
                          in (d['top_dishes'] as List).indexed)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          child: Row(children: [
                            SizedBox(
                                width: 22,
                                child: Text('${i + 1}',
                                    style: TextStyle(
                                        fontWeight: FontWeight.w800,
                                        color: i < 3
                                            ? kMoneyGreen
                                            : Colors.grey))),
                            Expanded(
                              child: Column(
                                crossAxisAlignment:
                                    CrossAxisAlignment.start,
                                children: [
                                  Text('${t['name']}'),
                                  if (t['sold_out_today'] == true)
                                    Text(
                                        '今日售罄,错过约 ${t['missed_estimate']} 单(估算)',
                                        style: const TextStyle(
                                            fontSize: 11,
                                            color: Colors.orange)),
                                ],
                              ),
                            ),
                            Text('${t['qty']} 份',
                                style: theme.textTheme.bodySmall),
                            const SizedBox(width: 10),
                            Text(yuan(t['amount_cents'] as int),
                                style: const TextStyle(
                                    fontWeight: FontWeight.w600)),
                          ]),
                        ),
                    ]),
                  ),
                  _section(
                    '客单价趋势',
                    Column(children: [
                      if ((d['ticket_trend'] as List).isEmpty)
                        const Text('暂无数据'),
                      for (final t in d['ticket_trend'] as List)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 2),
                          child: Row(children: [
                            Text('${t['date']}',
                                style: theme.textTheme.bodySmall),
                            const SizedBox(width: 12),
                            Text('${t['orders']} 单'),
                            const Spacer(),
                            Text('客单 ${yuan(t['avg_cents'] as int)}'),
                          ]),
                        ),
                    ]),
                  ),
                  const SizedBox(height: 8),
                  Text('只读统计,仅自己可见;不做同行对比,好好做菜就行。',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: Colors.grey)),
                  const SizedBox(height: 24),
                ],
              ),
            ),
    );
  }
}
