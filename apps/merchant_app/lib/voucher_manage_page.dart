import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:superz_shared/superz_shared.dart';

/// 团购券管理:发布 / 上下架 / 销量一览。核销服务费 2%,只在核销时收。
class VoucherManagePage extends StatefulWidget {
  const VoucherManagePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<VoucherManagePage> createState() => _VoucherManagePageState();
}

class _VoucherManagePageState extends State<VoucherManagePage> {
  List<VoucherDeal>? _deals;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final deals = await widget.api.myVoucherDeals();
      if (mounted) setState(() => _deals = deals);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _create() async {
    final title = TextEditingController();
    final sell = TextEditingController();
    final face = TextEditingController();
    final count = TextEditingController(text: '100');
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('发布代金券'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
                controller: title,
                decoration: const InputDecoration(
                    labelText: '标题(如 50元代金券)', isDense: true)),
            Row(children: [
              Expanded(
                child: TextField(
                    controller: sell,
                    keyboardType: const TextInputType.numberWithOptions(
                        decimal: true),
                    decoration: const InputDecoration(
                        labelText: '售价(元)', isDense: true)),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                    controller: face,
                    keyboardType: const TextInputType.numberWithOptions(
                        decimal: true),
                    decoration: const InputDecoration(
                        labelText: '面值(元)', isDense: true)),
              ),
            ]),
            TextField(
                controller: count,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: '发行数量', isDense: true)),
            const SizedBox(height: 8),
            const Text('用户核销后到账「售价 - 2% 服务费」;券未被使用平台分文不收',
                style: TextStyle(fontSize: 12)),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('发布')),
        ],
      ),
    );
    if (saved != true || !mounted) return;
    final sellCents = ((double.tryParse(sell.text) ?? 0) * 100).round();
    final faceCents = ((double.tryParse(face.text) ?? 0) * 100).round();
    final total = int.tryParse(count.text) ?? 0;
    if (title.text.trim().length < 2 ||
        sellCents <= 0 ||
        faceCents <= sellCents ||
        total <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请检查:标题至少 2 字,售价 < 面值,数量 > 0')));
      return;
    }
    try {
      await widget.api.createVoucher({
        'title': title.text.trim(),
        'sell_price_cents': sellCents,
        'face_value_cents': faceCents,
        'total_count': total,
      });
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final deals = _deals;
    return Scaffold(
      appBar: AppBar(title: const Text('团购券管理')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _create,
        icon: const Icon(Icons.add),
        label: const Text('发布'),
      ),
      body: deals == null
          ? const Center(child: CircularProgressIndicator())
          : deals.isEmpty
              ? const Center(
                  child: Text('还没发布团购券\n低价引流,核销才收 2% 服务费',
                      textAlign: TextAlign.center))
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView.separated(
                    padding: const EdgeInsets.all(12),
                    itemCount: deals.length,
                    separatorBuilder: (_, __) => const SizedBox(height: 8),
                    itemBuilder: (context, i) {
                      final d = deals[i];
                      return Card(
                        child: ListTile(
                          title: Text(d.title),
                          subtitle: Text(
                              '${yuan(d.sellPriceCents)} 售 / 面值 ${yuan(d.faceValueCents)}'
                              ' · 已售 ${d.soldCount} · 剩 ${d.totalCount}'),
                          trailing: Switch(
                            value: d.isActive,
                            onChanged: (v) async {
                              try {
                                await widget.api
                                    .updateVoucher(d.id, {'is_active': v});
                                _load();
                              } catch (e) {
                                if (!context.mounted) return;
                                ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(content: Text('$e')));
                              }
                            },
                          ),
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}

/// 输码核销:顾客到店出示券码,商家输入 → 服务端核验并入账。
class VoucherRedeemPage extends StatefulWidget {
  const VoucherRedeemPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<VoucherRedeemPage> createState() => _VoucherRedeemPageState();
}

class _VoucherRedeemPageState extends State<VoucherRedeemPage> {
  final _code = TextEditingController();
  bool _busy = false;

  bool get _canScan => !kIsWeb && (Platform.isAndroid || Platform.isIOS);

  Future<void> _redeem([String? scanned]) async {
    final code = (scanned ?? _code.text).replaceAll(' ', '');
    if (code.length < 6) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请输入完整券码')));
      return;
    }
    setState(() => _busy = true);
    try {
      final t = await widget.api.redeemVoucher(code);
      if (!mounted) return;
      _code.clear();
      await showDialog<void>(
        context: context,
        builder: (context) => AlertDialog(
          icon: const PopIn(
              child:
                  Icon(Icons.check_circle, color: kMoneyGreen, size: 52)),
          title: const Text('核销成功'),
          content: Text(
              '${t.title}\n面值 ${yuan(t.faceValueCents)}\n\n'
              '本单应收:${yuan(t.netCents)}'
              '(售价 ${yuan(t.sellPriceCents)} - 2% 服务费 ${yuan(t.commissionCents)})'),
          actions: [
            FilledButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('好的')),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 扫顾客的券码二维码(二维码内容即券码);相机不可用时退回手动输码
  Future<void> _scan() async {
    final code = await Navigator.of(context).push<String>(
        MaterialPageRoute(builder: (_) => const _ScanPage()));
    if (code != null && mounted) {
      _code.text = code;
      await _redeem(code);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('团购核销')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('扫顾客的券码二维码,或手动输入数字券码。核销即入账,不可撤销。'),
            const SizedBox(height: 16),
            if (_canScan) ...[
              FilledButton.icon(
                icon: const Icon(Icons.qr_code_scanner),
                label: const Text('扫码核销'),
                onPressed: _busy ? null : _scan,
              ),
              const SizedBox(height: 24),
              const Row(children: [
                Expanded(child: Divider()),
                Padding(
                    padding: EdgeInsets.symmetric(horizontal: 12),
                    child: Text('或手动输码')),
                Expanded(child: Divider()),
              ]),
              const SizedBox(height: 8),
            ],
            TextField(
              controller: _code,
              keyboardType: TextInputType.number,
              style: const TextStyle(fontSize: 24, letterSpacing: 2),
              decoration: const InputDecoration(
                  labelText: '12 位券码', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 16),
            FilledButton.tonal(
              onPressed: _busy ? null : _redeem,
              child: Text(_busy ? '核销中…' : '核销'),
            ),
          ],
        ),
      ),
    );
  }
}

/// 扫码页:识别到第一个二维码就返回其内容。
class _ScanPage extends StatefulWidget {
  const _ScanPage();

  @override
  State<_ScanPage> createState() => _ScanPageState();
}

class _ScanPageState extends State<_ScanPage> {
  bool _returned = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('对准顾客的券码二维码')),
      body: MobileScanner(
        onDetect: (capture) {
          if (_returned) return;
          final value = capture.barcodes.firstOrNull?.rawValue;
          if (value != null && value.trim().isNotEmpty) {
            _returned = true;
            Navigator.of(context).pop(value.trim());
          }
        },
      ),
    );
  }
}
