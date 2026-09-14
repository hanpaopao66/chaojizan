import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import '../store.dart';
import '../ui/avatar.dart';

/// 我的名片:二维码 + 链接。别人用「扫一扫」扫它、或者点这个链接,直接打开我的资料页,把我加为联系人。
///
/// 码里是什么由服务端定(/social/v1/me 的 link):有超级赞号、而且允许按号找到时是 `/@号`,
/// 否则是 `/u/名片编号`(一串随机编号,猜不出来)—— 关了「按超级赞号找到我」,这个码照样能用。
class MyCardPage extends StatefulWidget {
  const MyCardPage({super.key});

  @override
  State<MyCardPage> createState() => _MyCardPageState();
}

class _MyCardPageState extends State<MyCardPage> {
  Map<String, dynamic>? _me;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final m = await ChatStore.instance.api.me();
      if (mounted) {
        setState(() {
          _me = m;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final me = _me;
    if (me == null) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('我的名片')),
        body: _error != null
            ? SzError(
                error: _error,
                onRetry: () {
                  setState(() => _error = null);
                  _load();
                })
            : const Center(child: CircularProgressIndicator()),
      );
    }
    final link = '${me['link'] ?? ''}';
    final name = '${me['name'] ?? ''}';
    final username = me['username'] as String?;
    final searchOff = (me['privacy'] as Map?)?['username_search'] == 'nobody';
    return SzPageScaffold(
      appBar: AppBar(title: const Text('我的名片')),
      body: ListView(padding: const EdgeInsets.all(kPagePad), children: [
        Center(child: ChatAvatar(name: name, url: '${me['avatar'] ?? ''}', size: 64)),
        const SizedBox(height: 10),
        Center(
          child: Text(name, style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
        ),
        const SizedBox(height: 2),
        Center(
          child: Text(username != null ? '超级赞号:@$username' : '还没有超级赞号',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
        const SizedBox(height: 16),
        Center(
          child: Container(
            padding: const EdgeInsets.all(12),
            // 二维码必须白底黑码才扫得出来,不跟随深色主题
            decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(kRadiusMd)),
            child: QrImageView(data: link, size: 200),
          ),
        ),
        const SizedBox(height: 10),
        Center(child: SelectableText(link, style: TextStyle(color: sz.link, fontSize: kFontNote))),
        const SizedBox(height: 4),
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          TextButton.icon(
            icon: const Icon(Icons.copy, size: 18),
            label: const Text('复制链接'),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: link));
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已复制')));
              }
            },
          ),
          TextButton.icon(
            icon: const Icon(Icons.share_outlined, size: 18),
            label: const Text('分享'),
            onPressed: () => SharePlus.instance.share(ShareParams(text: '在超级赞上加我:$link')),
          ),
        ]),
        const SizedBox(height: 12),
        Text(
          [
            '对方用超级赞「扫一扫」扫这个码,或者点这个链接,就能打开你的资料页、把你加为联系人。',
            if (username == null) '你还没有设超级赞号,码里是一串随机编号。',
            if (username != null && searchOff)
              '你关了「按超级赞号找到我」,所以码里是一串随机编号,不是你的超级赞号:'
                  '别人输入你的号找不到你,这个码照样能用;以前发出去的 @ 链接打不开了。',
          ].join('\n'),
          style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.6),
        ),
      ]),
    );
  }
}
