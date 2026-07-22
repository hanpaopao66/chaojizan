import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:share_plus/share_plus.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:superz_shared/superz_shared.dart';

/// 团购页(从金刚区进入):在售代金券列表。
class DealsPage extends StatelessWidget {
  const DealsPage({super.key, required this.api});

  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('超值团购')),
      body: VoucherListView(api: api),
    );
  }
}

/// 在售代金券列表。
/// 平台姿态与外卖一致:核销才收 2% 服务费,券没用掉平台一分不赚、随时全额退。
class VoucherListView extends StatefulWidget {
  const VoucherListView({super.key, required this.api});

  final ApiClient api;

  @override
  State<VoucherListView> createState() => _VoucherListViewState();
}

class _VoucherListViewState extends State<VoucherListView> {
  List<VoucherDeal>? _deals;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final deals = await widget.api.voucherDeals();
      if (mounted) {
        setState(() {
          _deals = deals;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    }
  }

  Future<void> _buy(VoucherDeal deal) async {
    final confirmed = await showModalBottomSheet<bool>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(deal.merchantName,
                  style: Theme.of(context).textTheme.bodySmall),
              Text(deal.title,
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(yuan(deal.sellPriceCents),
                      style: Theme.of(context)
                          .textTheme
                          .headlineMedium
                          ?.copyWith(
                              color: Theme.of(context).colorScheme.primary,
                              fontWeight: FontWeight.bold)),
                  const SizedBox(width: 8),
                  Padding(
                    padding: const EdgeInsets.only(bottom: 4),
                    child: Text('门店价 ${yuan(deal.faceValueCents)}',
                        style: const TextStyle(
                            decoration: TextDecoration.lineThrough)),
                  ),
                ],
              ),
              if (deal.description.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(deal.description),
              ],
              const SizedBox(height: 6),
              Text(
                  '购买后 ${deal.validDays} 天内有效 · 未使用随时全额退 · '
                  '每人限购 ${deal.perUserLimit} 张',
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 16),
              Row(
                children: [
                  OutlinedButton.icon(
                    icon: const Icon(Icons.share_outlined, size: 18),
                    label: const Text('分享'),
                    onPressed: () {
                      Analytics.track(
                          'share', {'kind': 'voucher', 'id': deal.id});
                      SharePlus.instance.share(ShareParams(
                          text: '「${deal.merchantName}」${deal.title},'
                            '${yuan(deal.sellPriceCents)} 抵 ${yuan(deal.faceValueCents)},'
                            '未使用随时全额退。超级赞团购只收商家 2% 服务费。'
                          '下载:https://aikas.com.cn'));
                    },
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton(
                      onPressed: () => Navigator.pop(sheetContext, true),
                      child: Text('立即抢购 ${yuan(deal.sellPriceCents)}'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      final ticket = await widget.api.purchaseVoucher(deal.id);
      // 模拟支付(微信支付联调后换成拉起收银台)
      await widget.api.payVoucherMock(ticket.purchaseNo);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: const Text('抢购成功!券已放入「我的-我的券包」'),
        action: SnackBarAction(
            label: '去查看',
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => MyVouchersPage(api: widget.api)))),
      ));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (_error != null) {
      return Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
        Text(_error!),
        TextButton(onPressed: _load, child: const Text('重试')),
      ]));
    }
    final deals = _deals;
    if (deals == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        children: [
          // 不放口号横幅;用户需要知道的规则用一行淡字说清(可退才是真话语权)
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
            child: Text('未使用随时全额退 · 过期前有提醒',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline)),
          ),
          if (deals.isEmpty)
            const Padding(
              padding: EdgeInsets.all(48),
              child: Center(child: Text('商家们还没上团购,快去点外卖吧')),
            ),
          for (final (i, deal) in deals.indexed)
            FadeSlideIn(
              index: i,
              child: Card(
              margin: const EdgeInsets.symmetric(vertical: 6),
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () => _buy(deal),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Row(
                    children: [
                      Container(
                        width: 64,
                        height: 64,
                        decoration: BoxDecoration(
                          color: theme.colorScheme.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        clipBehavior: Clip.antiAlias,
                        child: deal.merchantLogo.isEmpty
                            ? Icon(Icons.local_activity,
                                color: theme.colorScheme.outline)
                            : Image.network(
                                widget.api.resolveUrl(deal.merchantLogo),
                                fit: BoxFit.cover,
                                errorBuilder: (_, __, ___) =>
                                    Icon(Icons.local_activity,
                                        color: theme.colorScheme.outline),
                              ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(deal.merchantName,
                                style: theme.textTheme.bodySmall),
                            Text(deal.title,
                                style: theme.textTheme.titleMedium
                                    ?.copyWith(fontWeight: FontWeight.w600)),
                            const SizedBox(height: 4),
                            Row(
                              children: [
                                Text(yuan(deal.sellPriceCents),
                                    style: TextStyle(
                                        color: theme.colorScheme.primary,
                                        fontWeight: FontWeight.bold,
                                        fontSize: 16)),
                                const SizedBox(width: 6),
                                Text(yuan(deal.faceValueCents),
                                    style: const TextStyle(
                                        fontSize: 12,
                                        decoration:
                                            TextDecoration.lineThrough)),
                                const SizedBox(width: 6),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 5, vertical: 1),
                                  decoration: BoxDecoration(
                                    color: Colors.orange
                                        .withValues(alpha: 0.15),
                                    borderRadius: BorderRadius.circular(4),
                                  ),
                                  child: Text(deal.discountLabel,
                                      style: const TextStyle(
                                          fontSize: 11,
                                          color: Colors.orange,
                                          fontWeight: FontWeight.bold)),
                                ),
                                const Spacer(),
                                Text('已售 ${deal.soldCount}',
                                    style: theme.textTheme.bodySmall),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            ),
        ],
      ),
    );
  }
}

/// 我的券包:券码展示 + 未使用退款。
class MyVouchersPage extends StatefulWidget {
  const MyVouchersPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<MyVouchersPage> createState() => _MyVouchersPageState();
}

class _MyVouchersPageState extends State<MyVouchersPage> {
  List<VoucherTicket>? _tickets;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final tickets = await widget.api.myVoucherTickets();
      if (mounted) setState(() => _tickets = tickets);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _showTicket(VoucherTicket t) async {
    await showDialog<void>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: Text(t.title),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(t.merchantName,
                style: Theme.of(context).textTheme.bodySmall),
            if (t.merchantAddress.isNotEmpty)
              Text(t.merchantAddress,
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.outline)),
            const SizedBox(height: 12),
            if (t.usable) ...[
              const Text('到店请商家扫码,或出示数字券码'),
              const SizedBox(height: 12),
              // 二维码内容就是券码本身,商家端扫码核销
              Container(
                padding: const EdgeInsets.all(8),
                color: Colors.white,
                child: QrImageView(
                  data: t.code,
                  size: 180,
                ),
              ),
              const SizedBox(height: 12),
              InkWell(
                onTap: () {
                  Clipboard.setData(ClipboardData(text: t.code));
                  ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('券码已复制')));
                },
                child: Text(
                  t.prettyCode,
                  style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 2),
                ),
              ),
            ] else
              Text(t.statusLabel,
                  style: Theme.of(context).textTheme.titleMedium),
          ],
        ),
        actions: [
          if (t.usable && t.merchantLat != null)
            TextButton.icon(
              icon: const Icon(Icons.near_me_outlined, size: 18),
              label: const Text('到店导航'),
              onPressed: () {
                // geo: 通用意图,Android 会列出已装地图 App
                launchUrl(Uri.parse(
                    'geo:${t.merchantLat},${t.merchantLng}'
                    '?q=${Uri.encodeComponent(t.merchantAddress.isEmpty ? t.merchantName : t.merchantAddress)}'));
              },
            ),
          if (t.usable)
            TextButton(
              onPressed: () async {
                Navigator.pop(dialogContext);
                try {
                  await widget.api.refundVoucher(t.purchaseNo);
                  if (!mounted) return;
                  ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('已退款,款项原路返回')));
                  _load();
                } catch (e) {
                  if (!mounted) return;
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text('$e')));
                }
              },
              child: Text('申请退款',
                  style: TextStyle(
                      color: Theme.of(context).colorScheme.error)),
            ),
          FilledButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('好的')),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final tickets = _tickets;
    return Scaffold(
      appBar: AppBar(title: const Text('我的券包')),
      body: tickets == null
          ? const Center(child: CircularProgressIndicator())
          : tickets.isEmpty
              ? const Center(child: Text('还没有券,去「团购」逛逛'))
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView.separated(
                    padding: const EdgeInsets.all(12),
                    itemCount: tickets.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (context, i) {
                      final t = tickets[i];
                      return Card(
                        child: ListTile(
                          leading: Icon(Icons.confirmation_number_outlined,
                              color: t.usable
                                  ? Theme.of(context).colorScheme.primary
                                  : Theme.of(context).colorScheme.outline),
                          title: Text(t.title),
                          subtitle: Text(
                              '${t.merchantName} · ${yuan(t.sellPriceCents)} 购'),
                          trailing: Chip(
                              label: Text(t.statusLabel),
                              visualDensity: VisualDensity.compact),
                          onTap: () => _showTicket(t),
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}
