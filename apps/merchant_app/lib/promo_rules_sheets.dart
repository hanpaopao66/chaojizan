import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 店铺的三套营销规则:满减、满赠、店铺券。
///
/// 从 `shop_tab.dart` 里搬出来的 —— 它们是三段自成一体的编辑流程,
/// 只要 `api`、当前店铺和一个「改完刷新」的回调,不碰店铺 Tab 的其它状态。
///
/// 三者的关系要在界面上讲清楚(商家最常问的就是这个):
/// **满减和店铺券二选其一取最优,满赠可以叠加。**

/// 满减规则编辑:最多 3 档,每档「满 X 减 Y」。
Future<void> editPromoRules(
  BuildContext context,
  ApiClient api,
  Merchant shop,
  Future<void> Function() reload,
) async {
  final rows = shop.promoRules
      .map((r) => (
            threshold:
                TextEditingController(text: '${r.thresholdCents ~/ 100}'),
            off: TextEditingController(
                text: (r.offCents / 100)
                    .toStringAsFixed(r.offCents % 100 == 0 ? 0 : 2)),
          ))
      .toList();
  try {
    await _runPromoDialog(context, api, rows, reload);
  } finally {
    // 这些 controller 原来没人释放,每开一次对话框漏一批
    for (final row in rows) {
      row.threshold.dispose();
      row.off.dispose();
    }
  }
}

typedef _PromoRow = ({TextEditingController threshold, TextEditingController off});

Future<void> _runPromoDialog(
  BuildContext context,
  ApiClient api,
  List<_PromoRow> rows,
  Future<void> Function() reload,
) async {
  final saved = await showDialog<bool>(
    context: context,
    builder: (context) => StatefulBuilder(
      builder: (context, setDialog) => AlertDialog(
        title: const Text('满减活动(最多 3 档)'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < rows.length; i++)
              Row(
                children: [
                  const Text('满'),
                  SizedBox(
                    width: 72,
                    child: TextField(
                        controller: rows[i].threshold,
                        keyboardType: TextInputType.number,
                        textAlign: TextAlign.center),
                  ),
                  const Text('元 减'),
                  SizedBox(
                    width: 72,
                    child: TextField(
                        controller: rows[i].off,
                        keyboardType: const TextInputType
                            .numberWithOptions(decimal: true),
                        textAlign: TextAlign.center),
                  ),
                  const Text('元'),
                  IconButton(
                    tooltip: '删掉这一档',
                    icon: const Icon(Icons.remove_circle_outline),
                    onPressed: () => setDialog(() {
                      // 删掉的行外面那个 finally 已经看不到了,当场释放
                      final row = rows.removeAt(i);
                      row.threshold.dispose();
                      row.off.dispose();
                    }),
                  ),
                ],
              ),
            if (rows.length < 3)
              TextButton.icon(
                icon: const Icon(Icons.add),
                label: const Text('加一档'),
                onPressed: () => setDialog(() => rows.add((
                      threshold: TextEditingController(),
                      off: TextEditingController(),
                    ))),
              ),
            const Text('成本商家承担;平台按满减后的实收计服务费',
                style: TextStyle(fontSize: 12)),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('保存')),
        ],
      ),
    ),
  );
  if (saved != true || !context.mounted) return;
  final rules = <Map<String, dynamic>>[];
  for (final row in rows) {
    final threshold = double.tryParse(row.threshold.text.trim());
    final off = double.tryParse(row.off.text.trim());
    if (threshold == null || off == null || threshold <= 0 || off <= 0) {
      continue; // 空行/无效行直接忽略
    }
    if (off >= threshold) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('减的金额必须小于门槛(不能倒贴)')));
      return;
    }
    rules.add({
      'threshold_cents': (threshold * 100).round(),
      'off_cents': (off * 100).round(),
    });
  }
  try {
    await api.updateShop({'promo_rules': rules});
    reload();
  } catch (e) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(e.toString())));
  }
}

