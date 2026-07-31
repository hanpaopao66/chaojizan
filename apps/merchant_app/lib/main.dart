import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'dish_manage_page.dart';
import 'finance_page.dart';
import 'hotel/hotel_home_page.dart';
import 'listen_service.dart';
import 'printer_service.dart';
import 'shop_tab.dart';
import 'self_delivery_map_page.dart';

/// 全端共用的 ApiClient 单例(会话持久化在它身上)
final rootApi = ApiClient();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // 推送 SDK 的初始化在用户同意隐私政策之后(PrivacyGate.onAgreed),
  // 同意前启动收集类 SDK 是应用商店审核红线
  // 可下发文案:只等本地缓存(毫秒级),网络刷新后台跑,不卡冷启动
  await RemoteCopy.loadCached();
  unawaited(RemoteCopy.refresh(rootApi));
  runApp(const MerchantApp());
}

class MerchantApp extends StatelessWidget {
  const MerchantApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '超级赞商家端',
      // 深浅两套令牌都在 brand.dart 里定义(第八辑 #101),#111 走查后放开
      theme: brandTheme(Brightness.light, density: SzDensity.operate),
      darkTheme: brandTheme(Brightness.dark, density: SzDensity.operate),
      themeMode: ThemeMode.system,
      home: SplashGate(
          app: 'merchant',
          tagline: '入驻免费,总负担 5% 封顶',
          subLines: const [
            '没有竞价排名,没有隐藏费用',
            '单量越大费率越低,自动降档最低 4%',
            '每日对账,每一笔分账可查可申诉',
          ],
          child: PrivacyGate(
            onAgreed: PushService.init,
            child: AuthGate(
              api: rootApi,
              title: '商家端 · 接单出餐',
              role: 'merchant',
              homeBuilder: (_, api) => ShopGate(api: api),
            ),
          )),
    );
  }
}

/// 审核状态门禁:没申请→申请表单;待审核→等待页;被驳回→表单+原因;通过→接单页
class ShopGate extends StatefulWidget {
  const ShopGate({super.key, required this.api});

  final ApiClient api;

  @override
  State<ShopGate> createState() => _ShopGateState();
}

class _ShopGateState extends State<ShopGate> {
  Merchant? _shop;
  bool _loaded = false;
  String? _error;
  Timer? _pollTimer;

  @override
  void initState() {
    super.initState();
    _load();
    // 待审核期间轮询,管理员一点通过,商家端自动进入接单页
    _pollTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (_shop != null && _shop!.isPending) _load();
    });
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final shop = await widget.api.myShop();
      if (mounted) {
        setState(() {
          _shop = shop;
          _loaded = true;
          _error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _loaded = true;
          _error = e.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!_loaded) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_error != null) {
      return Scaffold(
        body: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(_error!),
            const SizedBox(height: 12),
            FilledButton(onPressed: _load, child: const Text('重试')),
          ]),
        ),
      );
    }
    final shop = _shop;
    if (shop == null || shop.isRejected) {
      return ApplyShopPage(api: widget.api, existing: shop, onSubmitted: _load);
    }
    if (shop.isPending) {
      return Scaffold(
        appBar: AppBar(title: const Text('入驻审核中')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.hourglass_top, size: 56),
                const SizedBox(height: 16),
                Text('「${shop.name}」已提交审核',
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 8),
                Text(
                    shop.bizType == 'hotel'
                        ? '平台正在核对你的营业执照与特种行业许可证,通过后自动进入工作台'
                        : '平台正在核对你的食品经营许可证,通过后自动进入接单页',
                    textAlign: TextAlign.center),
              ],
            ),
          ),
        ),
      );
    }
    // 业态分叉:同一个 App,登录后按 biz_type 进入不同工作台
    if (shop.bizType == 'hotel') {
      return HotelHomePage(api: widget.api, shop: shop, onShopChanged: _load);
    }
    return MerchantHomePage(api: widget.api, shop: shop);
  }
}

/// 开店申请 / 被驳回后重新提交
class ApplyShopPage extends StatefulWidget {
  const ApplyShopPage({
    super.key,
    required this.api,
    this.existing,
    required this.onSubmitted,
  });

  final ApiClient api;
  final Merchant? existing; // 非空 = 被驳回后重新提交
  final VoidCallback onSubmitted;

  @override
  State<ApplyShopPage> createState() => _ApplyShopPageState();
}

