import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 在菜品详情页里选好的:规格(按规格组的顺序)和份数。
typedef DishPick = ({List<String> choices, int quantity});

/// 菜品详情(设计稿 D):图、菜名与描述、标签、规格组、明细、底栏合计。
///
/// 替掉原来的两个底部弹层 —— 点菜名弹的「详情」和点 + 弹的「选规格」。
/// 原来描述、库存、打包费看得到的地方选不了规格,选规格的地方又看不到这些;
/// 这一页把 [Dish] 已有的字段全摊开,底栏实时算合计。
///
/// 加购不在这里直接改购物车:确认后 pop 一个 [DishPick],由店铺页并进购物车
/// (同菜同规格合并一行)。这样购物车只有店铺页一个写入口。
///
/// ⚠️ 设计稿上的「这道菜的评价 4.9 分 · 31 条」没有做:评价挂在订单上,
/// 不挂在菜上,服务端没有按菜聚合的数。要做得先加接口。
class DishDetailPage extends StatefulWidget {
  const DishDetailPage({
    super.key,
    required this.api,
    required this.shop,
    required this.dish,
    this.inCart = 0,
    this.onShare,
  });

  final ApiClient api;
  final Merchant shop;
  final Dish dish;

  /// 这道菜已经在购物车里的份数(各规格合计)。能加的上限 = 库存 − 它
  final int inCart;

  /// 右上角的分享(店铺卡,这道菜排第一);不给就不画那个按钮
  final VoidCallback? onShare;

  @override
  State<DishDetailPage> createState() => _DishDetailPageState();
}

class _DishDetailPageState extends State<DishDetailPage> {
  /// 每个规格组选中了哪些。**按组存,不按选项名存** —— 两个组里可以有
  /// 同名的选项(「不要」),按名字存的话点一个组,另一个组跟着亮
  late final List<Set<String>> _picked = [
    for (final g in widget.dish.options)
      // 必选组默认选第一项(和原来的规格弹层同一口径):
      // 份量这种组一进来就有个合法的选择,不用每次都点
      {if (g.required_ && g.choices.isNotEmpty) g.choices.first.name},
  ];

  int _qty = 1;

  Dish get _dish => widget.dish;

  /// 还能加几份
  int get _room => _dish.stock - widget.inCart;

  bool get _unavailable =>
      _dish.stock <= 0 || _dish.soldOutToday || !_dish.servableNow;

  /// 按组的顺序排好的选项名(服务端 resolve_options 也是按组的顺序认)
  List<String> get _choices => [
        for (final (i, g) in _dish.options.indexed)
          for (final c in g.choices)
            if (_picked[i].contains(c.name)) c.name,
      ];

  int get _unitCents {
    var total = _dish.effectivePriceCents;
    for (final (i, g) in _dish.options.indexed) {
      for (final c in g.choices) {
        if (_picked[i].contains(c.name)) total += c.deltaCents;
      }
    }
    return total;
  }

  /// 还没选的必选组(第一个);都选了是 null
  OptionGroup? get _missing {
    for (final (i, g) in _dish.options.indexed) {
      if (g.required_ && _picked[i].isEmpty) return g;
    }
    return null;
  }

