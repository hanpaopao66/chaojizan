import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'hotel_pages.dart';

/// 住宿下单页:日期/间数/入住人 → 逐晚价格明细 → 支付。
/// 不复用外卖结算页(配送费/地址簿语义全不适用)。全程无营销横幅。
class StayCheckoutPage extends StatefulWidget {
  const StayCheckoutPage({
    super.key,
    required this.api,
    required this.hotel,
    required this.quote,
    required this.range,
  });

  final ApiClient api;
  final HotelDetail hotel;
  final RoomQuote quote;
  final StayRange range;

  @override
  State<StayCheckoutPage> createState() => _StayCheckoutPageState();
}

class _StayCheckoutPageState extends State<StayCheckoutPage> {
  late final _guestName =
      TextEditingController(text: widget.api.userName ?? '');
  final _guestPhone = TextEditingController();
  int _roomsQty = 1;
  String _arrival = '';
  bool _busy = false;

  static const _arrivalOptions = [
    '', '14:00-18:00', '18:00-22:00', '22:00 以后(请保留房间)'
  ];

  int get _maxQty {
    final left = widget.quote.leftQty;
    return left == null ? 5 : left.clamp(1, 5);
  }

  int get _totalCents => (widget.quote.totalCents ?? 0) * _roomsQty;

  Future<void> _submit() async {
    final phone = _guestPhone.text.trim();
    if (_guestName.text.trim().isEmpty || !RegExp(r'^1\d{10}$').hasMatch(phone)) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请填写入住人姓名和 11 位手机号')));
      return;
    }
    setState(() => _busy = true);
    try {
      final order = await widget.api.createStayOrder(
        roomTypeId: widget.quote.roomType.id,
        checkinDate: widget.range.checkinStr,
        checkoutDate: widget.range.checkoutStr,
        roomsQty: _roomsQty,
        guestName: _guestName.text.trim(),
        guestPhone: phone,
        arrivalNote: _arrival,
      );
      // 支付:商户参数未配置时走模拟通道(与外卖/团购同语义)
      final paid = await widget.api.payStayMock(order.orderNo);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(
          builder: (_) => _PaidPage(order: paid)));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final quote = widget.quote;
    return Scaffold(
      appBar: AppBar(title: const Text('确认订单')),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        Card(
          child: ListTile(
            title: Text('${widget.hotel.name} · ${quote.roomType.name}'),
            subtitle: Text('${widget.range.label}\n'
                '${widget.hotel.checkinFrom} 后入住,'
                '${widget.hotel.checkoutUntil} 前退房'),
            isThreeLine: true,
          ),
        ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(children: [
              Row(children: [
                const Text('间数'),
                const Spacer(),
                IconButton(
                    tooltip: '减少',
                    icon: const Icon(Icons.remove_circle_outline),
                    onPressed: _roomsQty > 1
                        ? () => setState(() => _roomsQty--)
                        : null),
                Text('$_roomsQty'),
                IconButton(
                    tooltip: '增加',
                    icon: const Icon(Icons.add_circle_outline),
                    onPressed: _roomsQty < _maxQty
                        ? () => setState(() => _roomsQty++)
                        : null),
              ]),
              TextField(
                  controller: _guestName,
                  decoration: const InputDecoration(
                      labelText: '入住人姓名 *',
                      helperText: '办理入住时与前台核对,不需要与账号一致',
                      border: OutlineInputBorder())),
              const SizedBox(height: 12),
              TextField(
                  controller: _guestPhone,
                  keyboardType: TextInputType.phone,
                  decoration: const InputDecoration(
                      labelText: '入住人手机号 *', border: OutlineInputBorder())),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: _arrival,
                decoration: const InputDecoration(
                    labelText: '预计到店时间(选填)', border: OutlineInputBorder()),
                items: [
                  for (final t in _arrivalOptions)
                    DropdownMenuItem(
                        value: t, child: Text(t.isEmpty ? '不填' : t)),
                ],
                onChanged: (v) => setState(() => _arrival = v ?? ''),
              ),
            ]),
          ),
        ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('价格明细', style: theme.textTheme.titleSmall),
              const SizedBox(height: 8),
              for (final night in quote.nightly)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(children: [
                    Text(night.date),
                    const Spacer(),
                    Text(
                        '${yuan(night.priceCents)}${_roomsQty > 1 ? ' × $_roomsQty' : ''}'),
                  ]),
                ),
              const Divider(),
              Row(children: [
                const Text('合计',
                    style: TextStyle(fontWeight: FontWeight.bold)),
                const Spacer(),
                Text(yuan(_totalCents),
                    style: theme.textTheme.titleMedium?.copyWith(
                        color: theme.colorScheme.primary,
                        fontWeight: FontWeight.bold)),
              ]),
            ]),
          ),
        ),
        Card(
          color: theme.colorScheme.primary.withValues(alpha: 0.05),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              const Icon(Icons.info_outline, size: 18),
              const SizedBox(width: 8),
              Expanded(child: Text(quote.cancelPolicyText)),
            ]),
          ),
        ),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: _busy ? null : _submit,
          style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(vertical: 14)),
          child: Text(_busy ? '提交中…' : '提交订单并支付 ${yuan(_totalCents)}'),
        ),
        const SizedBox(height: 8),
        Center(
            child: Text('支付后商家确认才算预订成功,未确认前可随时全额取消',
                style: theme.textTheme.bodySmall)),
      ]),
    );
  }
}

/// 支付成功页:待商家确认
class _PaidPage extends StatelessWidget {
  const _PaidPage({required this.order});

  final StayOrder order;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('支付成功')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.check_circle_outline,
                size: 64, color: Theme.of(context).sz.earn),
            const SizedBox(height: 16),
            Text('已支付 ${yuan(order.totalCents)}',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 8),
            const Text('等待商家确认,确认后会第一时间通知你\n入住凭证见「订单」页',
                textAlign: TextAlign.center),
            const SizedBox(height: 24),
            FilledButton(
                onPressed: () =>
                    Navigator.of(context).popUntil((r) => r.isFirst),
                child: const Text('好的')),
          ]),
        ),
      ),
    );
  }
}
