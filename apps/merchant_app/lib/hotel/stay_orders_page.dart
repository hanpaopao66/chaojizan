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

class _StayOrdersPageState extends State<StayOrdersPage>
    with WidgetsBindingObserver {
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

  /// 一次断线只排一次重连 + 指数退避。和外卖工作台同一套(见 [ReconnectPolicy]):
  /// 原来 onError / onDone 各排一个,重连数每轮翻倍
  final _reconnect = ReconnectPolicy();
  Timer? _reconnectTimer;

  final OrderAnnouncer _announcer = OrderAnnouncer();

  /// App 是不是在前台。后台时轮询降频,见 [didChangeAppLifecycleState]。
  bool _foreground = true;

  /// WebSocket 通没通。**后台靠它决定要不要轮询** ——
  /// 连着的时候轮询带不来新信息,是纯重复请求。
  bool _wsConnected = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      // 锁屏不丢单三件套(与外卖同一套):权限引导 → 前台服务
      await ListenKeepAlive.ensurePermissions(context);
      await ListenKeepAlive.start();
    });
    _refresh();
    _restartTimers();
    _connectWs();
  }

  /// 切前后台。和外卖那页同一个问题、同一套解法(#291) ——
  /// 前台服务带唤醒锁让 CPU 熄屏不休眠,而定时器在后台还全速跑,
  /// 叠起来就是「待机发热」。
  ///
  /// 听单能力一点不动(WS、前台服务、催办语音全保持),
  /// 降的是 WS 连着时那份纯重复的轮询。
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final fg = state == AppLifecycleState.resumed;
    if (fg == _foreground) return;
    _foreground = fg;
    _restartTimers();
    if (fg) _refresh();
  }

  void _restartTimers() {
    _timer?.cancel();
    _alertTimer?.cancel();
    // 轮询保底(WS 断线期间也不漏单)。
    // 后台拉到 60 秒,而且 WS 连着就整轮跳过 —— 那时它带不来新信息
    _timer = Timer.periodic(
        Duration(seconds: _foreground ? 20 : 60), (_) {
      if (!_foreground && _wsConnected) return;
      _refresh();
    });
    // 持续催办:有待确认单每 15 秒播报一次,直到处理。
    // **前后台同一个节奏** —— 后台听不见等于白做
    _alertTimer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (_pendingCount > 0) _announcer.announce();
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _alertTimer?.cancel();
    _wsPing?.cancel();
    _reconnectTimer?.cancel();
    _closeWs();
    _announcer.dispose();
    ListenKeepAlive.stop();
    super.dispose();
  }

  /// close() 可能带着「本来就没连上」的错误回来,吞掉 —— 这里只是清理
  void _closeWs() {
    final old = _ws;
    _ws = null;
    old?.sink.close().catchError((_) {});
  }

  void _connectWs() {
    if (!mounted) return;
    if (!_reconnect.beginConnect()) return; // 防重入
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    // 旧连接先关:留着它就是两条连接同时收推送,同一单播报两遍
    _wsPing?.cancel();
    _closeWs();

    final uri = Uri.parse(
        '${widget.api.wsBaseUrl}/ws/merchants/${widget.shop.id}?token=${widget.api.token}');
    try {
      _ws = WebSocketChannel.connect(uri);
    } catch (_) {
      _scheduleReconnect();
      return;
    }
    final ws = _ws!;
    ws.ready.then((_) {
      if (!mounted || !identical(_ws, ws)) return;
      _reconnect.onConnected();
      _wsConnected = true;
    }, onError: (_) => _scheduleReconnect(ws));
    _wsPing = Timer.periodic(
        const Duration(seconds: 30), (_) => _ws?.sink.add('ping'));
    ws.stream.listen(
      (message) {
        if (!_wsConnected) _wsConnected = true;
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
      // 连不上时这两个**都会**触发,判重交给 ReconnectPolicy。
      // 带上 ws:上一条连接的收尾事件不该把新连接顶掉
      onError: (_) => _scheduleReconnect(ws),
      onDone: () => _scheduleReconnect(ws),
    );
  }

  /// [from] 是发出这次断线通知的连接;不是当前那条就忽略
  void _scheduleReconnect([WebSocketChannel? from]) {
    if (!mounted) return;
    if (from != null && !identical(_ws, from)) return;
    _wsPing?.cancel();
    _wsConnected = false;
    final delay = _reconnect.schedule();
    if (delay == null) return; // 这次断线已经排过了
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, () {
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

  /// 状态色沿用与外卖侧同一套语义:待处理=clay(要你动手)、
  /// 进行中=hold、已入住=earn、终态=弱化。红色只留给报错。
  Color _statusColor(String status) {
    final sz = Theme.of(context).sz;
    return switch (status) {
      'paid' => sz.clay,
      'confirmed' => sz.hold,
      'checked_in' || 'completed' => sz.earn,
      _ => sz.inkMuted,
    };
  }

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
                padding: const EdgeInsets.only(right: 7),
                child: SzChip(
                  value == 'pending' && _pendingCount > 0
                      ? '$label($_pendingCount)'
                      : label,
                  selected: _state == value,
                  onTap: () {
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
                  SizedBox(height: 40),
                  SzEmpty(art: BrandArt.receipt, text: '这一栏没有订单'),
                ])
              : ListView.builder(
                  itemCount: _orders.length,
                  itemBuilder: (context, i) => _orderCard(_orders[i]),
                ),
        ),
      ),
    ]);
  }

  /// 住宿订单卡:与外卖侧订单卡同一套语言——待处理的左侧一条 clay,
  /// 状态走 SzChip,金额走 szMoney,到手的钱 earn、佣金 hold。
  Widget _orderCard(StayOrder order) {
    final sz = Theme.of(context).sz;
    final needsAction = order.status == 'paid';
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      decoration: BoxDecoration(
        color: sz.surface,
        borderRadius: BorderRadius.circular(kRadiusMd),
        border: Border.all(color: sz.line),
      ),
      foregroundDecoration: needsAction
          ? BoxDecoration(
              borderRadius: BorderRadius.circular(kRadiusMd),
              border: Border(left: BorderSide(color: sz.clay, width: 3)),
            )
          : null,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 11, 12, 11),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
                child: Text('${order.roomTypeName} × ${order.roomsQty} 间',
                    style: TextStyle(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w600,
                        color: sz.ink))),
            const SizedBox(width: 8),
            SzChip(order.statusLabel,
                color: _statusColor(order.status), dense: true),
          ]),
          const SizedBox(height: 6),
          Row(children: [
            Text(yuan(order.totalCents),
                style: szMoney(
                    fontSize: 14, fontWeight: FontWeight.w600, color: sz.ink)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                  '${order.checkinDate} → ${order.checkoutDate} · ${order.nights} 晚',
                  style: TextStyle(fontSize: 12, color: sz.inkMuted)),
            ),
          ]),
          const SizedBox(height: 3),
          Text('入住人 ${order.guestName} · ${order.guestPhone}',
              style: TextStyle(fontSize: 12, color: sz.inkMuted)),
          if (order.arrivalNote.isNotEmpty)
            Text('备注:${order.arrivalNote}',
                style: TextStyle(fontSize: 12, color: sz.inkMuted)),
          Text(order.cancelPolicyText,
              style: TextStyle(fontSize: 11, color: sz.inkMuted)),
          if (order.status == 'completed')
            Padding(
              padding: const EdgeInsets.only(top: 5),
              child: Text.rich(
                TextSpan(children: [
                  const TextSpan(text: '实收 '),
                  TextSpan(
                      text: yuan(order.netCents),
                      style: szMoney(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: sz.earn)),
                  const TextSpan(text: ' · 佣金 '),
                  TextSpan(
                      text: yuan(order.feeCents),
                      style: szMoney(fontSize: 12.5, color: sz.hold)),
                ]),
                style: TextStyle(fontSize: 12, color: sz.inkMuted),
              ),
            ),
          if (order.refundCents > 0)
            Text('已退款 ${yuan(order.refundCents)}(${order.refundNote})',
                style: TextStyle(fontSize: 12, color: sz.danger)),
          if (order.status == 'noshow')
            Text('系统已按政策处理:扣首晚 ${yuan(order.netCents)} 归你,其余退客人',
                style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
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
