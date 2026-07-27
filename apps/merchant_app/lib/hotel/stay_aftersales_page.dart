import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 商家端:住宿售后处理。
/// 到店无房 2 小时不响应按成立处理(全额退+首晚 30% 违约金);
/// 协商退同意时填退款金额(0~全额),平台只留证不强制。
class StayAftersalesPage extends StatefulWidget {
  const StayAftersalesPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<StayAftersalesPage> createState() => _StayAftersalesPageState();
}

class _StayAftersalesPageState extends State<StayAftersalesPage> {
  late Future<List<StayAfterSale>> _future =
      widget.api.merchantStayAftersales();

  Future<void> _refresh() async {
    setState(() => _future = widget.api.merchantStayAftersales());
    await _future;
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _respond(StayAfterSale a, bool accept) async {
    final note = TextEditingController();
    final amount = TextEditingController();
    final isNego = a.kind == 'nego_refund';
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(accept
            ? (isNego ? '同意协商退' : '确认无房,认罚')
            : '拒绝该申请'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          if (accept && !isNego)
            Text('将全额退款 ${yuan(a.totalCents)},并从你的余额中'
                '扣除首晚 30% 违约金赔付客人(平台分文不取)。'),
          if (accept && isNego) ...[
            Text('房费 ${yuan(a.totalCents)},你同意退多少?'),
            const SizedBox(height: 8),
            TextField(
              controller: amount,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                  labelText: '退款金额(元)', border: OutlineInputBorder()),
            ),
          ],
          const SizedBox(height: 8),
          TextField(
            controller: note,
            maxLength: 300,
            decoration: InputDecoration(
                labelText: accept ? '给客人的说明(选填)' : '拒绝原因(会展示给客人)',
                border: const OutlineInputBorder()),
          ),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('确定')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.respondStayAftersale(a.id,
          accept: accept,
          note: note.text.trim(),
          refundCents: accept && isNego
              ? ((double.tryParse(amount.text) ?? 0) * 100).round()
              : null);
      _snack('已处理');
      _refresh();
    } catch (e) {
      _snack(e is ApiException ? e.message : '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('售后处理')),
      body: FutureBuilder<List<StayAfterSale>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: CircularProgressIndicator());
          }
          final list = snapshot.data ?? const <StayAfterSale>[];
          if (list.isEmpty) {
            return const Center(child: Text('没有售后申请'));
          }
          return RefreshIndicator(
            onRefresh: _refresh,
            child: ListView.builder(
              itemCount: list.length,
              itemBuilder: (context, i) {
                final a = list[i];
                final pending = a.status == 'pending';
                return Card(
                  margin:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(children: [
                            Chip(label: Text(a.kindLabel)),
                            const SizedBox(width: 8),
                            Expanded(
                                child: Text(
                                    '单号 …${a.orderNo.length > 6 ? a.orderNo.substring(a.orderNo.length - 6) : a.orderNo}'
                                    ' · ${a.guestName}')),
                            Text(a.statusLabel,
                                style: TextStyle(
                                    color: pending
                                        ? theme.colorScheme.primary
                                        : theme.colorScheme.outline,
                                    fontWeight: FontWeight.bold)),
                          ]),
                          Text('房费 ${yuan(a.totalCents)}'),
                          if (a.note.isNotEmpty) Text('客人说明:${a.note}'),
                          if (a.merchantNote.isNotEmpty)
                            Text('我的回应:${a.merchantNote}',
                                style: theme.textTheme.bodySmall),
                          if (a.resolvedOk)
                            Text('退款 ${yuan(a.refundCents)}'
                                '${a.penaltyCents > 0 ? "(含违约金 ${yuan(a.penaltyCents)})" : ""}',
                                style: theme.textTheme.bodySmall),
                          if (pending) ...[
                            const SizedBox(height: 4),
                            if (a.kind == 'no_room')
                              Text('2 小时未响应将按成立处理',
                                  style: theme.textTheme.bodySmall
                                      ?.copyWith(color: Colors.deepOrange)),
                            Row(
                                mainAxisAlignment: MainAxisAlignment.end,
                                children: [
                                  OutlinedButton(
                                      onPressed: () => _respond(a, false),
                                      child: const Text('拒绝')),
                                  const SizedBox(width: 8),
                                  FilledButton(
                                      onPressed: () => _respond(a, true),
                                      child: Text(a.kind == 'no_room'
                                          ? '确认无房,认罚'
                                          : '同意退款')),
                                ]),
                          ],
                        ]),
                  ),
                );
              },
            ),
          );
        },
      ),
    );
  }
}
