import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'dart:convert';
import 'dart:typed_data';

import 'package:share_plus/share_plus.dart';

import 'analytics_page.dart';
import 'invoice_page.dart';

/// 商家对账:今日概览 + 按日账单,点某天看逐单明细。
class FinancePage extends StatefulWidget {
  const FinancePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<FinancePage> createState() => _FinancePageState();
}

class _FinancePageState extends State<FinancePage> {
  List<DayStat>? _daily;
  Wallet? _wallet;
  Map<String, dynamic>? _quality;
  Map<String, dynamic>? _tier;
  List<Withdrawal> _withdrawals = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final daily = await widget.api.financeDaily();
      final wallet = await widget.api.merchantWallet();
      final withdrawals = await widget.api.merchantWithdrawals();
      final quality = await widget.api.merchantQuality();
      final tier = await widget.api.merchantCommissionTier();
      if (mounted) {
        setState(() {
          _daily = daily;
          _wallet = wallet;
          _withdrawals = withdrawals;
          _quality = quality;
          _tier = tier;
        });
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 提现:输入金额 → 提交申请 → T+1 打款
  Future<void> _withdraw() async {
    final wallet = _wallet;
    if (wallet == null) return;
    final controller = TextEditingController(
        text: (wallet.withdrawableCents / 100).toStringAsFixed(2));
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('申请提现'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('可提现 ${yuan(wallet.withdrawableCents)},今天申请明天到账,零手续费',
                style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: '提现金额(元)', border: OutlineInputBorder()),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('提交')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final amount = ((double.tryParse(controller.text) ?? 0) * 100).round();
    try {
      await widget.api.requestMerchantWithdrawal(amount);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('提现申请已提交,T+1 打款')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  String _localTime(String iso) {
    final t = DateTime.tryParse(iso)?.toLocal();
    if (t == null) return '';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(t.month)}-${two(t.day)} ${two(t.hour)}:${two(t.minute)}';
  }

  Widget _walletMetric(String label, int cents) {
    return Column(children: [
      Text(yuan(cents), style: Theme.of(context).textTheme.titleMedium),
      Text(label, style: Theme.of(context).textTheme.bodySmall),
    ]);
  }

  Widget _walletCard(Wallet wallet) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            Text('可提现余额(外卖净额 + 团购核销净额 − 保证金留存)',
                style: Theme.of(context).textTheme.bodySmall),
            Text(yuan(wallet.withdrawableCents),
                style: Theme.of(context).textTheme.displaySmall),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                _walletMetric('累计收入', wallet.totalEarnedCents),
                _walletMetric('提现中', wallet.pendingWithdrawalCents),
                _walletMetric('已提现', wallet.withdrawnCents),
                _walletMetric('保证金留存', wallet.depositHeldCents),
              ],
            ),
            if (wallet.depositHeldCents < wallet.depositRequiredCents)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                    '保证金 ${yuan(wallet.depositHeldCents)}/${yuan(wallet.depositRequiredCents)}:'
                    '从营收自动留存,攒够后超出部分即可全额提现;退店无纠纷全额退还',
                    style: Theme.of(context).textTheme.bodySmall),
              ),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                icon: const Icon(Icons.account_balance_wallet_outlined),
                label: const Text('提现(T+1 到账,零手续费)'),
                onPressed: wallet.withdrawableCents >= 1000 ? _withdraw : null,
              ),
            ),
            if (wallet.withdrawableCents < 1000)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('满 ¥10 可提现',
                    style: Theme.of(context).textTheme.bodySmall),
              ),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                TextButton.icon(
                  icon: const Icon(Icons.credit_card_outlined, size: 18),
                  label: const Text('收款账户'),
                  onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                      builder: (_) => PayoutAccountPage(api: widget.api))),
                ),
                TextButton.icon(
                  icon: const Icon(Icons.receipt_long_outlined, size: 18),
                  label: const Text('服务费发票'),
                  onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                      builder: (_) => InvoicePage(api: widget.api))),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _metric(String label, String value) {
    return Column(children: [
      Text(value, style: Theme.of(context).textTheme.titleMedium),
      Text(label, style: Theme.of(context).textTheme.bodySmall),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final daily = _daily;
    if (daily == null) {
      return const Center(child: CircularProgressIndicator());
    }
    final today = DateTime.now();
    final todayKey =
        '${today.year}-${today.month.toString().padLeft(2, '0')}-${today.day.toString().padLeft(2, '0')}';
    final todayStat = daily.where((d) => d.day == todayKey).firstOrNull;

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (_wallet != null) ...[
            _walletCard(_wallet!),
            const SizedBox(height: 12),
          ],
          if (_tier != null) ...[
            // 阶梯佣金:单量越大费率越低,5% 永远是上限,只降不升
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      const Icon(Icons.trending_down, size: 18),
                      const SizedBox(width: 6),
                      Text('阶梯佣金',
                          style: Theme.of(context)
                              .textTheme
                              .titleSmall
                              ?.copyWith(fontWeight: FontWeight.bold)),
                      const Spacer(),
                      Text(
                          '当前费率 ${((_tier!['commission_rate'] as num) * 100).toStringAsFixed(1)}%',
                          style: TextStyle(
                              color: Theme.of(context).colorScheme.primary,
                              fontWeight: FontWeight.bold)),
                    ]),
                    const SizedBox(height: 6),
                    Text(
                      '上月完成 ${_tier!['last_month_completed']} 单 · '
                      '本月已完成 ${_tier!['this_month_completed']} 单'
                      '${_tier!['next_tier_from'] != null ? " · 本月再完成 ${_tier!['orders_to_next']} 单,下月降至 ${((_tier!['next_tier_rate'] as num) * 100).toStringAsFixed(1)}%" : " · 已是最低档"}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    Text(
                      '每月 1 日按上月单量自动重算,只降不升;5% 永远是上限',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context).colorScheme.outline),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
          ],
          if (_quality != null && (_quality!['completed_30d'] as int) > 0) ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                  children: [
                    _metric('近30天完成', '${_quality!['completed_30d']} 单'),
                    _metric(
                        '出餐超时率',
                        _quality!['ready_late_rate'] == null
                            ? '—'
                            : '${((_quality!['ready_late_rate'] as num) * 100).toStringAsFixed(1)}%'),
                    _metric('拒单', '${_quality!['rejects_30d']} 次'),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 12),
          ],
          Card(
            child: ListTile(
              leading: const Icon(Icons.file_download_outlined),
              title: const Text('导出对账单(CSV)'),
              subtitle: const Text('逐单明细+按日小计,口径与钱包同源,记账可用'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () async {
                final now = DateTime.now();
                final months = [
                  for (var i = 0; i < 6; i++)
                    DateTime(now.year, now.month - i)
                ];
                final month = await showModalBottomSheet<String>(
                  context: context,
                  builder: (context) => SafeArea(
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      for (final m in months)
                        ListTile(
                          title: Text(
                              '${m.year}-${m.month.toString().padLeft(2, '0')}'),
                          onTap: () => Navigator.pop(context,
                              '${m.year}-${m.month.toString().padLeft(2, '0')}'),
                        ),
                    ]),
                  ),
                );
                if (month == null || !context.mounted) return;
                try {
                  final csv = await widget.api.merchantStatementCsv(month);
                  await SharePlus.instance.share(ShareParams(files: [
                    XFile.fromData(
                        Uint8List.fromList(utf8.encode(csv)),
                        mimeType: 'text/csv',
                        name: 'statement-$month.csv'),
                  ]));
                } catch (e) {
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(e.toString())));
                }
              },
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              leading: const Icon(Icons.insights_outlined, color: kMoneyGreen),
              title: const Text('经营分析'),
              subtitle: const Text('时段分布 / 菜品排行 / 客单价 / 复购(仅自己可见)'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => AnalyticsPage(api: widget.api))),
            ),
          ),
          const SizedBox(height: 12),
          // 绿色大数卡:今日实收大字(风格系统规则④,三端最认的一屏)
          MoneyHeroCard(
            label: '今日实收',
            amountCents: todayStat?.netCents ?? 0,
            subtitle: '流水 ${yuan(todayStat?.foodCents ?? 0)} − '
                '佣金 ${yuan(todayStat?.commissionCents ?? 0)} · '
                '共 ${todayStat?.orderCount ?? 0} 单',
          ),
          const SizedBox(height: 12),
          Text('按日账单(近 30 天)',
              style: Theme.of(context).textTheme.titleMedium),
          if (daily.isEmpty)
            const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: Text('还没有入账记录,订单完成后会出现在这里')))
          else
            ...daily.map((d) => Card(
                  margin: const EdgeInsets.symmetric(vertical: 4),
                  child: ListTile(
                    title: Text('${d.day} · ${d.orderCount} 单'),
                    subtitle: Text(
                        '流水 ${yuan(d.foodCents)} − 佣金 ${yuan(d.commissionCents)}'),
                    trailing: Text('+${yuan(d.netCents)}',
                        style: TextStyle(
                            color: Colors.green.shade700,
                            fontWeight: FontWeight.bold)),
                    onTap: () => Navigator.of(context).push(MaterialPageRoute(
                        builder: (_) =>
                            DayOrdersPage(api: widget.api, stat: d))),
                  ),
                )),
          if (_withdrawals.isNotEmpty) ...[
            const SizedBox(height: 16),
            Text('提现记录', style: Theme.of(context).textTheme.titleMedium),
            ..._withdrawals.take(20).map((w) => Card(
                  margin: const EdgeInsets.symmetric(vertical: 4),
                  child: ListTile(
                    dense: true,
                    title: Text(yuan(w.amountCents)),
                    subtitle: Text(_localTime(w.createdAt) +
                        (w.rejectReason.isEmpty ? '' : ' · ${w.rejectReason}')),
                    trailing: Text(w.statusLabel,
                        style: TextStyle(
                            color: switch (w.status) {
                          'paid' => Colors.green.shade700,
                          'rejected' || 'failed' => Colors.red.shade700,
                          _ => Colors.orange.shade700,
                        })),
                  ),
                )),
          ],
          const SizedBox(height: 16),
          // 承诺卡:品牌渐变唯一允许出现处(规则⑦,对账页尾)
          const PledgeCard(
            title: '超级赞承诺',
            body: '佣金只抽 5%,单量越大费率越低 · 每日 4:00 自动核账,差一分钱系统报警 · 账目写进开源代码,欢迎监督',
          ),
        ],
      ),
    );
  }
}

/// 单日入账明细,和日汇总逐单能对上。
class DayOrdersPage extends StatelessWidget {
  const DayOrdersPage({super.key, required this.api, required this.stat});

  final ApiClient api;
  final DayStat stat;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('${stat.day} 入账明细')),
      body: FutureBuilder(
        future: api.financeOrders(stat.day),
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final orders = snapshot.data!;
          return ListView(
            children: [
              ListTile(
                title: Text('共 ${stat.orderCount} 单,净收入 ${yuan(stat.netCents)}'),
                subtitle: Text(
                    '菜品流水 ${yuan(stat.foodCents)},平台佣金 ${yuan(stat.commissionCents)}(5%)'),
              ),
              const Divider(height: 1),
              for (final o in orders)
                ListTile(
                  dense: true,
                  title: Text('订单 ${o.orderNo}'),
                  subtitle: Text(
                      '${o.createdAt.substring(11, 16)} · 流水 ${yuan(o.foodCents)} − 佣金 ${yuan(o.commissionCents)}'),
                  trailing: Text('+${yuan(o.netCents)}',
                      style: TextStyle(color: Colors.green.shade700)),
                ),
            ],
          );
        },
      ),
    );
  }
}
