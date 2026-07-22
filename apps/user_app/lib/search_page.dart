import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'main.dart' show MenuPage;

/// 搜索商家/菜品:冷启动给热搜词(真实销量,天然反刷)+ 本地搜索历史。
class SearchPage extends StatefulWidget {
  const SearchPage({super.key, required this.api, this.lat, this.lng});

  final ApiClient api;
  final double? lat; // 用户位置:用于距离筛选与综合/距离排序
  final double? lng;

  @override
  State<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends State<SearchPage> {
  static const _historyKey = 'search_history';

  final _controller = TextEditingController();
  Timer? _debounce;
  List<Merchant>? _results;
  bool _searching = false;
  List<String> _history = [];
  List<String> _hot = [];
  // 联想(输入中,未提交)
  List<String> _suggest = [];
  // 排序与筛选
  String _sort = 'comprehensive';
  bool _hasPromo = false;
  double? _minRating;
  int? _maxDistanceM;
  String _lastQuery = '';

  static const _sortLabels = {
    'comprehensive': '综合',
    'distance': '距离最近',
    'rating': '评分最高',
    'sales': '销量最高',
  };

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((prefs) {
      if (mounted) {
        setState(
            () => _history = prefs.getStringList(_historyKey) ?? []);
      }
    });
    widget.api.hotKeywords().then((words) {
      if (mounted) setState(() => _hot = words);
    }).catchError((_) {});
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  Future<void> _remember(String q) async {
    _history.remove(q);
    _history.insert(0, q);
    if (_history.length > 10) _history = _history.sublist(0, 10);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_historyKey, _history);
  }

