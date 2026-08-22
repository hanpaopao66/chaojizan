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

  /// 经营质量(近 30 天完成 / 出餐超时率 / 拒单)。
  ///
  /// 从对账页搬过来的(#33 4.3)—— 那三个数不是账,放在钱那一页里,
  /// 商家对着「出餐超时率」只会以为自己在被扣分。搬过来时**必须**
  /// 带上服务端 /me/quality docstring 里那句「只统计展示,不做处罚」:
  /// 之前客户端一个字都没写。
  Map<String, dynamic>? _quality;

  /// 非空 = 上一次加载失败。转个没头的圈,商家只能杀进程重开
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      // 两个接口互不依赖,先都发出去。质量拉不到不该拦着看分析,
      // 所以它单独 catch:一块挂了另一块照常
      final analyticsF = widget.api.merchantAnalytics(days: _days);
      final qualityF = widget.api.merchantQuality().catchError(
          (_) => <String, dynamic>{});
      final d = await analyticsF;
      final q = await qualityF;
      if (mounted) {
        setState(() {
          _data = d;
          _quality = q.isEmpty ? _quality : q;
          _error = '';
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e is ApiException ? e.message : '$e');
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(_error)));
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

  /// 经营质量的一个数。从对账页 `_metric` 原样搬来(#33 4.3)。
  Widget _qualityMetric(String label, String value, String unit) {
    final sz = Theme.of(context).sz;
    return Expanded(
      child: Column(children: [
        Text.rich(
          TextSpan(children: [
            TextSpan(
                text: value,
                style: szFigure(fontSize: 17, fontWeight: FontWeight.w600)),
            if (unit.isNotEmpty)
              TextSpan(text: unit, style: const TextStyle(fontSize: 11.5)),
          ]),
          style: TextStyle(color: sz.ink),
        ),
        const SizedBox(height: 2),
        Text(label, style: TextStyle(fontSize: 10.5, color: sz.inkMuted)),
      ]),
    );
  }

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
                            ? Theme.of(context).sz.earn
                            : Theme.of(context).sz.earn.withValues(alpha: .35),
                        borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(2)),
                      ),
                    ),
                    if (h % 6 == 0)
                      Text('$h',
                          style: TextStyle(
                              fontSize: 9, color: Theme.of(context).sz.inkMuted))
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
    return SzPageScaffold(
      // 限宽用宽档:图表挤在 720 里看不清 —— 
      // 宽度上限按**内容形态**选,不是统一限死
      contentMaxWidth: kWideMaxWidth,
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
          ? (_error.isNotEmpty
              ? SzError(error: _error, onRetry: _load)
              : const Center(child: CircularProgressIndicator()))
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  if (_quality != null &&
                      (_quality!['completed_30d'] as int? ?? 0) > 0)
                    _section(
                      '经营质量 · 近 30 天',
                      Column(crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                        Row(children: [
                          _qualityMetric('完成',
                              '${_quality!['completed_30d']}', '单'),
                          _qualityMetric(
                              '出餐超时率',
                              _quality!['ready_late_rate'] == null
                                  ? '—'
                                  : ((_quality!['ready_late_rate'] as num) *
                                          100)
                                      .toStringAsFixed(1),
                              _quality!['ready_late_rate'] == null ? '' : '%'),
                          _qualityMetric(
                              '拒单', '${_quality!['rejects_30d']}', '次'),
                        ]),
                        const SizedBox(height: 8),
                        // 这句话不许删:服务端 /me/quality 明写「只统计展示,
                        // 不做处罚」,而客户端此前一个字都没写 —— 商家看到
                        // 一个百分比,默认理解就是"我被扣分了"
                        Text('只统计给你自己看,不评分、不排名、不做处罚;'
                            '平台不会因为这三个数调整你的单量或费率',
                            style: TextStyle(
                                fontSize: 11,
                                height: 1.5,
                                color: Theme.of(context).sz.inkMuted)),
                      ]),
                    ),
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
                                            ? Theme.of(context).sz.earn
                                            : Theme.of(context).sz.inkMuted))),
                            Expanded(
                              child: Column(
                                crossAxisAlignment:
                                    CrossAxisAlignment.start,
                                children: [
                                  Text('${t['name']}'),
                                  if (t['sold_out_today'] == true)
                                    Text(
                                        '今日售罄,错过约 ${t['missed_estimate']} 单(估算)',
                                        style: TextStyle(
                                            fontSize: 11,
                                            color: Theme.of(context).sz.hold)),
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
                          ?.copyWith(color: Theme.of(context).sz.inkMuted)),
                  const SizedBox(height: 24),
                ],
              ),
            ),
    );
  }
}
