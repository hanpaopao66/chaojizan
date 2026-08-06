import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

/// 菜品管理:按分类分组的列表,上下架开关,点击编辑,长按置顶,右下角新增。
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
      color: Theme.of(context).sz.claySoft,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${st['meal_label']}备货提示(近 14 天同餐段销量估算)',
                style: Theme.of(context)
                    .textTheme
                    .titleSmall
                    ?.copyWith(color: Theme.of(context).sz.hold)),
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
                        ?.copyWith(color: Theme.of(context).sz.inkFaint)),
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

  /// 置顶:把这道菜排到本分类最前(招牌菜该在第一屏,不该靠改分类名硬凑)。
  /// 只改这一道的 sort,不整体重排 —— 一次请求,失败也不会打乱既有顺序
  Future<void> _pinToTop(Dish dish, List<Dish> sameCategory) async {
    final minSort = sameCategory
        .map((d) => d.sort)
        .fold<int>(0, (a, b) => a < b ? a : b);
    if (sameCategory.isNotEmpty && sameCategory.first.id == dish.id) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('「${dish.name}」已经在最前面了')));
      return;
    }
    try {
      await widget.api.reorderDishes([
        {'dish_id': dish.id, 'sort': (minSort - 1).clamp(-9999, 9999)},
      ]);
      _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('「${dish.name}」已置顶到「${dish.category}」最前')));
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

  // ---- 批量操作(网页端早有,App 端此前只能一道一道点) ----
  final Set<int> _selected = {};
  bool _batching = false;
  // 多选态是**显式开关**,不由"选中集非空"推导:否则批量执行中途
  // 取消最后一个勾选,底栏和进度圈会整个消失,看起来像已经跑完了
  bool _selectMode = false;

  bool get _selecting => _selectMode;

  void _exitSelect() {
    setState(() {
      _selectMode = false;
      _selected.clear();
    });
  }

  void _toggleSelect(Dish dish) {
    setState(() {
      if (!_selected.remove(dish.id)) _selected.add(dish.id);
    });
  }

  /// 批量执行:逐个调既有接口(菜品几十道,不值得为此加批量端点)。
  /// 单个失败不中断其余,最后汇总告诉商家成功几道。
  /// [skip] 命中的菜直接跳过且不计失败 —— 批量估清一批混合状态的菜时,
  /// 已估清的那几道会被服务端 409 拒,算成"失败 2 道"会让商家以为出了故障
  Future<void> _batch(String label, Future<void> Function(int id) act,
      {bool Function(Dish dish)? skip}) async {
    final byId = {for (final d in (_dishes ?? const <Dish>[])) d.id: d};
    final ids = _selected
        .where((id) => byId[id] != null && !(skip?.call(byId[id]!) ?? false))
        .toList();
    final skipped = _selected.length - ids.length;
    if (ids.isEmpty) {
      _exitSelect();
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('$label:选中的菜已经是这个状态了')));
      return;
    }
    setState(() => _batching = true);
    var ok = 0;
    for (final id in ids) {
      try {
        await act(id);
        ok++;
      } catch (_) {/* 汇总里体现 */}
    }
    if (!mounted) return;
    setState(() {
      _batching = false;
      _selectMode = false;
      _selected.clear();
    });
    _load();
    final tail = skipped > 0 ? '(另有 $skipped 道无需处理)' : '';
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(ok == ids.length
            ? '$label:${ids.length} 道已处理$tail'
            : '$label:成功 $ok 道,失败 ${ids.length - ok} 道$tail')));
  }

  Future<void> _batchCategory() async {
    final controller = TextEditingController();
    try {
      final category = await showDialog<String>(
        context: context,
        builder: (dialog) => AlertDialog(
          title: Text('把 ${_selected.length} 道菜改到新分类'),
          content: TextField(
            controller: controller,
            autofocus: true,
            // 库里 category 是 varchar(50),不限长度就会整批 500
            maxLength: 50,
            decoration: const InputDecoration(
                labelText: '分类名', hintText: '如 招牌/主食/饮品',
                border: OutlineInputBorder()),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialog),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(dialog, controller.text.trim()),
                child: const Text('确认')),
          ],
        ),
      );
      if (category == null || category.isEmpty) return;
      await _batch('改分类',
          (id) => widget.api.updateDish(id, {'category': category}));
    } finally {
      controller.dispose();
    }
  }

  Widget _thumb(Dish dish) => SzImage(
        url: dish.imageUrl.isEmpty ? '' : widget.api.resolveUrl(dish.imageUrl),
        name: dish.name,
        size: 48,
      );

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
      final noPhoto = dishes.where((d) => d.imageUrl.isEmpty).length;
      body = RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          children: [
            // 多选的显式入口(长按留给置顶,不重载手势)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
              child: Row(children: [
                Text('共 ${dishes.length} 道 · 长按可置顶',
                    style: TextStyle(
                        fontSize: 12, color: Theme.of(context).sz.inkMuted)),
                const Spacer(),
                if (!_selecting)
                  TextButton.icon(
                    icon: const Icon(Icons.checklist, size: 18),
                    label: const Text('批量'),
                    onPressed: () => setState(() => _selectMode = true),
                  ),
              ]),
            ),
            if (_stockingCard() != null) _stockingCard()!,
            // 缺图汇总:占位图能让列表不难看,但真正解决问题的是把图补上。
            // 只在确实有缺图时出现,补完自动消失,不长期占地方
            if (noPhoto > 0)
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
                child: SzCard(
                  child: Row(children: [
                    Icon(Icons.photo_camera_outlined,
                        size: 18, color: Theme.of(context).sz.hold),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text.rich(
                        TextSpan(children: [
                          TextSpan(
                              text: '$noPhoto',
                              style: szFigure(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600,
                                  color: Theme.of(context).sz.hold)),
                          const TextSpan(text: ' 道菜还没配图。'),
                          const TextSpan(text: '顾客看不到图会跳过——现在列表里'
                              '显示的是店名首字占位,补一张实拍就换成你的图。'),
                        ]),
                        style: TextStyle(
                            fontSize: 12,
                            height: 1.55,
                            color: Theme.of(context).sz.ink),
                      ),
                    ),
                  ]),
                ),
              ),
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
                  selected: _selected.contains(dish.id),
                  selectedTileColor:
                      Theme.of(context).sz.claySoft.withValues(alpha: 0.4),
                  // **长按始终是置顶**:这是上一版就教给商家的手势,
                  // 改成"第一次长按进多选、第二次才置顶"会让老用户
                  // 按肌肉记忆连按两下,结果置顶了错的那道菜(写库且无撤销)。
                  // 多选走上方显式的「批量」按钮进入
                  onLongPress: _batching
                      ? null
                      : () => _selecting
                          ? _toggleSelect(dish)
                          : _pinToTop(dish, entry.value),
                  leading: _selecting
                      ? Icon(
                          _selected.contains(dish.id)
                              ? Icons.check_circle
                              : Icons.radio_button_unchecked,
                          color: _selected.contains(dish.id)
                              ? Theme.of(context).colorScheme.primary
                              : Theme.of(context).sz.inkFaint,
                        )
                      : _thumb(dish),
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
                    ' · 月售 ${dish.monthlySales}',
                    style: dish.stock == 0
                        ? TextStyle(
                            color: Theme.of(context).colorScheme.error)
                        : null,
                  ),
                  trailing: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      // 缺图从一句混在灰字里的「· 建议配图」提成 chip:
                      // 占位图再好看也不如让商家把图补上,提示得看得见
                      if (dish.imageUrl.isEmpty)
                        Padding(
                          padding: const EdgeInsets.only(right: 4),
                          child: SzChip('缺图',
                              color: Theme.of(context).sz.hold, dense: true),
                        ),
                      // 批量执行中锁掉行内控件:否则能对正在批量处理的
                      // 同一道菜发一个反向请求,最后谁赢看运气
                      if (dish.isOnSale)
                        dish.soldOutToday
                            ? TextButton(
                                onPressed: _batching
                                    ? null
                                    : () => _cancelSellOut(dish),
                                child: const Text('恢复'))
                            : dish.stock > 0
                                ? TextButton(
                                    onPressed: _batching
                                        ? null
                                        : () => _sellOut(dish),
                                    child: const Text('估清'))
                                : TextButton(
                                    onPressed: _batching
                                        ? null
                                        : () => _setStock(dish, 100),
                                    child: const Text('补货')),
                      Switch(
                        value: dish.isOnSale,
                        onChanged: _batching
                            ? null
                            : (v) => _toggleOnSale(dish, v),
                      ),
                    ],
                  ),
                  onTap: _batching
                      ? null
                      : () => _selecting ? _toggleSelect(dish) : _edit(dish),
                ),
            ],
            const SizedBox(height: 80),
          ],
        ),
      );
    }

    return Scaffold(
      body: body,
      // 多选态:底部条给批量动作,别占常驻空间
      bottomNavigationBar: _selecting
          ? SafeArea(
              child: Container(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
                decoration: BoxDecoration(
                  color: Theme.of(context).sz.surface,
                  border: Border(
                      top: BorderSide(color: Theme.of(context).sz.line)),
                ),
                child: Row(children: [
                  Text('已选 ${_selected.length}'),
                  const Spacer(),
                  if (_batching)
                    const Padding(
                      padding: EdgeInsets.only(right: 12),
                      child: SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2)),
                    ),
                  TextButton(
                      onPressed: _batching ? null : _exitSelect,
                      child: const Text('取消')),
                  TextButton(
                      onPressed: _batching ? null : _batchCategory,
                      child: const Text('改分类')),
                  TextButton(
                      onPressed: _batching
                          ? null
                          // 已估清/已售罄的跳过:服务端会 409,
                          // 算进"失败"会让商家以为出了故障
                          : () => _batch(
                                '估清',
                                (id) => widget.api.sellOutDish(id),
                                skip: (d) => d.soldOutToday ||
                                    !d.isOnSale ||
                                    d.stock <= 0,
                              ),
                      child: const Text('估清')),
                  TextButton(
                      onPressed: _batching
                          ? null
                          : () => _batch('下架', (id) => widget.api
                              .updateDish(id, {'is_on_sale': false})),
                      child: const Text('下架')),
                  FilledButton(
                      onPressed: _batching
                          ? null
                          : () => _batch('上架', (id) => widget.api
                              .updateDish(id, {'is_on_sale': true})),
                      child: const Text('上架')),
                ]),
              ),
            )
          : null,
      floatingActionButton: _selecting
          ? null
          : FloatingActionButton.extended(
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
  late final _description =
      TextEditingController(text: widget.dish?.description ?? '');
  late final Set<String> _badges = {...?widget.dish?.badges};
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
    if (!await PermissionRationale.ensure(context, AppPermissionKind.photos,
        reason: '用于选取菜品图片并上传。\n拒绝不影响其他功能。')) {
      return;
    }
    final picked = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1024,
      imageQuality: 85,
    );
    if (picked == null) return;
    setState(() => _uploading = true);
    try {
      final bytes = await picked.readAsBytes();
      final url =
          await widget.api.uploadImage(bytes, picked.name, purpose: 'dish');
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
          description: _description.text.trim(),
          badges: _badges.toList(),
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
          'description': _description.text.trim(),
          'badges': _badges.toList(),
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
                        : Image(image: szNetImage(widget.api.resolveUrl(_imageUrl)),
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
          // 菜品描述:用户点之前想知道"这菜里有什么"。有忌口的人尤其需要
          TextField(
              controller: _description,
              maxLength: 200,
              maxLines: 2,
              decoration: const InputDecoration(
                  labelText: '菜品描述',
                  helperText: '写清用料和口味,有忌口的顾客不用猜',
                  border: OutlineInputBorder())),
          const SizedBox(height: 4),
          Align(
            alignment: Alignment.centerLeft,
            child: Text('标签(最多 4 个,用户端显示角标)',
                style: Theme.of(context).textTheme.bodySmall),
          ),
          const SizedBox(height: 4),
          Wrap(spacing: 6, runSpacing: 2, children: [
            for (final badge in kDishBadges)
              FilterChip(
                label: Text(badge, style: const TextStyle(fontSize: 12)),
                selected: _badges.contains(badge),
                visualDensity: VisualDensity.compact,
                onSelected: (on) => setState(() {
                  if (on && _badges.length < 4) {
                    _badges.add(badge);
                  } else {
                    _badges.remove(badge);
                  }
                }),
              ),
          ]),
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
                          tooltip: '删除',
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
                            tooltip: '减少',
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
