import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'merchant_ui.dart';

/// 新单详情(设计稿 6c):点看板/订单里的待接单卡推进来,菜名大字、分账常显。
///
/// 接单、拒单都**回调外层**(工作台的 `_act` / `_reject`),不自己调接口 ——
/// 列表、待接数、催单语音都挂在工作台上,这里自己接了单,那边要等下一轮
/// 轮询才知道,期间还会接着催。
///
/// ## 和设计稿不一样的两处
///
/// - 稿子上有「第 3 次来」:服务端不给商家顾客的到店次数,不编;
/// - 稿子上「预计出餐」是 8/12/18/25 四个按钮:服务端没有逐单改出餐时间的
///   接口,接单一律按店铺承诺算。这里就照实写「按店铺承诺 N 分钟」,
///   要改去改承诺(改完对之后所有单生效)。
class NewOrderPage extends StatefulWidget {
  const NewOrderPage({
    super.key,
    required this.order,
    required this.shop,
    required this.promiseMinutes,
    this.busyExtraMinutes = 0,
    required this.onAccept,
    required this.onReject,
    this.onEditPromise,
  });

  final Order order;

  /// 店的坐标(订单上没带商家坐标时用它算直线距离)与费率
  final Merchant shop;

  /// 店铺承诺出餐时长(分钟)
  final int promiseMinutes;

  /// 忙碌模式加的分钟数;没开忙碌模式传 0
  final int busyExtraMinutes;

  /// 接单成功返回 true
  final Future<bool> Function() onAccept;

  /// 拒单成功返回 true(拒单原因弹窗在外层)
  final Future<bool> Function() onReject;

  /// 改承诺出餐时长;保存了返回新的分钟数
  final Future<int?> Function()? onEditPromise;

  @override
  State<NewOrderPage> createState() => _NewOrderPageState();
}

class _NewOrderPageState extends State<NewOrderPage> {
  late int _promise = widget.promiseMinutes;
  bool _busy = false;
  bool _done = false;
  DateTime _now = DateTime.now();
  Timer? _tick;

  Order get _o => widget.order;

