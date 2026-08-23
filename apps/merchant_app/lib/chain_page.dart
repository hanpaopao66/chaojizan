import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:superz_shared/superz_shared.dart';

import 'license_upload_field.dart';

/// 连锁店群(总部视角)。
///
/// App 这边只做**看**和**开新店**两件事:跨店概览要随时能看,开新店要拍
/// 证照 —— 这两件恰好手机比电脑顺手。拉人授权、菜单批量同步这类要对着
/// 表格干的活留在网页版。
///
/// 界面上明写的两条规矩不是提示文案,是后端硬拦的:
/// 新门店证照不能复用(许可证按门店核发)、抄菜单不抄库存(否则一开门超卖)。
class MerchantChainPage extends StatefulWidget {
  const MerchantChainPage({super.key, required this.api, required this.shop});

  final ApiClient api;
  final Merchant shop;

  @override
  State<MerchantChainPage> createState() => _MerchantChainPageState();
}

class _MerchantChainPageState extends State<MerchantChainPage> {
  Map<String, dynamic>? _brand;
  Map<String, dynamic>? _overview;
  bool _loading = true;
  String? _error;
  int _days = 7;

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
      final brand = await widget.api.myBrand();
      Map<String, dynamic>? overview;
      if (brand['brand'] != null) {
        overview = await widget.api.brandOverview(days: _days);
      }
      if (!mounted) return;
      setState(() {
        _brand = brand;
        _overview = overview;
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
    final brand = _brand?['brand'] as Map<String, dynamic>?;
    final isOwner = brand?['is_owner'] == true;
    return SzPageScaffold(
      // 限宽用宽档:多门店对比表挤在 720 里看不清 ——
      // 宽度上限按**内容形态**选,不是统一限死
      contentMaxWidth: kWideMaxWidth,
      appBar: AppBar(
        title: Text(brand == null ? '连锁店群' : '${brand['name']}'),
        actions: [
          if (brand != null && isOwner)
            IconButton(
              tooltip: '开新门店',
              icon: const Icon(Icons.add_business_outlined),
              onPressed: _openNewShop,
            ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? _ErrorView(message: _error!, onRetry: _load)
              : brand == null
                  ? _CreateBrandView(
                      shopName: widget.shop.name, onCreate: _createBrand)
                  : RefreshIndicator(
                      onRefresh: _load, child: _overviewList(isOwner)),
    );
  }

  Widget _overviewList(bool isOwner) {
    final ov = _overview;
    final shops = ((ov?['shops'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    final total = (ov?['total'] as Map<String, dynamic>?) ?? const {};
    return ListView(
      padding: const EdgeInsets.all(12),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(children: [
              Row(children: [
                const Text('统计区间'),
                const Spacer(),
                SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(value: 1, label: Text('今天')),
                    ButtonSegment(value: 7, label: Text('7 天')),
                    ButtonSegment(value: 30, label: Text('30 天')),
                  ],
                  selected: {_days},
                  showSelectedIcon: false,
                  onSelectionChanged: (v) {
                    setState(() => _days = v.first);
                    _load();
                  },
                ),
              ]),
              const SizedBox(height: 12),
              Row(children: [
                _Stat(label: '门店', value: '${total['shops'] ?? 0}'),
                _Stat(label: '订单', value: '${total['orders'] ?? 0}'),
                _Stat(
                    label: '营业额',
                    value: '¥${((total['net_cents'] ?? 0) as int) / 100}'),
                _Stat(
                    label: '未回差评',
                    value: '${total['bad_unreplied'] ?? 0}',
                    danger: ((total['bad_unreplied'] ?? 0) as int) > 0),
              ]),
            ]),
          ),
        ),
        const SizedBox(height: 8),
        for (final s in shops) _shopCard(s),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 12),
          child: Text(
            '${ov?['note'] ?? ''}',
            style: TextStyle(
                fontSize: 12,
                color: Theme.of(context).colorScheme.onSurfaceVariant),
          ),
        ),
        if (isOwner)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Text(
              '拉区域经理进品牌、把菜价一次同步到几家店,在网页版'
              '(chaojizan.cc/merchant)对着表格干更顺手。',
              style: TextStyle(
                  fontSize: 12,
                  color: Theme.of(context).colorScheme.onSurfaceVariant),
            ),
          ),
      ],
    );
  }

  Widget _shopCard(Map<String, dynamic> s) {
    final current = s['shop_id'] == widget.shop.id;
    final bad = (s['bad_unreplied'] ?? 0) as int;
    final late = (s['ready_late'] ?? 0) as int;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text('${s['name']}',
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            if (current)
              const Chip(
                  label: Text('当前', style: TextStyle(fontSize: 11)),
                  visualDensity: VisualDensity.compact),
            if (s['status'] != 'approved')
              const Chip(
                  label: Text('审核中', style: TextStyle(fontSize: 11)),
                  visualDensity: VisualDensity.compact),
            if (s['status'] == 'approved' && s['is_open'] == false)
              const Chip(
                  label: Text('打烊', style: TextStyle(fontSize: 11)),
                  visualDensity: VisualDensity.compact),
          ]),
          const SizedBox(height: 8),
          Row(children: [
            _Stat(label: '订单', value: '${s['orders'] ?? 0}'),
            _Stat(
                label: '营业额',
                value: '¥${((s['net_cents'] ?? 0) as int) / 100}'),
            _Stat(
                label: '评分',
                value: s['rating_avg'] == null ? '—' : '${s['rating_avg']}'),
          ]),
          if (bad > 0 || late > 0) ...[
            const SizedBox(height: 6),
            Text(
              [
                if (bad > 0) '未回差评 $bad',
                if (late > 0) '出餐超时 $late',
              ].join(' · '),
              style: TextStyle(
                  fontSize: 12, color: Theme.of(context).colorScheme.error),
            ),
          ],
        ]),
      ),
    );
  }

  Future<void> _createBrand(String name) async {
    try {
      await widget.api.createBrand(name: name, shopId: widget.shop.id);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('品牌已创建')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _openNewShop() async {
    final shops = ((_brand?['shops'] as List?) ?? const [])
        .cast<Map<String, dynamic>>()
        .where((s) => s['in_brand'] == true)
        .toList();
    final ok = await Navigator.of(context).push<bool>(MaterialPageRoute(
      builder: (_) => _NewShopPage(api: widget.api, sources: shops),
    ));
    if (ok == true) _load();
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, this.danger = false});

  final String label;
  final String value;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label,
            style: TextStyle(
                fontSize: 12,
                color: Theme.of(context).colorScheme.onSurfaceVariant)),
        Text(value,
            style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w600,
                color: danger ? Theme.of(context).colorScheme.error : null)),
      ]),
    );
  }
}

