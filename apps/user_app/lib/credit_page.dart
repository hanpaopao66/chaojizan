import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'main.dart' show askAppealReason;

/// 我的信用分:分数、每一项加减分和对应的记录、每条扣分旁边的申诉、公式。
///
/// 数据全部来自 `/credit/me`,公式那一段是它带的 `rules` —— 和透明中心
/// `/transparency/credit` 是同一份(服务端 customer_credit.public_spec),这里一个数字都不写死。
///
/// 页面上每一个扣分都要能回答「是哪一单、哪一天、为什么」,并且旁边就是申诉:
/// 能走原来的申诉通道就走原来的(配送异常 72 小时内,改判的话钱也退),
/// 接不上的走客服工单。申诉成立,这一条不再计分,服务端当场重算。
class CreditPage extends StatefulWidget {
  const CreditPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<CreditPage> createState() => _CreditPageState();
}

class _CreditPageState extends State<CreditPage> {
  late Future<Map<String, dynamic>> _future = widget.api.myCredit();

  Future<void> _reload() async {
    final f = widget.api.myCredit();
    setState(() {
      _future = f;
    });
    await f.then((_) {}, onError: (_) {});
  }

  static String _day(Object? iso) {
    final t = DateTime.tryParse('${iso ?? ''}')?.toLocal();
    if (t == null) return '';
    return '${t.year}-${t.month.toString().padLeft(2, '0')}-'
        '${t.day.toString().padLeft(2, '0')}';
  }

  static String _tail(Object? no) {
    final s = '${no ?? ''}';
    return s.length > 6 ? s.substring(s.length - 6) : s;
  }

