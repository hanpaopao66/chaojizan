import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'address_pages.dart';
import 'identity_page.dart';
import 'main.dart' show OrderDetailPage;
import 'payment_service.dart';

/// 结算确认页(替代原来的确认弹窗):
/// 地址卡 + 送达时间(尽快/预约) + 商品明细 + 餐具/备注 + 透明分账预览 + 提交支付。
class CheckoutPage extends StatefulWidget {
  const CheckoutPage({
    super.key,
    required this.api,
    required this.merchant,
    required this.cart,
    this.groupCode = '',
  });

  final ApiClient api;
  final Merchant merchant;
  final List<CartLine> cart;
  final String groupCode; // 拼单码:发起人结算时带上,服务端原子关车

  @override
  State<CheckoutPage> createState() => _CheckoutPageState();
}

class _CheckoutPageState extends State<CheckoutPage> {
  bool _pickup = false; // 到店自取:免配送费,凭取餐码取餐
  int _tipCents = 0; // 小费:100% 归骑手,平台不抽不计佣
  Address? _address;
  bool _loadingAddress = true;
  int _tableware = 1;
  final _remark = TextEditingController();
  bool _submitting = false;
  DateTime? _scheduledAt; // null = 尽快送达
  // 平台券(超时安抚券等,平台承担):自动选可用的最大面额,可点掉
  List<Map<String, dynamic>> _coupons = [];
  int? _couponId;

  @override
  void initState() {
    super.initState();
    _loadDefaultAddress();
    _loadCoupons();
    Analytics.track('checkout_view', {'merchant_id': widget.merchant.id});
  }

  Future<void> _loadCoupons() async {
    try {
      final list = await widget.api.myCoupons();
      final usable = list
          .cast<Map<String, dynamic>>()
          .where((c) => c['usable'] == true)
          // 店铺券(funder=merchant)只在发券商家可用,平台券不限店
          .where((c) =>
              c['funder'] != 'merchant' ||
              c['merchant_id'] == widget.merchant.id)
          .toList()
        ..sort((a, b) =>
            (b['amount_cents'] as int).compareTo(a['amount_cents'] as int));
      if (mounted) {
        setState(() {
          _coupons = usable;
          _couponId = usable.firstOrNull?['id'] as int?;
        });
      }
    } catch (_) {}
  }

