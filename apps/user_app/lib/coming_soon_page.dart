import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

/// 未上线业务的落地页:不是"敬请期待"四个字,而是把这个行业的问题
/// 和我们的姿态讲清楚——占位本身就是一份公开承诺。
class ComingSoonPage extends StatefulWidget {
  const ComingSoonPage({
    super.key,
    required this.name,
    required this.icon,
    required this.blood,
    required this.promise,
  });

  final String name;
  final IconData icon;

  /// 这个行业现在的吸血现状(一句)
  final String blood;

  /// 我们的姿态承诺(一句)
  final String promise;

  @override
  State<ComingSoonPage> createState() => _ComingSoonPageState();
}

class _ComingSoonPageState extends State<ComingSoonPage> {
  bool _subscribed = false;

  String get _prefKey => 'notify_${widget.name}';

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((prefs) {
      if (mounted) {
        setState(() => _subscribed = prefs.getBool(_prefKey) ?? false);
      }
    });
  }

  Future<void> _subscribe() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_prefKey, true);
    if (!mounted) return;
    setState(() => _subscribed = true);
    ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('好的,${widget.name}上线会第一时间告诉你')));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(widget.name)),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              PopIn(
                child: Container(
                  width: 88,
                  height: 88,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    color: theme.colorScheme.primary.withValues(alpha: 0.10),
                    shape: BoxShape.circle,
                  ),
                  child:
                      Icon(widget.icon, size: 40, color: theme.colorScheme.primary),
                ),
              ),
              const SizedBox(height: 20),
              Text('这个行业现在的样子',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.outline)),
              const SizedBox(height: 4),
              Text(widget.blood,
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodyLarge?.copyWith(height: 1.6)),
              const SizedBox(height: 20),
              Text('超级赞的做法',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.outline)),
              const SizedBox(height: 4),
              Text(widget.promise,
                  textAlign: TextAlign.center,
                  style: theme.textTheme.titleLarge?.copyWith(
                      fontWeight: FontWeight.bold,
                      color: theme.colorScheme.primary,
                      height: 1.5)),
              const SizedBox(height: 8),
              Text('和外卖一样:低抽成、账目透明、规则开源',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.outline)),
              const SizedBox(height: 28),
              FilledButton.icon(
                icon: Icon(_subscribed
                    ? Icons.check
                    : Icons.notifications_active_outlined),
                label: Text(_subscribed ? '已登记,上线第一时间通知你' : '上线时告诉我'),
                onPressed: _subscribed ? null : _subscribe,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
