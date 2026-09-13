import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../store.dart';
import '../ui/format.dart';

/// 这个会话里我的定时消息:可以立即发送、删除。到点由服务端的清扫任务发出。
class ScheduledPage extends StatefulWidget {
  const ScheduledPage({super.key, required this.chatId});

  final int chatId;

  @override
  State<ScheduledPage> createState() => _ScheduledPageState();
}

class _ScheduledPageState extends State<ScheduledPage> {
  List<Map<String, dynamic>>? _items;
  Object? _error;

  ChatStore get store => ChatStore.instance;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await store.api.scheduled(widget.chatId);
      if (mounted) setState(() => _items = r);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _act(Future<void> Function() f) async {
    try {
      await f();
      await _load();
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('定时消息')),
      body: items == null
          ? (_error != null ? SzError(error: _error, onRetry: _load) : const Center(child: CircularProgressIndicator()))
          : items.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Text('没有定时消息。\n在输入框里长按发送键,选「定时发送」。',
                        textAlign: TextAlign.center, style: TextStyle(color: sz.inkMuted)),
                  ),
                )
              : ListView.separated(
                  itemCount: items.length,
                  separatorBuilder: (_, __) => Divider(height: 1, color: sz.line),
                  itemBuilder: (context, i) {
                    final it = items[i];
                    final at = DateTime.tryParse('${it['send_at']}')?.toLocal();
                    final p = (it['payload'] as Map?) ?? const {};
                    final text = '${p['text'] ?? ''}';
                    final kind = '${p['kind'] ?? 'text'}';
                    return ListTile(
                      leading: const Icon(Icons.schedule_send_outlined),
                      title: Text(text.isNotEmpty ? text : '[${kindLabels[kind] ?? kind}]',
                          maxLines: 2, overflow: TextOverflow.ellipsis),
                      subtitle: Text(at == null ? '' : '${at.month}月${at.day}日 ${hm(at)} 发出'),
                      trailing: PopupMenuButton<String>(
                        onSelected: (v) => _act(() => v == 'now'
                            ? store.api.sendScheduledNow(widget.chatId, (it['id'] as num).toInt())
                            : store.api.unschedule(widget.chatId, (it['id'] as num).toInt())),
                        itemBuilder: (_) => const [
                          PopupMenuItem(value: 'now', child: Text('立即发送')),
                          PopupMenuItem(value: 'delete', child: Text('删除')),
                        ],
                      ),
                    );
                  },
                ),
    );
  }
}
