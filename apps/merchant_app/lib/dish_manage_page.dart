import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

/// 菜品管理:按分类分组的列表,上下架开关,点击编辑,右下角新增。
class DishManagePage extends StatefulWidget {
  const DishManagePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<DishManagePage> createState() => _DishManagePageState();
}

class _DishManagePageState extends State<DishManagePage> {
  List<Dish>? _dishes;
  Map<String, dynamic>? _stocking; // 高峰备货建议(纯建议,不自动改)

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final dishes = await widget.api.myDishes();
      if (mounted) setState(() => _dishes = dishes);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
    try {
      final st = await widget.api.merchantStocking();
      if (mounted) setState(() => _stocking = st);
    } catch (_) {}
  }

  /// 一键按建议补库存(可能不够卖的菜全部补到建议份数)
  Future<void> _adoptStocking() async {
    final short = (_stocking?['shortlist'] as List?) ?? [];
    if (short.isEmpty) return;
    try {
      await widget.api.batchStock([
        for (final s in short)
          {'dish_id': s['dish_id'] as int, 'stock': s['suggested'] as int},
      ]);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('已按建议补 ${short.length} 道菜的库存(估清自动解除)')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Widget? _stockingCard() {
    final st = _stocking;
    final short = (st?['shortlist'] as List?) ?? [];
    if (st == null || short.isEmpty) return null;
    return Card(
      margin: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      color: Colors.orange.withValues(alpha: .08),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${st['meal_label']}备货提示(近 14 天同餐段销量估算)',
                style: Theme.of(context)
                    .textTheme
                    .titleSmall
                    ?.copyWith(color: Colors.orange.shade800)),
            const SizedBox(height: 6),
            for (final s in short)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(children: [
                  Expanded(child: Text('${s['name']}')),
                  Text('现 ${s['stock']} → 建议 ${s['suggested']} 份',
                      style: Theme.of(context).textTheme.bodySmall),
                ]),
              ),
            const SizedBox(height: 6),
            Row(children: [
              Expanded(
                child: Text('纯建议,不会自动改库存',
                    style: Theme.of(context)
                        .textTheme
                        .bodySmall
                        ?.copyWith(color: Colors.grey)),
              ),
              FilledButton.tonal(
                  onPressed: _adoptStocking,
                  child: const Text('一键按建议补货')),
            ]),
          ],
        ),
      ),
    );
  }

  Future<void> _edit([Dish? dish]) async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(
        builder: (_) => DishEditPage(api: widget.api, dish: dish)));
    if (changed == true) _load();
  }

  Future<void> _toggleOnSale(Dish dish, bool value) async {
    try {
      await widget.api.updateDish(dish.id, {'is_on_sale': value});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 补货(stock=100)。高峰期缺货一秒处理
  Future<void> _setStock(Dish dish, int stock) async {
    try {
      await widget.api.updateDish(dish.id, {'stock': stock});
      _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('「${dish.name}」已补货至 $stock')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 估清(今日售罄):库存清零打标,用户端灰态,次日 04:00 自动恢复
  Future<void> _sellOut(Dish dish) async {
    try {
      await widget.api.sellOutDish(dish.id);
      _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('「${dish.name}」已估清,明天 4 点自动恢复')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _cancelSellOut(Dish dish) async {
    try {
      final d = await widget.api.cancelSellOut(dish.id);
      _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('「${dish.name}」已恢复,库存 ${d.stock}')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Widget _thumb(Dish dish) {
    final placeholder = Container(
      width: 48,
      height: 48,
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Icon(Icons.ramen_dining,
          size: 22, color: Theme.of(context).colorScheme.outline),
    );
    if (dish.imageUrl.isEmpty) return placeholder;
    return ClipRRect(
      borderRadius: BorderRadius.circular(6),
      child: Image.network(
        widget.api.resolveUrl(dish.imageUrl),
        width: 48,
        height: 48,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => placeholder,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final dishes = _dishes;
    Widget body;
    if (dishes == null) {
      body = const Center(child: CircularProgressIndicator());
    } else if (dishes.isEmpty) {
      body = Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('还没有菜品'),
            const SizedBox(height: 12),
            FilledButton(onPressed: () => _edit(), child: const Text('上第一道菜')),
          ],
        ),
      );
    } else {
      // 按分类分组(保持后端返回的顺序)
      final grouped = <String, List<Dish>>{};
      for (final dish in dishes) {
        final key = dish.category.isEmpty ? '未分类' : dish.category;
        grouped.putIfAbsent(key, () => []).add(dish);
      }
      // 经营诊断:本月销量榜 + 滞销数(卖得好的多备货,滞销的考虑换菜)
      final ranked = [...dishes]
        ..sort((a, b) => b.monthlySales.compareTo(a.monthlySales));
      final top = ranked.where((d) => d.monthlySales > 0).take(3).toList();
      final stale =
          dishes.where((d) => d.isOnSale && d.monthlySales == 0).length;
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          children: [
            if (_stockingCard() != null) _stockingCard()!,
            if (top.isNotEmpty)
              Card(
                margin: const EdgeInsets.fromLTRB(12, 12, 12, 4),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('本月销量榜',
                          style: Theme.of(context)
                              .textTheme
                              .titleSmall
                              ?.copyWith(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 6),
                      for (final (i, d) in top.indexed)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 2),
                          child: Row(children: [
                            Text('${i + 1}. ${d.name}'),
                            const Spacer(),
                            Text('月售 ${d.monthlySales}',
                                style:
                                    Theme.of(context).textTheme.bodySmall),
                          ]),
                        ),
                      if (stale > 0)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text('$stale 道在售菜品本月零销量,考虑调整或下架',
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(
                                      color: Theme.of(context)
                                          .colorScheme
                                          .outline)),
                        ),
                    ],
                  ),
                ),
              ),
            for (final entry in grouped.entries) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                child: Text(entry.key,
                    style: Theme.of(context)
                        .textTheme
                        .titleSmall
                        ?.copyWith(color: Theme.of(context).colorScheme.primary)),
              ),
              for (final dish in entry.value)
                ListTile(
                  leading: _thumb(dish),
                  title: Text(
                    dish.name,
                    style: dish.isOnSale
                        ? null
                        : TextStyle(
                            color: Theme.of(context).colorScheme.outline,
                            decoration: TextDecoration.lineThrough),
                  ),
                  subtitle: Text(
                    '${yuan(dish.effectivePriceCents)}'
                    '${dish.flashActive ? "(限时中,原价 ${yuan(dish.priceCents)})" : ""} · '
                    '${dish.soldOutToday ? "今日售罄(明日自动恢复)" : dish.stock == 0 ? "已售罄" : "库存 ${dish.stock}"}'
                    '${dish.dailyStock != null ? " · 每日回满${dish.dailyStock}" : ""}'
                    ' · 月售 ${dish.monthlySales}'
                    '${dish.imageUrl.isEmpty ? " · 建议配图" : ""}',
                    style: dish.stock == 0
                        ? TextStyle(
                            color: Theme.of(context).colorScheme.error)
                        : null,
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (dish.isOnSale)
                        dish.soldOutToday
                            ? TextButton(
                                onPressed: () => _cancelSellOut(dish),
                                child: const Text('恢复'))
                            : dish.stock > 0
                                ? TextButton(
                                    onPressed: () => _sellOut(dish),
                                    child: const Text('估清'))
                                : TextButton(
                                    onPressed: () => _setStock(dish, 100),
                                    child: const Text('补货')),
                      Switch(
                        value: dish.isOnSale,
                        onChanged: (v) => _toggleOnSale(dish, v),
                      ),
                    ],
                  ),
                  onTap: () => _edit(dish),
                ),
            ],
            const SizedBox(height: 80),
          ],
        ),
      );
    }

    return Scaffold(
      body: body,
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _edit(),
        icon: const Icon(Icons.add),
        label: const Text('新增菜品'),
      ),
    );
  }
}

