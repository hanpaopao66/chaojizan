/// 商家入驻流程(对齐主流商家端的交互逻辑)。
///
/// 原先登录后没有店铺就被直接锁死在一张 400 行的大表单里 ——
/// 无返回、无说明、填一半退出全丢。现在拆成:
///
/// 1. [OnboardingWelcomePage] 开店引导页:先讲清楚平台规则和要准备的材料,
///    商家自己点「我要开店」才进表单;没点之前可以退出登录换账号;
/// 2. [ApplyShopPage] 分步表单(业态 → 门店信息 → 资质证照),
///    每步存草稿(shared_preferences),中途退出下次接着填;
/// 3. [PendingReviewPage] 审核进度可视化:已提交 → 审核中 → 通过,
///    通过后自动进工作台(ShopGate 轮询);
/// 4. [RejectedShopPage] 驳回页:原因醒目展示,「修改后重新提交」时
///    **所有已填内容(含证照号和照片)原样回填**,只改需要改的。
library;

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'license_upload_field.dart';

const _kDraftKey = 'apply_shop_draft_v1';

Future<bool> hasApplyDraft() async {
  final prefs = await SharedPreferences.getInstance();
  return prefs.containsKey(_kDraftKey);
}

Future<void> clearApplyDraft() async {
  final prefs = await SharedPreferences.getInstance();
  await prefs.remove(_kDraftKey);
}

// ---------------------------------------------------------------------------
// 1. 开店引导页
// ---------------------------------------------------------------------------

class OnboardingWelcomePage extends StatefulWidget {
  const OnboardingWelcomePage({
    super.key,
    required this.api,
    required this.onSubmitted,
  });

  final ApiClient api;
  final VoidCallback onSubmitted;

  @override
  State<OnboardingWelcomePage> createState() => _OnboardingWelcomePageState();
}

class _OnboardingWelcomePageState extends State<OnboardingWelcomePage> {
  bool _hasDraft = false;

  @override
  void initState() {
    super.initState();
    hasApplyDraft().then((v) {
      if (mounted) setState(() => _hasDraft = v);
    });
  }

  Future<void> _logout() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('退出登录?'),
        content: const Text('已填写的开店草稿会保留在本机。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dialog, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(dialog, true),
              child: const Text('退出')),
        ],
      ),
    );
    if (ok != true) return;
    await widget.api.clearSession();
    ApiClient.onUnauthorized?.call(); // AuthGate 切回登录页
  }

  Future<void> _startApply() async {
    await Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) =>
            ApplyShopPage(api: widget.api, onSubmitted: widget.onSubmitted)));
    // 回来时草稿状态可能变了(提交成功已清/中途退出已存)
    final v = await hasApplyDraft();
    if (mounted) setState(() => _hasDraft = v);
  }

  Widget _bullet(BuildContext context, IconData icon, String text) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Icon(icon, size: 18, color: sz.earn),
        const SizedBox(width: 10),
        Expanded(child: Text(text, style: const TextStyle(fontSize: 14))),
      ]),
    );
  }

  Widget _material(BuildContext context, String text, {bool optional = false}) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(optional ? Icons.circle_outlined : Icons.check_circle_outline,
            size: 16, color: optional ? sz.inkFaint : sz.clay),
        const SizedBox(width: 8),
        Expanded(
            child: Text(text,
                style: TextStyle(
                    fontSize: 13, color: optional ? sz.inkMuted : sz.ink))),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Scaffold(
      appBar: AppBar(
        title: const Text('开店入驻'),
        actions: [
          TextButton(onPressed: _logout, child: const Text('退出登录')),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const SizedBox(height: 8),
          Icon(Icons.storefront, size: 56, color: sz.clay),
          const SizedBox(height: 12),
          Text('把店开上超级赞',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 4),
          Text('入驻免费,随时可退',
              textAlign: TextAlign.center,
              style: TextStyle(color: sz.inkMuted)),
          const SizedBox(height: 20),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child:
                  Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('为什么选超级赞',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                _bullet(context, Icons.percent, '总负担 5% 封顶,单量越大费率越低(最低 4%)'),
                _bullet(context, Icons.visibility_outlined, '没有竞价排名,没有隐藏费用'),
                _bullet(context, Icons.receipt_long_outlined,
                    '每日对账,每一笔分账可查可申诉'),
                _bullet(context, Icons.delivery_dining_outlined, '配送费全归骑手,平台分文不取'),
              ]),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child:
                  Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('入驻前准备好这些材料',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 4),
                Text('拍好照片再开始,5 分钟就能填完',
                    style: TextStyle(fontSize: 12, color: sz.inkMuted)),
                const SizedBox(height: 10),
                Text('餐饮外卖', style: TextStyle(fontWeight: FontWeight.w600, color: sz.ink)),
                const SizedBox(height: 4),
                _material(context, '食品经营许可证(证号 + 照片)'),
                _material(context, '店铺名称、门店地址,并在地图上标出位置'),
                const SizedBox(height: 10),
                Text('酒店住宿', style: TextStyle(fontWeight: FontWeight.w600, color: sz.ink)),
                const SizedBox(height: 4),
                _material(context, '营业执照(注册号 + 照片)'),
                _material(context, '特种行业许可证(旅馆业,公安核发;证号 + 照片)'),
                _material(context, '卫生许可证照片(选填)', optional: true),
              ]),
            ),
          ),
          const SizedBox(height: 12),
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            Icon(Icons.schedule, size: 14, color: sz.inkFaint),
            const SizedBox(width: 4),
            Text('提交后平台人工审核,通常 1-3 个工作日',
                style: TextStyle(fontSize: 12, color: sz.inkMuted)),
          ]),
          const SizedBox(height: 16),
          FilledButton(
            style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14)),
            onPressed: _startApply,
            child: Text(_hasDraft ? '继续填写(已保存草稿)' : '我准备好了,开始入驻'),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 2. 分步入驻表单
