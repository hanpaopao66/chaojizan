import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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
  String _tag = '';          // 家 / 公司 / 学校(空 = 不打标签)
  bool _parsing = false;     // 智能识别中
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

  /// 在地图上选点。
  ///
  /// 搜索联想只覆盖已收录的 POI —— 新交付的小区、城中村、园区里的某栋楼,
  /// 搜出来要么没有、要么只能选到几百米外的地标。而**配送费和配送范围
  /// 都是按坐标算的**,差 500 米骑手就白跑一趟。
  Future<void> _pickOnMap() async {
    final picked = await Navigator.of(context).push<PickedPlace>(
      MaterialPageRoute(
        builder: (_) => MapPickerPage(
          initialLat: _selected?.lat,
          initialLng: _selected?.lng,
          onReverse: (lat, lng) async {
            final t = await widget.api.geoReverse(lat, lng);
            return (name: t.name, district: t.district);
          },
        ),
      ),
    );
    if (picked == null || !mounted) return;
    setState(() {
      _selected = PoiTip(
        // 反查不出名字时用坐标兜底,让用户知道"位置存下了、名字得自己写",
        // 而不是看到一个空白以为没选上
        name: picked.name.isEmpty
            ? '地图选点 ${picked.lat.toStringAsFixed(5)},'
                '${picked.lng.toStringAsFixed(5)}'
            : picked.name,
        district: picked.district,
        lat: picked.lat,
        lng: picked.lng,
      );
      _search.text = _selected!.name;
      _tips = [];
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
        tag: _tag,
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

  /// 智能识别:粘贴板里的一段文字 → 自动填进各栏。
  ///
  /// 用户的地址往往已经存在于别处(微信里同事发的、上一个平台复制的)。
  /// 让他对着现成的文字重新手打一遍是在制造错误 ——
  /// 打错一个数字,骑手就打不通电话。
  ///
  /// **识别结果只是填进表单,不直接保存** —— 服务端用的是本地正则,
  /// 解析不了刁钻写法是常态,得让用户过目。
  Future<void> _smartParse() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final text = (data?.text ?? '').trim();
    if (text.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('剪贴板是空的 —— 先复制一段带地址的文字')));
      return;
    }
    setState(() => _parsing = true);
    try {
      final r = await widget.api.parseAddress(text);
      if (!mounted) return;
      setState(() {
        if ('${r['name']}'.isNotEmpty) _name.text = '${r['name']}';
        if ('${r['phone']}'.isNotEmpty) _phone.text = '${r['phone']}';
        if ('${r['detail']}'.isNotEmpty) _detail.text = '${r['detail']}';
        if ('${r['salutation']}'.isNotEmpty) {
          _salutation.text = '${r['salutation']}';
        }
        // 地址要走 POI 搜索定位(得有经纬度),所以只填进搜索框触发搜索,
        // **不直接当成选中的地址** —— 没有坐标的地址骑手送不到
        final addr = '${r['address']}';
        if (addr.isNotEmpty) {
          _search.text = addr;
          _onSearchChanged(addr);
        }
      });
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${r['note']}')));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('\$e')));
      }
    } finally {
      if (mounted) setState(() => _parsing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('新建收货地址')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 智能识别放最上面:用户手里多半已经有一段现成的地址文字,
          // 先给他"一键填好"的路,再给"一栏栏填"的路
          _SmartParseBar(busy: _parsing, onTap: _smartParse),
          const SizedBox(height: 14),
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
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              icon: const Icon(Icons.my_location, size: 18),
              label: const Text('搜不到?在地图上选位置'),
              onPressed: _pickOnMap,
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
          // 标签:地址簿里三个「XX路XX号」排在一起时,
          // 用户得逐字读才知道哪个是家 —— 一个标签省掉这次阅读
          _TagPicker(value: _tag, onChanged: (v) => setState(() => _tag = v)),
          const SizedBox(height: 6),
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


/// 智能识别条:粘贴一段文字,自动拆成各栏(对齐主流外卖 App)。
class _SmartParseBar extends StatelessWidget {
  const _SmartParseBar({required this.busy, required this.onTap});

  final bool busy;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 11, 10, 11),
      decoration: BoxDecoration(
        color: sz.surfaceAlt,
        borderRadius: BorderRadius.circular(kRadiusSm),
      ),
      child: Row(children: [
        Expanded(
          child: Text(
            '复制一段带地址的文字,点右边自动拆成收货人、电话和地址\n'
            '例:成都市锦江区春熙路8号 3栋502 张三 13800138000',
            style: TextStyle(fontSize: 11.5, height: 1.5, color: sz.inkMuted),
          ),
        ),
        const SizedBox(width: 8),
        FilledButton.tonal(
          onPressed: busy ? null : onTap,
          child: Text(busy ? '识别中' : '智能识别'),
        ),
      ]),
    );
  }
}

/// 标签选择:家 / 公司 / 学校。再点一次取消。
class _TagPicker extends StatelessWidget {
  const _TagPicker({required this.value, required this.onChanged});

  final String value;
  final ValueChanged<String> onChanged;

  static const _tags = ['家', '公司', '学校'];

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Row(children: [
      Text('标签', style: TextStyle(fontSize: 13.5, color: sz.inkMuted)),
      const SizedBox(width: 14),
      for (final t in _tags) ...[
        ChoiceChip(
          label: Text(t),
          selected: value == t,
          // 选中时**不显示对勾**:默认的对勾会把「家」这一个字挤没,
          // 屏幕上只剩一个勾,用户不知道自己选的是什么(实机撞过)
          showCheckmark: false,
          // 再点一次取消 —— 标签是可选的,不该点了就摘不掉
          onSelected: (on) => onChanged(on ? t : ''),
        ),
        const SizedBox(width: 8),
      ],
    ]);
  }
}