/// 满赠规则编辑:最多 2 档,每档「满 X 元赠某菜 1 份」,赠品从本店在售菜里选。
Future<void> editGiftRules(
  BuildContext context,
  ApiClient api,
  Merchant shop,
  Future<void> Function() reload,
) async {
  final List<Dish> dishes;
  try {
    dishes = (await api.myDishes()).where((d) => d.isOnSale).toList();
  } catch (e) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(e.toString())));
    return;
  }
  if (!context.mounted) return;
  if (dishes.isEmpty) {
    ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('先上架菜品,才能选赠品')));
    return;
  }
  final dishIds = dishes.map((d) => d.id).toSet();
  final rows = shop.giftRules
      .map((r) => (
            threshold:
                TextEditingController(text: '${r.thresholdCents ~/ 100}'),
            // 赠品菜已下架时置空,强制重选
            dishId: ValueNotifier<int?>(
                dishIds.contains(r.dishId) ? r.dishId : null),
          ))
      .toList();
  try {
    await _runGiftDialog(context, api, dishes, rows, reload);
  } finally {
    for (final row in rows) {
      row.threshold.dispose();
      row.dishId.dispose();
    }
  }
}

typedef _GiftRow = ({
  TextEditingController threshold,
  ValueNotifier<int?> dishId
});

Future<void> _runGiftDialog(
  BuildContext context,
  ApiClient api,
  List<Dish> dishes,
  List<_GiftRow> rows,
  Future<void> Function() reload,
) async {
  final saved = await showDialog<bool>(
    context: context,
    builder: (context) => StatefulBuilder(
      builder: (context, setDialog) => AlertDialog(
        title: const Text('满赠活动(最多 2 档)'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < rows.length; i++)
              Row(
                children: [
                  const Text('满'),
                  SizedBox(
                    width: 56,
                    child: TextField(
                        controller: rows[i].threshold,
                        keyboardType: TextInputType.number,
                        textAlign: TextAlign.center),
                  ),
                  const Text('元赠'),
                  const SizedBox(width: 4),
                  Expanded(
                    child: DropdownButton<int>(
                      isExpanded: true,
                      value: rows[i].dishId.value,
                      hint: const Text('选菜品'),
                      items: [
                        for (final d in dishes)
                          DropdownMenuItem(
                              value: d.id,
                              child: Text(d.name,
                                  overflow: TextOverflow.ellipsis)),
                      ],
                      onChanged: (v) =>
                          setDialog(() => rows[i].dishId.value = v),
                    ),
                  ),
                  IconButton(
                    tooltip: '删掉这一档',
                    icon: const Icon(Icons.remove_circle_outline),
                    onPressed: () => setDialog(() {
                      final row = rows.removeAt(i);
                      row.threshold.dispose();
                      row.dishId.dispose();
                    }),
                  ),
                ],
              ),
            if (rows.length < 2)
              TextButton.icon(
                icon: const Icon(Icons.add),
                label: const Text('加一档'),
                onPressed: () => setDialog(() => rows.add((
                      threshold: TextEditingController(),
                      dishId: ValueNotifier<int?>(null),
                    ))),
              ),
            const Text('赠品照常扣库存,库存不足该档自动失效;与满减可同时生效',
                style: TextStyle(fontSize: 12)),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('保存')),
        ],
      ),
    ),
  );
  if (saved != true || !context.mounted) return;
  final rules = <Map<String, dynamic>>[];
  for (final row in rows) {
    final threshold = double.tryParse(row.threshold.text.trim());
    final dishId = row.dishId.value;
    if (threshold == null || threshold <= 0 || dishId == null) {
      continue; // 空行/无效行直接忽略
    }
    rules.add({
      'threshold_cents': (threshold * 100).round(),
      'dish_id': dishId,
    });
  }
  try {
    await api.updateShop({'gift_rules': rules});
    reload();
  } catch (e) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(e.toString())));
  }
}

