import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';

import 'appeal_page.dart';
import 'printer_page.dart';
import 'voucher_manage_page.dart';

/// 店铺 Tab:门头照、公告编辑、评价管理(查看 + 回复)。
class ShopTabPage extends StatefulWidget {
  const ShopTabPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<ShopTabPage> createState() => _ShopTabPageState();
}

class _ShopTabPageState extends State<ShopTabPage> {
  Merchant? _shop;
  List<Review> _reviews = [];
  List<AfterSale> _afterSales = [];
  List<Map<String, dynamic>> _shopCoupons = [];
  final _announcement = TextEditingController();
  bool _savingAnnouncement = false;
  bool _uploadingLogo = false;
  bool _uploadingPhoto = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final shop = await widget.api.myShop();
      final reviews = await widget.api.myReviews();
      final afterSales = await widget.api.myAfterSales(status: 'pending');
      List<Map<String, dynamic>> coupons = _shopCoupons;
      try {
        coupons = await widget.api.myShopCouponBatches();
      } catch (_) {}
      if (mounted) {
        setState(() {
          _shop = shop;
          _reviews = reviews;
          _afterSales = afterSales;
          _shopCoupons = coupons;
          if (_announcement.text.isEmpty) {
            _announcement.text = shop?.announcement ?? '';
          }
        });
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _pickLogo() async {
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 512, imageQuality: 85);
    if (picked == null) return;
    setState(() => _uploadingLogo = true);
    try {
      final url = await widget.api
          .uploadImage(await picked.readAsBytes(), picked.name);
      await widget.api.updateShop({'logo_url': url});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _uploadingLogo = false);
    }
  }

  Future<void> _addShopPhoto() async {
    final shop = _shop;
    if (shop == null || shop.photoUrls.length >= 9) return;
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 1280, imageQuality: 85);
    if (picked == null) return;
    setState(() => _uploadingPhoto = true);
    try {
      final url = await widget.api
          .uploadImage(await picked.readAsBytes(), picked.name);
      await widget.api
          .updateShop({'photo_urls': [...shop.photoUrls, url]});
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _uploadingPhoto = false);
    }
  }

  Future<void> _removeShopPhoto(String url) async {
    final shop = _shop;
    if (shop == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这张照片?'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('删除')),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await widget.api.updateShop(
          {'photo_urls': shop.photoUrls.where((u) => u != url).toList()});
      await _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _saveAnnouncement() async {
    setState(() => _savingAnnouncement = true);
    try {
      await widget.api.updateShop({'announcement': _announcement.text.trim()});
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('公告已更新')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _savingAnnouncement = false);
    }
  }

  Future<void> _pickTime(bool isOpenTime) async {
    final shop = _shop!;
    final current = isOpenTime ? shop.openTime : shop.closeTime;
    TimeOfDay initial = isOpenTime
        ? const TimeOfDay(hour: 9, minute: 0)
        : const TimeOfDay(hour: 21, minute: 0);
    if (current.contains(':')) {
      final parts = current.split(':');
      initial = TimeOfDay(
          hour: int.parse(parts[0]), minute: int.parse(parts[1]));
    }
    final picked = await showTimePicker(context: context, initialTime: initial);
    if (picked == null) return;
    final hhmm =
        '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}';
    try {
      await widget.api
          .updateShop({isOpenTime ? 'open_time' : 'close_time': hhmm});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _clearTimes() async {
    try {
      await widget.api.updateShop({'open_time': '', 'close_time': ''});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 外卖品类:底部弹层选择,选了即改(不是资质项,即时生效)
  Future<void> _editCategory() async {
    final shop = _shop!;
    final picked = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) => ListView(
        children: [
          for (final entry in kMerchantCategories.entries)
            ListTile(
              leading: Text(kMerchantCategoryEmoji[entry.key] ?? '',
                  style: const TextStyle(fontSize: 22)),
              title: Text(entry.value),
              trailing: shop.category == entry.key
                  ? const Icon(Icons.check, color: Colors.orange)
                  : null,
              onTap: () => Navigator.pop(context, entry.key),
            ),
        ],
      ),
    );
    if (picked == null || picked == shop.category || !mounted) return;
    try {
      await widget.api.updateShop({'category': picked});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 承诺出餐时长(5-60 分钟)
  Future<void> _editPromiseMinutes() async {
    final shop = _shop!;
    final controller =
        TextEditingController(text: '${shop.promiseReadyMinutes}');
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('承诺出餐时长(分钟)'),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.number,
          decoration: const InputDecoration(
              helperText: '5-60 分钟;定得实在比定得短更重要',
              border: OutlineInputBorder()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('保存')),
        ],
      ),
    );
    if (saved != true || !mounted) return;
    final minutes = int.tryParse(controller.text.trim());
    if (minutes == null || minutes < 5 || minutes > 60) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请输入 5~60 之间的分钟数')));
      return;
    }
    try {
      await widget.api.updateShop({'promise_ready_minutes': minutes});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 编辑金额类设置(起送价/打包费),输入以元为单位,存储为分。
  Future<void> _editAmount(String label, int currentCents, String field) async {
    final controller = TextEditingController(
        text: currentCents > 0 ? (currentCents / 100).toStringAsFixed(
            currentCents % 100 == 0 ? 0 : 2) : '');
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(label),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(
              prefixText: '¥ ', border: OutlineInputBorder()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('保存')),
        ],
      ),
    );
    if (saved != true || !mounted) return;
    final val = double.tryParse(controller.text.trim());
    if (val == null || val < 0 || val > 1000) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请输入 0~1000 之间的金额')));
      return;
    }
    try {
      await widget.api.updateShop({field: (val * 100).round()});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 满减规则编辑:最多 3 档,每档「满 X 减 Y」。
  Future<void> _editPromoRules() async {
    final shop = _shop!;
    final rows = shop.promoRules
        .map((r) => (
              threshold: TextEditingController(
                  text: '${r.thresholdCents ~/ 100}'),
              off: TextEditingController(
                  text: (r.offCents / 100).toStringAsFixed(
                      r.offCents % 100 == 0 ? 0 : 2)),
            ))
        .toList();
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialog) => AlertDialog(
          title: const Text('满减活动(最多 3 档)'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (var i = 0; i < rows.length; i++)
                Row(
                  children: [
                    const Text('满'),
                    SizedBox(
                      width: 72,
                      child: TextField(
                          controller: rows[i].threshold,
                          keyboardType: TextInputType.number,
                          textAlign: TextAlign.center),
                    ),
                    const Text('元 减'),
                    SizedBox(
                      width: 72,
                      child: TextField(
                          controller: rows[i].off,
                          keyboardType: const TextInputType
                              .numberWithOptions(decimal: true),
                          textAlign: TextAlign.center),
                    ),
                    const Text('元'),
                    IconButton(
                      icon: const Icon(Icons.remove_circle_outline),
                      onPressed: () => setDialog(() => rows.removeAt(i)),
                    ),
                  ],
                ),
              if (rows.length < 3)
                TextButton.icon(
                  icon: const Icon(Icons.add),
                  label: const Text('加一档'),
                  onPressed: () => setDialog(() => rows.add((
                        threshold: TextEditingController(),
                        off: TextEditingController(),
                      ))),
                ),
              const Text('成本商家承担;平台按满减后的实收计服务费',
                  style: TextStyle(fontSize: 12)),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('保存')),
          ],
        ),
      ),
    );
    if (saved != true || !mounted) return;
    final rules = <Map<String, dynamic>>[];
    for (final row in rows) {
      final threshold = double.tryParse(row.threshold.text.trim());
      final off = double.tryParse(row.off.text.trim());
      if (threshold == null || off == null || threshold <= 0 || off <= 0) {
        continue; // 空行/无效行直接忽略
      }
      if (off >= threshold) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('减的金额必须小于门槛(不能倒贴)')));
        return;
      }
      rules.add({
        'threshold_cents': (threshold * 100).round(),
        'off_cents': (off * 100).round(),
      });
    }
    try {
      await widget.api.updateShop({'promo_rules': rules});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  String _hhmmLocal(DateTime utc) {
    final t = utc.toLocal();
    return '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }

  /// 临时歇业:关店 + 到点自动恢复(区别于手动关店忘了开)
  Future<void> _rest({int? hours, bool untilClose = false}) async {
    try {
      final shop = await widget.api.restShop(
          hours: hours, untilClose: untilClose);
      _load();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(
              '已歇业,${_hhmmLocal(shop.closedUntil!)} 自动恢复营业')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 提前结束歇业 = 直接开店(服务端开店动作会清歇业标记)
  Future<void> _endRest() async {
    try {
      await widget.api.updateShop({'is_open': true});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  static String _shortDate(String ymd) =>
      ymd.length >= 10 ? '${int.parse(ymd.substring(5, 7))}/${int.parse(ymd.substring(8, 10))}' : ymd;

  String _planLabel(Map<String, dynamic> p) {
    final from = p['from'] as String? ?? '';
    final to = (p['to'] as String?)?.isNotEmpty == true ? p['to'] as String : from;
    final range = from == to
        ? _shortDate(from)
        : '${_shortDate(from)}~${_shortDate(to)}';
    return (p['closed'] as bool? ?? true)
        ? '$range 歇业'
        : '$range ${p['open']}-${p['close']}';
  }

  static String _ymd(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  /// 节假日计划管理:歇业区间 / 单日特殊时段,最多 20 条,过期自动清理
  Future<void> _editHolidayPlans() async {
    final plans = [
      for (final p in _shop!.holidayPlans) Map<String, dynamic>.from(p)
    ];
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialog) => AlertDialog(
          title: const Text('节假日计划'),
          content: SizedBox(
            width: double.maxFinite,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (plans.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 8),
                    child: Text('暂无计划。春节歇业、除夕只开半天,都在这里提前设置。',
                        style: TextStyle(fontSize: 13)),
                  ),
                for (var i = 0; i < plans.length; i++)
                  Row(children: [
                    Expanded(child: Text(_planLabel(plans[i]))),
                    IconButton(
                      icon: const Icon(Icons.delete_outline, size: 20),
                      onPressed: () => setDialog(() => plans.removeAt(i)),
                    ),
                  ]),
                const SizedBox(height: 4),
                if (plans.length < 20)
                  Row(children: [
                    TextButton.icon(
                      icon: const Icon(Icons.event_busy, size: 18),
                      label: const Text('加歇业'),
                      onPressed: () async {
                        final now = DateTime.now();
                        final range = await showDateRangePicker(
                          context: context,
                          firstDate: now,
                          lastDate: now.add(const Duration(days: 365)),
                        );
                        if (range == null) return;
                        setDialog(() => plans.add({
                              'from': _ymd(range.start),
                              'to': _ymd(range.end),
                              'closed': true,
                            }));
                      },
                    ),
                    TextButton.icon(
                      icon: const Icon(Icons.schedule, size: 18),
                      label: const Text('加特殊时段'),
                      onPressed: () async {
                        final now = DateTime.now();
                        final date = await showDatePicker(
                          context: context,
                          firstDate: now,
                          lastDate: now.add(const Duration(days: 365)),
                        );
                        if (date == null || !context.mounted) return;
                        final open = await showTimePicker(
                            context: context,
                            initialTime:
                                const TimeOfDay(hour: 10, minute: 0),
                            helpText: '当日开店时间');
                        if (open == null || !context.mounted) return;
                        final close = await showTimePicker(
                            context: context,
                            initialTime:
                                const TimeOfDay(hour: 15, minute: 0),
                            helpText: '当日打烊时间');
                        if (close == null) return;
                        String hhmm(TimeOfDay t) =>
                            '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
                        setDialog(() => plans.add({
                              'from': _ymd(date),
                              'to': _ymd(date),
                              'closed': false,
                              'open': hhmm(open),
                              'close': hhmm(close),
                            }));
                      },
                    ),
                  ]),
              ],
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('保存')),
          ],
        ),
      ),
    );
    if (saved != true || !mounted) return;
    try {
      await widget.api.updateShop({'holiday_plans': plans});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 子账号管理:列出店员 + 按手机号添加 + 移除(仅店主)
  Future<void> _manageStaff() async {
    List<Map<String, dynamic>> staff = [];
    try {
      staff = await widget.api.myStaff();
    } catch (_) {}
    if (!mounted) return;
    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (context) => StatefulBuilder(
        builder: (context, setSheet) => SafeArea(
          child: Padding(
            padding: EdgeInsets.only(
                left: 16, right: 16, top: 16,
                bottom: MediaQuery.of(context).viewInsets.bottom + 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('子账号(店员)',
                    style: Theme.of(context).textTheme.titleMedium),
                const Text('店员能接单/出餐/估清,不能提现/改价/改设置。',
                    style: TextStyle(fontSize: 12, color: Colors.grey)),
                const SizedBox(height: 8),
                if (staff.isEmpty)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 8),
                    child: Text('还没有店员'),
                  ),
                for (final s in staff)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(s['name'] as String? ?? ''),
                    subtitle: Text(s['phone'] as String? ?? ''),
                    trailing: IconButton(
                      icon: const Icon(Icons.person_remove_outlined),
                      onPressed: () async {
                        final messenger = ScaffoldMessenger.of(context);
                        try {
                          await widget.api.removeStaff(s['user_id'] as int);
                          staff = await widget.api.myStaff();
                          setSheet(() {});
                        } catch (e) {
                          messenger.showSnackBar(
                              SnackBar(content: Text(e.toString())));
                        }
                      },
                    ),
                  ),
                const Divider(),
                FilledButton.icon(
                  icon: const Icon(Icons.person_add_alt),
                  label: const Text('添加店员'),
                  onPressed: () async {
                    final added = await _addStaffDialog();
                    if (added == true) {
                      staff = await widget.api.myStaff();
                      setSheet(() {});
                    }
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<bool?> _addStaffDialog() async {
    final phone = TextEditingController();
    final name = TextEditingController();
    return showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('添加店员'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
              controller: phone,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(
                  labelText: '手机号', helperText: '对方需先下载 App 登录一次')),
          TextField(
              controller: name,
              decoration: const InputDecoration(labelText: '备注名(如:小王)')),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
            onPressed: () async {
              final messenger = ScaffoldMessenger.of(context);
              final nav = Navigator.of(context);
              try {
                await widget.api
                    .addStaff(phone.text.trim(), name.text.trim());
                nav.pop(true);
              } catch (e) {
                messenger.showSnackBar(
                    SnackBar(content: Text(e.toString())));
              }
            },
            child: const Text('添加'),
          ),
        ],
      ),
    );
  }

  /// 店铺券管理:列出已有批次(启停)+ 新建券
  Future<void> _manageShopCoupons() async {
    await showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (context) => StatefulBuilder(
        builder: (context, setSheet) => SafeArea(
          child: Padding(
            padding: EdgeInsets.only(
                left: 16, right: 16, top: 16,
                bottom: MediaQuery.of(context).viewInsets.bottom + 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('店铺券', style: Theme.of(context).textTheme.titleMedium),
                const Text('成本你自己出,用来引流拉复购。与满减二选其一取最优。',
                    style: TextStyle(fontSize: 12, color: Colors.grey)),
                const SizedBox(height: 8),
                for (final b in _shopCoupons)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    title: Text(
                        '满${b['threshold_cents'] ~/ 100}减${b['off_cents'] ~/ 100}'
                        ' · ${b['name']}'),
                    subtitle: Text('已领 ${b['issued']}/${b['total']}'
                        ' · 每人${b['per_user_limit']}张 · ${b['valid_days']}天'),
                    trailing: Switch(
                      value: b['active'] == true,
                      onChanged: (_) async {
                        final messenger = ScaffoldMessenger.of(context);
                        try {
                          await widget.api.toggleShopCouponBatch(b['id'] as int);
                          await _load();
                          setSheet(() {});
                        } catch (e) {
                          messenger.showSnackBar(
                              SnackBar(content: Text(e.toString())));
                        }
                      },
                    ),
                  ),
                const Divider(),
                FilledButton.icon(
                  icon: const Icon(Icons.add),
                  label: const Text('新建店铺券'),
                  onPressed: () async {
                    final ok = await _createShopCouponDialog();
                    if (ok == true) {
                      await _load();
                      setSheet(() {});
                    }
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<bool?> _createShopCouponDialog() async {
    final name = TextEditingController(text: '满减券');
    final threshold = TextEditingController();
    final off = TextEditingController();
    final total = TextEditingController(text: '100');
    final perUser = TextEditingController(text: '1');
    final validDays = TextEditingController(text: '7');
    return showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('新建店铺券'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(
                controller: name,
                decoration: const InputDecoration(labelText: '券名')),
            Row(children: [
              Expanded(
                child: TextField(
                    controller: threshold,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: '满(元,0无门槛)')),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                    controller: off,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: '减(元)')),
              ),
            ]),
            Row(children: [
              Expanded(
                child: TextField(
                    controller: total,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: '发行总量')),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                    controller: perUser,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: '每人限领')),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                    controller: validDays,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(labelText: '有效天数')),
              ),
            ]),
          ]),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
            onPressed: () async {
              final t = ((double.tryParse(threshold.text) ?? 0) * 100).round();
              final o = ((double.tryParse(off.text) ?? 0) * 100).round();
              final tot = int.tryParse(total.text) ?? 0;
              if (o <= 0 || tot <= 0 || (t > 0 && o >= t)) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                    content: Text('减额需>0且小于门槛,总量>0')));
                return;
              }
              try {
                await widget.api.createShopCouponBatch({
                  'name': name.text.trim(),
                  'threshold_cents': t,
                  'off_cents': o,
                  'total': tot,
                  'per_user_limit': int.tryParse(perUser.text) ?? 1,
                  'valid_days': int.tryParse(validDays.text) ?? 7,
                });
                if (context.mounted) Navigator.pop(context, true);
              } catch (e) {
                if (context.mounted) {
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(e.toString())));
                }
              }
            },
            child: const Text('发布'),
          ),
        ],
      ),
    );
  }

  /// 满赠规则编辑:最多 2 档,每档「满 X 元赠某菜 1 份」,赠品从本店在售菜里选。
  Future<void> _editGiftRules() async {
    final shop = _shop!;
    final List<Dish> dishes;
    try {
      dishes = (await widget.api.myDishes())
          .where((d) => d.isOnSale)
          .toList();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
      return;
    }
    if (!mounted) return;
    if (dishes.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('先上架菜品,才能选赠品')));
      return;
    }
    final dishIds = dishes.map((d) => d.id).toSet();
    final rows = shop.giftRules
        .map((r) => (
              threshold:
                  TextEditingController(text: '${r.thresholdCents ~/ 100}'),
              // 赠品菜已下架时置空,强制重选
              dishId: ValueNotifier<int?>(
                  dishIds.contains(r.dishId) ? r.dishId : null),
            ))
        .toList();
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialog) => AlertDialog(
          title: const Text('满赠活动(最多 2 档)'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (var i = 0; i < rows.length; i++)
                Row(
                  children: [
                    const Text('满'),
                    SizedBox(
                      width: 56,
                      child: TextField(
                          controller: rows[i].threshold,
                          keyboardType: TextInputType.number,
                          textAlign: TextAlign.center),
                    ),
                    const Text('元赠'),
                    const SizedBox(width: 4),
                    Expanded(
                      child: DropdownButton<int>(
                        isExpanded: true,
                        value: rows[i].dishId.value,
                        hint: const Text('选菜品'),
                        items: [
                          for (final d in dishes)
                            DropdownMenuItem(
                                value: d.id,
                                child: Text(d.name,
                                    overflow: TextOverflow.ellipsis)),
                        ],
                        onChanged: (v) =>
                            setDialog(() => rows[i].dishId.value = v),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.remove_circle_outline),
                      onPressed: () => setDialog(() => rows.removeAt(i)),
                    ),
                  ],
                ),
              if (rows.length < 2)
                TextButton.icon(
                  icon: const Icon(Icons.add),
                  label: const Text('加一档'),
                  onPressed: () => setDialog(() => rows.add((
                        threshold: TextEditingController(),
                        dishId: ValueNotifier<int?>(null),
                      ))),
                ),
              const Text('赠品照常扣库存,库存不足该档自动失效;与满减可同时生效',
                  style: TextStyle(fontSize: 12)),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('保存')),
          ],
        ),
      ),
    );
    if (saved != true || !mounted) return;
    final rules = <Map<String, dynamic>>[];
    for (final row in rows) {
      final threshold = double.tryParse(row.threshold.text.trim());
      final dishId = row.dishId.value;
      if (threshold == null || threshold <= 0 || dishId == null) {
        continue; // 空行/无效行直接忽略
      }
      rules.add({
        'threshold_cents': (threshold * 100).round(),
        'dish_id': dishId,
      });
    }
    try {
      await widget.api.updateShop({'gift_rules': rules});
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 处理售后:同意(退餐费,同意即认责从结算款扣)或拒绝,都必须给用户一句话回复
  Future<void> _processAfterSale(AfterSale sale, bool accept) async {
    final controller = TextEditingController(
        text: accept ? '非常抱歉给您带来不好的体验,已退您餐费' : '');
    final reply = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(accept ? '同意售后(退餐费,配送费已履约不退)' : '拒绝售后'),
        content: TextField(
          controller: controller,
          maxLength: 300,
          maxLines: 3,
          decoration: InputDecoration(
            labelText: '回复用户(必填)',
            hintText: accept ? '' : '说明拒绝原因,用户可向平台申诉',
            border: const OutlineInputBorder(),
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: Text(accept ? '确认退款' : '确认拒绝')),
        ],
      ),
    );
    if (reply == null || reply.length < 2) return;
    try {
      await widget.api.processAfterSale(sale.id, accept: accept, reply: reply);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(accept ? '已退款并回复用户' : '已拒绝并回复用户')));
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _reply(Review review) async {
    final controller = TextEditingController(text: review.reply);
    final text = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('回复评价'),
        content: TextField(
          controller: controller,
          maxLength: 300,
          maxLines: 3,
          decoration: const InputDecoration(
              hintText: '感谢惠顾,欢迎再来!', border: OutlineInputBorder()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: const Text('回复')),
        ],
      ),
    );
    if (text == null || text.isEmpty) return;
    try {
      await widget.api.replyReview(review.id, text);
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  String _stars(int n) => '★' * n + '☆' * (5 - n);

  @override
  Widget build(BuildContext context) {
    final shop = _shop;
    if (shop == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 店铺信息卡
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      InkWell(
                        onTap: _uploadingLogo ? null : _pickLogo,
                        borderRadius: BorderRadius.circular(32),
                        child: _uploadingLogo
                            ? const CircleAvatar(
                                radius: 32,
                                child: CircularProgressIndicator())
                            : shop.logoUrl.isEmpty
                                ? const CircleAvatar(
                                    radius: 32,
                                    child: Icon(Icons.add_a_photo))
                                : CircleAvatar(
                                    radius: 32,
                                    backgroundImage: NetworkImage(widget.api
                                        .resolveUrl(shop.logoUrl))),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(shop.name,
                                style:
                                    Theme.of(context).textTheme.titleLarge),
                            Text(shop.ratingLabel,
                                style: Theme.of(context).textTheme.bodySmall),
                            Text(shop.address,
                                style: Theme.of(context).textTheme.bodySmall),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _announcement,
                    maxLength: 200,
                    maxLines: 2,
                    decoration: const InputDecoration(
                        labelText: '店铺公告(显示在用户点单页顶部)',
                        border: OutlineInputBorder()),
                  ),
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton.tonal(
                      onPressed: _savingAnnouncement ? null : _saveAnnouncement,
                      child: Text(_savingAnnouncement ? '保存中…' : '保存公告'),
                    ),
                  ),
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('营业时间'),
                      const SizedBox(width: 12),
                      OutlinedButton(
                        onPressed: () => _pickTime(true),
                        child: Text(shop.openTime.isEmpty
                            ? '开店时间'
                            : shop.openTime),
                      ),
                      const Padding(
                          padding: EdgeInsets.symmetric(horizontal: 6),
                          child: Text('至')),
                      OutlinedButton(
                        onPressed: () => _pickTime(false),
                        child: Text(shop.closeTime.isEmpty
                            ? '打烊时间'
                            : shop.closeTime),
                      ),
                      const Spacer(),
                      if (shop.openTime.isNotEmpty || shop.closeTime.isNotEmpty)
                        TextButton(
                            onPressed: _clearTimes, child: const Text('清除')),
                    ],
                  ),
                  Text(
                    shop.openTime.isNotEmpty && shop.closeTime.isNotEmpty
                        ? '已开启自动开关店:${shop.openTime} 自动营业,${shop.closeTime} 自动打烊(临时手动开关不受影响)'
                        : '设置后到点自动开店/打烊;不设置则完全手动',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                  const SizedBox(height: 8),
                  // 临时歇业:到点自动恢复,区别于手动关店忘了开
                  if (shop.closedUntil != null &&
                      shop.closedUntil!.isAfter(DateTime.now().toUtc()))
                    Row(children: [
                      Expanded(
                        child: Text(
                          '歇业中,${_hhmmLocal(shop.closedUntil!)} 自动恢复营业',
                          style: const TextStyle(
                              color: Colors.orange,
                              fontWeight: FontWeight.bold),
                        ),
                      ),
                      FilledButton.tonal(
                          onPressed: () => _endRest(),
                          child: const Text('立即恢复')),
                    ])
                  else
                    Row(children: [
                      const Text('临时歇业'),
                      const SizedBox(width: 8),
                      OutlinedButton(
                          onPressed: () => _rest(hours: 1),
                          child: const Text('1小时')),
                      const SizedBox(width: 6),
                      OutlinedButton(
                          onPressed: () => _rest(hours: 2),
                          child: const Text('2小时')),
                      const SizedBox(width: 6),
                      if (shop.closeTime.isNotEmpty)
                        OutlinedButton(
                            onPressed: () => _rest(untilClose: true),
                            child: const Text('到打烊')),
                    ]),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Text('节假日计划'),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          shop.holidayPlans.isEmpty
                              ? '未设置'
                              : shop.holidayPlans
                                  .map(_planLabel)
                                  .join(' · '),
                          style: TextStyle(
                              color: shop.holidayPlans.isEmpty
                                  ? null
                                  : Colors.orange),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      TextButton(
                          onPressed: _editHolidayPlans,
                          child: const Text('管理')),
                    ],
                  ),
                  Text('计划优先于每日营业时间:歇业日自动关店不再自动开;特殊时段日按计划时段开关',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 运营三件套:起送价 / 打包费 / 满减(全部商家自主,平台不强制)
                  Row(
                    children: [
                      const Text('起送价'),
                      const SizedBox(width: 12),
                      OutlinedButton(
                        onPressed: () => _editAmount(
                            '起送价(元,0 为不限)', shop.minOrderCents,
                            'min_order_cents'),
                        child: Text(shop.minOrderCents > 0
                            ? '¥${shop.minOrderCents ~/ 100}'
                            : '不限'),
                      ),
                      const SizedBox(width: 16),
                      const Text('打包费'),
                      const SizedBox(width: 12),
                      OutlinedButton(
                        onPressed: () => _editAmount(
                            '每单打包费(元,0 为免收)', shop.packingFeeCents,
                            'packing_fee_cents'),
                        child: Text(shop.packingFeeCents > 0
                            ? yuan(shop.packingFeeCents)
                            : '免收'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Text('满减活动'),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          shop.promoLabels.isEmpty
                              ? '未设置'
                              : shop.promoLabels.join(' · '),
                          style: TextStyle(
                              color: shop.promoLabels.isEmpty
                                  ? null
                                  : Colors.orange),
                        ),
                      ),
                      TextButton(
                          onPressed: _editPromoRules,
                          child: const Text('编辑')),
                    ],
                  ),
                  Text('满减成本由商家承担,平台按满减后的实收计 5% 服务费——你让利,平台跟着少收',
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Text('满赠活动'),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          shop.giftRules.isEmpty
                              ? '未设置'
                              : shop.giftRules
                                  .map((r) =>
                                      '满${r.thresholdCents ~/ 100}赠${r.name}')
                                  .join(' · '),
                          style: TextStyle(
                              color: shop.giftRules.isEmpty
                                  ? null
                                  : Colors.orange),
                        ),
                      ),
                      TextButton(
                          onPressed: _editGiftRules,
                          child: const Text('编辑')),
                    ],
                  ),
                  Text('满赠动货不动钱:赠品 0 元入订单、照常扣库存,佣金不含赠品;赠品没库存时该档自动失效,不影响下单',
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      const Text('店铺券'),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          _shopCoupons.isEmpty
                              ? '未发券'
                              : _shopCoupons
                                  .where((b) => b['active'] == true)
                                  .map((b) =>
                                      '满${b['threshold_cents'] ~/ 100}减${b['off_cents'] ~/ 100}')
                                  .join(' · '),
                          style: TextStyle(
                              color: _shopCoupons.any((b) => b['active'] == true)
                                  ? Colors.orange
                                  : null),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      TextButton(
                          onPressed: _manageShopCoupons,
                          child: const Text('管理')),
                    ],
                  ),
                  Text('店铺券成本你自己出(和满减同口径,平台按券后实收计 5%),用来引流拉复购;与满减二选其一取最优,不叠加',
                      style: Theme.of(context).textTheme.bodySmall),
                  // 子账号管理:仅店主可见(店员看不到,也无权管理)
                  if (!shop.viewerIsStaff) ...[
                    const SizedBox(height: 8),
                    Row(children: [
                      const Text('子账号(店员)'),
                      const Spacer(),
                      TextButton(
                          onPressed: _manageStaff, child: const Text('管理')),
                    ]),
                    Text('给店员开账号只能接单/出餐/估清,提现改价改设置仍只有你能操作',
                        style: Theme.of(context).textTheme.bodySmall),
                  ] else
                    Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: Text('你是本店店员:可接单出餐估清;提现/改价/改设置请联系店主',
                          style: Theme.of(context)
                              .textTheme
                              .bodySmall
                              ?.copyWith(color: Colors.orange)),
                    ),
                  const Divider(height: 24),
                  // 团购(第二增长曲线:低价引流到店,核销才收 2%)
                  Row(
                    children: [
                      const Text('团购券'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.local_activity_outlined,
                            size: 18),
                        label: const Text('管理'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) =>
                                    VoucherManagePage(api: widget.api))),
                      ),
                      const SizedBox(width: 8),
                      FilledButton.tonalIcon(
                        icon: const Icon(Icons.qr_code_scanner, size: 18),
                        label: const Text('核销'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) =>
                                    VoucherRedeemPage(api: widget.api))),
                      ),
                    ],
                  ),
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('外卖品类'),
                      const SizedBox(width: 12),
                      Expanded(
                          child: Text(
                              '${kMerchantCategoryEmoji[shop.category] ?? ''} '
                              '${merchantCategoryLabel(shop.category)}',
                              style: const TextStyle(color: Colors.orange))),
                      TextButton(
                          onPressed: _editCategory,
                          child: const Text('修改')),
                    ],
                  ),
                  Text('品类决定你出现在用户端哪个分类里,随时可改即时生效',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('承诺出餐时长'),
                      const SizedBox(width: 12),
                      Expanded(
                          child: Text('${shop.promiseReadyMinutes} 分钟',
                              style: const TextStyle(color: Colors.orange))),
                      TextButton(
                          onPressed: _editPromiseMinutes,
                          child: const Text('编辑')),
                    ],
                  ),
                  Text('接单后超过承诺时长未出餐,平台会催单并统计超时率(对账页可见)',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  Row(
                    children: [
                      const Text('商家自配送'),
                      const Spacer(),
                      Switch(
                        value: shop.selfDelivery,
                        onChanged: (v) async {
                          try {
                            await widget.api
                                .updateShop({'self_delivery': v});
                            _load();
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text(e.toString())));
                          }
                        },
                      ),
                    ],
                  ),
                  Text('开启后新订单由你自己配送(不进骑手抢单池);配送费归你,'
                      '平台照常只抽餐费佣金。只影响开启之后的新订单',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 小票打印:云打印机(服务端直推)+ 蓝牙小票机(App 直连)
                  Row(
                    children: [
                      const Text('小票打印'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.print_outlined, size: 18),
                        label: const Text('设置'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) => PrinterPage(
                                    api: widget.api,
                                    shopName: shop.name))),
                      ),
                    ],
                  ),
                  Text('云打印机来单自动出票(手机不在场也能打);也可蓝牙直连通用小票机',
                      style: Theme.of(context).textTheme.bodySmall),
                  const Divider(height: 24),
                  // 判责申诉:售后判商家责/差评,72 小时内可申诉
                  Row(
                    children: [
                      const Text('判责申诉'),
                      const Spacer(),
                      OutlinedButton.icon(
                        icon: const Icon(Icons.gavel_outlined, size: 18),
                        label: const Text('进入'),
                        onPressed: () => Navigator.of(context).push(
                            MaterialPageRoute(
                                builder: (_) =>
                                    MerchantAppealPage(api: widget.api))),
                      ),
                    ],
                  ),
                  Text('对售后判责或差评有异议?72 小时内申诉,平台人工复核',
                      style: Theme.of(context).textTheme.bodySmall),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          // 门店相册:环境/后厨/证照实拍是最好的信任素材,展示在用户点单页「商家」标签
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text('门店相册(${shop.photoUrls.length}/9)',
                          style: Theme.of(context).textTheme.titleMedium),
                      const Spacer(),
                      TextButton.icon(
                        icon: _uploadingPhoto
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2))
                            : const Icon(Icons.add_photo_alternate_outlined,
                                size: 20),
                        label: Text(_uploadingPhoto ? '上传中…' : '添加'),
                        onPressed: _uploadingPhoto ||
                                shop.photoUrls.length >= 9
                            ? null
                            : _addShopPhoto,
                      ),
                    ],
                  ),
                  Text('店面环境、后厨、食材实拍,展示在用户点单页「商家」标签——真实门店是最好的信任素材',
                      style: Theme.of(context).textTheme.bodySmall),
                  const SizedBox(height: 8),
                  if (shop.photoUrls.isEmpty)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(vertical: 20),
                      decoration: BoxDecoration(
                        color: Theme.of(context)
                            .colorScheme
                            .surfaceContainerHighest
                            .withValues(alpha: 0.4),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Center(
                          child: Text('还没有照片,点右上角「添加」传第一张')),
                    )
                  else
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final url in shop.photoUrls)
                          Stack(
                            children: [
                              ClipRRect(
                                borderRadius: BorderRadius.circular(8),
                                child: Image.network(
                                  widget.api.resolveUrl(url),
                                  width: 92,
                                  height: 92,
                                  fit: BoxFit.cover,
                                  errorBuilder: (_, __, ___) => Container(
                                      width: 92,
                                      height: 92,
                                      color: Theme.of(context)
                                          .colorScheme
                                          .surfaceContainerHighest,
                                      child: const Icon(
                                          Icons.broken_image_outlined)),
                                ),
                              ),
                              Positioned(
                                top: 2,
                                right: 2,
                                child: InkWell(
                                  onTap: () => _removeShopPhoto(url),
                                  child: Container(
                                    padding: const EdgeInsets.all(2),
                                    decoration: BoxDecoration(
                                      color: Colors.black.withValues(
                                          alpha: 0.55),
                                      shape: BoxShape.circle,
                                    ),
                                    child: const Icon(Icons.close,
                                        size: 14, color: Colors.white),
                                  ),
                                ),
                              ),
                            ],
                          ),
                      ],
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 16),
          // 售后处理(待处理的排最前,拖着不处理伤信任)
          if (_afterSales.isNotEmpty) ...[
            Text('售后待处理(${_afterSales.length})',
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(color: Theme.of(context).colorScheme.error)),
            const SizedBox(height: 4),
            for (final sale in _afterSales)
              Card(
                margin: const EdgeInsets.symmetric(vertical: 4),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(sale.orderSummary,
                          style: Theme.of(context).textTheme.titleSmall),
                      Text('订单 ${sale.orderNo} · ${yuan(sale.totalCents)}',
                          style: Theme.of(context).textTheme.bodySmall),
                      const SizedBox(height: 4),
                      Text('用户反馈:${sale.reason}'),
                      if (sale.images.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Wrap(spacing: 6, children: [
                            for (final img in sale.images)
                              ClipRRect(
                                borderRadius: BorderRadius.circular(6),
                                child: Image.network(
                                    widget.api.resolveUrl(img),
                                    width: 64, height: 64, fit: BoxFit.cover),
                              ),
                          ]),
                        ),
                      const SizedBox(height: 8),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: [
                          OutlinedButton(
                            onPressed: () => _processAfterSale(sale, false),
                            child: const Text('拒绝'),
                          ),
                          const SizedBox(width: 8),
                          FilledButton(
                            onPressed: () => _processAfterSale(sale, true),
                            child: const Text('同意退款'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 12),
          ],
          Text('顾客评价(${_reviews.length})',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 4),
          if (_reviews.isEmpty)
            const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: Text('还没有评价'))),
          for (final review in _reviews)
            Card(
              margin: const EdgeInsets.symmetric(vertical: 4),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(review.customerName,
                            style: Theme.of(context).textTheme.titleSmall),
                        const SizedBox(width: 8),
                        Text(_stars(review.merchantRating),
                            style: const TextStyle(color: Colors.amber)),
                        const Spacer(),
                        Text(review.createdAt.substring(0, 10),
                            style: Theme.of(context).textTheme.bodySmall),
                      ],
                    ),
                    if (review.comment.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(review.comment),
                    ],
                    if (review.reply.isNotEmpty)
                      Container(
                        margin: const EdgeInsets.only(top: 6),
                        padding: const EdgeInsets.all(8),
                        width: double.infinity,
                        decoration: BoxDecoration(
                          color: Theme.of(context)
                              .colorScheme
                              .surfaceContainerHighest
                              .withValues(alpha: 0.5),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text('我的回复:${review.reply}',
                            style: Theme.of(context).textTheme.bodySmall),
                      ),
                    Align(
                      alignment: Alignment.centerRight,
                      child: TextButton(
                        onPressed: () => _reply(review),
                        child: Text(review.reply.isEmpty ? '回复' : '修改回复'),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              leading: const Icon(Icons.support_agent_outlined),
              title: const Text('联系平台客服'),
              subtitle: const Text('对账疑问、审核进度、任何问题都可以问'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => SupportPage(api: widget.api))),
            ),
          ),
        ],
      ),
    );
  }
}
