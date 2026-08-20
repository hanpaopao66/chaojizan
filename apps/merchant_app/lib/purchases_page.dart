import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'license_upload_field.dart';

/// 进货查验台账(食品溯源)。
///
/// 《食品安全法》五十三条要求记录食品名称、规格、数量、生产日期或批号、
/// 保质期、进货日期、供货者名称/地址/联系方式并保存凭证;留存期不少于
/// 保质期满后六个月(没有明确保质期的两年)。
///
/// 这是餐饮小商家普遍不做、而出事时**唯一能自证清白**的东西。所以整页的
/// 设计压力都在一件事上:**让人真的愿意录第二次、第三次**。
/// 只有食材名与进货日期必填,缺项当场列出但不拦;供货商可从用过的里选,
/// 一选带出地址与电话;留存到期日平台替你算。
///
/// 手机端尤其重要:收货就在后门口,拍一张票据当场录完,回到电脑前就没人补了。
class PurchasesPage extends StatefulWidget {
  const PurchasesPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<PurchasesPage> createState() => _PurchasesPageState();
}

class _PurchasesPageState extends State<PurchasesPage> {
  List<Map<String, dynamic>> _items = const [];
  String _note = '';
  String _q = '';
  bool _loading = true;
  String? _error;
  final _search = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final r = await widget.api.purchases(q: _q.isEmpty ? null : _q);
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
      appBar: AppBar(title: const Text('进货查验台账')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _add,
        icon: const Icon(Icons.add_a_photo_outlined),
        label: const Text('录一笔'),
      ),
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: TextField(
            controller: _search,
            decoration: InputDecoration(
              prefixIcon: const Icon(Icons.search),
              hintText: '按食材名反查,如:牛腩',
              border: const OutlineInputBorder(),
              isDense: true,
              suffixIcon: _q.isEmpty
                  ? null
                  : IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _search.clear();
                        setState(() => _q = '');
                        _load();
                      },
                    ),
            ),
            textInputAction: TextInputAction.search,
            onSubmitted: (v) {
              setState(() => _q = v.trim());
              _load();
            },
          ),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? Center(
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                        Padding(
                          padding: const EdgeInsets.all(24),
                          child: Text(_error!, textAlign: TextAlign.center),
                        ),
                        FilledButton(
                            onPressed: _load, child: const Text('重试')),
                      ]),
                    )
                  : RefreshIndicator(
                      onRefresh: _load,
                      child: _ledgerList(scheme),
                    ),
        ),
      ]),
    );
  }

  /// 进货台账**只增不减**,开一年就是几百条 —— 按需构建。
  /// 顶部说明卡和尾部备注数量固定,拿出来当固定头尾
  Widget _ledgerList(ColorScheme scheme) {
    final leading = <Widget>[
                          if (_q.isEmpty)
                            Card(
                              color: scheme.secondaryContainer,
                              child: Padding(
                                padding: const EdgeInsets.all(12),
                                child: Column(
                                  crossAxisAlignment:
                                      CrossAxisAlignment.start,
                                  children: [
                                    Text('出事时,这本台账是唯一能自证清白的东西',
                                        style: TextStyle(
                                            fontWeight: FontWeight.w600,
                                            color: scheme
                                                .onSecondaryContainer)),
                                    const SizedBox(height: 4),
                                    Text(
                                      '「这批肉是谁供的、什么时候进的、票在哪」—— '
                                      '答不上来就只能自己扛。'
                                      '只有食材名和进货日期必填,'
                                      '其余缺了会提醒但不拦你先记下。',
                                      style: TextStyle(
                                          fontSize: 12,
                                          color:
                                              scheme.onSecondaryContainer),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          if (_items.isEmpty)
                            Padding(
                              padding: const EdgeInsets.symmetric(
                                  vertical: 48),
                              child: Center(
                                  child: Text(_q.isEmpty
                                      ? '还没有进货记录'
                                      : '没有找到「$_q」的进货记录')),
                            ),
    ];
    final trailing = <Widget>[
      if (_note.isNotEmpty && _q.isEmpty)
        Padding(
          padding: const EdgeInsets.all(8),
          child: Text(_note,
              style:
                  TextStyle(fontSize: 12, color: scheme.onSurfaceVariant)),
        ),
    ];

    return ListView.builder(
      padding: const EdgeInsets.fromLTRB(12, 4, 12, 88),
      itemCount: leading.length + _items.length + trailing.length,
      itemBuilder: (context, i) {
        if (i < leading.length) return leading[i];
        final j = i - leading.length;
        if (j < _items.length) return _recordTile(_items[j]);
        return trailing[j - _items.length];
      },
    );
  }

  Widget _recordTile(Map<String, dynamic> r) {
    final scheme = Theme.of(context).colorScheme;
    final sub = [
      if ('${r['spec']}'.isNotEmpty) '${r['spec']}',
      if ('${r['qty']}'.isNotEmpty) '${r['qty']}',
    ].join(' · ');
    final trace = [
      '进货 ${r['purchased_on']}',
      if (r['produced_on'] != null) '生产 ${r['produced_on']}',
      if ('${r['batch_no']}'.isNotEmpty) '批号 ${r['batch_no']}',
      if (r['shelf_life_end'] != null) '保质期至 ${r['shelf_life_end']}',
    ].join(' · ');
    final noReceipt = '${r['receipt_url']}'.isEmpty;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${r['name']}${sub.isEmpty ? '' : '  $sub'}',
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            if (noReceipt)
              Chip(
                label: const Text('缺票据', style: TextStyle(fontSize: 11)),
                visualDensity: VisualDensity.compact,
                backgroundColor: scheme.errorContainer,
              ),
            IconButton(
              icon: const Icon(Icons.delete_outline, size: 20),
              tooltip: '删掉录错的',
              onPressed: () => _delete(r),
            ),
          ]),
          Text(trace,
              style: TextStyle(
                  fontSize: 12, color: scheme.onSurfaceVariant)),
          const SizedBox(height: 4),
          Text(
            '${r['supplier_name']}'.isEmpty
                ? '供货商未填 —— 出事时这一项最关键'
                : '${r['supplier_name']}'
                    '${'${r['supplier_phone']}'.isEmpty ? '' : ' · ${r['supplier_phone']}'}',
            style: TextStyle(
                fontSize: 12,
                color: '${r['supplier_name']}'.isEmpty
                    ? scheme.error
                    : scheme.onSurfaceVariant),
          ),
          const SizedBox(height: 2),
          Text('最短留存到 ${r['keep_until']}',
              style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant)),
        ]),
      ),
    );
  }

  Future<void> _delete(Map<String, dynamic> r) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: Text('删掉「${r['name']}」这条?'),
        content: const Text('只用来删录错的 —— 到了最短留存期平台也不会自动删,'
            '记录留着是给你自己用的。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(d, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(d, true),
              child: const Text('删除')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.deletePurchase(r['id'] as int);
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _add() async {
    final saved = await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => _PurchaseFormPage(api: widget.api),
    ));
    if (saved == true) _load();
  }
}

