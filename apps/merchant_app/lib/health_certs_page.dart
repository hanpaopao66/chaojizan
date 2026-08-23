import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'license_upload_field.dart';

/// 从业人员健康证台账。
///
/// 《食品安全法》四十五条:接触直接入口食品的从业人员每年体检、持证上岗。
/// 证一年一换、到期静默失效 —— 监管检查看的是**记录**,
/// 塞在抽屉里翻不出来就是没有。手机拍一张就录进来,比在电脑上敲顺手。
///
/// 界面上写死的两条规矩:
/// - **到期只提醒不停业**:证是按人的,一个员工过期停整家店不成比例
///   (与食品经营许可证过期的后果明确不同,不能让商家以为是一回事);
/// - **离职归档不删除**:监管查的是"当时在岗的人有没有证"。
class HealthCertsPage extends StatefulWidget {
  const HealthCertsPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<HealthCertsPage> createState() => _HealthCertsPageState();
}

class _HealthCertsPageState extends State<HealthCertsPage> {
  List<Map<String, dynamic>> _items = const [];
  String _note = '';
  bool _showArchived = false;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await widget.api.healthCerts(includeArchived: _showArchived);
      if (!mounted) return;
      setState(() {
        _items = ((r['items'] as List?) ?? const [])
            .cast<Map<String, dynamic>>();
        _note = '${r['note'] ?? ''}';
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('从业人员健康证'),
        actions: [
          IconButton(
            tooltip: _showArchived ? '隐藏已离职' : '显示已离职',
            icon: Icon(_showArchived
                ? Icons.person_off
                : Icons.person_off_outlined),
            onPressed: () {
              setState(() => _showArchived = !_showArchived);
              _load();
            },
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _edit(null),
        icon: const Icon(Icons.add),
        label: const Text('录入'),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(_error!, textAlign: TextAlign.center),
                    ),
                    FilledButton(onPressed: _load, child: const Text('重试')),
                  ]),
                )
              : RefreshIndicator(
                  onRefresh: _load,
                  child: ListView(
                    padding: const EdgeInsets.all(12),
                    children: [
                      Card(
                        color: scheme.secondaryContainer,
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('健康证一年一检,到期只提醒、不停业',
                                  style: TextStyle(
                                      fontWeight: FontWeight.w600,
                                      color: scheme.onSecondaryContainer)),
                              const SizedBox(height: 4),
                              Text(
                                '证是按人的,一个员工的证过期停整家店不成比例 —— '
                                '这一点和食品经营许可证不同(那张过期超宽限期会'
                                '暂停营业)。员工离职请用「归档」而不是删除:'
                                '监管查的是「当时在岗的人有没有证」。',
                                style: TextStyle(
                                    fontSize: 12,
                                    color: scheme.onSecondaryContainer),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 8),
                      if (_items.isEmpty)
                        const Padding(
                          padding: EdgeInsets.symmetric(vertical: 48),
                          child: Center(child: Text('还没有录入健康证')),
                        ),
                      for (final c in _items) _certTile(c),
                      if (_note.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.all(8),
                          child: Text(_note,
                              style: TextStyle(
                                  fontSize: 12,
                                  color: scheme.onSurfaceVariant)),
                        ),
                      const SizedBox(height: 72),
                    ],
                  ),
                ),
    );
  }

  Widget _certTile(Map<String, dynamic> c) {
    final scheme = Theme.of(context).colorScheme;
    final archived = c['archived'] == true;
    final stage = '${c['stage']}';
    final left = c['days_left'] as int?;
    final (label, color) = switch (stage) {
      _ when archived => ('已离职', scheme.onSurfaceVariant),
      'unknown' => ('未填有效期', scheme.onSurfaceVariant),
      'ok' => ('有效', Colors.green),
      'soon' => ('$left 天后到期', scheme.primary),
      'urgent' || 'last' => ('$left 天后到期', Colors.orange),
      _ => (left == null ? '已过期' : '已过期 ${-left} 天', scheme.error),
    };
    return Card(
      child: Opacity(
        opacity: archived ? 0.5 : 1,
        child: ListTile(
          title: Row(children: [
            Text('${c['name']}',
                style: const TextStyle(fontWeight: FontWeight.w600)),
            if ('${c['role']}'.isNotEmpty) ...[
              const SizedBox(width: 8),
              Text('${c['role']}',
                  style: TextStyle(
                      fontSize: 12, color: scheme.onSurfaceVariant)),
            ],
          ]),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if ('${c['cert_no']}'.isNotEmpty)
                Text('${c['cert_no']}',
                    style: TextStyle(
                        fontSize: 12, color: scheme.onSurfaceVariant)),
              Text(
                c['expires_at'] == null
                    ? '未填有效期'
                    : '有效期至 ${c['expires_at']} · $label',
                style: TextStyle(fontSize: 12, color: color),
              ),
            ],
          ),
          trailing: archived
              ? null
              : PopupMenuButton<String>(
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 'renew', child: Text('换新证')),
                    PopupMenuItem(value: 'archive', child: Text('该员工已离职')),
                  ],
                  onSelected: (v) {
                    if (v == 'renew') {
                      _edit(c);
                    } else {
                      _archive(c);
                    }
                  },
                ),
        ),
      ),
    );
  }

  Future<void> _archive(Map<String, dynamic> c) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => SzDialog(
        title: Text('「${c['name']}」已离职?'),
        content: const Text('归档后不再提醒,记录仍保留以备核查 —— '
            '监管查的是「当时在岗的人有没有证」,删掉就说不清了。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(d, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(d, true),
              child: const Text('归档')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.archiveHealthCert(c['id'] as int);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('已归档')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _edit(Map<String, dynamic>? existing) async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => _CertFormPage(api: widget.api, existing: existing),
    ));
    if (saved == true) _load();
  }
}

