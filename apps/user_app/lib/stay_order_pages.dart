import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

/// 住宿订单列表(嵌在订单 tab 的「住宿」分栏,无 Scaffold)。
class StayOrderListView extends StatefulWidget {
  const StayOrderListView({super.key, required this.api});

  final ApiClient api;

  @override
  State<StayOrderListView> createState() => _StayOrderListViewState();
}

class _StayOrderListViewState extends State<StayOrderListView> {
  late Future<List<StayOrder>> _future = widget.api.myStayOrders();

  Color _statusColor(String status, ThemeData theme) => switch (status) {
        'completed' => kMoneyGreen,
        'cancelled' || 'closed' || 'rejected' || 'noshow' =>
          theme.colorScheme.outline,
        _ => theme.colorScheme.primary,
      };

  Future<void> _refresh() async {
    setState(() => _future = widget.api.myStayOrders());
    await _future;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return FutureBuilder<List<StayOrder>>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        final orders = snapshot.data ?? const <StayOrder>[];
        if (orders.isEmpty) {
          return RefreshIndicator(
            onRefresh: _refresh,
            child: ListView(children: const [
              Padding(
                  padding: EdgeInsets.all(48),
                  child: Center(child: Text('还没有住宿订单\n首页「住宿」逛逛?',
                      textAlign: TextAlign.center))),
            ]),
          );
        }
        return RefreshIndicator(
          onRefresh: _refresh,
          child: ListView.builder(
            itemCount: orders.length,
            itemBuilder: (context, i) {
              final o = orders[i];
              return Card(
                margin:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                child: ListTile(
                  title: Text('${o.hotelName} · ${o.roomTypeName}'),
                  subtitle: Text('${o.stayLabel}\n${yuan(o.totalCents)}'),
                  isThreeLine: true,
                  trailing: Text(o.statusLabel,
                      style: TextStyle(
                          color: _statusColor(o.status, theme),
                          fontWeight: FontWeight.bold)),
                  onTap: () async {
                    await Navigator.of(context).push(MaterialPageRoute(
                        builder: (_) => StayOrderDetailPage(
                            api: widget.api, orderNo: o.orderNo)));
                    _refresh();
                  },
                ),
              );
            },
          ),
        );
      },
    );
  }
}

/// 住宿订单详情:状态时间线 + 入住凭证 + 资金流三行 + 取消试算。
class StayOrderDetailPage extends StatefulWidget {
  const StayOrderDetailPage(
      {super.key, required this.api, required this.orderNo});

  final ApiClient api;
  final String orderNo;

  @override
  State<StayOrderDetailPage> createState() => _StayOrderDetailPageState();
}

