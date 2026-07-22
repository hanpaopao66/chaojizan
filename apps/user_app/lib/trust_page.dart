import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import 'five_percent.dart';

/// 账目透明页:三原则实数 + 社区见证节点 + 近 30 天资金去向。
///
/// 数据来自公开接口 /stats/overview,与公开账本同源——
/// 页面上的每个数字,用户都可以自己跑一个见证节点去复核。
class TrustPage extends StatefulWidget {
  const TrustPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<TrustPage> createState() => _TrustPageState();
}

class _TrustPageState extends State<TrustPage> {
  Map<String, dynamic>? _stats;
  String? _error;
  WitnessResult? _witness;
  bool _witnessOn = false;
  bool _verifying = true;

  @override
  void initState() {
    super.initState();
    Analytics.track('view_trust');
    _load();
    _verify();
  }

  Future<void> _load() async {
    try {
      final stats = await widget.api.statsOverview();
      if (mounted) setState(() => _stats = stats);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  /// 本机独立核验:装了 App 的每台手机都是潜在的见证节点
  Future<void> _verify() async {
    final on = await PhoneWitness.enabled();
    if (mounted) setState(() => _witnessOn = on);
    try {
      final r = await PhoneWitness(widget.api).runCycle(heartbeat: on);
      if (mounted) {
        setState(() {
          _witness = r;
          _verifying = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _verifying = false);
    }
  }

  Future<void> _becomeWitness() async {
    await PhoneWitness.setEnabled(true,
        name: '${widget.api.userName ?? ''}的手机'.replaceFirst(RegExp(r'^的'), ''));
    setState(() => _witnessOn = true);
    final r = await PhoneWitness(widget.api).runCycle(heartbeat: true);
    if (mounted) {
      setState(() => _witness = r);
      _load(); // 节点数 +1 立即可见
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('你的手机已加入见证网络(匿名),感谢监督')));
    }
  }

  String _yuan(num cents) => '¥${(cents / 100).toStringAsFixed(0)}';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = _stats;
    return Scaffold(
      appBar: AppBar(title: const Text('账目透明')),
      body: _error != null
          ? EmptyState(
              icon: Icons.cloud_off_outlined,
              text: '暂时打不开,下拉重试\n$_error',
              actionLabel: '重试',
              onAction: _load)
          : s == null
              ? const Center(child: CircularProgressIndicator())
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      // 三原则:实数,不是口号(5% 卡可点开看「5% 去哪了」)
                      Row(
                        children: [
                          _principle(theme, '5%', '商家佣金上限', kBrandOrange,
                              onTap: () => showFivePercentSheet(context)),
                          const SizedBox(width: 10),
                          _principle(theme, '100%', '配送费归骑手', kMoneyGreen),
                          const SizedBox(width: 10),
                          _principle(theme, '2%', '团购核销费率', kPromoAmber),
                        ],
                      ),
                      const SizedBox(height: 16),
                      _witnessCard(theme, s),
                      const SizedBox(height: 16),
                      _flowCard(theme, s),
                      const SizedBox(height: 16),
                      Text(
                        '以上数字与平台公开账本同源。账本按日生成哈希锚点首尾相链,'
                        '改历史任何一分钱都会断链;任何人都可以运行见证节点独立复核。',
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.outline, height: 1.6),
                      ),
                    ],
                  ),
                ),
    );
  }

  Widget _principle(ThemeData theme, String number, String label, Color color,
      {VoidCallback? onTap}) {
    return Expanded(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 14),
          decoration: BoxDecoration(
            color: color.withValues(alpha: .08),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: color.withValues(alpha: .22)),
          ),
          child: Column(
            children: [
              Text(number,
                  style: TextStyle(
                      fontSize: 22, fontWeight: FontWeight.w800, color: color)),
              const SizedBox(height: 2),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Text(label,
                      style: theme.textTheme.bodySmall?.copyWith(
                          fontSize: 11, color: theme.colorScheme.outline)),
                  if (onTap != null) ...[
                    const SizedBox(width: 2),
                    Icon(Icons.help_outline,
                        size: 11, color: theme.colorScheme.outline),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _witnessCard(ThemeData theme, Map<String, dynamic> s) {
    final nodes = (s['nodes'] as Map?) ?? const {};
    final chain = (s['chain'] as Map?) ?? const {};
    final online = nodes['online'] as int? ?? 0;
    final hash = chain['latest_hash'] as String? ?? '';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.verified_user_outlined,
                    size: 18, color: kMoneyGreen),
                const SizedBox(width: 8),
                Text('社区见证节点', style: theme.textTheme.titleSmall),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text('$online',
                    style: const TextStyle(
                        fontSize: 34,
                        fontWeight: FontWeight.w800,
                        color: kMoneyGreen,
                        height: 1)),
                const SizedBox(width: 8),
                Padding(
                  padding: const EdgeInsets.only(bottom: 3),
                  child: Text(
                      online > 0 ? '个节点正在独立监督平台账目' : '成为第一个见证者',
                      style: theme.textTheme.bodySmall),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '见证节点由社区志愿运行,持续复算平台账本的哈希链与佣金恒等式,'
              '平台改一分钱历史都会被公开示警。',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline, height: 1.5),
            ),
            if (hash.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('最新锚点 ${chain['latest_day']}',
                  style: theme.textTheme.bodySmall),
              Text(hash,
                  style: TextStyle(
                      fontFamily: 'monospace',
                      fontSize: 10.5,
                      color: theme.colorScheme.outline)),
            ],
            const SizedBox(height: 12),
            // 本机核验:不信平台,信你自己手机算出来的哈希
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: kMoneyGreen.withValues(alpha: .07),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(
                          _verifying
                              ? Icons.sync
                              : (_witness?.ok ?? false)
                                  ? Icons.verified_rounded
                                  : Icons.error_outline_rounded,
                          size: 16,
                          color: _verifying
                              ? theme.colorScheme.outline
                              : (_witness?.ok ?? false)
                                  ? kMoneyGreen
                                  : theme.colorScheme.error),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          _verifying
                              ? '你的手机正在独立核验账本…'
                              : _witness == null
                                  ? '本机核验暂不可用(网络原因),下次进入自动重试'
                                  : _witness!.ok
                                      ? '你的手机已独立核验:${_witness!.daysVerified} 天账本全部一致'
                                      : '本机核验发现异常,已可公开质询',
                          style: theme.textTheme.bodySmall
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                      ),
                    ],
                  ),
                  if (!_verifying && _witness != null && !_witnessOn) ...[
                    const SizedBox(height: 8),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.tonal(
                        onPressed: _becomeWitness,
                        child: const Text('把核验结果匿名上报,成为见证节点'),
                      ),
                    ),
                  ],
                  if (_witnessOn && !_verifying) ...[
                    const SizedBox(height: 4),
                    Text('已匿名上报 · 你的手机在见证网络里(不含任何账号信息)',
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.outline)),
                  ],
                ],
              ),
            ),
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                icon: const Icon(Icons.open_in_new, size: 16),
                label: const Text('查看节点网络 / 运行我的节点'),
                onPressed: () => launchUrl(
                    Uri.parse('${widget.api.baseUrl}/nodes'),
                    mode: LaunchMode.externalApplication),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _flowCard(ThemeData theme, Map<String, dynamic> s) {
    final trend = (s['trend'] as List?)?.cast<Map>() ?? const [];
    num merchant = 0, rider = 0, platform = 0;
    for (final t in trend) {
      merchant += (t['merchant_net'] as num? ?? 0);
      rider += (t['rider_amount'] as num? ?? 0);
      platform += (t['commission'] as num? ?? 0) + (t['voucher_fee'] as num? ?? 0);
    }
    final total = merchant + rider + platform;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('近 30 天 · 每一分钱的去向', style: theme.textTheme.titleSmall),
            const SizedBox(height: 12),
            if (total <= 0)
              Text('平台刚起步,暂无足够数据', style: theme.textTheme.bodySmall)
            else ...[
              ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: SizedBox(
                  height: 14,
                  child: Row(
                    children: [
                      Expanded(
                          flex: (merchant * 1000 ~/ total).clamp(1, 1000),
                          child: const ColoredBox(color: kMoneyGreen)),
                      Expanded(
                          flex: (rider * 1000 ~/ total).clamp(1, 1000),
                          child: const ColoredBox(color: Color(0xFF4DA3FF))),
                      Expanded(
                          flex: (platform * 1000 ~/ total).clamp(1, 1000),
                          child: const ColoredBox(color: kBrandOrange)),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 10),
              _legend(theme, kMoneyGreen, '商家净得', _yuan(merchant), total, merchant),
              _legend(theme, const Color(0xFF4DA3FF), '骑手所得', _yuan(rider), total, rider),
              _legend(theme, kBrandOrange, '平台留存', _yuan(platform), total, platform),
            ],
          ],
        ),
      ),
    );
  }

  Widget _legend(ThemeData theme, Color color, String label, String amount,
      num total, num part) {
    final pct = total > 0 ? (part * 100 / total).toStringAsFixed(1) : '0';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Container(
              width: 10,
              height: 10,
              decoration:
                  BoxDecoration(color: color, borderRadius: BorderRadius.circular(3))),
          const SizedBox(width: 8),
          Text(label, style: theme.textTheme.bodySmall),
          const Spacer(),
          Text('$amount · $pct%',
              style: theme.textTheme.bodySmall
                  ?.copyWith(fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}