class _CertFormPage extends StatefulWidget {
  const _CertFormPage({required this.api, this.existing});

  final ApiClient api;
  final Map<String, dynamic>? existing;

  @override
  State<_CertFormPage> createState() => _CertFormPageState();
}

class _CertFormPageState extends State<_CertFormPage> {
  late final TextEditingController _name =
      TextEditingController(text: '${widget.existing?['name'] ?? ''}');
  late final TextEditingController _role =
      TextEditingController(text: '${widget.existing?['role'] ?? ''}');
  final _certNo = TextEditingController();
  DateTime? _expires;
  String _photo = '';
  bool _busy = false;

  bool get _renewing => widget.existing != null;

  @override
  void dispose() {
    _name.dispose();
    _role.dispose();
    _certNo.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SzPageScaffold(
      appBar: AppBar(
          title: Text(_renewing
              ? '为「${widget.existing!['name']}」录入新证'
              : '录入健康证')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _name,
            maxLength: 30,
            enabled: !_renewing,
            decoration: InputDecoration(
              labelText: '姓名',
              border: const OutlineInputBorder(),
              helperText: _renewing
                  ? '姓名与岗位都不变才算「换新证」,改了会新增一条记录'
                  : null,
              helperMaxLines: 2,
            ),
          ),
          TextField(
            controller: _role,
            maxLength: 20,
            enabled: !_renewing,
            decoration: const InputDecoration(
              labelText: '岗位',
              hintText: '如:后厨 / 配菜 / 传菜 / 前厅',
              border: OutlineInputBorder(),
            ),
          ),
          TextField(
            controller: _certNo,
            maxLength: 40,
            decoration: const InputDecoration(
                labelText: '健康证编号(选填)', border: OutlineInputBorder()),
          ),
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('有效期至'),
            subtitle: Text(_expires == null
                ? '到期提醒靠它 —— 到期前 30 天提醒你安排体检(体检要排队)'
                : _expires!.toIso8601String().substring(0, 10)),
            trailing: const Icon(Icons.calendar_today, size: 20),
            onTap: () async {
              final now = DateTime.now();
              final picked = await showDatePicker(
                context: context,
                firstDate: DateTime(now.year - 2),
                lastDate: DateTime(now.year + 10),
                initialDate: now.add(const Duration(days: 365)),
              );
              if (picked != null) setState(() => _expires = picked);
            },
          ),
          const SizedBox(height: 8),
          LicenseUploadField(
            api: widget.api,
            label: '健康证照片(选填)',
            url: _photo,
            onUploaded: (u) => setState(() => _photo = u),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text(
              '照片存在私密空间,只有你和平台审核员看得到 —— '
              '这是员工本人的个人信息,不会出现在店铺公示页。',
              style: TextStyle(
                  fontSize: 12, color: scheme.onSurfaceVariant),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: const Text('保存'),
          ),
        ],
      ),
    );
  }

  Future<void> _submit() async {
    final missing = <String>[
      if (_name.text.trim().length < 2) '姓名',
      if (_expires == null) '有效期至',
    ];
    if (missing.isNotEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('还差:${missing.join('、')}')));
      return;
    }
    setState(() => _busy = true);
    try {
      await widget.api.saveHealthCert(
        name: _name.text.trim(),
        role: _role.text.trim(),
        certNo: _certNo.text.trim(),
        photoUrl: _photo,
        expiresAt: _expires!.toIso8601String().substring(0, 10),
      );
      if (!mounted) return;
      Navigator.pop(context, true);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
      setState(() => _busy = false);
    }
  }
}
