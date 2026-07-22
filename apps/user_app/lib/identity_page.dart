import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 实名认证页:按需触发(购买酒类等受限品类时要求),不是注册门槛。
/// 证号加密落库、明文不出接口;这里只展示 verified 与打码姓名。
class IdentityPage extends StatefulWidget {
  const IdentityPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<IdentityPage> createState() => _IdentityPageState();
}

class _IdentityPageState extends State<IdentityPage> {
  Map<String, dynamic>? _status;
  final _name = TextEditingController();
  final _idNo = TextEditingController();
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final status = await widget.api.identityStatus();
      if (mounted) setState(() => _status = status);
    } catch (_) {
      if (mounted) setState(() => _status = {'verified': false});
    }
  }

  Future<void> _submit() async {
    final name = _name.text.trim();
    final idNo = _idNo.text.trim();
    if (name.length < 2 || idNo.length != 18) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请填写真实姓名与 18 位身份证号')));
      return;
    }
    setState(() => _submitting = true);
    try {
      await widget.api.verifyIdentity(name, idNo);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('实名认证完成 ✓')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = _status;
    return Scaffold(
      appBar: AppBar(title: const Text('实名认证')),
      body: s == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: s['verified'] == true
                  ? [
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(20),
                          child: Column(
                            children: [
                              const Icon(Icons.verified_user,
                                  size: 48, color: kMoneyGreen),
                              const SizedBox(height: 10),
                              Text('已完成实名认证',
                                  style: theme.textTheme.titleMedium?.copyWith(
                                      fontWeight: FontWeight.bold)),
                              const SizedBox(height: 4),
                              Text('${s['real_name'] ?? ''}',
                                  style: theme.textTheme.bodyMedium),
                              const SizedBox(height: 12),
                              Text(
                                '实名信息用于酒类等受限商品的年龄核验。'
                                '身份证号已加密存储,不会展示、不会提供给商家或骑手;'
                                '注销账号时实名数据一并删除。',
                                textAlign: TextAlign.center,
                                style: theme.textTheme.bodySmall?.copyWith(
                                    color: theme.colorScheme.outline,
                                    height: 1.6),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ]
                  : [
                      Text('为什么需要实名?',
                          style: theme.textTheme.titleSmall
                              ?.copyWith(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 6),
                      Text(
                        '依法向未成年人禁售酒类。购买酒类等受限商品前,'
                        '需完成一次实名认证核验年龄——只做一次,全程有效。\n'
                        '身份证号加密存储、明文不出接口,不会提供给商家或骑手;'
                        '注销账号时实名数据一并删除。',
                        style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.outline, height: 1.6),
                      ),
                      const SizedBox(height: 16),
                      TextField(
                        controller: _name,
                        maxLength: 50,
                        decoration: const InputDecoration(
                            labelText: '真实姓名',
                            border: OutlineInputBorder()),
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        controller: _idNo,
                        maxLength: 18,
                        decoration: const InputDecoration(
                            labelText: '身份证号(18 位)',
                            border: OutlineInputBorder()),
                      ),
                      const SizedBox(height: 12),
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton(
                          onPressed: _submitting ? null : _submit,
                          child: Text(_submitting ? '核验中…' : '提交认证'),
                        ),
                      ),
                    ],
            ),
    );
  }
}