class _StayOrderDetailPageState extends State<StayOrderDetailPage> {
  StayOrder? _order;
  StayReview? _review;
  StayAfterSale? _aftersale;
  String? _error;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load();
    // 待确认/待支付状态轮询,商家一确认页面自动更新
    _poll = Timer.periodic(const Duration(seconds: 10), (_) {
      final o = _order;
      if (o != null && (o.status == 'paid' || o.status == 'created')) _load();
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final order = await widget.api.stayOrderDetail(widget.orderNo);
      StayReview? review;
      if (order.status == 'completed') {
        try {
          review = await widget.api.myStayReview(widget.orderNo);
        } catch (_) {} // 404 = 还没评价
      }
      StayAfterSale? aftersale;
      try {
        aftersale = await widget.api.myStayAftersale(widget.orderNo);
      } catch (_) {} // 404 = 没有售后
      if (mounted) {
        setState(() {
          _order = order;
          _review = review;
          _aftersale = aftersale;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => _error = e is ApiException ? e.message : '$e');
      }
    }
  }

  /// 评价弹层:星级 + 一键标签 + 文字 + 匿名
  Future<void> _reviewSheet(StayOrder order) async {
    var rating = 5;
    final selected = <String>{};
    final comment = TextEditingController();
    var anonymous = false;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) => Padding(
          padding: EdgeInsets.only(
              left: 16, right: 16, top: 16,
              bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('这次住得怎么样?',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                Row(children: [
                  for (var i = 1; i <= 5; i++)
                    IconButton(
                      icon: Icon(
                          i <= rating ? Icons.star : Icons.star_border,
                          color: Colors.amber, size: 30),
                      onPressed: () => setSheet(() => rating = i),
                    ),
                ]),
                Wrap(spacing: 8, runSpacing: 4, children: [
                  for (final tag in kStayReviewTags)
                    FilterChip(
                      label: Text(tag),
                      selected: selected.contains(tag),
                      onSelected: (v) => setSheet(() =>
                          v ? selected.add(tag) : selected.remove(tag)),
                    ),
                ]),
                const SizedBox(height: 8),
                TextField(
                  controller: comment,
                  maxLength: 500,
                  maxLines: 3,
                  decoration: const InputDecoration(
                      hintText: '说说你的入住体验(选填)',
                      border: OutlineInputBorder()),
                ),
                SwitchListTile(
                  title: const Text('匿名评价'),
                  subtitle: const Text('显示为「匿名住客」,酒店无法反查'),
                  value: anonymous,
                  onChanged: (v) => setSheet(() => anonymous = v),
                ),
                SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                        onPressed: () => Navigator.pop(sheetContext, true),
                        child: const Text('提交评价'))),
              ],
            ),
          ),
        ),
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.createStayReview(order.orderNo,
          rating: rating,
          comment: comment.text.trim(),
          tags: selected.toList(),
          isAnonymous: anonymous);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('评价成功,感谢反馈')));
      }
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  /// 取消:先试算展示预计退款,确认后执行
  Future<void> _cancel(StayOrder order) async {
    StayCancelPreview preview;
    try {
      preview = await widget.api.stayCancelPreview(order.orderNo);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
      return;
    }
    if (!mounted) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('确认取消?'),
        content: Column(mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(preview.note),
              const SizedBox(height: 8),
              Text('预计退款:${yuan(preview.refundCents)}',
                  style: const TextStyle(
                      color: kMoneyGreen, fontWeight: FontWeight.bold)),
              if (preview.penaltyCents > 0)
                Text('扣款:${yuan(preview.penaltyCents)}(归商家,平台分文不取)',
                    style: const TextStyle(fontSize: 13)),
            ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('再想想')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('确认取消')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.cancelStayOrder(order.orderNo);
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final order = _order;
    if (order == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('订单详情')),
        body: Center(
            child: _error == null
                ? const CircularProgressIndicator()
                : Text(_error!)),
      );
    }
    final cancellable =
        order.status == 'paid' || order.status == 'confirmed';
    return Scaffold(
      appBar: AppBar(title: Text(order.statusLabel)),
      body: ListView(padding: const EdgeInsets.all(12), children: [
        _timeline(theme, order),
        // 入住凭证:到店出示订单号与入住人即可
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('入住凭证', style: theme.textTheme.titleSmall),
              const SizedBox(height: 8),
              Text('${order.hotelName} · ${order.roomTypeName} × ${order.roomsQty} 间',
                  style: theme.textTheme.titleMedium),
              Text('${order.checkinDate} 入住 → ${order.checkoutDate} 退房'
                  '(${order.nights} 晚)'),
              Text('入住人:${order.guestName} ${order.guestPhone}'),
              if (order.arrivalNote.isNotEmpty)
                Text('预计到店:${order.arrivalNote}'),
              const SizedBox(height: 4),
              SelectableText('订单号:${order.orderNo}',
                  style: theme.textTheme.bodySmall),
              if (order.hotelAddress.isNotEmpty)
                Row(children: [
                  Expanded(
                      child: Text('地址:${order.hotelAddress}',
                          style: theme.textTheme.bodySmall)),
                  if (order.hotelPhone.isNotEmpty)
                    TextButton.icon(
                        icon: const Icon(Icons.phone, size: 16),
                        label: const Text('联系酒店'),
                        onPressed: () => launchUrl(
                            Uri.parse('tel:${order.hotelPhone}'))),
                ]),
              if (order.status == 'rejected')
                Text('商家拒单:${order.rejectReason}',
                    style: TextStyle(color: theme.colorScheme.error)),
            ]),
          ),
        ),
        // 资金流三行:账目透明是卖点
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('这笔钱怎么分', style: theme.textTheme.titleSmall),
              const SizedBox(height: 8),
              _moneyRow('房费', order.totalCents),
              if (order.status == 'completed') ...[
                _moneyRow('平台佣金(5%)', -order.feeCents),
                _moneyRow('商家实收', order.netCents, bold: true),
              ] else if (order.refundCents > 0 ||
                  const {'cancelled', 'noshow'}.contains(order.status)) ...[
                _moneyRow('退回给你', order.refundCents, green: true),
                if (order.netCents > 0)
                  _moneyRow('商家所得(平台 0 佣金)', order.netCents),
              ] else
                const Padding(
                  padding: EdgeInsets.only(top: 4),
                  child: Text('佣金 5% 在离店后才产生;取消或未入住,平台分文不取',
                      style: TextStyle(fontSize: 12)),
                ),
              if (order.refundNote.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(order.refundNote,
                      style: theme.textTheme.bodySmall),
                ),
            ]),
          ),
        ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              const Icon(Icons.info_outline, size: 16),
              const SizedBox(width: 8),
              Expanded(
                  child: Text(order.cancelPolicyText,
                      style: theme.textTheme.bodySmall)),
            ]),
          ),
        ),
        // 离店后评价(15 天内);已评展示内容与酒店回复
        if (order.status == 'completed')
          _review == null
              ? Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: FilledButton.tonalIcon(
                      icon: const Icon(Icons.rate_review_outlined, size: 18),
                      onPressed: () => _reviewSheet(order),
                      label: const Text('评价这次入住')),
                )
              : Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(children: [
                            Text('我的评价',
                                style: theme.textTheme.titleSmall),
                            const Spacer(),
                            for (var i = 1; i <= 5; i++)
                              Icon(
                                  i <= _review!.rating
                                      ? Icons.star
                                      : Icons.star_border,
                                  size: 16,
                                  color: Colors.amber),
                          ]),
                          if (_review!.comment.isNotEmpty)
                            Text(_review!.comment),
                          if (_review!.tags.isNotEmpty)
                            Text(_review!.tags.join(' · '),
                                style: theme.textTheme.bodySmall),
                          if (_review!.reply.isNotEmpty)
                            Text('酒店回复:${_review!.reply}',
                                style: theme.textTheme.bodySmall),
                        ]),
                  ),
                ),
        // 售后状态卡
        if (_aftersale != null)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(children: [
                      Text('售后:${_aftersale!.kindLabel}',
                          style: theme.textTheme.titleSmall),
                      const Spacer(),
                      Text(_aftersale!.statusLabel,
                          style: TextStyle(
                              color: _aftersale!.resolvedOk
                                  ? kMoneyGreen
                                  : (_aftersale!.status == 'pending'
                                      ? theme.colorScheme.primary
                                      : theme.colorScheme.outline),
                              fontWeight: FontWeight.bold)),
                    ]),
                    if (_aftersale!.resolvedOk)
                      Text('退款 ${yuan(_aftersale!.refundCents)}'
                          '${_aftersale!.penaltyCents > 0 ? "(含商家违约金 ${yuan(_aftersale!.penaltyCents)})" : ""}'
                          ' 将原路退回'),
                    if (_aftersale!.merchantNote.isNotEmpty)
                      Text('商家回应:${_aftersale!.merchantNote}',
                          style: theme.textTheme.bodySmall),
                    if (_aftersale!.status == 'pending' &&
                        _aftersale!.kind == 'no_room')
                      Text('商家 2 小时未响应将自动按成立处理',
                          style: theme.textTheme.bodySmall),
                  ]),
            ),
          ),
        const SizedBox(height: 12),
        if (cancellable)
          OutlinedButton(
              onPressed: () => _cancel(order), child: const Text('取消订单')),
        // 到店无房:已确认且到了入住日,前台却没房
        if (order.status == 'confirmed' &&
            DateTime.now().compareTo(
                    DateTime.parse('${order.checkinDate} 00:00:00')) >=
                0 &&
            (_aftersale == null || _aftersale!.status != 'pending'))
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: OutlinedButton.icon(
                icon: const Icon(Icons.report_problem_outlined, size: 18),
                onPressed: () => _aftersaleSheet(order, 'no_room'),
                label: const Text('到店无房?发起赔付')),
          ),
        // strict 档协商退
        if (const {'paid', 'confirmed'}.contains(order.status) &&
            order.cancelPolicy == 'strict' &&
            (_aftersale == null || _aftersale!.status != 'pending'))
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: OutlinedButton(
                onPressed: () => _aftersaleSheet(order, 'nego_refund'),
                child: const Text('申请协商退款')),
          ),
      ]),
    );
  }

  /// 售后发起弹层
  Future<void> _aftersaleSheet(StayOrder order, String kind) async {
    final controller = TextEditingController();
    final isNoRoom = kind == 'no_room';
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(isNoRoom ? '到店无房' : '申请协商退款'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(isNoRoom
              ? '商家确认后却没有房间?发起后商家需在 2 小时内处理,'
                  '成立即全额退款,商家另赔首晚 30% 违约金(平台分文不取)。'
              : '该房型不可退,但你可以说明情况请商家通融;'
                  '商家同意多少退多少,平台只留证不强制。'),
          const SizedBox(height: 12),
          TextField(
            controller: controller,
            maxLength: 300,
            maxLines: 2,
            decoration: const InputDecoration(
                hintText: '说明情况', border: OutlineInputBorder()),
          ),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('提交')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.createStayAftersale(order.orderNo,
          kind: kind, note: controller.text.trim());
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('已提交,等待商家处理')));
      }
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  Widget _moneyRow(String label, int cents,
      {bool bold = false, bool green = false}) {
    final style = TextStyle(
        fontWeight: bold ? FontWeight.bold : null,
        color: green ? kMoneyGreen : null);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(children: [
        Text(label, style: style),
        const Spacer(),
        Text(yuan(cents.abs()) + (cents < 0 ? '(平台收取)' : ''),
            style: style),
      ]),
    );
  }

  Widget _timeline(ThemeData theme, StayOrder order) {
    final steps = <(String, String?, bool)>[
      ('下单', order.createdAt, true),
      ('支付', order.paidAt, order.paidAt != null),
      ('商家确认', order.confirmedAt, order.confirmedAt != null),
      ('入住', order.checkedInAt, order.checkedInAt != null),
      ('离店', order.completedAt, order.completedAt != null),
    ];
    final terminated = const {'cancelled', 'closed', 'rejected', 'noshow'}
        .contains(order.status);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (terminated)
            Text('订单已终止:${order.statusLabel}',
                style: TextStyle(
                    color: theme.colorScheme.outline,
                    fontWeight: FontWeight.bold))
          else
            Row(children: [
              for (final (label, _, done) in steps) ...[
                Column(children: [
                  Icon(done ? Icons.check_circle : Icons.circle_outlined,
                      size: 18,
                      color: done
                          ? theme.colorScheme.primary
                          : theme.colorScheme.outline),
                  Text(label, style: const TextStyle(fontSize: 11)),
                ]),
                if (label != '离店')
                  Expanded(
                      child: Divider(
                          thickness: 1.5,
                          color: theme.colorScheme.outlineVariant)),
              ],
            ]),
        ]),
      ),
    );
  }
}
