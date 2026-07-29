/// 三端共享组件层(第八辑视觉重构)。
///
/// 约定:
///  - 组件**不带外边距**。间距由调用方用 Column/Wrap 的 gap 或 SizedBox 控制,
///    否则三端的间距会像现在这样忽宽忽窄。
///  - 颜色一律走 `Theme.of(context).sz`,组件内不出现字面色值。
///  - 动效尊重系统「减弱动态效果」(MediaQuery.disableAnimations)。
///  - 参数超过 6 个就该拆成两个组件,别做万能配置。
library;

import 'package:flutter/material.dart';

import 'brand.dart';
import 'brand_art.dart';
import 'ui_bits.dart';

/// 卡片:surface 底 + 1px 描边 + 圆角 12。用在所有需要"成块"的地方。
///
/// 用于:首页商家卡、结算页费用块、订单页骑手卡、我的页数字卡。
class SzCard extends StatelessWidget {
  const SzCard({
    super.key,
    required this.child,
    this.onTap,
    this.padding,
    this.dense = false,
  });

  final Widget child;
  final VoidCallback? onTap;

  /// 覆盖默认内边距(默认 14,dense 时 10)。
  final EdgeInsetsGeometry? padding;

  /// 紧凑模式:商家端这种信息密度高的列表用。
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(kRadiusMd),
      side: BorderSide(color: sz.line),
    );
    return Material(
      color: sz.surface,
      shape: shape,
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: padding ?? EdgeInsets.all(dense ? 10 : kCardPad),
          child: child,
        ),
      ),
    );
  }
}

/// 分段标题:弱化小字 + 字距。用来分组,不用横线也不用大标题。
///
/// 用于:结算页「费用」「支付方式」、订单页「进度」、我的页「账目」。
class SzSectionTitle extends StatelessWidget {
  const SzSectionTitle(this.text, {super.key, this.trailing});

  final String text;

  /// 右侧可选动作(如「全部 →」)。
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Row(
      children: [
        Text(text,
            style: TextStyle(
                fontSize: 11, letterSpacing: 1.2, color: sz.inkFaint)),
        if (trailing != null) ...[const Spacer(), trailing!],
      ],
    );
  }
}

/// 胶囊 chip。两用:
///  - 筛选/排序(selected 为真时墨色实底反白)
///  - 状态标(传 color,描边取该语义色,如缺货、超时)
///
/// 用于:首页排序、店铺页缺货标、商家端订单状态、骑手端单类型。
class SzChip extends StatelessWidget {
  const SzChip(
    this.label, {
    super.key,
    this.selected = false,
    this.onTap,
    this.color,
    this.dense = false,
  });

  final String label;
  final bool selected;
  final VoidCallback? onTap;

  /// 语义色(状态标用);为空时走中性描边。
  final Color? color;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final fg = selected ? sz.paper : (color ?? sz.ink);
    final bg = selected ? sz.ink : Colors.transparent;
    final border = selected ? sz.ink : (color ?? sz.line);
    return Material(
      color: bg,
      shape: StadiumBorder(side: BorderSide(color: border)),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: EdgeInsets.symmetric(
              horizontal: dense ? 9 : 13, vertical: dense ? 3 : 6),
          child: Text(label,
              style: TextStyle(
                  fontSize: dense ? 11 : 12.5,
                  fontWeight: FontWeight.w500,
                  color: fg)),
        ),
      ),
    );
  }
}

/// 菜品加减。数量为 0 时只露 + 号(减号与数字隐藏但仍占位,避免行宽跳动)。
///
/// 用于:店铺页菜品行、购物车弹层、追加下单。
class SzStepper extends StatelessWidget {
  const SzStepper({
    super.key,
    required this.quantity,
    required this.onAdd,
    this.onRemove,
  });

  final int quantity;
  final VoidCallback onAdd;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final empty = quantity <= 0;
    Widget btn(IconData icon, VoidCallback? onTap, {bool filled = false}) =>
        Semantics(
          button: true,
          label: filled ? '增加' : '减少',
          child: InkWell(
            onTap: onTap,
            customBorder: const CircleBorder(),
            // 点击热区 44,视觉直径 23——户外单手也点得中
            child: SizedBox(
              width: 44,
              height: 44,
              child: Center(
                child: Container(
                  width: 23,
                  height: 23,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: filled ? sz.clay : sz.surface,
                    border: Border.all(color: filled ? sz.clay : sz.line),
                  ),
                  child: Icon(icon,
                      size: 15, color: filled ? sz.paper : sz.ink),
                ),
              ),
            ),
          ),
        );

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Visibility(
          visible: !empty,
          maintainSize: true,
          maintainAnimation: true,
          maintainState: true,
          child: btn(Icons.remove, onRemove),
        ),
        Visibility(
          visible: !empty,
          maintainSize: true,
          maintainAnimation: true,
          maintainState: true,
          child: SizedBox(
            width: 22,
            child: Text('$quantity',
                textAlign: TextAlign.center,
                style: szFigure(fontSize: 14, color: sz.ink)),
          ),
        ),
        btn(Icons.add, onAdd, filled: true),
      ],
    );
  }
}

