import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 平台优惠券包:可用在前;结算页会自动带出可用券。
class CouponsPage extends StatefulWidget {
  const CouponsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<CouponsPage> createState() => _CouponsPageState();
}

class _CouponsPageState extends State<CouponsPage> {
  List<dynamic>? _coupons;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await widget.api.myCoupons();
      if (mounted) setState(() => _coupons = list);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final list = _coupons;
    return Scaffold(
      appBar: AppBar(title: const Text('优惠券')),
      body: list == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: list.isEmpty
                  ? ListView(children: const [
                      Padding(
                        padding: EdgeInsets.all(48),
                        child: Center(child: Text('还没有券;超时赔付、新客活动都会发到这里')),
                      ),
                    ])
                  : ListView.builder(
                      padding: const EdgeInsets.all(12),
                      itemCount: list.length,
                      itemBuilder: (context, i) {
                        final c = list[i] as Map<String, dynamic>;
                        final usable = c['usable'] == true;
                        final expires = DateTime.tryParse(
                            '${c['expires_at']}')?.toLocal();
                        return Card(
                          margin: const EdgeInsets.only(bottom: 10),
                          child: ListTile(
                            leading: Text(
                              yuan(c['amount_cents'] as int),
                              style: TextStyle(
                                  fontSize: 18,
                                  fontWeight: FontWeight.w900,
                                  color: usable ? kMoneyGreen : Colors.grey),
                            ),
                            title: Text(
                                (c['min_spend_cents'] as int) > 0
                                    ? '满 ${yuan(c['min_spend_cents'] as int)} 可用'
                                    : '无门槛',
                                style: TextStyle(
                                    color: usable ? null : Colors.grey)),
                            subtitle: Text(
                                '${c['note']}\n'
                                '${expires == null ? '' : '有效期至 ${expires.month}/${expires.day}'}',
                                style: theme.textTheme.bodySmall),
                            trailing: Text(
                                usable
                                    ? '可用'
                                    : (c['used'] == true ? '已使用' : '已过期'),
                                style: TextStyle(
                                    color: usable
                                        ? kMoneyGreen
                                        : Colors.grey,
                                    fontWeight: FontWeight.w700)),
                          ),
                        );
                      },
                    ),
            ),
    );
  }
}
