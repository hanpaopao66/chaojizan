import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:geolocator/geolocator.dart';
import 'package:superz_shared/superz_shared.dart';

/// 地址簿排序的结果。[nearestId] 为 null 表示没定位/只有一个地址,
/// 此时 [list] 保持服务端给的原顺序,也不打「距离最近」标签。
typedef AddressOrder = ({List<Address> list, int? nearestId, double nearestM});

/// 地址簿排序(#171)。**纯函数** —— 不碰网络、定位和 UI。
///
/// 排序规则是这个页面唯一真正的逻辑,单独拎出来是为了能直接测:
/// 埋在 State 的异步 `_load()` 里,测试就只能去测自己抄的一份副本。
///
/// 两件事**故意分开**:
///
/// - **排序**:默认地址永远排最前 —— 用户特意设过「默认」,
///   那是他的明确意愿,不该被算出来的距离盖过去;
/// - **「距离最近」标签**:标在真的最近的那个上,而不是排序后的第一个。
///
/// 合成一件事的话,要么默认地址被挤走(违背用户意愿),
/// 要么标签指着一个并不最近的地址(是在骗人)。
AddressOrder sortAddressBook(List<Address> rows,
    {double? myLat, double? myLng}) {
  final lat = myLat, lng = myLng;
  // 没定位或只有一个地址:退回原来的顺序,功能不受影响
  if (lat == null || lng == null || rows.length <= 1) {
    return (list: rows, nearestId: null, nearestM: 0);
  }
  final list = [...rows]..sort((a, b) {
      if (a.isDefault != b.isDefault) return a.isDefault ? -1 : 1;
      return distanceMeters(lat, lng, a.lat, a.lng)
          .compareTo(distanceMeters(lat, lng, b.lat, b.lng));
    });
  // 「距离最近」标签给的是**真的最近的那个**,不是排序后的第一个 ——
  // 默认地址排在最前,但它未必是最近的
  var best = 0;
  var bestD = double.infinity;
  for (var i = 0; i < list.length; i++) {
    final d = distanceMeters(lat, lng, list[i].lat, list[i].lng);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  return (list: list, nearestId: list[best].id, nearestM: bestD);
}

/// 地址簿。selectMode = true 时点选地址直接返回(下单选址用)。
class AddressBookPage extends StatefulWidget {
  const AddressBookPage({
    super.key,
    required this.api,
    this.selectMode = false,
    this.myLat,
    this.myLng,
  });

  final ApiClient api;
  final bool selectMode;

  /// 当前位置。给了就按距离排序、给最近的打「距离最近」标签,
  /// 选址模式下还会自动选中它。
  ///
  /// **不给也能用** —— 定位失败/没授权时退回原来的顺序(默认地址在前),
  /// 不能因为拿不到定位就让用户选不了地址。
  final double? myLat;
  final double? myLng;

  @override
  State<AddressBookPage> createState() => _AddressBookPageState();
}

class _AddressBookPageState extends State<AddressBookPage> {
  List<Address> _list = [];
  bool _loaded = false;
  /// 离当前位置最近的那个地址;没定位时为 null
  int? _nearestId;
  double _nearestM = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await widget.api.addresses();
      if (!mounted) return;
      // 调用方没给位置时,自己取一次**最后已知位置**:
      // 不弹权限、不等 GPS 定位、拿不到就算了 ——
      // 「哪个地址离我近」这件事,几分钟前的位置足够用了,
      // 而为它卡住整个地址簿的加载是不划算的
      var myLat = widget.myLat, myLng = widget.myLng;
      if (myLat == null || myLng == null) {
        try {
          final last = await Geolocator.getLastKnownPosition();
          if (last != null) {
            myLat = last.latitude;
            myLng = last.longitude;
          }
        } catch (_) {
          // 没授权/不可用都走这里 —— 退回原来的顺序,功能不受影响
        }
      }
      if (!mounted) return;
      // 按离当前位置的远近排(规则见 sortAddressBook)
      final ordered = sortAddressBook(list, myLat: myLat, myLng: myLng);
      if (ordered.nearestId != null) {
        _nearestId = ordered.nearestId;
        _nearestM = ordered.nearestM;
      }
      setState(() {
        _list = ordered.list;
        _loaded = true;
      });
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
    return SzPageScaffold(
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
                  // +1 是顶部那条说明
                  itemCount: _list.length + (_nearestId != null ? 1 : 0),
                  itemBuilder: (context, rawIndex) {
                    // **不自动 pop 选中最近的那个。**
                    //
                    // 截图里那句"已为你自动选中"是在一个**单选列表**里预选,
                    // 用户仍能改。而我们这个列表点一下就返回了 ——
                    // 在这里"自动选中"等于替他做决定,他连别的地址都没看见。
                    // 所以只标出来 + 说一句,选还是他选。
                    if (_nearestId != null && rawIndex == 0) {
                      final sz = Theme.of(context).sz;
                      return Padding(
                        padding:
                            const EdgeInsets.fromLTRB(kPagePad, 10, kPagePad, 2),
                        child: Text(
                          '已按离你的远近排好序,最近的那个标了「距离最近」',
                          style:
                              TextStyle(fontSize: 11.5, color: sz.inkMuted),
                        ),
                      );
                    }
                    final i = _nearestId != null ? rawIndex - 1 : rawIndex;
                    final addr = _list[i];
                    final nearest = addr.id == _nearestId;
                    final sz = Theme.of(context).sz;
                    return ListTile(
                      leading: Icon(
                        addr.isDefault ? Icons.star : Icons.place_outlined,
                        color: addr.isDefault
                            ? Theme.of(context).colorScheme.primary
                            : null,
                      ),
                      title: Row(children: [
                        // 「距离最近」+ 标签:让用户一眼挑出要哪个,
                        // 不用逐字读三个「XX路XX号」
                        if (nearest) ...[
                          _Pill('距离最近', sz.clay),
                          const SizedBox(width: 5),
                        ],
                        if (addr.tag.isNotEmpty) ...[
                          _Pill(addr.tag, sz.inkMuted),
                          const SizedBox(width: 5),
                        ],
                        Expanded(
                          child: Text(addr.fullAddress,
                              maxLines: 1, overflow: TextOverflow.ellipsis),
                        ),
                      ]),
                      subtitle: Text(
                        nearest && _nearestM > 0
                            ? '${addr.contactName} ${addr.contactPhone}'
                                ' · 离你 ${distanceLabel(_nearestM)}'
                            : '${addr.contactName} ${addr.contactPhone}',
                      ),
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
  // 楼层与电梯(选填)。填了两件事会变准:
  // ETA 更诚实(爬 6 楼确实更慢)、无电梯高楼层下单时可以选「送上门」
  // 并付一笔**全额归骑手**的上门难度费(也可以选送到楼下不收)
  final _floor = TextEditingController();
  bool? _hasElevator;
  /// 搜索所在城市。**必须对**:服务端把 POI 搜索限死在这个城市里,
  /// 选错了用户搜自己家会一条都搜不到(实测西安的小区在 city=成都 时返回 0 条)
  String _city = '';
  bool _parsing = false;     // 智能识别中
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _initCity();
  }

  /// 城市优先级(记住的 > 定位解析 > 留空)统一在 CityPref.resolve 里,
  /// 商家端用的是同一份 —— 各写一遍的话两端行为会不一致,
  /// 而"为什么商家端搜不出来"这种问题极难从表象追到根因
  /// 当前位置。**先要权限再取** —— 直接取会在没授权时静默失败,
  /// 用户点了按钮没反应,只会以为 App 卡了
  Future<({double lat, double lng})?> _currentPosition() async {
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) {
      perm = await Geolocator.requestPermission();
    }
    if (perm == LocationPermission.denied ||
        perm == LocationPermission.deniedForever) {
      return null;
    }
    final me = await Geolocator.getCurrentPosition();
    return (lat: me.latitude, lng: me.longitude);
  }

  Future<void> _initCity() async {
    final city = await CityPref.resolve(
      // 用**最后已知位置**:不弹权限、不等 GPS —— 解析城市这件事
      // 不值得为它卡住表单
      lastKnown: () async {
        final me = await Geolocator.getLastKnownPosition();
        return me == null ? null : (lat: me.latitude, lng: me.longitude);
      },
      // 服务端直接给结构化城市名,客户端不解析(以前抠 district 那串
      // 行政区划,正则一贪婪就成了「陕西省西安市」)
      reverse: (lat, lng) async =>
          (await widget.api.geoReverse(lat, lng)).city,
    );
    if (city.isNotEmpty && mounted) setState(() => _city = city);
  }

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
        final tips = await widget.api.geoTips(text.trim(), city: _city);
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
          // 周边地点列表:用户认地名比认坐标容易得多
          onAround: widget.api.geoAround,
          // 地图页里也能搜。**和外面那个搜索框是两个入口不是两套逻辑** ——
          // 大厂都是这样:列表页搜到大致位置,进地图再微调到自家单元门
          onSearch: (kw) => widget.api.geoTips(kw, city: _city),
          city: _city,
          onCities: widget.api.openCities,
          onCityChanged: (c) => setState(() => _city = c),
          onLocate: _currentPosition,
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
        floor: int.tryParse(_floor.text.trim()),
        hasElevator: _hasElevator,
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
            .showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      if (mounted) setState(() => _parsing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: const Text('新建收货地址')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 智能识别放最上面:用户手里多半已经有一段现成的地址文字,
          // 先给他"一键填好"的路,再给"一栏栏填"的路
          _SmartParseBar(busy: _parsing, onTap: _smartParse),
          const SizedBox(height: 10),
          // 城市切换器紧挨着搜索框:服务端把 POI 搜索限死在这个城市里,
          // 选错了搜不出自己家 —— 它得和搜索框在一起,用户才会把两者关联起来
          Row(children: [
            SzCityChip(
              city: _city,
              loadCities: widget.api.openCities,
              onChanged: (c) {
                setState(() {
                  _city = c;
                  _tips = [];        // 换了城市,上一个城市的结果不作数
                });
                CityPref.save(c);
                if (_search.text.trim().isNotEmpty) {
                  _onSearchChanged(_search.text);   // 用新城市重搜一次
                }
              },
            ),
            const SizedBox(width: 4),
            Expanded(
              child: Text('搜索只在这个城市里找',
                  style: TextStyle(
                      fontSize: 11.5, color: Theme.of(context).sz.inkMuted)),
            ),
          ]),
          const SizedBox(height: 6),
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
          // 楼层与电梯:两个都选填。填了 ETA 会准一点,
          // 无电梯高楼层还能选「送上门」——那笔钱全额归骑手
          Row(children: [
            Expanded(
              child: TextField(
                controller: _floor,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                    labelText: '楼层(选填)',
                    hintText: '如 6',
                    border: OutlineInputBorder()),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: DropdownButtonFormField<bool?>(
                initialValue: _hasElevator,
                decoration: const InputDecoration(
                    labelText: '电梯(选填)', border: OutlineInputBorder()),
                items: const [
                  DropdownMenuItem(value: null, child: Text('不填')),
                  DropdownMenuItem(value: true, child: Text('有电梯')),
                  DropdownMenuItem(value: false, child: Text('无电梯')),
                ],
                onChanged: (v) => setState(() => _hasElevator = v),
              ),
            ),
          ]),
          Padding(
            padding: const EdgeInsets.only(top: 4, bottom: 6),
            child: Text(
              '填了楼层,预计送达会更准;无电梯的高楼层下单时可以选'
              '「送上门」,那笔钱全额归骑手,也可以选送到楼下不加钱。',
              style: TextStyle(
                  fontSize: 11.5,
                  color: Theme.of(context).colorScheme.onSurfaceVariant),
            ),
          ),
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

/// 地址前面的小标签(「距离最近」/「家」)。
///
/// 做成扁的小药丸而不是彩色徽章:地址簿是个功能列表,
/// 标签是用来**快速区分**的,不是用来吸引注意的。
class _Pill extends StatelessWidget {
  const _Pill(this.text, this.color);

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
        decoration: BoxDecoration(
          color: color.withValues(alpha: .12),
          borderRadius: BorderRadius.circular(3),
        ),
        child: Text(text,
            style: TextStyle(
                fontSize: 10.5, fontWeight: FontWeight.w600, color: color)),
      );
}
