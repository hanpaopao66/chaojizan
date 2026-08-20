import 'package:flutter/material.dart';

import 'brand.dart';

/// 屏幕档位与自适应外壳。三端共用。
///
/// ## 为什么需要它(#295)
///
/// 三端都是手机优先写的,而现在要上 web 和桌面。在 1440px 的浏览器里打开:
///
/// - 金刚区两格各 700px 宽,图标和文字挤在最左边,右边一大片空;
/// - 底部导航横跨整个屏宽 —— 鼠标从内容区跑到底部导航要走半屏;
/// - 搜索框 1400px 宽,而它只是输一个店名;
/// - 正文一行拉到 1400px,远超舒适阅读行长。
///
/// 这不是"没做好看",是**手机布局直接拉宽的必然结果**。
///
/// ## 三个档位,按内容决定不按设备名
///
/// 断点取的是 Material 3 的窗口尺寸类,但**判据是内容**不是设备:
///
/// | 档 | 宽度 | 典型 | 布局 |
/// |---|---|---|---|
/// | [SzWidth.compact] | < 600 | 手机竖屏 | 单列 + 底部导航 |
/// | [SzWidth.medium] | 600–1023 | 平板竖屏 / 手机横屏 / 小窗 | 单列限宽 + 侧栏(收起) |
/// | [SzWidth.expanded] | ≥ 1024 | 平板横屏 / 桌面 / 网页 | 限宽内容 + 侧栏(展开) |
///
/// ⚠️ **不要按 `kIsWeb` 或 `Platform.isMacOS` 判断**。同一个 web 页面
/// 可能在手机浏览器里打开(那时候是 compact),桌面窗口也可以拖到很窄。
/// 判据永远是**当前可用宽度**。
enum SzWidth {
  compact,
  medium,
  expanded;

  bool get isCompact => this == SzWidth.compact;

  /// 宽到该给侧栏导航了。
  bool get hasSideNav => this != SzWidth.compact;

  /// 侧栏是否展开显示文字(窄一点的只显示图标)。
  bool get sideNavExtended => this == SzWidth.expanded;
}

/// 按当前可用宽度取档。
///
/// 用 `MediaQuery.sizeOf` 而不是 `MediaQuery.of` —— 后者会在**任何**
/// MediaQuery 变化(键盘弹出、系统字号改变)时重建,而这里只关心宽度。
SzWidth szWidthOf(BuildContext context) =>
    szWidthFor(MediaQuery.sizeOf(context).width);

SzWidth szWidthFor(double width) {
  if (width < 600) return SzWidth.compact;
  if (width < 1024) return SzWidth.medium;
  return SzWidth.expanded;
}

/// 内容最大宽度。
///
/// ## 为什么要限宽,而不是铺满
///
/// 一行汉字超过 40 个就很难读了(拉丁文是 75 字符左右)。1440px 的屏上
/// 铺满能排 90 多个汉字 —— 眼睛从行尾回到下一行行首会跳错行。
///
/// 卡片同理:一张 1400px 宽的卡片,里面的图标在最左、金额在最右,
/// 两者之间隔着一片空白,眼睛得来回扫。
///
/// 三个值不同是因为**内容形态不同**:
const double kContentMaxWidth = 720; // 单列内容(设置页、表单、正文)
const double kFeedMaxWidth = 1080; // 卡片流(商家列表、订单列表)
const double kWideMaxWidth = 1440; // 看板类(要并排放图表的)

/// 给内容限个宽并居中。
///
/// 窄屏上什么都不做(`maxWidth` 大于可用宽度时 ConstrainedBox 不生效),
/// 所以可以无脑套在页面外面,不用自己判断档位。
class SzContentWidth extends StatelessWidget {
  const SzContentWidth({
    super.key,
    required this.child,
    this.maxWidth = kContentMaxWidth,
  });

  final Widget child;
  final double maxWidth;

  @override
  Widget build(BuildContext context) => Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxWidth),
          child: child,
        ),
      );
}

/// 一个导航项。
@immutable
class SzNavItem {
  const SzNavItem({
    required this.icon,
    required this.selectedIcon,
    required this.label,
    this.badgeCount = 0,
  });

  final IconData icon;
  final IconData selectedIcon;
  final String label;

  /// 角标数字。0 = 不显示。
  final int badgeCount;
}