class _ApplyShopPageState extends State<ApplyShopPage> {
  late final _name = TextEditingController(text: widget.existing?.name ?? '');
  late final _description =
      TextEditingController(text: widget.existing?.description ?? '');
  late final _address =
      TextEditingController(text: widget.existing?.address ?? '');
  final _licenseNo = TextEditingController();
  late String _category = widget.existing?.category ?? 'fast_food';
  // 业态:第一步选择,决定后续收哪些证照(重新提交时沿用原业态)
  late String _bizType = widget.existing?.bizType ?? 'food';
  String _licenseImageUrl = '';
  bool _uploading = false;
  bool _busy = false;

  // 酒店专属
  final _frontDeskPhone = TextEditingController();
  final _specialLicenseNo = TextEditingController();
  String _tier = 'economy';
  String _specialLicenseImageUrl = '';
  String _hygieneImageUrl = '';

  // 演示坐标;接高德 POI 选点后替换
  static const _lat = 30.6598;
  static const _lng = 104.0810;

  bool get _isHotel => _bizType == 'hotel';

  Future<String?> _uploadPicked() async {
    if (!await PermissionRationale.ensure(context, AppPermissionKind.photos,
        reason: '用于选取经营证照图片并上传。\n拒绝不影响其他功能。')) {
      return null;
    }
    final picked = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: 1600, // 证照要能看清文字,分辨率比菜品图高
      imageQuality: 90,
    );
    if (picked == null) return null;
    setState(() => _uploading = true);
    try {
      final bytes = await picked.readAsBytes();
      // 经营证照:私密桶,只有店主和管理员看得到(#124)
      return await widget.api
          .uploadImage(bytes, picked.name, purpose: 'license');
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('上传失败:$e')));
      }
      return null;
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  Future<void> _submit() async {
    final licenseLabel = _isHotel ? '营业执照注册号' : '食品经营许可证号';
    if (_name.text.trim().isEmpty ||
        _address.text.trim().isEmpty ||
        _licenseNo.text.trim().isEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('店名、地址、$licenseLabel都是必填的')));
      return;
    }
    if (_licenseImageUrl.isEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('请上传$licenseLabel照片(监管要求)')));
      return;
    }
    if (_isHotel &&
        (_specialLicenseNo.text.trim().isEmpty ||
            _specialLicenseImageUrl.isEmpty)) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('酒店入驻需要特种行业许可证(旅馆业,公安核发)号与照片')));
      return;
    }
    setState(() => _busy = true);
    try {
      if (widget.existing == null) {
        await widget.api.applyShop(
          name: _name.text.trim(),
          description: _description.text.trim(),
          address: _address.text.trim(),
          lat: _lat,
          lng: _lng,
          licenseNo: _licenseNo.text.trim(),
          licenseImageUrl: _licenseImageUrl,
          category: _category,
          bizType: _bizType,
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
      } else {
        await widget.api.updateShop({
          'name': _name.text.trim(),
          'description': _description.text.trim(),
          'address': _address.text.trim(),
          'license_no': _licenseNo.text.trim(),
          'license_image_url': _licenseImageUrl,
          if (!_isHotel) 'category': _category,
        });
      }
      widget.onSubmitted();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// 证照上传框(入驻通用):点击选图,回显缩略图
  Widget _licenseUpload({
    required String label,
    required String url,
    required ValueChanged<String> onUploaded,
  }) {
    return InkWell(
      onTap: _uploading
          ? null
          : () async {
              final uploaded = await _uploadPicked();
              if (uploaded != null && mounted) onUploaded(uploaded);
            },
      borderRadius: BorderRadius.circular(8),
      child: Container(
        height: 140,
        decoration: BoxDecoration(
          border: Border.all(color: Theme.of(context).colorScheme.outline),
          borderRadius: BorderRadius.circular(8),
        ),
        clipBehavior: Clip.antiAlias,
        child: _uploading
            ? const Center(child: CircularProgressIndicator())
            : url.isEmpty
                ? Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.add_a_photo_outlined, size: 32),
                      const SizedBox(height: 8),
                      Text(label, style: Theme.of(context).textTheme.bodySmall),
                    ],
                  )
                : Image(
                    image: szNetImage(widget.api.resolveUrl(url)),
                    fit: BoxFit.cover,
                    width: double.infinity,
                  ),
      ),
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
            : () => setState(() => _bizType = value),
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

  @override
  Widget build(BuildContext context) {
    final rejected = widget.existing?.isRejected == true;
    return SzUnsavedGuard(
      // 入驻表单是转化率最关键的一屏:填了店名/地址/证照号或传了证照图,
      // 误触返回就得从头再来
      isDirty: () =>
          _name.text.trim().isNotEmpty ||
          _address.text.trim().isNotEmpty ||
          _licenseNo.text.trim().isNotEmpty ||
          _licenseImageUrl.isNotEmpty ||
          _specialLicenseNo.text.trim().isNotEmpty ||
          _specialLicenseImageUrl.isNotEmpty ||
          _hygieneImageUrl.isNotEmpty,
      message: '店名、证照这些还没提交,现在返回会丢掉。',
      child: Scaffold(
        appBar: AppBar(title: Text(rejected ? '重新提交申请' : '申请入驻')),
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (rejected)
              Card(
                color: Theme.of(context).colorScheme.errorContainer,
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text('上次申请被驳回:${widget.existing!.rejectReason}\n'
                      '请修改后重新提交'),
                ),
              ),
            const SizedBox(height: 8),
            // 第一步:选业态(证照要求不同;重新提交沿用原业态)
            Row(children: [
              _bizTypeCard(
                  'food', Icons.restaurant, '餐饮外卖', '佣金 5% 封顶\n配送费全归骑手'),
              const SizedBox(width: 12),
              _bizTypeCard('hotel', Icons.hotel, '酒店住宿', '佣金 5%,离店才收\n取消分文不收'),
            ]),
            const SizedBox(height: 16),
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
            const SizedBox(height: 12),
            if (!_isHotel) ...[
              // 外卖品类:决定出现在用户端哪个分类,入驻后可随时改
              DropdownButtonFormField<String>(
                initialValue: _category,
                decoration: const InputDecoration(
                    labelText: '外卖品类 *', border: OutlineInputBorder()),
                items: [
                  for (final e in kMerchantCategories.entries)
                    DropdownMenuItem(
                        value: e.key,
                        child: Text(
                            '${kMerchantCategoryEmoji[e.key] ?? ''} ${e.value}')),
                ],
                onChanged: (v) => setState(() => _category = v ?? 'fast_food'),
              ),
              const SizedBox(height: 12),
            ] else ...[
              DropdownButtonFormField<String>(
                initialValue: _tier,
                decoration: const InputDecoration(
                    labelText: '酒店档次 *', border: OutlineInputBorder()),
                items: [
                  for (final e in kHotelTiers.entries)
                    DropdownMenuItem(value: e.key, child: Text(e.value)),
                ],
                onChanged: (v) => setState(() => _tier = v ?? 'economy'),
              ),
              const SizedBox(height: 12),
              TextField(
                  controller: _frontDeskPhone,
                  keyboardType: TextInputType.phone,
                  decoration: const InputDecoration(
                      labelText: '前台电话',
                      helperText: '展示给已下单的住客,方便到店联系',
                      border: OutlineInputBorder())),
              const SizedBox(height: 12),
            ],
            TextField(
                controller: _licenseNo,
                decoration: InputDecoration(
                    labelText: _isHotel ? '营业执照注册号 *' : '食品经营许可证号 *',
                    helperText: '平台会人工核对,信息不实将无法通过审核',
                    border: const OutlineInputBorder())),
            const SizedBox(height: 12),
            // 证照照片(监管要求留存影像,审核员对照证号人工核验)
            _licenseUpload(
              label: _isHotel ? '上传营业执照照片 *' : '上传食品经营许可证照片 *',
              url: _licenseImageUrl,
              onUploaded: (u) => setState(() => _licenseImageUrl = u),
            ),
            if (_isHotel) ...[
              const SizedBox(height: 12),
              TextField(
                  controller: _specialLicenseNo,
                  decoration: const InputDecoration(
                      labelText: '特种行业许可证号(旅馆业) *',
                      helperText: '公安机关核发,开旅馆的硬性资质',
                      border: OutlineInputBorder())),
              const SizedBox(height: 12),
              _licenseUpload(
                label: '上传特种行业许可证照片 *',
                url: _specialLicenseImageUrl,
                onUploaded: (u) => setState(() => _specialLicenseImageUrl = u),
              ),
              const SizedBox(height: 12),
              _licenseUpload(
                label: '上传卫生许可证照片(选填)',
                url: _hygieneImageUrl,
                onUploaded: (u) => setState(() => _hygieneImageUrl = u),
              ),
            ],
            const SizedBox(height: 24),
            FilledButton(
              onPressed: _busy ? null : _submit,
              child: Text(_busy ? '提交中…' : (rejected ? '重新提交审核' : '提交申请')),
            ),
          ],
        ),
      ),
    );
  }
}

