/// 我的配送异常与申诉:上报记录列表;判骑手责任(先行赔付)的裁决可在 72 小时内申诉。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

const _kindLabels = {
  'cannot_contact': '联系不上顾客',
  'wrong_address': '地址错误',
  'food_damaged': '餐品洒损',
  'other': '其他',
};
const _resolutionLabels = {
  'continue_delivery': '已协调,继续配送',
  'mark_delivered': '按送达处理(用户原因)',
  'refund': '判骑手责任,平台先行赔付',
};

class RiderIssuesPage extends StatefulWidget {
  const RiderIssuesPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderIssuesPage> createState() => _RiderIssuesPageState();
}

class _RiderIssuesPageState extends State<RiderIssuesPage> {
  List<Map<String, dynamic>> _issues = [];
  Map<int, Map<String, dynamic>> _appeals = {}; // target_id -> appeal
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final issues = await widget.api.riderIssues();
      final appeals = await widget.api.myAppeals();
      if (mounted) {
        setState(() {
          _issues = issues;
          _appeals = {
            for (final a in appeals)
              if (a['target_type'] == 'delivery_issue')
                a['target_id'] as int: a,
          };
          _loaded = true;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loaded = true);
    }
  }

  Future<void> _appeal(Map<String, dynamic> issue) async {
    final controller = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('申诉这次判责'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('说明为什么这不是你的责任,平台会人工复核;'
                '申诉成立会为你消除责任记录(用户已得退款由平台承担)。',
                style: TextStyle(fontSize: 13)),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              maxLength: 200,
              maxLines: 3,
              decoration: const InputDecoration(
                  labelText: '申诉理由(必填)', border: OutlineInputBorder()),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('提交申诉')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await widget.api.submitAppeal(
        targetType: 'delivery_issue',
        targetId: issue['id'] as int,
        reason: controller.text.trim(),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('申诉已提交,平台会尽快复核并推送结果')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  String _appealStatusLabel(String status) => switch (status) {
        'open' => '申诉复核中',
        'upheld' => '申诉未通过(维持原判)',
        'overturned' => '申诉成立(已消责)',
        _ => status,
      };

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('配送异常与申诉')),
      body: !_loaded
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: _issues.isEmpty
                  ? ListView(children: const [
                      Padding(
                          padding: EdgeInsets.all(24),
                          child: Text('还没有配送异常上报记录')),
                    ])
                  : ListView.builder(
                      padding: const EdgeInsets.all(12),
                      itemCount: _issues.length,
                      itemBuilder: (context, i) {
                        final issue = _issues[i];
                        final resolution = issue['resolution'] as String? ?? '';
                        final open = (issue['status'] as String?) == 'open';
                        final appeal = _appeals[issue['id'] as int];
                        final blamed = resolution == 'refund';
                        return Card(
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                    '订单#${(issue['order_no'] as String).substring((issue['order_no'] as String).length - 6)}'
                                    ' · ${_kindLabels[issue['kind']] ?? issue['kind']}',
                                    style: theme.textTheme.titleSmall),
                                if ((issue['note'] as String? ?? '').isNotEmpty)
                                  Text(issue['note'] as String,
                                      style: theme.textTheme.bodySmall),
                                const SizedBox(height: 4),
                                Text(
                                  open
                                      ? '平台处理中'
                                      : (_resolutionLabels[resolution] ??
                                          resolution),
                                  style: TextStyle(
                                      color: blamed
                                          ? theme.colorScheme.error
                                          : Colors.green.shade700,
                                      fontSize: 13),
                                ),
                                if (appeal != null)
                                  Text(
                                      _appealStatusLabel(
                                          appeal['status'] as String),
                                      style: theme.textTheme.bodySmall),
                                if (blamed && appeal == null)
                                  Align(
                                    alignment: Alignment.centerRight,
                                    child: OutlinedButton(
                                      onPressed: () => _appeal(issue),
                                      child: const Text('申诉(72 小时内)'),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
            ),
    );
  }
}
