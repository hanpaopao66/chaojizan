import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

/// 地址簿。selectMode = true 时点选地址直接返回(下单选址用)。
class AddressBookPage extends StatefulWidget {
  const AddressBookPage({super.key, required this.api, this.selectMode = false});

  final ApiClient api;
  final bool selectMode;

  @override
  State<AddressBookPage> createState() => _AddressBookPageState();
}

class _AddressBookPageState extends State<AddressBookPage> {
  List<Address> _list = [];
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await widget.api.addresses();
      if (mounted) {
        setState(() {
          _list = list;
          _loaded = true;
        });
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _add() async {
    final created = await Navigator.of(context).push<Address>(
        MaterialPageRoute(builder: (_) => AddressEditPage(api: widget.api)));
    if (created != null && widget.selectMode && mounted) {
      Navigator.of(context).pop(created); // 新建完直接选中
      return;
    }
    _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(widget.selectMode ? '选择收货地址' : '我的收货地址')),
      body: !_loaded
          ? const Center(child: CircularProgressIndicator())
          : _list.isEmpty
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Text('还没有收货地址'),
                      const SizedBox(height: 12),
                      FilledButton(onPressed: _add, child: const Text('新建地址')),
                    ],
                  ),
                )
              : ListView.builder(
                  itemCount: _list.length,
                  itemBuilder: (context, i) {
                    final addr = _list[i];
                    return ListTile(
                      leading: Icon(
                        addr.isDefault ? Icons.star : Icons.place_outlined,
                        color: addr.isDefault
                            ? Theme.of(context).colorScheme.primary
                            : null,
                      ),
                      title: Text(addr.fullAddress),
                      subtitle:
                          Text('${addr.contactName} ${addr.contactPhone}'),
                      trailing: widget.selectMode
                          ? const Icon(Icons.chevron_right)
                          : PopupMenuButton<String>(
                              onSelected: (action) async {
                                try {
                                  if (action == 'default') {
                                    await widget.api.updateAddress(
                                        addr.id, {'is_default': true});
                                  } else if (action == 'delete') {
                                    await widget.api.deleteAddress(addr.id);
                                  }
                                  _load();
                                } catch (e) {
                                  if (!context.mounted) return;
                                  ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(content: Text(e.toString())));
                                }
                              },
                              itemBuilder: (_) => const [
                                PopupMenuItem(
                                    value: 'default', child: Text('设为默认')),
                                PopupMenuItem(
                                    value: 'delete', child: Text('删除')),
                              ],
                            ),
                      onTap: widget.selectMode
                          ? () => Navigator.of(context).pop(addr)
                          : null,
                    );
                  },
                ),
      floatingActionButton: _list.isEmpty
          ? null
          : FloatingActionButton.extended(
              onPressed: _add,
              icon: const Icon(Icons.add),
              label: const Text('新建地址')),
    );
  }
}

/// 新建地址:POI 搜索选点 + 门牌 + 联系人。
class AddressEditPage extends StatefulWidget {
  const AddressEditPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<AddressEditPage> createState() => _AddressEditPageState();
}

class _AddressEditPageState extends State<AddressEditPage> {
  final _search = TextEditingController();
  final _detail = TextEditingController();
  final _name = TextEditingController();
  final _phone = TextEditingController();
  Timer? _debounce;
  List<PoiTip> _tips = [];
  PoiTip? _selected;
  bool _isDefault = false;
  bool _protect = false; // 保护模式:骑手只见小区/楼栋,门牌送达前不下发
  final _salutation = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  void _onSearchChanged(String text) {
    _debounce?.cancel();
    if (text.trim().isEmpty) {
      setState(() => _tips = []);
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 400), () async {
      try {
        final tips = await widget.api.geoTips(text.trim());
        if (mounted) setState(() => _tips = tips);
      } catch (_) {}
    });
  }

  Future<void> _save() async {
    if (_selected == null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请先搜索并选择地址')));
      return;
    }
    if (_name.text.trim().isEmpty || !RegExp(r'^1\d{10}$').hasMatch(_phone.text.trim())) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请填写联系人和正确的手机号')));
      return;
    }
    setState(() => _busy = true);
    try {
      final created = await widget.api.addAddress(
        contactName: _name.text.trim(),
        contactPhone: _phone.text.trim(),
        address: _selected!.name,
        detail: _detail.text.trim(),
        lat: _selected!.lat,
        lng: _selected!.lng,
        isDefault: _isDefault,
        protect: _protect,
        salutation: _salutation.text.trim(),
      );
      if (mounted) Navigator.of(context).pop(created);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('新建收货地址')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _search,
            onChanged: _onSearchChanged,
            decoration: InputDecoration(
              labelText: '搜索小区/大厦/学校',
              prefixIcon: const Icon(Icons.search),
              border: const OutlineInputBorder(),
              helperText: _selected == null ? '从搜索结果里选一个定位点' : null,
            ),
          ),
          if (_selected == null)
            ..._tips.map((tip) => ListTile(
                  leading: const Icon(Icons.place_outlined),
                  title: Text(tip.name),
                  subtitle: Text(tip.district),
                  onTap: () => setState(() {
                    _selected = tip;
                    _search.text = tip.name;
                    _tips = [];
                  }),
                ))
          else
            ListTile(
              leading: Icon(Icons.check_circle,
                  color: Theme.of(context).colorScheme.primary),
              title: Text(_selected!.name),
              subtitle: Text(_selected!.district),
              trailing: TextButton(
                onPressed: () => setState(() => _selected = null),
                child: const Text('重选'),
              ),
            ),
          const SizedBox(height: 12),
          TextField(
              controller: _detail,
              decoration: const InputDecoration(
                  labelText: '门牌号(如 2 单元 501)',
                  border: OutlineInputBorder())),
          const SizedBox(height: 12),
          TextField(
              controller: _name,
              decoration: const InputDecoration(
                  labelText: '联系人 *', border: OutlineInputBorder())),
          const SizedBox(height: 12),
          TextField(
              controller: _phone,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(
                  labelText: '手机号 *', border: OutlineInputBorder())),
          SwitchListTile(
            title: const Text('设为默认地址'),
            value: _isDefault,
            onChanged: (v) => setState(() => _isDefault = v),
          ),
          SwitchListTile(
            title: const Text('地址保护(深夜更安心)'),
            subtitle: const Text('骑手只看到小区/楼栋,门牌号送达前不下发;'
                '骑手到楼下后可下楼取,或一键临时放行'),
            value: _protect,
            onChanged: (v) => setState(() => _protect = v),
          ),
          if (_protect)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: TextField(
                  controller: _salutation,
                  maxLength: 12,
                  decoration: const InputDecoration(
                      labelText: '对骑手显示的称呼(留空显示「顾客」)',
                      hintText: '如:李女士 / 顾客',
                      counterText: '',
                      border: OutlineInputBorder())),
            ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: _busy ? null : _save,
            child: Text(_busy ? '保存中…' : '保存'),
          ),
        ],
      ),
    );
  }
}