// ---------------------------------------------------------------------------

class ApplyShopPage extends StatefulWidget {
  const ApplyShopPage({
    super.key,
    required this.api,
    this.existing,
    required this.onSubmitted,
  });

  final ApiClient api;
  final Merchant? existing; // 非空 = 被驳回后重新提交(全部回填,不走草稿)
  final VoidCallback onSubmitted;

  @override
  State<ApplyShopPage> createState() => _ApplyShopPageState();
}

class _ApplyShopPageState extends State<ApplyShopPage> {
  int _step = 0;
  static const _stepTitles = ['选择业态', '门店信息', '资质证照'];

  // ---- 表单状态(驳回重提时全部回填,少填一遍是一遍) ----
  late final _name = TextEditingController(text: widget.existing?.name ?? '');
  late final _description =
      TextEditingController(text: widget.existing?.description ?? '');
  late final _address =
      TextEditingController(text: widget.existing?.address ?? '');
  late final _licenseNo =
      TextEditingController(text: widget.existing?.licenseNo ?? '');
  late String _category = widget.existing?.category ?? 'fast_food';
  // 堂食标识(#187):unknown 未填报 / yes 有堂食 / no 无堂食。
  // 初值取服务端已填的,新申请是 unknown —— 不预设成「有堂食」
  late String _dineInStatus = widget.existing?.dineInStatus ?? 'unknown';
  // 业态:第一步选择,决定后续收哪些证照(重新提交时沿用原业态)
  late String _bizType = widget.existing?.bizType ?? 'food';
  late String _licenseImageUrl = widget.existing?.licenseImageUrl ?? '';
  bool _busy = false;

  // 酒店专属
  final _frontDeskPhone = TextEditingController();
  late final _specialLicenseNo =
      TextEditingController(text: widget.existing?.specialLicenseNo ?? '');
  String _tier = 'economy';
  late String _specialLicenseImageUrl =
      widget.existing?.specialLicenseImageUrl ?? '';
  late String _hygieneImageUrl = widget.existing?.hygieneImageUrl ?? '';