/// 新增 / 编辑菜品,支持相册选图上传。
class DishEditPage extends StatefulWidget {
  const DishEditPage({super.key, required this.api, this.dish});

  final ApiClient api;
  final Dish? dish; // null = 新增

  @override
  State<DishEditPage> createState() => _DishEditPageState();
}

class _DishEditPageState extends State<DishEditPage> {
  late final _name = TextEditingController(text: widget.dish?.name ?? '');
  late final _category =
      TextEditingController(text: widget.dish?.category ?? '');
  late final _price = TextEditingController(
      text: widget.dish == null
          ? ''
          : (widget.dish!.priceCents / 100).toStringAsFixed(2));
  late final _stock =
      TextEditingController(text: '${widget.dish?.stock ?? 100}');
  // 每日回满目标(空=不启用)
  late final _dailyStock = TextEditingController(
      text: widget.dish?.dailyStock == null ? '' : '${widget.dish!.dailyStock}');
  late String _imageUrl = widget.dish?.imageUrl ?? '';
  late bool _isAlcohol = widget.dish?.isAlcohol ?? false;
  bool _uploading = false;
  bool _saving = false;

  // 限时折扣(两者齐才生效;保存时校验低于原价)
  late final _flashPrice = TextEditingController(
      text: widget.dish?.flashPriceCents == null
          ? ''
          : (widget.dish!.flashPriceCents! / 100).toStringAsFixed(2));
  late DateTime? _flashUntil = widget.dish?.flashUntil?.toLocal();

