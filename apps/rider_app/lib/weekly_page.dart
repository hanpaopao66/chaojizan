import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 骑手周报 + 给平台提意见。
///
/// ## 红线:只统计,不考核
///
/// 这一页里不会出现排名、等级、"超过了 X% 的骑手"、"再跑 3 单解锁"。
/// 一旦出现,它就从"我这周跑得怎么样"变成了平台的另一根鞭子 ——
/// 而平台既定立场是不做骑手评分体系。
///
/// ## 收入构成是这一页真正的新东西
///
/// 别处的周报只给一个总数。有了配送费拆分之后,能告诉他
/// 「这周 8% 的收入来自爬楼费」「夜间那两晚多挣了 30 块」——
/// 这才谈得上让他自己判断怎么跑更划算。
class RiderWeeklyPage extends StatefulWidget {
  const RiderWeeklyPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderWeeklyPage> createState() => _RiderWeeklyPageState();
}

class _RiderWeeklyPageState extends State<RiderWeeklyPage> {
  static const _weekdays = ['一', '二', '三', '四', '五', '六', '日'];

  int _offset = 0;
  Map<String, dynamic>? _data;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final r = await widget.api.riderWeeklyReport(weekOffset: _offset);
      if (mounted) setState(() { _data = r; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final d = _data;
    final days = ((d?['days'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    final maxCents = days.fold<int>(
        1, (m, x) => ((x['earned_cents'] as num?)?.toInt() ?? 0) > m
            ? (x['earned_cents'] as num).toInt() : m);
    final parts = ((d?['fee_parts'] as Map?) ?? const {})
        .map((k, v) => MapEntry('$k', (v as num).toInt()));
    final labels = ((d?['fee_part_labels'] as Map?) ?? const {})
        .map((k, v) => MapEntry('$k', '$v'));
    final partsTotal = parts.values.fold<int>(0, (a, b) => a + b);

    return Scaffold(
      appBar: AppBar(
        title: const Text('我的周报'),
        actions: [
          IconButton(
            tooltip: '给平台提意见',
            icon: const Icon(Icons.forum_outlined),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => RiderFeedbackPage(api: widget.api))),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  Row(children: [
                    IconButton(
                      icon: const Icon(Icons.chevron_left),
                      onPressed: () { setState(() => _offset++); _load(); },
                    ),
                    Expanded(
                      child: Center(
                        child: Text(
                            _offset == 0 ? '本周'
                                : _offset == 1 ? '上周' : '$_offset 周前',
                            style: const TextStyle(
                                fontSize: 15, fontWeight: FontWeight.w600)),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.chevron_right),
                      onPressed: _offset == 0
                          ? null
                          : () { setState(() => _offset--); _load(); },
                    ),
                  ]),
                  SzCard(
                    child: Column(children: [
                      Row(children: [
                        _stat(sz, '完成', '${d?['orders'] ?? 0}', '单'),
                        _stat(sz, '收入',
                            (((d?['earned_cents'] as num?) ?? 0) / 100)
                                .toStringAsFixed(2), '元'),
                        _stat(sz, '在线',
                            (((d?['online_minutes'] as num?) ?? 0) / 60)
                                .toStringAsFixed(1), '小时'),
                      ]),
                      const SizedBox(height: 8),
                      // 时薪:总额高不等于划算,这是骑手最该拿到的一个数。
                      // 在线不足 1 小时不给 —— 分母太小算出来是个荒唐数字
                      Text(
                          d?['cents_per_hour'] == null
                              ? '在线时间太短,这周还算不出时薪'
                              : '平均时薪 ¥'
                                  '${((d!['cents_per_hour'] as num) / 100).toStringAsFixed(1)}'
                                  '/小时',
                          style: TextStyle(
                              fontSize: 12.5,
                              fontWeight: FontWeight.w600,
                              color: sz.earn)),
                    ]),
                  ),
                  const SizedBox(height: 12),
                  const SzSectionTitle('每天'),
                  const SizedBox(height: 8),
                  SzCard(
                    child: Column(children: [
                      for (final (i, day) in days.indexed)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 3),
                          child: Row(children: [
                            SizedBox(
                                width: 22,
                                child: Text('周${_weekdays[i]}',
                                    style: TextStyle(
                                        fontSize: 12, color: sz.inkMuted))),
                            const SizedBox(width: 8),
                            Expanded(
                              child: ClipRRect(
                                borderRadius: BorderRadius.circular(3),
                                child: LinearProgressIndicator(
                                  minHeight: 8,
                                  value: ((day['earned_cents'] as num?)
                                      ?.toInt() ?? 0) / maxCents,
                                  backgroundColor: sz.line,
                                  valueColor:
                                      AlwaysStoppedAnimation(sz.earn),
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            SizedBox(
                              width: 118,
                              child: Text(
                                  '${day['orders']} 单 · ¥'
                                  '${(((day['earned_cents'] as num?) ?? 0) / 100).toStringAsFixed(0)}'
                                  ' · ${(((day['minutes'] as num?) ?? 0) / 60).toStringAsFixed(1)}h',
                                  textAlign: TextAlign.right,
                                  style: TextStyle(
                                      fontSize: 11.5, color: sz.ink)),
                            ),
                          ]),
                        ),
                    ]),
                  ),
                  if (parts.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    const SzSectionTitle('这些钱是怎么来的'),
                    const SizedBox(height: 8),
                    SzCard(
                      child: Column(children: [
                        for (final e in (parts.entries.toList()
                          ..sort((a, b) => b.value.compareTo(a.value))))
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 3),
                            child: Row(children: [
                              Expanded(
                                  child: Text(labels[e.key] ?? e.key,
                                      style: const TextStyle(fontSize: 13))),
                              Text(
                                  '¥${(e.value / 100).toStringAsFixed(2)}',
                                  style: szMoney(
                                      fontSize: 13.5, color: sz.ink)),
                              const SizedBox(width: 8),
                              SizedBox(
                                width: 42,
                                child: Text(
                                    '${(e.value * 100 / partsTotal).round()}%',
                                    textAlign: TextAlign.right,
                                    style: TextStyle(
                                        fontSize: 11.5, color: sz.inkMuted)),
                              ),
                            ]),
                          ),
                      ]),
                    ),
                  ],
                  const SizedBox(height: 12),
                  Text('${_data?['note'] ?? ''}',
                      style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
                ],
              ),
            ),
    );
  }

  Widget _stat(SzColors sz, String label, String value, String unit) =>
      Expanded(
        child: Column(children: [
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            Text(value,
                style: szMoney(
                    fontSize: 21, fontWeight: FontWeight.w600, color: sz.ink)),
            const SizedBox(width: 2),
            Text(unit, style: TextStyle(fontSize: 11, color: sz.inkMuted)),
          ]),
          Text(label, style: TextStyle(fontSize: 12, color: sz.inkMuted)),
        ]),
      );
}

