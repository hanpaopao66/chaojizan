import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import 'checkout_page.dart';
import 'dish_detail_page.dart';

/// 拼单页(设计稿 G 发起人 / H 同伴):拼单码、车上的人、按人分组的「已点」、加菜。
/// 发起人锁单后去结算(一次性支付,AA 线下自行解决)。3 秒轮询同步。
///
/// 机制照服务端 group_cart.py:码是 6 位数字、从开车起 2 小时有效(改菜不续期);
/// 各自只能改自己点的;锁单后谁都不能改菜,发起人可以解锁;
/// 下单时这车原子关掉,订单只记在发起人名下。
///
/// 车里的一行 = (谁, 菜, 规格, 备注)。带规格的菜进菜品详情选(和店铺页同一页,
/// 多一个备注框);单价服务端按规格算,备注下单时并进订单备注。
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

class _GroupCartPageState extends State<GroupCartPage>
    with WidgetsBindingObserver {
  Map<String, dynamic>? _cart;
  String? _error;
  List<Dish> _dishes = [];
  Timer? _timer;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _sync());
  }

  /// 拼单同步:3 秒一次很费电,退到后台就停,回前台立刻同步一次
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _sync();
      _timer?.cancel();
      _timer = Timer.periodic(const Duration(seconds: 3), (_) => _sync());
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden) {
      _timer?.cancel();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final dishes = await widget.api.menu(widget.merchant.id);
      if (mounted) setState(() => _dishes = dishes);
    } catch (_) {}
    await _sync();
  }

  Future<void> _sync() async {
    try {
      final c = await widget.api.getGroupCart(widget.code);
      // 拉成功要把上次的错清掉:出错页排在前面判断,不清的话重试回不来
      if (mounted) {
        setState(() {
          _cart = c;
          _error = null;
        });
      }
    } catch (e) {
      if (!mounted) return;
      if (e.toString().contains('过期') || e.toString().contains('不存在')) {
        _timer?.cancel();
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('这车拼单已结束(已下单或超 2 小时过期)')));
        Navigator.of(context).pop();
      } else if (_cart == null) {
        // 第一次就没拉到:给出错页和重试,别一直转圈
        setState(() => _error = e.toString());
      }
    }
  }

  int? get _me => _cart?['me'] as int?;

  List<Map<String, dynamic>> get _items =>
      ((_cart?['items'] as List?) ?? const []).cast<Map<String, dynamic>>();

  static List<String> _choicesOf(Map<String, dynamic> i) =>
      ((i['choices'] as List?) ?? const []).cast<String>();

  static String _noteOf(Map<String, dynamic> i) =>
      ((i['note'] as String?) ?? '').trim();

  /// 我的某一行:同菜、同一组规格(先后顺序不算)、同一句备注 —— 和服务端
  /// group_cart.line_key 一个判法
  Map<String, dynamic>? _myLine(int dishId, List<String> choices, String note) {
    final want = {...choices};
    for (final i in _items) {
      final c = _choicesOf(i);
      if (i['uid'] == _me &&
          i['dish_id'] == dishId &&
          c.length == want.length &&
          want.containsAll(c) &&
          _noteOf(i) == note.trim()) {
        return i;
      }
    }
    return null;
  }

  /// 我点的这道菜一共几份(各规格、各备注合计;「选规格」上的角标)
  int _myQtyOf(int dishId) => _items
      .where((i) => i['uid'] == _me && i['dish_id'] == dishId)
      .fold(0, (a, i) => a + (i['quantity'] as int));

  /// 整车这道菜一共几份:下单时是一起扣库存的,加菜按它封顶
  int _cartQtyOf(int dishId) => _items
      .where((i) => i['dish_id'] == dishId)
      .fold(0, (a, i) => a + (i['quantity'] as int));

  int _sum(Iterable<Map<String, dynamic>> items) => items.fold(
      0, (a, i) => a + (i['price_cents'] as int) * (i['quantity'] as int));

  /// 设自己某一行的份数(0 = 删掉这一行)
  Future<void> _setLine(int dishId, int qty,
      {List<String> choices = const [], String note = ''}) async {
    try {
      final c = await widget.api.setGroupCartItem(widget.code, dishId, qty,
          choices: choices, note: note);
      if (mounted) setState(() => _cart = c);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 进菜品详情选规格、份数、写备注;选好的并进自己同规格同备注的那一行
  Future<void> _openDish(Dish d) async {
    final pick = await Navigator.of(context).push<DishPick>(MaterialPageRoute(
      builder: (_) => DishDetailPage(
        api: widget.api,
        shop: widget.merchant,
        dish: d,
        inCart: _cartQtyOf(d.id),
        forGroupCart: true,
      ),
    ));
    if (pick == null || !mounted) return;
    final line = _myLine(d.id, pick.choices, pick.note);
    await _setLine(d.id, (line?['quantity'] as int? ?? 0) + pick.quantity,
        choices: pick.choices, note: pick.note);
  }

  /// 自己那一行的加减(已点里、加菜里的步进器都走这里)
  void _bump(Map<String, dynamic>? line, Dish? dish, int delta, {int? dishId}) {
    final id = dishId ?? line!['dish_id'] as int;
    final qty = (line?['quantity'] as int? ?? 0) + delta;
    if (qty < 0) return;
    // 整车这道菜的份数到库存了就不给加(菜单没拉到时交给服务端)
    if (delta > 0 && dish != null && _cartQtyOf(id) >= dish.stock) return;
    _setLine(id, qty,
        choices: line == null ? const [] : _choicesOf(line),
        note: line == null ? '' : _noteOf(line));
  }

  Future<void> _checkout() async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final locked = _cart?['locked'] == true
          ? _cart!
          : await widget.api.lockGroupCart(widget.code);
      if (!mounted) return;
      setState(() => _cart = locked);
      if (_dishes.isEmpty) {
        // 进页面时菜单没拉到:结算前再拉一次,不然每道菜都会被当成「找不到了」
        try {
          final dishes = await widget.api.menu(widget.merchant.id);
          if (mounted) setState(() => _dishes = dishes);
        } catch (_) {}
        if (!mounted) return;
      }
      final byId = {for (final d in _dishes) d.id: d};
      final lines = <CartLine>[];
      final missing = <String>[];
      for (final i in (locked['items'] as List).cast<Map<String, dynamic>>()) {
        final dish = byId[i['dish_id']];
        if (dish == null) {
          missing.add('${i['name']}');
          continue;
        }
        // 规格照车里的带上(下单时服务端按它计价);不同人点的同菜同规格并成一行,
        // 各自的备注由服务端从车里取,并进订单备注
        final choices = _choicesOf(i);
        final same = lines.where((l) => l.sameAs(dish, choices)).firstOrNull;
        if (same != null) {
          same.quantity += i['quantity'] as int;
        } else {
          lines.add(CartLine(
              dish: dish,
              choices: List.of(choices),
              quantity: i['quantity'] as int));
        }
      }
      // 车里有菜在菜单里找不到(刚下架):原来是悄悄跳过,结算的钱就和车里对不上。
      // 各人只能删自己点的,所以话要说成「让点它的人删」
      if (missing.isNotEmpty) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('「${missing.first}」在菜单里找不到了(可能刚下架)。'
                '解锁后让点它的人删掉,再来结算')));
        return;
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
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 发起人解锁(服务端 lock 接口带 locked=false):锁了之后发现有人漏点,
  /// 原来客户端没有这个口子,车就一直锁着,谁都改不了
  Future<void> _unlock() async {
    try {
      final c = await widget.api.lockGroupCart(widget.code, locked: false);
      if (mounted) setState(() => _cart = c);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: widget.code));
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('拼单码已复制')));
  }

  Future<void> _sendToFriends() => SharePlus.instance.share(ShareParams(
      text: '来一起拼「${widget.merchant.name}」:打开超级赞,进这家店,点右上角的'
          '「拼单」→「输码加入拼单」,拼单码 ${widget.code}(开车起 2 小时内有效)'));

  @override
  Widget build(BuildContext context) {
    final cart = _cart;
    final Widget body;
    if (cart == null) {
      body = _error != null
          ? SzError(
              error: _error,
              onRetry: () {
                setState(() => _error = null);
                _sync();
              })
          : const Center(child: CircularProgressIndicator());
    } else {
      final locked = cart['locked'] == true;
      final isOwner = cart['is_owner'] == true;
      body = ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 24),
        children: [
          locked ? _lockedCard(cart, isOwner) : _codeCard(cart),
          const SizedBox(height: 16),
          if (!isOwner && locked)
            ..._companionLocked(cart)
          else
            ..._editable(locked),
        ],
      );
    }
    return SzPageScaffold(
      appBar: AppBar(title: Text('拼单 · ${widget.merchant.name}')),
      body: body,
      bottomNavigationBar: cart == null ? null : _bottomBar(cart),
    );
  }

  // ---------- 头上那张卡 ----------

  /// 没锁:拼单码(大号、能复制、能发给朋友)+ 车上的人(稿子 G)
  Widget _codeCard(Map<String, dynamic> cart) {
    final sz = Theme.of(context).sz;
    final btnShape =
        RoundedRectangleBorder(borderRadius: BorderRadius.circular(kRadiusSm));
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: sz.earn.withValues(alpha: .08),
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('拼单码 · 2 小时有效',
                        style: TextStyle(
                            fontSize: kFontMicro,
                            letterSpacing: 1.2,
                            color: sz.earn)),
                    const SizedBox(height: 2),
                    SelectableText(widget.code,
                        style: szMoney(
                                fontSize: kFigureXl, height: 1.1, color: sz.ink)
                            .copyWith(letterSpacing: 3)),
                  ],
                ),
              ),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  foregroundColor: sz.earn,
                  side: BorderSide(color: sz.earn),
                  shape: btnShape,
                  minimumSize: const Size(0, 34),
                  padding: const EdgeInsets.symmetric(horizontal: 11),
                  textStyle:
                      szSans(fontSize: kFontBody, fontWeight: FontWeight.w500),
                ),
                icon: const Icon(Icons.copy_rounded, size: 15),
                label: const Text('复制'),
                onPressed: _copy,
              ),
              const SizedBox(width: 8),
              FilledButton(
                style: FilledButton.styleFrom(
                  backgroundColor: sz.earn,
                  foregroundColor: sz.paper,
                  shape: btnShape,
                  minimumSize: const Size(0, 34),
                  padding: const EdgeInsets.symmetric(horizontal: 13),
                  textStyle:
                      szSans(fontSize: kFontBody, fontWeight: FontWeight.w600),
                ),
                onPressed: _sendToFriends,
                child: const Text('发给朋友'),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _members(cart),
          const SizedBox(height: 9),
          Text('各自加菜,发起人一次性支付;起送价与满减按合计算。',
              style: TextStyle(
                  fontSize: kFontNote, height: 1.6, color: sz.inkMuted)),
        ],
      ),
    );
  }

  /// 锁了:琥珀底,先说「改不了菜了」和现在在等什么(稿子 H)
  Widget _lockedCard(Map<String, dynamic> cart, bool isOwner) {
    final sz = Theme.of(context).sz;
    final members = (cart['members'] as Map).length;
    final total = cart['total_cents'] as int? ?? _sum(_items);
    final mine = _sum(_items.where((i) => i['uid'] == _me));
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: sz.hold.withValues(alpha: .10),
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.lock_outline_rounded, size: 16, color: sz.hold),
            const SizedBox(width: 8),
            Expanded(
              child: Text('已锁单 · 不能再改菜',
                  style: TextStyle(
                      fontSize: kFontBodyLg,
                      fontWeight: FontWeight.w600,
                      color: sz.hold)),
            ),
          ]),
          const SizedBox(height: 7),
          Text(
              isOwner
                  ? '同伴都改不了菜了。去结算付款;有人漏点就先解锁。'
                  : '发起人正在结算。这一车共 $members 人、${yuan(total)};'
                      '你点的 ${yuan(mine)}。',
              style: TextStyle(
                  fontSize: kFontNote, height: 1.6, color: sz.inkMuted)),
          const SizedBox(height: 11),
          _members(cart),
        ],
      ),
    );
  }

  /// 车上的人:头像字 + 名字胶囊;自己写「你」,发起人后面标出来、头像用黏土淡底
  /// (稿子 G/H:淡底跟着发起人走,不跟着「我」走)
  Widget _members(Map<String, dynamic> cart) {
    final sz = Theme.of(context).sz;
    final members = (cart['members'] as Map).cast<String, dynamic>();
    final owner = '${cart['owner_id']}';
    final me = '$_me';
    return Wrap(
      spacing: 7,
      runSpacing: 7,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        for (final e in members.entries)
          Container(
            padding: const EdgeInsets.fromLTRB(4, 3, 10, 3),
            decoration: ShapeDecoration(
              color: sz.surface,
              shape: StadiumBorder(side: BorderSide(color: sz.line)),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Container(
                width: 20,
                height: 20,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: e.key == owner ? sz.claySoft : sz.surfaceAlt,
                  shape: BoxShape.circle,
                ),
                child: Text(e.key == me ? '我' : szInitialOf('${e.value}'),
                    style: TextStyle(
                        fontSize: kFontMicro,
                        fontWeight: FontWeight.w600,
                        color: e.key == owner ? sz.clay : sz.inkMuted)),
              ),
              const SizedBox(width: 6),
              Text(
                  '${e.key == me ? '你' : e.value}'
                  '${e.key == owner ? '(发起人)' : ''}',
                  style: TextStyle(fontSize: kFontNote, color: sz.ink)),
            ]),
          ),
        if (!(cart['locked'] == true))
          Text('${members.length} 人在车上',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      ],
    );
  }

  // ---------- 主体 ----------

  Widget _sectionHead(String title, {Widget? trailing, Widget? middle}) {
    final sz = Theme.of(context).sz;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.baseline,
      textBaseline: TextBaseline.alphabetic,
      children: [
        Text(title,
            style: TextStyle(
                fontSize: kFontBody,
                fontWeight: FontWeight.w600,
                color: sz.ink)),
        if (middle != null) ...[const SizedBox(width: 8), middle],
        const Spacer(),
        if (trailing != null) trailing,
      ],
    );
  }

  Widget _box(List<Widget> rows) {
    final sz = Theme.of(context).sz;
    return Container(
      margin: const EdgeInsets.only(top: 10),
      decoration: BoxDecoration(
        color: sz.surface,
        border: Border.all(color: sz.line),
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(children: [
        for (final (i, r) in rows.indexed)
          Container(
            decoration: i == 0
                ? null
                : BoxDecoration(
                    border: Border(top: BorderSide(color: sz.line))),
            child: r,
          ),
      ]),
    );
  }

  Widget _moneyRow(String label, int cents,
      {bool header = false, bool strong = false}) {
    final sz = Theme.of(context).sz;
    return Container(
      color: header ? sz.surfaceAlt : null,
      padding: EdgeInsets.symmetric(horizontal: 13, vertical: header ? 9 : 10),
      child: Row(children: [
        Expanded(
          child: Text(label,
              style: TextStyle(
                  fontSize: header ? kFontNote : kFontBody,
                  color: header ? sz.inkMuted : sz.ink)),
        ),
        const SizedBox(width: 8),
        Text(yuan(cents),
            style: szMoney(
                fontSize: header ? kFontNote : kFontBody,
                fontWeight: strong ? FontWeight.w600 : FontWeight.w400,
                color: header ? sz.inkMuted : sz.ink)),
      ]),
    );
  }

  String _nameOf(int uid) {
    if (uid == _me) return '我';
    final members = (_cart?['members'] as Map?) ?? const {};
    return '${members['$uid'] ?? ''}';
  }

  /// 按人分组:车上的人按上车的顺序(发起人在最前),每人一个小计
  List<(int uid, List<Map<String, dynamic>>)> get _byPerson {
    final members = ((_cart?['members'] as Map?) ?? const {}).keys.toList();
    final groups = <int, List<Map<String, dynamic>>>{};
    for (final i in _items) {
      groups.putIfAbsent(i['uid'] as int, () => []).add(i);
    }
    final order = [
      for (final k in members)
        if (groups.containsKey(int.tryParse('$k'))) int.parse('$k'),
      for (final k in groups.keys)
        if (!members.contains('$k')) k,
    ];
    return [for (final uid in order) (uid, groups[uid]!)];
  }

  /// 满减按合计算(服务端 orders.py:取满足门槛的最高一档,门槛看菜品金额)。
  /// 返回合计够到的那一档;一档都不够是 null
  PromoRule? get _promoHit {
    final total = _sum(_items);
    PromoRule? hit;
    for (final r in widget.merchant.promoRules) {
      if (total >= r.thresholdCents &&
          (hit == null || r.thresholdCents > hit.thresholdCents)) {
        hit = r;
      }
    }
    return hit;
  }

  /// 已点里的一行:菜名(带规格)、备注、这一行多少钱。
  /// 自己的行、没锁单时带加减(一行一个步进器:规格或备注不同就是不同的行)
  Widget _lineRow(Map<String, dynamic> i, {required bool editable}) {
    final sz = Theme.of(context).sz;
    final note = _noteOf(i);
    final qty = i['quantity'] as int;
    final dish = _dishes.where((d) => d.id == i['dish_id']).firstOrNull;
    return Padding(
      padding: editable
          ? const EdgeInsets.fromLTRB(13, 0, 4, 0)
          : const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
      child: Row(children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(editable ? '${i['name']}' : '${i['name']} ×$qty',
                  style: TextStyle(fontSize: kFontBody, color: sz.ink)),
              if (note.isNotEmpty)
                Text('备注:$note',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ],
          ),
        ),
        const SizedBox(width: 8),
        Text(yuan((i['price_cents'] as int) * qty),
            style: szMoney(
                fontSize: kFontBody,
                fontWeight: FontWeight.w400,
                color: sz.ink)),
        if (editable) ...[
          const SizedBox(width: 2),
          SzStepper(
            quantity: qty,
            onAdd: () => _bump(i, dish, 1),
            onRemove: () => _bump(i, dish, -1),
          ),
        ],
      ]),
    );
  }

  /// 有规格的菜:「选规格」进详情页(和店铺页一样的描边胶囊),
  /// 角上挂自己点了几份(各规格合计)
  Widget _specButton(Dish d) {
    final sz = Theme.of(context).sz;
    final n = _myQtyOf(d.id);
    return Semantics(
      button: true,
      label: n > 0 ? '选规格,已加 $n 份' : '选规格',
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: () => _openDish(d),
        child: SizedBox(
          height: 44,
          child: Center(
            child: Stack(clipBehavior: Clip.none, children: [
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                decoration: ShapeDecoration(
                    shape: StadiumBorder(side: BorderSide(color: sz.clay))),
                child: Text('选规格',
                    style: TextStyle(
                        fontSize: kFontNote,
                        fontWeight: FontWeight.w500,
                        color: sz.clay)),
              ),
              Positioned(
                top: -7,
                right: -7,
                child: SzPopBadge(
                  show: n > 0,
                  child: Container(
                    constraints: const BoxConstraints(minWidth: 16),
                    height: 16,
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                        color: sz.clay,
                        borderRadius: BorderRadius.circular(999)),
                    child: Text('${n < 1 ? 1 : n}',
                        style: szFigure(
                            fontSize: kFontMicro,
                            fontWeight: FontWeight.w600,
                            color: sz.paper,
                            height: 1)),
                  ),
                ),
              ),
            ]),
          ),
        ),
      ),
    );
  }

  /// 发起人,或者没锁单的同伴:已点(按人分组)+ 加菜
  List<Widget> _editable(bool locked) {
    final sz = Theme.of(context).sz;
    final total = _sum(_items);
    // 实际起送价(含平台下限),和结算页、服务端拦的是同一个数
    final min = widget.merchant.effectiveMinOrderCents;
    // 带规格的菜也列:点「选规格」进详情页选好再加(车里存规格,服务端按规格计价)。
    // 不在供应时段的不列 —— 加进来到下单时一定被服务端拒
    final addable = _dishes
        .where((d) =>
            d.isOnSale && d.stock > 0 && !d.soldOutToday && d.servableNow)
        .toList();
    return [
      if (_items.isNotEmpty) ...[
        _sectionHead('已点',
            middle: Text(yuan(total),
                style: szMoney(fontSize: kFigureSm, color: sz.ink)),
            trailing: min > 0
                ? Text(total >= min ? '已够起送' : '还差 ${yuan(min - total)} 起送',
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))
                : null),
        _box([
          for (final (uid, items) in _byPerson) ...[
            _moneyRow(_nameOf(uid), _sum(items), header: true),
            for (final i in items) _lineRow(i, editable: !locked && uid == _me),
          ],
        ]),
        const SizedBox(height: 16),
      ],
      _sectionHead('加菜',
          middle: Text(locked ? '锁单了,解锁之后才能改' : '只列在售有库存的',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))),
      const SizedBox(height: 4),
      for (final d in addable)
        // 点菜名进详情页:选规格、写备注(「不要香菜」),和店铺页点菜一样
        InkWell(
          onTap: locked ? null : () => _openDish(d),
          child: Container(
            decoration:
                BoxDecoration(border: Border(top: BorderSide(color: sz.line))),
            child: Row(children: [
              Expanded(
                child: Text(d.name,
                    style: TextStyle(fontSize: kFontBody, color: sz.ink)),
              ),
              Text.rich(TextSpan(children: [
                TextSpan(
                    text: yuan(d.effectivePriceCents),
                    style: szMoney(
                        fontSize: kFontBody,
                        fontWeight: FontWeight.w400,
                        color: sz.inkMuted)),
                if (d.hasOptions)
                  TextSpan(
                      text: ' 起',
                      style:
                          TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ])),
              const SizedBox(width: 4),
              Opacity(
                opacity: locked ? .4 : 1,
                child: IgnorePointer(
                  ignoring: locked,
                  child: d.hasOptions
                      ? _specButton(d)
                      : Builder(builder: (_) {
                          // 这里的加减管的是「不带备注」的那一行;
                          // 写了备注的行在上面「已点」里各有各的加减
                          final line = _myLine(d.id, const [], '');
                          return SzStepper(
                            quantity: line?['quantity'] as int? ?? 0,
                            onAdd: () => _bump(line, d, 1, dishId: d.id),
                            onRemove: () => _bump(line, d, -1, dishId: d.id),
                          );
                        }),
                ),
              ),
            ]),
          ),
        ),
      if (!locked && addable.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text('点菜名可以选规格、写备注(比如「不要香菜」),下单时一起带给商家。',
            style: TextStyle(
                fontSize: kFontNote, height: 1.6, color: sz.inkMuted)),
      ],
    ];
  }

  /// 同伴、已锁单:你点的、这一车、以及「你不用付钱」这件事(稿子 H)
  List<Widget> _companionLocked(Map<String, dynamic> cart) {
    final sz = Theme.of(context).sz;
    final mine = _items.where((i) => i['uid'] == _me).toList();
    final hit = _promoHit;
    return [
      _sectionHead('你点的',
          trailing: Text(yuan(_sum(mine)),
              style: szMoney(fontSize: kFigureSm, color: sz.ink))),
      mine.isEmpty
          ? Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text('你这车里没点菜',
                  style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
            )
          : _box([
              for (final i in mine) _lineRow(i, editable: false),
            ]),
      const SizedBox(height: 16),
      _sectionHead('这一车',
          trailing: Text(yuan(_sum(_items)),
              style: szMoney(fontSize: kFigureSm, color: sz.ink))),
      _box([
        for (final (uid, items) in _byPerson)
          _moneyRow(
              uid == _me
                  ? '你'
                  : '${_nameOf(uid)}${'$uid' == '${cart['owner_id']}' ? '(发起人)' : ''}',
              _sum(items)),
        if (hit != null)
          Container(
            color: sz.surfaceAlt,
            padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
            child: Row(children: [
              Expanded(
                child: Text(
                    '满 ${yuanShort(hit.thresholdCents).substring(1)} 减 '
                    '${yuanShort(hit.offCents).substring(1)} · 结算时按合计算',
                    style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
              ),
              Text('−${yuan(hit.offCents)}',
                  style: szMoney(fontSize: kFontBody, color: sz.earn)),
            ]),
          ),
      ]),
      const SizedBox(height: 12),
      // 稿子写「发起人付完,订单会出现在你的『我的订单』里」—— 不对:
      // 订单只建在发起人名下(orders.py 用发起人下单、原子关车),同伴这边没有这一单
      Text(
          '你不用付钱,也不用等着操作。订单记在发起人名下、送到发起人填的地址,'
          '你的「我的订单」里不会有这一单;钱怎么分你们自己商量,平台不代收。',
          style:
              TextStyle(fontSize: kFontNote, height: 1.7, color: sz.inkMuted)),
    ];
  }

  // ---------- 底栏 ----------

  Widget _bottomBar(Map<String, dynamic> cart) {
    final sz = Theme.of(context).sz;
    final locked = cart['locked'] == true;
    final isOwner = cart['is_owner'] == true;
    final empty = _items.isEmpty;
    // 不够起送价就不让锁单去结算:锁了到结算页也提交不了,还得先解锁
    final min = widget.merchant.effectiveMinOrderCents;
    final gap = min - _sum(_items);
    final Widget content;
    if (isOwner) {
      content = Row(children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(yuan(_sum(_items)),
                  style: szMoney(
                      fontSize: kFontLead, height: 1.25, color: sz.ink)),
              Text(locked ? '已锁单,同伴改不了菜' : '锁单后同伴不能再改菜',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ],
          ),
        ),
        if (locked)
          TextButton(
            style: TextButton.styleFrom(
                foregroundColor: sz.inkMuted,
                minimumSize: const Size(0, 42),
                padding: const EdgeInsets.symmetric(horizontal: 10)),
            onPressed: _busy ? null : _unlock,
            child: const Text('解锁'),
          ),
        const SizedBox(width: 4),
        FilledButton(
          style: FilledButton.styleFrom(
            minimumSize: const Size(0, 42),
            padding: const EdgeInsets.symmetric(horizontal: 18),
            // 点不了时按钮上写着差多少,默认的禁用色太淡读不清
            disabledBackgroundColor: sz.surfaceAlt,
            disabledForegroundColor: sz.inkMuted,
          ),
          onPressed: empty || _busy || gap > 0 ? null : _checkout,
          child: Text(empty && min > 0
              ? '${yuanShort(min)} 起送'
              : gap > 0
                  ? '差 ${yuanShort(gap)} 起送'
                  : locked
                      ? '去结算'
                      : '锁单并去结算'),
        ),
      ]);
    } else {
      content = Center(
        child: Text(locked ? '发起人结算中…' : '点好了等发起人锁单结算就行',
            style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
      );
    }
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 6, 12, 14),
        child: Container(
          height: 58,
          padding: const EdgeInsets.fromLTRB(16, 0, 8, 0),
          decoration: BoxDecoration(
            color: isOwner ? sz.surface : sz.surfaceAlt,
            border: Border.all(color: sz.line),
            borderRadius: BorderRadius.circular(kRadiusLg),
          ),
          child: content,
        ),
      ),
    );
  }
}
