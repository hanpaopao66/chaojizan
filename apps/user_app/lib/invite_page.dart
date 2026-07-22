import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

/// 邀请有礼:好友完成首单后双方各得券。奖励挂首单不挂注册,刷号无利可图。
class InvitePage extends StatefulWidget {
  const InvitePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<InvitePage> createState() => _InvitePageState();
}

class _InvitePageState extends State<InvitePage> {
  Map<String, dynamic>? _d;
  final _claim = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final d = await widget.api.myReferral();
      if (mounted) setState(() => _d = d);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final d = _d;
    final reward =
        d == null ? '' : '${(d['reward_cents'] as int) / 100} 元';
    return Scaffold(
      appBar: AppBar(title: const Text('邀请有礼')),
      body: d == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(16), children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(children: [
                    Text('我的邀请码', style: theme.textTheme.titleSmall),
                    const SizedBox(height: 8),
                    Text('${d['code']}',
                        style: const TextStyle(
                            fontSize: 34,
                            fontWeight: FontWeight.w900,
                            letterSpacing: 6,
                            color: kBrandOrange)),
                    const SizedBox(height: 8),
                    Text('好友注册 24 小时内填码,完成首单后你俩各得 $reward无门槛券',
                        textAlign: TextAlign.center,
                        style: theme.textTheme.bodySmall),
                    const SizedBox(height: 12),
                    Row(children: [
                      Expanded(
                        child: OutlinedButton.icon(
                          icon: const Icon(Icons.copy, size: 16),
                          label: const Text('复制'),
                          onPressed: () {
                            Clipboard.setData(
                                ClipboardData(text: '${d['code']}'));
                            ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(content: Text('邀请码已复制')));
                          },
                        ),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: FilledButton.icon(
                          icon: const Icon(Icons.share, size: 16),
                          label: const Text('分享'),
                          onPressed: () {
                            Analytics.track('share',
                                {'kind': 'referral'});
                            SharePlus.instance.share(ShareParams(
                                text: '我在用「超级赞外卖」:商家只抽 5%、'
                                    '配送费全归骑手、账目公开。'
                                    '下载 https://chaojizan.cc/download ,'
                                    '注册后填我的邀请码 ${d['code']},'
                                    '你首单完成咱俩各得 $reward券!'));
                          },
                        ),
                      ),
                    ]),
                  ]),
                ),
              ),
              const SizedBox(height: 12),
              Card(
                child: ListTile(
                  title: const Text('我的战绩'),
                  subtitle: Text('已邀请 ${d['invited']} 人 · '
                      '完成首单 ${d['rewarded']} 人'),
                ),
              ),
              if (d['can_claim'] == true) ...[
                const SizedBox(height: 12),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('新用户?填好友的邀请码',
                            style: theme.textTheme.titleSmall),
                        const SizedBox(height: 8),
                        Row(children: [
                          Expanded(
                            child: TextField(
                                controller: _claim,
                                maxLength: 6,
                                keyboardType: TextInputType.number,
                                decoration: const InputDecoration(
                                    hintText: '6 位邀请码',
                                    counterText: '',
                                    border: OutlineInputBorder())),
                          ),
                          const SizedBox(width: 8),
                          FilledButton(
                            onPressed: () async {
                              try {
                                final r = await widget.api
                                    .claimReferral(_claim.text.trim());
                                if (!context.mounted) return;
                                ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(
                                        content: Text('${r['hint']}')));
                                _load();
                              } catch (e) {
                                if (!context.mounted) return;
                                ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(
                                        content: Text(e.toString())));
                              }
                            },
                            child: const Text('提交'),
                          ),
                        ]),
                      ],
                    ),
                  ),
                ),
              ],
            ]),
    );
  }
}
