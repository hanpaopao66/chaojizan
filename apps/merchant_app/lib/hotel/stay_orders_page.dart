import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../listen_service.dart';

/// 住宿订单 tab:待确认/今日预抵/在住/今日预离/全部,
/// 确认→入住→离店全流程 + 新单语音循环播报(与外卖同通道)。
class StayOrdersPage extends StatefulWidget {
  const StayOrdersPage({super.key, required this.api, required this.shop});

  final ApiClient api;
  final Merchant shop;

  @override
  State<StayOrdersPage> createState() => _StayOrdersPageState();
}

class _StayOrdersPageState extends State<StayOrdersPage> {
  static const _states = [
    ('pending', '待确认'),
    ('arriving', '今日预抵'),
    ('inhouse', '在住'),
    ('leaving', '今日预离'),
    ('all', '全部'),
  ];

  String _state = 'pending';
  List<StayOrder> _orders = [];
  int _pendingCount = 0;
  bool _loaded = false;
  Timer? _timer;
  Timer? _alertTimer;
  Timer? _wsPing;
  WebSocketChannel? _ws;

  final OrderAnnouncer _announcer = OrderAnnouncer();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      // 锁屏不丢单三件套(与外卖同一套):权限引导 → 前台服务
      await ListenKeepAlive.ensurePermissions(context);
      await ListenKeepAlive.start();
    });
    _refresh();
    // 轮询保底(WS 断线期间也不漏单)
    _timer = Timer.periodic(const Duration(seconds: 20), (_) => _refresh());
    // 持续催办:有待确认单每 15 秒播报一次,直到处理
    _alertTimer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (_pendingCount > 0) _announcer.announce();
    });
    _connectWs();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _alertTimer?.cancel();
    _wsPing?.cancel();
    _ws?.sink.close();
    _announcer.dispose();
    ListenKeepAlive.stop();
    super.dispose();
  }

  void _connectWs() {
    final uri = Uri.parse(
        '${widget.api.wsBaseUrl}/ws/merchants/${widget.shop.id}?token=${widget.api.token}');
    try {
      _ws = WebSocketChannel.connect(uri);
    } catch (_) {
      _scheduleReconnect();
      return;
    }
    _wsPing?.cancel();
    _wsPing = Timer.periodic(
        const Duration(seconds: 30), (_) => _ws?.sink.add('ping'));
    _ws!.stream.listen(
      (message) {
        final data = jsonDecode(message as String) as Map<String, dynamic>;
        if (data['type'] == 'new_stay_order') {
          _announcer.announce();
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              content: Text(
                  '🔔 新住宿订单:${data['summary']} ${yuan(data['total_cents'] as int)}'),
              duration: const Duration(seconds: 6),
            ));
          }
          _refresh();
        }
      },
      onError: (_) => _scheduleReconnect(),
      onDone: _scheduleReconnect,
    );
  }

  void _scheduleReconnect() {
    Timer(const Duration(seconds: 5), () {
      if (mounted) _connectWs();
    });
  }

  Future<void> _refresh() async {
    try {
      final orders = await widget.api.stayMerchantOrders(state: _state);
      // 待确认角标独立拉取(当前筛选可能不是 pending)
      final pending = _state == 'pending'
          ? orders
          : await widget.api.stayMerchantOrders(state: 'pending');
      if (mounted) {
        setState(() {
          _orders = orders;
          _pendingCount = pending.length;
          _loaded = true;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loaded = true);
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  /// 二次确认弹层后执行操作;离店操作展示结算金额
  Future<void> _confirmThen(String title, String body,
      Future<StayOrder> Function() action, {String? doneMessage}) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(body),
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
      final updated = await action();
      if (doneMessage != null) {
        _snack(doneMessage);
      } else if (updated.status == 'completed') {
        _snack('已办理离店,实收 ${yuan(updated.netCents)}'
            '(房费 ${yuan(updated.totalCents)} − 佣金 5% ${yuan(updated.feeCents)})');
      }
      _refresh();
    } catch (e) {
      _snack(e is ApiException ? e.message : '$e');
    }
  }

  Future<void> _reject(StayOrder order) async {
    final controller = TextEditingController(text: '满房,暂时无法接待');
    final reason = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('拒单原因'),
        content: TextField(
          controller: controller,
          maxLength: 100,
          decoration: const InputDecoration(
              helperText: '会展示给客人,订单将全额退款',
              border: OutlineInputBorder()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: const Text('确认拒单')),
        ],
      ),
    );
    if (reason == null || reason.length < 2) return;
    try {
      await widget.api.stayReject(order.orderNo, reason);
      _snack('已拒单,房费将全额退回客人');
      _refresh();
    } catch (e) {
      _snack(e is ApiException ? e.message : '$e');
    }
  }

  List<Widget> _actionsFor(StayOrder order) {
    switch (order.status) {
      case 'paid':
        return [
          OutlinedButton(
              onPressed: () => _reject(order), child: const Text('拒单')),
          const SizedBox(width: 8),
          FilledButton(
              onPressed: () => _confirmThen(
                  '确认订单',
                  '确认后请为客人保留房间:\n${order.roomTypeName}×${order.roomsQty},'
                      '${order.checkinDate} 入住 ${order.nights} 晚',
                  () => widget.api.stayConfirm(order.orderNo),
                  doneMessage: '已确认,客人会收到通知'),
              child: const Text('确认订单')),
        ];
      case 'confirmed':
        return [
          FilledButton.icon(
              icon: const Icon(Icons.login, size: 18),
              onPressed: () => _confirmThen(
                  '办理入住',
                  '请核对入住人:${order.guestName} ${order.guestPhone}',
                  () => widget.api.stayCheckin(order.orderNo),
                  doneMessage: '已办理入住'),
              label: const Text('办理入住')),
        ];
      case 'checked_in':
        return [
          FilledButton.icon(
              icon: const Icon(Icons.logout, size: 18),
              onPressed: () => _confirmThen(
                  '办理离店',
                  '离店后结算:实收 = 房费 ${yuan(order.totalCents)} − 5% 佣金,'
                      '入账到店铺钱包',
                  () => widget.api.stayCheckout(order.orderNo)),
              label: const Text('办理离店')),
        ];
      default:
        return const [];
    }
  }

  Color? _statusColor(String status) => switch (status) {
        'paid' => Colors.orange,
        'confirmed' => Colors.blue,
        'checked_in' => Colors.green,
        'noshow' || 'cancelled' || 'rejected' => Colors.grey,
        _ => null,
      };

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return const Center(child: CircularProgressIndicator());
    }
    return Column(children: [
      AnnouncementBanner(api: widget.api, audience: 'merchant'),
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (final (value, label) in _states)
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(value == 'pending' && _pendingCount > 0
                      ? '$label($_pendingCount)'
                      : label),
                  selected: _state == value,
                  onSelected: (_) {
                    setState(() => _state = value);
                    _refresh();
                  },
                ),
              ),
          ]),
        ),
      ),
      Expanded(
        child: RefreshIndicator(
          onRefresh: _refresh,
          child: _orders.isEmpty
              ? ListView(children: const [
                  Padding(
                      padding: EdgeInsets.all(24),
                      child: Center(child: Text('这一栏没有订单')))
                ])
              : ListView.builder(
                  itemCount: _orders.length,
                  itemBuilder: (context, i) => _orderCard(_orders[i]),
                ),
        ),
      ),
    ]);
  }

  Widget _orderCard(StayOrder order) {
    final color = _statusColor(order.status);
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
                child: Text('${order.roomTypeName} × ${order.roomsQty} 间',
                    style: Theme.of(context).textTheme.titleMedium)),
            Chip(
              label: Text(order.statusLabel,
                  style: TextStyle(color: color, fontSize: 12)),
              side: color == null ? null : BorderSide(color: color),
            ),
          ]),
          const SizedBox(height: 4),
          Text('${order.checkinDate} → ${order.checkoutDate}'
              '(${order.nights} 晚) · ${yuan(order.totalCents)}'),
          Text('入住人:${order.guestName} · ${order.guestPhone}'),
          if (order.arrivalNote.isNotEmpty) Text('备注:${order.arrivalNote}'),
          Text(order.cancelPolicyText,
              style: Theme.of(context).textTheme.bodySmall),
          if (order.status == 'completed')
            Text('实收 ${yuan(order.netCents)}(佣金 ${yuan(order.feeCents)})',
                style: TextStyle(
                    color: Colors.green.shade700,
                    fontWeight: FontWeight.bold)),
          if (order.refundCents > 0)
            Text('已退款 ${yuan(order.refundCents)}(${order.refundNote})',
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
          if (order.status == 'noshow')
            Text('系统已按政策处理:扣首晚 ${yuan(order.netCents)} 归你,其余退客人',
                style: Theme.of(context).textTheme.bodySmall),
          if (_actionsFor(order).isNotEmpty) ...[
            const SizedBox(height: 8),
            Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: _actionsFor(order)),
          ],
        ]),
      ),
    );
  }
}
