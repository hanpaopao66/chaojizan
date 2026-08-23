import 'package:flutter/material.dart';

import 'brand.dart';

/// 网格里的一格。
class SzIconGridItem {
  const SzIconGridItem({
    required this.icon,
    required this.label,
    this.badge = 0,
    this.onTap,
  });

  final IconData icon;

  /// 两三个字就说清的标题。说不清的那个不该进网格,该留在 [SzEntryTile]。
  final String label;

  /// 角标数字。0 = 不显示。
  ///
  /// **只给「你还有事要做」的格子用。** 退款到账、售后已受理都不是待办,
  /// 给它们挂个红数字只会制造焦虑 —— 用户点进去发现什么也不用做,
  /// 下一次就不信这个角标了。
  final int badge;

  final VoidCallback? onTap;
}

/// 图标网格:一行几个平级入口。
///
/// ## 它补的是 [SzEntryTile] 的哪一档
///
/// `SzEntryTile` 一条 46px(有状态值或光杆)、63px(只有 hint)。那是给
/// **需要一句说明**或者**有状态值可显示**的入口用的。但有一类入口两样都
/// 给不出:标题两三个字就说清了(优惠券、我的收藏、待评价),彼此完全平级,
/// 也没有"当前是什么值"可言。这类东西排成竖列是浪费 —— 一条 46px 只放一个词。
///
/// 网格把它们横过来:**四个入口不到 100px,合下来 25px 一个,
/// 密度是列表条的两倍。**
///
/// 这不是推翻 `SzEntryTile`。三种副标题的分工(状态值走 `value:`、
/// 一次性解释走 `hint:`、立场表达走 `SzEntryGroup.footnote`)一条没变,
/// 网格只是多出来的一个选项:**给不出状态值、标题已经说清是什么的**,
/// 网格比列表更省地方也更好扫。
///
/// ## 标签必须能换行
///
/// 320 窄屏 + 长辈版 1.4× 下,一格只有 60px 出头,而「退款售后」四个字
/// 要 64px。这时候:
///
/// - `maxLines: 1 + ellipsis` → 切成「退款…」,**四个字切一半等于没写**;
/// - `softWrap: false` → 默默画到隔壁格子上,不报错也不留痕
///   (`channel_grid.dart` 踩过这一个);
/// - `maxLines: 2` 换行 → 卡片高一点,但字是全的。
///
/// 选第三个。判据锁在 `test/icon_grid_test.dart`。
class SzIconGrid extends StatelessWidget {
  const SzIconGrid({super.key, required this.items, this.columns});

  final List<SzIconGridItem> items;

  /// 每行几格。不给就是 `items.length`(一行放完)。
  ///
  /// ## 为什么需要它
  ///
  /// 这个组件是 `Row` + `Expanded`,列数**不会**自己跟着宽度变。
  /// 五个格子在 390 屏上每格 71px,刚好;同样五个格子在 1080 的宽屏上
  /// 每格 216px —— 一个 40px 的图标居中飘着,两侧各 88px 空白,
  /// 看着像图标掉队了。
  ///
  /// 商家端「店铺」页因此按可用宽度分叉:窄屏 2 行 × 5 列,
  /// 宽屏 1 行 × 10 列。**判据是可用宽度不是平台**(见 `responsive.dart`)。
  ///
  /// 格子数不够整行时补空位,**不把最后几格拉宽** —— 拉宽的话第二行
  /// 和第一行对不齐,看着像布局坏了。
  final int? columns;

  @override
  Widget build(BuildContext context) {
    final n = columns ?? items.length;
    if (n <= 0) return const SizedBox.shrink();
    final rows = <List<SzIconGridItem?>>[];
    for (var i = 0; i < items.length; i += n) {
      final row = <SzIconGridItem?>[
        for (var j = i; j < i + n; j++) j < items.length ? items[j] : null,
      ];
      rows.add(row);
    }
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [for (final row in rows) _row(context, row)],
    );
  }

  Widget _row(BuildContext context, List<SzIconGridItem?> row) {
    final sz = Theme.of(context).sz;
    // 和 SzEntryTile 同一条:字号跟密度走(#33 第 5 节遗留)
    final bump = Theme.of(context).szMetrics.fontBump;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final it in row)
            Expanded(
              // 空位:占着宽度但什么都不画,好让上下两行的格子对齐
              child: it == null
                  ? const SizedBox.shrink()
                  : InkWell(
                      onTap: it.onTap,
                      borderRadius: BorderRadius.circular(kRadiusSm),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Badge(
                              isLabelVisible: it.badge > 0,
                              // 20+ 是列表首页的上限(myOrders 一页 20 条)。
                              // 显示 21 会是**猜**的 —— 第 21 条还没拉下来
                              label:
                                  Text(it.badge > 20 ? '20+' : '${it.badge}'),
                              child: SizedBox(
                                width: 40,
                                height: 40,
                                child: Icon(it.icon,
                                    size: 22, color: sz.inkMuted),
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              it.label,
                              maxLines: 2,
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                  fontSize: kFontNote + bump,
                                  height: 1.2,
                                  color: sz.ink),
                            ),
                          ],
                        ),
                      ),
                    ),
            ),
        ],
      ),
    );
  }
}