/// 分账条的一行。占比按用户实付算;[note] 里写清另一个口径。
class SzFlowItem {
  const SzFlowItem({
    required this.name,
    required this.amountCents,
    required this.fraction,
    required this.note,
    this.isHold = false,
    this.onWhy,
  });

  final String name;
  final int amountCents;

  /// 占用户实付的比例,0–1。
  final double fraction;

  /// 一句话说明。平台留存那行必须在这里写清商家侧口径,
  /// 否则「4.5%」挨着「5% 承诺」会被当成玩数字。
  final String note;

  /// 真=平台留存(hold 色),假=到手的钱(earn 色)。
  final bool isHold;

  /// 「为什么是 5%」之类的追问入口。
  final VoidCallback? onWhy;
}

/// 分账条:名称 + 占比 + 金额 + 占比进度条。超级赞的招牌信息设计。
///
/// 用于:「钱去哪了」页、订单详情的分账预览、商家端对账、骑手端收入。
class SzMoneyFlow extends StatefulWidget {
  const SzMoneyFlow({super.key, required this.items, this.whyLabel = '为什么'});

  final List<SzFlowItem> items;
  final String whyLabel;

  @override
  State<SzMoneyFlow> createState() => _SzMoneyFlowState();
}

class _SzMoneyFlowState extends State<SzMoneyFlow> {
  bool _grown = false;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final instant = MediaQuery.of(context).disableAnimations;
    if (!_grown) {
      // 首帧后再撑开,才有"钱流出去"的那一下;关了动效就直接到位
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) setState(() => _grown = true);
      });
    }

    return Column(
      children: [
        for (final (i, item) in widget.items.indexed) ...[
          if (i > 0) Divider(color: sz.line, height: 1),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 11),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(children: [
                  Text(item.name,
                      style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w500,
                          color: sz.ink)),
                  const SizedBox(width: 8),
                  Text('${(item.fraction * 100).toStringAsFixed(1)}%',
                      style: szFigure(fontSize: 11, color: sz.inkFaint)),
                  const Spacer(),
                  Text(yuanOf(item.amountCents),
                      style: szMoney(
                          fontSize: 15,
                          color: item.isHold ? sz.hold : sz.earn)),
                ]),
                const SizedBox(height: 8),
                ClipRRect(
                  borderRadius: BorderRadius.circular(2),
                  child: TweenAnimationBuilder<double>(
                    tween: Tween(
                        begin: 0,
                        end: (instant || _grown) ? item.fraction : 0),
                    duration: Duration(milliseconds: instant ? 0 : 450),
                    curve: Curves.easeOutCubic,
                    builder: (context, v, _) => LinearProgressIndicator(
                      value: v.clamp(0, 1),
                      minHeight: 4,
                      color: item.isHold ? sz.hold : sz.earn,
                      backgroundColor: sz.surfaceAlt,
                    ),
                  ),
                ),
                const SizedBox(height: 5),
                Row(children: [
                  Flexible(
                    child: Text(item.note,
                        style: TextStyle(
                            fontSize: 11, height: 1.5, color: sz.inkMuted)),
                  ),
                  if (item.onWhy != null)
                    TextButton(
                      onPressed: item.onWhy,
                      style: TextButton.styleFrom(
                        padding: const EdgeInsets.symmetric(horizontal: 6),
                        minimumSize: const Size(0, 32),
                        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        textStyle: const TextStyle(fontSize: 11),
                      ),
                      child: Text(widget.whyLabel),
                    ),
                ]),
              ],
            ),
          ),
        ],
      ],
    );
  }
}

/// 费用行:左说明右金额。减项传 [negative],用 earn 色带负号。
///
/// 用于:结算页费用明细、订单详情账单、商家端对账、发票明细。
class SzFeeRow extends StatelessWidget {
  const SzFeeRow({
    super.key,
    required this.label,
    required this.amountCents,
    this.note,
    this.negative = false,
    this.emphasized = false,
  });

  final String label;
  final int amountCents;

  /// 跟在标签后的小字,写清"谁承担"(如「全额归骑手」「商家承担」)。
  final String? note;
  final bool negative;