class _ErrorView extends StatelessWidget {
  const _ErrorView({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Padding(
          padding: const EdgeInsets.all(24),
          child: Text(message, textAlign: TextAlign.center),
        ),
        FilledButton(onPressed: onRetry, child: const Text('重试')),
      ]),
    );
  }
}

class _CreateBrandView extends StatefulWidget {
  const _CreateBrandView({required this.shopName, required this.onCreate});

  final String shopName;
  final Future<void> Function(String name) onCreate;

  @override
  State<_CreateBrandView> createState() => _CreateBrandViewState();
}

class _CreateBrandViewState extends State<_CreateBrandView> {
  final _ctrl = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Text('把「${widget.shopName}」升级为品牌总部',
            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
        const SizedBox(height: 12),
        const Text('升级之后你可以:'),
        const SizedBox(height: 6),
        const Text('· 一处看完所有门店的单量、营业额、未回差评\n'
            '· 开新门店时直接抄这家的菜单(不抄库存)\n'
            '· 把菜价、描述一次同步到指定的几家店\n'
            '· 请区域经理帮你管几家店,不用把账号密码给别人'),
        const SizedBox(height: 12),
        Text(
          '新门店仍要各自提交证照并照走审核 —— '
          '食品经营许可证按门店核发,总部的不能给分店用。',
          style: TextStyle(fontSize: 13, color: muted),
        ),
        const SizedBox(height: 24),
        TextField(
          controller: _ctrl,
          maxLength: 50,
          decoration: const InputDecoration(
            labelText: '品牌名',
            hintText: '如:赞小碗',
            helperText: '用户端看到的仍是各门店自己的店名,品牌名只用在你的后台',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _busy
              ? null
              : () async {
                  final name = _ctrl.text.trim();
                  if (name.length < 2) {
                    ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text('品牌名至少 2 个字')));
                    return;
                  }
                  setState(() => _busy = true);
                  await widget.onCreate(name);
                  if (mounted) setState(() => _busy = false);
                },
          child: const Text('创建品牌'),
        ),
      ],
    );
  }
}

