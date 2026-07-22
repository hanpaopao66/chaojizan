import 'dart:async';

import 'package:flutter/material.dart';

import 'api_client.dart';
import 'brand.dart';

/// 订单内聊天页(三端共用):气泡 + 快捷语 + 输入框,3 秒轮询兜底。
/// 电话(隐私号)仍是兜底通道;终结 2 小时后只读。
class OrderChatPage extends StatefulWidget {
  const OrderChatPage({
    super.key,
    required this.api,
    required this.orderNo,
    required this.title,
    this.peer = '',
    this.quickReplies = const [],
  });

  final ApiClient api;
  final String orderNo;
  final String title;
  final String peer; // 用户端指定 rider/merchant;骑手/商家端留空
  final List<String> quickReplies;

  @override
  State<OrderChatPage> createState() => _OrderChatPageState();
}

class _OrderChatPageState extends State<OrderChatPage> {
  List<dynamic> _messages = [];
  bool _readonly = false;
  final _input = TextEditingController();
  final _scroll = ScrollController();
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r =
          await widget.api.orderMessages(widget.orderNo, peer: widget.peer);
      if (!mounted) return;
      final grew = (r['messages'] as List).length != _messages.length;
      setState(() {
        _messages = r['messages'] as List;
        _readonly = r['readonly'] == true;
      });
      if (grew && _scroll.hasClients) {
        WidgetsBinding.instance.addPostFrameCallback(
            (_) => _scroll.jumpTo(_scroll.position.maxScrollExtent));
      }
    } catch (_) {}
  }

  Future<void> _send(String content, {String kind = 'text'}) async {
    final text = content.trim();
    if (text.isEmpty) return;
    try {
      await widget.api.sendOrderMessage(widget.orderNo, text,
          to: widget.peer, kind: kind);
      _input.clear();
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: Column(children: [
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.all(12),
            itemCount: _messages.length,
            itemBuilder: (context, i) {
              final m = _messages[i] as Map<String, dynamic>;
              final mine = m['mine'] == true;
              return Align(
                alignment:
                    mine ? Alignment.centerRight : Alignment.centerLeft,
                child: Container(
                  margin: const EdgeInsets.symmetric(vertical: 3),
                  padding: const EdgeInsets.symmetric(
                      horizontal: 12, vertical: 8),
                  constraints: const BoxConstraints(maxWidth: 280),
                  decoration: BoxDecoration(
                    color: mine
                        ? kMoneyGreen.withValues(alpha: .15)
                        : theme.colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: m['kind'] == 'image'
                      ? Image.network('${m['content']}',
                          width: 180, fit: BoxFit.cover)
                      : Text('${m['content']}'),
                ),
              );
            },
          ),
        ),
        if (_readonly)
          Container(
            padding: const EdgeInsets.all(10),
            width: double.infinity,
            color: theme.colorScheme.surfaceContainerHighest,
            child: const Text('订单已结束,会话转为只读;有问题请走售后或客服',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 12)),
          )
        else ...[
          if (widget.quickReplies.isNotEmpty)
            SizedBox(
              height: 40,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                children: [
                  for (final q in widget.quickReplies)
                    Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ActionChip(
                          label: Text(q, style: const TextStyle(fontSize: 12)),
                          onPressed: () => _send(q, kind: 'quick')),
                    ),
                ],
              ),
            ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(10, 6, 10, 10),
              child: Row(children: [
                Expanded(
                  child: TextField(
                    controller: _input,
                    maxLength: 200,
                    decoration: const InputDecoration(
                      hintText: '输入消息…(紧急事直接打电话)',
                      counterText: '',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                    onSubmitted: _send,
                  ),
                ),
                const SizedBox(width: 8),
                IconButton.filled(
                    onPressed: () => _send(_input.text),
                    icon: const Icon(Icons.send)),
              ]),
            ),
          ),
        ],
      ]),
    );
  }
}

/// 各端预设快捷语
const kCustomerQuickReplies = ['放门口就行', '放前台/驿站', '到了打电话', '请尽快,谢谢'];
const kRiderQuickReplies = ['已到店等出餐', '已取餐,马上到', '到楼下了', '已放门口,注意查收'];
const kMerchantQuickReplies = ['收到,马上做', '今天有点忙,稍等', '已出餐'];
