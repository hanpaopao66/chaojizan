import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 骑手申诉。
///
/// ## 为什么这一页必须存在
///
/// 商家早就能对差评申诉,骑手不能 —— 被判超时、收到差评时**完全没有说话
/// 的地方**。而超时的成因里,商家出餐慢、地址填错、顾客不接电话占了相当
/// 一部分,这些都不是骑手能控制的。
///
/// ## 界面上必须说清楚的一句
///
/// **申诉成立不加分也不补钱** —— 平台没有骑手评分体系(不做服务分、
/// 不做违规积分),所以没有分可加。申诉的价值是这条记录上写着不怪你。
/// 不说清楚的话骑手会以为申诉能拿到补偿,结果是更大的失望。
///
/// ## 证据不用骑手自己找
///
/// 等餐时长、实际距离、天气豁免这些平台都有,提交时自动附上。
/// 让一个在马路上跑车的人去截图收集材料,这个通道就等于不存在。
class RiderAppealPage extends StatefulWidget {
  const RiderAppealPage({super.key, required this.api, this.order});

  final ApiClient api;

  /// 从订单卡进来时带上这一单;从「我的」进来时为 null(只看列表)
  final Order? order;

  @override
  State<RiderAppealPage> createState() => _RiderAppealPageState();
}

class _RiderAppealPageState extends State<RiderAppealPage> {
  List<Map<String, dynamic>> _items = const [];
  String _note = '';
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.myRiderAppeals();
      if (!mounted) return;
      setState(() {
        _items = ((r['items'] as List?) ?? const [])
            .cast<Map<String, dynamic>>();
        _note = '${r['note'] ?? ''}';
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('我的申诉')),
      floatingActionButton: widget.order == null
          ? null
          : FloatingActionButton.extended(
              onPressed: _submit,
              icon: const Icon(Icons.record_voice_over_outlined),
              label: const Text('为这一单申诉'),
            ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 88),
                children: [
                  Card(
                    color: scheme.secondaryContainer,
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('申诉成立 = 这一单标注为「非你的责任」',
                              style: TextStyle(
                                  fontWeight: FontWeight.w600,
                                  color: scheme.onSecondaryContainer)),
                          const SizedBox(height: 4),
                          Text(
                            '平台没有骑手服务分、没有违规积分,所以**没有分可加、'
                            '也不会补钱**。申诉的意义是记录上写清楚不怪你,'
                            '以及平台据此去看商家出餐那一环。\n'
                            '证据不用你自己找 —— 等餐时长、实际距离、'
                            '天气豁免提交时会自动附上。',
                            style: TextStyle(
                                fontSize: 12,
                                color: scheme.onSecondaryContainer),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  if (_items.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 48),
                      child: Center(child: Text('还没有申诉记录')),
                    ),
                  for (final a in _items) _appealTile(a),
                  if (_note.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.all(8),
                      child: Text(_note,
                          style: TextStyle(
                              fontSize: 12,
                              color: scheme.onSurfaceVariant)),
                    ),
                ],
              ),
            ),
    );
  }

  Widget _appealTile(Map<String, dynamic> a) {
    final scheme = Theme.of(context).colorScheme;
    final status = '${a['status']}';
    final (label, color) = switch (status) {
      'accepted' => ('已认定非你的责任', Colors.green),
      'rejected' => ('未采纳', scheme.error),
      _ => ('核实中', scheme.onSurfaceVariant),
    };
    final ev = (a['evidence'] as Map?)?.cast<String, dynamic>() ?? const {};
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${a['order_no']}',
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            Text(label, style: TextStyle(fontSize: 12, color: color)),
          ]),
          const SizedBox(height: 4),
          Text('${a['reason']}', style: const TextStyle(fontSize: 13)),
          if (ev.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              [
                if (ev['wait_minutes'] != null) '等餐 ${ev['wait_minutes']} 分钟',
                if (ev['late_minutes'] != null)
                  '超时 ${ev['late_minutes']} 分钟',
                if (ev['distance_m'] != null) '配送 ${ev['distance_m']} 米',
                if (ev['weather_exempt'] == true) '恶劣天气豁免',
              ].join(' · '),
              style: TextStyle(
                  fontSize: 12, color: scheme.onSurfaceVariant),
            ),
          ],
          if ('${a['verdict_note']}'.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text('平台回复:${a['verdict_note']}',
                style: TextStyle(fontSize: 12, color: color)),
          ],
        ]),
      ),
    );
  }

  Future<void> _submit() async {
    final order = widget.order!;
    var kind = 'late';
    final reason = TextEditingController();
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheet) => StatefulBuilder(
        builder: (sheet, setSheet) => Padding(
          padding: EdgeInsets.only(
              left: 16, right: 16, top: 16,
              bottom: MediaQuery.of(sheet).viewInsets.bottom + 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('为 ${order.orderNo} 申诉',
                  style: Theme.of(sheet).textTheme.titleMedium),
              Text('说清楚当时的情况就行,证据平台自己附',
                  style: Theme.of(sheet).textTheme.bodySmall),
              const SizedBox(height: 8),
              RadioGroup<String>(
                groupValue: kind,
                onChanged: (v) => setSheet(() => kind = v!),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: const [
                    RadioListTile<String>(
                        dense: true, value: 'late',
                        title: Text('超时不是我的责任')),
                    RadioListTile<String>(
                        dense: true, value: 'review',
                        title: Text('差评不是我的责任')),
                    RadioListTile<String>(
                        dense: true, value: 'other', title: Text('其他')),
                  ],
                ),
              ),
              TextField(
                controller: reason,
                maxLines: 3,
                maxLength: 300,
                decoration: const InputDecoration(
                  hintText: '如:到店后等餐二十分钟,商家一直没出餐',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () => Navigator.pop(sheet, true),
                  child: const Text('提交'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (ok != true) return;
    try {
      final r = await widget.api.submitRiderAppeal(
          orderNo: order.orderNo, kind: kind, reason: reason.text.trim());
      if (!mounted) return;
      // 服务端返回体里那句口径原样展示 —— 不说清楚骑手会以为能拿到钱
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('${r['note']}'), duration: const Duration(seconds: 8)));
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }
}
