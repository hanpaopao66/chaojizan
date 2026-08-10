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
import 'net_image.dart';
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
                fontSize: 11, letterSpacing: 1.2, color: sz.inkMuted)),
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
                      style: szFigure(fontSize: 11, color: sz.inkMuted)),
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
    this.isHold = false,
  });

  final String label;
  final int amountCents;

  /// 跟在标签后的小字,写清"谁承担"(如「全额归骑手」「商家承担」)。
  final String? note;

  /// 只管**符号**:金额前加一个减号。不要拿它当"这是优惠"用 ——
  /// 颜色由 [isHold] 决定。
  final bool negative;

  /// 合计行:加粗 + 金额放大。
  final bool emphasized;

  /// 这一笔是**平台留存**(佣金、服务费),用 `hold` 琥珀。
  ///
  /// 默认 false 时减项走 `earn` 绿 —— 那是**用户省下的钱**(满减、抵扣、让利),
  /// 绿色在这里读作"你赚了"。但商家看到的「平台佣金」是被抽走的钱,
  /// 同样是减项、语义相反,再用绿色就成了"抽你的钱是好事"。
  /// BRAND.md 写死:`earn` = 到手的钱,`hold` = 平台留存,两者不能混。
  final bool isHold;

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
                  Text(note!,
                      style: TextStyle(
                          fontSize: 11, color: isHold ? sz.hold : sz.earn)),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Text('${negative ? '−' : ''}${yuanOf(amountCents)}',
              style: szMoney(
                fontSize: emphasized ? 18 : 14,
                fontWeight: emphasized ? FontWeight.w600 : FontWeight.w500,
                color: isHold
                    ? sz.hold
                    : negative
                        ? sz.earn
                        : sz.ink,
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
                                  ? sz.inkMuted
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

/// 图片位:有图显示图,没图显示成体系的占位——**三端所有会缺图的地方都走它**。
///
/// 为什么要收成一个组件:改之前三端有 12 处缺图兜底、12 个 CircleAvatar、
/// 15 个灰图标,每处各写各的——有的灰图标、有的首字、有的 emoji。
/// 列表里十家店排下来一片灰,那才是"难看"的来源。
///
/// 占位的构成:
///  1. 底色按 [seed](店名/菜名)哈希取自六组泥土色(见 [szToneOf]),
///     同一家店永远同一个色,用户能靠颜色认店;
///  2. 中间是名称首字(中文一字、拉丁两字母),用衬线,克制的对比;
///  3. 传了 [categoryIcon] 且尺寸够大时,右下角压一个极淡的品类符号做纹样。
///
/// 用于:商家 logo、菜品图、房型图、头像、店铺封面。
class SzImage extends StatelessWidget {
  const SzImage({
    super.key,
    required this.url,
    required this.name,
    required this.size,
    this.radius,
    this.circle = false,
    this.categoryIcon,
  });

  /// 已解析好的完整图片地址;空串或加载失败都走占位。
  final String url;

  /// 名称,用来取首字与底色。
  final String name;

  final double size;

  /// 圆角;不传按尺寸自动(≤48 用 8,更大用 12)。
  final double? radius;

  /// 头像用圆形。
  final bool circle;

  /// 品类符号(仅大尺寸时作为淡纹样出现)。
  final IconData? categoryIcon;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final sz = Theme.of(context).sz;
    final tone = szToneOf(name, dark: dark);
    final r = circle
        ? size / 2
        : (radius ?? (size <= 48 ? kRadiusSm : kRadiusMd));
    final shape = circle
        ? const CircleBorder()
        : RoundedRectangleBorder(borderRadius: BorderRadius.circular(r));

    Widget placeholder = Container(
      width: size,
      height: size,
      color: tone.bg,
      child: Stack(
        alignment: Alignment.center,
        children: [
          // 品类纹样:只在够大的图上出现,压在右下角当底纹,不抢首字
          if (categoryIcon != null && size >= 72)
            Positioned(
              right: -size * .10,
              bottom: -size * .10,
              child: Icon(categoryIcon,
                  size: size * .62, color: tone.fg.withValues(alpha: .14)),
            ),
          Text(
            szInitialOf(name),
            style: szFigure(
              // 首字占宽度的四成左右:大图上是主视觉,小图上仍认得清
              fontSize: size * .40,
              fontWeight: FontWeight.w600,
              color: tone.fg,
              height: 1.0,
            ),
          ),
        ],
      ),
    );

    return Container(
      width: size,
      height: size,
      decoration: ShapeDecoration(
        shape: shape.copyWith(side: BorderSide(color: sz.line)),
      ),
      clipBehavior: Clip.antiAlias,
      child: url.isEmpty
          ? placeholder
          : Image(
              image: szNetImage(url),
              width: size,
              height: size,
              fit: BoxFit.cover,
              // 加载中先显示占位,不给转圈——列表里十个转圈比十个色块还难看
              loadingBuilder: (context, child, progress) =>
                  progress == null ? child : placeholder,
              errorBuilder: (_, __, ___) => placeholder,
            ),
    );
  }
}

/// 宽幅封面位(店铺头图、房型大图):同一套占位规则,只是不是正方形。
class SzCover extends StatelessWidget {
  const SzCover({
    super.key,
    required this.url,
    required this.name,
    this.height = 132,
    this.categoryIcon,
  });

  final String url;
  final String name;
  final double height;
  final IconData? categoryIcon;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final tone = szToneOf(name, dark: dark);
    Widget placeholder = Container(
      height: height,
      width: double.infinity,
      color: tone.bg,
      child: Stack(
        alignment: Alignment.center,
        children: [
          if (categoryIcon != null)
            Positioned(
              right: height * .10,
              bottom: -height * .18,
              child: Icon(categoryIcon,
                  size: height * .86, color: tone.fg.withValues(alpha: .12)),
            ),
          Text(szInitialOf(name),
              style: szFigure(
                  fontSize: height * .34,
                  fontWeight: FontWeight.w600,
                  color: tone.fg,
                  height: 1.0)),
        ],
      ),
    );
    return SizedBox(
      height: height,
      width: double.infinity,
      child: url.isEmpty
          ? placeholder
          : Image(
              image: szNetImage(url),
              height: height,
              width: double.infinity,
              fit: BoxFit.cover,
              loadingBuilder: (context, child, progress) =>
                  progress == null ? child : placeholder,
              errorBuilder: (_, __, ___) => placeholder),
    );
  }
}

