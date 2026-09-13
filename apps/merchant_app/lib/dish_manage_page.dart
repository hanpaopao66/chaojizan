import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

import 'merchant_ui.dart';

/// 菜单(设计稿 6e):左边竖排分类,右边菜品行,每行一个「在售 / 售罄」开关。
///
/// ## 行上那个开关管的是「今天」
///
/// 开 = 在售;关 = **今日售罄**(估清:用户端灰着显示「今日售罄」,
/// 明早 04:00 自动恢复)。高峰时后厨喊一声「肥肠卖完了」,商家要的是这一下,
/// 而不是把菜从菜单上拿掉。
///
/// 永久的上架 / 下架搬进了编辑页和批量操作 —— 它低频,而且拿掉之后
/// 用户就看不到这道菜了,不该和「今天卖完了」长在同一个开关上。
/// 下架了的菜行上照样有开关,拨开就是重新上架。
class DishManagePage extends StatefulWidget {
  const DishManagePage({super.key, required this.api, this.active = true});

  final ApiClient api;

  /// 这一页是不是当前 tab。从别的 tab 切回来时悄悄刷一遍
  final bool active;

  @override
  State<DishManagePage> createState() => _DishManagePageState();
}

class _DishManagePageState extends State<DishManagePage> {
  List<Dish>? _dishes;
  Map<String, dynamic>? _stocking; // 高峰备货建议(纯建议,不自动改)

  /// 分类栏选中的分类。null = 全部。**只影响显示** ——
  /// 批量/置顶/估清这些操作照旧作用在真实的菜上
  String? _activeCategory;

  /// 非空 = 菜单没拉到。「没有菜品」和「没拉到」在这一页含义天差地别
  String _error = '';

  /// 行上开关的「先动起来」:拨下去就按新值画,请求回来(成功或失败)再对齐。
  /// 不这么做的话开关要等一个来回才动,商家会以为没点上又点一下
  final Map<int, bool> _optimistic = {};

  /// 入场动效:第一次拉到菜、下拉刷新时各播一次
  final EnterGate _enter = EnterGate();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(covariant DishManagePage old) {
    super.didUpdateWidget(old);
    // 切回这个 tab:页面一直留着(外层是 IndexedStack),菜可能已经在别处改了
    if (widget.active && !old.active) _load();
  }

