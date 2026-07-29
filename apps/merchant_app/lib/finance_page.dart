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

  /// 近的说「多久前」,超过昨天自动退回「M/D HH:MM」——
  /// 精度不丢,但「2 小时前提的」比「07-29 05:12」好读得多。
  String _localTime(String iso) => szTimeAgo(iso);

  Widget _walletMetric(String label, int cents) {
    final sz = Theme.of(context).sz;
    return Expanded(
      child: Column(children: [
        Text(yuan(cents),
            style: szMoney(
                fontSize: 14, fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 2),
        Text(label,
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 10.5, color: sz.inkMuted)),
      ]),
    );
  }

  Widget _walletCard(Wallet wallet) {
    final sz = Theme.of(context).sz;
    return SzCard(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('可提现余额',
              style: TextStyle(fontSize: 12.5, color: sz.inkMuted)),
          const SizedBox(height: 2),
          Text(yuan(wallet.withdrawableCents),
              style: szMoney(
                  fontSize: 34, fontWeight: FontWeight.w600, color: sz.earn)),
          const SizedBox(height: 2),
          Text('外卖净额 + 团购核销净额 − 保证金留存',
              style: TextStyle(fontSize: 11, color: sz.inkFaint)),
          const SizedBox(height: 14),
          Row(
            children: [
              _walletMetric('累计收入', wallet.totalEarnedCents),
              _walletMetric('提现中', wallet.pendingWithdrawalCents),
              _walletMetric('已提现', wallet.withdrawnCents),
              _walletMetric('保证金', wallet.depositHeldCents),
            ],
          ),
          if (wallet.depositHeldCents < wallet.depositRequiredCents)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text(
                  '保证金 ${yuan(wallet.depositHeldCents)}/${yuan(wallet.depositRequiredCents)}:'
                  '从营收自动留存,攒够后超出部分即可全额提现;退店无纠纷全额退还',
                  style: TextStyle(
                      fontSize: 11, height: 1.5, color: sz.inkMuted)),
            ),
          const SizedBox(height: 14),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: wallet.withdrawableCents >= 1000 ? _withdraw : null,
              child: const Text('提现 · T+1 到账,零手续费'),
            ),
          ),
          if (wallet.withdrawableCents < 1000)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('满 ¥10 可提现',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: 11, color: sz.inkFaint)),
            ),
          const SizedBox(height: 4),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              TextButton(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => PayoutAccountPage(api: widget.api))),
                child: const Text('收款账户'),
              ),
              Container(width: 1, height: 12, color: sz.line),
              TextButton(
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => InvoicePage(api: widget.api))),
                child: const Text('服务费发票'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  /// 对账工具的一行:标题 + 一句说明 + 右箭头。热区整行,不小于 48。
  Widget _toolRow(String title, String desc, VoidCallback onTap,
      {bool isAsync = true}) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 13),
        child: Row(children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: TextStyle(fontSize: 13.5, color: sz.ink)),
                const SizedBox(height: 2),
                Text(desc,
                    style: TextStyle(fontSize: 11, color: sz.inkMuted)),
              ],
            ),
          ),
          Icon(Icons.chevron_right, size: 16, color: sz.inkFaint),
        ]),
      ),
    );
  }

  /// 按日账单一行:左日期与单量,右当日实收(到手的钱走 earn)。
  Widget _dayRow(DayStat d) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: () => Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => DayOrdersPage(api: widget.api, stat: d))),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 12),
        child: Row(children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${d.day} · ${d.orderCount} 单',
                    style: TextStyle(fontSize: 13.5, color: sz.ink)),
                const SizedBox(height: 2),
                Text(
                    '流水 ${yuan(d.foodCents)} − 佣金 ${yuan(d.commissionCents)}',
                    style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
              ],
            ),
          ),
          Text(yuan(d.netCents),
              style: szMoney(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w600,
                  color: sz.earn)),
          const SizedBox(width: 4),
          Icon(Icons.chevron_right, size: 16, color: sz.inkFaint),
        ]),
      ),
    );
  }

  /// 提现记录一行:状态用 chip,红色只留给驳回/失败。
  Widget _withdrawalRow(Withdrawal w) {
    final sz = Theme.of(context).sz;
    final color = switch (w.status) {
      'paid' => sz.earn,
      'rejected' || 'failed' => sz.danger,
      _ => sz.hold,
    };
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 11),
      child: Row(children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(yuan(w.amountCents),
                  style: szMoney(fontSize: 13.5, color: sz.ink)),
              const SizedBox(height: 2),
              Text(
                  _localTime(w.createdAt) +
                      (w.rejectReason.isEmpty ? '' : ' · ${w.rejectReason}'),
                  style: TextStyle(fontSize: 11, color: sz.inkMuted)),
            ],
          ),
        ),
        SzChip(w.statusLabel, color: color, dense: true),
      ]),
    );
  }

  Widget _metric(String label, String value, String unit) {
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
            SzCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    Text('阶梯佣金',
                        style: TextStyle(
                            fontSize: 13.5,
                            fontWeight: FontWeight.w600,
                            color: Theme.of(context).sz.ink)),
                    const Spacer(),
                    // 费率是"被抽走的",用 hold 不用强调色
                    Text(
                        '${((_tier!['commission_rate'] as num) * 100).toStringAsFixed(1)}%',
                        style: szFigure(
                            fontSize: 17,
                            fontWeight: FontWeight.w600,
                            color: Theme.of(context).sz.hold)),
                  ]),
                  const SizedBox(height: 6),
                  Text(
                    '上月完成 ${_tier!['last_month_completed']} 单 · '
                    '本月已完成 ${_tier!['this_month_completed']} 单'
                    '${_tier!['next_tier_from'] != null ? " · 本月再完成 ${_tier!['orders_to_next']} 单,下月降至 ${((_tier!['next_tier_rate'] as num) * 100).toStringAsFixed(1)}%" : " · 已是最低档"}',
                    style: TextStyle(
                        fontSize: 12,
                        height: 1.55,
                        color: Theme.of(context).sz.inkMuted),
                  ),
                  const SizedBox(height: 3),
                  Text('每月 1 日按上月单量自动重算,只降不升;5% 永远是上限',
                      style: TextStyle(
                          fontSize: 11, color: Theme.of(context).sz.inkFaint)),
                ],
              ),
            ),
            const SizedBox(height: 10),
          ],
          if (_quality != null && (_quality!['completed_30d'] as int) > 0) ...[
            SzCard(
              child: Row(
                children: [
                  _metric('近 30 天完成', '${_quality!['completed_30d']}', '单'),
                  _metric(
                      '出餐超时率',
                      _quality!['ready_late_rate'] == null
                          ? '—'
                          : ((_quality!['ready_late_rate'] as num) * 100)
                              .toStringAsFixed(1),
                      _quality!['ready_late_rate'] == null ? '' : '%'),
                  _metric('拒单', '${_quality!['rejects_30d']}', '次'),
                ],
              ),
            ),
            const SizedBox(height: 10),
          ],
          const SzSectionTitle('对账工具'),
          const SizedBox(height: 9),
          SzCard(
            padding: EdgeInsets.zero,
            child: Column(children: [
            _toolRow('导出对账单(CSV)', '逐单明细 + 按日小计,口径与钱包同源,记账可用',
                () async {
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
              }),
            Divider(height: 1, color: Theme.of(context).sz.line),
            _toolRow('经营分析', '时段分布 / 菜品排行 / 客单价 / 复购(仅自己可见)',
                () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => AnalyticsPage(api: widget.api))),
                isAsync: false),
            ]),
          ),
          const SizedBox(height: 18),
          // 今日这一屏要能一眼回答:挣了多少、被抽了多少、共几单
          const SzSectionTitle('今天'),
          const SizedBox(height: 9),
          MoneyHeroCard(
            label: '今日实收',
            amountCents: todayStat?.netCents ?? 0,
          ),
          const SizedBox(height: 8),
          SzCard(
            padding: const EdgeInsets.symmetric(
                horizontal: kCardPad, vertical: 4),
            child: Column(children: [
              SzFeeRow(
                  label: '菜品流水', amountCents: todayStat?.foodCents ?? 0),
              SzFeeRow(
                  label: '平台佣金',
                  note: '按 ${((_tier?['commission_rate'] as num?) ?? 0.05) * 100 ~/ 1}% 计',
                  amountCents: todayStat?.commissionCents ?? 0,
                  negative: true),
              Divider(color: Theme.of(context).sz.line, height: 17),
              SzFeeRow(
                  label: '今日实收 · ${todayStat?.orderCount ?? 0} 单',
                  amountCents: todayStat?.netCents ?? 0,
                  emphasized: true),
            ]),
          ),
          const SizedBox(height: 18),
          const SzSectionTitle('按日账单 · 近 30 天'),
          const SizedBox(height: 9),
          if (daily.isEmpty)
            const SzEmpty(
                art: BrandArt.receipt,
                text: '还没有入账记录\n订单完成后会出现在这里')
          else
            SzCard(
              padding: EdgeInsets.zero,
              child: Column(children: [
                for (final (i, d) in daily.indexed) ...[
                  if (i > 0)
                    Divider(height: 1, color: Theme.of(context).sz.line),
                  _dayRow(d),
                ],
              ]),
            ),
          if (_withdrawals.isNotEmpty) ...[
            const SizedBox(height: 18),
            const SzSectionTitle('提现记录'),
            const SizedBox(height: 9),
            SzCard(
              padding: EdgeInsets.zero,
              child: Column(children: [
                for (final (i, w) in _withdrawals.take(20).indexed) ...[
                  if (i > 0)
                    Divider(height: 1, color: Theme.of(context).sz.line),
                  _withdrawalRow(w),
                ],
              ]),
            ),
          ],
          const SizedBox(height: 18),
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
class DayOrdersPage extends StatefulWidget {
  const DayOrdersPage({super.key, required this.api, required this.stat});

