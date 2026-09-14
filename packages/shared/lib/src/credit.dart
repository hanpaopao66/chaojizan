import 'package:flutter/material.dart';

import 'api_client.dart';
import 'brand.dart';
import 'models.dart';
import 'responsive.dart';
import 'sz_widgets.dart';
import 'ui_bits.dart';

/// 信用分在三端的样子(server/app/services/credit.py):顾客、商家、骑手同一套机制。
///
/// - 订单上的小签:「顾客信用 92 · 良好」「商家信用 …」「骑手信用 …」;
/// - 「我的信用分」页:三端共用这一页([CreditPage]),内容全从 `/credit/me` 读。
///
/// ## 小签只在接单之后出现
///
/// 服务端只给「接单之后、这一单的交易对方」带分数(credit.py 的 visible_parties)。
/// 这里按订单状态**再兜一道**:哪天服务端在待接单上漏带了,商家端的新单卡、
/// 骑手端的抢单卡上也不会冒出来 —— 接单之前看得到,它就会被拿来挑人、挑店。
///
/// ## 只有分数和等级
///
/// 点开是一段说明,从 `/transparency/credit?role=` 读(和透明中心、本人看到的是同一份),
/// 没有明细。平台的派单、排序、价格里都没有它 —— 这是一个给人看的数,不是开关。

/// 三方各叫什么(小签上那两个字)
const Map<String, String> kCreditPartyLabels = {
  'customer': '顾客',
  'merchant': '商家',
  'rider': '骑手',
};

/// 交易对方能看到信用分的订单状态:接单之后、没取消。
///
/// 和服务端 credit.COUNTERPART_STATUS_VALUES 同一组。
/// 待接单(新单提醒、新单详情)、待支付、已取消一律不显示
const Set<OrderStatus> kCreditStatuses = {
  OrderStatus.accepted,
  OrderStatus.ready,
  OrderStatus.pickedUp,
  OrderStatus.delivered,
  OrderStatus.completed,
};

/// 这一单上 [party](customer / merchant / rider)那一方的分数和等级,没有就是 null。
CreditBrief? creditOf(Order order, String party) => switch (party) {
      'customer' => order.customerCredit,
      'merchant' => order.merchantCredit,
      'rider' => order.riderCredit,
      _ => null,
    };

/// 这一单上该不该显示 [party] 那一方的信用分。
///
/// 除了状态,再各兜一道:商家的分跑腿单上不给(跑腿挂的是虚拟服务主体,没有商家);
/// 骑手的分要这一单真有骑手。
bool creditVisible(Order order, String party) {
  if (creditOf(order, party) == null || !kCreditStatuses.contains(order.status)) {
    return false;
  }
  return switch (party) {
    'merchant' => !order.isErrand,
    'rider' => order.riderId != null,
    _ => true,
  };
}

bool customerCreditVisible(Order order) => creditVisible(order, 'customer');
bool merchantCreditVisible(Order order) => creditVisible(order, 'merchant');
bool riderCreditVisible(Order order) => creditVisible(order, 'rider');

/// 订单上的一枚信用分小签。
class CreditChip extends StatelessWidget {
  const CreditChip({
    super.key,
    required this.order,
    required this.party,
    required this.viewer,
    this.api,
  });

  final Order order;

  /// 被看的是哪一方:customer / merchant / rider
  final String party;

  /// 看的人是谁(顾客 / 商家 / 骑手):公式说明里挑哪一条「谁能看到」
  final String viewer;

  /// 点开说明时拉公式用。为空时小签不可点(测试、没有网络的场合)
  final ApiClient? api;

  @override
  Widget build(BuildContext context) {
    final credit = creditOf(order, party);
    if (credit == null || !creditVisible(order, party)) {
      return const SizedBox.shrink();
    }
    final sz = Theme.of(context).sz;
    final label = '${kCreditPartyLabels[party] ?? ''}信用 ${credit.score} · ${credit.levelLabel}';
    final client = api;
    return Semantics(
      label: '$label,点开看这个分怎么来的',
      button: client != null,
      excludeSemantics: true,
      child: SzChip(
        label,
        dense: true,
        // 字色一律中性,不按等级染红:它是一条给人参考的信息,不是警报
        textColor: sz.inkMuted,
        onTap: client == null
            ? null
            : () => showCreditExplain(context, client, party: party, viewer: viewer),
      ),
    );
  }
}

/// 商家端、骑手端订单上的顾客信用分。
class CustomerCreditChip extends CreditChip {
  const CustomerCreditChip({super.key, required super.order, super.api, super.viewer = '商家'})
      : super(party: 'customer');
}

/// 用户端、骑手端订单上的商家信用分。
class MerchantCreditChip extends CreditChip {
  const MerchantCreditChip({super.key, required super.order, super.api, super.viewer = '顾客'})
      : super(party: 'merchant');
}

/// 用户端、商家端订单上的骑手信用分。
class RiderCreditChip extends CreditChip {
  const RiderCreditChip({super.key, required super.order, super.api, super.viewer = '顾客'})
      : super(party: 'rider');
}