  Future<void> _clearHistory() async {
    setState(() => _history = []);
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_historyKey);
  }

  void _search(String q) {
    _controller.text = q;
    _controller.selection =
        TextSelection.collapsed(offset: q.length);
    _onChanged(q, immediate: true);
  }

  void _onChanged(String text, {bool immediate = false}) {
    _debounce?.cancel();
    final q = text.trim();
    if (q.isEmpty) {
      setState(() {
        _results = null;
        _suggest = [];
      });
      return;
    }
    if (immediate) {
      _runSearch(q);
      return;
    }
    // 输入中:防抖拉联想(不立刻搜),提交或点联想才真正搜
    _debounce = Timer(const Duration(milliseconds: 250), () async {
      try {
        final s = await widget.api.searchSuggest(q);
        if (mounted && _controller.text.trim() == q) {
          setState(() => _suggest = [...s.shops, ...s.dishes]);
        }
      } catch (_) {}
    });
  }

  Future<void> _runSearch(String q) async {
    _lastQuery = q;
    setState(() {
      _searching = true;
      _suggest = [];
    });
    try {
      final results = await widget.api.searchMerchants(
        q,
        lat: widget.lat,
        lng: widget.lng,
        sort: _sort,
        hasPromo: _hasPromo,
        minRating: _minRating,
        maxDistanceM: _maxDistanceM,
      );
      if (mounted) {
        setState(() => _results = results);
        _remember(q);
        Analytics.track('search', {'q': q, 'hits': results.length});
      }
    } catch (_) {
    } finally {
      if (mounted) setState(() => _searching = false);
    }
  }

  /// 排序/筛选变更后,若已有查询则用新条件重搜
  void _rerunIfSearched() {
    if (_lastQuery.isNotEmpty) _runSearch(_lastQuery);
  }

  Widget _chipWrap(List<String> words) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        for (final w in words)
          ActionChip(
            label: Text(w, style: const TextStyle(fontSize: 13)),
            visualDensity: VisualDensity.compact,
            onPressed: () => _search(w),
          ),
      ],
    );
  }

  /// 冷启动引导:搜索历史 + 热搜词
  Widget _suggestions() {
    final theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (_history.isNotEmpty) ...[
          Row(
            children: [
              Text('搜索历史',
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.bold)),
              const Spacer(),
              IconButton(
                icon: const Icon(Icons.delete_outline, size: 18),
                tooltip: '清空历史',
                onPressed: _clearHistory,
              ),
            ],
          ),
          _chipWrap(_history),
          const SizedBox(height: 20),
        ],
        if (_hot.isNotEmpty) ...[
          Row(
            children: [
              Icon(Icons.local_fire_department,
                  size: 18, color: theme.colorScheme.primary),
              const SizedBox(width: 4),
              Text('大家都在点',
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.bold)),
            ],
          ),
          const SizedBox(height: 8),
          _chipWrap(_hot),
        ],
        if (_history.isEmpty && _hot.isEmpty)
          const Padding(
            padding: EdgeInsets.only(top: 80),
            child: Center(child: Text('输入关键词开始搜索')),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final results = _results;
    return Scaffold(
      appBar: AppBar(
        title: TextField(
          controller: _controller,
          autofocus: true,
          onChanged: _onChanged,
          textInputAction: TextInputAction.search,
          onSubmitted: (q) => _onChanged(q, immediate: true),
          decoration: const InputDecoration(
            hintText: '搜店铺或菜品,如「牛肉面」',
            border: InputBorder.none,
          ),
        ),
        actions: [
          if (_searching)
            const Padding(
              padding: EdgeInsets.all(14),
              child: SizedBox(
                  width: 20, height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2)),
            ),
        ],
      ),
      body: _suggest.isNotEmpty
          ? _suggestList()
          : results == null
              ? _suggestions()
              : Column(
                  children: [
                    _sortFilterBar(),
                    Expanded(
                      child: results.isEmpty
                          ? const EmptyState(
                              icon: Icons.search_off,
                              text: '没有找到相关的店铺或菜品\n换个关键词或放宽筛选')
                          : ListView.builder(
                              itemCount: results.length,
                              itemBuilder: (context, i) {
                                final m = results[i];
                                return FadeSlideIn(
                                  index: i,
                                  child: ListTile(
                                    leading: m.logoUrl.isEmpty
                                        ? const CircleAvatar(
                                            child: Icon(Icons.restaurant))
                                        : CircleAvatar(
                                            backgroundImage: NetworkImage(
                                                widget.api
                                                    .resolveUrl(m.logoUrl))),
                                    title: Text(m.name),
                                    subtitle: Text(
                                        '${m.ratingLabel} · ${m.address}'),
                                    onTap: () => Navigator.of(context).push(
                                        MaterialPageRoute(
                                            builder: (_) => MenuPage(
                                                api: widget.api,
                                                merchant: m))),
                                  ),
                                );
                              },
                            ),
                    ),
                  ],
                ),
    );
  }

  /// 输入中的联想词:点一下即用该词搜索
  Widget _suggestList() {
    return ListView(
      children: [
        for (final s in _suggest)
          ListTile(
            dense: true,
            leading: const Icon(Icons.search, size: 18),
            title: Text(s),
            onTap: () => _search(s),
          ),
      ],
    );
  }

  /// 排序切换 + 筛选入口(变更即用当前关键词重搜)
  Widget _sortFilterBar() {
    final theme = Theme.of(context);
    final hasFilter =
        _hasPromo || _minRating != null || _maxDistanceM != null;
    return SizedBox(
      height: 46,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        children: [
          for (final e in _sortLabels.entries)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ChoiceChip(
                label: Text(e.value),
                selected: _sort == e.key,
                onSelected: (_) {
                  setState(() => _sort = e.key);
                  _rerunIfSearched();
                },
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: ActionChip(
              avatar: Icon(Icons.tune,
                  size: 16,
                  color: hasFilter ? theme.colorScheme.primary : null),
              label: Text(hasFilter ? '筛选·已启用' : '筛选'),
              onPressed: _openFilterSheet,
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _openFilterSheet() async {
    await showModalBottomSheet(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setSheet) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('筛选', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('只看有优惠(满减/满赠)'),
                  value: _hasPromo,
                  onChanged: (v) => setSheet(() => _hasPromo = v),
                ),
                const Text('最低评分'),
                Wrap(spacing: 8, children: [
                  for (final r in [null, 3.0, 4.0, 4.5])
                    ChoiceChip(
                      label: Text(r == null ? '不限' : '$r 星+'),
                      selected: _minRating == r,
                      onSelected: (_) => setSheet(() => _minRating = r),
                    ),
                ]),
                const SizedBox(height: 8),
                const Text('距离'),
                Wrap(spacing: 8, children: [
                  for (final d in [null, 1000, 3000, 5000])
                    ChoiceChip(
                      label: Text(d == null ? '不限' : '${d ~/ 1000}km 内'),
                      selected: _maxDistanceM == d,
                      onSelected: (_) => setSheet(() => _maxDistanceM = d),
                    ),
                ]),
                const SizedBox(height: 12),
                Row(children: [
                  TextButton(
                    onPressed: () => setSheet(() {
                      _hasPromo = false;
                      _minRating = null;
                      _maxDistanceM = null;
                    }),
                    child: const Text('重置'),
                  ),
                  const Spacer(),
                  FilledButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('查看结果'),
                  ),
                ]),
              ],
            ),
          ),
        ),
      ),
    );
    if (mounted) {
      setState(() {});
      _rerunIfSearched();
    }
  }
}
