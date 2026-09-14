import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 手机上「在 Chrome · macOS 上登录超级赞?」这一页。扫码登录和一键登录共用。
///
/// ## 这一页要让人认出「这是不是我那台电脑」
///
/// 最常见的钓鱼是扫别人伪造的码:骗子在他自己电脑上打开网页版,把二维码截图发给你
/// (「扫码领券」),你一扫一点,他那台电脑就登上了你的账号。手机上能帮你认出来的只有这三样:
/// **哪台设备、哪个 IP、什么时候发起的**,所以一样不少地摆出来,并写明「不是你本人在电脑前,请点取消」。
///
/// 不选就退出(返回键、手势)按取消处理 —— 电脑那边立刻知道,不用干等到过期。
class QrConfirmPage extends StatefulWidget {
  const QrConfirmPage({super.key, required this.api, required this.request});

  final ApiClient api;

  /// 服务端给的请求信息(扫码的回包、或者待确认列表里的一条):
  /// sid、mode、client、device、ip(打过码)、same_network、created_at、expires_at
  final Map<String, dynamic> request;

  @override
  State<QrConfirmPage> createState() => _QrConfirmPageState();
}

class _QrConfirmPageState extends State<QrConfirmPage> {
  bool _busy = false;

  /// 点过「登录」或「取消」了(离开页面时就不用再替他取消)
  bool _decided = false;

  /// 登录不了的原因(过期、被取消……)。有了它,页面只剩一个「知道了」
  String _failed = '';

  String get _sid => '${widget.request['sid']}';

  @override
  void dispose() {
    if (!_decided) {
      // 没选就走了:当作取消。失败了也没关系,会话 120 秒自己过期
      unawaited(widget.api.cancelQrLogin(_sid).catchError((_) {}));
    }
    super.dispose();
  }

  Future<void> _confirm() async {
    setState(() => _busy = true);
    try {
      await widget.api.confirmQrLogin(_sid);
      _decided = true;
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已登录。可以在「设置 → 已登录的网页和电脑」里随时移除')));
      Navigator.of(context).pop(true);
    } on ApiException catch (e) {
      _decided = true;
      if (mounted) {
        setState(() {
          _busy = false;
          _failed = e.message;
        });
      }
    }
  }

  Future<void> _cancel() async {
    _decided = true;
    setState(() => _busy = true);
    try {
      await widget.api.cancelQrLogin(_sid);
    } catch (_) {
      // 取消失败也照样离开:会话 120 秒自己过期,电脑那边登不进去
    }
    if (mounted) Navigator.of(context).pop(false);
  }

  String _clock(String iso) {
    final t = DateTime.tryParse(iso)?.toLocal();
    if (t == null) return '';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${t.month} 月 ${t.day} 日 ${two(t.hour)}:${two(t.minute)}';
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final r = widget.request;
    final device = '${r['device'] ?? ''}'.isEmpty ? '一台设备' : '${r['device']}';
    final desktop = r['client'] == 'desktop';
    final sameNetwork = r['same_network'] == true;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('登录确认')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(kPagePad, 28, kPagePad, 24),
          children: [
            Icon(desktop ? Icons.desktop_windows_outlined : Icons.language_outlined,
                size: 56, color: sz.inkMuted),
            const SizedBox(height: 16),
            Text('在 $device 上登录超级赞?',
                textAlign: TextAlign.center,
                style: TextStyle(
                    fontSize: kFontLead, fontWeight: FontWeight.w600, color: sz.ink)),
            if (r['mode'] == 'oneclick') ...[
              const SizedBox(height: 6),
              Text('这台设备之前扫码登录过你的账号,现在请求一键登录',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ],
            const SizedBox(height: 20),
            SzEntryGroup(children: [
              SzEntryTile(icon: Icons.devices_outlined, title: '设备', value: device),
              SzEntryTile(
                  icon: Icons.public,
                  title: 'IP 地址',
                  value: '${r['ip'] ?? '未知'}'),
              if (sameNetwork)
                const SzEntryTile(
                    icon: Icons.wifi, title: '网络', value: '和这台手机是同一个网络'),
              SzEntryTile(
                  icon: Icons.schedule,
                  title: '发起时间',
                  value: _clock('${r['created_at'] ?? ''}')),
            ]),
            const SizedBox(height: 14),
            // 这句话是整页的重点:扫别人发来的码是最常见的骗法
            Text('如果不是你本人正在电脑前操作,请点取消。登录后,那台设备能看到你的订单、消息和收货地址。',
                style: TextStyle(fontSize: kFontNote, height: 1.6, color: sz.danger)),
            const SizedBox(height: 24),
            if (_failed.isNotEmpty) ...[
              Text(_failed,
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: kFontBody, color: sz.ink)),
              const SizedBox(height: 12),
              FilledButton(
                  onPressed: () => Navigator.of(context).pop(false),
                  child: const Text('知道了')),
            ] else ...[
              FilledButton(
                  onPressed: _busy ? null : _confirm,
                  child: Text(_busy ? '请稍候…' : '登录')),
              const SizedBox(height: 8),
              TextButton(onPressed: _busy ? null : _cancel, child: const Text('取消')),
            ],
          ],
        ),
      ),
    );
  }
}