/// 加载失败态:一句人话 + 一个重试按钮。
///
/// 改之前三端有 6 处 `snapshot.hasError` 分支,**没有一处给重试按钮**——
/// 用户只能下拉(如果那页恰好有 RefreshIndicator)或者杀 App。
/// 外卖场景里电梯、地库、信号弱是常态,这是高频路径。
///
/// 文案直接用 [error] 的 message:走 ApiClient 出来的要么是服务端的中文
/// 业务错误,要么是翻好的网络提示(那句提示本身就带了"检查网络再试"这类
/// 行动建议),不会是异常原文。所以这里不需要判断是不是网络错误——
/// 设计层也就不必反过来依赖网络层。
class SzError extends StatelessWidget {
  const SzError({super.key, required this.error, this.onRetry});

  final Object? error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            PopIn(child: BrandArtView(BrandArt.offline, size: 112)),
            const SizedBox(height: 14),
            Text('${error ?? '加载失败'}',
                textAlign: TextAlign.center,
                style: TextStyle(
                    fontSize: 14, height: 1.6, color: sz.ink)),
            if (onRetry != null) ...[
              const SizedBox(height: 18),
              FilledButton(onPressed: onRetry, child: const Text('重试')),
            ],
          ],
        ),
      ),
    );
  }
}

/// 顶部警示条:页面**主体还能用**,但有一块数据没拉到。
///
/// 和 [SzError] 的分工:整页没数据用 SzError(占满屏、给重试);
/// 只是某一块拉不到、剩下的照常能看,用这个 —— 整页打回错误态会
/// 把本来能用的东西也一起拿走。
///
/// 关键是**把歧义说破**:界面上那块空白到底是「没有」还是「没拉到」,
/// 用户自己分辨不出来,得由这行字来讲。
class SzRetryBanner extends StatelessWidget {
  const SzRetryBanner({super.key, required this.text, required this.onRetry});

  /// 说清楚缺的是什么、空白不代表什么。别只写「加载失败」
  final String text;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Material(
      color: sz.danger.withValues(alpha: .12),
      child: InkWell(
        onTap: onRetry,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Row(children: [
            Icon(Icons.wifi_off, size: 18, color: sz.danger),
            const SizedBox(width: 8),
            Expanded(
              child: Text(text,
                  style:
                      TextStyle(fontSize: 13, color: sz.danger, height: 1.4)),
            ),
            // 整条都能点,图标只是提示 —— 别让读屏把它再念一遍
            ExcludeSemantics(
              child: Icon(Icons.refresh, size: 18, color: sz.danger),
            ),
          ]),
        ),
      ),
    );
  }
}