/// 店铺券管理:列出已有批次(启停)+ 新建券
Future<void> showShopCouponSheet(
  BuildContext context,
  ApiClient api,
  List<Map<String, dynamic>> Function() coupons,
  Future<void> Function() reload,
) async {
  await szShowSheet(
    context: context,
    isScrollControlled: true,
    builder: (context) => StatefulBuilder(
      builder: (context, setSheet) => SafeArea(
        child: Padding(
          padding: EdgeInsets.only(
              left: 16, right: 16, top: 16,
              bottom: MediaQuery.of(context).viewInsets.bottom + 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('店铺券', style: Theme.of(context).textTheme.titleMedium),
              Text('成本你自己出,用来引流拉复购。与满减二选其一取最优。',
                  style: TextStyle(fontSize: 12, color: Theme.of(context).sz.inkMuted)),
              const SizedBox(height: 8),
              for (final b in coupons())
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(
                      '满${b['threshold_cents'] ~/ 100}减${b['off_cents'] ~/ 100}'
                      ' · ${b['name']}'),
                  subtitle: Text('已领 ${b['issued']}/${b['total']}'
                      ' · 每人${b['per_user_limit']}张 · ${b['valid_days']}天'),
                  trailing: Switch(
                    value: b['active'] == true,
                    onChanged: (_) async {
                      final messenger = ScaffoldMessenger.of(context);
                      try {
                        await api.toggleShopCouponBatch(b['id'] as int);
                        await reload();
                        setSheet(() {});
                      } catch (e) {
                        messenger.showSnackBar(
                            SnackBar(content: Text(e.toString())));
                      }
                    },
                  ),
                ),
              const Divider(),
              FilledButton.icon(
                icon: const Icon(Icons.add),
                label: const Text('新建店铺券'),
                onPressed: () async {
                  final ok = await _createShopCouponDialog(context, api);
                  if (ok == true) {
                    await reload();
                    setSheet(() {});
                  }
                },
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

Future<bool?> _createShopCouponDialog(
  BuildContext context, ApiClient api) async {
  final name = TextEditingController(text: '满减券');
  final threshold = TextEditingController();
  final off = TextEditingController();
  final total = TextEditingController(text: '100');
  final perUser = TextEditingController(text: '1');
  final validDays = TextEditingController(text: '7');
  try {
    return await showDialog<bool>(
    context: context,
    builder: (context) => AlertDialog(
      title: const Text('新建店铺券'),
      content: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
              controller: name,
              decoration: const InputDecoration(labelText: '券名')),
          Row(children: [
            Expanded(
              child: TextField(
                  controller: threshold,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: '满(元,0无门槛)')),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                  controller: off,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: '减(元)')),
            ),
          ]),
          Row(children: [
            Expanded(
              child: TextField(
                  controller: total,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: '发行总量')),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                  controller: perUser,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: '每人限领')),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                  controller: validDays,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(labelText: '有效天数')),
            ),
          ]),
        ]),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消')),
        FilledButton(
          onPressed: () async {
            final t = ((double.tryParse(threshold.text) ?? 0) * 100).round();
            final o = ((double.tryParse(off.text) ?? 0) * 100).round();
            final tot = int.tryParse(total.text) ?? 0;
            if (o <= 0 || tot <= 0 || (t > 0 && o >= t)) {
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text('减额需>0且小于门槛,总量>0')));
              return;
            }
            try {
              await api.createShopCouponBatch({
                'name': name.text.trim(),
                'threshold_cents': t,
                'off_cents': o,
                'total': tot,
                'per_user_limit': int.tryParse(perUser.text) ?? 1,
                'valid_days': int.tryParse(validDays.text) ?? 7,
              });
              if (context.mounted) Navigator.pop(context, true);
            } catch (e) {
              if (context.mounted) {
                ScaffoldMessenger.of(context)
                    .showSnackBar(SnackBar(content: Text(e.toString())));
              }
            }
          },
          child: const Text('发布'),
        ),
      ],
    ),
    );
  } finally {
    // 六个 controller,原来一个都没释放
    for (final c in [name, threshold, off, total, perUser, validDays]) {
      c.dispose();
    }
  }
}
