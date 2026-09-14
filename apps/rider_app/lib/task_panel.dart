import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'hall_widgets.dart';

/// 一张任务卡上的一个动作。[primary] 只有一个,其余进卡底那一排小字按钮。
@immutable
class TaskAction {
  const TaskAction(this.label, this.onTap, {this.primary = false, this.danger = false});

  final String label;
  final VoidCallback? onTap;
  final bool primary;
  final bool danger;
}

/// 进行中(设计稿 5e):上半地图,下半当前这一单的任务卡;多单左右滑切换。
///
/// 地图用 shared 的 DeliveryMapView(腾讯地图,没配 key 时是品牌网格示意)。
/// 稿子上「下一步:学府街右转」那种逐路口提示我们没有 —— 路线规划只给距离,
/// 导航交给外部地图 App。所以这一格写的是**下一站去哪、多远**,点它唤起导航。
///
/// 稿子上的「取餐码 A17」也没有照做:骑手取餐靠输小票单号后 4 位核验,
/// 把号码直接摆在骑手屏幕上,这道防拿错单的核验就形同虚设了。
class TaskPanel extends StatefulWidget {
  const TaskPanel({
    super.key,
    required this.orders,
    required this.riderPosition,
    required this.actionsFor,
    required this.alertsFor,
    required this.unread,
    required this.onChat,
    required this.onCall,
    required this.onSos,
    required this.onNavigate,
    required this.onGoHall,
    required this.onRefresh,
    this.header,
    this.api,
  });

  final List<Order> orders;
  final ValueNotifier<({double lat, double lng})?> riderPosition;
  final List<TaskAction> Function(Order order) actionsFor;
  final List<({String text, Color color})> Function(Order order) alertsFor;

  /// 单号 → 顾客发来的未读消息数
  final Map<String, int> unread;
  final void Function(Order order) onChat;
  final void Function(Order order) onCall;
  final VoidCallback onSos;
  final void Function(Order order) onNavigate;
  final VoidCallback onGoHall;
  final Future<void> Function() onRefresh;

  /// 地图上方的一条(刷新失败提示、同店批量条),可空
  final Widget? header;

  /// 点开顾客信用分小签时拉公式说明用;为空时小签不可点
  final ApiClient? api;

  @override
  State<TaskPanel> createState() => _TaskPanelState();
}

class _TaskPanelState extends State<TaskPanel> {
  int _index = 0;

  Order? get _current => widget.orders.isEmpty
      ? null
      : widget.orders[_index.clamp(0, widget.orders.length - 1)];

  void _go(int delta) {
    final n = widget.orders.length;
    if (n < 2) return;
    setState(() => _index = (_index + delta) % n < 0
        ? n - 1
        : (_index + delta) % n);
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final order = _current;
    if (order == null) {
      return RefreshIndicator(
        onRefresh: widget.onRefresh,
        child: ListView(children: [
          if (widget.header != null) widget.header!,
          const SizedBox(height: 120),
          Center(
            child: Text('没有进行中的配送',
                style: TextStyle(fontSize: kFontBodyLg, color: sz.inkMuted)),
          ),
          const SizedBox(height: 12),
          Center(
            child: OutlinedButton(
                onPressed: widget.onGoHall, child: const Text('去大厅看看')),
          ),
        ]),
      );
    }
    return LayoutBuilder(builder: (context, box) {
      return Column(children: [
        if (widget.header != null) widget.header!,
        Expanded(child: _mapArea(context, order)),
        ConstrainedBox(
          // 卡片最多占六成高:再高地图就只剩一条缝,等于没有
          constraints: BoxConstraints(maxHeight: box.maxHeight * 0.62),
          child: GestureDetector(
            // 多单左右滑切换(稿子:「多单时横滑切换」)
            onHorizontalDragEnd: (d) {
              final v = d.primaryVelocity ?? 0;
              if (v.abs() < 200) return;
              _go(v < 0 ? 1 : -1);
            },
            child: _card(context, order),
          ),
        ),
      ]);
    });
  }

