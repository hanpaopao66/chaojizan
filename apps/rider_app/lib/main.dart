import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import 'location_service.dart';
import 'map_page.dart';
import 'verify_page.dart';
import 'wallet_page.dart';

// GPS 不可用时(如 iOS 模拟器没设置位置)的兜底坐标,保证开发期照常演示
const fallbackLat = 30.6605;
const fallbackLng = 104.0815;

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  // 推送 SDK 的初始化在用户同意隐私政策之后(PrivacyGate.onAgreed),
  // 同意前启动收集类 SDK 是应用商店审核红线
  runApp(const RiderApp());
}

class RiderApp extends StatelessWidget {
  const RiderApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '超级赞骑手端',
      theme: ThemeData(
          useMaterial3: true,
          brightness: Brightness.light,
          colorSchemeSeed: Colors.indigo),
      darkTheme: ThemeData(
          useMaterial3: true,
          brightness: Brightness.dark,
          colorSchemeSeed: Colors.indigo),
      themeMode: ThemeMode.system,
      home: SplashGate(
          app: 'rider',
          tagline: '配送费 100% 归你',
          subLines: const [
            '小费全归你,平台分文不取',
            '提现零手续费,收入明细逐单可查',
            '干活的人,拿到该拿的钱',
          ],
          child: PrivacyGate(
        onAgreed: PushService.init,
        child: LoginPage(
          title: '骑手端 · 抢单配送',
          defaultPhone: '13800000003',
          onLoggedIn: (context, api) => Navigator.of(context).pushReplacement(
              MaterialPageRoute(
                  builder: (_) => RiderVerifyGate(
                      api: api, child: RiderHomePage(api: api)))),
        ),
      )),
    );
  }
}

class RiderHomePage extends StatefulWidget {
  const RiderHomePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<RiderHomePage> createState() => _RiderHomePageState();
}

class _RiderHomePageState extends State<RiderHomePage> {
  int _tab = 0;
  bool _online = false;
  int? _grabRadiusKm; // 接单半径偏好(null=不限),服务端持久化
  bool _gpsActive = false;
  List<Order> _available = [];
  List<Order> _mine = [];
  Timer? _pollTimer;
  Timer? _keepaliveTimer;
  final _location = LocationService();

