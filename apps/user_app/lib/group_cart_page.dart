import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import 'checkout_page.dart';

/// 拼单页(设计稿 G 发起人 / H 同伴):拼单码、车上的人、按人分组的「已点」、加菜。
/// 发起人锁单后去结算(一次性支付,AA 线下自行解决)。3 秒轮询同步。
///
/// 机制照服务端 group_cart.py:码是 6 位数字、从开车起 2 小时有效(改菜不续期);
/// 各自只能改自己点的;锁单后谁都不能改菜,发起人可以解锁;
/// 下单时这车原子关掉,订单只记在发起人名下。
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

  int _myQty(int dishId) {
    for (final i in _items) {
      if (i['uid'] == _me && i['dish_id'] == dishId) {
        return i['quantity'] as int;
      }
    }
    return 0;
  }

  int _sum(Iterable<Map<String, dynamic>> items) => items.fold(
      0, (a, i) => a + (i['price_cents'] as int) * (i['quantity'] as int));

  Future<void> _setQty(int dishId, int qty) async {
    try {
      final c = await widget.api.setGroupCartItem(widget.code, dishId, qty);
      if (mounted) setState(() => _cart = c);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
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

  /// 发起人,或者没锁单的同伴:已点(按人分组)+ 加菜
  List<Widget> _editable(bool locked) {
    final sz = Theme.of(context).sz;
    final total = _sum(_items);
    final min = widget.merchant.minOrderCents;
    // 拼单车里的菜没有规格字段(group_cart.py 只存菜和份数),带必选规格的菜
    // 加进来到结算页一定被服务端拒;不在供应时段的同理。这两种不列
    final addable = _dishes
        .where((d) =>
            d.isOnSale &&
            d.stock > 0 &&
            !d.soldOutToday &&
            d.servableNow &&
            !d.options.any((g) => g.required_))
        .toList();
    final hidden = _dishes.any((d) => d.options.any((g) => g.required_));
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
            for (final i in items)
              _moneyRow('${i['name']} ×${i['quantity']}',
                  (i['price_cents'] as int) * (i['quantity'] as int)),
          ],
        ]),
        const SizedBox(height: 16),
      ],
      _sectionHead('加菜',
          middle: Text(locked ? '锁单了,解锁之后才能改' : '只列在售有库存的',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))),
      const SizedBox(height: 4),
      for (final d in addable)
        Container(
          decoration:
              BoxDecoration(border: Border(top: BorderSide(color: sz.line))),
          child: Row(children: [
            Expanded(
              child: Text(d.name,
                  style: TextStyle(fontSize: kFontBody, color: sz.ink)),
            ),
            Text(yuan(d.priceCents),
                style: szMoney(
                    fontSize: kFontBody,
                    fontWeight: FontWeight.w400,
                    color: sz.inkMuted)),
            const SizedBox(width: 4),
            Opacity(
              opacity: locked ? .4 : 1,
              child: IgnorePointer(
                ignoring: locked,
                child: SzStepper(
                  quantity: _myQty(d.id),
                  onAdd: () {
                    if (_myQty(d.id) < d.stock) _setQty(d.id, _myQty(d.id) + 1);
                  },
                  onRemove: () => _setQty(d.id, _myQty(d.id) - 1),
                ),
              ),
            ),
          ]),
        ),
      if (hidden) ...[
        const SizedBox(height: 8),
        Text('要选规格的菜暂时不能拼:拼单车还不支持选规格。',
            style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
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
              for (final i in mine)
                _moneyRow('${i['name']} ×${i['quantity']}',
                    (i['price_cents'] as int) * (i['quantity'] as int)),
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
          ),
          onPressed: empty || _busy ? null : _checkout,
          child: Text(locked ? '去结算' : '锁单并去结算'),
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