/// 自适应导航外壳:窄屏底部导航,宽屏左侧栏。
///
/// ## 为什么宽屏不能继续用底部导航
///
/// 底部导航是为**拇指**设计的 —— 手机上拇指自然落在屏幕下缘。
/// 桌面上操作的是鼠标,而鼠标的"家"在内容附近;把导航钉在 1440px 屏的
/// 最底部,意味着每次切页都要横跨半个屏幕跑一趟。
///
/// 侧栏还有一个附带好处:垂直方向省下 80px 给内容 ——
/// 桌面浏览器的可视高度本来就比手机紧张(地址栏、标签栏、书签栏都在吃)。
///
/// ## 谁负责限宽
///
/// 宽屏上这个组件**同时**限住 [appBar] 的内容和 [body],用同一个
/// [contentMaxWidth] —— 两边必须一致,不然标题从 1440 的最左开始、
/// 内容从居中的 1080 开始,上下对不齐,看着像两个页面拼起来的。
///
/// 不同页面的内容形态不同(设置页 720、卡片流 1080、看板 1440),
/// 所以宽度由调用方按当前页传进来,而不是在这里写死。
class SzNavScaffold extends StatelessWidget {
  const SzNavScaffold({
    super.key,
    required this.items,
    required this.selectedIndex,
    required this.onSelected,
    required this.body,
    this.appBar,
    this.floatingActionButton,
    this.leading,
    this.contentMaxWidth = kFeedMaxWidth,
  });

  final List<SzNavItem> items;
  final int selectedIndex;
  final ValueChanged<int> onSelected;
  final Widget body;
  final PreferredSizeWidget? appBar;
  final Widget? floatingActionButton;

  /// 侧栏顶部的东西(logo 之类)。**只在宽屏出现** ——
  /// 窄屏的底部导航没地方放它。
  final Widget? leading;

  /// 内容(含 [appBar] 的内容)的最大宽度。
  ///
  /// **appBar 和 body 用同一个值**,否则标题和下面的内容对不齐 ——
  /// 一个从 1440 的最左开始、一个从居中的 1080 开始,看着像两个页面。
  ///
  /// 页面按 tab 切换不同宽度的(用户端首页是卡片流、「我的」是单列),
  /// 在这里传当前 tab 的值就行,两边一起变。
  final double contentMaxWidth;

  @override
  Widget build(BuildContext context) {
    final w = szWidthOf(context);
    final sz = Theme.of(context).sz;

    if (!w.hasSideNav) {
      return Scaffold(
        appBar: appBar,
        body: body,
        floatingActionButton: floatingActionButton,
        bottomNavigationBar: NavigationBar(
          selectedIndex: selectedIndex,
          onDestinationSelected: onSelected,
          destinations: [
            for (final it in items)
              NavigationDestination(
                icon: _badged(it, Icon(it.icon)),
                selectedIcon: _badged(it, Icon(it.selectedIcon)),
                label: it.label,
              ),
          ],
        ),
      );
    }

    // 宽屏上 **appBar 不给 Scaffold**,而是放进侧栏右边那一列。
    //
    // 给 Scaffold 的话它会横跨整个 1440:标题贴在最左上角、图标钉在最右上角,
    // 中间隔着一米宽的空白,而下面的内容是居中限宽的 —— 上下对不齐,
    // 看着像标题栏和内容不是一个页面的。
    return Scaffold(
      floatingActionButton: floatingActionButton,
      body: Row(children: [
        NavigationRail(
          selectedIndex: selectedIndex,
          onDestinationSelected: onSelected,
          // medium 档只显示图标:那个宽度(600–1023)通常是平板竖屏或
          // 拖窄的桌面窗口,展开的侧栏会吃掉内容本来就不多的横向空间
          extended: w.sideNavExtended,
          labelType: w.sideNavExtended
              ? NavigationRailLabelType.none
              : NavigationRailLabelType.all,
          backgroundColor: sz.surface,
          leading: leading == null
              ? null
              : Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: leading,
                ),
          destinations: [
            for (final it in items)
              NavigationRailDestination(
                icon: _badged(it, Icon(it.icon)),
                selectedIcon: _badged(it, Icon(it.selectedIcon)),
                label: Text(it.label),
              ),
          ],
        ),
        VerticalDivider(width: 1, thickness: 1, color: sz.line),
        Expanded(
          child: Column(children: [
            if (appBar != null)
              // 标题栏的**内容**跟着限宽,而底色铺满 ——
              // 底色断在 1080 会在右边留一条色差,像渲染坏了
              Material(
                color: Theme.of(context).appBarTheme.backgroundColor ??
                    sz.surface,
                child: SafeArea(
                  bottom: false,
                  child: SzContentWidth(
                    maxWidth: contentMaxWidth,
                    child: SizedBox(
                        height: appBar!.preferredSize.height, child: appBar),
                  ),
                ),
              ),
            Expanded(
                child: SzContentWidth(maxWidth: contentMaxWidth, child: body)),
          ]),
        ),
      ]),
    );
  }

  Widget _badged(SzNavItem it, Widget child) => it.badgeCount > 0
      ? Badge(label: Text('${it.badgeCount}'), child: child)
      : child;
}