/// 未保存内容的返回拦截:填了东西再手势返回时先问一句。
///
/// 商家入驻要填店名/地址/证照号 + 传两张证照图,骑手实名要填身份证 +
/// 传照片——这两个恰好是转化率最关键的表单,误触返回一下全丢、得从头再来。
/// 改之前三端 PopScope 用量为 0。
///
/// [isDirty] 每次返回时求值(不是构造时),所以传闭包而不是 bool。
class SzUnsavedGuard extends StatelessWidget {
  const SzUnsavedGuard({
    super.key,
    required this.isDirty,
    required this.child,
    this.message = '填的内容还没提交,现在返回会丢掉。',
  });

  final bool Function() isDirty;
  final Widget child;
  final String message;

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final nav = Navigator.of(context);
        if (!isDirty()) {
          nav.pop();
          return;
        }
        final leave = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('要放弃已填的内容吗'),
            content: Text(message),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('继续填')),
              // 放弃是破坏性动作,用 danger 而不是主按钮色
              TextButton(
                  style: TextButton.styleFrom(
                      foregroundColor: Theme.of(context).sz.danger),
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('放弃')),
            ],
          ),
        );
        if (leave == true) nav.pop();
      },
      child: child,
    );
  }
}

/// 账目台面(#133):「钱去哪了」「平台账本」这类可查账的地方专用。
///
/// ## 为什么单独做一个
///
/// 账目透明是这个平台唯一抄不走的差异点,却和普通卡片长得一样。
/// 用一张更"硬"的深色台面把它托出来 —— 让"这块是账"在读到文字之前就被认出来。
///
/// ## 实现上的关键一步
///
/// 它**在内部把 `SzColors` 整个换掉**,而不是给每个子组件传一堆颜色参数:
/// 台面里的 `SzMoneyFlow`、`SzFeeRow`、`Text` 照常读 `Theme.of(context).sz.ink`,
/// 拿到的自动是适配深底的那一套。已有组件一行都不用改,
/// 将来新写的组件掉进来也自动是对的 —— 靠约定而不是靠记得传参。
///
/// 语义色(earn/hold)在台面里一律取深色态的亮版:浅色态的墨绿墨褐
/// 压在深底上根本读不出来。
/// **调用方注意**:台面内部换的是 `SzColors`,靠的是子组件**在台面内**
/// 调 `Theme.of(context)`。如果你在台面外先 `final sz = Theme.of(context).sz;`
/// 再把 `sz.line` 之类传进来,拿到的还是外层浅色态 —— 画出来是一道刺眼的亮线。
/// 台面内要用颜色,就在台面内取(必要时套一层 `Builder`)。
class SzLedgerCard extends StatelessWidget {
  const SzLedgerCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(kCardPad),
    this.margin,
    this.onTap,
  });

  final Widget child;
  final EdgeInsets padding;
  final EdgeInsets? margin;

  /// 台面可点(如订单详情的分账预览点开看完整口径)
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final base = Theme.of(context).sz;
    final dark = SzColors.dark;

    // 台面内的令牌:底是 ledger,文字与语义色取深色态,
    // 分隔线用一点点亮的白 —— 深色态的 line 压在更深的底上会消失
    final inside = dark.copyWith(
      paper: base.ledger,
      surface: base.ledger,
      surfaceAlt: base.ledger,
      line: const Color(0x22FFFFFF),
    );

    final body = Padding(
      padding: padding,
      child: Theme(
        data: Theme.of(context).copyWith(extensions: [inside]),
        // DefaultTextStyle 也要换:台面里裸 Text 不带颜色时会继承页面的墨色,
        // 压在深底上就是黑底黑字
        child: DefaultTextStyle.merge(
          style: TextStyle(color: inside.ink),
          child: child,
        ),
      ),
    );

    // 深色页上台面与页底的明度只差 1.10(实测),光靠颜色分不出是两层 ——
    // 补一道细边把边界画出来。浅色页上反差 14.35,不需要边框
    final needsEdge = Theme.of(context).brightness == Brightness.dark;

    return Container(
      margin: margin,
      decoration: BoxDecoration(
        color: base.ledger,
        borderRadius: BorderRadius.circular(kRadiusMd),
        border: needsEdge
            ? Border.all(color: const Color(0x1FFFFFFF))
            : null,
      ),
      clipBehavior: Clip.antiAlias,
      child: onTap == null
          ? body
          : InkWell(onTap: onTap, child: body),
    );
  }
}
