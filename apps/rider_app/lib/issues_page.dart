/// 我的配送异常与申诉:上报记录列表;判骑手责任的裁决可在 72 小时内申诉。
///
/// 判骑手责任的钱(服务端 services/rider_fault):顾客全额退款,这单配送费不计,
/// 商家那份餐钱先由骑手保障金池出、不够的从骑手收入里扣,不封顶;申诉成立扣的钱退回。
///
/// 裁成「退款」判的是谁,**以服务端给的 fault 为准**(services/delivery_fault):
/// 到店未出餐、餐品不齐判的是商家责任,不算骑手的,也就没有申诉按钮。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

const _kindLabels = {
  'cannot_contact': '联系不上顾客',
  'wrong_address': '地址错误',
  'food_damaged': '餐品洒损',
  'not_ready': '到店未出餐',
  'items_missing': '餐品不齐',
  'other': '其他',
};
const _resolutionLabels = {
  'continue_delivery': '已协调,继续配送',
  'mark_delivered': '按送达处理(用户原因)',
  'refund': '判骑手责任(这单配送费不计,商家那份餐钱先由保障金池出,不够的从收入里扣,不封顶;'
      '72 小时内可申诉,成立全部退回)',
};

/// 老服务端不带 fault 时的兜底:和服务端 delivery_fault.MERCHANT_KINDS 同一组
const _merchantKinds = {'not_ready', 'items_missing'};

/// 这一条判的是谁的责任:customer / rider / merchant,没判谁的责任为空串。
String issueFault(Map<String, dynamic> issue) {
  final f = issue['fault'];
  if (f is String) return f;
  final resolution = issue['resolution'] as String? ?? '';
  if (resolution == 'mark_delivered') return 'customer';
  if (resolution == 'refund') {
    return _merchantKinds.contains(issue['kind']) ? 'merchant' : 'rider';
  }
  return '';
}

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

  /// 拉失败的原因;空串 = 上一次是成功的。
  ///
  /// 这一页拉不到会写成「还没有配送异常上报记录」—— 而骑手正是因为
  /// **有**一次判责才点进来的。看到"没有记录"他会以为申诉入口没了
  String _error = '';

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
          _error = '';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loaded = true;
          _error = e is ApiException ? e.message : '$e';
        });
      }
    }
  }

  Future<void> _appeal(Map<String, dynamic> issue) async {
    final controller = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: const Text('申诉这次判责'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('说明为什么这不是你的责任,平台会人工复核;'
                '申诉成立会为你消除责任记录,判责时扣的钱退回你的收入。',
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
    // 「还没有记录」和「没拉到」必须分开:骑手是因为**有**一次判责
    // 才点进来的,看到"还没有配送异常上报记录"他会以为申诉入口没了
    final loadFailed = _error.isNotEmpty && _issues.isEmpty;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('配送异常与申诉')),
      body: _loaded && !loadFailed
          ? RefreshIndicator(
              onRefresh: _load,
              child: _issues.isEmpty
                  ? ListView(children: const [
                      Padding(
                          padding: EdgeInsets.all(24),
                          child: Text('还没有配送异常上报记录')),
                    ])
                  : ListView.builder(
                      padding: const EdgeInsets.all(12),
                      // 有旧列表但这次没刷成功:顶一条,别让人以为是最新的
                      itemCount: _issues.length + (_error.isEmpty ? 0 : 1),
                      itemBuilder: (context, index) {
                        if (_error.isNotEmpty) {
                          if (index == 0) {
                            return SzRetryBanner(
                                text: '这次没刷新成功($_error),下面是上一次的记录',
                                onRetry: _load);
                          }
                        }
                        final i = _error.isEmpty ? index : index - 1;
                        final issue = _issues[i];
                        final resolution = issue['resolution'] as String? ?? '';
                        final open = (issue['status'] as String?) == 'open';
                        final appeal = _appeals[issue['id'] as int];
                        final fault = issueFault(issue);
                        // 只有判骑手责任的才算你的、才给申诉:到店未出餐、餐品不齐判的是商家
                        final blamed = fault == 'rider';
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
                                      : fault == 'merchant'
                                          ? '判商家责任,商家承担退款(不算你的,配送费照常结算)'
                                          : (_resolutionLabels[resolution] ??
                                              resolution),
                                  style: TextStyle(
                                      color: blamed
                                          ? theme.colorScheme.error
                                          : Theme.of(context).sz.earn,
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
            )
          : loadFailed
              ? SzError(error: '上报记录没能加载出来:$_error', onRetry: _load)
              : const Center(child: CircularProgressIndicator()),
    );
  }
}