class MerchantHomePage extends StatefulWidget {
  const MerchantHomePage({super.key, required this.api, required this.shop});

  final ApiClient api;
  final Merchant shop;

  @override
  State<MerchantHomePage> createState() => _MerchantHomePageState();
}

class _MerchantHomePageState extends State<MerchantHomePage> {
  int _tab = 0;
  int _segment = 0; // 0 待接单 / 1 进行中 / 2 历史
  List<Order> _orders = [];
  late bool _isOpen = widget.shop.isOpen;
  Timer? _timer;
  Timer? _alertTimer;
  Timer? _wsPing;
  WebSocketChannel? _ws;
  bool _wsConnected = false;

  final OrderAnnouncer _announcer = OrderAnnouncer();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      checkForUpdate(context, baseUrl: widget.api.baseUrl, app: 'merchant');
      // 锁屏不丢单三件套:权限引导 → 前台服务 → 语音催单
      await ListenKeepAlive.ensurePermissions(context);
      await ListenKeepAlive.start();
    });
    _refresh();
    // 轮询保底(WebSocket 断线期间也不会漏单)
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _refresh());
    // 持续催单:只要有待接订单,每 10 秒语音播报一次,直到商家处理
    _alertTimer = Timer.periodic(const Duration(seconds: 10), (_) {
      if (_orders.any((o) => o.status == OrderStatus.paid)) {
        _announcer.announce();
      }
    });
    _connectWs();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _alertTimer?.cancel();
    _wsPing?.cancel();
    _ws?.sink.close();
    _announcer.dispose();
    ListenKeepAlive.stop();
    super.dispose();
  }

  /// 实时听单通道:新单推送 → 响铃 + 振动 + 横幅
  void _connectWs() {
    final uri = Uri.parse(
        '${widget.api.wsBaseUrl}/ws/merchants/${widget.shop.id}?token=${widget.api.token}');
    try {
      _ws = WebSocketChannel.connect(uri);
    } catch (_) {
      _scheduleReconnect();
      return;
    }
    _wsPing?.cancel();
    _wsPing = Timer.periodic(
        const Duration(seconds: 30), (_) => _ws?.sink.add('ping'));
    _ws!.stream.listen(
      (message) {
        if (!_wsConnected && mounted) setState(() => _wsConnected = true);
        final data = jsonDecode(message as String) as Map<String, dynamic>;
        if (data['type'] == 'new_order') {
          _announcer.announce();
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              content: Text(
                  '🔔 新订单:${data['summary']} ${yuan(data['total_cents'] as int)}'),
              duration: const Duration(seconds: 5),
            ));
          }
          _refresh();
        } else if (data['type'] == 'urge') {
          // 用户催单:语音 + 橙色横幅 + 一键回复
          _announcer.announce();
          final no = data['order_no'] as String;
          if (mounted) {
            setState(() => _urgedOrders.add(no));
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              backgroundColor: Theme.of(context).sz.hold,
              duration: const Duration(seconds: 8),
              content: Text('🔥 用户催单:${data['summary']}'),
              action: SnackBarAction(
                label: '回复:马上好',
                textColor: Colors.white,
                onPressed: () async {
                  try {
                    await widget.api.urgeReply(no, '马上好,正在加急制作!');
                    _snack('已回复用户');
                  } catch (e) {
                    _snack(e is ApiException ? e.message : '$e');
                  }
                },
              ),
            ));
          }
        }
      },
      onError: (_) => _scheduleReconnect(),
      onDone: _scheduleReconnect,
    );
  }

  void _scheduleReconnect() {
    if (!mounted) return;
    setState(() => _wsConnected = false);
    Timer(const Duration(seconds: 5), () {
      if (mounted) _connectWs();
    });
  }

  Future<void> _refresh() async {
    try {
      final orders = await widget.api.myOrders();
      if (mounted) setState(() => _orders = orders);
      _autoPrintNew(orders);
    } catch (_) {}
  }

  // ---------- 蓝牙自动出票 ----------
  // 云打印在服务端支付成功时直推,这里只管蓝牙这条本地通道。
  // 首次加载只登记不打印:App 重启时不给列表里的存量待接单补打(要打点卡片上的按钮)
  final Set<String> _btPrinted = {};
  final Set<String> _urgedOrders = {}; // 被催过的订单,卡片打标
  bool _btSeeded = false;

  Future<void> _autoPrintNew(List<Order> orders) async {
    final paid = orders.where((o) => o.status == OrderStatus.paid).toList();
    if (!_btSeeded) {
      _btSeeded = true;
      _btPrinted.addAll(paid.map((o) => o.orderNo));
      return;
    }
    if (!await BtPrinter.autoPrintEnabled()) return;
    for (final order in paid) {
      if (!_btPrinted.add(order.orderNo)) continue; // 已打过(WS 和轮询会重复看到)
      final err = await BtPrinter.printOrder(order, shopName: widget.shop.name);
      if (err != null && err != 'NO_DEVICE' && mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('蓝牙打印失败:$err')));
      }
    }
  }

  /// 手动打小票:蓝牙优先(即时),没配蓝牙走云打印补打
  Future<void> _printTicket(Order order) async {
    final err = await BtPrinter.printOrder(order, shopName: widget.shop.name);
    if (err == null) return _snack('小票已发送到蓝牙打印机');
    if (err != 'NO_DEVICE') return _snack(err);
    try {
      await widget.api.reprintOrder(order.orderNo);
      _snack('小票已发送到云打印机');
    } catch (e) {
      _snack(e is ApiException ? '${e.message}(在「店铺-小票打印」里设置打印机)' : '打印失败:$e');
    }
  }

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  /// 在途的状态流转(按单号):接单/出餐/开始配送/已送达都走 _act,
  /// 连点两下会发两个请求,第二个被服务端拒绝后弹一个错误——
  /// 老板会以为没接上。骑手端抢单原先也有同样的问题。
  final Set<String> _acting = {};

  Future<void> _act(Order order, OrderStatus to) async {
    if (_acting.contains(order.orderNo)) return;
    setState(() => _acting.add(order.orderNo));
    try {
      await widget.api.transition(order.orderNo, to);
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _acting.remove(order.orderNo));
    }
  }

  Future<void> _reject(Order order) async {
    final controller = TextEditingController(text: '菜品售罄,暂时无法接单');
    final reason = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('拒单原因'),
        content: TextField(
          controller: controller,
          maxLength: 200,
          decoration: const InputDecoration(
              helperText: '会展示给用户,订单将全额退款', border: OutlineInputBorder()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: const Text('确认拒单')),
        ],
      ),
    );
    if (reason == null || reason.length < 2) return;
    try {
      await widget.api
          .transition(order.orderNo, OrderStatus.cancelled, reason: reason);
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 缺货退款:弹层选菜品和份数,退对应的钱(不用整单拒)
  Future<void> _refundSheet(Order order) async {
    final result = await showModalBottomSheet<(int, int)>(
      context: context,
      builder: (sheetContext) {
        int? selectedDish;
        int quantity = 1;
        return StatefulBuilder(
          builder: (sheetContext, setSheet) {
            final maxQty = selectedDish == null
                ? 1
                : order.items
                    .firstWhere((i) => i.dishId == selectedDish)
                    .quantity;
            return SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('缺货退款',
                        style: Theme.of(context).textTheme.titleMedium),
                    const SizedBox(height: 4),
                    Text('选择缺货的菜品,对应金额将退给用户',
                        style: Theme.of(context).textTheme.bodySmall),
                    const SizedBox(height: 8),
                    // 0 元赠品行不可选(无款可退,服务端也会拒)
                    for (final item
                        in order.items.where((i) => i.priceCents > 0))
                      ListTile(
                        dense: true,
                        selected: selectedDish == item.dishId,
                        leading: Icon(
                          selectedDish == item.dishId
                              ? Icons.radio_button_checked
                              : Icons.radio_button_off,
                          color: selectedDish == item.dishId
                              ? Theme.of(context).colorScheme.primary
                              : null,
                        ),
                        title: Text('${item.name}(共 ${item.quantity} 份)'),
                        onTap: () => setSheet(() {
                          selectedDish = item.dishId;
                          quantity = 1;
                        }),
                      ),
                    if (selectedDish != null)
                      Row(
                        children: [
                          const Text('退货份数'),
                          const Spacer(),
                          IconButton(
                            tooltip: '减少',
                            icon: const Icon(Icons.remove_circle_outline),
                            onPressed: quantity > 1
                                ? () => setSheet(() => quantity--)
                                : null,
                          ),
                          Text('$quantity'),
                          IconButton(
                            tooltip: '增加',
                            icon: const Icon(Icons.add_circle_outline),
                            onPressed: quantity < maxQty
                                ? () => setSheet(() => quantity++)
                                : null,
                          ),
                        ],
                      ),
                    const SizedBox(height: 8),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: selectedDish == null
                            ? null
                            : () => Navigator.pop(
                                sheetContext, (selectedDish!, quantity)),
                        child: const Text('确认退款'),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
    if (result == null || !mounted) return;
    try {
      final updated =
          await widget.api.refundItem(order.orderNo, result.$1, result.$2);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(updated.status == OrderStatus.cancelled
              ? '已全部退款,订单取消'
              : '已退款,订单金额已更新')));
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 自取单核销:输入顾客报的取餐码 → 订单完成并结算
  Future<void> _verifyPickup(Order order) async {
    final controller = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('核销取餐码'),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.number,
          maxLength: 4,
          decoration: const InputDecoration(
              labelText: '顾客报的 4 位取餐码', border: OutlineInputBorder()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('确认交餐')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await widget.api.pickupVerify(order.orderNo, controller.text.trim());
      _snack('已交餐,订单完成');
      _refresh();
    } catch (e) {
      _snack(e is ApiException ? e.message : '$e');
    }
  }

  /// 备餐计时:接单后已耗时;出餐超时(server 定格 readyLate)用 danger 高亮
  Widget _prepTimer(Order order) {
    final raw = order.acceptedAt;
    if (raw == null) return const SizedBox.shrink();
    final accepted = DateTime.tryParse(raw)?.toLocal();
    if (accepted == null) return const SizedBox.shrink();
    final mins = DateTime.now().difference(accepted).inMinutes;
    final late = order.readyLate;
    final sz = Theme.of(context).sz;
    final color = late ? sz.danger : sz.inkMuted;
    return Padding(
      padding: const EdgeInsets.only(top: 3),
      child: Row(children: [
        Icon(late ? Icons.local_fire_department : Icons.timer_outlined,
            size: 13, color: color),
        const SizedBox(width: 4),
        Text.rich(
          TextSpan(children: [
            TextSpan(text: late ? '出餐超时 · 已备餐 ' : '备餐中 · 已 '),
            TextSpan(text: '$mins', style: szFigure(fontSize: 12)),
            TextSpan(text: late ? ' 分钟,尽快出餐' : ' 分钟'),
          ]),
          style: TextStyle(
              color: color,
              fontSize: 12,
              fontWeight: late ? FontWeight.w600 : FontWeight.w400),
        ),
      ]),
    );
  }

  /// 待接单计时:顾客已经等了多久。商家端最该被盯住的数字。
  Widget _waitTimer(Order order) {
    final created = DateTime.tryParse(order.createdAt)?.toLocal();
    if (created == null) return const SizedBox.shrink();
    final mins = DateTime.now().difference(created).inMinutes;
    final sz = Theme.of(context).sz;
    final urgent = mins >= 3;
    return Padding(
      padding: const EdgeInsets.only(top: 3),
      child: Text.rich(
        TextSpan(children: [
          const TextSpan(text: '顾客已等 '),
          TextSpan(
              text: '$mins',
              style: szFigure(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: urgent ? sz.danger : sz.ink)),
          const TextSpan(text: ' 分钟'),
        ]),
        style: TextStyle(fontSize: 12, color: urgent ? sz.danger : sz.inkMuted),
      ),
    );
  }

  List<Widget> _actionsFor(Order order) {
    final printButton = Row(mainAxisSize: MainAxisSize.min, children: [
      IconButton(
        tooltip: '和顾客说句话',
        icon: const Icon(Icons.chat_bubble_outline, size: 20),
        onPressed: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => OrderChatPage(
                api: widget.api,
                orderNo: order.orderNo,
                title: '和顾客说句话',
                quickReplies: kMerchantQuickReplies))),
      ),
      IconButton(
        tooltip: '打印小票',
        icon: const Icon(Icons.print_outlined, size: 20),
        onPressed: () => _printTicket(order),
      ),
    ]);
    switch (order.status) {
      case OrderStatus.paid:
        return [
          printButton,
          TextButton(
              onPressed: () => _refundSheet(order), child: const Text('缺货退款')),
          OutlinedButton(
              onPressed: () => _reject(order), child: const Text('拒单')),
          const SizedBox(width: 8),
          FilledButton(
              onPressed: _acting.contains(order.orderNo)
                  ? null
                  : () => _act(order, OrderStatus.accepted),
              child: Text(_acting.contains(order.orderNo) ? '处理中…' : '接单')),
        ];
      case OrderStatus.accepted:
        return [
          printButton,
          TextButton(
              onPressed: () => _refundSheet(order), child: const Text('缺货退款')),
          const SizedBox(width: 8),
          FilledButton(
              onPressed: _acting.contains(order.orderNo)
                  ? null
                  : () => _act(order, OrderStatus.ready),
              child: Text(_acting.contains(order.orderNo) ? '处理中…' : '出餐完成')),
        ];
      case OrderStatus.ready:
        return [
          printButton,
          if (order.pickup) ...[
            const SizedBox(width: 8),
            FilledButton.icon(
                icon: const Icon(Icons.qr_code, size: 18),
                onPressed: () => _verifyPickup(order),
                label: const Text('核销取餐码')),
          ],
          if (order.selfDelivery) ...[
            const SizedBox(width: 8),
            // 出发前先看清送去哪、多远。远近全靠猜的话,
            // 猜错就是自己骑半小时送一单 3 块钱配送费的活
            OutlinedButton.icon(
                icon: const Icon(Icons.map_outlined, size: 18),
                onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                        builder: (_) => SelfDeliveryMapPage(order: order))),
                label: const Text('地图')),
            const SizedBox(width: 8),
            FilledButton.icon(
                icon: const Icon(Icons.delivery_dining, size: 18),
                onPressed: () => _act(order, OrderStatus.pickedUp),
                label: const Text('开始配送(自送)')),
          ],
        ];
      case OrderStatus.pickedUp:
        return [
          printButton,
          // 自送的商家在路上,和骑手是同一种处境:需要导航,而不是一行文字地址。
          // 此前商家端全程没有地图,自送只能对着地址自己找
          if (order.selfDelivery) ...[
            const SizedBox(width: 8),
            OutlinedButton.icon(
                icon: const Icon(Icons.navigation_outlined, size: 18),
                onPressed: () => navigateTo(context,
                    lat: order.lat,
                    lng: order.lng,
                    name: order.address,
                    mode: NavMode.ride),
                label: const Text('导航')),
            const SizedBox(width: 8),
            FilledButton(
                onPressed: () => _act(order, OrderStatus.delivered),
                child: const Text('已送达')),
          ],
        ];
      default:
        return const [];
    }
  }

  List<Order> get _filteredOrders {
    const ongoing = {
      OrderStatus.accepted,
      OrderStatus.ready,
      OrderStatus.pickedUp,
    };
    return switch (_segment) {
      0 => _orders.where((o) => o.status == OrderStatus.paid).toList(),
      1 => _orders.where((o) => ongoing.contains(o.status)).toList(),
      _ => _orders
          .where((o) =>
              o.status == OrderStatus.delivered ||
              o.status == OrderStatus.completed ||
              o.status == OrderStatus.cancelled)
          .toList(),
    };
  }

  @override
  Widget build(BuildContext context) {
    final pending = _orders.where((o) => o.status == OrderStatus.paid).length;
    return Scaffold(
      appBar: AppBar(
        title: Text(switch (_tab) {
          1 => '菜品管理',
          2 => '对账',
          3 => '店铺',
          _ => pending > 0 ? '订单($pending 单待接)' : '订单',
        }),
        actions: [
          Row(children: [
            Icon(
              _wsConnected
                  ? Icons.notifications_active
                  : Icons.notifications_off,
              size: 18,
              color: _wsConnected
                  ? Theme.of(context).sz.earn
                  : Theme.of(context).sz.inkFaint,
            ),
            const SizedBox(width: 8),
            Text(_isOpen ? '营业中' : '已打烊'),
            Switch(
              value: _isOpen,
              onChanged: (v) async {
                setState(() => _isOpen = v);
                try {
                  await widget.api.setShopOpen(v);
                } catch (e) {
                  setState(() => _isOpen = !v);
                }
              },
            ),
            const SizedBox(width: 8),
          ]),
        ],
      ),
      body: _tab == 1
          ? DishManagePage(api: widget.api)
          : _tab == 2
              ? FinancePage(api: widget.api)
              : _tab == 3
                  ? ShopTabPage(api: widget.api)
                  : Column(
                      children: [
                        // 平台公告(费率调整、新功能上线等,发通知不用发版)
                        AnnouncementBanner(
                            api: widget.api, audience: 'merchant'),
                        Padding(
                          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
                          child: SegmentedButton<int>(
                            segments: const [
                              ButtonSegment(value: 0, label: Text('待接单')),
                              ButtonSegment(value: 1, label: Text('进行中')),
                              ButtonSegment(value: 2, label: Text('历史')),
                            ],
                            selected: {_segment},
                            onSelectionChanged: (s) =>
                                setState(() => _segment = s.first),
                          ),
                        ),
                        Expanded(
                          child: RefreshIndicator(
                            onRefresh: _refresh,
                            child: _filteredOrders.isEmpty
                                ? ListView(children: const [
                                    Padding(
                                        padding: EdgeInsets.all(24),
                                        child: Center(child: Text('这一栏没有订单')))
                                  ])
                                : ListView.builder(
                                    itemCount: _filteredOrders.length,
                                    itemBuilder: (context, i) {
                                      final order = _filteredOrders[i];
                                      final sz = Theme.of(context).sz;
                                      final isNew =
                                          order.status == OrderStatus.paid;
                                      return Container(
                                        margin: const EdgeInsets.symmetric(
                                            horizontal: 12, vertical: 5),
                                        decoration: BoxDecoration(
                                          color: sz.surface,
                                          borderRadius:
                                              BorderRadius.circular(kRadiusMd),
                                          border: Border.all(
                                              // 出餐超时:整卡 danger 描边,后厨一眼看到该催
                                              color: order.readyLate
                                                  ? sz.danger
                                                  : sz.line,
                                              width: order.readyLate ? 1.5 : 1),
                                        ),
                                        // 新单左侧一条 clay:待接单的在列表里要一眼挑出来
                                        foregroundDecoration: isNew
                                            ? BoxDecoration(
                                                borderRadius:
                                                    BorderRadius.circular(
                                                        kRadiusMd),
                                                border: Border(
                                                    left: BorderSide(
                                                        color: sz.clay,
                                                        width: 3)),
                                              )
                                            : null,
                                        child: Padding(
                                          padding: const EdgeInsets.fromLTRB(
                                              12, 11, 12, 11),
                                          child: Column(
                                            crossAxisAlignment:
                                                CrossAxisAlignment.start,
                                            children: [
                                              Row(
                                                  crossAxisAlignment:
                                                      CrossAxisAlignment.start,
                                                  children: [
                                                    Expanded(
                                                        child: Text(
                                                            order.summary,
                                                            style: TextStyle(
                                                                fontSize: 14.5,
                                                                fontWeight:
                                                                    FontWeight
                                                                        .w600,
                                                                color:
                                                                    sz.ink))),
                                                    const SizedBox(width: 8),
                                                    SzChip(order.status.label,
                                                        color: isNew
                                                            ? sz.clay
                                                            : sz.inkFaint,
                                                        dense: true),
                                                  ]),
                                              const SizedBox(height: 5),
                                              Wrap(
                                                  spacing: 6,
                                                  runSpacing: 4,
                                                  children: [
                                                    if (order.parentOrderNo
                                                        .isNotEmpty)
                                                      SzChip(
                                                          '加·随${order.parentOrderNo.substring(order.parentOrderNo.length - 6)}',
                                                          color: sz.earn,
                                                          dense: true),
                                                    if (_urgedOrders.contains(
                                                        order.orderNo))
                                                      SzChip('催',
                                                          color: sz.danger,
                                                          dense: true),
                                                    if (order.pickup)
                                                      SzChip(
                                                          order.pickupCode
                                                                  .isEmpty
                                                              ? '自取'
                                                              : '自取 ${order.pickupCode}',
                                                          color: sz.hold,
                                                          dense: true),
                                                  ]),
                                              if (order.scheduledLabel != null)
                                                Padding(
                                                  padding:
                                                      const EdgeInsets.only(
                                                          top: 4),
                                                  child: Text(
                                                      '⏰ ${order.scheduledLabel},请按时出餐',
                                                      style: TextStyle(
                                                          fontSize: 12,
                                                          color: sz.hold,
                                                          fontWeight:
                                                              FontWeight.w600)),
                                                ),
                                              if (isNew) _waitTimer(order),
                                              // 备餐计时:接单后按承诺出餐时长计时,超时高亮
                                              if (order.status ==
                                                  OrderStatus.accepted)
                                                _prepTimer(order),
                                              const SizedBox(height: 5),
                                              Row(children: [
                                                Text(yuan(order.totalCents),
                                                    style: szMoney(
                                                        fontSize: 14,
                                                        fontWeight:
                                                            FontWeight.w600,
                                                        color: sz.ink)),
                                                const SizedBox(width: 8),
                                                Expanded(
                                                  child: Text(order.address,
                                                      maxLines: 1,
                                                      overflow:
                                                          TextOverflow.ellipsis,
                                                      style: TextStyle(
                                                          fontSize: 12,
                                                          color: sz.inkMuted)),
                                                ),
                                              ]),
                                              if (order.remark.isNotEmpty)
                                                Text('备注:${order.remark}',
                                                    style: TextStyle(
                                                        fontSize: 12,
                                                        color: sz.inkMuted)),
                                              if (order.status ==
                                                      OrderStatus.cancelled &&
                                                  order.cancelReason.isNotEmpty)
                                                Text(
                                                    '取消原因:${order.cancelReason}',
                                                    style: TextStyle(
                                                        fontSize: 12,
                                                        color: sz.danger)),
                                              if (order.refundCents > 0)
                                                Text(
                                                    '已退款 ${yuan(order.refundCents)}(${order.refundNote})',
                                                    style: TextStyle(
                                                        fontSize: 12,
                                                        color: sz.danger)),
                                              if (_actionsFor(order)
                                                  .isNotEmpty) ...[
                                                const SizedBox(height: 6),
                                                Row(
                                                  mainAxisAlignment:
                                                      MainAxisAlignment.end,
                                                  children: _actionsFor(order),
                                                ),
                                              ],
                                            ],
                                          ),
                                        ),
                                      );
                                    },
                                  ),
                          ),
                        ),
                      ],
                    ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.receipt_long), label: '订单'),
          NavigationDestination(icon: Icon(Icons.restaurant_menu), label: '菜品'),
          NavigationDestination(icon: Icon(Icons.bar_chart), label: '对账'),
          NavigationDestination(icon: Icon(Icons.store), label: '店铺'),
        ],
      ),
    );
  }
}
