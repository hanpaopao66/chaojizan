import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 我提交过的食安投诉。
///
/// 投诉能提交却查不到进度,用户交完照片就没下文了 —— 对一个把食安
/// 当卖点的平台,投诉黑洞比没有投诉入口更伤。服务端 /food-safety/mine
/// 早就写好了,这里只是把它接上。
class FoodSafetyRecordsPage extends StatefulWidget {
  const FoodSafetyRecordsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<FoodSafetyRecordsPage> createState() => _FoodSafetyRecordsPageState();
}

class _FoodSafetyRecordsPageState extends State<FoodSafetyRecordsPage> {
  late Future<List<Map<String, dynamic>>> _future = widget.api.myFoodSafetyReports();

  static String _kindLabel(String kind) => switch (kind) {
        'foreign_object' => '异物',
        'spoiled' => '变质',
        'sick' => '食用后不适',
        _ => '食安问题',
      };

  /// 处置结论的三态。**不认定的那一档照实写**,不粉饰成"已处理" ——
  /// 这一页的可信度全靠它敢显示对用户不利的结果
  (String, Color) _statusStyle(String status, ThemeData theme) =>
      switch (status) {
        'confirmed' => ('投诉成立,平台已处理', theme.sz.earn),
        'dismissed' => ('调查后未认定', theme.colorScheme.outline),
        _ => ('平台受理中', theme.colorScheme.primary),
      };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('我的食安投诉')),
      body: RefreshIndicator(
        onRefresh: () async =>
            setState(() => _future = widget.api.myFoodSafetyReports()),
        child: FutureBuilder<List<Map<String, dynamic>>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.hasError) {
              return SzError(
                  error: snapshot.error,
                  onRetry: () => setState(
                      () => _future = widget.api.myFoodSafetyReports()));
            }
            if (!snapshot.hasData) return const SkeletonList();
            final rows = snapshot.data!;
            if (rows.isEmpty) {
              return const SzEmpty(text: '你还没有提交过食安投诉');
            }
            return ListView.separated(
              padding: const EdgeInsets.all(12),
              itemCount: rows.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, i) {
                final r = rows[i];
                final (label, color) =
                    _statusStyle(r['status'] as String? ?? 'open', theme);
                final actions = (r['actions'] as List?) ?? const [];
                final note = actions.isEmpty
                    ? ''
                    : ((actions.last as Map)['note'] as String? ?? '');
                return Card(
                  margin: EdgeInsets.zero,
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(children: [
                          Expanded(
                            child: Text(
                                '${_kindLabel(r['kind'] as String? ?? '')}'
                                ' · 订单 ${r['order_no']}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                    fontWeight: FontWeight.w600)),
                          ),
                          Text(label,
                              style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: color)),
                        ]),
                        const SizedBox(height: 6),
                        Text(r['description'] as String? ?? '',
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.bodySmall),
                        if (note.isNotEmpty) ...[
                          const SizedBox(height: 6),
                          Text('平台回复:$note',
                              style: theme.textTheme.bodySmall
                                  ?.copyWith(color: color)),
                        ],
                      ],
                    ),
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}