/// 开新门店:抄哪家的菜单 + 这家店自己的地址与证照。
class _NewShopPage extends StatefulWidget {
  const _NewShopPage({required this.api, required this.sources});

  final ApiClient api;
  final List<Map<String, dynamic>> sources;

  @override
  State<_NewShopPage> createState() => _NewShopPageState();
}

class _NewShopPageState extends State<_NewShopPage> {
  int? _copyFrom;
  final _name = TextEditingController();
  final _address = TextEditingController();

  /// 门店坐标(#285):由地图选点产生,**不再手输**
  double? _lat;
  double? _lng;

  /// 选点页的城市(限定 POI 搜索范围)。空 = 让选点页自己解析
  String _city = '';
  final _licenseNo = TextEditingController();
  String _licenseUrl = '';
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    if (widget.sources.isNotEmpty) {
      _copyFrom = widget.sources.first['id'] as int;
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _address.dispose();
    _licenseNo.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('开一家新门店')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            color: scheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('新门店必须提交自己的证照',
                      style: TextStyle(
                          fontWeight: FontWeight.w600,
                          color: scheme.onErrorContainer)),
                  const SizedBox(height: 6),
                  Text(
                    '食品经营许可证按门店核发,总部或其他门店的证照不能复用 —— '
                    '这是法定要求,不是平台的规定。新店照走人工核验。\n'
                    '菜品、分类、营业时间会从参照门店抄一份;库存不抄'
                    '(新店还没进货,抄了等于一开门就超卖)。',
                    style: TextStyle(
                        fontSize: 13, color: scheme.onErrorContainer),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          DropdownButtonFormField<int>(
            initialValue: _copyFrom,
            decoration: const InputDecoration(
                labelText: '参照门店(抄它的菜单)',
                border: OutlineInputBorder()),
            items: [
              for (final s in widget.sources)
                DropdownMenuItem(
                    value: s['id'] as int, child: Text('${s['name']}')),
            ],
            onChanged: (v) => setState(() => _copyFrom = v),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _name,
            maxLength: 50,
            decoration: const InputDecoration(
                labelText: '新门店名称',
                hintText: '如:赞小碗(高新店)',
                border: OutlineInputBorder()),
          ),
          TextField(
            controller: _address,
            maxLength: 200,
            decoration: const InputDecoration(
                labelText: '门店地址',
                hintText: '街道门牌号',
                border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          SzCard(
            child: Row(children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('门店位置',
                        style: TextStyle(
                            fontSize: 13.5, color: Theme.of(context).sz.ink)),
                    const SizedBox(height: 2),
                    Text(
                      _lat == null
                          ? '还没标 —— 用户能不能搜到这家店、骑手导航去哪,都看它'
                          : '已标(${_lat!.toStringAsFixed(5)}, ${_lng!.toStringAsFixed(5)})',
                      style: TextStyle(
                          fontSize: 11,
                          color: _lat == null
                              ? Theme.of(context).sz.danger
                              : Theme.of(context).sz.earn),
                    ),
                  ],
                ),
              ),
              TextButton.icon(
                icon: const Icon(Icons.map_outlined, size: 18),
                label: Text(_lat == null ? '标位置' : '重新标'),
                onPressed: _pickSpot,
              ),
            ]),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _licenseNo,
            maxLength: 64,
            decoration: const InputDecoration(
                labelText: '食品经营许可证编号',
                hintText: '这家店自己的编号',
                border: OutlineInputBorder()),
          ),
          const SizedBox(height: 8),
          LicenseUploadField(
            api: widget.api,
            label: '食品经营许可证照片',
            url: _licenseUrl,
            onUploaded: (url) => setState(() => _licenseUrl = url),
          ),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _busy ? null : _submit,
            child: const Text('提交审核'),
          ),
        ],
      ),
    );
  }

  /// 在地图上标这家分店的位置(#285)。
  ///
  /// 以前这里是两个「纬度」「经度」输入框,让店主手打坐标 —— 而**同一个 App
  /// 的首次入驻**(onboarding.dart 的 `_pickShopSpot`)早就用地图选点了,
  /// 那边的注释还写着「老板认自己店旁边那个地标,比认坐标容易」。
  ///
  /// 这不是体验问题,是**数据正确性**:小数点后第 2 位差 1 就是 1 公里,
  /// 而这个坐标决定用户能不能搜到这家店、骑手导航去哪、配送费按多远算。
  /// 填错了没有任何一层会拦。
  ///
  /// 走的是和入驻**同一套** `MapPickerPage` —— 另写一套的话两处行为迟早分叉。
  Future<void> _pickSpot() async {
    final picked = await Navigator.of(context).push<PickedPlace>(
      MaterialPageRoute(
        builder: (_) => MapPickerPage(
          initialLat: _lat,
          initialLng: _lng,
          onReverse: (lat, lng) async {
            final t = await widget.api.geoReverse(lat, lng);
            return (name: t.name, district: t.district);
          },
          // 周边地点:老板认自己店旁边那个地标,比认坐标容易
          onAround: widget.api.geoAround,
          onSearch: (kw) => widget.api.geoTips(kw, city: _city),
          city: _city,
          onCities: widget.api.openCities,
          onCityChanged: (c) => setState(() => _city = c),
          // 开分店时人多半就站在新店里,一键定位比拖地图准
          onLocate: _currentPosition,
        ),
      ),
    );
    if (picked == null || !mounted) return;
    setState(() {
      _lat = picked.lat;
      _lng = picked.lng;
      // 地址跟着选点走,和入驻页一个口径:显示的地址必须是这个坐标反查出来的,
      // 否则会出现「地址写着 A、坐标指着 B」而没人看得出来
      if (picked.name.isNotEmpty) _address.text = picked.name;
    });
  }

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

  Future<void> _submit() async {
    final lat = _lat;
    final lng = _lng;
    final missing = <String>[
      if (_copyFrom == null) '参照门店',
      if (_name.text.trim().isEmpty) '门店名称',
      if (_address.text.trim().isEmpty) '门店地址',
      if (lat == null || lng == null) '门店位置(在地图上标一下)',
      if (_licenseNo.text.trim().isEmpty) '许可证编号',
      if (_licenseUrl.isEmpty) '许可证照片',
    ];
    if (missing.isNotEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('还差:${missing.join('、')}')));
      return;
    }
    setState(() => _busy = true);
    try {
      await widget.api.openBrandShop(
        copyFrom: _copyFrom!,
        name: _name.text.trim(),
        address: _address.text.trim(),
        lat: lat!,
        lng: lng!,
        licenseNo: _licenseNo.text.trim(),
        licenseImageUrl: _licenseUrl,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已提交,平台核验证照后自动开通')));
      Navigator.pop(context, true);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
      setState(() => _busy = false);
    }
  }
}
