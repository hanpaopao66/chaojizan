import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 节假日计划:歇业区间 / 单日特殊营业时段。
///
/// 从 `shop_tab.dart` 搬出来 —— 一段自成一体的编辑流程,只要 api、
/// 当前店铺和一个「改完刷新」的回调。
///
/// 这件事对商家的价值是**提前告诉顾客**:春节关门七天,顾客提前看得到,
/// 就不会下单之后被取消。取消这件事在用户端是差评源头。

String _shortDate(String ymd) =>
    ymd.length >= 10 ? '${int.parse(ymd.substring(5, 7))}/${int.parse(ymd.substring(8, 10))}' : ymd;

String holidayPlanLabel(Map<String, dynamic> p) {
  final from = p['from'] as String? ?? '';
  final to = (p['to'] as String?)?.isNotEmpty == true ? p['to'] as String : from;
  final range = from == to
      ? _shortDate(from)
      : '${_shortDate(from)}~${_shortDate(to)}';
  return (p['closed'] as bool? ?? true)
      ? '$range 歇业'
      : '$range ${p['open']}-${p['close']}';
}

String _ymd(DateTime d) =>
    '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// 节假日计划管理:歇业区间 / 单日特殊时段,最多 20 条,过期自动清理
Future<void> editHolidayPlans(
  BuildContext context,
  ApiClient api,
  Merchant shop,
  Future<void> Function() reload,
) async {
  final plans = [
    for (final p in shop.holidayPlans) Map<String, dynamic>.from(p)
  ];
  final saved = await showDialog<bool>(
    context: context,
    builder: (context) => StatefulBuilder(
      builder: (context, setDialog) => SzDialog(
        title: const Text('节假日计划'),
        content: SizedBox(
          width: double.maxFinite,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (plans.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 8),
                  child: Text('暂无计划。春节歇业、除夕只开半天,都在这里提前设置。',
                      style: TextStyle(fontSize: 13)),
                ),
              for (var i = 0; i < plans.length; i++)
                Row(children: [
                  Expanded(child: Text(holidayPlanLabel(plans[i]))),
                  IconButton(
                    tooltip: '删除',
                    icon: const Icon(Icons.delete_outline, size: 20),
                    onPressed: () => setDialog(() => plans.removeAt(i)),
                  ),
                ]),
              const SizedBox(height: 4),
              if (plans.length < 20)
                Row(children: [
                  TextButton.icon(
                    icon: const Icon(Icons.event_busy, size: 18),
                    label: const Text('加歇业'),
                    onPressed: () async {
                      final now = DateTime.now();
                      final range = await showDateRangePicker(
                        context: context,
                        firstDate: now,
                        lastDate: now.add(const Duration(days: 365)),
                      );
                      if (range == null) return;
                      setDialog(() => plans.add({
                            'from': _ymd(range.start),
                            'to': _ymd(range.end),
                            'closed': true,
                          }));
                    },
                  ),
                  TextButton.icon(
                    icon: const Icon(Icons.schedule, size: 18),
                    label: const Text('加特殊时段'),
                    onPressed: () async {
                      final now = DateTime.now();
                      final date = await showDatePicker(
                        context: context,
                        firstDate: now,
                        lastDate: now.add(const Duration(days: 365)),
                      );
                      if (date == null || !context.mounted) return;
                      final open = await showTimePicker(
                          context: context,
                          initialTime:
                              const TimeOfDay(hour: 10, minute: 0),
                          helpText: '当日开店时间');
                      if (open == null || !context.mounted) return;
                      final close = await showTimePicker(
                          context: context,
                          initialTime:
                              const TimeOfDay(hour: 15, minute: 0),
                          helpText: '当日打烊时间');
                      if (close == null) return;
                      String hhmm(TimeOfDay t) =>
                          '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
                      setDialog(() => plans.add({
                            'from': _ymd(date),
                            'to': _ymd(date),
                            'closed': false,
                            'open': hhmm(open),
                            'close': hhmm(close),
                          }));
                    },
                  ),
                ]),
            ],
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('保存')),
        ],
      ),
    ),
  );
  if (saved != true || !context.mounted) return;
  try {
    await api.updateShop({'holiday_plans': plans});
    reload();
  } catch (e) {
    if (!context.mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(e.toString())));
  }
}

/// 子账号管理:列出店员 + 按手机号添加 + 移除(仅店主)