  /// 骑手当前位置(GCJ-02),地图页监听它实时刷新
  final _riderPosition = ValueNotifier<({double lat, double lng})?>(null);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) =>
        checkForUpdate(context, baseUrl: widget.api.baseUrl, app: 'rider'));
    _refresh();
    _pollTimer = Timer.periodic(const Duration(seconds: 5), (_) => _refresh());
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _keepaliveTimer?.cancel();
    _location.stop();
    _riderPosition.dispose();
    super.dispose();
  }

  final Set<String> _seenOrderNos = {};
  bool _firstLoad = true;

  /// 骑手到商家的距离(米);没定位或订单缺坐标返回 null
  double? _distanceToShop(Order order) {
    final fix = _location.lastFix;
    if (fix == null || order.merchantLat == null || order.merchantLng == null) {
      return null;
    }
    return distanceMeters(fix.lat, fix.lng, order.merchantLat!, order.merchantLng!);
  }

  /// 商家到顾客的送程(米)
  double? _tripDistance(Order order) {
    if (order.merchantLat == null || order.merchantLng == null) return null;
    return distanceMeters(
        order.merchantLat!, order.merchantLng!, order.lat, order.lng);
  }

  Future<void> _refresh() async {
    try {
      // 服务端已按「综合分 = 距离 - 等待加权」排好(顺路信息也来自服务端),
      // 客户端不再自行重排,避免把等久的老单永远压在底部
      final available = _online ? await widget.api.availableOrders() : <Order>[];
      final mine = await widget.api.myOrders();

      // 新的可抢订单出现 → 响铃 + 振动提醒(首轮加载不响,避免一上线就炸铃)
      final fresh = available
          .where((o) => !_seenOrderNos.contains(o.orderNo))
          .toList();
      _seenOrderNos.addAll(available.map((o) => o.orderNo));
      if (!_firstLoad && _online && fresh.isNotEmpty && mounted) {
        SystemSound.play(SystemSoundType.alert);
        HapticFeedback.vibrate();
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('🔔 新单来了:${fresh.first.merchantName} '
              '→ ${fresh.first.address},配送费 ${yuan(fresh.first.deliveryFeeCents)}'),
          duration: const Duration(seconds: 4),
        ));
      }
      _firstLoad = false;

      if (mounted) {
        setState(() {
          _available = available;
          _mine = _suggestSequence(mine
              .where((o) =>
                  o.status == OrderStatus.accepted ||
                  o.status == OrderStatus.ready ||
                  o.status == OrderStatus.pickedUp)
              .toList());
        });
      }
    } catch (_) {}
  }

  /// 我的配送建议顺序:先取后送——待取餐的单同店相邻(店按离我远近),
  /// 已取餐的按收货点离我远近连着送。只是建议排序,不强制。
  List<Order> _suggestSequence(List<Order> mine) {
    int rank(Order o) => o.status == OrderStatus.pickedUp ? 1 : 0;
    final sorted = [...mine];
    sorted.sort((a, b) {
      final r = rank(a).compareTo(rank(b));
      if (r != 0) return r;
      if (rank(a) == 0) {
        // 取餐组:同店聚在一起(一次到店拿多单),店按距我远近
        if (a.merchantId == b.merchantId) return 0;
        final da = _distanceToShop(a) ?? double.infinity;
        final db = _distanceToShop(b) ?? double.infinity;
        final c = da.compareTo(db);
        if (c != 0) return c;
        return a.merchantId.compareTo(b.merchantId);
      }
      // 配送组:收货点近的先送
      final fix = _location.lastFix;
      if (fix == null) return 0;
      return distanceMeters(fix.lat, fix.lng, a.lat, a.lng)
          .compareTo(distanceMeters(fix.lat, fix.lng, b.lat, b.lng));
    });
    return sorted;
  }

  Future<void> _report(double lat, double lng) async {
    _riderPosition.value = (lat: lat, lng: lng);
    try {
      await widget.api.reportLocation(lat, lng);
    } catch (_) {}
  }

  /// 一键紧急求助:长按触发 → 确认弹层(二道防误触)→ 上报,
  /// 2 分钟内可撤销;110/120 快拨置顶;在途订单由客服确认后处理。
  Future<void> _triggerSos() async {
    final go = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('🆘 紧急求助'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            Expanded(
              child: FilledButton.icon(
                style: FilledButton.styleFrom(backgroundColor: Colors.red),
                icon: const Icon(Icons.emergency),
                label: const Text('110'),
                onPressed: () => launchUrl(Uri.parse('tel:110')),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FilledButton.icon(
                style: FilledButton.styleFrom(backgroundColor: Colors.orange),
                icon: const Icon(Icons.medical_services_outlined),
                label: const Text('120'),
                onPressed: () => launchUrl(Uri.parse('tel:120')),
              ),
            ),
          ]),
          const SizedBox(height: 10),
          const Text('确认后平台 5 分钟内电话回访,并通知你的紧急联系人;'
              '在途订单不用管,客服会处理。误触可在 2 分钟内撤销。',
              style: TextStyle(fontSize: 12)),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              style: FilledButton.styleFrom(backgroundColor: Colors.red),
              onPressed: () => Navigator.pop(context, true),
              child: const Text('向平台求助')),
        ],
      ),
    );
    if (go != true || !mounted) return;
    try {
      final fix = _location.lastFix;
      final r = await widget.api.riderSos(
          lat: fix?.lat, lng: fix?.lng);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: const Text('已求助,平台马上联系你;注意安全'),
        duration: const Duration(seconds: 8),
        action: SnackBarAction(
          label: '误触撤销',
          onPressed: () async {
            try {
              await widget.api.cancelSos(r['id'] as int);
              if (!mounted) return;
              ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('已撤销')));
            } catch (_) {}
          },
        ),
      ));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _toggleOnline(bool value) async {
    try {
      await widget.api.setOnline(value);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
      return;
    }
    setState(() => _online = value);

    if (value) {
      // 真实 GPS:移动 10 米上报一次
      final error = await _location.start(_report);
      _gpsActive = error == null;
      if (error != null && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('$error(先用演示坐标继续)')));
      }
      // 静止时每 15 秒保活一次,防止后台位置过期;GPS 不可用则上报兜底坐标
      _keepaliveTimer = Timer.periodic(const Duration(seconds: 15), (_) {
        final fix = _location.lastFix;
        if (fix != null) {
          _report(fix.lat, fix.lng);
        } else if (!_gpsActive) {
          _report(fallbackLat, fallbackLng);
        }
      });
      if (!_gpsActive) _report(fallbackLat, fallbackLng);
    } else {
      _location.stop();
      _keepaliveTimer?.cancel();
    }
    _refresh();
  }

  Future<void> _grab(Order order) async {
    try {
      await widget.api.grabOrder(order.orderNo);
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('抢单成功!')));
      setState(() => _tab = 1);
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
      _refresh();
    }
  }

  /// 送达:保护单引导拍照留证(深夜强制,白天可选,放门口拍一张)
  Future<void> _deliver(Order order) async {
    var photoUrl = '';
    if (order.addrProtect) {
      final take = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('拍照留证'),
          content: const Text('这是地址保护订单:放门口请拍一张照片留证'
              '(深夜时段必须拍;照片只有顾客和平台能看到)。'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('当面交付,不拍')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('去拍照')),
          ],
        ),
      );
      if (take == null || !mounted) return;
      if (take) {
        try {
          final picked = await ImagePicker().pickImage(
              source: ImageSource.camera, maxWidth: 1280, imageQuality: 80);
          if (picked == null) return;
          final bytes = await picked.readAsBytes();
          photoUrl = await widget.api.uploadImage(bytes, picked.name);
        } catch (e) {
          if (!mounted) return;
          ScaffoldMessenger.of(context)
              .showSnackBar(SnackBar(content: Text(e.toString())));
          return;
        }
      }
    }
    try {
      await widget.api.transition(order.orderNo, OrderStatus.delivered,
          photoUrl: photoUrl);
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 地址不准反馈:只沉淀不追责,攒两条用户下单会收到核对提示
  Future<void> _reportAddress(Order order) async {
    final note = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('反馈地址不准'),
        content: TextField(
            controller: note,
            maxLength: 100,
            decoration: const InputDecoration(
                hintText: '哪里对不上?(如 定位偏了/楼栋找不到)',
                border: OutlineInputBorder())),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('提交')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await widget.api.addressFeedback(order.orderNo, note.text.trim());
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已反馈,谢谢;不影响你正常送达')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 取餐核验:输小票单号尾号后 4 位防拿错单;连续输错 3 次可强制取餐(留痕)。
  Future<void> _pickUp(Order order) async {
    final code = TextEditingController();
    var error = '';
    var failures = 0;
    var submitting = false;
    final done = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) {
          Future<void> submit({bool force = false}) async {
            setSheet(() => submitting = true);
            try {
              await widget.api.transition(order.orderNo, OrderStatus.pickedUp,
                  verifyCode: force ? '' : code.text.trim(), force: force);
              if (sheetContext.mounted) Navigator.pop(sheetContext, true);
            } catch (e) {
              setSheet(() {
                failures += 1;
                submitting = false;
                error = e.toString();
              });
            }
          }

          return Padding(
            padding: EdgeInsets.only(
                left: 16, right: 16, top: 16,
                bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('取餐核验',
                    style: Theme.of(sheetContext).textTheme.titleMedium),
                Text('输入小票上单号的后 4 位,防止拿错别人的餐',
                    style: Theme.of(sheetContext).textTheme.bodySmall),
                const SizedBox(height: 12),
                TextField(
                  controller: code,
                  autofocus: true,
                  maxLength: 4,
                  keyboardType: TextInputType.text,
                  decoration: InputDecoration(
                    labelText: '单号后 4 位',
                    border: const OutlineInputBorder(),
                    errorText: error.isEmpty ? null : error,
                    errorMaxLines: 3,
                  ),
                ),
                const SizedBox(height: 8),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: submitting ? null : () => submit(),
                    child: Text(submitting ? '核验中…' : '核验并取餐'),
                  ),
                ),
                // 连续输错 3 次:小票可能损坏/丢失,放行但服务端留痕
                if (failures >= 3)
                  SizedBox(
                    width: double.infinity,
                    child: TextButton(
                      onPressed: submitting ? null : () => submit(force: true),
                      child: const Text('核验不了?强制取餐(会记录)'),
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    );
    if (done == true) _refresh();
  }

  /// 配送异常上报:途中(联系不上/地址错/餐损)+ 交接(到店未出餐/餐不齐)。
  /// 到店未出餐 = 催商家出餐,等满 10 分钟还可无责转单;
  /// 餐损/餐不齐必须拍照,走平台仲裁。
  Future<void> _reportIssue(Order order) async {
    final pickedUp = order.status == OrderStatus.pickedUp;
    // 已取餐了不能再报「未出餐」;没取餐时最常用的是催出餐,排前面
    final kinds = [
      if (!pickedUp) ('not_ready', '到店未出餐(催商家)'),
      ('items_missing', '餐品不齐/缺件(需拍照)'),
      ('cannot_contact', '联系不上顾客'),
      ('wrong_address', '地址错误/找不到'),
      ('food_damaged', '餐品洒损(需拍照)'),
      ('other', '其他'),
    ];
    var kind = kinds.first.$1;
    final note = TextEditingController();
    String photoUrl = '';
    bool uploading = false;
    bool needPhoto() => kind == 'food_damaged' || kind == 'items_missing';
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) => Padding(
          padding: EdgeInsets.only(
              left: 16, right: 16, top: 16,
              bottom: MediaQuery.of(sheetContext).viewInsets.bottom + 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('上报配送异常',
                  style: Theme.of(sheetContext).textTheme.titleMedium),
              Text('顾客和商家会立即收到提醒,平台客服介入处理',
                  style: Theme.of(sheetContext).textTheme.bodySmall),
              const SizedBox(height: 8),
              RadioGroup<String>(
                groupValue: kind,
                onChanged: (v) => setSheet(() => kind = v!),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    for (final (value, label) in kinds)
                      RadioListTile<String>(
                        dense: true,
                        value: value,
                        title: Text(label),
                      ),
                  ],
                ),
              ),
              TextField(
                controller: note,
                maxLength: 100,
                decoration: const InputDecoration(
                    labelText: '补充说明(选填)', border: OutlineInputBorder()),
              ),
              if (needPhoto())
                Row(children: [
                  OutlinedButton.icon(
                    icon: const Icon(Icons.photo_camera_outlined, size: 18),
                    label: Text(photoUrl.isEmpty
                        ? (uploading ? '上传中…' : '拍现场照片(必传)')
                        : '已上传 ✓'),
                    onPressed: uploading
                        ? null
                        : () async {
                            final picked = await ImagePicker().pickImage(
                                source: ImageSource.camera,
                                maxWidth: 1280,
                                imageQuality: 85);
                            if (picked == null) return;
                            setSheet(() => uploading = true);
                            try {
                              final bytes = await picked.readAsBytes();
                              final url = await widget.api
                                  .uploadImage(bytes, picked.name);
                              setSheet(() => photoUrl = url);
                            } catch (_) {
                            } finally {
                              setSheet(() => uploading = false);
                            }
                          },
                  ),
                ]),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () => Navigator.pop(sheetContext, true),
                  child: const Text('提交上报'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (ok != true || !mounted) return;
    if (needPhoto() && photoUrl.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(kind == 'food_damaged'
              ? '餐损上报必须拍现场照片'
              : '餐不齐上报必须拍照(袋内实拍)')));
      return;
    }
    try {
      await widget.api.reportDeliveryIssue(order.orderNo, kind,
          note: note.text.trim(), photoUrl: photoUrl);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(kind == 'not_ready'
              ? '已催商家出餐;等满 10 分钟仍未出餐,可无责转单'
              : '已上报,平台会尽快处理;紧急情况可直接电话联系顾客')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 转单:已抢未取餐的单退回抢单池(车坏了/身体不适等突发状况不用硬扛)。
  /// 每天免责 2 次,超出仍可转但计入考核参考;已取餐不能转,走异常上报。
  Future<void> _transferOrder(Order order) async {
    var reason = 'vehicle_broken';
    final ok = await showModalBottomSheet<bool>(
      context: context,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) => Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('转单', style: Theme.of(sheetContext).textTheme.titleMedium),
              Text('订单退回抢单池由其他骑手接力;每天免责 2 次,请勿频繁转单',
                  style: Theme.of(sheetContext).textTheme.bodySmall),
              const SizedBox(height: 8),
              RadioGroup<String>(
                groupValue: reason,
                onChanged: (v) => setSheet(() => reason = v!),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    for (final (value, label) in const [
                      ('vehicle_broken', '车坏了'),
                      ('unwell', '身体不适'),
                      ('route_conflict', '顺路冲突'),
                      ('other', '其他'),
                    ])
                      RadioListTile<String>(
                        dense: true,
                        value: value,
                        title: Text(label),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () => Navigator.pop(sheetContext, true),
                  child: const Text('确认转单'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final result = await widget.api.transferOrder(order.orderNo, reason);
      if (!mounted) return;
      final count = result['today_count'] as int? ?? 0;
      final free = result['free_times'] as int? ?? 2;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(count > free
              ? '已转单(今日第 $count 次,超过免责 $free 次会计入考核参考)'
              : '已转单,其他骑手会接力配送')));
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 接单半径 chips:只看 N 公里内的单(顺路单豁免),服务端持久化。
  Widget _radiusBar() {
    Future<void> setRadius(int? km) async {
      try {
        final saved = await widget.api.setGrabRadius(km);
        if (mounted) setState(() => _grabRadiusKm = saved);
        _refresh();
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.toString())));
      }
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: Row(children: [
        Text('接单半径', style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(width: 8),
        Expanded(
          child: Wrap(spacing: 6, children: [
            for (final (km, label) in const [
              (null, '不限'), (1, '1km'), (2, '2km'), (3, '3km'), (5, '5km'),
            ])
              ChoiceChip(
                label: Text(label, style: const TextStyle(fontSize: 12)),
                visualDensity: VisualDensity.compact,
                selected: _grabRadiusKm == km,
                onSelected: (_) => setRadius(km),
              ),
          ]),
        ),
      ]),
    );
  }

  void _openMap(Order order) {
    Navigator.of(context).push(MaterialPageRoute(
        builder: (_) =>
            DeliveryMapPage(order: order, riderPosition: _riderPosition)));
  }

  Widget _orderCard(Order order, {List<Widget> actions = const []}) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              Expanded(
                  child: Text(order.summary,
                      style: Theme.of(context).textTheme.titleMedium)),
              Chip(label: Text(order.status.label)),
            ]),
            const SizedBox(height: 4),
            if (order.scheduledLabel != null)
              Text('⏰ ${order.scheduledLabel}',
                  style: const TextStyle(
                      color: Colors.orange, fontWeight: FontWeight.bold)),
            if (order.parentOrderNo.isNotEmpty)
              Text(
                  '📎 追加单,随#${order.parentOrderNo.substring(order.parentOrderNo.length - 6)} 一起取送',
                  style: const TextStyle(
                      color: Colors.teal, fontWeight: FontWeight.bold)),
            // 顺路标记(抢单池):同店一次取多单 / 收货点相近连着送
            if (order.sameShop || order.sameWay)
              Text(order.sameShop ? '🛵 顺路 · 与手头单同店取餐' : '🛵 顺路 · 与手头单收货点相近',
                  style: const TextStyle(
                      color: Colors.green, fontWeight: FontWeight.bold)),
            if (order.hasAlcohol)
              const Text('🍺 含酒精饮品,送达请查验收件人年龄',
                  style: TextStyle(
                      color: Colors.orange, fontWeight: FontWeight.bold)),
            Text('取餐:${order.merchantName} · ${order.merchantAddress}'),
            Text('送达:${order.address}'),
            if (order.contactPhone.isNotEmpty)
              Row(children: [
                // 号码打码展示;拨打走隐私号通道(严格模式下无号可拨则不显示按钮)
                Expanded(
                    child:
                        Text('联系:${order.contactName} ${order.contactPhone}')),
                IconButton(
                  icon: const Icon(Icons.chat_bubble_outline, size: 18),
                  visualDensity: VisualDensity.compact,
                  tooltip: '发消息',
                  onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute(
                          builder: (_) => OrderChatPage(
                              api: widget.api,
                              orderNo: order.orderNo,
                              title: '和顾客说句话',
                              quickReplies: kRiderQuickReplies))),
                ),
                if (order.privacyPhone.isNotEmpty)
                  IconButton(
                    icon: const Icon(Icons.phone, size: 18),
                    visualDensity: VisualDensity.compact,
                    tooltip: '拨打(号码保护)',
                    onPressed: () => launchUrl(
                        Uri.parse('tel:${order.privacyPhone}')),
                  ),
              ]),
            Builder(builder: (context) {
              // 本地定位优先(更新更快),没有就用服务端算的距离
              final toShop = _distanceToShop(order) ?? order.distanceM?.toDouble();
              final trip = _tripDistance(order);
              final parts = [
                if (toShop != null) '距你 ${distanceLabel(toShop)}',
                if (trip != null) '送程 ${distanceLabel(trip)}',
              ];
              return Row(children: [
                Text(
                    order.tipCents > 0
                        ? '配送费 ${yuan(order.deliveryFeeCents)}+小费 ${yuan(order.tipCents)}'
                        : '配送费 ${yuan(order.deliveryFeeCents)}',
                    style: TextStyle(
                        color: Theme.of(context).colorScheme.primary,
                        fontWeight: FontWeight.bold)),
                if (parts.isNotEmpty) ...[
                  const SizedBox(width: 8),
                  Text(parts.join(' · '),
                      style: Theme.of(context).textTheme.bodySmall),
                ],
              ]);
            }),
            if (actions.isNotEmpty) ...[
              const SizedBox(height: 8),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  for (final (i, action) in actions.indexed) ...[
                    if (i > 0) const SizedBox(width: 8),
                    action,
                  ],
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final body = _tab == 0
        ? RefreshIndicator(
            onRefresh: _refresh,
            child: !_online
                ? ListView(children: const [
                    Padding(
                        padding: EdgeInsets.all(24),
                        child: Text('上线后开始接单(右上角开关)'))
                  ])
                : ListView.builder(
                        itemCount: _available.length + 1,
                        itemBuilder: (context, i) {
                          if (i == 0) return _radiusBar();
                          return _orderCard(
                          _available[i - 1],
                          actions: [
                            OutlinedButton(
                                onPressed: () => _openMap(_available[i - 1]),
                                child: const Text('看路线')),
                            FilledButton(
                                onPressed: () => _grab(_available[i - 1]),
                                child: const Text('抢单')),
                          ],
                        );
                        },
                      ),
          )
        : RefreshIndicator(
            onRefresh: _refresh,
            child: _mine.isEmpty
                ? ListView(children: const [
                    Padding(
                        padding: EdgeInsets.all(24), child: Text('没有进行中的配送'))
                  ])
                : ListView.builder(
                    itemCount: _mine.length,
                    itemBuilder: (context, i) {
                      final order = _mine[i];
                      final actions = <Widget>[
                        OutlinedButton.icon(
                            icon: const Icon(Icons.map, size: 18),
                            onPressed: () => _openMap(order),
                            label: const Text('地图')),
                        OutlinedButton.icon(
                            icon: const Icon(Icons.report_problem_outlined,
                                size: 18),
                            onPressed: () => _reportIssue(order),
                            label: const Text('异常')),
                      ];
                      // 未取餐(接单中/待取餐)且非追加单可转单;追加单随原单一起转
                      if (order.status != OrderStatus.pickedUp &&
                          order.parentOrderNo.isEmpty) {
                        actions.add(OutlinedButton.icon(
                            icon: const Icon(Icons.swap_horiz, size: 18),
                            onPressed: () => _transferOrder(order),
                            label: const Text('转单')));
                      }
                      if (order.status == OrderStatus.ready) {
                        actions.add(FilledButton(
                            onPressed: () => _pickUp(order),
                            child: const Text('已取餐')));
                      } else if (order.status == OrderStatus.pickedUp) {
                        actions.add(TextButton(
                            onPressed: () => _reportAddress(order),
                            child: const Text('地址不准')));
                        actions.add(FilledButton(
                            onPressed: () => _deliver(order),
                            child: const Text('已送达')));
                      }
                      return _orderCard(order, actions: actions);
                    },
                  ),
          );

    final page = _tab == 2 ? WalletPage(api: widget.api) : body;

    return Scaffold(
      appBar: AppBar(
        title: Text(switch (_tab) { 0 => '抢单大厅', 1 => '我的配送', _ => '我的钱包' }),
        leading: Tooltip(
          message: '长按 3 秒紧急求助',
          child: GestureDetector(
            onLongPress: _triggerSos,
            child: const Icon(Icons.sos, color: Colors.red),
          ),
        ),
        actions: [
          Row(children: [
            Icon(
              _gpsActive ? Icons.gps_fixed : Icons.gps_off,
              size: 18,
              color: _gpsActive ? Colors.green : Colors.grey,
            ),
            const SizedBox(width: 4),
            Text(_online ? '接单中' : '已下线'),
            Switch(value: _online, onChanged: _toggleOnline),
            const SizedBox(width: 8),
          ]),
        ],
      ),
      body: page,
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.flash_on), label: '抢单'),
          NavigationDestination(icon: Icon(Icons.moped), label: '配送'),
          NavigationDestination(icon: Icon(Icons.account_balance_wallet), label: '钱包'),
        ],
      ),
    );
  }
}