  final ApiClient api;
  final DayStat stat;

  @override
  State<DayOrdersPage> createState() => _DayOrdersPageState();
}

class _DayOrdersPageState extends State<DayOrdersPage> {
  late Future<List<FinanceOrder>> _future =
      widget.api.financeOrders(widget.stat.day);
  ApiClient get api => widget.api;
  DayStat get stat => widget.stat;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text('${stat.day} 入账明细')),
      body: FutureBuilder(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return SzError(
                error: snapshot.error,
                onRetry: () =>
                    setState(() => _future = api.financeOrders(stat.day)));
          }
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }
          final orders = snapshot.data!;
          final sz = Theme.of(context).sz;
          return ListView(
            padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 24),
            children: [
              SzCard(
                padding: const EdgeInsets.symmetric(
                    horizontal: kCardPad, vertical: 4),
                child: Column(children: [
                  SzFeeRow(label: '菜品流水', amountCents: stat.foodCents),
                  SzFeeRow(
                      label: '平台佣金',
                      amountCents: stat.commissionCents,
                      negative: true),
                  Divider(color: sz.line, height: 17),
                  SzFeeRow(
                      label: '净收入 · ${stat.orderCount} 单',
                      amountCents: stat.netCents,
                      emphasized: true),
                ]),
              ),
              const SizedBox(height: 18),
              const SzSectionTitle('逐单明细'),
              const SizedBox(height: 9),
              if (orders.isEmpty)
                const SzEmpty(art: BrandArt.receipt, text: '这一天没有入账订单')
              else
                SzCard(
                  padding: EdgeInsets.zero,
                  child: Column(children: [
                    for (final (i, o) in orders.indexed) ...[
                      if (i > 0) Divider(height: 1, color: sz.line),
                      Padding(
                        padding: const EdgeInsets.symmetric(
                            horizontal: kCardPad, vertical: 11),
                        child: Row(children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text('${o.createdAt.substring(11, 16)} · ${o.orderNo}',
                                    style: TextStyle(
                                        fontSize: 12.5, color: sz.ink)),
                                const SizedBox(height: 2),
                                Text(
                                    '流水 ${yuan(o.foodCents)} − 佣金 ${yuan(o.commissionCents)}',
                                    style: TextStyle(
                                        fontSize: 11, color: sz.inkMuted)),
                              ],
                            ),
                          ),
                          Text(yuan(o.netCents),
                              style: szMoney(
                                  fontSize: 13.5,
                                  fontWeight: FontWeight.w600,
                                  color: sz.earn)),
                        ]),
                      ),
                    ],
                  ]),
                ),
            ],
          );
        },
      ),
    );
  }
}