  /// 合计行:加粗 + 金额放大。
  final bool emphasized;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      // 左边一整块 Expanded、右边金额定宽:别用 Flexible + Spacer,
      // 两者都是 flex:1,会把空隙对半分,金额就停在半中间不靠右了
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.baseline,
        textBaseline: TextBaseline.alphabetic,
        children: [
          Expanded(
            child: Wrap(
              crossAxisAlignment: WrapCrossAlignment.center,
              spacing: 6,
              children: [
                Text(label,
                    style: TextStyle(
                        fontSize: 13,
                        color: emphasized ? sz.ink : sz.inkMuted,
                        fontWeight: emphasized ? FontWeight.w600 : null)),
                if (note != null)
                  Text(note!, style: TextStyle(fontSize: 11, color: sz.earn)),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Text('${negative ? '−' : ''}${yuanOf(amountCents)}',
              style: szMoney(
                fontSize: emphasized ? 18 : 14,
                fontWeight: emphasized ? FontWeight.w600 : FontWeight.w500,
                color: negative ? sz.earn : sz.ink,
              )),
        ],
      ),
    );
  }
}

/// 时间线节点状态。
enum SzStepState { done, now, todo }

/// 时间线的一步。
class SzStep {
  const SzStep(this.title, {this.subtitle, this.state = SzStepState.todo});

  final String title;

  /// 时刻或补充说明(「09:26」「距你 1.4km」)。时间线的价值就在能带时刻。
  final String? subtitle;
  final SzStepState state;
}

/// 竖向时间线。当前节点用 claySoft 光晕,不放大——安静但找得到。
///
/// 用于:用户端订单跟踪、骑手端配送、商家端订单流转。
class SzTimeline extends StatelessWidget {
  const SzTimeline({super.key, required this.steps});

  final List<SzStep> steps;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final (i, step) in steps.indexed)
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                SizedBox(
                  width: 22,
                  child: CustomPaint(
                    painter: _RailPainter(
                      sz: sz,
                      state: step.state,
                      first: i == 0,
                      last: i == steps.length - 1,
                    ),
                  ),
                ),
                Expanded(
                  child: Padding(
                    padding: EdgeInsets.only(
                        bottom: i == steps.length - 1 ? 0 : 18, top: 1),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(step.title,
                            style: TextStyle(
                              fontSize: 13.5,
                              fontWeight: step.state == SzStepState.todo
                                  ? FontWeight.w400
                                  : FontWeight.w500,
                              color: step.state == SzStepState.todo
                                  ? sz.inkFaint
                                  : sz.ink,
                            )),
                        if (step.subtitle != null) ...[
                          const SizedBox(height: 2),
                          Text(step.subtitle!,
                              style:
                                  TextStyle(fontSize: 11.5, color: sz.inkMuted)),
                        ],
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _RailPainter extends CustomPainter {
  _RailPainter({
    required this.sz,
    required this.state,
    required this.first,
    required this.last,
  });

  final SzColors sz;
  final SzStepState state;
  final bool first;
  final bool last;

  @override
  void paint(Canvas canvas, Size size) {
    const cx = 6.0;
    const cy = 9.0;
    final line = Paint()
      ..color = sz.line
      ..strokeWidth = 1;

    if (!first) canvas.drawLine(const Offset(cx, 0), const Offset(cx, cy), line);
    if (!last) {
      canvas.drawLine(const Offset(cx, cy), Offset(cx, size.height), line);
    }

    if (state == SzStepState.now) {
      canvas.drawCircle(
          const Offset(cx, cy), 9.5, Paint()..color = sz.claySoft);
    }
    final done = state != SzStepState.todo;
    canvas.drawCircle(const Offset(cx, cy), 5.5,
        Paint()..color = done ? sz.clay : sz.paper);
    if (!done) {
      canvas.drawCircle(
          const Offset(cx, cy),
          5.5,
          Paint()
            ..color = sz.line
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1);
    }
  }

  @override
  bool shouldRepaint(covariant _RailPainter old) =>
      old.state != state || old.sz != sz || old.first != first || old.last != last;
}

/// 空态:品牌插画 + 文案 + 可选动作。收口旧的 EmptyState,新代码用这个。
///
/// 用于:三端所有空列表、搜索无结果、断网。
class SzEmpty extends StatelessWidget {
  const SzEmpty({
    super.key,
    required this.text,
    this.art = BrandArt.bowl,
    this.actionLabel,
    this.onAction,
  });

  final String text;
  final BrandArt art;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopIn(child: BrandArtView(art, size: 124)),
            const SizedBox(height: 14),
            Text(text,
                textAlign: TextAlign.center,
                style: TextStyle(color: sz.inkMuted, height: 1.6)),
            if (actionLabel != null) ...[
              const SizedBox(height: 16),
              OutlinedButton(onPressed: onAction, child: Text(actionLabel!)),
            ],
          ],
        ),
      ),
    );
  }
}

/// 分转元。与 models.dart 的 yuan() 同口径,这里再导一份是为了
/// 让 design.dart 这个轻入口不必依赖 models(models 会带出网络层)。
String yuanOf(int cents) => '¥${(cents / 100).toStringAsFixed(2)}';