  // 规格/加料组(编辑用可变结构,保存时序列化)
  late final List<_EditGroup> _groups = [
    for (final g in widget.dish?.options ?? <OptionGroup>[])
      _EditGroup.from(g),
  ];

  Future<void> _pickImage() async {
    final picked = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1024,
      imageQuality: 85,
    );
    if (picked == null) return;
    setState(() => _uploading = true);
    try {
      final bytes = await picked.readAsBytes();
      final url = await widget.api.uploadImage(bytes, picked.name);
      if (mounted) setState(() => _imageUrl = url);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  /// 序列化规格组;组名/选项名为空的行自动丢弃
  List<Map<String, dynamic>>? _serializeOptions() {
    final result = <Map<String, dynamic>>[];
    for (final g in _groups) {
      final name = g.name.text.trim();
      final choices = <Map<String, dynamic>>[];
      for (final c in g.choices) {
        final cname = c.name.text.trim();
        if (cname.isEmpty) continue;
        final delta = ((double.tryParse(c.delta.text.trim()) ?? 0) * 100).round();
        if (delta < 0) {
          ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('加价不能为负(降价请直接改基础价)')));
          return null;
        }
        choices.add({'name': cname, 'delta_cents': delta});
      }
      if (name.isEmpty || choices.isEmpty) continue;
      result.add({
        'name': name,
        'required': g.required_,
        'multi': g.multi,
        'choices': choices,
      });
    }
    return result;
  }

  Future<void> _save() async {
    final priceCents = ((double.tryParse(_price.text) ?? 0) * 100).round();
    final stock = int.tryParse(_stock.text) ?? -1;
    if (_name.text.trim().isEmpty || priceCents <= 0 || stock < 0) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请填写菜名、正确的价格和库存')));
      return;
    }
    final options = _serializeOptions();
    if (options == null) return;
    setState(() => _saving = true);
    try {
      // 限时折扣:价与时间必须成对;客户端先校验一遍(服务端还有兜底)
      final flashText = _flashPrice.text.trim();
      final flashCents =
          flashText.isEmpty ? null : ((double.tryParse(flashText) ?? 0) * 100).round();
      if ((flashCents == null) != (_flashUntil == null)) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('限时折扣需同时设置折扣价和截止时间')));
        setState(() => _saving = false);
        return;
      }
      if (flashCents != null && flashCents >= priceCents) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('折扣价必须低于原价')));
        setState(() => _saving = false);
        return;
      }
      final flashFields = {
        'flash_price_cents': flashCents,
        'flash_until': _flashUntil?.toUtc().toIso8601String(),
      };
      final dailyText = _dailyStock.text.trim();
      final dailyStock = dailyText.isEmpty ? null : int.tryParse(dailyText);
      if (dailyText.isNotEmpty && (dailyStock == null || dailyStock < 0)) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('每日回满份数请填非负整数(留空不启用)')));
        setState(() => _saving = false);
        return;
      }
      if (widget.dish == null) {
        await widget.api.addDish(
          name: _name.text.trim(),
          category: _category.text.trim(),
          priceCents: priceCents,
          stock: stock,
          imageUrl: _imageUrl,
          options: options,
          dailyStock: dailyStock,
          isAlcohol: _isAlcohol,
        );
      } else {
        await widget.api.updateDish(widget.dish!.id, {
          'name': _name.text.trim(),
          'category': _category.text.trim(),
          'price_cents': priceCents,
          'stock': stock,
          'daily_stock': dailyStock, // null = 关闭每日回满
          'is_alcohol': _isAlcohol,
          'image_url': _imageUrl,
          'options': options,
          ...flashFields,
        });
      }
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.dish == null ? '新增菜品' : '编辑菜品')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Center(
            child: InkWell(
              onTap: _uploading ? null : _pickImage,
              borderRadius: BorderRadius.circular(12),
              child: Container(
                width: 120,
                height: 120,
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(12),
                ),
                clipBehavior: Clip.antiAlias,
                child: _uploading
                    ? const Center(child: CircularProgressIndicator())
                    : _imageUrl.isEmpty
                        ? Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            children: [
                              Icon(Icons.add_a_photo,
                                  color:
                                      Theme.of(context).colorScheme.outline),
                              const SizedBox(height: 4),
                              const Text('选菜品图', style: TextStyle(fontSize: 12)),
                            ],
                          )
                        : Image.network(
                            widget.api.resolveUrl(_imageUrl),
                            fit: BoxFit.cover,
                            errorBuilder: (_, __, ___) =>
                                const Icon(Icons.broken_image),
                          ),
              ),
            ),
          ),
          const SizedBox(height: 16),
          TextField(
              controller: _name,
              decoration: const InputDecoration(
                  labelText: '菜名 *', border: OutlineInputBorder())),
          const SizedBox(height: 12),
          TextField(
              controller: _category,
              decoration: const InputDecoration(
                  labelText: '分类(如 招牌/主食/饮品)',
                  helperText: '同分类的菜在点单页归为一组',
                  border: OutlineInputBorder())),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: TextField(
                  controller: _price,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(
                      labelText: '价格(元)*', border: OutlineInputBorder())),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                  controller: _stock,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                      labelText: '库存 *', border: OutlineInputBorder())),
            ),
          ]),
          const SizedBox(height: 12),
          TextField(
              controller: _dailyStock,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                  labelText: '每日回满(份,留空不启用)',
                  helperText: '设置后每天凌晨 4 点库存自动重置为该值,估清同时解除',
                  border: OutlineInputBorder())),
          const SizedBox(height: 4),
          // 酒类标记:依法只售成年人,勾选后用户须实名且成年才能下单
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('酒类商品'),
            subtitle: const Text('勾选后用户需实名认证且年满 18 岁才能购买;小票与骑手端会提示查验收件人',
                style: TextStyle(fontSize: 11)),
            value: _isAlcohol,
            onChanged: (v) => setState(() => _isAlcohol = v),
          ),
          if (widget.dish != null) ...[
            const SizedBox(height: 16),
            Row(
              children: [
                Text('限时折扣',
                    style: Theme.of(context).textTheme.titleSmall),
                const Spacer(),
                if (_flashPrice.text.isNotEmpty || _flashUntil != null)
                  TextButton(
                    onPressed: () => setState(() {
                      _flashPrice.clear();
                      _flashUntil = null;
                    }),
                    child: const Text('清除'),
                  ),
              ],
            ),
            Row(
              children: [
                Expanded(
                  child: TextField(
                      controller: _flashPrice,
                      keyboardType: const TextInputType.numberWithOptions(
                          decimal: true),
                      onChanged: (_) => setState(() {}),
                      decoration: const InputDecoration(
                          labelText: '折扣价(元)', isDense: true)),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton(
                    onPressed: () async {
                      final now = DateTime.now();
                      final date = await showDatePicker(
                          context: context,
                          initialDate: now,
                          firstDate: now,
                          lastDate: now.add(const Duration(days: 30)));
                      if (date == null || !context.mounted) return;
                      final time = await showTimePicker(
                          context: context,
                          initialTime: const TimeOfDay(hour: 21, minute: 0));
                      if (time == null) return;
                      setState(() => _flashUntil = DateTime(date.year,
                          date.month, date.day, time.hour, time.minute));
                    },
                    child: Text(_flashUntil == null
                        ? '截止时间'
                        : '${_flashUntil!.month}/${_flashUntil!.day} '
                            '${_flashUntil!.hour.toString().padLeft(2, '0')}:'
                            '${_flashUntil!.minute.toString().padLeft(2, '0')} 止'),
                  ),
                ),
              ],
            ),
            Text('折扣价即成交价,服务费按折后实收计——你让利,平台跟着少收',
                style: Theme.of(context).textTheme.bodySmall),
          ],
          const SizedBox(height: 16),
          // 规格/加料(如 份量:小份/大份+3元;加料:加蛋+2元)
          Row(
            children: [
              Text('规格/加料', style: Theme.of(context).textTheme.titleSmall),
              const Spacer(),
              if (_groups.length < 5)
                TextButton.icon(
                  icon: const Icon(Icons.add, size: 18),
                  label: const Text('加一组'),
                  onPressed: () =>
                      setState(() => _groups.add(_EditGroup.empty())),
                ),
            ],
          ),
          if (_groups.isEmpty)
            Text('不设置则按固定价售卖。示例:「份量」组必选(小份 +0 / 大份 +3),'
                '「加料」组可多选(加蛋 +2)',
                style: Theme.of(context).textTheme.bodySmall),
          for (var gi = 0; gi < _groups.length; gi++)
            Card(
              margin: const EdgeInsets.symmetric(vertical: 6),
              child: Padding(
                padding: const EdgeInsets.all(10),
                child: Column(
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _groups[gi].name,
                            decoration: const InputDecoration(
                                labelText: '组名(如 份量)', isDense: true),
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.delete_outline),
                          onPressed: () =>
                              setState(() => _groups.removeAt(gi)),
                        ),
                      ],
                    ),
                    Row(
                      children: [
                        FilterChip(
                          label: const Text('必选'),
                          selected: _groups[gi].required_,
                          onSelected: (v) =>
                              setState(() => _groups[gi].required_ = v),
                        ),
                        const SizedBox(width: 8),
                        FilterChip(
                          label: const Text('可多选'),
                          selected: _groups[gi].multi,
                          onSelected: (v) =>
                              setState(() => _groups[gi].multi = v),
                        ),
                      ],
                    ),
                    for (var ci = 0; ci < _groups[gi].choices.length; ci++)
                      Row(
                        children: [
                          Expanded(
                            flex: 3,
                            child: TextField(
                              controller: _groups[gi].choices[ci].name,
                              decoration: const InputDecoration(
                                  labelText: '选项名', isDense: true),
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            flex: 2,
                            child: TextField(
                              controller: _groups[gi].choices[ci].delta,
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                      decimal: true),
                              decoration: const InputDecoration(
                                  labelText: '加价(元)', isDense: true),
                            ),
                          ),
                          IconButton(
                            visualDensity: VisualDensity.compact,
                            icon: const Icon(Icons.remove_circle_outline,
                                size: 20),
                            onPressed: _groups[gi].choices.length > 1
                                ? () => setState(
                                    () => _groups[gi].choices.removeAt(ci))
                                : null,
                          ),
                        ],
                      ),
                    if (_groups[gi].choices.length < 10)
                      Align(
                        alignment: Alignment.centerLeft,
                        child: TextButton(
                          onPressed: () => setState(
                              () => _groups[gi].choices.add(_EditChoice())),
                          child: const Text('+ 加选项'),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 24),
          FilledButton(
            onPressed: _saving ? null : _save,
            child: Text(_saving ? '保存中…' : '保存'),
          ),
        ],
      ),
    );
  }
}

/// 规格组编辑态(TextEditingController 持有可变文本)。
class _EditGroup {
  _EditGroup.empty()
      : name = TextEditingController(),
        required_ = false,
        multi = false,
        choices = [_EditChoice()];

  _EditGroup.from(OptionGroup g)
      : name = TextEditingController(text: g.name),
        required_ = g.required_,
        multi = g.multi,
        choices = [for (final c in g.choices) _EditChoice.from(c)];

  final TextEditingController name;
  bool required_;
  bool multi;
  final List<_EditChoice> choices;
}

class _EditChoice {
  _EditChoice()
      : name = TextEditingController(),
        delta = TextEditingController();

  _EditChoice.from(OptionChoice c)
      : name = TextEditingController(text: c.name),
        delta = TextEditingController(
            text: c.deltaCents == 0
                ? ''
                : (c.deltaCents / 100).toStringAsFixed(
                    c.deltaCents % 100 == 0 ? 0 : 2));

  final TextEditingController name;
  final TextEditingController delta;
}
