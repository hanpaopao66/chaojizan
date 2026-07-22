import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'checkout_page.dart';

/// 拼单页:成员列表 + 按人分组的菜品,自己的菜可加减;
/// 发起人锁单后去结算(一次性支付,AA 线下自行解决)。3 秒轮询同步。
class GroupCartPage extends StatefulWidget {
  const GroupCartPage({
    super.key,
    required this.api,
    required this.merchant,
    required this.code,
  });

  final ApiClient api;
  final Merchant merchant;
  final String code;

  @override
  State<GroupCartPage> createState() => _GroupCartPageState();
}

class _GroupCartPageState extends State<GroupCartPage> {
  Map<String, dynamic>? _cart;
  List<Dish> _dishes = [];
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _sync());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final dishes = await widget.api.menu(widget.merchant.id);
      if (mounted) setState(() => _dishes = dishes);
    } catch (_) {}
    _sync();
  }

  Future<void> _sync() async {
    try {
      final c = await widget.api.getGroupCart(widget.code);
      if (mounted) setState(() => _cart = c);
    } catch (e) {
      if (!mounted) return;
      if (e.toString().contains('过期') || e.toString().contains('不存在')) {
        _timer?.cancel();
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('这车拼单已结束(已下单或超 2 小时过期)')));
        Navigator.of(context).pop();
      }
    }
  }

  int _myQty(int dishId) {
    final me = _cart?['me'];
    for (final i in (_cart?['items'] as List? ?? [])) {
      if (i['uid'] == me && i['dish_id'] == dishId) {
        return i['quantity'] as int;
      }
    }
    return 0;
  }

  Future<void> _setQty(int dishId, int qty) async {
    try {
      final c =
          await widget.api.setGroupCartItem(widget.code, dishId, qty);
      if (mounted) setState(() => _cart = c);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _checkout() async {
    try {
      final locked = await widget.api.lockGroupCart(widget.code);
      if (!mounted) return;
      setState(() => _cart = locked);
      final byId = {for (final d in _dishes) d.id: d};
      final lines = <CartLine>[];
      for (final i in locked['items'] as List) {
        final dish = byId[i['dish_id']];
        if (dish == null) continue;
        final line = CartLine(dish: dish, choices: const []);
        line.quantity = i['quantity'] as int;
        lines.add(line);
      }
      if (lines.isEmpty) return;
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => CheckoutPage(
              api: widget.api,
              merchant: widget.merchant,
              cart: lines,
              groupCode: widget.code)));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cart = _cart;
    final locked = cart?['locked'] == true;
    final isOwner = cart?['is_owner'] == true;
    return Scaffold(
      appBar: AppBar(title: Text('拼单 · ${widget.merchant.name}')),
      body: cart == null
          ? const Center(child: CircularProgressIndicator())
          : Column(children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                color: kMoneyGreen.withValues(alpha: .08),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SelectableText('拼单码:${widget.code}(2 小时有效)',
                        style: const TextStyle(
                            fontWeight: FontWeight.w800, fontSize: 16)),
                    const SizedBox(height: 4),
                    Text(
                        '${(cart['members'] as Map).length} 人在车上:'
                        '${(cart['members'] as Map).values.join('、')}\n'
                        '各自加菜,发起人一次性支付;起送价/满减按合计算',
                        style: theme.textTheme.bodySmall),
                    if (locked)
                      const Text('已锁单:同伴不能再改菜',
                          style: TextStyle(
                              color: Colors.orange,
                              fontWeight: FontWeight.w700)),
                  ],
                ),
              ),
              Expanded(
                child: ListView(padding: const EdgeInsets.all(12), children: [
                  if ((cart['items'] as List).isNotEmpty) ...[
                    Text('已点(${yuan(cart['total_cents'] as int)})',
                        style: theme.textTheme.titleSmall),
                    for (final i in cart['items'] as List)
                      Row(children: [
                        Expanded(
                            child:
                                Text('${i['name']} ×${i['quantity']}')),
                        Text('${i['by']}',
                            style: theme.textTheme.bodySmall),
                        const SizedBox(width: 8),
                        Text(yuan((i['price_cents'] as int) *
                            (i['quantity'] as int))),
                      ]),
                    const Divider(height: 24),
                  ],
                  Text('加菜', style: theme.textTheme.titleSmall),
                  for (final d in _dishes.where(
                      (d) => d.isOnSale && d.stock > 0 && !d.soldOutToday))
                    Row(children: [
                      Expanded(child: Text(d.name)),
                      Text(yuan(d.priceCents),
                          style: theme.textTheme.bodySmall),
                      IconButton(
                          visualDensity: VisualDensity.compact,
                          onPressed: locked || _myQty(d.id) == 0
                              ? null
                              : () => _setQty(d.id, _myQty(d.id) - 1),
                          icon: const Icon(Icons.remove_circle_outline)),
                      Text('${_myQty(d.id)}'),
                      IconButton(
                          visualDensity: VisualDensity.compact,
                          onPressed: locked
                              ? null
                              : () => _setQty(d.id, _myQty(d.id) + 1),
                          icon: const Icon(Icons.add_circle_outline)),
                    ]),
                ]),
              ),
              SafeArea(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: isOwner
                      ? SizedBox(
                          width: double.infinity,
                          child: FilledButton(
                            onPressed: (cart['items'] as List).isEmpty
                                ? null
                                : _checkout,
                            child: Text(locked ? '去结算' : '锁单并去结算'),
                          ),
                        )
                      : Text(
                          locked ? '发起人结算中…' : '点好了等发起人结算就行',
                          textAlign: TextAlign.center,
                          style: theme.textTheme.bodySmall),
                ),
              ),
            ]),
    );
  }
}
