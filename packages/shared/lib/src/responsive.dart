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
/// **这个组件不限宽**,它只管导航。限宽是每个页面自己的事 ——
/// 因为不同页面的内容形态不同(设置页 720、卡片流 1080、看板 1440),
/// 在外壳这一层统一限死会把看板也压成 720。
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

    return Scaffold(
      appBar: appBar,
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
        Expanded(child: body),
      ]),
    );
  }

  Widget _badged(SzNavItem it, Widget child) => it.badgeCount > 0
      ? Badge(label: Text('${it.badgeCount}'), child: child)
      : child;
}
