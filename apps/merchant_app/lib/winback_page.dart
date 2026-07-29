import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 老客召回(#117):这家店有多少人好久没来了,要不要发一批券把人叫回来。
///
/// 券钱商家出,所以决定权也交给商家 —— 但顾客名单不交出去:
/// 页面只有计数,商家看不到是谁、也导不出手机号。发不发是商家的选择,
/// 发给谁、发几次由平台按频控执行(每人每店每月一次,全局每周两条)。
class MerchantWinbackPage extends StatefulWidget {
  const MerchantWinbackPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<MerchantWinbackPage> createState() => _MerchantWinbackPageState();
}

class _MerchantWinbackPageState extends State<MerchantWinbackPage> {
  Map<String, dynamic>? _data;
  Object? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final data = await widget.api.merchantWinback();
      if (!mounted) return;
      setState(() => _data = data);
    } catch (e) {
      if (!mounted) return;
      setState(() => _error = e);
    }
  }

  Future<void> _createBatch() async {
    final off = TextEditingController(text: '5');
    final threshold = TextEditingController(text: '30');
    final total = TextEditingController(text: '50');
    final validDays = TextEditingController(text: '15');

    final ok = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('发一批召回券'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Expanded(
                child: TextField(
                    controller: threshold,
                    keyboardType: TextInputType.number,
                    decoration:
                        const InputDecoration(labelText: '满(元,0 无门槛)')),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                    controller: off,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: '减(元)')),
              ),
            ]),
            Row(children: [
              Expanded(
                child: TextField(
                    controller: total,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: '总量(预算封顶)')),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                    controller: validDays,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: '有效天数')),
              ),
            ]),
            const SizedBox(height: 12),
            const Text('总量就是你的预算上限,发完自动停,不会超支。'
                '每人只发一张,同一个人一个月最多被叫一次。',
                style: TextStyle(fontSize: 12)),
          ]),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('取消')),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('确认发布'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;

    final t = ((double.tryParse(threshold.text) ?? 0) * 100).round();
    final o = ((double.tryParse(off.text) ?? 0) * 100).round();
    final tot = int.tryParse(total.text) ?? 0;
    if (o <= 0 || tot <= 0 || (t > 0 && o >= t)) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('减额需 > 0 且小于门槛,总量 > 0')));
      return;
    }
    setState(() => _busy = true);
    try {
      await widget.api.createShopCouponBatch({
        'name': '召回老客 满${t ~/ 100}减${o ~/ 100}',
        'trigger': 'winback',
        'threshold_cents': t,
        'off_cents': o,
        'total': tot,
        'per_user_limit': 1,
        'valid_days': int.tryParse(validDays.text) ?? 15,
      });
      await _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已发布,系统会按频控陆续送出')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _stopBatch(int batchId) async {
    setState(() => _busy = true);
    try {
      await widget.api.toggleShopCouponBatch(batchId);
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final sz = theme.sz;
    final data = _data;
    return Scaffold(
      appBar: AppBar(title: const Text('老客召回')),
      body: _error != null
          ? SzError(error: _error!, onRetry: _load)
          : data == null
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(kPagePad),
                    children: [
                      SzCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const SzSectionTitle('这家店的老客'),
                            const SizedBox(height: 12),
                            _Stat('30 天没来过',
                                '${data['dormant_30d']} 人', sz.clay),
                            _Stat('90 天没来过',
                                '${data['dormant_90d']} 人', sz.hold),
                            _Stat('半年内来过',
                                '${data['customers_180d']} 人', sz.inkMuted),
                          ],
                        ),
                      ),
                      const SizedBox(height: 14),
                      SzCard(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const SzSectionTitle('平台不会给你顾客名单'),
                            const SizedBox(height: 8),
                            Text('你看到的只有人数。谁没来、手机号是多少,'
                                '平台不给你,也不给任何人 —— 名单一旦交出去就再也收不回来。\n\n'
                                '想把人叫回来,就发一批券:平台按每人每月最多一次、'
                                '每周最多两条的频控替你送出去,发完即止。',
                                style: theme.textTheme.bodySmall
                                    ?.copyWith(color: sz.inkMuted, height: 1.7)),
                          ],
                        ),
                      ),
                      const SizedBox(height: 14),
                      if (data['batch'] == null)
                        FilledButton(
                          onPressed: _busy ? null : _createBatch,
                          child: const Text('发一批召回券'),
                        )
                      else
                        _ActiveBatch(
                          batch: data['batch'] as Map<String, dynamic>,
                          busy: _busy,
                          onStop: _stopBatch,
                        ),
                      const SizedBox(height: 12),
                      Text('券的成本由你承担,平台不抽券的钱,也不出补贴 —— '
                          '这笔预算花多少、什么时候停,完全是你说了算',
                          style: theme.textTheme.bodySmall
                              ?.copyWith(color: sz.inkMuted)),
                    ],
                  ),
                ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value, this.color);

  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Row(children: [
          Expanded(
              child: Text(label,
                  style: TextStyle(color: Theme.of(context).sz.inkMuted))),
          Text(value,
              style: szFigure(
                  fontSize: 20, fontWeight: FontWeight.w600, color: color)),
        ]),
      );
}

class _ActiveBatch extends StatelessWidget {
  const _ActiveBatch(
      {required this.batch, required this.busy, required this.onStop});

  final Map<String, dynamic> batch;
  final bool busy;
  final Future<void> Function(int) onStop;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final total = (batch['total'] as num?)?.toInt() ?? 0;
    final issued = (batch['issued'] as num?)?.toInt() ?? 0;
    final off = (batch['off_cents'] as num?)?.toInt() ?? 0;
    final threshold = (batch['threshold_cents'] as num?)?.toInt() ?? 0;
    return SzCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const SzSectionTitle('正在召回'),
        const SizedBox(height: 8),
        Text(
            threshold > 0
                ? '满 ${yuan(threshold)} 减 ${yuan(off)}'
                : '立减 ${yuan(off)}',
            style: TextStyle(
                fontSize: 16, fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 6),
        Text('已发出 $issued / $total 张',
            style: szMoney(fontSize: 13, color: sz.inkMuted)),
        const SizedBox(height: 4),
        Text('发完自动停,不会超出你设的总量',
            style: TextStyle(fontSize: 12, color: sz.inkMuted)),
        const SizedBox(height: 12),
        OutlinedButton(
          onPressed:
              busy ? null : () => onStop((batch['id'] as num).toInt()),
          child: const Text('立即停止'),
        ),
      ]),
    );
  }
}
