/// 收款账户登记页(骑手/商家共用):提现打款的目标账户。
///
/// 账号只在提交时上行一次,之后接口只回尾 4 位——完整账号密文落库,
/// 只有平台打款界面能看到。换账户后 24 小时内的提现会被人工加核(防盗号改卡)。
library;

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'models.dart';

class PayoutAccountPage extends StatefulWidget {
  const PayoutAccountPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<PayoutAccountPage> createState() => _PayoutAccountPageState();
}

class _PayoutAccountPageState extends State<PayoutAccountPage> {
  PayoutAccount? _current;
  bool _loaded = false;
  bool _busy = false;

  String _kind = 'bank_personal';
  final _holder = TextEditingController();
  final _account = TextEditingController();
  final _bank = TextEditingController();

  static const _kinds = [
    ('bank_corporate', '对公账户'),
    ('bank_personal', '银行卡'),
    ('wechat', '微信'),
    ('alipay', '支付宝'),
  ];

  bool get _isBank => _kind.startsWith('bank');

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final a = await widget.api.payoutAccount();
      if (mounted) {
        setState(() {
          _current = a;
          _loaded = true;
          if (a.configured) {
            _kind = a.kind;
            _holder.text = a.holderName;
            _bank.text = a.bankName;
          }
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loaded = true);
    }
  }

  Future<void> _save() async {
    if (_holder.text.trim().length < 2 || _account.text.trim().length < 4) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请填写户名和完整账号')));
      return;
    }
    setState(() => _busy = true);
    try {
      final a = await widget.api.savePayoutAccount(
        kind: _kind,
        holderName: _holder.text.trim(),
        accountNo: _account.text.trim(),
        bankName: _bank.text.trim(),
      );
      if (!mounted) return;
      setState(() {
        _current = a;
        _account.clear();
      });
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('已保存。刚变更的账户,24 小时内提现会人工核实后打款')));
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
    final current = _current;
    return Scaffold(
      appBar: AppBar(title: const Text('收款账户')),
      body: !_loaded
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                if (current != null && current.configured)
                  Card(
                    child: ListTile(
                      leading: const Icon(Icons.check_circle,
                          color: Colors.green),
                      title: Text(
                          '当前:${current.kindLabel} ${current.holderName} '
                          '****${current.accountTail}'),
                      subtitle: Text(current.bankName.isEmpty
                          ? '提现将打款到该账户'
                          : '${current.bankName} · 提现将打款到该账户'),
                    ),
                  )
                else
                  Card(
                    color: theme.colorScheme.errorContainer.withValues(alpha: .5),
                    child: const ListTile(
                      leading: Icon(Icons.info_outline),
                      title: Text('还没登记收款账户'),
                      subtitle: Text('登记后才能申请提现(T+1 到账,零手续费)'),
                    ),
                  ),
                const SizedBox(height: 12),
                Text('账户类型', style: theme.textTheme.titleSmall),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: [
                    for (final (value, label) in _kinds)
                      ChoiceChip(
                        label: Text(label),
                        selected: _kind == value,
                        onSelected: (_) => setState(() => _kind = value),
                      ),
                  ],
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _holder,
                  maxLength: 50,
                  decoration: InputDecoration(
                      labelText: _kind == 'bank_corporate' ? '单位户名' : '户名/姓名',
                      border: const OutlineInputBorder()),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _account,
                  maxLength: 64,
                  decoration: InputDecoration(
                      labelText: _isBank ? '银行账号' : '收款账号(手机号/账号)',
                      helperText: current?.configured == true
                          ? '出于安全,这里不回显旧账号;要更换直接填新账号'
                          : null,
                      border: const OutlineInputBorder()),
                ),
                if (_isBank) ...[
                  const SizedBox(height: 12),
                  TextField(
                    controller: _bank,
                    maxLength: 100,
                    decoration: const InputDecoration(
                        labelText: '开户行(支行写全)',
                        border: OutlineInputBorder()),
                  ),
                ],
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _busy ? null : _save,
                    child: Text(_busy
                        ? '保存中…'
                        : (current?.configured == true ? '更换账户' : '保存')),
                  ),
                ),
                const SizedBox(height: 8),
                Text('账号加密存储,平台仅在打款时使用;更换账户后 24 小时内的提现会人工电话核实,防止账号被盗后改卡跑款。',
                    style: theme.textTheme.bodySmall),
              ],
            ),
    );
  }
}
