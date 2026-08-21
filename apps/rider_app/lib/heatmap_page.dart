import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 跑单热力图:**过去 N 周,这个时段、这个网格,实际完成了多少单。**
///
/// ## 只回答历史,不做预测
///
/// 这一页不预测、不外推、**不推荐去哪跑**。
///
/// - 预测在我们现在的单量上只会产生噪音,而噪音在这里的代价很实:
///   骑手照着一片"高热区"跑过去,发现没单;
/// - "推荐去哪跑"是软性派单,会变成"平台让我去我才有单"的另一种绑定。
///
/// ## 样本不足的格子不画热区
///
/// 这是这个功能唯一会真正伤人的失败方式。所以低于门槛的格子显示成
/// **「数据不够」**而不是"冷区" —— "这里没单"和"我们不知道这里有没有单"
/// 是两件事,混在一起就是在编。
class RiderHeatmapPage extends StatefulWidget {
  const RiderHeatmapPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderHeatmapPage> createState() => _RiderHeatmapPageState();
}

class _RiderHeatmapPageState extends State<RiderHeatmapPage> {
  static const _weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

  int? _weekday;
  int? _hour;
  Map<String, dynamic>? _data;
  bool _loading = true;

  /// 拉失败的原因;空串 = 上一次是成功的。
  ///
  /// 这一页整个立意就是"『这里没单』和『我们不知道这里有没有单』是两件事"——
  /// 那么"拉不到数据"当然更不能画成一片没有热区的图。
  String _error = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final r = await widget.api
          .riderHeatmap(weekday: _weekday, hour: _hour);
      if (!mounted) return;
      setState(() {
        _data = r;
        _weekday = (r['weekday'] as num?)?.toInt();
        _hour = (r['hour'] as num?)?.toInt();
        _loading = false;
        _error = '';
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = e is ApiException ? e.message : '$e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final cells = ((_data?['cells'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    final enough = cells.where((c) => c['enough'] == true).toList();
    final maxOrders = enough.fold<int>(
        1, (m, c) => (c['orders'] as num).toInt() > m
            ? (c['orders'] as num).toInt() : m);

    return SzPageScaffold(
      // 限宽用宽档:热力图要看得见范围挤在 720 里看不清 —— 
      // 宽度上限按**内容形态**选,不是统一限死
      contentMaxWidth: kWideMaxWidth,
      appBar: AppBar(title: const Text('哪儿有单')),
      body: !_loading && _data != null
          ? RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  // 有旧数据但这次没刷新成功:说一句,别让他以为是最新的
                  if (_error.isNotEmpty) ...[
                    SzRetryBanner(
                        text: '这次没刷新成功($_error),下面是上一次的数据',
                        onRetry: _load),
                    const SizedBox(height: 8),
                  ],
                  SzCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Expanded(
                            child: DropdownButton<int>(
                              isExpanded: true,
                              value: _weekday,
                              items: [
                                for (final (i, w) in _weekdays.indexed)
                                  DropdownMenuItem(value: i, child: Text(w)),
                              ],
                              onChanged: (v) {
                                setState(() => _weekday = v);
                                _load();
                              },
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: DropdownButton<int>(
                              isExpanded: true,
                              value: _hour,
                              items: [
                                for (var h = 0; h < 24; h++)
                                  DropdownMenuItem(
                                      value: h, child: Text('$h 点')),
                              ],
                              onChanged: (v) {
                                setState(() => _hour = v);
                                _load();
                              },
                            ),
                          ),
                        ]),
                        const SizedBox(height: 6),
                        Text('${_data?['note'] ?? ''}',
                            style: TextStyle(
                                fontSize: 11.5, color: sz.inkMuted)),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  if (enough.isEmpty)
                    SzCard(
                      child: Column(children: [
                        Icon(Icons.help_outline, size: 28, color: sz.inkFaint),
                        const SizedBox(height: 8),
                        const Text('这个时段的数据还不够',
                            style: TextStyle(fontWeight: FontWeight.w600)),
                        const SizedBox(height: 4),
                        Text(
                            '我们不会拿几单数据编一张热力图给你 —— '
                            '照着编出来的图跑过去发现没单,比不给更糟。'
                            '先按自己的经验跑,单量攒起来这里就有东西了。',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                                fontSize: 12, color: sz.inkMuted)),
                      ]),
                    ),
                  for (final c in enough)
                    Card(
                      margin: const EdgeInsets.only(bottom: 8),
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
                        child: Row(children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                    '${(c['lat'] as num).toStringAsFixed(4)}, '
                                    '${(c['lng'] as num).toStringAsFixed(4)}',
                                    style: const TextStyle(fontSize: 13)),
                                const SizedBox(height: 4),
                                ClipRRect(
                                  borderRadius: BorderRadius.circular(3),
                                  child: LinearProgressIndicator(
                                    minHeight: 7,
                                    value: (c['orders'] as num) / maxOrders,
                                    backgroundColor: sz.line,
                                    valueColor:
                                        AlwaysStoppedAnimation(sz.earn),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(width: 10),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              Text('${c['orders']} 单',
                                  style: szMoney(
                                      fontSize: 16,
                                      fontWeight: FontWeight.w600,
                                      color: sz.ink)),
                              Text('约 ${c['per_week']} 单/周',
                                  style: TextStyle(
                                      fontSize: 11, color: sz.inkMuted)),
                            ],
                          ),
                        ]),
                      ),
                    ),
                  // 被样本门槛挡掉的格子也要交代,而不是当它们不存在
                  if (((_data?['insufficient'] as num?) ?? 0) > 0)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                          '另有 ${_data!['insufficient']} 个点位这个时段只有零星几单,'
                          '样本太少,没列出来 —— 不是那里没单,是我们还不知道。',
                          style: TextStyle(
                              fontSize: 11.5, color: sz.inkMuted)),
                    ),
                ],
              ),
            )
          // 一次都没拉到:转圈和「没拉到」是两件事。
          // 这一页整个立意就是"『这里没单』和『我们不知道有没有单』不一样",
          // 那就更不能拿一张空图冒充"这一带没单"
          : _loading
              ? const Center(child: CircularProgressIndicator())
              : SzError(error: '没能拿到跑单数据:$_error', onRetry: _load),
    );
  }
}