/// 点开小签:这个分怎么来的、我能拿它做什么、不能做什么。内容全从服务端读(被看的那一方那一份)。
Future<void> showCreditExplain(BuildContext context, ApiClient api,
    {required String party, required String viewer}) {
  final spec = api.creditSpec(role: party);
  final fallbackTitle = '${kCreditPartyLabels[party] ?? ''}信用分';
  return showDialog<void>(
    context: context,
    builder: (context) => SzDialog(
      title: FutureBuilder<Map<String, dynamic>>(
          future: spec,
          builder: (context, snap) =>
              Text('${snap.data?['title'] ?? fallbackTitle}')),
      scrollable: true,
      content: FutureBuilder<Map<String, dynamic>>(
        future: spec,
        builder: (context, snap) {
          final sz = Theme.of(context).sz;
          final body = TextStyle(fontSize: kFontBody, height: 1.5, color: sz.ink);
          final note =
              TextStyle(fontSize: kFontNote, height: 1.45, color: sz.inkMuted);
          if (snap.hasError) {
            return Text('说明没加载出来。完整的公式在超级赞透明中心「信用分怎么算」。',
                style: body);
          }
          final s = snap.data;
          if (s == null) {
            return const SizedBox(
                height: 48, child: Center(child: CircularProgressIndicator()));
          }
          final seen = ((s['visibility'] as List?) ?? const [])
              .cast<Map>()
              .firstWhere((v) => v['who'] == viewer, orElse: () => const {});
          final never = ((s['never_used_for'] as List?) ?? const []).cast<String>();
          return Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (seen['what'] != null) Text('${seen['what']}', style: body),
              const SizedBox(height: 8),
              Text('${s['formula'] ?? ''}', style: note),
              if (s['level_rule'] != null) ...[
                const SizedBox(height: 4),
                Text('${s['level_rule']}', style: note),
              ],
              if (never.isNotEmpty) ...[
                const SizedBox(height: 10),
                for (final line in never)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('· $line', style: note),
                  ),
              ],
              const SizedBox(height: 6),
              Text('完整的公式在超级赞透明中心「信用分怎么算」。', style: note),
            ],
          );
        },
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('知道了')),
      ],
    ),
  );
}

/// 「我的信用分」:分数、每一项加减分和对应的记录、每条扣分旁边的申诉、公式。三端共用。
///
/// 数据全部来自 `/credit/me`(按登录的角色算自己那一份),公式那一段是它带的 `rules` ——
/// 和透明中心 `/transparency/credit?role=` 是同一份(服务端 credit.public_spec),
/// 这里一个数字都不写死;「谁看得到」那一句、申诉框里「改判会怎样」那一句也是服务端给的。
///
/// 页面上每一个扣分都要能回答「是哪一单、哪一天、为什么」,并且旁边就是申诉:
/// 能走原来的申诉通道就走原来的(72 小时内,改判的话钱和记录一起改),
/// 接不上的走客服工单。申诉成立,这一条不再计分,服务端当场重算。
class CreditPage extends StatefulWidget {
  const CreditPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<CreditPage> createState() => _CreditPageState();
}

/// 申诉框里的例子:按角色给一句像样的(只是占位提示,不是规则)
const Map<String, String> _kAppealHints = {
  'customer': '例如:那天我一直在家,手机没有未接来电',
  'merchant': '例如:出餐前拍过照,餐盒封好是完整的',
  'rider': '例如:取餐时餐盒已经裂了,我当场拍了照',
};

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

  Future<String?> _askReason(String role, Map<String, dynamic> appeal) async {
    final via = appeal['via'] as String? ?? '';
    final confirm = '${appeal['confirm'] ?? ''}'.isNotEmpty
        ? '${appeal['confirm']}'
        : (via == 'appeal'
            ? '平台会重新复核这次判定。改判的话,这一条不再计分。'
            : '会转给平台客服,回复在「联系平台客服」里看得到。${appeal['after'] ?? ''}');
    final ctrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => SzDisposeWith(
        controllers: [ctrl],
        child: SzDialog(
          title: const Text('申诉这一条扣分'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(confirm, style: const TextStyle(fontSize: kFontBody)),
            const SizedBox(height: 12),
            TextField(
              controller: ctrl,
              maxLines: 3,
              maxLength: 400,
              decoration: InputDecoration(
                  hintText: _kAppealHints[role] ?? _kAppealHints['customer'],
                  border: const OutlineInputBorder()),
            ),
          ]),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('再想想')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('提交申诉')),
          ],
        ),
      ),
    );
    if (ok != true) return null;
    final text = ctrl.text.trim();
    if (text.length < 5) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('理由至少写 5 个字,复核的人要有东西可看')));
      }
      return null;
    }
    return text;
  }

  Future<void> _appeal(String role, Map<String, dynamic> row) async {
    final a = (row['appeal'] as Map?)?.cast<String, dynamic>() ?? const {};
    final via = a['via'] as String? ?? '';
    if (via.isEmpty) return;
    final reason = await _askReason(role, a);
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
              : '已转给平台客服,回复在「联系平台客服」里看得到')));
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
            final role = '${d['role'] ?? 'customer'}';
            return ListView(
              padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 28),
              children: [
                _header(context, d),
                const SizedBox(height: 16),
                _plusCard(context, d),
                const SizedBox(height: 16),
                _minusCard(context, role, d),
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
    // 老服务端没有 seen_by(那时只有顾客有分):照当时的口径说
    final seen = '${d['seen_by'] ?? ''}'.isNotEmpty
        ? '${d['seen_by']}'
        : '接了你单的商家、接到你单的骑手只看得到分数和等级,看不到下面这些明细。';
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
            Text(seen,
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

  Widget _minusCard(BuildContext context, String role, Map<String, dynamic> d) {
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
          _deductionCard(context, role, r),
          const SizedBox(height: 8),
        ],
    ]);
  }

  Widget _deductionCard(BuildContext context, String role, Map<String, dynamic> r) {
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
                onPressed: () => _appeal(role, r),
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

  /// 「这个分怎么算」:整段是服务端 rules(= /transparency/credit?role=)原样摊开。
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
            // 起算日之前的裁决不扣分(老服务端没有这个字段)
            if (s['count_from_why'] != null) bullet('${s['count_from_why']}'),
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
