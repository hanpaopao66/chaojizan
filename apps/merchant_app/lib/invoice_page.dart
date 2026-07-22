/// 平台服务费发票:按自然月索取(佣金+团购服务费,系统聚合金额)。
/// 一个月一张,只能开已结束的月份;开好后这里可复制下载链接。
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';

class InvoicePage extends StatefulWidget {
  const InvoicePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<InvoicePage> createState() => _InvoicePageState();
}

class _InvoicePageState extends State<InvoicePage> {
  late String _period; // YYYY-MM,默认上个月
  Map<String, dynamic>? _summary;
  List<Map<String, dynamic>> _mine = [];
  final _title = TextEditingController();
  final _taxNo = TextEditingController();
  final _email = TextEditingController();
  bool _busy = false;

  List<String> get _recentPeriods {
    final now = DateTime.now();
    return [
      for (var i = 1; i <= 6; i++)
        () {
          final d = DateTime(now.year, now.month - i);
          return '${d.year}-${d.month.toString().padLeft(2, '0')}';
        }(),
    ];
  }

  @override
  void initState() {
    super.initState();
    _period = _recentPeriods.first;
    _load();
  }

  Future<void> _load() async {
    try {
      final summary = await widget.api.invoiceSummary(_period);
      final mine = await widget.api.myInvoices();
      if (mounted) {
        setState(() {
          _summary = summary;
          _mine = mine;
          if (_title.text.isEmpty) {
            _title.text = summary['title'] as String? ?? '';
            _taxNo.text = summary['tax_no'] as String? ?? '';
            _email.text = summary['email'] as String? ?? '';
          }
        });
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _apply() async {
    setState(() => _busy = true);
    try {
      await widget.api.applyInvoice(
        period: _period,
        title: _title.text.trim(),
        taxNo: _taxNo.text.trim(),
        email: _email.text.trim(),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('申请已提交,开票完成后会推送通知')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final summary = _summary;
    final requested = summary?['requested'] == true;
    final total = summary?['total_cents'] as int? ?? 0;
    return Scaffold(
      appBar: AppBar(title: const Text('平台服务费发票')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Row(children: [
            const Text('开票月份'),
            const SizedBox(width: 12),
            DropdownButton<String>(
              value: _period,
              items: [
                for (final p in _recentPeriods)
                  DropdownMenuItem(value: p, child: Text(p)),
              ],
              onChanged: (v) {
                if (v == null) return;
                setState(() {
                  _period = v;
                  _summary = null;
                });
                _load();
              },
            ),
          ]),
          if (summary != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('$_period 平台服务费', style: theme.textTheme.bodySmall),
                    Text(yuan(total), style: theme.textTheme.headlineMedium),
                    Text('外卖佣金 ${yuan(summary['commission_cents'] as int)} + '
                        '团购服务费 ${yuan(summary['voucher_fee_cents'] as int)}'
                        '(售后冲账已抵减)',
                        style: theme.textTheme.bodySmall),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 8),
          if (requested)
            const Card(
              child: ListTile(
                leading: Icon(Icons.check_circle, color: Colors.green),
                title: Text('该月已申请开票'),
                subtitle: Text('处理进度见下方开票记录'),
              ),
            )
          else ...[
            TextField(
                controller: _title,
                maxLength: 100,
                decoration: const InputDecoration(
                    labelText: '发票抬头(单位名称)', border: OutlineInputBorder())),
            const SizedBox(height: 10),
            TextField(
                controller: _taxNo,
                maxLength: 30,
                decoration: const InputDecoration(
                    labelText: '纳税人识别号', border: OutlineInputBorder())),
            const SizedBox(height: 10),
            TextField(
                controller: _email,
                maxLength: 100,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                    labelText: '接收邮箱(电子发票发到这里)',
                    border: OutlineInputBorder())),
            const SizedBox(height: 10),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _busy || total <= 0 ? null : _apply,
                child: Text(total <= 0 ? '该月无可开票金额' : '申请开票'),
              ),
            ),
          ],
          const SizedBox(height: 20),
          Text('开票记录', style: theme.textTheme.titleMedium),
          if (_mine.isEmpty)
            const Padding(
                padding: EdgeInsets.all(12), child: Text('还没有开票记录')),
          for (final inv in _mine)
            Card(
              child: ListTile(
                dense: true,
                title: Text('${inv['period']} · ${yuan(inv['amount_cents'] as int)}'),
                subtitle: Text(inv['status'] == 'issued'
                    ? '已开票${(inv['note'] as String).isEmpty ? '' : ' · ${inv['note']}'}'
                    : '开票处理中'),
                trailing: inv['status'] == 'issued' &&
                        (inv['file_url'] as String).isNotEmpty
                    ? TextButton(
                        onPressed: () {
                          Clipboard.setData(ClipboardData(
                              text: widget.api
                                  .resolveUrl(inv['file_url'] as String)));
                          ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(
                                  content: Text('发票链接已复制,浏览器打开下载')));
                        },
                        child: const Text('复制链接'))
                    : null,
              ),
            ),
        ],
      ),
    );
  }
}