  Widget _mapArea(BuildContext context, Order order) {
    final sz = Theme.of(context).sz;
    final accent = Theme.of(context).colorScheme.primary;
    final picked = order.status == OrderStatus.pickedUp;
    return Stack(children: [
      Positioned.fill(
        child: ValueListenableBuilder(
          valueListenable: widget.riderPosition,
          builder: (context, rider, _) => DeliveryMapView(points: [
            if (order.merchantLat != null && order.merchantLng != null)
              MapPoint(
                  lat: order.merchantLat!,
                  lng: order.merchantLng!,
                  label: order.isErrand ? '取件' : '取餐 ${order.merchantName}',
                  icon: Icons.storefront,
                  color: sz.hold),
            if (rider != null)
              MapPoint(
                  lat: rider.lat,
                  lng: rider.lng,
                  label: '我',
                  icon: Icons.sports_motorsports,
                  color: sz.clay),
            MapPoint(
                lat: order.lat,
                lng: order.lng,
                label: '送达',
                icon: Icons.home,
                color: sz.earn),
          ]),
        ),
      ),
      Positioned(
        left: kPagePad,
        right: kPagePad,
        top: MediaQuery.paddingOf(context).top + 8,
        child: Row(children: [
          Expanded(
            child: _floatBox(
              context,
              onTap: () => widget.onNavigate(order),
              child: Row(children: [
                Icon(Icons.navigation_outlined, size: 18, color: accent),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                      _nextStep(order, picked),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontBody, color: sz.ink)),
                ),
              ]),
            ),
          ),
          if (order.privacyPhone.isNotEmpty) ...[
            const SizedBox(width: 8),
            _floatBox(context,
                square: true,
                onTap: () => widget.onCall(order),
                child: Icon(Icons.call, size: 20, color: sz.ink)),
          ],
          const SizedBox(width: 8),
          // SOS 在这一页也要有:骑手出事的时候多半就在这一页上。
          // 长按才触发(和大厅左上角同一个口径),防误触
          Tooltip(
            message: '长按 3 秒紧急求助',
            child: GestureDetector(
              onLongPress: widget.onSos,
              child: _floatBox(context,
                  square: true,
                  child: Icon(Icons.sos, size: 20, color: sz.danger)),
            ),
          ),
        ]),
      ),
    ]);
  }

  String _nextStep(Order order, bool picked) {
    final fix = widget.riderPosition.value;
    String? dist(double lat, double lng) => fix == null
        ? null
        : distanceLabel(distanceMeters(fix.lat, fix.lng, lat, lng));
    if (!picked && order.merchantLat != null && order.merchantLng != null) {
      final d = dist(order.merchantLat!, order.merchantLng!);
      final name = order.isErrand ? '取件点' : order.merchantName;
      return '下一步:去$name${d == null ? '' : ' · $d'}';
    }
    final d = dist(order.lat, order.lng);
    return '下一步:去送达${d == null ? '' : ' · $d'}';
  }

  Widget _floatBox(BuildContext context,
      {required Widget child, VoidCallback? onTap, bool square = false}) {
    final sz = Theme.of(context).sz;
    return Material(
      color: sz.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        side: BorderSide(color: sz.line),
      ),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: SizedBox(
          width: square ? 44 : null,
          height: 44,
          child: square
              ? Center(child: child)
              : Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 14),
                  child: child,
                ),
        ),
      ),
    );
  }

  Widget _card(BuildContext context, Order order) {
    final sz = Theme.of(context).sz;
    final accent = Theme.of(context).colorScheme.primary;
    final n = widget.orders.length;
    final i = _index.clamp(0, n - 1);
    final next = n > 1 ? widget.orders[(i + 1) % n] : null;
    final actions = widget.actionsFor(order);
    final primary = actions.where((a) => a.primary).firstOrNull;
    final others = actions.where((a) => !a.primary).toList();
    final picked = order.status == OrderStatus.pickedUp;
    final step = picked ? 2 : 1;
    final unread = widget.unread[order.orderNo] ?? 0;
    final fee = HallOrderCard.riderTakeCents(order);
    final dropTo = [
      order.address,
      if (order.tripM != null) distanceLabelShort(order.tripM!.toDouble()),
    ].join(' · ');
    final pickupSub = [
      if (order.status == OrderStatus.ready)
        '已出餐'
      else if (order.estWaitMinutes != null && order.estWaitMinutes! > 0)
        () {
          final t = DateTime.now()
              .add(Duration(minutes: order.estWaitMinutes!.round()));
          return '预计出餐 ${t.hour.toString().padLeft(2, '0')}:'
              '${t.minute.toString().padLeft(2, '0')}';
        }(),
      if (!order.isErrand) '核对小票单号后 4 位取餐',
      if (order.isErrand && order.errandNote.isNotEmpty) order.errandNote,
      if (order.items.isNotEmpty && !order.isErrand) order.summary,
    ].join(' · ');
    final dropSub = [
      if (order.etaClock != null) '用户参考送达 ${order.etaClock}',
      if (order.remark.isNotEmpty) order.remark,
      if (!order.toDoor) '送到楼下',
    ].join(' · ');

    return Material(
      color: sz.surface,
      borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(kPagePad, 16, kPagePad, 16),
        child: SzDirectionalSwitcher(
          index: i,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(children: [
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
                  decoration: BoxDecoration(
                      color: sz.ink, borderRadius: BorderRadius.circular(999)),
                  child: Text('${i + 1} / $n',
                      style: szFigure(
                          fontSize: kFontNote,
                          fontWeight: FontWeight.w600,
                          color: sz.paper)),
                ),
                const SizedBox(width: 8),
                Flexible(
                  child: Text(
                      '${order.isErrand ? "帮我送" : order.merchantName} → '
                      '${_short(order.address)}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ),
                const Spacer(),
                if (next != null)
                  InkWell(
                    onTap: () => _go(1),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 6),
                      child: Text(
                          '下一单 · ${next.isErrand ? "帮我送" : next.merchantName}',
                          style: TextStyle(
                              fontSize: kFontNote, color: sz.inkMuted)),
                    ),
                  ),
              ]),
              const SizedBox(height: 12),
              SzProgressRail(
                labels: [
                  '已抢单',
                  order.isErrand ? '去取件' : '去取餐',
                  '配送中',
                  '送达'
                ],
                step: step,
                dots: false,
              ),
              const SizedBox(height: 12),
              _block(
                context,
                pickup: true,
                title: order.isErrand
                    ? '取件 · ${order.merchantAddress}'
                    : '${order.merchantName} · ${order.merchantAddress}',
                sub: pickupSub,
                current: !picked,
              ),
              const SizedBox(height: 10),
              _block(context,
                  pickup: false, title: dropTo, sub: dropSub, current: picked),
              // 顾客信用分:**接到这一单之后**才有,抢单大厅里没有(服务端只给这一单的骑手带)。
              // 只有分数和等级,看不到是因为什么扣的。派单和排序里都没有它;点开是公式说明
              if (customerCreditVisible(order))
                Padding(
                  padding: const EdgeInsets.only(left: 20, top: 6),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: CustomerCreditChip(
                        order: order, api: widget.api, viewer: '骑手'),
                  ),
                ),
              for (final a in widget.alertsFor(order)) ...[
                const SizedBox(height: 8),
                Text(a.text,
                    style: TextStyle(
                        fontSize: kFontNote,
                        fontWeight: FontWeight.w600,
                        height: 1.4,
                        color: a.color)),
              ],
              const SizedBox(height: 12),
              Material(
                color: sz.paper,
                borderRadius: BorderRadius.circular(10),
                child: InkWell(
                  borderRadius: BorderRadius.circular(10),
                  onTap: () => widget.onChat(order),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 10),
                    child: Row(children: [
                      Text(szYuanText(fee),
                          style: szMoney(fontSize: kFontTitle, color: sz.earn)),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                            // 入账时点是「订单完成」(顾客确认或送达 24 小时后自动),
                            // 不是按下「已送达」那一刻 —— 稿子上写的「送达即入账」不对
                            order.isErrand
                                ? '跑腿费扣 2% · 订单完成后入账'
                                : '配送费全额 · 订单完成后入账',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                                fontSize: kFontNote, color: sz.inkMuted)),
                      ),
                      Icon(Icons.chat_bubble_outline,
                          size: 15, color: unread > 0 ? sz.clay : sz.inkMuted),
                      const SizedBox(width: 4),
                      // 一单一个群:未读里可能是顾客也可能是商家,不写「用户」
                      Text(unread > 0 ? '新消息 $unread 条' : '订单群',
                          style: TextStyle(
                              fontSize: kFontNote,
                              color: unread > 0 ? sz.clay : sz.inkMuted)),
                    ]),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              if (primary != null)
                SzPressScale(
                  enabled: primary.onTap != null,
                  child: FilledButton(
                    style: FilledButton.styleFrom(
                      backgroundColor: primary.danger ? sz.danger : accent,
                      minimumSize: const Size.fromHeight(50),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10)),
                      textStyle: const TextStyle(
                          fontSize: kFontTitle, fontWeight: FontWeight.w600),
                    ),
                    onPressed: primary.onTap,
                    child: Text(primary.label),
                  ),
                ),
              if (others.isNotEmpty) ...[
                const SizedBox(height: 6),
                Wrap(
                  alignment: WrapAlignment.center,
                  children: [
                    for (final a in others)
                      TextButton(
                        style: TextButton.styleFrom(
                          foregroundColor: a.danger ? sz.danger : sz.inkMuted,
                          minimumSize: const Size(48, 44),
                          padding: const EdgeInsets.symmetric(horizontal: 10),
                          textStyle: const TextStyle(fontSize: kFontBody),
                        ),
                        onPressed: a.onTap,
                        child: Text(a.label),
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _block(BuildContext context,
      {required bool pickup,
      required String title,
      required String sub,
      required bool current}) {
    final sz = Theme.of(context).sz;
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.only(top: 6),
        child: SzPointDot(pickup: pickup),
      ),
      const SizedBox(width: 10),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                  fontSize: kFontBodyLg,
                  fontWeight: FontWeight.w600,
                  color: current ? sz.ink : sz.inkMuted)),
          if (sub.isNotEmpty)
            Text(sub,
                style: TextStyle(
                    fontSize: kFontNote, height: 1.45, color: sz.inkMuted)),
        ]),
      ),
    ]);
  }

  /// 「高新路 88 号 3 栋 2 单元」→ 前 8 个字,标题行放得下
  String _short(String s) => s.length <= 8 ? s : '${s.substring(0, 8)}…';
}