class _PurchaseFormPage extends StatefulWidget {
  const _PurchaseFormPage({required this.api});

  final ApiClient api;

  @override
  State<_PurchaseFormPage> createState() => _PurchaseFormPageState();
}

class _PurchaseFormPageState extends State<_PurchaseFormPage> {
  final _name = TextEditingController();
  final _spec = TextEditingController();
  final _qty = TextEditingController();
  final _batch = TextEditingController();
  final _supplier = TextEditingController();
  final _address = TextEditingController();
  final _phone = TextEditingController();
  DateTime _purchased = DateTime.now();
  DateTime? _produced;
  DateTime? _shelfEnd;
  String _receipt = '';
  String _supLicense = '';
  bool _busy = false;
  List<Map<String, dynamic>> _suppliers = const [];

  @override
  void initState() {
    super.initState();
    // 拉不到"用过的供货商"只是少了个便捷入口,不该打断录入 —— 静默
    widget.api.purchaseSuppliers().then((v) {
      if (mounted) setState(() => _suppliers = v);
    }).onError((_, __) {});
  }

  @override
  void dispose() {
    for (final c in [_name, _spec, _qty, _batch, _supplier, _address, _phone]) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('录一笔进货')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _name,
            maxLength: 60,
            decoration: const InputDecoration(
              labelText: '食材名称',
              hintText: '如:牛腩',
              helperText: '出事时按这个名字反查,写日常叫法就行',
              border: OutlineInputBorder(),
            ),
          ),
          Row(children: [
            Expanded(
              child: TextField(
                controller: _spec,
                maxLength: 40,
                decoration: const InputDecoration(
                    labelText: '规格', hintText: '冷鲜/10kg',
                    border: OutlineInputBorder()),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: TextField(
                controller: _qty,
                maxLength: 30,
                decoration: const InputDecoration(
                    labelText: '数量', hintText: '2 箱',
                    border: OutlineInputBorder()),
              ),
            ),
          ]),
          _dateTile('进货日期', _purchased,
              (d) => setState(() => _purchased = d)),
          _dateTile('生产日期(与批号有一个即可)', _produced,
              (d) => setState(() => _produced = d), nullable: true),
          TextField(
            controller: _batch,
            maxLength: 40,
            decoration: const InputDecoration(
                labelText: '生产批号', border: OutlineInputBorder()),
          ),
          _dateTile('保质期至(留存期按它算)', _shelfEnd,
              (d) => setState(() => _shelfEnd = d), nullable: true),
          const SizedBox(height: 8),
          if (_suppliers.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Wrap(
                spacing: 8,
                children: [
                  for (final s in _suppliers.take(6))
                    ActionChip(
                      label: Text('${s['name']}'),
                      onPressed: () => setState(() {
                        _supplier.text = '${s['name']}';
                        _address.text = '${s['address'] ?? ''}';
                        _phone.text = '${s['phone'] ?? ''}';
                        _supLicense = '${s['license_url'] ?? ''}';
                      }),
                    ),
                ],
              ),
            ),
          TextField(
            controller: _supplier,
            maxLength: 60,
            decoration: const InputDecoration(
              labelText: '供货商名称',
              helperText: '点上面用过的一下带出地址与电话',
              border: OutlineInputBorder(),
            ),
          ),
          TextField(
            controller: _address,
            maxLength: 120,
            decoration: const InputDecoration(
                labelText: '供货商地址', border: OutlineInputBorder()),
          ),
          TextField(
            controller: _phone,
            maxLength: 20,
            keyboardType: TextInputType.phone,
            decoration: const InputDecoration(
                labelText: '联系方式', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          LicenseUploadField(
            api: widget.api,
            label: '进货票据照片',
            url: _receipt,
            onUploaded: (u) => setState(() => _receipt = u),
          ),
          const SizedBox(height: 8),
          LicenseUploadField(
            api: widget.api,
            label: '供货商资质照片(五十三条要求查验)',
            url: _supLicense,
            onUploaded: (u) => setState(() => _supLicense = u),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text(
              '票据与资质存在私密空间,只有你和平台审核员看得到。',
              style: TextStyle(fontSize: 12, color: scheme.onSurfaceVariant),
            ),
          ),
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: const Text('保存'),
          ),
        ],
      ),
    );
  }

  Widget _dateTile(String label, DateTime? value, void Function(DateTime) set,
      {bool nullable = false}) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(label),
      subtitle: Text(value == null
          ? '未填'
          : value.toIso8601String().substring(0, 10)),
      trailing: const Icon(Icons.calendar_today, size: 20),
      onTap: () async {
        final now = DateTime.now();
        final picked = await showDatePicker(
          context: context,
          firstDate: DateTime(now.year - 3),
          lastDate: DateTime(now.year + 10),
          initialDate: value ?? now,
        );
        if (picked != null) set(picked);
      },
    );
  }

  Future<void> _submit() async {
    if (_name.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('还差:食材名称')));
      return;
    }
    setState(() => _busy = true);
    try {
      String? d(DateTime? v) => v?.toIso8601String().substring(0, 10);
      final r = await widget.api.addPurchase({
        'name': _name.text.trim(),
        'spec': _spec.text.trim(),
        'qty': _qty.text.trim(),
        'batch_no': _batch.text.trim(),
        'produced_on': d(_produced),
        'shelf_life_end': d(_shelfEnd),
        'purchased_on': d(_purchased),
        'supplier_name': _supplier.text.trim(),
        'supplier_address': _address.text.trim(),
        'supplier_phone': _phone.text.trim(),
        'receipt_url': _receipt,
        'supplier_license_url': _supLicense,
      });
      if (!mounted) return;
      final missing = ((r['missing'] as List?) ?? const []).cast<String>();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(missing.isEmpty
            ? '已保存,这条至少留到 ${r['keep_until']}'
            : '已保存。还缺:${missing.join('、')}(可稍后补录)'),
        duration: Duration(seconds: missing.isEmpty ? 3 : 6),
      ));
      Navigator.pop(context, true);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
      setState(() => _busy = false);
    }
  }
}
