import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../session.dart';
import 'qr_login.dart';
import 'qr_scan_page.dart';

/// 设置 →「已登录的网页和电脑」:扫码登录过、还能一键登录的那几台。
///
/// 移除一台:它**下一次请求就退出登录**(那台设备的登录里带着这条记录,服务端每次都查),
/// 也不能再一键登录。要再用,重新扫码。
class LoginDevicesPage extends StatefulWidget {
  const LoginDevicesPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<LoginDevicesPage> createState() => _LoginDevicesPageState();
}

class _LoginDevicesPageState extends State<LoginDevicesPage> {
  List<Map<String, dynamic>>? _items;
  Object? _error;

  /// 多少天没用自动失效(服务端给的数,不在这里写死)
  int _idleDays = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final data = await widget.api.loginDevices();
      if (!mounted) return;
      setState(() {
        _items = (data['items'] as List? ?? const []).cast<Map<String, dynamic>>();
        _idleDays = (data['idle_days'] as num?)?.toInt() ?? 0;
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _remove(Map<String, dynamic> d) async {
    final current = d['current'] == true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => SzDialog(
        title: Text('移除「${d['device']}」?'),
        content: Text(current
            ? '这就是你现在用的这台。移除后这里马上退出登录,也不能再一键登录。'
            : '那台设备会马上退出登录,也不能再一键登录。要再用,重新扫码登录。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('再想想')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('移除')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await widget.api.removeLoginDevice((d['id'] as num).toInt());
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
      }
      return;
    }
    if (!mounted) return;
    if (current) {
      // 移除的就是这一台:这边的登录马上就失效了,不等下一次请求 401,直接退出
      await QrLoginMemory.clear();
      await widget.api.clearSession();
      authTick.value++;
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('这台设备已退出登录')));
      Navigator.of(context).popUntil((route) => route.isFirst);
      return;
    }
    await _load();
  }

  String _when(String? iso) {
    final t = DateTime.tryParse(iso ?? '')?.toLocal();
    if (t == null) return '';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${t.month} 月 ${t.day} 日 ${two(t.hour)}:${two(t.minute)}';
  }

  Widget _row(Map<String, dynamic> d) {
    final sz = Theme.of(context).sz;
    final current = d['current'] == true;
    final desktop = d['client'] == 'desktop';
    final last = _when(d['last_used_at'] as String?);
    return Padding(
      padding: const EdgeInsets.fromLTRB(kCardPad, 10, 6, 10),
      child: Row(children: [
        Icon(desktop ? Icons.desktop_windows_outlined : Icons.language_outlined,
            size: 22, color: sz.inkMuted),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(current ? '${d['device']}(这台)' : '${d['device']}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
            const SizedBox(height: 2),
            Text(
                [
                  if (last.isNotEmpty) '最近使用 $last',
                  if ('${d['ip'] ?? ''}'.isNotEmpty) 'IP ${d['ip']}',
                ].join(' · '),
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ]),
        ),
        TextButton(
          onPressed: () => _remove(d),
          child: Text('移除', style: TextStyle(color: sz.danger)),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final items = _items;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('已登录的网页和电脑')),
      body: items == null
          ? (_error != null
              ? SzError(error: _error, onRetry: _load)
              : const Center(child: CircularProgressIndicator()))
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 32),
                children: [
                  Text('用扫码登录过的超级赞网页版、电脑版。移除后,那台设备马上退出登录,也不能再一键登录。',
                      style: TextStyle(fontSize: kFontNote, height: 1.6, color: sz.inkMuted)),
                  const SizedBox(height: 12),
                  if (items.isEmpty)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 28),
                      child: Text('还没有用扫码登录过网页版或电脑版',
                          textAlign: TextAlign.center,
                          style: TextStyle(fontSize: kFontBody, color: sz.inkMuted)),
                    )
                  else
                    SzEntryGroup(children: [for (final d in items) _row(d)]),
                  if (canScanHere) ...[
                    const SizedBox(height: 16),
                    OutlinedButton.icon(
                      onPressed: () => openQrScanner(context, widget.api),
                      icon: const Icon(Icons.qr_code_scanner),
                      label: const Text('扫一扫,登录网页版或电脑版'),
                    ),
                  ],
                  if (_idleDays > 0) ...[
                    const SizedBox(height: 16),
                    Text('$_idleDays 天没用过的会自动失效,要再用就重新扫码。',
                        style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
                  ],
                ],
              ),
            ),
    );
  }
}
