import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'main.dart' show MerchantListView;

/// 外卖二级品类页:顶部品类宫格(推荐 + 23 品类,默认收起两行可展开),
/// 下方商家列表随选中品类过滤。空品类展示招商位(见 MerchantListView)。
class CategoryPage extends StatefulWidget {
  const CategoryPage({super.key, required this.api, this.deliveryAddress});

  final ApiClient api;
  final Address? deliveryAddress;

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
    // 推荐排最前;收起时只露两行(含"展开"占位格)
    final entries = [
      const MapEntry('', '推荐'),
      ...kMerchantCategories.entries,
    ];
    final collapsedCount = _perRow * 2 - 1; // 两行,留一格给"展开全部"
    final visible = _expanded ? entries : entries.take(collapsedCount).toList();

    Widget cell({
      required String emoji,
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
              child: Text(emoji, style: const TextStyle(fontSize: 22)),
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

    return Scaffold(
      appBar: AppBar(title: const Text('点外卖')),
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
                    emoji: e.key.isEmpty
                        ? '⭐'
                        : kMerchantCategoryEmoji[e.key] ?? '🍱',
                    label: e.value,
                    selected: _selected == e.key,
                    onTap: () => setState(() => _selected = e.key),
                  ),
                cell(
                  emoji: _expanded ? '🔼' : '🔽',
                  label: _expanded ? '收起' : '展开全部',
                  onTap: () => setState(() => _expanded = !_expanded),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            // key 随品类走:切品类整组重建,列表重新拉取
            child: MerchantListView(
              key: ValueKey('cat-$_selected'),
              api: widget.api,
              deliveryAddress: widget.deliveryAddress,
              category: _selected,
            ),
          ),
        ],
      ),
    );
  }
}
