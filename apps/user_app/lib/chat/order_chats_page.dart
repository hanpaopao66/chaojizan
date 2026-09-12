import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../main.dart' show OrderDetailPage;

/// 「消息」列表顶部的「订单消息」:进行中和刚结束的订单里,和商家、骑手的对话。
///
/// 订单聊天本身没动(三端共用的 [OrderChatPage],结单 2 小时后只读),
/// 这一页只是把入口从订单详情里**再**露一份出来 —— 底部没有订单 tab 之后,
/// 「骑手问我在哪」这种消息不能要人先进「我的」→ 订单 → 详情才看得到。
class OrderChatsPage extends StatefulWidget {
  const OrderChatsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<OrderChatsPage> createState() => _OrderChatsPageState();
}

/// 列在这一页的订单:付了款、没取消,下单在 3 天内。
///
/// 结单 2 小时后聊天只读(服务端 `_chat_age_hours`),但记录还能看 ——
/// 「骑手说放在哪了」往往是第二天才想起来要翻的
bool orderChatListed(Order o, DateTime now) {
  if (o.status == OrderStatus.cancelled) return false;
  if (o.status == OrderStatus.pendingPayment) return false;
  final at = DateTime.tryParse(o.createdAt);
  return at == null || now.difference(at) < const Duration(days: 3);
}

class _OrderChatsPageState extends State<OrderChatsPage> {
  late Future<List<(Order, int)>> _future = _load();

  Future<List<(Order, int)>> _load() async {
    final orders = await widget.api.myOrders(limit: 30);
    final now = DateTime.now();
    final open = orders.where((o) => orderChatListed(o, now)).take(20).toList();
    // 未读数一单一个请求;最多 20 单,并发发出去
    final unread = await Future.wait(open.map((o) =>
        widget.api.orderUnread(o.orderNo).catchError((Object _) => 0)));
    return [for (var i = 0; i < open.length; i++) (open[i], unread[i])];
  }

  Future<void> _open(Order o) async {
    final peer = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: const Icon(Icons.storefront_outlined),
            title: Text('和商家说句话 · ${o.merchantName}'),
            onTap: () => Navigator.pop(ctx, 'merchant'),
          ),
          if (o.riderId != null)
            ListTile(
              leading: const Icon(Icons.delivery_dining_outlined),
              title: Text(o.riderName.isEmpty ? '和骑手说句话' : '和骑手说句话 · ${o.riderName}'),
              onTap: () => Navigator.pop(ctx, 'rider'),
            ),
          ListTile(
            leading: const Icon(Icons.receipt_long_outlined),
            title: const Text('看订单详情'),
            onTap: () => Navigator.pop(ctx, 'detail'),
          ),
        ]),
      ),
    );
    if (peer == null || !mounted) return;
    if (peer == 'detail') {
      await Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => OrderDetailPage(api: widget.api, orderNo: o.orderNo)));
    } else {
      await Navigator.of(context).push(MaterialPageRoute<void>(
          builder: (_) => OrderChatPage(
              api: widget.api,
              orderNo: o.orderNo,
              title: peer == 'rider' ? '和骑手说句话' : '和商家说句话',
              peer: peer,
              quickReplies: kCustomerQuickReplies)));
    }
    if (mounted) {
      final f = _load();
      setState(() {
        _future = f;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('订单消息')),
      body: RefreshIndicator(
        onRefresh: () async {
          final f = _load();
          setState(() {
            _future = f;
          });
          await f.then((_) {}, onError: (_) {});
        },
        child: FutureBuilder<List<(Order, int)>>(
          future: _future,
          builder: (context, snap) {
            if (snap.hasError) {
              return ListView(children: [
                SzError(
                    error: snap.error,
                    onRetry: () => setState(() {
                          _future = _load();
                        })),
              ]);
            }
            final rows = snap.data;
            if (rows == null) {
              return const Center(child: CircularProgressIndicator());
            }
            if (rows.isEmpty) {
              return ListView(children: const [
                Padding(
                  padding: EdgeInsets.only(top: 80),
                  child: SzEmpty(text: '没有进行中的订单\n下单后和商家、骑手的对话会出现在这里'),
                ),
              ]);
            }
            return ListView.separated(
              itemCount: rows.length,
              separatorBuilder: (_, __) =>
                  Divider(height: 1, indent: 72, color: sz.line),
              itemBuilder: (context, i) {
                final (o, unread) = rows[i];
                return ListTile(
                  leading: CircleAvatar(
                    backgroundColor: sz.surfaceAlt,
                    child: Icon(Icons.receipt_long_outlined, color: sz.inkMuted),
                  ),
                  title: Text(o.merchantName,
                      maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: Text('${o.status.label} · 订单尾号 ${o.orderNo.substring(o.orderNo.length > 6 ? o.orderNo.length - 6 : 0)}',
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  trailing: unread > 0
                      ? Badge(label: Text('$unread'))
                      : Icon(Icons.chevron_right, color: sz.inkFaint),
                  onTap: () => _open(o),
                );
              },
            );
          },
        ),
      ),
    );
  }
}