/// 给平台提意见。
///
/// 与申诉的区别要写在界面上:申诉是"这一单不怪我",这里是
/// "你们这个东西不好用 / 这条规则不合理"。分不清的话,骑手会把
/// 单子的问题提到这里来,然后等一个永远不会有的改判。
class RiderFeedbackPage extends StatefulWidget {
  const RiderFeedbackPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderFeedbackPage> createState() => _RiderFeedbackPageState();
}

class _RiderFeedbackPageState extends State<RiderFeedbackPage> {
  static const _kinds = <(String, String)>[
    ('bug', '有东西坏了'),
    ('rule', '规则不合理'),
    ('feature', '希望能加'),
    ('other', '其他'),
  ];

  final _text = TextEditingController();
  String _kind = 'bug';
  List<Map<String, dynamic>> _items = const [];
  bool _loading = true;
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await widget.api.myRiderFeedback();
      if (!mounted) return;
      setState(() {
        _items = ((r['items'] as List?) ?? const [])
            .cast<Map<String, dynamic>>();
        _loading = false;
      });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Scaffold(
      appBar: AppBar(title: const Text('给平台提意见')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(12),
              children: [
                SzCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('这里是给平台提意见的地方',
                          style: TextStyle(fontWeight: FontWeight.w600)),
                      const SizedBox(height: 4),
                      Text(
                          '某一单判得不对走「申诉」(在配送页那一单上)。'
                          '这里说的是平台本身:哪个页面不好用、'
                          '哪条规则不合理、希望加点什么。\n'
                          '提了一定会有人看,有回复会推送给你,也会进「消息」页。',
                          style: TextStyle(
                              fontSize: 12, color: sz.inkMuted)),
                      const SizedBox(height: 10),
                      Wrap(spacing: 6, children: [
                        for (final (v, label) in _kinds)
                          ChoiceChip(
                            label: Text(label,
                                style: const TextStyle(fontSize: 12)),
                            visualDensity: VisualDensity.compact,
                            selected: _kind == v,
                            onSelected: (_) => setState(() => _kind = v),
                          ),
                      ]),
                      const SizedBox(height: 8),
                      TextField(
                        controller: _text,
                        maxLines: 4,
                        maxLength: 500,
                        decoration: const InputDecoration(
                          hintText: '如:抢单页刷新一次要五六秒,高峰期根本抢不到',
                          border: OutlineInputBorder(),
                        ),
                      ),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: _sending ? null : _submit,
                          child: Text(_sending ? '提交中…' : '提交'),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                if (_items.isNotEmpty) const SzSectionTitle('我提过的'),
                const SizedBox(height: 8),
                for (final f in _items)
                  SzCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Expanded(
                            child: Text('${f['content']}',
                                style: const TextStyle(fontSize: 13.5)),
                          ),
                          Text(
                              f['status'] == 'replied' ? '已回复' : '待处理',
                              style: TextStyle(
                                  fontSize: 11.5,
                                  color: f['status'] == 'replied'
                                      ? sz.earn : sz.inkMuted)),
                        ]),
                        if ('${f['reply']}'.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Container(
                            padding: const EdgeInsets.all(8),
                            decoration: BoxDecoration(
                              color: sz.earn.withValues(alpha: .08),
                              borderRadius: BorderRadius.circular(kRadiusSm),
                            ),
                            child: Text('平台回复:${f['reply']}',
                                style: const TextStyle(fontSize: 12.5)),
                          ),
                        ],
                      ],
                    ),
                  ),
              ],
            ),
    );
  }

  Future<void> _submit() async {
    final text = _text.text.trim();
    if (text.length < 4) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('说具体一点,不然没法处理')));
      return;
    }
    setState(() => _sending = true);
    try {
      final r = await widget.api
          .submitRiderFeedback(kind: _kind, content: text);
      if (!mounted) return;
      _text.clear();
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('${r['note']}')));
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }
}