  Future<void> _load() async {
    // 两个请求互不依赖,先都发出去再逐个 await
    final dishesF = widget.api.myDishes();
    final stockingF = widget.api.merchantStocking();
    final g = SzGather();
    final dishes = await g.take(dishesF);
    // 备货建议只是锦上添花,拉不到不该拦着改菜单
    final stocking = await g.soft(stockingF, _stocking);

    if (!mounted) return;
    if (g.failed) {
      // 菜单没拉到时**不能**留在"还没有菜品"那一屏 —— 那句话会让商家
      // 以为菜真的没了,跑去重新录一遍
      setState(() => _error = g.message);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(g.message)));
      return;
    }
    setState(() {
      if (_dishes == null) _enter.open();
      _error = '';
      _dishes = dishes;
      _stocking = stocking;
    });
  }

  Future<void> _pull() async {
    setState(() => _enter.open(replay: true));
    await _load();
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  String _errText(Object e) => e is ApiException ? e.message : '$e';

  /// 一键按建议补库存(可能不够卖的菜全部补到建议份数)
  Future<void> _adoptStocking() async {
    final short = (_stocking?['shortlist'] as List?) ?? [];
    if (short.isEmpty) return;
    try {
      await widget.api.batchStock([
        for (final s in short)
          {'dish_id': s['dish_id'] as int, 'stock': s['suggested'] as int},
      ]);
      _snack('已按建议补 ${short.length} 道菜的库存(估清自动解除)');
      _load();
    } catch (e) {
      _snack(_errText(e));
    }
  }

  /// 备货明细:哪几道、现在多少、建议多少,以及这个数是怎么估的。
  ///
  /// 明细从常驻卡片挪进弹层(#33 4.2)。**没有被砍** —— 它是决策依据,
  /// 不是解释:商家要先看见"哪几道菜快不够了"才敢点补货。
  void _stockingSheet() {
    final st = _stocking;
    final short = (st?['shortlist'] as List?) ?? [];
    if (st == null || short.isEmpty) return;
    final sz = Theme.of(context).sz;
    // 走 szShowSheet:宽屏上它自己换成居中对话框。钉在 1440 屏底的弹层
    // 是横贯屏底的一条,内容挤在左边而视线在屏幕中央
    szShowSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(kCardPad, 16, kCardPad, 12),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Expanded(
                child: Text('${st['meal_label']}备货提示',
                    style: TextStyle(
                        fontSize: kFontBodyLg,
                        fontWeight: FontWeight.w600,
                        color: sz.ink)),
              ),
              Text('近 14 天同餐段销量估算',
                  style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
            ]),
            const SizedBox(height: 8),
            for (final s in short)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(children: [
                  Expanded(child: Text('${s['name']}')),
                  Text('现 ${s['stock']} → 建议 ${s['suggested']} 份',
                      style:
                          TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ]),
              ),
            const SizedBox(height: 10),
            Row(children: [
              Expanded(
                child: Text('纯建议,不会自动改库存',
                    style:
                        TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ),
              FilledButton.tonal(
                  onPressed: () {
                    Navigator.of(ctx).pop();
                    _adoptStocking();
                  },
                  child: const Text('一键按建议补货')),
            ]),
          ]),
        ),
      ),
    );
  }

  /// 左边的竖排分类(设计稿 6e)。**两类及以上才出现** —— 只有一类时它是纯噪音。
  ///
  /// 顶上多一格「全部」:设计稿里没有,但原来的分类条就有,
  /// 商家找一道记不清分类的菜时要靠它(选中的分类不存在了也会退回全部)。
  Widget _categoryRail(Map<String, List<Dish>> grouped, String? active) {
    final sz = Theme.of(context).sz;
    final accent = Theme.of(context).colorScheme.primary;
    final total = grouped.values.fold<int>(0, (n, l) => n + l.length);
    Widget item(String label, bool on, VoidCallback onTap) => Material(
          color: on ? sz.surface : Colors.transparent,
          child: InkWell(
            onTap: onTap,
            child: Container(
              width: double.infinity,
              decoration: BoxDecoration(
                border: Border(
                    left: BorderSide(
                        color: on ? accent : Colors.transparent, width: 3)),
              ),
              padding: const EdgeInsets.fromLTRB(9, 14, 8, 14),
              child: Text(label,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      fontSize: kFontBody,
                      height: 1.3,
                      fontWeight: on ? FontWeight.w600 : FontWeight.w400,
                      color: on ? sz.ink : sz.inkMuted)),
            ),
          ),
        );
    return ColoredBox(
      color: sz.surfaceAlt,
      child: ListView(children: [
        item('全部 · $total', active == null,
            () => setState(() => _activeCategory = null)),
        for (final e in grouped.entries)
          item('${e.key} · ${e.value.length}', active == e.key,
              () => setState(() => _activeCategory = e.key)),
      ]),
    );
  }

  /// 提示组:备货 + 菜单体检。两条都是**条件性的**,没事时整组不出现。
  ///
  /// 原先是三张卡 428px(备货卡列明细、缺图卡三行解释、销量榜前三名)。
  /// #33 4.2 压到一组 ~127px:明细进弹层、解释进脚注、**销量榜整块砍掉**
  /// —— 对账页 AnalyticsPage 明说包含「菜品排行」,那是同一份东西的另一份。
  /// 零销量留下,因为它是待办。
  List<Widget> _hintRows({required int noPhoto, required int stale}) {
    final st = _stocking;
    final short = (st?['shortlist'] as List?) ?? [];
    final hasStocking = st != null && short.isNotEmpty;
    final hasCheck = noPhoto > 0 || stale > 0;
    if (!hasStocking && !hasCheck) return const [];
    final sz = Theme.of(context).sz;
    final notes = <String>[
      if (hasStocking) '备货是纯建议,不会自动改库存;点这一条看是哪几道',
      if (noPhoto > 0) '缺图的菜在列表里显示菜名首字占位',
    ];
    Widget rule(Widget child) => DecoratedBox(
          decoration: BoxDecoration(
              border: Border(bottom: BorderSide(color: sz.line))),
          child: child,
        );
    return [
      if (hasStocking)
        rule(SzEntryTile(
          title: '${st['meal_label']}备货提示',
          value: '${short.length} 道可能不够卖',
          valueTone: sz.hold,
          onTap: _stockingSheet,
          trailing: InkWell(
            onTap: _adoptStocking,
            borderRadius: BorderRadius.circular(kRadiusSm),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                color: sz.claySoft,
                borderRadius: BorderRadius.circular(kRadiusSm),
              ),
              child: Text('一键补货',
                  style: TextStyle(fontSize: kFontNote, color: sz.clay)),
            ),
          ),
        )),
      if (hasCheck)
        rule(SzEntryTile(
          title: '菜单体检',
          value: [
            if (noPhoto > 0) '$noPhoto 道缺图',
            if (stale > 0) '$stale 道近 30 天零销量',
          ].join(' · '),
          valueTone: sz.hold,
        )),
      if (notes.isNotEmpty)
        rule(Padding(
          padding: const EdgeInsets.fromLTRB(kCardPad, 6, kCardPad, 8),
          child: Text(notes.join(' · '),
              style: TextStyle(
                  fontSize: kFontMicro, height: 1.5, color: sz.inkMuted)),
        )),
    ];
  }

  Future<void> _edit([Dish? dish]) async {
    final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(
        builder: (_) => DishEditPage(api: widget.api, dish: dish)));
    if (changed == true) _load();
  }

  /// 补货。高峰期缺货一秒处理
  Future<void> _setStock(Dish dish, int stock) async {
    try {
      await widget.api.updateDish(dish.id, {'stock': stock});
      await _load();
      _snack('「${dish.name}」已补货至 $stock');
    } catch (e) {
      _snack(_errText(e));
    }
  }

  /// 库存卖到 0 的菜,拨开关 = 补货。先问补多少 —— 一声不响补成 100 份的话,
  /// 商家以为只是「恢复」,其实库存被改了
  Future<void> _restockPrompt(Dish dish) async {
    final controller =
        TextEditingController(text: '${dish.dailyStock ?? 100}');
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => SzDialog(
        title: Text('「${dish.name}」库存是 0'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('补了货才能接着卖。补到多少份?'),
          const SizedBox(height: 12),
          TextField(
            controller: controller,
            autofocus: true,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
                suffixText: '份', border: OutlineInputBorder()),
          ),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(d, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(d, true),
              child: const Text('补货')),
        ],
      ),
    );
    // controller 不在这里 dispose:弹窗退场动画还要画几帧输入框,
    // 这时候 dispose 会报「用了已释放的 controller」
    final n = int.tryParse(controller.text.trim());
    if (ok != true) return;
    if (n == null || n <= 0) {
      _snack('请输入大于 0 的份数');
      return;
    }
    await _setStock(dish, n);
  }

  /// 置顶:把这道菜排到本分类最前(招牌菜该在第一屏,不该靠改分类名硬凑)。
  /// 只改这一道的 sort,不整体重排 —— 一次请求,失败也不会打乱既有顺序
  Future<void> _pinToTop(Dish dish, List<Dish> sameCategory) async {
    final minSort = sameCategory
        .map((d) => d.sort)
        .fold<int>(0, (a, b) => a < b ? a : b);
    if (sameCategory.isNotEmpty && sameCategory.first.id == dish.id) {
      _snack('「${dish.name}」已经在最前面了');
      return;
    }
    try {
      await widget.api.reorderDishes([
        {'dish_id': dish.id, 'sort': (minSort - 1).clamp(-9999, 9999)},
      ]);
      _load();
      _snack('「${dish.name}」已置顶到「${dish.category}」最前');
    } catch (e) {
      _snack(_errText(e));
    }
  }

  /// 此刻能不能卖:上架、没估清、有库存
  static bool _sellableOf(Dish d) =>
      d.isOnSale && !d.soldOutToday && d.stock > 0;

  bool _sellable(Dish d) => _optimistic[d.id] ?? _sellableOf(d);

  /// 行上的开关。
  ///
  /// - 关:估清(今日售罄),明早 04:00 自动恢复;
  /// - 开:估清的撤销估清;下架的重新上架;库存卖到 0 的先问补多少。
  ///
  /// 服务端 409 是「状态已经变了」(比如另一台手机刚估清过):
  /// 说清楚现在是什么状态,再拉一遍,不当成故障报。
  Future<void> _toggleSellable(Dish dish, bool on) async {
    if (on && dish.isOnSale && !dish.soldOutToday && dish.stock <= 0) {
      await _restockPrompt(dish);
      return;
    }
    setState(() => _optimistic[dish.id] = on);
    try {
      if (!on) {
        await widget.api.sellOutDish(dish.id);
        _snack('「${dish.name}」标为今日售罄,明早 04:00 自动恢复');
      } else if (!dish.isOnSale) {
        await widget.api.updateDish(dish.id, {'is_on_sale': true});
        _snack('「${dish.name}」已重新上架');
      } else {
        final d = await widget.api.cancelSellOut(dish.id);
        _snack(d.stock > 0
            ? '「${dish.name}」恢复在售,库存 ${d.stock}'
            : '「${dish.name}」撤销了售罄,但库存是 0 —— 补货后才能卖');
      }
    } on ApiException catch (e) {
      _snack(e.statusCode == 409
          ? '「${dish.name}」${e.message}(可能另一台设备刚改过),已刷新'
          : e.message);
    } catch (e) {
      _snack(_errText(e));
    }
    await _load();
    if (mounted) setState(() => _optimistic.remove(dish.id));
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
      _snack('$label:选中的菜已经是这个状态了');
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
    _snack(ok == ids.length
        ? '$label:${ids.length} 道已处理$tail'
        : '$label:成功 $ok 道,失败 ${ids.length - ok} 道$tail');
  }

  Future<void> _batchCategory() async {
    final controller = TextEditingController();
    // 控制器跟着对话框卸载时销毁(SzDisposeWith),不在 pop 回来之后马上销毁:对话框那时还在退场
    final category = await showDialog<String>(
      context: context,
      builder: (dialog) => SzDisposeWith(
        controllers: [controller],
        child: SzDialog(
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
      ),
    );
    if (category == null || category.isEmpty) return;
    await _batch('改分类',
        (id) => widget.api.updateDish(id, {'category': category}));
  }

  /// 缩略图。缺图的压一个角标在右下角(#33 4.2)。
  ///
  /// 角标是**压在已有的 48px 上**,零额外高度 —— 它原先在行尾和开关抢一列,
  /// 把菜名挤窄、逼副标题折行。
  Widget _thumb(Dish dish) {
    final img = SzImage(
      url: dish.imageUrl.isEmpty ? '' : widget.api.resolveUrl(dish.imageUrl),
      name: dish.name,
      size: 48,
    );
    if (dish.imageUrl.isNotEmpty) return img;
    final sz = Theme.of(context).sz;
    return SizedBox(
      width: 48,
      height: 48,
      child: Stack(children: [
        img,
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 1),
            decoration: BoxDecoration(
              color: sz.hold.withValues(alpha: 0.85),
              borderRadius: const BorderRadius.vertical(
                  bottom: Radius.circular(kRadiusSm)),
            ),
            child: Text('缺图',
                textAlign: TextAlign.center,
                style: TextStyle(
                    fontSize: kFontMicro - 2, height: 1.3, color: sz.surface)),
          ),
        ),
      ]),
    );
  }

  Widget _categoryHeader(String name) {
    final sz = Theme.of(context).sz;
    return Container(
      padding: const EdgeInsets.fromLTRB(kCardPad, 12, kCardPad, 6),
      decoration:
          BoxDecoration(border: Border(bottom: BorderSide(color: sz.line))),
      child: Text(name,
          style: TextStyle(
              fontSize: kFontNote,
              letterSpacing: 1,
              fontWeight: FontWeight.w600,
              color: sz.inkMuted)),
    );
  }

  /// 行上的副标题:今天卖了几份;卖不了时说为什么、什么时候恢复。
  (String, Color?) _metaOf(Dish d, SzColors sz) {
    final unit = d.unit.isNotEmpty ? d.unit : '份';
    if (!d.isOnSale) return ('已下架 · 用户看不到', sz.inkMuted);
    // 估清 = 今日售罄,次日 04:00 由服务端清扫任务恢复
    if (d.soldOutToday) return ('售罄 · 明早 04:00 自动恢复', sz.inkMuted);
    if (d.stock <= 0) {
      // 卖到 0 不是估清:只有设了每日回满的菜 04:00 会自己回来
      return d.dailyStock != null
          ? ('卖完了 · 明早 04:00 回满 ${d.dailyStock} $unit', sz.inkMuted)
          // 这一种不会自己回来,要人动手:用 hold 提醒
          : ('库存 0 · 补货后才能卖', sz.hold);
    }
    final parts = <String>[
      '今日已卖 ${d.todaySold} $unit',
      // 库存只在「管着库存」的时候说:设了每日回满,或者快卖完了
      if (d.dailyStock != null || d.stock <= 10) '库存 ${d.stock}',
      if (d.flashActive) '限时 · 原价 ${yuan(d.priceCents)}',
    ];
    return (parts.join(' · '), d.stock <= 10 ? sz.hold : null);
  }

  /// 菜品行(设计稿 6e)。[sameCategory] 是同分类的菜,置顶要靠它算最小 sort
  Widget _dishTile(Dish dish, List<Dish> sameCategory) {
    final sz = Theme.of(context).sz;
    final selected = _selected.contains(dish.id);
    final sellable = _sellable(dish);
    final (meta, metaTone) = _metaOf(dish, sz);
    // 卖不了的菜名、价格退一档:还要读得清(不用 inkFaint,那只给装饰)
    final nameColor = sellable ? sz.ink : sz.inkMuted;
    return Material(
      color: selected ? sz.claySoft.withValues(alpha: 0.4) : sz.surface,
      child: InkWell(
        // **长按始终是置顶**:这是上一版就教给商家的手势,
        // 改成"第一次长按进多选、第二次才置顶"会让老用户
        // 按肌肉记忆连按两下,结果置顶了错的那道菜(写库且无撤销)。
        // 多选走标题行「⋯」里的「批量操作」
        onLongPress: _batching
            ? null
            : () => _selecting
                ? _toggleSelect(dish)
                : _pinToTop(dish, sameCategory),
        onTap: _batching
            ? null
            : () => _selecting ? _toggleSelect(dish) : _edit(dish),
        child: Container(
          padding: const EdgeInsets.fromLTRB(kCardPad, 12, kCardPad, 12),
          decoration:
              BoxDecoration(border: Border(bottom: BorderSide(color: sz.line))),
          child: Row(children: [
            _selecting
                ? SizedBox(
                    width: 48,
                    height: 48,
                    child: Icon(
                      selected
                          ? Icons.check_circle
                          : Icons.radio_button_unchecked,
                      color: selected
                          ? Theme.of(context).colorScheme.primary
                          : sz.inkMuted,
                    ),
                  )
                : _thumb(dish),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(dish.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: kFontBodyLg + 0.5,
                          fontWeight: FontWeight.w600,
                          color: nameColor)),
                  const SizedBox(height: 2),
                  Text(meta,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                          fontSize: kFontNote,
                          height: 1.35,
                          color: metaTone ?? sz.inkMuted)),
                ],
              ),
            ),
            const SizedBox(width: 8),
            // 价格在上、开关在下。开关的点击区是 48(戴手套也按得到),
            // 视觉只有 36×20,多出来的那圈压在行的留白上,不把行撑高
            SizedBox(
              height: 48,
              child: Stack(
                clipBehavior: Clip.none,
                alignment: Alignment.topRight,
                children: [
                  Text(yuan(dish.effectivePriceCents),
                      style: szMoney(
                          fontSize: kFigureSm,
                          fontWeight: FontWeight.w600,
                          color: nameColor)),
                  Positioned(
                    right: -6,
                    top: 12,
                    child: SzSwitch(
                      small: true,
                      value: sellable,
                      // 读屏用户听到的只有"开关",不知道是哪道菜的 ——
                      // 按错了整天卖不出去
                      semanticLabel:
                          '${dish.name} ${sellable ? "在售" : "售罄"}',
                      // 批量执行中锁掉行内开关:否则能对正在批量处理的
                      // 同一道菜发一个反向请求,最后谁赢看运气
                      onChanged: _batching || _selecting
                          ? null
                          : (v) => _toggleSellable(dish, v),
                    ),
                  ),
                ],
              ),
            ),
          ]),
        ),
      ),
    );
  }

  /// 「18 个在售 · 2 售罄」。下架的菜也在列表里,有就一并说出来
  String _countsLabel(List<Dish> dishes) {
    final onSale = dishes.where(_sellableOf).length;
    final soldOut =
        dishes.where((d) => d.isOnSale && !_sellableOf(d)).length;
    final off = dishes.where((d) => !d.isOnSale).length;
    return [
      '$onSale 个在售',
      if (soldOut > 0) '$soldOut 售罄',
      if (off > 0) '$off 下架',
    ].join(' · ');
  }

  /// 标题行(设计稿 6e):菜单 + 在售/售罄数 + 添加 + 「⋯」(批量、备货)
  Widget _header() {
    final sz = Theme.of(context).sz;
    final dishes = _dishes;
    final hasStocking =
        ((_stocking?['shortlist'] as List?) ?? const []).isNotEmpty;
    return SizedBox(
      height: 56,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 0, 4, 0),
        child: Row(children: [
          Expanded(
            child: Text('菜单',
                style: Theme.of(context).appBarTheme.titleTextStyle),
          ),
          if (dishes != null && dishes.isNotEmpty)
            Flexible(
              child: Text(_countsLabel(dishes),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
            ),
          const SizedBox(width: 10),
          if (!_selecting)
            FilledButton.icon(
              onPressed: () => _edit(),
              icon: const Icon(Icons.add, size: 18),
              label: const Text('添加'),
              style: smallFilledStyle().copyWith(
                padding: const WidgetStatePropertyAll(
                    EdgeInsets.fromLTRB(10, 0, 12, 0)),
              ),
            ),
          PopupMenuButton<String>(
            tooltip: '更多',
            icon: const Icon(Icons.more_horiz),
            onSelected: (v) {
              switch (v) {
                case 'batch':
                  setState(() => _selectMode = true);
                case 'stocking':
                  _stockingSheet();
              }
            },
            itemBuilder: (_) => [
              // 多选的显式入口(长按留给置顶,不重载手势)
              const PopupMenuItem(
                value: 'batch',
                child: ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.checklist, size: 20),
                  title: Text('批量操作'),
                  subtitle: Text('上架 · 下架 · 估清 · 改分类'),
                ),
              ),
              if (hasStocking)
                const PopupMenuItem(
                  value: 'stocking',
                  child: ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(Icons.inventory_2_outlined, size: 20),
                    title: Text('备货建议'),
                  ),
                ),
            ],
          ),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final dishes = _dishes;
    Widget body;
    if (dishes == null) {
      body = _error.isNotEmpty
          ? SzError(error: _error, onRetry: _load)
          : const Center(child: CircularProgressIndicator());
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
      // 菜单体检的两个数。零销量是待办;窗口是服务端的滚动 30 天,
      // 所以文案写「近 30 天」,不写「本月」
      final stale =
          dishes.where((d) => d.isOnSale && d.monthlySales == 0).length;
      final noPhoto = dishes.where((d) => d.imageUrl.isEmpty).length;

      // 选中的分类不存在了(改分类/删菜之后)就自动回到全部,
      // 否则商家会盯着一个空列表以为菜没了
      final active =
          grouped.containsKey(_activeCategory) ? _activeCategory : null;

      // 把「分类标题 + 该分类下的菜」拍平成一维,交给 ListView.builder 按需构建。
      // 原来是 ListView(children: [...]):菜单上百道时,首帧要把每一行的缩略图、
      // 开关全建出来 —— 而卡住的那几百毫秒,商家正在接单
      final rows = <_MenuRow>[];
      for (final entry in grouped.entries) {
        if (active != null && entry.key != active) continue;
        // 只筛出一个分类时不再重复它的名字 —— 左边分类栏上已经高亮着
        if (active == null && grouped.length > 1) {
          rows.add(_MenuRow.header(entry.key));
        }
        for (final dish in entry.value) {
          rows.add(_MenuRow.dish(dish, entry.value));
        }
      }
      final leading = _hintRows(noPhoto: noPhoto, stale: stale);
      final list = ColoredBox(
        color: sz.surface,
        child: RefreshIndicator(
          onRefresh: _pull,
          child: ListView.builder(
            key: ValueKey('menu-${_enter.epoch}'),
            // +1 是尾部那句手势说明
            itemCount: leading.length + rows.length + 1,
            itemBuilder: (context, i) {
              if (i < leading.length) return leading[i];
              final j = i - leading.length;
              if (j >= rows.length) {
                return Padding(
                  padding: const EdgeInsets.fromLTRB(kCardPad, 12, kCardPad, 32),
                  child: Text('点一道菜改价、改库存、上下架;长按置顶到本分类最前',
                      style: TextStyle(
                          fontSize: kFontMicro, height: 1.5, color: sz.inkMuted)),
                );
              }
              final row = rows[j];
              final dish = row.dish;
              if (dish == null) return _categoryHeader(row.category!);
              return EnterOnce(
                key: ValueKey(dish.id),
                gate: _enter,
                index: j,
                child: _dishTile(dish, row.siblings),
              );
            },
          ),
        ),
      );
      body = grouped.length < 2
          ? list
          : LayoutBuilder(builder: (context, c) {
              // 窄屏 88(设计稿),宽屏放宽 —— 长分类名在 88 里要折两行
              final rail = c.maxWidth >= 900 ? 168.0 : 88.0;
              return Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SizedBox(width: rail, child: _categoryRail(grouped, active)),
                    Expanded(child: list),
                  ]);
            });
    }

    return Scaffold(
      body: Column(children: [
        _header(),
        Expanded(child: body),
      ]),
      // 多选态:底部条给批量动作,别占常驻空间
      bottomNavigationBar: _selecting
          ? SafeArea(
              child: Container(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
                decoration: BoxDecoration(
                  color: sz.surface,
                  border: Border(top: BorderSide(color: sz.line)),
                ),
                // 动作一排五个,窄屏大字放不下时横着滑,一个都不藏
                child: Row(children: [
                  Text('已选 ${_selected.length}'),
                  const SizedBox(width: 8),
                  Expanded(
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      reverse: true,
                      child: Row(mainAxisSize: MainAxisSize.min, children: [
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
                  ),
                ]),
              ),
            )
          : null,
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
  // 成本(元/份)。0 = 没录过 → 输入框留空,别显示成 0.00 让人以为录过了
  late final _cost = TextEditingController(
      text: (widget.dish?.costCents ?? 0) == 0
          ? ''
          : (widget.dish!.costCents / 100).toStringAsFixed(2));
  // 额外打包费(元/份);空 = 用店铺的每单打包费
  late final _packing = TextEditingController(
      text: widget.dish?.packingFeeCents == null
          ? ''
          : (widget.dish!.packingFeeCents! / 100).toStringAsFixed(2));
  late final _stock =
      TextEditingController(text: '${widget.dish?.stock ?? 100}');

  /// 卖价与成本都填了才给毛利。**明说不含平台佣金与配送** ——
  /// 那是订单层面的,摊到单个菜上的数不能拿来定价。
  String? get _grossHint {
    final p = double.tryParse(_price.text);
    final c = double.tryParse(_cost.text);
    if (p == null || c == null || p <= 0) return null;
    final pct = ((p - c) / p * 100).round();
    return '毛利 ¥${(p - c).toStringAsFixed(2)}($pct%)'
        ' —— 卖价 − 进价,不含平台佣金与配送';
  }
  // 每日回满目标(空=不启用)
  late final _dailyStock = TextEditingController(
      text: widget.dish?.dailyStock == null ? '' : '${widget.dish!.dailyStock}');
  late final _description =
      TextEditingController(text: widget.dish?.description ?? '');
  late final Set<String> _badges = {...?widget.dish?.badges};
  late final _serveWindow =
      TextEditingController(text: widget.dish?.serveWindow ?? '');
  late String _imageUrl = widget.dish?.imageUrl ?? '';
  late bool _isAlcohol = widget.dish?.isAlcohol ?? false;

  /// 上架(在菜单里显示)。列表行上的开关改管「今日售罄」之后,
  /// 永久的上下架落在这里和批量操作里
  late bool _onSale = widget.dish?.isOnSale ?? true;
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
    final costCents = _cost.text.trim().isEmpty
        ? 0
        : ((double.tryParse(_cost.text) ?? 0) * 100).round();
    // null 有语义:清回"用店铺默认"。所以空串 → null,而不是 0
    final packingCents = _packing.text.trim().isEmpty
        ? null
        : ((double.tryParse(_packing.text) ?? 0) * 100).round();
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
          serveWindow: _serveWindow.text.trim(),
          options: options,
          dailyStock: dailyStock,
          isAlcohol: _isAlcohol,
        );
      } else {
        await widget.api.updateDish(widget.dish!.id, {
          'name': _name.text.trim(),
          'category': _category.text.trim(),
          'price_cents': priceCents,
          'cost_cents': costCents,
          'packing_fee_cents': packingCents,
          'stock': stock,
          'daily_stock': dailyStock, // null = 关闭每日回满
          'is_alcohol': _isAlcohol,
          'is_on_sale': _onSale,
          'image_url': _imageUrl,
          'description': _description.text.trim(),
          'badges': _badges.toList(),
          'serve_window': _serveWindow.text.trim(),
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
    return SzPageScaffold(
      appBar: AppBar(title: Text(widget.dish == null ? '新增菜品' : '编辑菜品')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 价格 / 库存提到最顶(#33 4.2)。
          //
          // 改一道菜的价格是这一页最高频的动作,而原来价格框在第二屏、
          // 保存在第三屏 —— 一次改价 2 触摸 + 2 滚动。现在两个框和常驻的
          // 保存条都在首屏,0 滚动。
          //
          // 上下架在这一页的最下面(见「上架」开关):列表行上的开关
          // 2026-09 起管的是「今日售罄」,永久下架是低频动作,不和它挤一处。
          Row(children: [
            Expanded(
              child: TextField(
                  controller: _price,
                  onChanged: (_) => setState(() {}),
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
              controller: _name,
              decoration: const InputDecoration(
                  labelText: '菜名 *', border: OutlineInputBorder())),
          const SizedBox(height: 12),
          // 图片挪到菜名之后:它是这一页最占地方的一块(120px),
          // 但换图的频次远低于改价改库存
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
                              const Text('选菜品图', style: TextStyle(fontSize: kFontNote)),
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
                label: Text(badge, style: const TextStyle(fontSize: kFontNote)),
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
          // 供应时段:早餐/夜宵这类只在某个时段卖的菜。
          // 留空 = 全天;非供应时段用户端置灰不消失
          TextField(
              controller: _serveWindow,
              decoration: const InputDecoration(
                  labelText: '供应时段(选填)',
                  hintText: '06:00-10:30',
                  helperText: '留空=全天供应;非供应时段顾客看得到但点不了',
                  border: OutlineInputBorder())),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: TextField(
                  controller: _cost,
                  onChanged: (_) => setState(() {}),
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(
                      labelText: '成本(元/份)',
                      helperText: '只你自己看得到,填了才有毛利',
                      helperMaxLines: 2,
                      border: OutlineInputBorder())),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                  controller: _packing,
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  decoration: const InputDecoration(
                      labelText: '额外打包费(元)',
                      helperText: '空=只收店铺每单那笔;填了另加',
                      helperMaxLines: 2,
                      border: OutlineInputBorder())),
            ),
          ]),
          if (_grossHint != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_grossHint!,
                  style: TextStyle(
                      fontSize: kFontNote,
                      color: Theme.of(context).colorScheme.onSurfaceVariant)),
            ),
          const SizedBox(height: 12),
          TextField(
              controller: _dailyStock,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                  labelText: '每日回满(份,留空不启用)',
                  helperText: '设置后每天凌晨 4 点库存自动重置为该值,估清同时解除',
                  border: OutlineInputBorder())),
          const SizedBox(height: 4),
          if (widget.dish != null)
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('上架(在菜单里显示)'),
              subtitle: const Text(
                  '关掉就是下架,用户看不到这道菜。只是今天卖完了的话,'
                  '用菜单列表里那个开关标售罄,明早 04:00 自动恢复',
                  style: TextStyle(fontSize: kFontMicro)),
              value: _onSale,
              onChanged: (v) => setState(() => _onSale = v),
            ),
          // 酒类标记:依法只售成年人,勾选后用户须实名且成年才能下单
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('酒类商品'),
            subtitle: const Text('勾选后用户需实名认证且年满 18 岁才能购买;小票与骑手端会提示查验收件人',
                style: TextStyle(fontSize: kFontMicro)),
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
          // 底部留白:给常驻保存条让位,否则最后一组规格会被压在条底下
          const SizedBox(height: 24),
        ],
      ),
      // 保存常驻底部(#33 4.2):原来它在页面最末,改完价格要一路滚到底才存得了,
      // 而规格/加料多的菜这一路有两三屏
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
          child: FilledButton(
            onPressed: _saving ? null : _save,
            child: Text(_saving ? '保存中…' : '保存'),
          ),
        ),
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

/// 拍平后的一行:要么是分类标题,要么是一道菜。
///
/// 为的是能用 `ListView.builder` —— 「分类嵌菜品」的两层结构没法直接按需构建
class _MenuRow {
  const _MenuRow.header(this.category)
      : dish = null,
        siblings = const [];

  const _MenuRow.dish(this.dish, this.siblings) : category = null;

  final String? category;
  final Dish? dish;

  /// 同分类的菜,置顶时要靠它算最小 sort
  final List<Dish> siblings;
}
