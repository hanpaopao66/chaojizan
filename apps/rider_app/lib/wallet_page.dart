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

  Widget _sep() => Divider(height: 1, color: Theme.of(context).sz.line);

  /// 入口行:标题 + 一句说明 + 右箭头。整行热区,高度不小于 48。
  Widget _navRow(String title, String desc, Widget Function() page,
      {bool danger = false}) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: () => Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => page())),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 13),
        child: Row(children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: TextStyle(
                        fontSize: 14, color: danger ? sz.danger : sz.ink)),
                const SizedBox(height: 2),
                Text(desc,
                    style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
              ],
            ),
          ),
          Icon(Icons.chevron_right, size: 16, color: sz.inkFaint),
        ]),
      ),
    );
  }

  Widget _metric(String label, int cents) {
    final sz = Theme.of(context).sz;
    return Expanded(
      child: Column(children: [
        Text(yuan(cents),
            style: szMoney(
                fontSize: 15, fontWeight: FontWeight.w600, color: sz.ink)),
        const SizedBox(height: 2),
        Text(label, style: TextStyle(fontSize: 11, color: sz.inkMuted)),
      ]),
    );
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
          // 这一屏要能一眼回答:能提多少、今天跑了多少、什么时候能到账。
          // 户外单手,所以金额和按钮都比另外两端再大一档
          MoneyHeroCard(
            label: '可提现余额',
            amountCents: wallet.balanceCents,
          ),
          const SizedBox(height: 8),
          SzCard(
            child: Column(children: [
              Row(children: [
                Expanded(
                  child: Text.rich(
                    TextSpan(children: [
                      const TextSpan(text: '今天跑了 '),
                      TextSpan(
                          text: '${todayEarnings.length}',
                          style: szFigure(
                              fontSize: 15, fontWeight: FontWeight.w600)),
                      const TextSpan(text: ' 单,入账 '),
                      TextSpan(
                          text: yuan(todayCents),
                          style: szMoney(
                              fontSize: 15,
                              fontWeight: FontWeight.w600,
                              color: Theme.of(context).sz.earn)),
                    ]),
                    style: TextStyle(
                        fontSize: 13, color: Theme.of(context).sz.ink),
                  ),
                ),
              ]),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  style: FilledButton.styleFrom(
                      minimumSize: const Size(0, 52)),
                  onPressed: wallet.balanceCents >= 1000 ? _withdraw : null,
                  child: Text(wallet.balanceCents >= 1000
                      ? '提现 · T+1 到账,零手续费'
                      : '满 ¥10 可提现'),
                ),
              ),
            ]),
          ),
          const SizedBox(height: 8),
          SzCard(
            child: Row(
              children: [
                _metric('累计收入', wallet.totalEarnedCents),
                _metric('提现中', wallet.pendingWithdrawalCents),
                _metric('已提现', wallet.withdrawnCents),
              ],
            ),
          ),
          if (_worklog != null) ...[
            const SizedBox(height: 8),
            // 我的数据:自我参考,不做考核
            SzCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('我的数据 · 仅自己可见,不做考核',
                      style: TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                          color: Theme.of(context).sz.ink)),
                  const SizedBox(height: 8),
                  Text(
                    '今日在线 ${(_worklog!['today_minutes'] as int) ~/ 60} 小时'
                    '${(_worklog!['today_minutes'] as int) % 60} 分 · '
                    '${_worklog!['today_orders']} 单 ${yuan(_worklog!['today_earned_cents'] as int)}\n'
                    '本周在线 ${(_worklog!['week_minutes'] as int) ~/ 60} 小时'
                    '${(_worklog!['week_minutes'] as int) % 60} 分 · '
                    '${_worklog!['week_orders']} 单 ${yuan(_worklog!['week_earned_cents'] as int)}',
                    style: TextStyle(
                        fontSize: 12,
                        height: 1.7,
                        color: Theme.of(context).sz.inkMuted),
                  ),
                ],
              ),
            ),
          ],
          const SizedBox(height: 18),
          const SzSectionTitle('保障与规则'),
          const SizedBox(height: 9),
          SzCard(
            padding: EdgeInsets.zero,
            child: Column(children: [
              _navRow('上岗培训考试', '交通安全 / 食安 / 平台规则,80 分通过',
                  () => RiderExamPage(api: widget.api)),
              _sep(),
              _navRow('规则中心', '转单 / 考核 / 结算 / 申诉,规则先说清',
                  () => RiderRulesPage(api: widget.api)),
              _sep(),
              _navRow('意外保障', '每日上线自动登记,出险有兜底',
                  () => RiderInsurancePage(api: widget.api)),
              _sep(),
              _navRow('紧急联系人', 'SOS 时平台第一时间联系(加密存储)',
                  () => EmergencyContactsPage(api: widget.api)),
              _sep(),
              // 事故上报是唯一该用 danger 的入口:人先安全
              _navRow('事故上报', '人先安全;在途订单自动处理',
                  () => RiderAccidentPage(api: widget.api),
                  danger: true),
              _sep(),
              _navRow('装备申领', '头盔 / 保温餐箱 / 雨衣',
                  () => RiderGearPage(api: widget.api)),
            ]),
          ),
          const SizedBox(height: 18),
          const SzSectionTitle('账目与账户'),
          const SizedBox(height: 9),
          SzCard(
            padding: EdgeInsets.zero,
            child: Column(children: [
              _navRow('收款账户', '提现打款到这里;未登记不能提现',
                  () => PayoutAccountPage(api: widget.api)),
              _sep(),
              _navRow('配送异常与申诉', '上报记录;判骑手责的裁决 72 小时内可申诉',
                  () => RiderIssuesPage(api: widget.api)),
              _sep(),
              _navRow('联系平台客服', '提现、账目、认证有疑问?直接找平台',
                  () => SupportPage(api: widget.api)),
            ]),
          ),
          const SizedBox(height: 18),
          const PledgeCard(
            title: '配送费 100% 归骑手',
            body: '平台分文不取,提现零手续费,每一分都看得见。\n'
                '配送收入属劳务报酬,请依法申报个税;'
                '平台接入灵活用工代发后将自动完税并另行通知。',
          ),
          const SizedBox(height: 8),
          // 商店审核三件套:协议全文 / 退出登录 / 注销账号
          AccountLegalSection(
            api: widget.api,
            onLoggedOut: (ctx) {
              Navigator.of(ctx).popUntil((route) => route.isFirst);
              ApiClient.onUnauthorized?.call(); // AuthGate 切回登录页
            },
            onDeleted: (ctx) {
              Navigator.of(ctx).popUntil((route) => route.isFirst);
              ApiClient.onUnauthorized?.call();
            },
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