  Future<void> _loadDefaultAddress() async {
    try {
      final list = await widget.api.addresses();
      if (mounted) {
        setState(() {
          _address = list.where((a) => a.isDefault).firstOrNull ??
              list.firstOrNull;
          _loadingAddress = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loadingAddress = false);
    }
  }

  Future<void> _pickAddress() async {
    final picked = await Navigator.of(context).push<Address>(MaterialPageRoute(
        builder: (_) => AddressBookPage(api: widget.api, selectMode: true)));
    if (picked != null && mounted) setState(() => _address = picked);
  }

  int get _foodCents => widget.cart
      .fold(0, (sum, line) => sum + line.unitCents * line.quantity);

  /// 满减(与后端同规则:取满足门槛的最大一档)。服务端是最终口径,这里仅预估展示
  int get _discountCents {
    var off = 0;
    final rules = [...widget.merchant.promoRules]
      ..sort((a, b) => a.thresholdCents.compareTo(b.thresholdCents));
    for (final r in rules) {
      if (_foodCents >= r.thresholdCents) off = r.offCents;
    }
    return off;
  }

  /// 满赠(与后端同规则:取满足门槛的最高一档)。库存不足时服务端会自动跳过
  GiftRule? get _giftRule {
    GiftRule? hit;
    final rules = [...widget.merchant.giftRules]
      ..sort((a, b) => a.thresholdCents.compareTo(b.thresholdCents));
    for (final r in rules) {
      if (_foodCents >= r.thresholdCents) hit = r;
    }
    return hit;
  }

  bool get _belowMinOrder => _foodCents < widget.merchant.minOrderCents;

  /// 配送费与后端同公式(pricing.py):2km 内 ¥3,每 km +¥1,封顶 ¥10
  int? get _feeCents {
    if (_pickup) return 0; // 自取免配送费
    final a = _address;
    if (a == null) return null;
    final dist = distanceMeters(
        widget.merchant.lat, widget.merchant.lng, a.lat, a.lng);
    final extraKm = ((dist / 1000 - 2.0).clamp(0, double.infinity)).ceil();
    final fee = 300 + extraKm * 100;
    return fee > 1000 ? 1000 : fee;
  }

  /// 已选券的抵扣额(不超过 菜品+打包-满减)
  int get _selectedCouponOff {
    final c =
        _coupons.where((c) => c['id'] == _couponId).firstOrNull;
    if (c == null) return 0;
    final cap = _foodCents + widget.merchant.packingFeeCents - _discountCents;
    final off = c['amount_cents'] as int;
    return off > cap ? (cap > 0 ? cap : 0) : off;
  }

  int? get _etaMin {
    final a = _address;
    if (_pickup || a == null) return null;
    return etaMinutes(distanceMeters(
        widget.merchant.lat, widget.merchant.lng, a.lat, a.lng));
  }

  Future<void> _submit() async {
    final address = _address;
    if (!_pickup && address == null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请先选择收货地址')));
      return;
    }
    setState(() => _submitting = true);
    try {
      final remark = [
        if (_remark.text.trim().isNotEmpty) _remark.text.trim(),
        '餐具 $_tableware 份',
      ].join(';');
      final order = await widget.api.createOrder(
        merchantId: widget.merchant.id,
        items: widget.cart.map((l) => l.toOrderItem()).toList(),
        address: _pickup ? null : address,
        pickup: _pickup,
        remark: remark,
        scheduledAt: _scheduledAt,
        tipCents: _pickup ? 0 : _tipCents,
        couponId: _couponId,
        groupCode: widget.groupCode,
      );
      if (!mounted) return;
      final paid = await payOrder(widget.api, order, context);
      if (!mounted) return;
      // 下单成功:清掉该店云端购物车(已成单,不该再恢复)
      widget.api.putCart(widget.merchant.id, const []).catchError((_) {});
      // 支付完成:栈收敛为 首页 → 订单详情
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(
            builder: (_) =>
                OrderDetailPage(api: widget.api, orderNo: paid.orderNo)),
        (route) => route.isFirst,
      );
    } catch (e) {
      if (!mounted) return;
      final msg = e.toString();
      // 酒类需实名:直接给去认证的入口,别让用户自己找
      if (msg.contains('实名认证')) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(msg),
          duration: const Duration(seconds: 6),
          action: SnackBarAction(
            label: '去实名',
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => IdentityPage(api: widget.api))),
          ),
        ));
      } else {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(msg)));
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  /// 预约送达时间选择:今天/明天 + 时刻;至少提前 30 分钟(与服务端一致)
  Future<void> _pickScheduledTime() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      initialDate: now,
      firstDate: now,
      lastDate: now.add(const Duration(days: 2)),
      helpText: '选择送达日期',
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(now.add(const Duration(hours: 1))),
      helpText: '选择送达时刻',
    );
    if (time == null || !mounted) return;
    final picked =
        DateTime(date.year, date.month, date.day, time.hour, time.minute);
    if (picked.isBefore(now.add(const Duration(minutes: 30)))) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('预约时间至少要在 30 分钟之后')));
      return;
    }
    setState(() => _scheduledAt = picked);
  }

  String get _scheduleLabel {
    final t = _scheduledAt;
    if (t == null) return '尽快送达';
    final now = DateTime.now();
    final day =
        (t.day == now.day && t.month == now.month) ? '今天' : '${t.month}/${t.day}';
    return '预约 $day ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }

  Widget _row(String label, String value, {bool bold = false}) {
    final style = bold ? const TextStyle(fontWeight: FontWeight.bold) : null;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [Text(label, style: style), Text(value, style: style)],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final fee = _feeCents;
    final eta = _etaMin;
    final packing = widget.merchant.packingFeeCents;
    final discount = _discountCents;
    // 首单立减由服务端判定,这里不预估(下单后订单明细会显示)
    final tip = _pickup ? 0 : _tipCents;
    final total =
        fee == null ? null : _foodCents + packing - discount + fee + tip;
    final commission =
        ((_foodCents + packing - discount) * widget.merchant.commissionRate)
            .round();

    return Scaffold(
      appBar: AppBar(title: const Text('确认订单')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          // 配送方式:外卖配送 / 到店自取(免配送费)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(
                      value: false,
                      icon: Icon(Icons.electric_moped_outlined),
                      label: Text('外卖配送')),
                  ButtonSegment(
                      value: true,
                      icon: Icon(Icons.storefront_outlined),
                      label: Text('到店自取(免配送费)')),
                ],
                selected: {_pickup},
                onSelectionChanged: (v) => setState(() => _pickup = v.first),
              ),
            ),
          ),
          const SizedBox(height: 8),
          // 地址卡(配送) / 门店卡(自取)
          if (_pickup)
            Card(
              child: ListTile(
                leading: Icon(Icons.storefront,
                    color: theme.colorScheme.primary),
                title: Text(widget.merchant.name),
                subtitle: Text('${widget.merchant.address}\n'
                    '出餐后凭订单页的取餐码到店取餐'),
                isThreeLine: true,
              ),
            )
          else
            Card(
              child: _loadingAddress
                  ? const Padding(
                      padding: EdgeInsets.all(20),
                      child: Center(child: CircularProgressIndicator()))
                  : ListTile(
                      leading: Icon(Icons.place,
                          color: theme.colorScheme.primary),
                      title: Text(_address == null
                          ? '选择收货地址'
                          : _address!.fullAddress),
                      subtitle: _address == null
                          ? const Text('还没有地址,点击新建')
                          : Text(
                              '${_address!.contactName} ${_address!.contactPhone}'),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: _pickAddress,
                    ),
            ),
          if (eta != null && _scheduledAt == null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 0),
              child: Text(
                '🕐 预计 $eta 分钟送达',
                style: TextStyle(
                    color: theme.colorScheme.primary,
                    fontWeight: FontWeight.w600),
              ),
            ),
          const SizedBox(height: 8),
          // 送达时间:尽快 / 预约(预约单商家可从容备餐,接单超时豁免)
          Card(
            child: ListTile(
              leading: Icon(Icons.schedule, color: theme.colorScheme.primary),
              title: Text(_scheduleLabel),
              subtitle: _scheduledAt == null
                  ? Text(_pickup
                      ? '点击可预约取餐时间(最多提前 48 小时)'
                      : '点击可预约送达时间(最多提前 48 小时)')
                  : null,
              trailing: _scheduledAt == null
                  ? const Icon(Icons.chevron_right)
                  : TextButton(
                      onPressed: () => setState(() => _scheduledAt = null),
                      child: const Text('改为尽快')),
              onTap: _pickScheduledTime,
            ),
          ),
          const SizedBox(height: 8),

          // 平台券:有可用券时展示,默认选中最大面额,可点掉
          if (_coupons.isNotEmpty)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('优惠券',
                        style: Theme.of(context).textTheme.titleSmall),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      children: [
                        for (final c in _coupons)
                          ChoiceChip(
                            label: Text(
                                '¥${(c['amount_cents'] as int) ~/ 100} 无门槛'),
                            selected: _couponId == c['id'],
                            onSelected: (sel) => setState(
                                () => _couponId = sel ? c['id'] as int : null),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          // 小费:可选,全归骑手(自取单无配送环节不显示)
          if (!_pickup)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('给骑手加个小费(可选,100% 归骑手)',
                        style: theme.textTheme.titleSmall),
                    const SizedBox(height: 8),
                    Wrap(spacing: 8, children: [
                      for (final c in const [0, 200, 500, 1000])
                        ChoiceChip(
                          label: Text(c == 0 ? '不加' : '¥${c ~/ 100}'),
                          selected: _tipCents == c,
                          onSelected: (_) => setState(() => _tipCents = c),
                        ),
                    ]),
                  ],
                ),
              ),
            ),
          if (!_pickup) const SizedBox(height: 8),

          // 商品明细
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(widget.merchant.name,
                      style: theme.textTheme.titleMedium),
                  const Divider(),
                  for (final line in widget.cart)
                    _row('${line.label} ×${line.quantity}',
                        yuan(line.unitCents * line.quantity)),
                  if (packing > 0) _row('打包费', yuan(packing)),
                  if (discount > 0)
                    _row('满减优惠(商家承担)', '-${yuan(discount)}'),
                  if (_giftRule != null)
                    _row(
                        '已享:满${_giftRule!.thresholdCents ~/ 100}'
                        '赠${_giftRule!.name}',
                        '¥0'),
                  if (_pickup)
                    _row('配送费(到店自取)', '免')
                  else
                    _row('配送费(按距离)',
                        fee == null ? '选地址后计算' : yuan(fee)),
                  if (!_pickup && tip > 0)
                    _row('小费(100% 归骑手)', yuan(tip)),
                  if (_selectedCouponOff > 0)
                    _row('安抚券抵扣(平台承担)',
                        '-${yuan(_selectedCouponOff)}'),
                  const Divider(),
                  _row(
                      '合计',
                      total == null
                          ? '—'
                          : yuan(total - _selectedCouponOff),
                      bold: true),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          // 餐具 + 备注
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              child: Column(
                children: [
                  Row(
                    children: [
                      const Text('餐具份数'),
                      const Spacer(),
                      IconButton(
                        icon: const Icon(Icons.remove_circle_outline),
                        onPressed: _tableware > 0
                            ? () => setState(() => _tableware--)
                            : null,
                      ),
                      Text('$_tableware'),
                      IconButton(
                        icon: const Icon(Icons.add_circle_outline),
                        onPressed: _tableware < 20
                            ? () => setState(() => _tableware++)
                            : null,
                      ),
                    ],
                  ),
                  TextField(
                    controller: _remark,
                    maxLength: 100,
                    decoration: const InputDecoration(
                      labelText: '订单备注',
                      hintText: '口味偏好、放门口等(选填)',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 8),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          // 透明分账预览
          if (total != null)
            Card(
              color: theme.colorScheme.surfaceContainerHighest
                  .withValues(alpha: 0.35),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      const Icon(Icons.visibility_outlined, size: 16),
                      const SizedBox(width: 6),
                      Text('这一单的钱会去哪',
                          style: theme.textTheme.titleSmall
                              ?.copyWith(fontWeight: FontWeight.bold)),
                    ]),
                    const SizedBox(height: 6),
                    _row('商家实收(扣 5% 服务费)',
                        yuan(_foodCents + packing - discount - commission)),
                    if (!_pickup)
                      _row(tip > 0 ? '骑手所得(配送费+小费)' : '骑手所得(配送费全额)',
                          yuan(fee! + tip)),
                    _row('平台留存', yuan(commission)),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 80),
        ],
      ),
      bottomNavigationBar: SafeArea(
        child: Container(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
          decoration: BoxDecoration(
            color: theme.colorScheme.surface,
            boxShadow: const [BoxShadow(color: Colors.black12, blurRadius: 8)],
          ),
          child: Row(
            children: [
              Expanded(
                // 合计变化时轻微上滚过渡,给"价格在响应我的操作"的反馈
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 200),
                  transitionBuilder: (child, animation) => FadeTransition(
                    opacity: animation,
                    child: SlideTransition(
                      position: Tween(
                              begin: const Offset(0, 0.4), end: Offset.zero)
                          .animate(animation),
                      child: child,
                    ),
                  ),
                  child: Text(
                    _belowMinOrder
                        ? '差 ${yuan(widget.merchant.minOrderCents - _foodCents)} 起送'
                        : total == null
                            ? '请先选择地址'
                            : '合计 ${yuan(total)}${_pickup ? ' · 自取' : ''}',
                    key: ValueKey('$_belowMinOrder-$total'),
                    style: theme.textTheme.titleMedium
                        ?.copyWith(fontWeight: FontWeight.bold),
                  ),
                ),
              ),
              FilledButton(
                onPressed: _submitting || total == null || _belowMinOrder
                    ? null
                    : _submit,
                child: Text(_belowMinOrder
                    ? '未达起送价'
                    : _submitting
                        ? '下单中…'
                        : '提交订单并支付'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