  Future<void> _appeal(Map<String, dynamic> row) async {
    final a = (row['appeal'] as Map?)?.cast<String, dynamic>() ?? const {};
    final via = a['via'] as String? ?? '';
    if (via.isEmpty) return;
    final reason = await askAppealReason(
      context,
      title: '申诉这一条扣分',
      hint: '例如:那天我一直在家,手机没有未接来电',
      note: via == 'appeal'
          ? '平台会重新复核这次裁决。改判的话,这一条不再计分,钱也会原路退回。'
          : '会转给平台客服,回复在「我的工单」里。${a['after'] ?? ''}',
    );
    if (reason == null) return;
    try {
      if (via == 'appeal') {
        await widget.api.submitAppeal(
            targetType: a['target_type'] as String,
            targetId: (a['target_id'] as num).toInt(),
            reason: reason);
      } else {
        await widget.api.submitCreditAppeal(
            kind: row['kind'] as String,
            recordId: (row['record_id'] as num).toInt(),
            reason: reason);
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(via == 'appeal'
              ? '申诉已提交,平台复核后通知你'
              : '已转给平台客服,回复在「我的工单」里')));
      await _reload();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: const Text('我的信用分')),
      body: RefreshIndicator(
        onRefresh: _reload,
        child: FutureBuilder<Map<String, dynamic>>(
          future: _future,
          builder: (context, snap) {
            if (snap.hasError) {
              return SzError(
                  error: snap.error,
                  onRetry: () => setState(() {
                        _future = widget.api.myCredit();
                      }));
            }
            final d = snap.data;
            if (d == null) return const SkeletonList();
            return ListView(
              padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
              children: [
                _header(context, d),
                const SizedBox(height: 16),
                _plusCard(context, d),
                const SizedBox(height: 16),
                _minusCard(context, d),
                ..._excluded(context, d),
                const SizedBox(height: 16),
                _rules(context, (d['rules'] as Map?)?.cast<String, dynamic>() ?? const {}),
              ],
            );
          },
        ),
      ),
    );
  }

  Widget _header(BuildContext context, Map<String, dynamic> d) {
    final sz = Theme.of(context).sz;
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(kCardPad),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text('${d['score']}',
                  style: szMoney(fontSize: kFigureHero, height: 1.05, color: sz.ink)),
              const SizedBox(width: 10),
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: SzChip('${d['level_label'] ?? ''}', dense: true),
              ),
            ]),
            const SizedBox(height: 6),
            Text(
                '${d['formula_line'] ?? ''} · 只看最近 ${d['window_days'] ?? ''} 天',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            const SizedBox(height: 8),
            Text('接了你单的商家、接到你单的骑手只看得到分数和等级,看不到下面这些明细。',
                style: TextStyle(fontSize: kFontNote, height: 1.45, color: sz.inkMuted)),
          ],
        ),
      ),
    );
  }

  Widget _plusCard(BuildContext context, Map<String, dynamic> d) {
    final sz = Theme.of(context).sz;
    final o = (d['orders'] as Map?)?.cast<String, dynamic>() ?? const {};
    final recent = ((o['recent'] as List?) ?? const []).cast<Map>();
    final small = TextStyle(fontSize: kFontNote, color: sz.inkMuted);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SzSectionTitle('加分'),
      const SizedBox(height: 6),
      Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(kCardPad),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(
                child: Text('完成订单 ${o['count'] ?? 0} 单',
                    style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
              ),
              Text('+${o['points'] ?? 0}',
                  style: szFigure(
                      fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.earn)),
            ]),
            const SizedBox(height: 2),
            Text('每单加分,最多 +${o['cap'] ?? ''}', style: small),
            if (recent.isNotEmpty) ...[
              const SizedBox(height: 8),
              for (final r in recent)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text('订单尾号 ${_tail(r['order_no'])} · ${_day(r['at'])} 完成',
                      style: small),
                ),
            ],
          ]),
        ),
      ),
    ]);
  }

  Widget _minusCard(BuildContext context, Map<String, dynamic> d) {
    final sz = Theme.of(context).sz;
    final rows = ((d['deductions'] as List?) ?? const [])
        .map((e) => (e as Map).cast<String, dynamic>())
        .toList();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SzSectionTitle('扣分 · 共 ${d['minus'] ?? 0}'),
      const SizedBox(height: 6),
      if (rows.isEmpty)
        Card(
          margin: EdgeInsets.zero,
          child: Padding(
            padding: const EdgeInsets.all(kCardPad),
            child: Text('最近 ${d['window_days'] ?? ''} 天没有扣分的记录',
                style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
          ),
        )
      else
        for (final r in rows) ...[
          _deductionCard(context, r),
          const SizedBox(height: 8),
        ],
    ]);
  }

  Widget _deductionCard(BuildContext context, Map<String, dynamic> r) {
    final sz = Theme.of(context).sz;
    final a = (r['appeal'] as Map?)?.cast<String, dynamic>() ?? const {};
    final via = a['via'] as String? ?? '';
    final small = TextStyle(fontSize: kFontNote, height: 1.45, color: sz.inkMuted);
    final meta = [
      if ('${r['order_no'] ?? ''}'.isNotEmpty) '订单尾号 ${_tail(r['order_no'])}',
      _day(r['at']),
      '${_day(r['expires_at'])} 起不再计分',
    ].where((s) => s.isNotEmpty).join(' · ');
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kCardPad, 12, kCardPad, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              child: Text('${r['title'] ?? ''}',
                  style: TextStyle(fontSize: kFontBody, height: 1.45, color: sz.ink)),
            ),
            const SizedBox(width: 8),
            Text('${r['points']}',
                style: szFigure(
                    fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.hold)),
          ]),
          const SizedBox(height: 4),
          Text(meta, style: small),
          if ('${r['note'] ?? ''}'.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text('平台的说明:${r['note']}', style: small),
            ),
          if ('${a['note'] ?? ''}'.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text('复核结论:${a['note']}', style: small),
            ),
          const SizedBox(height: 4),
          Row(children: [
            Expanded(
              child: Text('${a['after'] ?? ''}',
                  style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
            ),
            if (via.isNotEmpty)
              TextButton(
                onPressed: () => _appeal(r),
                child: Text(via == 'appeal' ? '申诉' : '申诉(客服工单)'),
              )
            else
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text('${a['label'] ?? ''}',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
          ]),
          // 原通道维持原判之后还能走一次工单:label 说清楚现在是什么状态
          if (via.isNotEmpty && '${a['state'] ?? ''}'.isNotEmpty)
            Text('${a['label'] ?? ''}', style: small),
        ]),
      ),
    );
  }

  List<Widget> _excluded(BuildContext context, Map<String, dynamic> d) {
    final rows = ((d['excluded'] as List?) ?? const []).cast<Map>();
    if (rows.isEmpty) return const [];
    final sz = Theme.of(context).sz;
    final small = TextStyle(fontSize: kFontNote, height: 1.45, color: sz.inkMuted);
    return [
      const SizedBox(height: 8),
      const SzSectionTitle('申诉成立,不再计分'),
      const SizedBox(height: 6),
      Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(kCardPad),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            for (final r in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text(
                    '${r['title'] ?? ''}(${_day(r['at'])}'
                    '${'${r['order_no'] ?? ''}'.isEmpty ? '' : ',订单尾号 ${_tail(r['order_no'])}'})'
                    ' —— ${r['why'] ?? ''}',
                    style: small),
              ),
          ]),
        ),
      ),
    ];
  }

  /// 「这个分怎么算」:整段是服务端 rules(= /transparency/credit)原样摊开。
  Widget _rules(BuildContext context, Map<String, dynamic> s) {
    final sz = Theme.of(context).sz;
    final body = TextStyle(fontSize: kFontBody, height: 1.5, color: sz.ink);
    final small = TextStyle(fontSize: kFontNote, height: 1.5, color: sz.inkMuted);
    List<Map<String, dynamic>> list(String k) => ((s[k] as List?) ?? const [])
        .map((e) => (e as Map).cast<String, dynamic>())
        .toList();
    final levels = list('levels');
    final levelLine = [
      for (var i = 0; i < levels.length; i++)
        '${levels[i]['label']} ${i == 0 ? '≥ ${levels[i]['min']}' : '${levels[i]['min']}–${(levels[i - 1]['min'] as num).toInt() - 1}'}',
    ].join(' · ');
    Widget bullet(String text) => Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('· $text', style: small),
        );
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const SzSectionTitle('这个分怎么算'),
      const SizedBox(height: 6),
      Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(kCardPad),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${s['formula'] ?? ''}', style: body),
            if (levelLine.isNotEmpty) bullet('等级:$levelLine。${s['level_rule'] ?? ''}'),
            if (s['base_why'] != null) bullet('${s['base_why']}'),
            const SizedBox(height: 8),
            for (final p in list('plus')) ...[
              Text('加分:${p['label']}', style: body),
              bullet('${p['counts']}'),
              for (final n in ((p['not_counted'] as List?) ?? const []))
                bullet('不算:$n'),
            ],
            const SizedBox(height: 8),
            for (final m in list('minus')) ...[
              Text('扣分:${m['label']}', style: body),
              bullet('${m['counts']}'),
              if (m['appeal'] != null) bullet('申诉:${m['appeal']}'),
            ],
            if (s['minus_cap'] != null) bullet('${s['minus_cap']}'),
            const SizedBox(height: 8),
            Text('不扣分的事', style: body),
            for (final n in list('not_counted')) bullet('${n['what']}:${n['why']}'),
            const SizedBox(height: 8),
            Text('谁能看到', style: body),
            for (final v in list('visibility')) bullet('${v['who']}:${v['what']}'),
            const SizedBox(height: 8),
            Text('不用来做的事', style: body),
            for (final n in ((s['never_used_for'] as List?) ?? const [])) bullet('$n'),
            const SizedBox(height: 8),
            if (s['appeal'] is Map) ...[
              Text('怎么申诉', style: body),
              bullet('${(s['appeal'] as Map)['summary'] ?? ''}'),
              if ((s['appeal'] as Map)['once'] != null)
                bullet('${(s['appeal'] as Map)['once']}'),
            ],
            if (s['refresh'] != null) bullet('${s['refresh']}'),
          ]),
        ),
      ),
    ]);
  }
}
