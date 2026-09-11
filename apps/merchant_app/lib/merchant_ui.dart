/// 商家端几页共用的小件(2026-09 浅色定稿):订单编号与时刻、钱的口径、
/// 卡片里的小号按钮、「钱靠左按钮靠右」的一行、入场动效只播一次的闸门。
///
/// 看板、订单、新单详情三处画的是同一张单,口径各写一份迟早对不上 ——
/// 所以钱怎么算、编号取哪几位都收在这里。
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:superz_shared/superz_shared.dart';

String _two(int n) => n.toString().padLeft(2, '0');

/// 「11:51」
String hhmm(DateTime t) => '${_two(t.hour)}:${_two(t.minute)}';

/// 服务端时间戳转本地;解析不了返回 null(页面上就不显示那一段)
DateTime? localTimeOf(String? iso) =>
    iso == null ? null : DateTime.tryParse(iso)?.toLocal();

/// 订单号后 6 位,当叫号用:「#128411」。
///
/// 商家端没有「当日第几单」这个数(服务端不发),拿单号尾巴顶上 ——
/// **位数要和小票一致**:云打印和蓝牙小票机顶上那个大号「#xxxxxx」都是
/// 后 6 位(server/app/services/cloud_print.py、printer_service.dart),
/// 屏幕上少两位的话,后厨拿着小票对不上屏幕上是哪一单。
String orderTail(String orderNo) =>
    orderNo.length > 6 ? orderNo.substring(orderNo.length - 6) : orderNo;

/// 顾客手机尾号。商家拿到的是打码号(138****3382),取最后 4 位数字;
/// 凑不齐 4 位就不显示,不猜。
String? phoneTail(String phone) {
  final digits = phone.replaceAll(RegExp(r'\D'), '');
  return digits.length >= 4 ? digits.substring(digits.length - 4) : null;
}

/// 费率文案:0.05 → 5%、0.045 → 4.5%。
///
/// 按一位小数四舍五入后再去掉「.0」—— 不许用 `~/` 截断
/// (4.5% 被截成 4% 的旧账见 finance_page.dart)。
String pctLabel(double rate) {
  final r = (rate * 1000).round() / 10;
  return r == r.truncateToDouble()
      ? '${r.toInt()}%'
      : '${r.toStringAsFixed(1)}%';
}

/// 平台抽成的基数:菜品 + 打包费 − 商家满减(服务端 payment_core 同口径)。
/// 商家让利的那部分平台不抽,平台补贴的那部分照常计佣(商家全额收到)。
int orderBaseCents(Order o) =>
    math.max(o.foodCents + o.packingFeeCents - o.discountCents, 0);

/// 这一单商家实收:基数 − 平台抽成;自己送的单配送费归商家
/// (与服务端 credit_merchant_for_order 同口径)。
///
/// 待接单上的抽成是支付时按当时费率落定的数,**订单完成才真的收**;
/// 取消了就是 0。所以这里显示的是「做完这单能拿到多少」。
int orderNetCents(Order o) =>
    orderBaseCents(o) -
    o.commissionCents +
    (o.selfDelivery ? o.deliveryFeeCents : 0);

/// 「牛肉面 ×1、卤蛋 ×2」(`Order.summary` 没有空格,设计稿有)
String orderItemsLine(Order o) =>
    o.items.map((i) => '${i.name} ×${i.quantity}').join('、');

/// 顾客等了多久。1 分钟内先说「刚刚」,满 3 分钟算急(和旧版一个口径)。
({String text, bool urgent}) waitLabel(DateTime created, DateTime now) {
  final d = now.difference(created);
  if (d.inSeconds < 30) return (text: '刚刚', urgent: false);
  if (d.inMinutes < 1) return (text: '等 ${d.inSeconds} 秒', urgent: false);
  if (d.inHours < 1) {
    return (
      text: '等 ${d.inMinutes} 分 ${d.inSeconds % 60} 秒',
      urgent: d.inMinutes >= 3
    );
  }
  return (text: '等 ${d.inHours} 小时 ${d.inMinutes % 60} 分', urgent: true);
}

/// 按钮文字的样式。**要带字族**:页面里一旦自己给了 textStyle,就整份替换掉
/// 主题的那一份 —— 不写字族的话「接单 · 12 分出餐」里的数字会落到系统字,
/// 和旁边的 SzSans / 衬线数字不是一套。所以走 [szSans],中文照样由系统字补。
TextStyle buttonText(double size, {FontWeight weight = FontWeight.w600}) =>
    szSans(fontSize: size, fontWeight: weight);