  void _tap(int groupIndex, OptionChoice c) {
    final g = _dish.options[groupIndex];
    final set = _picked[groupIndex];
    setState(() {
      if (set.contains(c.name)) {
        // 必选的单选组不许点空(换一个选就行);其余都能取消
        if (!(g.required_ && !g.multi)) set.remove(c.name);
      } else {
        if (!g.multi) set.clear();
        set.add(c.name);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      body: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _hero(context),
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 13, kPagePad, 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _intro(sz),
                  if (_dish.options.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Divider(color: sz.line),
                    for (final (i, g) in _dish.options.indexed) ...[
                      const SizedBox(height: 12),
                      _group(sz, i, g),
                    ],
                  ],
                  if (_showBreakdown) ...[
                    const SizedBox(height: 14),
                    _breakdown(sz),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
      bottomNavigationBar: _bottomBar(sz),
    );
  }

  // ---------- 图 ----------

  Widget _hero(BuildContext context) {
    final sz = Theme.of(context).sz;
    final top = MediaQuery.paddingOf(context).top;
    final hasPhoto = _dish.imageUrl.isNotEmpty;
    return Stack(
      children: [
        // 图从屏幕顶上铺下来,状态栏压在图上(设计稿 212 里含 38 的状态栏);
        // 刘海更高的机器往下多让出那一截,图下沿不跟着缩
        SzCover(
          url: hasPhoto ? widget.api.resolveUrl(_dish.imageUrl) : '',
          name: _dish.name,
          height: 212 + (top > 38 ? top - 38 : 0),
        ),
        // 按钮画 34、点击区 44:四周各多出 5,所以定位比视觉位置少 5
        Positioned(
          top: top + 1,
          left: 9,
          child: _RoundButton(
            icon: Icons.chevron_left,
            label: '返回',
            onTap: () => Navigator.of(context).maybePop(),
          ),
        ),
        if (widget.onShare != null)
          Positioned(
            top: top + 1,
            right: 9,
            child: _RoundButton(
              icon: Icons.share_outlined,
              label: '分享',
              onTap: widget.onShare!,
            ),
          ),
        // 图是商家传的,平台不修图 —— 只在真有图的时候说;占位色块不是「图」
        if (hasPhoto)
          Positioned(
            left: 14,
            bottom: 12,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
              decoration: BoxDecoration(
                color: sz.ledger.withValues(alpha: .72),
                borderRadius: BorderRadius.circular(999),
              ),
              child: Text('商家上传 · 平台不修图',
                  style: TextStyle(fontSize: kFontMicro, color: sz.paper)),
            ),
          ),
      ],
    );
  }

  // ---------- 主体 ----------

  Widget _intro(SzColors sz) {
    final d = _dish;
    final chips = <Widget>[
      for (final b in d.badges)
        SzChip(b,
            dense: true,
            // 忌口类关乎安全,用醒目色(和菜单行同一口径)
            color: kAllergenBadges.contains(b) ? sz.danger : null),
      if (d.isAlcohol) SzChip('酒', dense: true, color: sz.hold),
      if (d.monthlySales > 0)
        SzChip('月售 ${d.monthlySales}', dense: true, textColor: sz.inkMuted),
      if (!_unavailable)
        // 设了「每日回满」的菜,库存每天 04:00 回到目标值 —— 这时它就是「今天还剩几份」;
        // 没设的是一个长期库存数,不能说成「今日」
        d.dailyStock != null
            ? SzChip('今日还剩 ${d.stock} 份', dense: true, textColor: sz.hold)
            : SzChip('库存 ${d.stock} 份', dense: true, textColor: sz.inkMuted),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(d.name,
            style: Theme.of(context)
                .textTheme
                .titleLarge
                ?.copyWith(letterSpacing: -0.2)),
        if (d.description.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(d.description,
              style: TextStyle(
                  fontSize: kFontBody, height: 1.6, color: sz.inkMuted)),
        ],
        if (d.isCombo && d.comboDishes.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(
              '含 ${d.comboDishes.map((c) => '${c['name']}×${c['quantity']}').join(' + ')}',
              style: TextStyle(
                  fontSize: kFontBody, height: 1.6, color: sz.inkMuted)),
        ],
        if (chips.isNotEmpty) ...[
          const SizedBox(height: 8),
          Wrap(spacing: 6, runSpacing: 6, children: chips),
        ],
        if (d.isAlcohol) ...[
          const SizedBox(height: 8),
          Text('酒类商品:未成年人禁止购买,下单需完成实名认证',
              style: TextStyle(
                  fontSize: kFontNote,
                  fontWeight: FontWeight.w600,
                  color: sz.hold)),
        ],
        const SizedBox(height: 10),
        Wrap(
          crossAxisAlignment: WrapCrossAlignment.end,
          spacing: 8,
          children: [
            Text(yuan(d.effectivePriceCents),
                style: szMoney(fontSize: kFigureLg, color: sz.ink)),
            if (d.flashActive)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(yuan(d.priceCents),
                    style: TextStyle(
                        fontSize: kFontNote,
                        color: sz.inkMuted,
                        decoration: TextDecoration.lineThrough)),
              ),
            if (d.comboSaveCents > 0)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                    '单点合计 ${yuan(d.comboOriginalCents)},省 ${yuan(d.comboSaveCents)}',
                    style: TextStyle(fontSize: kFontNote, color: sz.earn)),
              ),
            if (d.hasOptions)
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text('起 · 按所选规格计价',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
          ],
        ),
      ],
    );
  }

  Widget _group(SzColors sz, int i, OptionGroup g) {
    final tag = g.required_
        ? (g.multi ? '必选 · 可多选' : '必选')
        : (g.multi ? '可多选' : '可不选');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text(g.name,
                style: TextStyle(
                    fontSize: kFontBodyLg,
                    fontWeight: FontWeight.w600,
                    color: sz.ink)),
            const SizedBox(width: 8),
            Text(tag,
                style: TextStyle(
                    fontSize: kFontMicro,
                    color: g.required_ ? sz.clay : sz.inkMuted)),
          ],
        ),
        const SizedBox(height: 9),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final c in g.choices)
              SzChip(
                c.deltaCents > 0 ? '${c.name} +${yuan(c.deltaCents)}' : c.name,
                selected: _picked[i].contains(c.name),
                onTap: () => _tap(i, c),
              ),
          ],
        ),
      ],
    );
  }

  /// 有规格、或者有打包费,才值得单列一张明细;一道没规格没打包费的菜,
  /// 明细就是它自己的价钱,底栏已经写了
  bool get _showBreakdown =>
      _dish.hasOptions ||
      (_dish.packingFeeCents ?? 0) > 0 ||
      widget.shop.packingFeeCents > 0;

  Widget _breakdown(SzColors sz) {
    final dishPack = _dish.packingFeeCents ?? 0;
    final shopPack = widget.shop.packingFeeCents;
    final picked = _choices;
    final what = picked.isEmpty ? _dish.name : picked.join(' + ');
    Widget line(String label, int cents, {bool strong = false}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Expanded(
                child: Text(label,
                    style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
              ),
              const SizedBox(width: 8),
              Text(yuan(cents),
                  style: szMoney(
                      fontSize: kFontBody,
                      fontWeight: strong ? FontWeight.w600 : FontWeight.w400,
                      color: sz.ink)),
            ],
          ),
        );
    final notes = [
      // 店铺那笔是**每单一次**,菜品这笔是**每份**另加(服务端 orders.py 同口径)
      if (shopPack > 0) '店铺另收打包费 ${yuan(shopPack)} / 单,结算时算',
      if (dishPack > 0 || shopPack > 0)
        '打包费在 ${widget.shop.commissionPct}% 抽成基数里,配送费不在',
    ];
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 9, 14, 9),
      decoration: BoxDecoration(
        color: sz.surface,
        border: Border.all(color: sz.line),
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          line(_qty > 1 ? '$what × $_qty' : what, _unitCents * _qty,
              strong: true),
          if (dishPack > 0)
            line('打包费 · 每份 ${yuan(dishPack)}', dishPack * _qty),
          if (notes.isNotEmpty)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(top: 4),
              padding: const EdgeInsets.only(top: 6),
              decoration: BoxDecoration(
                  border: Border(top: BorderSide(color: sz.line))),
              child: Text(notes.join('\n'),
                  style: TextStyle(
                      fontSize: kFontNote, height: 1.6, color: sz.inkMuted)),
            ),
        ],
      ),
    );
  }

  // ---------- 底栏 ----------

  String get _unavailableText {
    if (_dish.soldOutToday) return '今日售罄 · 明天自动恢复';
    if (_dish.stock <= 0) {
      return _dish.dailyStock != null ? '已售罄 · 明天自动补货' : '已售罄 · 等商家补货';
    }
    return '现在不供应 · 每天 ${_dish.serveWindow} 供应';
  }

  Widget _bottomBar(SzColors sz) {
    final Widget content;
    if (_unavailable) {
      content = Center(
        child: Text(_unavailableText,
            style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
      );
    } else {
      final missing = _missing;
      final full = _room < 1;
      content = Row(
        children: [
          SzStepper(
            quantity: _qty,
            onAdd: () {
              if (_qty < _room) setState(() => _qty++);
            },
            onRemove: _qty > 1 ? () => setState(() => _qty--) : null,
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(yuan(_unitCents * _qty),
                textAlign: TextAlign.right,
                maxLines: 1,
                style: szMoney(fontSize: kFontLead, color: sz.ink)),
          ),
          const SizedBox(width: 10),
          FilledButton(
            style: FilledButton.styleFrom(
              minimumSize: const Size(0, 42),
              padding: const EdgeInsets.symmetric(horizontal: 18),
            ),
            onPressed: missing != null || full
                ? null
                : () => Navigator.of(context)
                    .pop<DishPick>((choices: _choices, quantity: _qty)),
            child: Text(missing != null
                ? '请选择${missing.name}'
                : full
                    ? '库存都在购物车里了'
                    : '加入购物车'),
          ),
        ],
      );
    }
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 6, 12, 14),
        child: Container(
          height: 58,
          padding: const EdgeInsets.fromLTRB(6, 0, 8, 0),
          decoration: BoxDecoration(
            color: _unavailable ? sz.surfaceAlt : sz.surface,
            border: Border.all(color: sz.line),
            borderRadius: BorderRadius.circular(kRadiusLg),
          ),
          child: content,
        ),
      ),
    );
  }
}

/// 图上的圆形按钮:半透明卡片底,压在任何菜品图上都看得见
class _RoundButton extends StatelessWidget {
  const _RoundButton(
      {required this.icon, required this.label, required this.onTap});

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Semantics(
      button: true,
      label: label,
      child: Material(
        type: MaterialType.transparency,
        child: InkWell(
          onTap: onTap,
          customBorder: const CircleBorder(),
          child: SizedBox(
            width: 44,
            height: 44,
            child: Center(
              child: Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: sz.surface.withValues(alpha: .86),
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, size: 20, color: sz.ink),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
