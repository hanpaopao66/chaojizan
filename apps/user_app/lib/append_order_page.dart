/// 加菜(追加单):商家出餐前从同店补点几样,免配送费随原单一起送。
/// 独立支付独立小票——原单的账已经冻结,不动它。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'main.dart' show OrderDetailPage;
import 'payment_service.dart';

class AppendOrderPage extends StatefulWidget {
  const AppendOrderPage({super.key, required this.api, required this.parent});

  final ApiClient api;
  final Order parent;

  @override
  State<AppendOrderPage> createState() => _AppendOrderPageState();
}

class _AppendOrderPageState extends State<AppendOrderPage> {
  List<Dish>? _dishes;
  final Map<int, int> _qty = {}; // dishId -> 数量
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final menu = await widget.api.menu(widget.parent.merchantId);
      if (mounted) {
        setState(() {
          // 带必选规格的菜需要选规格,加菜走快捷通道只放"拿起就买"的
          _dishes = menu
              .where((d) =>
                  d.isOnSale &&
                  d.stock > 0 &&
                  !d.options.any((g) => g.required_))
              .toList();
        });
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  int get _totalCents {
    var total = 0;
    for (final d in _dishes ?? <Dish>[]) {
      total += (_qty[d.id] ?? 0) * d.priceCents;
    }
    return total;
  }

  Future<void> _submit() async {
    final items = [
      for (final e in _qty.entries)
        if (e.value > 0) {'dish_id': e.key, 'quantity': e.value},
    ];
    if (items.isEmpty) return;
    setState(() => _submitting = true);
    try {
      final order = await widget.api.createOrder(
        merchantId: widget.parent.merchantId,
        items: items,
        appendTo: widget.parent.orderNo,
      );
      if (!mounted) return;
      final paid = await payOrder(widget.api, order, context);
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(
          builder: (_) =>
              OrderDetailPage(api: widget.api, orderNo: paid.orderNo)));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final dishes = _dishes;
    return Scaffold(
      appBar: AppBar(
          title: Text('加菜 · 随#'
              '${widget.parent.orderNo.substring(widget.parent.orderNo.length - 6)}'
              ' 一起送')),
      body: dishes == null
          ? const Center(child: CircularProgressIndicator())
          : Column(children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 10, 16, 0),
                child: Text('免配送费、免起送价,商家会和原单一起打包;带规格的菜请重新下单选择',
                    style: TextStyle(fontSize: 12, color: Colors.grey)),
              ),
              Expanded(
                child: dishes.isEmpty
                    ? const Center(child: Text('暂无可快捷加购的菜品'))
                    : ListView.builder(
                        itemCount: dishes.length,
                        itemBuilder: (context, i) {
                          final d = dishes[i];
                          final q = _qty[d.id] ?? 0;
                          return ListTile(
                            title: Text(d.name),
                            subtitle: Text(yuan(d.priceCents)),
                            trailing: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                IconButton(
                                  icon:
                                      const Icon(Icons.remove_circle_outline),
                                  onPressed: q > 0
                                      ? () =>
                                          setState(() => _qty[d.id] = q - 1)
                                      : null,
                                ),
                                Text('$q'),
                                IconButton(
                                  icon: const Icon(Icons.add_circle_outline),
                                  onPressed: q < d.stock
                                      ? () =>
                                          setState(() => _qty[d.id] = q + 1)
                                      : null,
                                ),
                              ],
                            ),
                          );
                        },
                      ),
              ),
              SafeArea(
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: _totalCents > 0 && !_submitting
                          ? _submit
                          : null,
                      child: Text(_submitting
                          ? '提交中…'
                          : '加菜并支付 ${yuan(_totalCents)}(免配送费)'),
                    ),
                  ),
                ),
              ),
            ]),
    );
  }
}