/// 卡片里的小号实底按钮:**视觉 32 高**(设计稿),点击区仍撑到 48 ——
/// 商家端的密度档是给戴手套的手准备的,缩的只是看得见的那一块。
ButtonStyle smallFilledStyle({Color? background, Color? foreground}) =>
    FilledButton.styleFrom(
      backgroundColor: background,
      foregroundColor: foreground,
      minimumSize: const Size(0, 32),
      // 稿子上是 14;收 2px,390 宽上「钱 + 拒单 + 接单 · N 分出餐」才排得进一行
      padding: const EdgeInsets.symmetric(horizontal: 12),
      visualDensity: VisualDensity.standard,
      tapTargetSize: MaterialTapTargetSize.padded,
      textStyle: buttonText(kFontBody),
    );

/// 小号描边按钮(拒单、骑手位置、地图):同上,视觉 32、点击 48。
ButtonStyle smallOutlinedStyle() => OutlinedButton.styleFrom(
      minimumSize: const Size(0, 32),
      padding: const EdgeInsets.symmetric(horizontal: 10),
      visualDensity: VisualDensity.standard,
      tapTargetSize: MaterialTapTargetSize.padded,
      textStyle: buttonText(kFontBody, weight: FontWeight.w500),
    );

/// 入场动效「只在这一批第一次出现时播」的闸门。
///
/// SzEnter 只在元素第一次建出来时播,而长列表滚出屏的行会被回收,
/// 滚回来重建时又播一遍 —— 那不是入场。这里给每一批数据一个 700ms 的窗口:
/// 首次加载、下拉刷新各开一次,窗口外建出来的行(轮询进来的、滚回来的)
/// 一律不做入场。下拉刷新要重播时 [epoch] 加一,调用方拿它换列表的 key。
class EnterGate {
  DateTime _until = DateTime.fromMillisecondsSinceEpoch(0);

  /// 下拉刷新重播时加一
  int epoch = 0;

  bool get isOpen => DateTime.now().isBefore(_until);

  void open({bool replay = false}) {
    if (replay) epoch++;
    _until = DateTime.now().add(const Duration(milliseconds: 700));
  }
}

/// 列表里的一行入场:建出来的那一刻决定播不播,之后结构不再变 ——
/// 中途把 SzEnter 摘掉会让整张卡重建,卡上正在闪的新单光晕也跟着断。
class EnterOnce extends StatefulWidget {
  const EnterOnce({
    super.key,
    required this.gate,
    required this.index,
    required this.child,
  });

  final EnterGate gate;
  final int index;
  final Widget child;

  @override
  State<EnterOnce> createState() => _EnterOnceState();
}

class _EnterOnceState extends State<EnterOnce> {
  late final bool _animate = widget.gate.isOpen && widget.index < 8;

  @override
  Widget build(BuildContext context) => _animate
      ? SzEnter(index: widget.index, child: widget.child)
      : widget.child;
}

/// 一左一右两组:放得下就一行(左组靠左、右组靠右),放不下就两行
/// (右组换到下一行,仍然靠右)。订单卡上用了两处:
/// 标题行(编号 + 下单时刻 | 等了多久)、底行(钱 | 拒单 接单)。
///
/// 为什么不用 Row / Wrap:
/// - Row 放不下时溢出,被挤出去的是最后一个孩子 —— 也就是「接单」;
/// - Wrap 换行后单独一行的按钮会靠左,和上面那行的按钮对不齐;
/// - OverflowBar 竖排时所有孩子用同一种对齐,钱和按钮没法一左一右。
class EdgeRow extends MultiChildRenderObjectWidget {
  EdgeRow({
    super.key,
    required Widget start,
    required Widget end,
    this.gap = 8,
    this.runGap = 8,
  }) : super(children: [start, end]);

  final double gap;
  final double runGap;

  @override
  RenderObject createRenderObject(BuildContext context) =>
      _RenderEdgeRow(gap: gap, runGap: runGap);

  @override
  void updateRenderObject(BuildContext context, RenderObject renderObject) {
    (renderObject as _RenderEdgeRow)
      ..gap = gap
      ..runGap = runGap;
  }
}

class _EdgeRowData extends ContainerBoxParentData<RenderBox> {}

