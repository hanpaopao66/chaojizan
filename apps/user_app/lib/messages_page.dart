import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'session.dart';

/// 消息中心:平台公告 + 订单状态通知(近 30 天订单的状态流水)。
/// 未读逻辑:本地记住看过的最新公告 id,有更新时首页铃铛带红点。
class MessageCenterPage extends StatefulWidget {
  const MessageCenterPage({super.key, required this.api});

  final ApiClient api;

  /// 首页铃铛红点:最新公告 id 比本地记录的新 → true
  static Future<bool> hasUnread(ApiClient api) async {
    try {
      final list = await api.announcements('user');
      if (list.isEmpty) return false;
      final prefs = await SharedPreferences.getInstance();
      return list.first.id > (prefs.getInt(_kSeenKey) ?? 0);
    } catch (_) {
      return false;
    }
  }

  static const _kSeenKey = 'msg_seen_announcement_id';

  @override
  State<MessageCenterPage> createState() => _MessageCenterPageState();
}

class _MessageCenterPageState extends State<MessageCenterPage> {
  int _segment = 0;
  List<PlatformAnnouncement>? _announcements;
  List<Order>? _orders;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await widget.api.announcements('user');
      if (mounted) setState(() => _announcements = list);
      // 打开即视为已读最新公告
      if (list.isNotEmpty) {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setInt(MessageCenterPage._kSeenKey, list.first.id);
      }
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    }
    if (widget.api.isLoggedIn) {
      try {
        final orders = await widget.api.myOrders();
        final cutoff = DateTime.now().subtract(const Duration(days: 30));
        if (mounted) {
          setState(() => _orders = orders
              .where((o) =>
                  (DateTime.tryParse(o.createdAt)?.isAfter(cutoff)) ?? false)
              .toList());
        }
      } catch (_) {}
    }
  }

  Widget _announcementList() {
    final list = _announcements;
    if (_error != null && list == null) return Center(child: Text(_error!));
    if (list == null) return const Center(child: CircularProgressIndicator());
    if (list.isEmpty) {
      return const EmptyState(
          icon: Icons.campaign_outlined, text: '暂无平台公告');
    }
    return ListView.separated(
      padding: const EdgeInsets.all(12),
      itemCount: list.length,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (context, i) {
        final a = list[i];
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Icon(Icons.campaign_outlined,
                    size: 18, color: Theme.of(context).colorScheme.primary),
                const SizedBox(width: 6),
                Expanded(
                    child: Text(a.title,
                        style: const TextStyle(fontWeight: FontWeight.bold))),
              ]),
              const SizedBox(height: 6),
              Text(a.content, style: const TextStyle(height: 1.6)),
            ]),
          ),
        );
      },
    );
  }

  Widget _orderNotices() {
    if (!widget.api.isLoggedIn) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('登录后查看订单通知'),
          const SizedBox(height: 12),
          FilledButton(
              onPressed: () async {
                if (await ensureLoggedIn(context) && mounted) _load();
              },
              child: const Text('登录 / 注册')),
        ]),
      );
    }
    final orders = _orders;
    if (orders == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (orders.isEmpty) {
      return const EmptyState(
          icon: Icons.notifications_none, text: '近 30 天没有订单通知');
    }
    return ListView.separated(
      padding: const EdgeInsets.all(12),
      itemCount: orders.length,
      separatorBuilder: (_, __) => const Divider(height: 1),
      itemBuilder: (context, i) {
        final o = orders[i];
        final t = DateTime.tryParse(o.createdAt)?.toLocal();
        return ListTile(
          leading: const Icon(Icons.receipt_long_outlined),
          title: Text('订单 ${o.orderNo.length > 12 ? o.orderNo.substring(0, 12) : o.orderNo}… ${o.status.label}'),
          subtitle: Text(t == null
              ? o.merchantName
              : '${o.merchantName} · ${t.month}/${t.day} '
                  '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}'),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: const Text('消息中心')),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          child: SegmentedButton<int>(
            segments: const [
              ButtonSegment(value: 0, label: Text('平台公告')),
              ButtonSegment(value: 1, label: Text('订单通知')),
            ],
            selected: {_segment},
            onSelectionChanged: (s) => setState(() => _segment = s.first),
          ),
        ),
        Expanded(child: _segment == 0 ? _announcementList() : _orderNotices()),
      ]),
    );
  }
}
