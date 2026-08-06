import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 骑手消息中心。
///
/// ## 为什么骑手比商家更需要这一页
///
/// 商家至少还有个后台天天开着。骑手在马路上,推送弹出来那一下没看到就
/// **永远找不回来了** —— 而发给他的偏偏是最要紧的几类:申诉结果、
/// 提现到账、极端天气预警、装备发放。此前这些只走推送,没有归档的地方。
///
/// ## 订单类不进这里
///
/// 订单页本身就是它们的家。不排除的话,一个跑通宵的骑手打开消息中心
/// 第一屏全是"有新单可抢",真正要看的那条被压到第三页。
class RiderMessagesPage extends StatefulWidget {
  const RiderMessagesPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderMessagesPage> createState() => _RiderMessagesPageState();
}

class _RiderMessagesPageState extends State<RiderMessagesPage> {
  static const _tabs = <(String?, String)>[
    (null, '全部'),
    ('money', '钱'),
    ('safety', '安全'),
    ('appeal', '申诉'),
    ('system', '其他'),
  ];

  String? _category;
  List<Map<String, dynamic>> _messages = const [];
  List<Map<String, dynamic>> _announcements = const [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load(markRead: true);
  }

  Future<void> _load({bool markRead = false}) async {
    setState(() => _loading = true);
    try {
      final r = await widget.api.riderMessages(category: _category);
      if (!mounted) return;
      setState(() {
        _messages =
            ((r['messages'] as List?) ?? const []).cast<Map<String, dynamic>>();
        _announcements = ((r['announcements'] as List?) ?? const [])
            .cast<Map<String, dynamic>>();
        _loading = false;
      });
      // 打开即已读:进到这一页本身就是"我看过了"。
      // 失败不提示 —— 未读数下次自己对齐,为这个弹一条错误毫无意义
      if (markRead) {
        try {
          await widget.api.markRiderMessagesRead();
        } catch (_) {}
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('消息'),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(46),
          child: SizedBox(
            height: 46,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 8),
              children: [
                for (final (value, label) in _tabs)
                  Padding(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 4, vertical: 6),
                    child: ChoiceChip(
                      label: Text(label),
                      selected: _category == value,
                      onSelected: (_) {
                        setState(() => _category = value);
                        _load();
                      },
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  for (final a in _announcements)
                    Card(
                      color: scheme.secondaryContainer,
                      child: ListTile(
                        leading: const Icon(Icons.campaign_outlined),
                        title: Text('${a['title']}',
                            style: const TextStyle(
                                fontWeight: FontWeight.w600)),
                        subtitle: Text('${a['content']}'),
                      ),
                    ),
                  if (_messages.isEmpty)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 64),
                      child: Center(child: Text('这里还没有消息')),
                    ),
                  for (final m in _messages) _tile(m),
                ],
              ),
            ),
    );
  }

  Widget _tile(Map<String, dynamic> m) {
    final scheme = Theme.of(context).colorScheme;
    final (icon, color) = switch ('${m['kind']}') {
      'money' => (Icons.account_balance_wallet_outlined, Colors.green),
      'safety' => (Icons.health_and_safety_outlined, Colors.orange),
      'appeal' => (Icons.record_voice_over_outlined, scheme.primary),
      _ => (Icons.notifications_none, scheme.onSurfaceVariant),
    };
    final at = DateTime.tryParse('${m['created_at']}')?.toLocal();
    return Card(
      child: ListTile(
        leading: Icon(icon, color: color),
        title: Text('${m['title']}',
            style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('${m['content']}'),
            if (at != null)
              Text(
                  '${at.month}/${at.day} '
                  '${at.hour.toString().padLeft(2, '0')}:'
                  '${at.minute.toString().padLeft(2, '0')}',
                  style: TextStyle(
                      fontSize: 11, color: scheme.onSurfaceVariant)),
          ],
        ),
      ),
    );
  }
}