class _RenderEdgeRow extends RenderBox
    with
        ContainerRenderObjectMixin<RenderBox, _EdgeRowData>,
        RenderBoxContainerDefaultsMixin<RenderBox, _EdgeRowData> {
  _RenderEdgeRow({required double gap, required double runGap})
      : _gap = gap,
        _runGap = runGap;

  double _gap;
  double get gap => _gap;
  set gap(double v) {
    if (v == _gap) return;
    _gap = v;
    markNeedsLayout();
  }

  double _runGap;
  double get runGap => _runGap;
  set runGap(double v) {
    if (v == _runGap) return;
    _runGap = v;
    markNeedsLayout();
  }

  @override
  void setupParentData(RenderBox child) {
    if (child.parentData is! _EdgeRowData) {
      child.parentData = _EdgeRowData();
    }
  }

  RenderBox get _start => firstChild!;
  RenderBox get _end => childAfter(firstChild!)!;

  /// 三档,从宽到窄(以底行为例,左组是钱、右组是按钮):
  /// 1. 钱排一行也放得下 → 一行;
  /// 2. 按钮留在右边,钱在剩下的宽度里自己折行(净额一行、「菜价 − 5%」一行);
  /// 3. 连这样都挤不下(窄屏 + 长辈版大字)→ 按钮换到下一行,靠右。
  (Size, Offset, Offset) _arrange(
      BoxConstraints c, Size Function(RenderBox, BoxConstraints) sizeOf) {
    final loose = c.loosen();
    final b = sizeOf(_end, loose);
    var a = sizeOf(_start, loose);
    final w = c.hasBoundedWidth ? c.maxWidth : a.width + gap + b.width;
    (Size, Offset, Offset) oneRow(Size a) {
      final h = math.max(a.height, b.height);
      return (
        c.constrain(Size(w, h)),
        Offset(0, (h - a.height) / 2),
        Offset(w - b.width, (h - b.height) / 2),
      );
    }

    if (a.width + gap + b.width <= w) return oneRow(a);
    final room = w - gap - b.width;
    if (room > 0 && room >= _start.getMinIntrinsicWidth(double.infinity)) {
      return oneRow(sizeOf(_start, BoxConstraints(maxWidth: room)));
    }
    a = sizeOf(_start, loose);
    final h = a.height + runGap + b.height;
    return (
      c.constrain(Size(w, h)),
      Offset.zero,
      Offset(math.max(0, w - b.width), a.height + runGap),
    );
  }

  @override
  Size computeDryLayout(covariant BoxConstraints constraints) =>
      _arrange(constraints, (child, c) => child.getDryLayout(c)).$1;

  @override
  void performLayout() {
    final (s, startAt, endAt) = _arrange(constraints, (child, c) {
      child.layout(c, parentUsesSize: true);
      return child.size;
    });
    size = s;
    (_start.parentData! as _EdgeRowData).offset = startAt;
    (_end.parentData! as _EdgeRowData).offset = endAt;
  }

  @override
  double computeMinIntrinsicWidth(double height) => math.max(
      _start.getMinIntrinsicWidth(height),
      _end.getMinIntrinsicWidth(height));

  @override
  double computeMaxIntrinsicWidth(double height) =>
      _start.getMaxIntrinsicWidth(height) +
      gap +
      _end.getMaxIntrinsicWidth(height);

  double _heightFor(double width) {
    final endW = _end.getMaxIntrinsicWidth(double.infinity);
    final b = _end.getMinIntrinsicHeight(width);
    if (_start.getMaxIntrinsicWidth(double.infinity) + gap + endW <=
        width) {
      return math.max(_start.getMinIntrinsicHeight(width), b);
    }
    final room = width - gap - endW;
    if (room > 0 && room >= _start.getMinIntrinsicWidth(double.infinity)) {
      return math.max(_start.getMinIntrinsicHeight(room), b);
    }
    return _start.getMinIntrinsicHeight(width) + runGap + b;
  }

  @override
  double computeMinIntrinsicHeight(double width) => _heightFor(width);

  @override
  double computeMaxIntrinsicHeight(double width) => _heightFor(width);

  @override
  void paint(PaintingContext context, Offset offset) =>
      defaultPaint(context, offset);

  @override
  bool hitTestChildren(BoxHitTestResult result, {required Offset position}) =>
      defaultHitTestChildren(result, position: position);
}

/// 让孩子的「最小固有宽度」报 0:它可以被挤到一个字都不剩(配 ellipsis 用)。
///
/// 订单卡标题行里的「11:51 下单 · 尾号 3382」是可以省略的那一段 ——
/// 不包这一层的话,[EdgeRow] 会拿它最长的一个词当底线,
/// 宁可把「等 1 分 20 秒」挤到下一行也要留着它。
class Squeezable extends SingleChildRenderObjectWidget {
  const Squeezable({super.key, required Widget super.child});

  @override
  RenderObject createRenderObject(BuildContext context) => _RenderSqueezable();
}

class _RenderSqueezable extends RenderProxyBox {
  @override
  double computeMinIntrinsicWidth(double height) => 0;
}
