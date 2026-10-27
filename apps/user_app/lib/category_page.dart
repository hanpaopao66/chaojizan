import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'main.dart' show MerchantListView;

/// 品类页:顶部品类宫格(推荐 + 品类,默认收起两行可展开),
/// 下方商家列表随选中品类过滤。空品类展示招商位(见 MerchantListView)。
///
/// 外卖和零售共用这一页:品类表按 [bizType] 取([categoriesOfBiz]),
/// 业态一路带到 /merchants 的 `biz_type`。两套品类**不能合并** ——
/// 合起来意味着一家快餐店的下拉里出现「母婴玩具」。
class CategoryPage extends StatefulWidget {
  const CategoryPage(
      {super.key, required this.api, this.deliveryAddress, this.bizType = 'food'});

  final ApiClient api;
  final Address? deliveryAddress;

  /// food = 点外卖 / retail = 买菜买水果
  final String bizType;

  @override
  State<CategoryPage> createState() => _CategoryPageState();
}

class _CategoryPageState extends State<CategoryPage> {
  static const _perRow = 5;

  String _selected = ''; // '' = 推荐(不过滤)
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isRetail = widget.bizType == 'retail';
    // 推荐排最前;收起时只露两行(含"展开"占位格)
    final entries = [
      const MapEntry('', '推荐'),
      ...categoriesOfBiz(widget.bizType).entries,
    ];
    final collapsedCount = _perRow * 2 - 1; // 两行,留一格给"展开全部"
    final visible = _expanded ? entries : entries.take(collapsedCount).toList();

    // 品类符号:餐饮是 emoji(彩色的,一个字符搞定);零售没有 emoji 表,
    // 用 Material 图标 —— 它已经打进包里,零额外体积
    Widget categoryGlyph(String key) {
      if (key.isEmpty) return const Text('⭐', style: TextStyle(fontSize: 22));
      if (isRetail) {
        return Icon(kRetailCategoryIcon[key] ?? Icons.storefront_outlined,
            size: 22);
      }
      return Text(kMerchantCategoryEmoji[key] ?? '🍱',
          style: const TextStyle(fontSize: 22));
    }

    Widget cell({
      required Widget icon,
      required String label,
      bool selected = false,
      VoidCallback? onTap,
    }) {
      return InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: onTap,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              width: 44,
              height: 44,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: selected
                    ? theme.colorScheme.primary.withValues(alpha: .14)
                    : theme.colorScheme.surfaceContainerHighest
                        .withValues(alpha: .5),
                shape: BoxShape.circle,
              ),
              child: icon,
            ),
            const SizedBox(height: 4),
            Text(label,
                style: TextStyle(
                    fontSize: 12,
                    fontWeight:
                        selected ? FontWeight.w700 : FontWeight.w400,
                    color: selected
                        ? theme.colorScheme.primary
                        : theme.colorScheme.onSurface)),
          ],
        ),
      );
    }

    return SzPageScaffold(
      // 频道标识条(#132):细细一条,只回答"你在哪个世界",不抢内容的戏
      appBar: AppBar(
        title: Text(isRetail ? '买菜买水果' : '点外卖'),
        bottom: PreferredSize(
            preferredSize: const Size.fromHeight(3),
            child: SzChannelBar(isRetail ? 'retail' : 'food')),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(8, 4, 8, 0),
            child: GridView.count(
              crossAxisCount: _perRow,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              childAspectRatio: 0.96,
              children: [
                for (final e in visible)
                  cell(
                    icon: categoryGlyph(e.key),
                    label: e.value,
                    selected: _selected == e.key,
                    onTap: () => setState(() => _selected = e.key),
                  ),
                cell(
                  icon: Text(_expanded ? '🔼' : '🔽',
                      style: const TextStyle(fontSize: 22)),
                  label: _expanded ? '收起' : '展开全部',
                  onTap: () => setState(() => _expanded = !_expanded),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            // key 随业态 + 品类走:切品类整组重建,列表重新拉取
            child: MerchantListView(
              key: ValueKey('cat-${widget.bizType}-$_selected'),
              api: widget.api,
              bizType: widget.bizType,
              deliveryAddress: widget.deliveryAddress,
              category: _selected,
            ),
          ),
        ],
      ),
    );
  }
}