  @override
  void initState() {
    super.initState();
    // 顶上「已等 N 分 N 秒」要按秒走:这一页开着时顾客正在等
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _now = DateTime.now());
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    super.dispose();
  }

  int get _eta => _promise + widget.busyExtraMinutes;

  Future<void> _accept() async {
    if (_busy || _done) return;
    setState(() => _busy = true);
    final ok = await widget.onAccept();
    if (!mounted) return;
    if (!ok) {
      setState(() => _busy = false);
      return;
    }
    setState(() => _done = true);
    // 成功块停一会儿再回去(规范 06:800ms 后自动跳转)
    await Future<void>.delayed(SzSuccessSwap.hold);
    if (mounted) Navigator.of(context).pop(true);
  }

  Future<void> _reject() async {
    if (_busy || _done) return;
    setState(() => _busy = true);
    final ok = await widget.onReject();
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) Navigator.of(context).pop(true);
  }

  Future<void> _editPromise() async {
    final v = await widget.onEditPromise?.call();
    if (v != null && mounted) setState(() => _promise = v);
  }

  /// 第二行:地址 · 直线距离 · 送法。自取单只说自取和取餐码
  List<String> _whereLine() {
    if (_o.pickup) {
      return [
        '到店自取',
        if (_o.pickupCode.isNotEmpty) '取餐码 ${_o.pickupCode}',
      ];
    }
    final fromLat = _o.merchantLat ?? widget.shop.lat;
    final fromLng = _o.merchantLng ?? widget.shop.lng;
    // 直线距离,不是骑行路程(Merchant.distanceM 的注释:直线比骑行短约 19%),
    // 所以文案上带「直线」两个字
    final m = distanceMeters(fromLat, fromLng, _o.lat, _o.lng);
    return [
      if (_o.address.isNotEmpty) _o.address,
      '直线 ${distanceLabelShort(m)}',
      _o.selfDelivery ? '你自己送' : (_o.toDoor ? '送上门' : '送到楼下'),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final tail = orderTail(_o.orderNo);
    final created = localTimeOf(_o.createdAt);
    final phone = phoneTail(_o.contactPhone);
    final wait = created == null ? null : waitLabel(created, _now);
    final pending = _o.status == OrderStatus.paid;
    return SzPageScaffold(
      appBar: AppBar(
        title: Text('新单 #$tail'),
        actions: [
          if (wait != null && pending)
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Center(
                child: Text(
                    wait.text == '刚刚' ? '刚刚下单' : '已${wait.text}',
                    style: TextStyle(
                        fontSize: kFontNote,
                        fontWeight: FontWeight.w600,
                        color: wait.urgent ? sz.danger : sz.clay)),
              ),
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 16),
        children: [
          _header(sz, tail, created, phone),
          const SizedBox(height: 12),
          _itemsCard(sz),
          const SizedBox(height: 12),
          _splitCard(sz),
          const SizedBox(height: 16),
          _prepBlock(sz),
        ],
      ),
      // 底部至少留 28(稿子);有小白条的机器上 SafeArea 给得更多就用它的
      bottomNavigationBar: SafeArea(
        top: false,
        minimum: const EdgeInsets.only(bottom: 28),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 0),
          child: _actions(sz, pending),
        ),
      ),
    );
  }

  Widget _header(SzColors sz, String tail, DateTime? created, String? phone) {
    final line1 = [
      if (created != null) '${hhmm(created)} 下单',
      if (phone != null) '用户尾号 $phone',
    ].join(' · ');
    return Row(children: [
      // 稿子上是 36 的两位数;单号尾巴是四位,用 32 那一档,右边两行才放得下
      Text('#$tail',
          style: szMoney(
              fontSize: kFigureXl,
              fontWeight: FontWeight.w600,
              color: sz.ink,
              height: 1)),
      const SizedBox(width: 10),
      Expanded(
        child: DefaultTextStyle.merge(
          style: TextStyle(fontSize: kFontBody, color: sz.inkMuted, height: 1.4),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (line1.isNotEmpty) Text(line1),
            // 一截一个 Text 放进 Wrap:折行只在「·」处整截挪下去,
            // 不会把「送上门」拆成「送上 / 门」;只有地址自己太长时在地址里折
            Wrap(children: [
              for (final (i, seg) in _whereLine().indexed)
                Text(i == 0 ? seg : ' · $seg',
                    maxLines: i == 0 ? 2 : 1,
                    softWrap: i == 0,
                    overflow: i == 0 ? TextOverflow.ellipsis : TextOverflow.clip),
            ]),
          ]),
        ),
      ),
    ]);
  }

  Widget _itemsCard(SzColors sz) {
    final rows = <Widget>[];
    for (var i = 0; i < _o.items.length; i++) {
      final it = _o.items[i];
      final last = i == _o.items.length - 1 && _o.remark.isEmpty;
      rows.add(Container(
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          border: last ? null : Border(bottom: BorderSide(color: sz.line)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Expanded(
              child: Text(it.name,
                  style: TextStyle(
                      fontSize: kFontLead,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
            ),
            const SizedBox(width: 10),
            Text('×${it.quantity}',
                style: szFigure(fontSize: kFontLead, color: sz.inkMuted)),
            SizedBox(
              width: 76,
              child: Text(yuan(it.priceCents * it.quantity),
                  textAlign: TextAlign.right,
                  style: szMoney(
                      fontSize: kFigureSm,
                      fontWeight: FontWeight.w400,
                      color: sz.ink)),
            ),
          ],
        ),
      ));
    }
    if (_o.remark.isNotEmpty) {
      rows.add(Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(Icons.sticky_note_2_outlined, size: 18, color: sz.clay),
          const SizedBox(width: 8),
          Expanded(
            child: Text('备注:${_o.remark}',
                style: TextStyle(
                    fontSize: kFontBody + 0.5, height: 1.4, color: sz.clay)),
          ),
        ]),
      ));
    }
    return _box(sz,
        padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 4),
        child: Column(children: rows));
  }

  Widget _splitCard(SzColors sz) {
    final base = orderBaseCents(_o);
    final net = orderNetCents(_o);
    Widget row(String label, String amount,
            {Color? amountColor, bool strong = false}) =>
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Expanded(
                child: Text(label,
                    style: TextStyle(
                        fontSize: kFontBody,
                        fontWeight: strong ? FontWeight.w600 : FontWeight.w400,
                        color: strong ? sz.ink : sz.inkMuted)),
              ),
              const SizedBox(width: 10),
              Text(amount,
                  style: szMoney(
                      fontSize: strong ? kFontTitle : kFontBody,
                      fontWeight: strong ? FontWeight.w600 : FontWeight.w400,
                      color: amountColor ?? sz.ink)),
            ],
          ),
        );
    final rate = pctLabel(widget.shop.commissionRate);
    return _box(sz,
        padding: const EdgeInsets.fromLTRB(kCardPad, 9, kCardPad, 9),
        child: Column(children: [
          // 菜价合计 = 平台抽成的基数。有打包费、满减时拆开写,
          // 否则「菜价 − 5% = 实收」对不上稿子里那一行
          row(_o.packingFeeCents > 0 || _o.discountCents > 0 ? '菜品' : '菜价合计',
              yuan(_o.foodCents)),
          if (_o.packingFeeCents > 0) row('打包费', '+${yuan(_o.packingFeeCents)}'),
          if (_o.discountCents > 0)
            row('店铺满减(你出)', '−${yuan(_o.discountCents)}'),
          if (_o.packingFeeCents > 0 || _o.discountCents > 0)
            row('菜价合计', yuan(base)),
          row('平台 $rate(订单完成才收)', '−${yuan(_o.commissionCents)}',
              amountColor: sz.hold),
          if (_o.pickup)
            row('到店自取 · 无配送费', '¥0', amountColor: sz.inkMuted)
          else if (_o.selfDelivery)
            row('配送费 ${yuanShort(_o.deliveryFeeCents)} · 你自己送,归你',
                '+${yuan(_o.deliveryFeeCents)}',
                amountColor: sz.earn)
          else
            row('配送费 ${yuanShort(_o.deliveryFeeCents)} → 骑手全额,与你无关', '¥0',
                amountColor: sz.inkMuted),
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Divider(height: 1, color: sz.line),
          ),
          const SizedBox(height: 4),
          row('你实收', yuan(net), amountColor: sz.earn, strong: true),
        ]));
  }

  Widget _prepBlock(SzColors sz) {
    final busy = widget.busyExtraMinutes > 0;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('预计出餐',
          style: TextStyle(
              fontSize: kFontNote, letterSpacing: 1, color: sz.inkMuted)),
      const SizedBox(height: 8),
      Material(
        color: sz.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: BorderSide(color: sz.line),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: widget.onEditPromise == null ? null : _editPromise,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 44),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 11),
              child: Row(children: [
                Expanded(
                  child: Text.rich(
                    TextSpan(children: [
                      const TextSpan(text: '按店铺承诺 '),
                      TextSpan(
                          text: '$_promise',
                          style: szFigure(
                              fontWeight: FontWeight.w600, color: sz.ink)),
                      const TextSpan(text: ' 分钟'),
                      if (busy)
                        TextSpan(
                            text: ' · 忙碌模式 +${widget.busyExtraMinutes} 分钟',
                            style: TextStyle(color: sz.hold)),
                    ]),
                    style: TextStyle(fontSize: kFontBodyLg, color: sz.ink),
                  ),
                ),
                if (widget.onEditPromise != null)
                  Text('改承诺 →',
                      style: TextStyle(fontSize: kFontBody, color: sz.clay)),
              ]),
            ),
          ),
        ),
      ),
      const SizedBox(height: 8),
      // 「超时不罚、不影响排名和曝光」是承诺页里写着的(promises_page.dart);
      // 出餐时长还会拿去估骑手等餐和送达时间,所以不说「只给你自己看」
      Text('超时不罚,也不影响排名和曝光;要改出餐时间就改承诺,对之后所有单生效',
          style: TextStyle(fontSize: kFontNote, height: 1.5, color: sz.inkMuted)),
    ]);
  }

  Widget _actions(SzColors sz, bool pending) {
    if (!pending) {
      // 推进来之后单子变了(被取消、别处接了):不给按钮,照实说
      return Text('这单现在是「${_o.status.label}」,回列表看最新状态',
          textAlign: TextAlign.center,
          style: TextStyle(fontSize: kFontBody, color: sz.inkMuted));
    }
    final accent = Theme.of(context).colorScheme.primary;
    return Row(children: [
      Semantics(
        label: '拒单,尾号 ${orderTail(_o.orderNo)}',
        excludeSemantics: true,
        button: true,
        child: OutlinedButton(
          onPressed: _busy || _done ? null : _reject,
          style: OutlinedButton.styleFrom(
            minimumSize: const Size(0, 52),
            padding: const EdgeInsets.symmetric(horizontal: 20),
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(kRadiusMd)),
            textStyle: buttonText(kFontBodyLg, weight: FontWeight.w400),
          ),
          child: const Text('拒单'),
        ),
      ),
      const SizedBox(width: 10),
      Expanded(
        child: SizedBox(
          height: 52,
          child: SzSuccessSwap(
            done: _done,
            button: SzPressScale(
              enabled: !_busy,
              child: SizedBox.expand(
                child: FilledButton(
                  onPressed: _busy || _done ? null : _accept,
                  style: FilledButton.styleFrom(
                    backgroundColor: accent,
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(kRadiusMd)),
                    textStyle: buttonText(kFontTitle),
                  ),
                  child: Text(_busy ? '处理中…' : '接单,$_eta 分钟出餐'),
                ),
              ),
            ),
            success: Container(
              decoration: BoxDecoration(
                color: sz.earn,
                borderRadius: BorderRadius.circular(kRadiusMd),
              ),
              alignment: Alignment.center,
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.check_circle, size: 20, color: sz.surface),
                const SizedBox(width: 6),
                Text('已接单',
                    style: TextStyle(
                        fontSize: kFontTitle,
                        fontWeight: FontWeight.w600,
                        color: sz.surface)),
              ]),
            ),
          ),
        ),
      ),
    ]);
  }

  Widget _box(SzColors sz,
          {required Widget child, required EdgeInsetsGeometry padding}) =>
      Container(
        padding: padding,
        decoration: BoxDecoration(
          color: sz.surface,
          borderRadius: BorderRadius.circular(kRadiusMd),
          border: Border.all(color: sz.line),
        ),
        child: child,
      );
}