/// 自适应弹层:窄屏底部弹出,宽屏居中对话框。
///
/// ## 为什么宽屏不能继续用底部弹层
///
/// 底部弹层是从屏幕下缘升起的 —— 手机上那是拇指够得着的地方,而且
/// 弹层最宽也就一个手机宽。
///
/// 1440px 的桌面上它变成:一条横贯整个屏幕底部、高度可能只有 200px 的
/// 长条。内容在左边一小块,右边一米空白;而用户的视线本来在屏幕中央,
/// 得往下扫到底才看得到。
///
/// 居中对话框在宽屏上是对的:它出现在视线落点上,宽度也收得住。
///
/// ## 用法和 showModalBottomSheet 一样
///
/// ```dart
/// final picked = await szShowSheet<String>(
///   context: context,
///   builder: (ctx) => ...,
/// );
/// ```
///
/// ## builder 照原样写,两种形态的差异 helper 自己吸收
///
/// 底部弹层要的三样东西 —— `SafeArea`、拖拽条、键盘避让 ——
/// 在对话框里都是多余的。但**不用在 builder 里判断**:
///
/// | builder 里写的 | 对话框形态下 |
/// |---|---|
/// | `SafeArea(...)` | 零内边距 —— [showDialog] 的 `useSafeArea` 先吃掉了 |
/// | `showDragHandle` | 不画 —— 对话框没有拖拽条这回事 |
/// | `MediaQuery.viewInsetsOf(ctx).bottom` | 恒为 0([Dialog] 自己 remove 掉了) |
///
/// 这么做是因为调用点有 39 个,让每个都写 `if (isSheetBottom(ctx))`
/// 迟早会漏。真需要按形态分叉的(比如整块内容都不一样),
/// 用 [isSheetBottom] 判断。
Future<T?> szShowSheet<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool isScrollControlled = true,
  bool isDismissible = true,

  /// ⚠️ 保持**可空**。brandTheme 的 `bottomSheetTheme` 全局开了拖拽条,
  /// 这里写死 `false` 会显式覆盖主题,把三端的拖拽条一起关掉。
  /// null = 听主题的
  bool? showDragHandle,

  /// 对话框形态下的最大宽度。默认 [kContentMaxWidth](720)——
  /// 弹层装的多半是表单和选项,和单列正文同一个口径。
  double dialogMaxWidth = kContentMaxWidth,
}) {
  if (!szWidthOf(context).hasSideNav) {
    return showModalBottomSheet<T>(
      context: context,
      isScrollControlled: isScrollControlled,
      isDismissible: isDismissible,
      showDragHandle: showDragHandle,
      useSafeArea: true,
      builder: builder,
    );
  }
  return showDialog<T>(
    context: context,
    barrierDismissible: isDismissible,
    // useSafeArea 已经把安全区吃掉了,builder 里的 SafeArea 因此
    // 自动变成空操作 —— 对话框浮在屏幕中间,离刘海和小白条都远,
    // 再补一截 34px 只会在底部留一条白边。**别关掉它**
    useSafeArea: true,
    builder: (ctx) => Dialog(
      clipBehavior: Clip.antiAlias,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: dialogMaxWidth,
          // 别顶到屏幕上下缘:对话框贴边看着像卡住了。
          // 0.85 是留出一圈能看见遮罩的余量
          maxHeight: MediaQuery.sizeOf(ctx).height * 0.85,
        ),
        child: Builder(builder: builder),
      ),
    ),
  );
}

/// 当前的弹层是不是底部形态。
///
/// 给 builder 里判断要不要画拖拽条、要不要 SafeArea 用 ——
/// 那两样只有底部弹层需要。
bool isSheetBottom(BuildContext context) => !szWidthOf(context).hasSideNav;

/// 弹层里的滚动内容 —— 两种形态用两种方式定高度。
///
/// [DraggableScrollableSheet] 是**底部弹层专属**的:它靠"从屏底往上拖"
/// 来决定高度,对话框浮在屏幕中间,没有屏底可拖。直接塞进对话框
/// 不会报错,只是那根拖拽手势永远拖不动。
///
/// 所以这里按档位分叉:
///
/// | | 高度来自 | 传给 builder 的 controller |
/// |---|---|---|
/// | 底部弹层 | 拖到哪算哪([initialSize] 起步) | 拖拽用的那个 |
/// | 对话框 | 内容自己撑,上限 0.85 屏高 | `null` |
///
/// ⚠️ **builder 里的 `ListView` 要写 `shrinkWrap: controller == null`。**
/// 对话框那边给的是宽松约束,ListView 不 shrinkWrap 就会贪到 0.85 屏高 ——
/// 三条 FAQ 撑出大半屏空白。
class SzSheetScrollable extends StatelessWidget {
  const SzSheetScrollable({
    super.key,
    required this.builder,
    this.initialSize = 0.7,
    this.minSize = 0.4,
    this.maxSize = 0.95,
  });

  final Widget Function(BuildContext context, ScrollController? controller)
      builder;
  final double initialSize;
  final double minSize;
  final double maxSize;

  @override
  Widget build(BuildContext context) {
    if (!isSheetBottom(context)) return builder(context, null);
    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: initialSize,
      minChildSize: minSize,
      maxChildSize: maxSize,
      builder: builder,
    );
  }
}
