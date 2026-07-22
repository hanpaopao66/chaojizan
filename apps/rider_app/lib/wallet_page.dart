import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'issues_page.dart';
import 'onboarding_page.dart';

/// 骑手钱包:余额卡片 + 提现 + 收入/提现记录。
class WalletPage extends StatefulWidget {
  const WalletPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<WalletPage> createState() => _WalletPageState();
}

class _WalletPageState extends State<WalletPage> {
  Wallet? _wallet;
  Map<String, dynamic>? _worklog; // 我的数据:在线时长/单量(只统计不考核)
  List<Earning> _earnings = [];
  List<Withdrawal> _withdrawals = [];
  int _segment = 0; // 0 收入明细 / 1 提现记录

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final wallet = await widget.api.wallet();
      final earnings = await widget.api.earnings();
      final withdrawals = await widget.api.withdrawals();
      Map<String, dynamic>? worklog;
      try {
        worklog = await widget.api.riderWorklog();
      } catch (_) {}
      if (mounted) {
        setState(() {
          _wallet = wallet;
          _earnings = earnings;
          _withdrawals = withdrawals;
          _worklog = worklog;
        });
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _withdraw() async {
    final wallet = _wallet;
    if (wallet == null) return;
    final controller = TextEditingController(
        text: (wallet.balanceCents / 100).toStringAsFixed(2));
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('申请提现'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('可提现 ${yuan(wallet.balanceCents)},最低 ¥10'),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
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
      await widget.api.requestWithdrawal(amount);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('提现申请已提交,平台确认后打款')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// UTC ISO 时间 → 本地 "MM-dd HH:mm"
  String _localTime(String iso) {
    final t = DateTime.tryParse(iso)?.toLocal();
    if (t == null) return '';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(t.month)}-${two(t.day)} ${two(t.hour)}:${two(t.minute)}';
  }

  Widget _metric(String label, int cents) {
    return Column(children: [
      Text(yuan(cents), style: Theme.of(context).textTheme.titleMedium),
      Text(label, style: Theme.of(context).textTheme.bodySmall),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final wallet = _wallet;
    if (wallet == null) {
      return const Center(child: CircularProgressIndicator());
    }
    // 今日战报:后端时间戳是 UTC,必须转本地时区再按日归属
    final now = DateTime.now();
    bool isToday(String iso) {
      final t = DateTime.tryParse(iso)?.toLocal();
      return t != null &&
          t.year == now.year && t.month == now.month && t.day == now.day;
    }

    final todayEarnings = _earnings.where((e) => isToday(e.createdAt)).toList();
    final todayCents =
        todayEarnings.fold(0, (sum, e) => sum + e.amountCents);

    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 绿色大数卡:余额大字 + 白色提现按钮(风格系统规则④)
          MoneyHeroCard(
            label: '可提现余额',
            amountCents: wallet.balanceCents,
            subtitle:
                '今日跑单 ${todayEarnings.length} 单,入账 ${yuan(todayCents)} · 提现零手续费 T+1',
            action: FilledButton(
              style: FilledButton.styleFrom(
                backgroundColor: Colors.white,
                foregroundColor: kMoneyGreen,
                minimumSize: const Size(0, 38),
                padding: const EdgeInsets.symmetric(horizontal: 22),
                textStyle:
                    const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800),
              ),
              onPressed: wallet.balanceCents >= 1000 ? _withdraw : null,
              child: Text(wallet.balanceCents >= 1000 ? '提现' : '满 ¥10 可提'),
            ),
          ),
          const SizedBox(height: 8),
          // 承诺卡:品牌渐变唯一允许出现处(规则⑦)
          const PledgeCard(
            title: '配送费 100% 归骑手',
            body: '平台分文不取,提现零手续费——规则写进开源代码,欢迎监督',
          ),
          const SizedBox(height: 8),
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  _metric('累计收入', wallet.totalEarnedCents),
                  _metric('提现中', wallet.pendingWithdrawalCents),
                  _metric('已提现', wallet.withdrawnCents),
                ],
              ),
            ),
          ),
          if (_worklog != null) ...[
            const SizedBox(height: 8),
            // 我的数据:自我参考,不做考核
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('我的数据(仅自己可见,不做考核)',
                        style: Theme.of(context).textTheme.titleSmall),
                    const SizedBox(height: 6),
                    Text(
                      '今日在线 ${(_worklog!['today_minutes'] as int) ~/ 60} 小时'
                      '${(_worklog!['today_minutes'] as int) % 60} 分 · '
                      '${_worklog!['today_orders']} 单 ${yuan(_worklog!['today_earned_cents'] as int)}\n'
                      '本周在线 ${(_worklog!['week_minutes'] as int) ~/ 60} 小时'
                      '${(_worklog!['week_minutes'] as int) % 60} 分 · '
                      '${_worklog!['week_orders']} 单 ${yuan(_worklog!['week_earned_cents'] as int)}',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 8),
          Card(
            child: Column(children: [
              ListTile(
                dense: true,
                leading: const Icon(Icons.school_outlined),
                title: const Text('上岗培训考试'),
                subtitle: const Text('交通安全/食安/平台规则,80 分通过'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => RiderExamPage(api: widget.api))),
              ),
              const Divider(height: 1),
              ListTile(
                dense: true,
                leading: const Icon(Icons.menu_book_outlined),
                title: const Text('规则中心'),
                subtitle: const Text('转单/考核/结算/申诉,规则先说清'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => RiderRulesPage(api: widget.api))),
              ),
              const Divider(height: 1),
              ListTile(
                dense: true,
                leading: const Icon(Icons.health_and_safety_outlined),
                title: const Text('意外保障'),
                subtitle: const Text('每日上线自动登记,出险有兜底'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => RiderInsurancePage(api: widget.api))),
              ),
              const Divider(height: 1),
              ListTile(
                dense: true,
                leading: const Icon(Icons.contact_phone_outlined),
                title: const Text('紧急联系人'),
                subtitle: const Text('SOS 时平台第一时间联系(加密存储)'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => EmergencyContactsPage(api: widget.api))),
              ),
              const Divider(height: 1),
              ListTile(
                dense: true,
                leading: const Icon(Icons.emergency_outlined,
                    color: Colors.red),
                title: const Text('事故上报',
                    style: TextStyle(color: Colors.red)),
                subtitle: const Text('人先安全;在途订单自动处理'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => RiderAccidentPage(api: widget.api))),
              ),
              const Divider(height: 1),
              ListTile(
                dense: true,
                leading: const Icon(Icons.checkroom_outlined),
                title: const Text('装备申领'),
                subtitle: const Text('头盔/保温餐箱/雨衣'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => RiderGearPage(api: widget.api))),
              ),
            ]),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              dense: true,
              leading: const Icon(Icons.report_problem_outlined),
              title: const Text('配送异常与申诉'),
              subtitle: const Text('上报记录;判骑手责的裁决 72 小时内可申诉'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => RiderIssuesPage(api: widget.api))),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              dense: true,
              leading: const Icon(Icons.credit_card_outlined),
              title: const Text('收款账户'),
              subtitle: const Text('提现打款到这里;未登记不能提现'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => PayoutAccountPage(api: widget.api))),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            color: Theme.of(context).colorScheme.tertiaryContainer,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  Icon(Icons.handshake,
                      color: Theme.of(context).colorScheme.onTertiaryContainer),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      '超级赞承诺:配送费 100% 归骑手,平台分文不取,提现零手续费。每一分都看得见。\n'
                      '配送收入属劳务报酬,请依法申报个税;平台接入灵活用工代发后将自动完税并另行通知。',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: Theme.of(context)
                              .colorScheme
                              .onTertiaryContainer,
                          height: 1.5),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
          Card(
            child: ListTile(
              dense: true,
              leading: const Icon(Icons.support_agent_outlined),
              title: const Text('联系平台客服'),
              subtitle: const Text('提现、账目、认证有疑问?直接找平台'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => SupportPage(api: widget.api))),
            ),
          ),
          const SizedBox(height: 12),
          SegmentedButton<int>(
            segments: const [
              ButtonSegment(value: 0, label: Text('收入明细')),
              ButtonSegment(value: 1, label: Text('提现记录')),
            ],
            selected: {_segment},
            onSelectionChanged: (s) => setState(() => _segment = s.first),
          ),
          const SizedBox(height: 8),
          if (_segment == 0)
            if (_earnings.isEmpty)
              const Padding(
                  padding: EdgeInsets.all(24),
                  child: Center(child: Text('还没有收入,去抢单吧')))
            else
              ..._earnings.map((e) => ListTile(
                    dense: true,
                    leading: const Icon(Icons.add_circle, color: Colors.green),
                    title: Text('配送费 +${yuan(e.amountCents)}'),
                    subtitle: Text('订单 ${e.orderNo}'),
                    trailing: Text(_localTime(e.createdAt)),
                  ))
          else if (_withdrawals.isEmpty)
            const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: Text('还没有提现记录')))
          else
            ..._withdrawals.map((w) => ListTile(
                  dense: true,
                  leading: Icon(
                    switch (w.status) {
                      'paid' => Icons.check_circle,
                      'rejected' => Icons.cancel,
                      _ => Icons.hourglass_top,
                    },
                    color: switch (w.status) {
                      'paid' => Colors.green,
                      'rejected' || 'failed' => Colors.red,
                      _ => Colors.orange,
                    },
                  ),
                  title: Text('提现 ${yuan(w.amountCents)} · ${w.statusLabel}'),
                  subtitle: w.rejectReason.isNotEmpty
                      ? Text('原因:${w.rejectReason}')
                      : Text(_localTime(w.createdAt)),
                )),
        ],
      ),
    );
  }
}