  /// 店铺坐标。**入驻必须在地图上选**:附近商家搜索按坐标算,
  /// 不标或标错,这家店对周边用户是隐形的。编辑已有店铺时回填原坐标。
  late double? _lat = widget.existing?.lat;
  late double? _lng = widget.existing?.lng;

  bool get _isHotel => _bizType == 'hotel';
  bool get _rejected => widget.existing?.isRejected == true;

  /// POI 搜索限城市(不限的话搜「一号店」会返回全国同名地点)。
  /// 优先级与用户端**共用同一份** CityPref.resolve:
  /// 记住的选择 > 定位解析 > 留空让他自己选。
  /// 留空时切换器显示「选择城市」—— 不猜一个填进去
  String _city = '';

  @override
  void initState() {
    super.initState();
    if (widget.existing == null) _restoreDraft();
    _initCity();
  }

  /// 当前位置。先要权限再取 —— 直接取会在没授权时静默失败,
  /// 点了没反应用户只会以为卡了
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
    // 商家端没装定位插件,只读记住的城市;没记过就留空让他自己选。
    // 老板开店时人多半就在店里,但"多半"不足以拿来猜一个城市填上
    final city = await CityPref.resolve();
    if (city.isNotEmpty && mounted) setState(() => _city = city);
  }

  @override
  void dispose() {
    for (final c in [
      _name, _description, _address, _licenseNo, _frontDeskPhone,
      _specialLicenseNo,
    ]) {
      c.dispose();
    }
    super.dispose();
  }

  // ---- 草稿:中途退出不丢进度(仅新申请;驳回重提以服务端数据为准) ----

  Future<void> _restoreDraft() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_kDraftKey);
    if (raw == null || !mounted) return;
    try {
      final d = jsonDecode(raw) as Map<String, dynamic>;
      setState(() {
        _step = (d['step'] as int? ?? 0).clamp(0, 2);
        _bizType = d['biz_type'] as String? ?? 'food';
        _category = d['category'] as String? ?? 'fast_food';
        _dineInStatus = d['dine_in_status'] as String? ?? 'unknown';
        _tier = d['tier'] as String? ?? 'economy';
        _name.text = d['name'] as String? ?? '';
        _description.text = d['description'] as String? ?? '';
        _address.text = d['address'] as String? ?? '';
        _frontDeskPhone.text = d['front_desk_phone'] as String? ?? '';
        _licenseNo.text = d['license_no'] as String? ?? '';
        _licenseImageUrl = d['license_image_url'] as String? ?? '';
        _specialLicenseNo.text = d['special_license_no'] as String? ?? '';
        _specialLicenseImageUrl =
            d['special_license_image_url'] as String? ?? '';
        _hygieneImageUrl = d['hygiene_image_url'] as String? ?? '';
        _lat = d['lat'] as double?;
        _lng = d['lng'] as double?;
      });
    } catch (_) {/* 草稿坏了就当没有 */}
  }

  Future<void> _saveDraft() async {
    if (widget.existing != null) return;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kDraftKey, jsonEncode({
      'step': _step,
      'biz_type': _bizType,
      'category': _category,
      'dine_in_status': _dineInStatus,
      'tier': _tier,
      'name': _name.text,
      'description': _description.text,
      'address': _address.text,
      'front_desk_phone': _frontDeskPhone.text,
      'license_no': _licenseNo.text,
      'license_image_url': _licenseImageUrl,
      'special_license_no': _specialLicenseNo.text,
      'special_license_image_url': _specialLicenseImageUrl,
      'hygiene_image_url': _hygieneImageUrl,
      'lat': _lat,
      'lng': _lng,
    }));
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  // ---- 步骤校验与流转 ----

  String? _validateStep(int step) {
    if (step == 1) {
      if (_name.text.trim().isEmpty) return _isHotel ? '请填写酒店名称' : '请填写店铺名称';
      if (_address.text.trim().isEmpty) return '请填写门店地址';
      if (_lat == null) return '请在地图上标出店铺位置——用户按坐标搜附近的店,标错就没人看得到你';
    }
    if (step == 2) {
      final licenseLabel = _isHotel ? '营业执照注册号' : '食品经营许可证号';
      if (_licenseNo.text.trim().isEmpty) return '请填写$licenseLabel';
      if (_licenseImageUrl.isEmpty) return '请上传$licenseLabel照片(监管要求)';
      if (_isHotel) {
        if (_specialLicenseNo.text.trim().isEmpty) {
          return '请填写特种行业许可证号(旅馆业,公安核发)';
        }
        if (_specialLicenseImageUrl.isEmpty) return '请上传特种行业许可证照片';
      }
    }
    return null;
  }

  void _next() {
    final error = _validateStep(_step);
    if (error != null) {
      _toast(error);
      return;
    }
    setState(() => _step += 1);
    _saveDraft();
  }

  void _back() {
    setState(() => _step -= 1);
    _saveDraft();
  }

  Future<void> _pickShopSpot() async {
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
          // 搜索:打个店名直接跳过去,不用把地图从市中心一路拖到自己店门口。
          // 之前这一条只有用户端有 —— 搜索做在了用户端那一页上,
          // 而不是做在共享的选点组件里,商家端就只剩"拖地图"
          onSearch: (kw) => widget.api.geoTips(kw, city: _city),
          city: _city,
          onCities: widget.api.openCities,
          onCityChanged: (c) => setState(() => _city = c),
          // 老板填店址时多半就站在店里,一键定位比拖地图准得多
          onLocate: _currentPosition,
        ),
      ),
    );
    if (picked == null || !mounted) return;
    setState(() {
      _lat = picked.lat;
      _lng = picked.lng;
      // 地址框空着就用反查结果填上,已经写了就不覆盖 ——
      // 商家写的往往比反查更准(带门牌号)
      if (_address.text.trim().isEmpty && picked.name.isNotEmpty) {
        _address.text = picked.name;
      }
    });
    _saveDraft();
  }

  /// OCR 识别结果回填:只填**还空着**的框,绝不覆盖商家手输的内容
  void _fillFromOcr(Map<String, dynamic> fields,
      {required TextEditingController numberField, bool fillName = false}) {
    var filled = false;
    final no = (fields['license_no'] as String? ?? '').trim();
    if (no.isNotEmpty && numberField.text.trim().isEmpty) {
      numberField.text = no;
      filled = true;
    }
    final name = (fields['name'] as String? ?? '').trim();
    if (fillName && name.isNotEmpty && _name.text.trim().isEmpty) {
      _name.text = name;
      filled = true;
    }
    if (filled) {
      _toast('已自动填入证照识别结果,请核对');
      _saveDraft();
    }
  }

  Future<void> _submit() async {
    final error = _validateStep(2);
    if (error != null) {
      _toast(error);
      return;
    }
    setState(() => _busy = true);
    try {
      if (widget.existing == null) {
        await widget.api.applyShop(
          name: _name.text.trim(),
          description: _description.text.trim(),
          address: _address.text.trim(),
          lat: _lat!,
          lng: _lng!,
          licenseNo: _licenseNo.text.trim(),
          licenseImageUrl: _licenseImageUrl,
          category: _category,
          bizType: _bizType,
          // 堂食标识随入驻一起提交,不再补一发 PATCH
          dineInStatus: _isHotel ? 'unknown' : _dineInStatus,
          hotel: _isHotel
              ? {
                  'tier': _tier,
                  'front_desk_phone': _frontDeskPhone.text.trim(),
                  'special_license_no': _specialLicenseNo.text.trim(),
                  'special_license_image_url': _specialLicenseImageUrl,
                  if (_hygieneImageUrl.isNotEmpty)
                    'hygiene_image_url': _hygieneImageUrl,
                }
              : null,
        );
        await clearApplyDraft();
      } else {
        await widget.api.updateShop({
          'name': _name.text.trim(),
          'description': _description.text.trim(),
          'address': _address.text.trim(),
          'license_no': _licenseNo.text.trim(),
          'license_image_url': _licenseImageUrl,
          if (!_isHotel) ...{
            'category': _category,
            'dine_in_status': _dineInStatus,
          },
          // 酒店的第二证照也要随重提更新,否则商家改了等于白改
          if (_isHotel) ...{
            'special_license_no': _specialLicenseNo.text.trim(),
            'special_license_image_url': _specialLicenseImageUrl,
            if (_hygieneImageUrl.isNotEmpty)
              'hygiene_image_url': _hygieneImageUrl,
          },
        });
      }
      if (!mounted) return;
      // 从引导页 push 进来的,提交成功要先退回去,ShopGate 刷新后接管路由
      Navigator.of(context).popUntil((route) => route.isFirst);
      widget.onSubmitted();
    } catch (e) {
      if (!mounted) return;
      _toast(e is ApiException ? e.message : e.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ---- UI ----

  Widget _stepIndicator() {
    final scheme = Theme.of(context).colorScheme;
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(children: [
        for (var i = 0; i < _stepTitles.length; i++) ...[
          if (i > 0)
            Expanded(
              child: Container(
                height: 2,
                margin: const EdgeInsets.symmetric(horizontal: 6),
                color: i <= _step ? scheme.primary : sz.line,
              ),
            ),
          Column(mainAxisSize: MainAxisSize.min, children: [
            Container(
              width: 24,
              height: 24,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: i <= _step ? scheme.primary : sz.line,
              ),
              child: i < _step
                  ? const Icon(Icons.check, size: 14, color: Colors.white)
                  : Text('${i + 1}',
                      style: TextStyle(
                          fontSize: 12,
                          color: i <= _step ? Colors.white : sz.inkMuted)),
            ),
            const SizedBox(height: 4),
            Text(_stepTitles[i],
                style: TextStyle(
                    fontSize: 11,
                    fontWeight:
                        i == _step ? FontWeight.w600 : FontWeight.w400,
                    color: i == _step ? scheme.primary : sz.inkMuted)),
          ]),
        ],
      ]),
    );
  }

  /// 业态选择卡(仅首次入驻可选;重新提交沿用原业态)
  Widget _bizTypeCard(
      String value, IconData icon, String title, String promise) {
    final selected = _bizType == value;
    final scheme = Theme.of(context).colorScheme;
    return Expanded(
      child: InkWell(
        onTap: widget.existing != null
            ? null
            : () {
                setState(() => _bizType = value);
                _saveDraft();
              },
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 8),
          decoration: BoxDecoration(
            border: Border.all(
                color: selected ? scheme.primary : scheme.outlineVariant,
                width: selected ? 2 : 1),
            borderRadius: BorderRadius.circular(12),
            color: selected ? scheme.primary.withValues(alpha: 0.06) : null,
          ),
          child: Column(children: [
            Icon(icon,
                size: 32, color: selected ? scheme.primary : scheme.outline),
            const SizedBox(height: 8),
            Text(title,
                style: TextStyle(
                    fontWeight: FontWeight.bold,
                    color: selected ? scheme.primary : null)),
            const SizedBox(height: 4),
            Text(promise,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall),
          ]),
        ),
      ),
    );
  }

  List<Widget> _stepBizType() {
    return [
      Text('选择经营业态', style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 4),
      Text('业态决定需要提交哪些证照,提交后不可更改',
          style: TextStyle(
              fontSize: 12, color: Theme.of(context).sz.inkMuted)),
      const SizedBox(height: 12),
      Row(children: [
        _bizTypeCard('food', Icons.restaurant, '餐饮外卖', '佣金 5% 封顶\n配送费全归骑手'),
        const SizedBox(width: 12),
        _bizTypeCard('hotel', Icons.hotel, '酒店住宿', '佣金 5%,离店才收\n取消分文不收'),
      ]),
      const SizedBox(height: 16),
      if (!_isHotel)
        // 外卖品类:决定出现在用户端哪个分类,入驻后可随时改
        DropdownButtonFormField<String>(
          initialValue: _category,
          decoration: const InputDecoration(
              labelText: '外卖品类 *', border: OutlineInputBorder()),
          items: [
            for (final e in kMerchantCategories.entries)
              DropdownMenuItem(
                  value: e.key,
                  child:
                      Text('${kMerchantCategoryEmoji[e.key] ?? ''} ${e.value}')),
          ],
          onChanged: (v) {
            setState(() => _category = v ?? 'fast_food');
            _saveDraft();
          },
        )
      else
        DropdownButtonFormField<String>(
          initialValue: _tier,
          decoration: const InputDecoration(
              labelText: '酒店档次 *', border: OutlineInputBorder()),
          items: [
            for (final e in kHotelTiers.entries)
              DropdownMenuItem(value: e.key, child: Text(e.value)),
          ],
          onChanged: (v) {
            setState(() => _tier = v ?? 'economy');
            _saveDraft();
          },
        ),
    ];
  }

  List<Widget> _stepShopInfo() {
    final sz = Theme.of(context).sz;
    return [
      Text('门店信息', style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 12),
      TextField(
          controller: _name,
          decoration: InputDecoration(
              labelText: _isHotel ? '酒店名称 *' : '店铺名称 *',
              border: const OutlineInputBorder())),
      const SizedBox(height: 12),
      TextField(
          controller: _description,
          decoration: const InputDecoration(
              labelText: '一句话介绍', border: OutlineInputBorder())),
      const SizedBox(height: 12),
      TextField(
          controller: _address,
          decoration: InputDecoration(
              labelText: _isHotel ? '酒店地址 *' : '门店地址 *',
              border: const OutlineInputBorder())),
      const SizedBox(height: 6),
      // 文字地址给人看,坐标给系统算 —— 两者都要。
      // 入驻时必须自己标;入驻后**不给自助改**:坐标决定谁能搜到这家店,
      // 自助改等于绕过审核把自己挪到人流密集区。要挪店走客服重审。
      if (widget.existing == null)
        Row(children: [
          Expanded(
            child: Text(
              _lat == null
                  ? '还没标位置:用户按坐标搜附近的店'
                  : '已标位置 ${_lat!.toStringAsFixed(5)},'
                      '${_lng!.toStringAsFixed(5)}',
              style: TextStyle(
                  fontSize: 12,
                  color: _lat == null ? sz.danger : sz.earn),
            ),
          ),
          TextButton.icon(
            icon: const Icon(Icons.map_outlined, size: 18),
            label: Text(_lat == null ? '在地图上标位置 *' : '重新标'),
            onPressed: _pickShopSpot,
          ),
        ])
      else
        Text(
          _lat == null
              ? '本店尚未标定位置,请联系客服补录'
              : '店铺位置 ${_lat!.toStringAsFixed(5)},'
                  '${_lng!.toStringAsFixed(5)}(如需迁址请联系客服)',
          style: TextStyle(fontSize: 12, color: sz.inkMuted),
        ),
      if (_isHotel) ...[
        const SizedBox(height: 12),
        TextField(
            controller: _frontDeskPhone,
            keyboardType: TextInputType.phone,
            decoration: const InputDecoration(
                labelText: '前台电话',
                helperText: '展示给已下单的住客,方便到店联系',
                border: OutlineInputBorder())),
      ],
      // 堂食标识(#187,总局令第 123 号第十二条):入驻时就问,
      // 免得开业第一天列表上就挂着「未填报」。
      // **预选的是「未填报」而不是「有堂食」**:大半人会顺手划过默认项,
      // 预选一个业务值等于让平台替他公示了一条没人核实过的信息。
      // 也因此不设成必填 —— 未填报是个如实的状态,不是待补的空
      if (!_isHotel) ...[
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _dineInStatus,
          decoration: const InputDecoration(
              labelText: '堂食标识',
              helperText: '监管要求公示,会显示在用户端列表和店铺页;'
                  '现在不填之后也能在「店铺」页改',
              helperMaxLines: 3,
              border: OutlineInputBorder()),
          items: const [
            DropdownMenuItem(value: 'unknown', child: Text('未填报')),
            DropdownMenuItem(value: 'yes', child: Text('有堂食(店里有餐位)')),
            DropdownMenuItem(value: 'no', child: Text('无堂食(只做外卖/自取)')),
          ],
          onChanged: (v) {
            setState(() => _dineInStatus = v ?? 'unknown');
            _saveDraft();
          },
        ),
      ],
    ];
  }

  List<Widget> _stepLicenses() {
    return [
      Text('资质证照', style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 4),
      Text('平台人工核对,信息不实将无法通过审核',
          style:
              TextStyle(fontSize: 12, color: Theme.of(context).sz.inkMuted)),
      const SizedBox(height: 12),
      TextField(
          controller: _licenseNo,
          decoration: InputDecoration(
              labelText: _isHotel ? '营业执照注册号 *' : '食品经营许可证号 *',
              helperText: '先传照片可自动识别填入,再核对一遍即可',
              border: const OutlineInputBorder())),
      const SizedBox(height: 12),
      // 证照照片(监管要求留存影像,审核员对照证号人工核验)
      LicenseUploadField(
        api: widget.api,
        label: _isHotel ? '上传营业执照照片 *' : '上传食品经营许可证照片 *',
        url: _licenseImageUrl,
        onUploaded: (u) {
          setState(() => _licenseImageUrl = u);
          _saveDraft();
        },
        onOcr: (f) =>
            _fillFromOcr(f, numberField: _licenseNo, fillName: true),
      ),
      if (_isHotel) ...[
        const SizedBox(height: 16),
        TextField(
            controller: _specialLicenseNo,
            decoration: const InputDecoration(
                labelText: '特种行业许可证号(旅馆业) *',
                helperText: '公安机关核发,开旅馆的硬性资质',
                border: OutlineInputBorder())),
        const SizedBox(height: 12),
        LicenseUploadField(
          api: widget.api,
          label: '上传特种行业许可证照片 *',
          url: _specialLicenseImageUrl,
          onUploaded: (u) {
            setState(() => _specialLicenseImageUrl = u);
            _saveDraft();
          },
          onOcr: (f) => _fillFromOcr(f, numberField: _specialLicenseNo),
        ),
        const SizedBox(height: 16),
        LicenseUploadField(
          api: widget.api,
          label: '上传卫生许可证照片(选填)',
          url: _hygieneImageUrl,
          onUploaded: (u) {
            setState(() => _hygieneImageUrl = u);
            _saveDraft();
          },
        ),
      ],
    ];
  }

  @override
  Widget build(BuildContext context) {
    final steps = switch (_step) {
      0 => _stepBizType(),
      1 => _stepShopInfo(),
      _ => _stepLicenses(),
    };
    return PopScope(
      // 随时可退:进度已存草稿,不弹「会丢掉」的拦截框吓人
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) _saveDraft();
      },
      child: Scaffold(
        appBar: AppBar(title: Text(_rejected ? '修改重新提交' : '申请入驻')),
        body: Column(children: [
          if (_rejected)
            Container(
              width: double.infinity,
              color: Theme.of(context).colorScheme.errorContainer,
              padding: const EdgeInsets.all(12),
              child: Text('上次申请被驳回:${widget.existing!.rejectReason}\n'
                  '已填内容都保留着,只改需要改的就行'),
            ),
          _stepIndicator(),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
              children: steps,
            ),
          ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: Row(children: [
                if (_step > 0)
                  OutlinedButton(onPressed: _busy ? null : _back, child: const Text('上一步')),
                const Spacer(),
                if (_step < 2)
                  FilledButton(onPressed: _next, child: const Text('下一步'))
                else
                  FilledButton(
                    onPressed: _busy ? null : _submit,
                    child: Text(_busy
                        ? '提交中…'
                        : (_rejected ? '重新提交审核' : '提交申请')),
                  ),
              ]),
            ),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 3. 审核进度页
// ---------------------------------------------------------------------------

class PendingReviewPage extends StatelessWidget {
  const PendingReviewPage({super.key, required this.api, required this.shop});

  final ApiClient api;
  final Merchant shop;

  Widget _node(BuildContext context,
      {required IconData icon,
      required String title,
      required String detail,
      required int state, // 0=已完成 1=进行中 2=未开始
      bool last = false}) {
    final sz = Theme.of(context).sz;
    final scheme = Theme.of(context).colorScheme;
    final color = switch (state) {
      0 => sz.earn,
      1 => scheme.primary,
      _ => sz.inkFaint,
    };
    return IntrinsicHeight(
      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Column(children: [
          Icon(state == 0 ? Icons.check_circle : icon, size: 24, color: color),
          if (!last)
            Expanded(
                child: Container(
                    width: 2,
                    margin: const EdgeInsets.symmetric(vertical: 2),
                    color: state == 0 ? sz.earn : sz.line)),
        ]),
        const SizedBox(width: 12),
        Expanded(
          child: Padding(
            padding: EdgeInsets.only(bottom: last ? 0 : 20),
            child:
                Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title,
                  style: TextStyle(
                      fontWeight: FontWeight.w600,
                      color: state == 2 ? sz.inkMuted : sz.ink)),
              const SizedBox(height: 2),
              Text(detail,
                  style: TextStyle(fontSize: 12, color: sz.inkMuted)),
            ]),
          ),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Scaffold(
      appBar: AppBar(title: const Text('入驻审核中')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const SizedBox(height: 8),
          Text('「${shop.name}」',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 24),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(children: [
                _node(context,
                    icon: Icons.upload_file,
                    title: '提交申请',
                    detail: '资料已收到',
                    state: 0),
                _node(context,
                    icon: Icons.manage_search,
                    title: '平台人工审核',
                    detail: shop.bizType == 'hotel'
                        ? '正在核对营业执照与特种行业许可证,通常 1-3 个工作日'
                        : '正在核对食品经营许可证,通常 1-3 个工作日',
                    state: 1),
                _node(context,
                    icon: Icons.storefront,
                    title: '审核通过,开门营业',
                    detail: '通过后自动进入工作台,可以先准备菜单和定价',
                    state: 2,
                    last: true),
              ]),
            ),
          ),
          const SizedBox(height: 12),
          Text('审核结果会自动刷新,不用一直守着这个页面',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: sz.inkMuted)),
          const SizedBox(height: 16),
          Center(
            child: TextButton.icon(
              icon: const Icon(Icons.support_agent, size: 18),
              label: const Text('有疑问?联系客服'),
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => SupportPage(api: api))),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// 4. 驳回页
// ---------------------------------------------------------------------------

class RejectedShopPage extends StatelessWidget {
  const RejectedShopPage({
    super.key,
    required this.api,
    required this.shop,
    required this.onSubmitted,
  });

  final ApiClient api;
  final Merchant shop;
  final VoidCallback onSubmitted;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Scaffold(
      appBar: AppBar(title: const Text('入驻申请被驳回')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const SizedBox(height: 8),
          Icon(Icons.assignment_late_outlined, size: 56, color: sz.danger),
          const SizedBox(height: 12),
          Text('「${shop.name}」未通过审核',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          Card(
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('驳回原因',
                        style: TextStyle(fontWeight: FontWeight.w600)),
                    const SizedBox(height: 6),
                    Text(shop.rejectReason.isEmpty
                        ? '证照信息无法核实'
                        : shop.rejectReason),
                  ]),
            ),
          ),
          const SizedBox(height: 12),
          Text('之前填的内容都保留着,修改对应的项目重新提交即可',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: sz.inkMuted)),
          const SizedBox(height: 16),
          FilledButton(
            style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 14)),
            onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                builder: (_) => ApplyShopPage(
                    api: api, existing: shop, onSubmitted: onSubmitted))),
            child: const Text('修改后重新提交'),
          ),
          const SizedBox(height: 8),
          Center(
            child: TextButton.icon(
              icon: const Icon(Icons.support_agent, size: 18),
              label: const Text('对结果有异议?联系客服'),
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => SupportPage(api: api))),
            ),
          ),
        ],
      ),
    );
  }
}
