import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'address_pages.dart';
import 'append_order_page.dart';
import 'category_page.dart';
import 'checkout_page.dart';
import 'coupons_page.dart';
import 'group_cart_page.dart';
import 'invite_page.dart';
import 'share_card.dart';
import 'five_percent.dart';
import 'identity_page.dart';
import 'coming_soon_page.dart';
import 'delivery_map_page.dart';
import 'reviews_page.dart';
import 'search_page.dart';
import 'trust_page.dart';
import 'voucher_pages.dart';

// 定位失败(权限拒绝/模拟器没设位置)时的兜底坐标
const demoLat = 30.6612;
const demoLng = 104.0823;

/// 一次性获取当前位置(GCJ-02),失败静默退回演示坐标
Future<({double lat, double lng, bool real})> resolveMyLocation() async {
  try {
    if (!await Geolocator.isLocationServiceEnabled()) throw Exception();
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }
    if (permission == LocationPermission.denied ||
        permission == LocationPermission.deniedForever) {
      throw Exception();
    }
    final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
            accuracy: LocationAccuracy.high,
            timeLimit: Duration(seconds: 6)));
    final gcj = wgs84ToGcj02(position.latitude, position.longitude);
    return (lat: gcj.lat, lng: gcj.lng, real: true);
  } catch (_) {
    return (lat: demoLat, lng: demoLng, real: false);
  }
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // 推送 SDK 的初始化在用户同意隐私政策之后(PrivacyGate.onAgreed),
  // 同意前启动收集类 SDK 是应用商店审核红线
  // 长辈版(大字)开关:启动时从本地读一次,全程用 ValueNotifier 广播
  final prefs = await SharedPreferences.getInstance();
  elderMode.value = prefs.getBool(_elderKey) ?? false;
  runApp(const UserApp());
}

/// 长辈版大字模式(全局):开启后在系统字体缩放之上再放大,兼顾读屏用户已放大的场景
const _elderKey = 'elder_mode';
final ValueNotifier<bool> elderMode = ValueNotifier<bool>(false);

Future<void> setElderMode(bool on) async {
  elderMode.value = on;
  final prefs = await SharedPreferences.getInstance();
  await prefs.setBool(_elderKey, on);
}

/// 亮/暗双主题(跟随系统),用品牌体系(炉火橙,见 shared/brand.dart)。
ThemeData superZTheme(Brightness brightness) => brandTheme(brightness);

class UserApp extends StatelessWidget {
  const UserApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<bool>(
      valueListenable: elderMode,
      builder: (context, elder, _) => MaterialApp(
        title: '超级赞 · 点外卖',
        theme: superZTheme(Brightness.light),
        darkTheme: superZTheme(Brightness.dark),
        themeMode: ThemeMode.system,
        // 长辈版:字号放大到 1.4×(封顶,避免溢出);关闭则尊重系统缩放
        builder: (context, child) {
          final mq = MediaQuery.of(context);
          final scaler = elder
              ? const TextScaler.linear(1.4)
              : mq.textScaler.clamp(maxScaleFactor: 1.6);
          return MediaQuery(
              data: mq.copyWith(textScaler: scaler),
              child: child ?? const SizedBox.shrink());
        },
        home: SplashGate(
            app: 'user',
            tagline: '点外卖,每一单分账可查',
            subLines: const [
              '5% 佣金封顶,账本向所有人公开',
              '配送费一分不截留,全部归骑手',
              '让利于民 · 取之有道 · 账目为证',
            ],
            child:
                PrivacyGate(onAgreed: PushService.init, child: buildUserLogin())),
      ),
    );
  }
}

/// 登录入口(退出登录后也回到这里)
Widget buildUserLogin() {
  return SmsLoginPage(
    title: '用户端 · 点外卖',
    onLoggedIn: (context, api) => Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => HomePage(api: api))),
    // 演示账号(13800000001/123456)走这里
    passwordLoginBuilder: (_) => LoginPage(
      title: '用户端 · 密码登录',
      defaultPhone: '13800000001',
      onLoggedIn: (context, api) => Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => HomePage(api: api))),
    ),
  );
}

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _tab = 0;

  /// 顶部地址栏选中的收货地址;null = 用当前定位
  Address? _deliveryAddress;

  @override
  void initState() {
    super.initState();
    Analytics.instance.init(widget.api);
    WidgetsBinding.instance.addPostFrameCallback((_) =>
        checkForUpdate(context, baseUrl: widget.api.baseUrl, app: 'user'));
  }

  Future<void> _pickDeliveryAddress() async {
    final picked = await Navigator.of(context).push<Address>(MaterialPageRoute(
        builder: (_) => AddressBookPage(api: widget.api, selectMode: true)));
    if (picked != null && mounted) {
      setState(() => _deliveryAddress = picked);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: _tab == 0
            // 商业平台标配:顶部地址栏,让用户知道「附近」是哪儿附近
            ? InkWell(
                onTap: _pickDeliveryAddress,
                borderRadius: BorderRadius.circular(8),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.place,
                        size: 18,
                        color: Theme.of(context).colorScheme.primary),
                    const SizedBox(width: 4),
                    ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 190),
                      child: Text(
                        _deliveryAddress?.address ?? '当前位置',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w600),
                      ),
                    ),
                    const Icon(Icons.arrow_drop_down, size: 20),
                  ],
                ),
              )
            : Text(_tab == 1 ? '我的订单' : '我的'),
        actions: [
          // 搜索是主页第一交互,已做成显眼的大搜索框(点餐页顶部),
          // 这里只保留地址簿入口,避免图标堆积
          IconButton(
            icon: const Icon(Icons.place_outlined),
            tooltip: '收货地址',
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => AddressBookPage(api: widget.api))),
          ),
        ],
      ),
      // tab 切换:轻快的淡入 + 微上滑(120ms,不拖节奏)
      // 底部 tab 只放功能(首页/订单/我的),业务一律走金刚区——
      // 业务会持续增加(团购/打车/跑腿…),金刚区横向扩展,tab 保持稳定
      body: AnimatedSwitcher(
        duration: const Duration(milliseconds: 160),
        switchInCurve: Curves.easeOutCubic,
        transitionBuilder: (child, animation) => FadeTransition(
          opacity: animation,
          child: SlideTransition(
            position: Tween(
                    begin: const Offset(0, 0.015), end: Offset.zero)
                .animate(animation),
            child: child,
          ),
        ),
        child: switch (_tab) {
          0 => MerchantListView(
              key: const ValueKey('tab-food'),
              api: widget.api,
              deliveryAddress: _deliveryAddress),
          1 => OrderListView(key: const ValueKey('tab-order'), api: widget.api),
          _ => ProfileView(key: const ValueKey('tab-me'), api: widget.api),
        },
      ),
      // 图标手感:未选描边、选中实心,切换自带 M3 缩放指示
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(
              icon: Icon(Icons.storefront_outlined),
              selectedIcon: Icon(Icons.storefront),
              label: '首页'),
          NavigationDestination(
              icon: Icon(Icons.receipt_long_outlined),
              selectedIcon: Icon(Icons.receipt_long),
              label: '订单'),
          NavigationDestination(
              icon: Icon(Icons.person_outline),
              selectedIcon: Icon(Icons.person),
              label: '我的'),
        ],
      ),
    );
  }
}


/// 排序 chips 吸顶(滚动时钉在顶部,随时可换排序)。
class _PinnedChipsDelegate extends SliverPersistentHeaderDelegate {
  _PinnedChipsDelegate(this.child);

  final Widget child;

  @override
  double get minExtent => 52;
  @override
  double get maxExtent => 52;

  @override
  Widget build(BuildContext context, double shrinkOffset,
      bool overlapsContent) {
    return Container(
      color: Theme.of(context).scaffoldBackgroundColor,
      alignment: Alignment.centerLeft,
      child: child,
    );
  }

  @override
  bool shouldRebuild(covariant _PinnedChipsDelegate old) =>
      old.child != child;
}

class MerchantListView extends StatefulWidget {
  const MerchantListView(
      {super.key, required this.api, this.deliveryAddress, this.category});

  final ApiClient api;

  /// 顶部地址栏选中的地址;null = 用手机定位
  final Address? deliveryAddress;

  /// 品类模式(外卖二级页):null = 首页模式(搜索栏+金刚区+再来一单);
  /// '' = 推荐(不过滤,不带首页头部);slug = 按品类过滤
  final String? category;

  @override
  State<MerchantListView> createState() => _MerchantListViewState();
}

class _MerchantListViewState extends State<MerchantListView> {
  bool _realLocation = true;
  double _myLat = demoLat;
  double _myLng = demoLng;
  String _sort = 'distance';
  late Future<List<Merchant>> _future = _load();

  /// 再来一单:最近点过的店(按商家去重,最多 6 家)
  List<Order> _reorder = [];

  @override
  void initState() {
    super.initState();
    _loadRecent();
  }

  Future<void> _loadRecent() async {
    try {
      final orders = await widget.api.myOrders();
      final seen = <int>{};
      final recent = <Order>[];
      for (final o in orders) {
        if (o.status != OrderStatus.completed &&
            o.status != OrderStatus.delivered) {
          continue;
        }
        if (seen.add(o.merchantId)) recent.add(o);
        if (recent.length >= 6) break;
      }
      if (mounted) setState(() => _reorder = recent);
    } catch (_) {}
  }

  /// 一键回购:拉店铺详情,带上历史购物车进店(缺货/带规格的菜会被过滤/重选)
  Future<void> _openReorder(Order order) async {
    try {
      final merchant = await widget.api.merchantDetail(order.merchantId);
      if (!mounted) return;
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => MenuPage(
                api: widget.api,
                merchant: merchant,
                initialCart: {
                  for (final it in order.items)
                    if (it.dishId != 0) it.dishId: it.quantity,
                },
              )));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  void didUpdateWidget(MerchantListView old) {
    super.didUpdateWidget(old);
    if (old.deliveryAddress?.id != widget.deliveryAddress?.id) {
      setState(() => _future = _load());
    }
  }

  Future<List<Merchant>> _load() async {
    final address = widget.deliveryAddress;
    if (address != null) {
      _realLocation = true; // 用户手选地址,视为精确
      _myLat = address.lat;
      _myLng = address.lng;
    } else {
      final location = await resolveMyLocation();
      _realLocation = location.real; // FutureBuilder 完成时会重建,无需 setState
      _myLat = location.lat;
      _myLng = location.lng;
    }
    return widget.api.merchants(
        lat: _myLat, lng: _myLng, sort: _sort, category: widget.category);
  }

  /// 空品类招商位:该品类还没有商家,把空状态变成入驻引导
  Widget _categoryVacancy() {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(24, 48, 24, 24),
      child: Column(children: [
        Icon(Icons.storefront_outlined,
            size: 56, color: theme.colorScheme.outline),
        const SizedBox(height: 12),
        const Text('该品类商家入驻中', style: TextStyle(fontSize: 16)),
        const SizedBox(height: 6),
        Text('总负担 5% 封顶 · 入驻免费 · 没有竞价排名',
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.outline)),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          icon: const Icon(Icons.storefront, size: 18),
          label: const Text('我有店,去入驻'),
          onPressed: () => launchUrl(
              Uri.parse('${widget.api.baseUrl}/join/merchant'),
              mode: LaunchMode.externalApplication),
        ),
      ]),
    );
  }

  Widget _sortChips() {
    const options = [
      ('distance', '综合'),
      ('rating', '评分优先'),
      ('sales', '月售优先'),
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: Row(
        children: [
          for (final (value, label) in options)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(label),
                selected: _sort == value,
                visualDensity: VisualDensity.compact,
                onSelected: (_) => setState(() {
                  _sort = value;
                  _future = _load();
                }),
              ),
            ),
        ],
      ),
    );
  }

  /// 大搜索框:商业外卖首页的第一交互,直接可见可点(不藏在图标里)。
  /// 不放口号横幅——信任靠订单里可查的账单传达,不靠喊。
  Widget _searchBar() {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: InkWell(
        borderRadius: BorderRadius.circular(24),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) =>
                SearchPage(api: widget.api, lat: _myLat, lng: _myLng))),
        child: Container(
          height: 44,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            color: theme.brightness == Brightness.light
                ? Colors.white
                : theme.colorScheme.surfaceContainerHigh,
            borderRadius: BorderRadius.circular(24),
            border: Border.all(
                color: theme.colorScheme.primary.withValues(alpha: 0.5)),
          ),
          child: Row(
            children: [
              Icon(Icons.search, color: theme.colorScheme.primary, size: 20),
              const SizedBox(width: 8),
              Text('搜店铺、搜菜品',
                  style: TextStyle(
                      color: theme.colorScheme.outline, fontSize: 14)),
            ],
          ),
        ),
      ),
    );
  }

  /// 金刚区:业务矩阵。已上线的可点,未上线的占位——每个占位都是一句
  /// "我们打算怎么不黑"的宣言,这是愿景的展示位,不是空头支票堆
  Widget _kingKong() {
    final theme = Theme.of(context);
    Widget entry(IconData icon, String label,
        {VoidCallback? onTap, String? coming, String? blood}) {
      final dimmed = coming != null;
      final color =
          dimmed ? theme.colorScheme.outline : theme.colorScheme.primary;
      return InkWell(
        borderRadius: BorderRadius.circular(12),
        // 占位业务点进落地页:把行业问题和我们的姿态讲清楚,不是糊弄的"敬请期待"
        onTap: onTap ??
            () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => ComingSoonPage(
                    name: label,
                    icon: icon,
                    blood: blood ?? '',
                    promise: coming ?? ''))),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Column(
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: dimmed ? 0.06 : 0.10),
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, color: color, size: 23),
              ),
              const SizedBox(height: 5),
              Text(label,
                  style: TextStyle(
                      fontSize: 12,
                      color: dimmed
                          ? theme.colorScheme.outline
                          : theme.colorScheme.onSurface)),
            ],
          ),
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.fromLTRB(8, 4, 8, 0),
      child: GridView.count(
        crossAxisCount: 4,
        shrinkWrap: true,
        physics: const NeverScrollableScrollPhysics(),
        childAspectRatio: 0.98,  // 每格高约 92px:圆标46+间距+单行标签,不溢出
        children: [
          entry(Icons.ramen_dining, '点外卖',
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => CategoryPage(
                      api: widget.api,
                      deliveryAddress: widget.deliveryAddress)))),
          entry(Icons.local_activity_outlined, '超值团购',
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => DealsPage(api: widget.api)))),
          entry(Icons.local_taxi_outlined, '打车',
              coming: '司机不被抽走三成车费',
              blood: '司机每单被抽走两三成,高峰还有乘客看不见的差价'),
          entry(Icons.directions_run, '跑腿',
              coming: '跑腿费给跑腿的人,平台只收零头',
              blood: '跑腿平台抽成 25% 起,小哥风里雨里拿的是小头'),
          entry(Icons.cleaning_services_outlined, '家政',
              coming: '阿姨的钱不过中介的手',
              blood: '中介两头收费,阿姨的月薪被抽走两到四成'),
          entry(Icons.build_outlined, '维修',
              coming: '明码标价,不搞小病大修',
              blood: '上门费加虚报故障,"小病大修"成了行业默认'),
          entry(Icons.local_shipping_outlined, '货运',
              coming: '不收会员费,不用算法压价',
              blood: '司机先交会员费才能接单,算法再一路压运价'),
          entry(Icons.badge_outlined, '零工',
              coming: '日结工资一分不被中介截',
              blood: '劳务中介层层转包,日结工资被截走一两成'),
        ],
      ),
    );
  }

  /// 再来一单:外卖最高频的路径是回头单,抬到首屏(Grab 的 Order it again)
  Widget _reorderRow() {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
          child: Text('再来一单',
              style: theme.textTheme.titleSmall
                  ?.copyWith(fontWeight: FontWeight.bold)),
        ),
        SizedBox(
          height: 92,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            itemCount: _reorder.length,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (context, i) {
              final order = _reorder[i];
              return InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: () => _openReorder(order),
                child: Container(
                  width: 168,
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: theme.brightness == Brightness.light
                        ? Colors.white
                        : theme.colorScheme.surfaceContainerHigh,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                        color: theme.colorScheme.primary
                            .withValues(alpha: 0.25)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(order.merchantName.isEmpty
                              ? '常点的店'
                              : order.merchantName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontWeight: FontWeight.w600, fontSize: 13)),
                      const SizedBox(height: 2),
                      Expanded(
                        child: Text(order.summary,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.bodySmall
                                ?.copyWith(fontSize: 11)),
                      ),
                      Row(
                        children: [
                          Text(yuan(order.totalCents),
                              style: theme.textTheme.bodySmall),
                          const Spacer(),
                          Icon(Icons.replay_circle_filled,
                              size: 18, color: theme.colorScheme.primary),
                        ],
                      ),
                    ],
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  /// Grab 式大图商家卡:封面为主、信息精简
  Widget _bigMerchantCard(Merchant m) {
    final theme = Theme.of(context);
    final dist = distanceMeters(_myLat, _myLng, m.lat, m.lng);
    final eta = etaMinutes(dist);
    final cover = m.logoUrl.isEmpty
        ? Container(
            color: theme.colorScheme.primary.withValues(alpha: 0.08),
            child: Center(
                child: Icon(Icons.ramen_dining,
                    size: 48,
                    color: theme.colorScheme.primary
                        .withValues(alpha: 0.45))),
          )
        : Image.network(
            widget.api.resolveUrl(m.logoUrl),
            fit: BoxFit.cover,
            errorBuilder: (_, __, ___) => Container(
              color: theme.colorScheme.primary.withValues(alpha: 0.08),
              child: Center(
                  child: Icon(Icons.ramen_dining,
                      size: 48,
                      color: theme.colorScheme.primary
                          .withValues(alpha: 0.45))),
            ),
          );
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 10),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => MenuPage(api: widget.api, merchant: m))),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(height: 132, width: double.infinity, child: cover),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(m.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium
                          ?.copyWith(fontWeight: FontWeight.bold)),
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      if (m.ratingAvg != null) ...[
                        Icon(Icons.star_rounded,
                            size: 16, color: theme.colorScheme.primary),
                        Text(' ${m.ratingAvg}',
                            style: const TextStyle(
                                fontSize: 13,
                                fontWeight: FontWeight.w600)),
                        Text('  ·  ', style: theme.textTheme.bodySmall),
                      ],
                      Text('月售 ${m.monthlySales}',
                          style: theme.textTheme.bodySmall),
                      Text('  ·  约 $eta 分钟  ·  ${distanceLabel(dist)}',
                          style: theme.textTheme.bodySmall),
                    ],
                  ),
                  if (m.promoLabels.isNotEmpty || m.minOrderCents > 0) ...[
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 4,
                      runSpacing: 2,
                      children: [
                        for (final label in m.promoLabels)
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 5, vertical: 1),
                            decoration: BoxDecoration(
                              border: Border.all(
                                  color: kPromoAmber, width: .8),
                              borderRadius: BorderRadius.circular(4),
                            ),
                            child: Text(label,
                                style: const TextStyle(
                                    fontSize: 10, color: kPromoAmber)),
                          ),
                        if (m.minOrderCents > 0)
                          Padding(
                            padding: const EdgeInsets.only(top: 1),
                            child: Text(
                                '¥${m.minOrderCents ~/ 100} 起送',
                                style: theme.textTheme.bodySmall
                                    ?.copyWith(fontSize: 10)),
                          ),
                      ],
                    ),
                  ],
                  // 招牌菜:列表页直接看到"这家卖什么、多少钱"(美团式决策信息)
                  if (m.topDishes.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        for (final d in m.topDishes.take(3))
                          Expanded(
                            child: Padding(
                              padding: const EdgeInsets.only(right: 6),
                              child: Column(
                                crossAxisAlignment:
                                    CrossAxisAlignment.start,
                                children: [
                                  ClipRRect(
                                    borderRadius: BorderRadius.circular(8),
                                    child: SizedBox(
                                      height: 56,
                                      width: double.infinity,
                                      child: d.imageUrl.isEmpty
                                          ? Container(
                                              color: theme
                                                  .colorScheme.primary
                                                  .withValues(alpha: 0.07),
                                              child: Icon(
                                                  Icons.ramen_dining,
                                                  size: 20,
                                                  color: theme
                                                      .colorScheme.primary
                                                      .withValues(
                                                          alpha: 0.4)),
                                            )
                                          : Image.network(
                                              widget.api
                                                  .resolveUrl(d.imageUrl),
                                              fit: BoxFit.cover,
                                              errorBuilder: (_, __, ___) =>
                                                  Container(
                                                color: theme
                                                    .colorScheme.primary
                                                    .withValues(
                                                        alpha: 0.07),
                                              ),
                                            ),
                                    ),
                                  ),
                                  const SizedBox(height: 2),
                                  Text(d.name,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: const TextStyle(
                                          fontSize: 11)),
                                  Text(yuan(d.priceCents),
                                      style: TextStyle(
                                          fontSize: 11,
                                          fontWeight: FontWeight.w600,
                                          color:
                                              theme.colorScheme.primary)),
                                ],
                              ),
                            ),
                          ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _bigCardSkeleton() {
    final base = Theme.of(context).colorScheme.surfaceContainerHighest;
    return Card(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 10),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(height: 132, color: base),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                    height: 16,
                    width: 140,
                    decoration: BoxDecoration(
                        color: base,
                        borderRadius: BorderRadius.circular(4))),
                const SizedBox(height: 8),
                Container(
                    height: 12,
                    width: 220,
                    decoration: BoxDecoration(
                        color: base,
                        borderRadius: BorderRadius.circular(4))),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async {
        _loadRecent();
        setState(() => _future = _load());
      },
      child: FutureBuilder(
        future: _future,
        builder: (context, snapshot) {
          final merchants = snapshot.data;
          return CustomScrollView(
            slivers: [
              // 品类模式只留列表,首页头部(搜索/公告/金刚区/再来一单)不重复出现
              if (widget.category == null)
                SliverToBoxAdapter(
                  child: Column(children: [
                    _searchBar(),
                    // 平台公告(运营配置,发通知不用发版);无公告时零高度
                    AnnouncementBanner(api: widget.api, audience: 'user'),
                    _kingKong(),
                    if (_reorder.isNotEmpty) _reorderRow(),
                  ]),
                ),
              SliverPersistentHeader(
                pinned: true,
                delegate: _PinnedChipsDelegate(_sortChips()),
              ),
              SliverList(
                delegate: SliverChildListDelegate([
              if (!_realLocation && merchants != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
                  child: Text('未获取到定位,正在展示演示区域的商家(下拉重试)',
                      style: Theme.of(context)
                          .textTheme
                          .bodySmall
                          ?.copyWith(
                              color:
                                  Theme.of(context).colorScheme.outline)),
                ),
              if (snapshot.hasError)
                Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text('加载失败:${snapshot.error}')),
              if (!snapshot.hasData && !snapshot.hasError) ...[
                _bigCardSkeleton(),
                _bigCardSkeleton(),
              ] else if (merchants != null && merchants.isEmpty)
                // 空品类不摆烂:空状态变招商位(平台没钱补贴,但入驻免费是真的)
                (widget.category?.isNotEmpty ?? false)
                    ? _categoryVacancy()
                    : const Padding(
                        padding: EdgeInsets.only(top: 48),
                        child: EmptyState(
                            icon: Icons.storefront_outlined,
                            text: '附近暂时没有营业的商家\n下拉刷新试试'),
                      ),
              if (merchants != null)
                for (final (i, m) in merchants.indexed)
                  FadeSlideIn(index: i, child: _bigMerchantCard(m)),
              const SizedBox(height: 24),
                ]),
              ),
            ],
          );
        },
      ),
    );
  }

}

class MenuPage extends StatefulWidget {
  const MenuPage({
    super.key,
    required this.api,
    required this.merchant,
    this.initialCart,
  });

  final ApiClient api;
  final Merchant merchant;

  /// 「再来一单」预填的购物车(dishId -> quantity)
  final Map<int, int>? initialCart;

  @override
  State<MenuPage> createState() => _MenuPageState();
}

class _MenuPageState extends State<MenuPage>
    with SingleTickerProviderStateMixin {
  Merchant? _detail;
  List<Dish> _dishes = [];
  bool _loaded = false;
  String? _error;
  String _category = '';
  // 购物车行:同一菜品不同规格是不同的行(如 大份+加蛋 / 小份 各一行)
  final List<CartLine> _cart = [];
  // 云端购物车:变更防抖上报;进店时若本地空则从云端恢复
  Timer? _cartSaveTimer;
  List<Dish> _frequent = []; // 我常买
  List<Map<String, dynamic>> _claimable = []; // 可领店铺券
  bool _isFavorite = false;
  late final TabController _tabController =
      TabController(length: 3, vsync: this);

  @override
  void initState() {
    super.initState();
    _load();
    Analytics.track('view_menu', {'merchant_id': widget.merchant.id});
  }

  @override
  void dispose() {
    // 离店时把最新购物车落一次云端(防抖未触发也不丢)
    if (_cartSaveTimer?.isActive ?? false) {
      _cartSaveTimer!.cancel();
      _flushCart();
    }
    _tabController.dispose();
    super.dispose();
  }

  /// 购物车 → 云端 items 快照
  List<Map<String, dynamic>> _cartItems() =>
      _cart.map((l) => l.toOrderItem()).toList();

  /// 变更后防抖 800ms 上报云端(失败静默,不打扰下单)
  void _scheduleCartSave() {
    _cartSaveTimer?.cancel();
    _cartSaveTimer = Timer(const Duration(milliseconds: 800), _flushCart);
  }

  void _flushCart() {
    widget.api.putCart(widget.merchant.id, _cartItems()).catchError((_) {});
  }

  /// 进店时从云端恢复购物车(本地空且非再来一单场景才恢复)
  void _restoreServerCart(List<Dish> dishes) async {
    try {
      final items = await widget.api.getCart(widget.merchant.id);
      if (!mounted || _cart.isNotEmpty) return;
      final byId = {for (final d in dishes) d.id: d};
      final restored = <CartLine>[];
      for (final it in items) {
        final dish = byId[it['dish_id'] as int?];
        final qty = (it['quantity'] as int?) ?? 0;
        if (dish == null || qty <= 0 || dish.soldOutToday) continue;
        final choices =
            ((it['choices'] as List?) ?? const []).cast<String>();
        restored.add(CartLine(
            dish: dish, choices: choices, quantity: qty.clamp(1, dish.stock)));
      }
      if (restored.isNotEmpty && mounted) {
        setState(() => _cart.addAll(restored));
      }
    } catch (_) {/* 云端购物车不可用不影响点单 */}
  }

  Future<void> _load() async {
    try {
      final detail = await widget.api.merchantDetail(widget.merchant.id);
      final dishes = await widget.api.menu(widget.merchant.id);
      bool fav = _isFavorite;
      try {
        fav = (await widget.api.favoriteIds()).contains(widget.merchant.id);
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _detail = detail;
        _dishes = dishes;
        _isFavorite = fav;
        _loaded = true;
        if (_category.isEmpty && dishes.isNotEmpty) {
          _category = _categoryOf(dishes.first);
        }
        // 再来一单:还在售且库存够的菜自动入车(带规格的菜请重新选规格)
        final initial = widget.initialCart;
        if (initial != null && _cart.isEmpty) {
          for (final entry in initial.entries) {
            final dish = dishes.where((d) => d.id == entry.key).firstOrNull;
            if (dish != null &&
                dish.stock >= entry.value &&
                !dish.hasOptions) {
              _cart.add(CartLine(
                  dish: dish, choices: const [], quantity: entry.value));
            }
          }
        }
      });
      // 非再来一单时,从云端恢复上次未提交的购物车
      if (widget.initialCart == null) _restoreServerCart(dishes);
      // 我常买(登录用户;失败静默)
      widget.api.frequentDishes(widget.merchant.id).then((f) {
        if (mounted) setState(() => _frequent = f);
      }).catchError((_) {});
      // 可领店铺券(失败静默)
      _loadClaimable();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loaded = true;
      });
    }
  }

  String _categoryOf(Dish dish) => dish.category.isEmpty ? '其他' : dish.category;

  List<String> get _categories {
    final seen = <String>{};
    final list = <String>[];
    for (final dish in _dishes) {
      final c = _categoryOf(dish);
      if (seen.add(c)) list.add(c);
    }
    return list;
  }

  int get _totalCents =>
      _cart.fold(0, (sum, line) => sum + line.unitCents * line.quantity);

  int get _totalCount => _cart.fold(0, (a, line) => a + line.quantity);

  /// 该菜品在购物车里的总份数(跨规格行合计,菜单行角标用)
  int _qtyOf(Dish dish) => _cart
      .where((l) => l.dish.id == dish.id)
      .fold(0, (a, l) => a + l.quantity);

  void _changeLine(CartLine line, int delta) {
    setState(() {
      line.quantity += delta;
      if (line.quantity <= 0) _cart.remove(line);
    });
    _scheduleCartSave();
  }

  /// 菜单行的 +/-:无规格直接加;有规格弹选规格面板;减号减掉该菜最后一行
  void _changeQuantity(Dish dish, int delta) {
    if (delta > 0) {
      if (dish.hasOptions) {
        _pickOptions(dish);
        return;
      }
      if (_qtyOf(dish) >= dish.stock) return;
      final line = _cart
          .where((l) => l.sameAs(dish, const []))
          .firstOrNull;
      setState(() {
        if (line != null) {
          line.quantity++;
        } else {
          _cart.add(CartLine(dish: dish, choices: const []));
        }
      });
      _scheduleCartSave();
    } else {
      final line = _cart.where((l) => l.dish.id == dish.id).lastOrNull;
      if (line != null) _changeLine(line, -1);
    }
  }

  /// 规格/加料选择面板:必选组默认选第一项,确认后按组合并入购物车
  Future<void> _pickOptions(Dish dish) async {
    final selected = <String>{
      for (final g in dish.options)
        if (g.required_ && g.choices.isNotEmpty) g.choices.first.name,
    };
    final confirmed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) {
          int unit() {
            var total = dish.effectivePriceCents;
            for (final g in dish.options) {
              for (final c in g.choices) {
                if (selected.contains(c.name)) total += c.deltaCents;
              }
            }
            return total;
          }

          return SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(dish.name,
                      style: Theme.of(context).textTheme.titleLarge),
                  for (final group in dish.options) ...[
                    const SizedBox(height: 10),
                    Text(
                        '${group.name}'
                        '${group.required_ ? '(必选)' : group.multi ? '(可多选)' : ''}',
                        style: Theme.of(context).textTheme.bodySmall),
                    const SizedBox(height: 4),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: [
                        for (final c in group.choices)
                          ChoiceChip(
                            label: Text(c.label),
                            selected: selected.contains(c.name),
                            onSelected: (on) => setSheet(() {
                              if (on) {
                                if (!group.multi) {
                                  // 单选组:清掉同组其他选项
                                  for (final other in group.choices) {
                                    selected.remove(other.name);
                                  }
                                }
                                selected.add(c.name);
                              } else {
                                // 必选单选组不允许取消(换选即可)
                                if (!(group.required_ && !group.multi)) {
                                  selected.remove(c.name);
                                }
                              }
                            }),
                          ),
                      ],
                    ),
                  ],
                  const SizedBox(height: 16),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: () => Navigator.pop(sheetContext, true),
                      child: Text('加入购物车 ${yuan(unit())}'),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
    if (confirmed != true || !mounted) return;
    final choices = selected.toList();
    setState(() {
      final line = _cart.where((l) => l.sameAs(dish, choices)).firstOrNull;
      if (line != null) {
        line.quantity++;
      } else {
        _cart.add(CartLine(dish: dish, choices: choices));
      }
    });
    _scheduleCartSave();
  }

  Future<void> _groupCart() async {
    final action = await showModalBottomSheet<String>(
      context: context,
      builder: (context) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
              leading: const Icon(Icons.group_add_outlined),
              title: const Text('发起拼单'),
              subtitle: const Text('生成拼单码,大家各自加菜,你一次性支付'),
              onTap: () => Navigator.pop(context, 'open')),
          ListTile(
              leading: const Icon(Icons.pin_outlined),
              title: const Text('输码加入拼单'),
              onTap: () => Navigator.pop(context, 'join')),
        ]),
      ),
    );
    if (action == null || !mounted) return;
    try {
      Map<String, dynamic> cart;
      if (action == 'open') {
        cart = await widget.api.openGroupCart(widget.merchant.id);
      } else {
        final controller = TextEditingController();
        final ok = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('输入 6 位拼单码'),
            content: TextField(
                controller: controller,
                autofocus: true,
                keyboardType: TextInputType.number,
                maxLength: 6),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('取消')),
              FilledButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('加入')),
            ],
          ),
        );
        if (ok != true || !mounted) return;
        cart = await widget.api.joinGroupCart(controller.text.trim());
      }
      if (!mounted) return;
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => GroupCartPage(
              api: widget.api,
              merchant: widget.merchant,
              code: cart['code'] as String)));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  void _checkout() {
    // 进正式结算页;订单在结算页最终提交时才创建(不再"先建单再确认"浪费库存)
    Navigator.of(context).push(MaterialPageRoute(
        builder: (_) => CheckoutPage(
              api: widget.api,
              merchant: _detail ?? widget.merchant,
              cart: List.of(_cart),
            )));
  }

  // ---------- UI ----------

  Widget _header() {
    final shop = _detail ?? widget.merchant;
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(shop.name,
              style: theme.textTheme.headlineSmall
                  ?.copyWith(fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          InkWell(
            onTap: () => _tabController.animateTo(1), // 切到「评价」Tab
            child: Row(
              children: [
                Text(
                    [
                      '${shop.ratingLabel} · 月售 ${shop.monthlySales} 单 · 配送费 ¥3 起',
                      if (shop.minOrderCents > 0)
                        '¥${shop.minOrderCents ~/ 100} 起送',
                      ...shop.promoLabels,
                    ].join(' · '),
                    style: theme.textTheme.bodySmall),
                Icon(Icons.chevron_right,
                    size: 14, color: theme.colorScheme.outline),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text(
              '本店仅被抽成 ${(shop.commissionRate * 100).toStringAsFixed(0)}%,菜价里没有平台税',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.primary),
            ),
          ),
          if (shop.announcement.isNotEmpty)
            Container(
              margin: const EdgeInsets.only(top: 8),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: theme.colorScheme.tertiaryContainer,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(Icons.campaign,
                      size: 16, color: theme.colorScheme.onTertiaryContainer),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(shop.announcement,
                        style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onTertiaryContainer)),
                  ),
                ],
              ),
            ),
          if (_hoursNotice(shop) != null)
            Container(
              margin: const EdgeInsets.only(top: 8),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: theme.colorScheme.errorContainer,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  Icon(Icons.schedule,
                      size: 16, color: theme.colorScheme.onErrorContainer),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(_hoursNotice(shop)!,
                        style: theme.textTheme.bodySmall?.copyWith(
                            color: theme.colorScheme.onErrorContainer)),
                  ),
                ],
              ),
            ),
          if (_claimable.isNotEmpty) _claimableStrip(),
        ],
      ),
    );
  }

  /// 营业提示:今日特殊计划(节假日) > 临时歇业 > 打烊前 15 分钟催单
  String? _hoursNotice(Merchant shop) {
    final plan = shop.todayHolidayPlan;
    if (plan != null) {
      if (plan['closed'] as bool? ?? true) {
        final to = (plan['to'] as String?)?.isNotEmpty == true
            ? plan['to'] as String
            : plan['from'] as String;
        return '商家歇业中,${int.parse(to.substring(5, 7))}/${int.parse(to.substring(8, 10))} 后恢复营业';
      }
      return '今日特殊营业时间:${plan['open']} - ${plan['close']}';
    }
    final until = shop.closedUntil;
    if (until != null && until.isAfter(DateTime.now().toUtc())) {
      final t = until.toLocal();
      return '商家临时歇业中,预计 ${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')} 恢复';
    }
    if (shop.isOpen && shop.closeTime.isNotEmpty) {
      final now = DateTime.now();
      final parts = shop.closeTime.split(':');
      final close = DateTime(now.year, now.month, now.day,
          int.parse(parts[0]), int.parse(parts[1]));
      final left = close.difference(now).inMinutes;
      if (left >= 0 && left <= 15) {
        return '商家 ${shop.closeTime} 打烊,还剩 $left 分钟,尽快下单';
      }
    }
    return null;
  }

  Widget _categoryRail() {
    final theme = Theme.of(context);
    return Container(
      width: 92,
      color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.4),
      child: ListView(
        children: [
          for (final c in _categories)
            InkWell(
              onTap: () => setState(() => _category = c),
              child: Container(
                padding:
                    const EdgeInsets.symmetric(vertical: 14, horizontal: 10),
                decoration: BoxDecoration(
                  color: c == _category
                      ? theme.scaffoldBackgroundColor
                      : Colors.transparent,
                  border: Border(
                    left: BorderSide(
                      width: 3,
                      color: c == _category
                          ? theme.colorScheme.primary
                          : Colors.transparent,
                    ),
                  ),
                ),
                child: Text(
                  c,
                  style: TextStyle(
                    fontWeight:
                        c == _category ? FontWeight.bold : FontWeight.normal,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _dishImage(Dish dish) {
    final placeholder = Container(
      width: 64,
      height: 64,
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Icon(Icons.ramen_dining,
          color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.45)),
    );
    if (dish.imageUrl.isEmpty) return placeholder;
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: Image.network(
        widget.api.resolveUrl(dish.imageUrl),
        width: 64,
        height: 64,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => placeholder,
      ),
    );
  }

  Widget _stepper(Dish dish, int quantity, void Function(Dish, int) change) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (quantity > 0) ...[
          IconButton(
            visualDensity: VisualDensity.compact,
            icon: const Icon(Icons.remove_circle_outline),
            onPressed: () => change(dish, -1),
          ),
          Text('$quantity'),
        ],
        IconButton(
          visualDensity: VisualDensity.compact,
          icon: const Icon(Icons.add_circle),
          onPressed: dish.stock > quantity ? () => change(dish, 1) : null,
        ),
      ],
    );
  }

  void _loadClaimable() {
    widget.api.claimableShopCoupons(widget.merchant.id).then((list) {
      if (mounted) {
        setState(() =>
            _claimable = list.where((c) => c['can_claim'] == true).toList());
      }
    }).catchError((_) {});
  }

  Future<void> _claimCoupon(Map<String, dynamic> batch) async {
    try {
      await widget.api
          .claimShopCoupon(widget.merchant.id, batch['batch_id'] as int);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('领取成功,下单时可用')));
      _loadClaimable();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 可领店铺券:一排「领」券横条(商家出成本)
  Widget _claimableStrip() {
    return Container(
      margin: const EdgeInsets.only(top: 8),
      height: 30,
      child: ListView(
        scrollDirection: Axis.horizontal,
        children: [
          for (final b in _claimable)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ActionChip(
                avatar: const Icon(Icons.card_giftcard,
                    size: 16, color: kBrandOrange),
                label: Text(
                    '${b['threshold_cents'] == 0 ? "无门槛" : "满${b['threshold_cents'] ~/ 100}"}'
                    '减${b['off_cents'] ~/ 100} · 领',
                    style: const TextStyle(fontSize: 12)),
                onPressed: () => _claimCoupon(b),
              ),
            ),
        ],
      ),
    );
  }

  /// 我常买:横向卡片,点 + 直接加购(带规格的引导去选规格)
  Widget _frequentRow() {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Icon(Icons.replay, size: 16, color: theme.colorScheme.primary),
            const SizedBox(width: 4),
            Text('我常买',
                style: theme.textTheme.titleSmall
                    ?.copyWith(fontWeight: FontWeight.bold)),
          ]),
          const SizedBox(height: 8),
          SizedBox(
            height: 116,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: _frequent.length,
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (context, i) {
                final dish = _frequent[i];
                final soldOut = dish.stock <= 0;
                return SizedBox(
                  width: 92,
                  child: InkWell(
                    onTap: () => _showDishDetail(dish),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Stack(children: [
                          _dishImage(dish),
                          Positioned(
                            right: 0,
                            bottom: 0,
                            child: InkWell(
                              onTap: soldOut
                                  ? null
                                  : () => _changeQuantity(dish, 1),
                              child: CircleAvatar(
                                radius: 12,
                                backgroundColor: soldOut
                                    ? theme.disabledColor
                                    : theme.colorScheme.primary,
                                child: const Icon(Icons.add,
                                    size: 16, color: Colors.white),
                              ),
                            ),
                          ),
                        ]),
                        const SizedBox(height: 2),
                        Text(dish.name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: theme.textTheme.bodySmall),
                        Text(yuan(dish.effectivePriceCents),
                            style: theme.textTheme.bodySmall?.copyWith(
                                color: theme.colorScheme.primary,
                                fontWeight: FontWeight.bold)),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
          const Divider(height: 16),
        ],
      ),
    );
  }

  Widget _dishList() {
    final dishes =
        _dishes.where((d) => _categoryOf(d) == _category).toList();
    // 我常买:只在第一个分类顶部露出一次,避免各分类重复
    final showFrequent = _frequent.isNotEmpty &&
        _categories.isNotEmpty &&
        _category == _categories.first;
    return ListView.builder(
      itemCount: dishes.length + (showFrequent ? 1 : 0),
      itemBuilder: (context, rawIndex) {
        if (showFrequent && rawIndex == 0) return _frequentRow();
        final i = showFrequent ? rawIndex - 1 : rawIndex;
        final dish = dishes[i];
        final quantity = _qtyOf(dish);
        final soldOut = dish.stock <= 0;
        return InkWell(
          onTap: () => _showDishDetail(dish),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                _dishImage(dish),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(children: [
                        Flexible(
                            child: Text(dish.name,
                                style:
                                    Theme.of(context).textTheme.titleSmall)),
                        // 酒类角标:购买需实名且成年
                        if (dish.isAlcohol) ...[
                          const SizedBox(width: 4),
                          Container(
                            padding: const EdgeInsets.symmetric(
                                horizontal: 4, vertical: 1),
                            decoration: BoxDecoration(
                              color: Colors.orange.withValues(alpha: 0.15),
                              borderRadius: BorderRadius.circular(3),
                            ),
                            child: const Text('酒',
                                style: TextStyle(
                                    fontSize: 10, color: Colors.orange)),
                          ),
                        ],
                      ]),
                      const SizedBox(height: 2),
                      Row(
                        children: [
                          Text(
                            soldOut
                                // 估清 = 今日售罄(明天自动恢复),区别于长期没货
                                ? (dish.soldOutToday ? '今日售罄' : '已售罄')
                                : dish.hasOptions
                                    ? '${yuan(dish.effectivePriceCents)} 起'
                                    : yuan(dish.effectivePriceCents),
                            style: TextStyle(
                              color: soldOut
                                  ? Theme.of(context).colorScheme.outline
                                  : Theme.of(context).colorScheme.primary,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          // 限时折扣:划线原价 + 琥珀"限时"签
                          if (!soldOut && dish.flashActive) ...[
                            const SizedBox(width: 4),
                            Text(yuan(dish.priceCents),
                                style: TextStyle(
                                    fontSize: 11,
                                    color: Theme.of(context)
                                        .colorScheme
                                        .outline,
                                    decoration:
                                        TextDecoration.lineThrough)),
                            const SizedBox(width: 3),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 4, vertical: 1),
                              decoration: BoxDecoration(
                                color:
                                    kPromoAmber.withValues(alpha: 0.15),
                                borderRadius: BorderRadius.circular(3),
                              ),
                              child: const Text('限时',
                                  style: TextStyle(
                                      fontSize: 10, color: kPromoAmber)),
                            ),
                          ],
                          if (dish.monthlySales > 0) ...[
                            const SizedBox(width: 6),
                            Text('月售 ${dish.monthlySales}',
                                style:
                                    Theme.of(context).textTheme.bodySmall),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
                if (!soldOut) _stepper(dish, quantity, _changeQuantity),
              ],
            ),
          ),
        );
      },
    );
  }

  /// 菜品详情弹层:大图 + 价格 + 库存 + 数量加减 + 加入购物车
  void _showDishDetail(Dish dish) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) {
          final theme = Theme.of(context);
          final quantity = _qtyOf(dish);
          final soldOut = dish.stock <= 0;
          return SafeArea(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 大图(无图用大号占位图标)
                SizedBox(
                  height: 200,
                  width: double.infinity,
                  child: dish.imageUrl.isEmpty
                      ? Container(
                          color: theme.colorScheme.surfaceContainerHighest,
                          child: Icon(Icons.ramen_dining,
                              size: 72, color: theme.colorScheme.outline),
                        )
                      : Image.network(
                          widget.api.resolveUrl(dish.imageUrl),
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => Container(
                            color:
                                theme.colorScheme.surfaceContainerHighest,
                            child: Icon(Icons.ramen_dining,
                                size: 72,
                                color: theme.colorScheme.outline),
                          ),
                        ),
                ),
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(dish.name, style: theme.textTheme.headlineSmall),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          if (dish.category.isNotEmpty)
                            Chip(
                              label: Text(dish.category),
                              visualDensity: VisualDensity.compact,
                            ),
                          const SizedBox(width: 8),
                          Text(
                            soldOut
                                ? (dish.soldOutToday ? '今日售罄,明日再来' : '已售罄')
                                : '库存 ${dish.stock} 份'
                                    '${dish.monthlySales > 0 ? " · 月售 ${dish.monthlySales}" : ""}',
                            style: theme.textTheme.bodySmall,
                          ),
                        ],
                      ),
                      if (dish.isAlcohol) ...[
                        const SizedBox(height: 6),
                        Text('🍺 酒类商品:未成年人禁止购买,下单需完成实名认证',
                            style: theme.textTheme.bodySmall?.copyWith(
                                color: Colors.orange,
                                fontWeight: FontWeight.w600)),
                      ],
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Text(yuan(dish.effectivePriceCents),
                              style: theme.textTheme.headlineSmall?.copyWith(
                                  color: theme.colorScheme.primary,
                                  fontWeight: FontWeight.bold)),
                          if (dish.flashActive) ...[
                            const SizedBox(width: 6),
                            Text(yuan(dish.priceCents),
                                style: TextStyle(
                                    color: theme.colorScheme.outline,
                                    decoration:
                                        TextDecoration.lineThrough)),
                          ],
                          const Spacer(),
                          if (!soldOut)
                            quantity == 0
                                ? FilledButton.icon(
                                    icon: const Icon(Icons.add),
                                    label: const Text('加入购物车'),
                                    onPressed: () {
                                      _changeQuantity(dish, 1);
                                      setSheet(() {});
                                    },
                                  )
                                : _stepper(dish, quantity, (d, delta) {
                                    _changeQuantity(d, delta);
                                    setSheet(() {});
                                  }),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  void _openCartSheet() {
    showModalBottomSheet(
      context: context,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheetState) {
          void change(CartLine line, int delta) {
            _changeLine(line, delta);
            setSheetState(() {});
            if (_cart.isEmpty) Navigator.pop(sheetContext);
          }

          return SafeArea(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                ListTile(
                  title: Text('已选 $_totalCount 件',
                      style: Theme.of(context).textTheme.titleMedium),
                  trailing: TextButton.icon(
                    icon: const Icon(Icons.delete_outline, size: 18),
                    label: const Text('清空'),
                    onPressed: () {
                      setState(() => _cart.clear());
                      Navigator.pop(sheetContext);
                    },
                  ),
                ),
                const Divider(height: 1),
                for (final line in _cart.toList())
                  ListTile(
                    dense: true,
                    title: Text(line.label),
                    subtitle: Text(yuan(line.unitCents * line.quantity)),
                    trailing: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        IconButton(
                          visualDensity: VisualDensity.compact,
                          icon: const Icon(Icons.remove_circle_outline),
                          onPressed: () => change(line, -1),
                        ),
                        Text('${line.quantity}'),
                        IconButton(
                          visualDensity: VisualDensity.compact,
                          icon: const Icon(Icons.add_circle),
                          onPressed: line.dish.stock > _qtyOf(line.dish)
                              ? () => change(line, 1)
                              : null,
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    Widget body;
    if (!_loaded) {
      body = const Center(child: CircularProgressIndicator());
    } else if (_error != null) {
      body = Center(child: Text(_error!));
    } else {
      body = Column(
        children: [
          _header(),
          TabBar(
            controller: _tabController,
            tabs: const [
              Tab(text: '点餐'),
              Tab(text: '评价'),
              Tab(text: '商家'),
            ],
          ),
          Expanded(
            child: TabBarView(
              controller: _tabController,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _categoryRail(),
                    Expanded(child: _dishList()),
                  ],
                ),
                ReviewsList(api: widget.api, merchantId: widget.merchant.id),
                _ShopInfoTab(
                    api: widget.api, shop: _detail ?? widget.merchant),
              ],
            ),
          ),
        ],
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.merchant.name),
        actions: [
          IconButton(
            tooltip: '拼单(和朋友一起点)',
            icon: const Icon(Icons.group_add_outlined),
            onPressed: _groupCart,
          ),
          IconButton(
            tooltip: '分享本店',
            icon: const Icon(Icons.share_outlined),
            onPressed: () {
              final m = _detail ?? widget.merchant;
              showShareCard(context, shopShareCard(m),
                  event: 'share_shop', props: {'id': m.id});
            },
          ),
          IconButton(
            tooltip: _isFavorite ? '取消收藏' : '收藏本店',
            icon: Icon(
              _isFavorite ? Icons.favorite : Icons.favorite_outline,
              color: _isFavorite ? Colors.redAccent : null,
            ),
            onPressed: () async {
              final next = !_isFavorite;
              setState(() => _isFavorite = next); // 先响应再请求,失败回滚
              try {
                await widget.api.setFavorite(widget.merchant.id, next);
              } catch (_) {
                if (mounted) setState(() => _isFavorite = !next);
              }
            },
          ),
        ],
      ),
      body: body,
      bottomNavigationBar: SafeArea(
        child: Container(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surface,
            boxShadow: const [
              BoxShadow(color: Colors.black12, blurRadius: 8),
            ],
          ),
          child: Row(
            children: [
              TweenAnimationBuilder<double>(
                key: ValueKey(_totalCount), // 数量一变,重放弹跳动画
                tween: Tween(begin: 0.7, end: 1.0),
                duration: const Duration(milliseconds: 350),
                curve: Curves.elasticOut,
                builder: (context, scale, child) =>
                    Transform.scale(scale: scale, child: child),
                child: Badge.count(
                  count: _totalCount,
                  isLabelVisible: _totalCount > 0,
                  child: IconButton.filledTonal(
                    icon: const Icon(Icons.shopping_cart),
                    onPressed: _cart.isEmpty ? null : _openCartSheet,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  _cart.isEmpty
                      ? '还没选商品'
                      : '菜品 ${yuan(_totalCents)} · 配送费按距离结算',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
              ),
              FilledButton(
                onPressed: _cart.isEmpty ? null : _checkout,
                child: const Text('去结算'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class OrderListView extends StatefulWidget {
  const OrderListView({super.key, required this.api});

  final ApiClient api;

  @override
  State<OrderListView> createState() => _OrderListViewState();
}

class _OrderListViewState extends State<OrderListView> {
  late Future<List<Order>> _future = widget.api.myOrders();

  /// 状态语义色:进行中 = 品牌橙(需要关注),完成 = 账目绿(钱已结清),取消 = 灰
  Color _statusColor(OrderStatus status, ThemeData theme) => switch (status) {
        OrderStatus.completed => kMoneyGreen,
        OrderStatus.cancelled => theme.colorScheme.outline,
        _ => theme.colorScheme.primary,
      };

  String _timeLabel(Order order) {
    final t = DateTime.tryParse(order.createdAt)?.toLocal();
    if (t == null) return '';
    return '${t.month}/${t.day} '
        '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
  }

  /// 一键回购:与首页「再来一单」同逻辑
  Future<void> _reorder(Order order) async {
    try {
      final merchant = await widget.api.merchantDetail(order.merchantId);
      if (!mounted) return;
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => MenuPage(
                api: widget.api,
                merchant: merchant,
                initialCart: {
                  for (final it in order.items)
                    if (it.dishId != 0) it.dishId: it.quantity,
                },
              )));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Widget _orderCard(Order order, int index) {
    final theme = Theme.of(context);
    final color = _statusColor(order.status, theme);
    final active = order.status != OrderStatus.completed &&
        order.status != OrderStatus.cancelled;
    return FadeSlideIn(
      index: index,
      child: Card(
        margin: const EdgeInsets.fromLTRB(12, 5, 12, 5),
        // 进行中订单描一圈橙,列表里一眼找到"正在路上的那单"
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: active
              ? BorderSide(
                  color: theme.colorScheme.primary.withValues(alpha: 0.45))
              : BorderSide.none,
        ),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) =>
                  OrderDetailPage(api: widget.api, orderNo: order.orderNo))),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                          order.merchantName.isEmpty
                              ? '订单'
                              : order.merchantName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontWeight: FontWeight.w600, fontSize: 15)),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 8, vertical: 2),
                      decoration: BoxDecoration(
                        color: color.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: Text(order.status.label,
                          style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: color)),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(order.summary,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall?.copyWith(height: 1.4)),
                if (order.scheduledLabel != null) ...[
                  const SizedBox(height: 4),
                  Text('⏰ ${order.scheduledLabel}',
                      style: const TextStyle(
                          fontSize: 12,
                          color: kPromoAmber,
                          fontWeight: FontWeight.w600)),
                ],
                if (order.selfDelivery) ...[
                  const SizedBox(height: 4),
                  const Text('🛵 商家自送',
                      style: TextStyle(
                          fontSize: 12,
                          color: kMoneyGreen,
                          fontWeight: FontWeight.w600)),
                ],
                const SizedBox(height: 8),
                Row(
                  children: [
                    Text(yuan(order.totalCents),
                        style: const TextStyle(
                            fontWeight: FontWeight.bold, fontSize: 15)),
                    const SizedBox(width: 8),
                    Text(_timeLabel(order),
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: theme.colorScheme.outline)),
                    const Spacer(),
                    if (order.status == OrderStatus.completed)
                      SizedBox(
                        height: 30,
                        child: OutlinedButton(
                          style: OutlinedButton.styleFrom(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 12),
                              visualDensity: VisualDensity.compact),
                          onPressed: () => _reorder(order),
                          child: const Text('再来一单',
                              style: TextStyle(fontSize: 12)),
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => setState(() => _future = widget.api.myOrders()),
      child: FutureBuilder(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return ListView(children: [
              Padding(
                  padding: const EdgeInsets.all(24),
                  child: Text('${snapshot.error}'))
            ]);
          }
          if (!snapshot.hasData) {
            return const SkeletonList();
          }
          final orders = snapshot.data!;
          if (orders.isEmpty) {
            return ListView(children: const [
              SizedBox(height: 120),
              EmptyState(
                  icon: Icons.receipt_long_outlined, text: '还没有订单\n去点一单支持身边小店吧'),
            ]);
          }
          return ListView.builder(
            padding: const EdgeInsets.symmetric(vertical: 8),
            itemCount: orders.length,
            itemBuilder: (context, i) => _orderCard(orders[i], i),
          );
        },
      ),
    );
  }
}

class OrderDetailPage extends StatefulWidget {
  const OrderDetailPage({super.key, required this.api, required this.orderNo});

  final ApiClient api;
  final String orderNo;

  @override
  State<OrderDetailPage> createState() => _OrderDetailPageState();
}

class _OrderDetailPageState extends State<OrderDetailPage> {
  Order? _order;
  Review? _review;
  AfterSale? _afterSale;
  List<OrderEvent> _events = [];
  List<RefundRecord> _refunds = [];
  bool _reviewChecked = false;
  Timer? _timer;
  WebSocketChannel? _ws;

  @override
  void initState() {
    super.initState();
    _refresh();
    _connectWs();
    // WebSocket 为主,慢轮询兜底(断线期间也不至于卡住)
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _refresh());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _ws?.sink.close();
    super.dispose();
  }

  /// 订单状态实时推送:状态一变立刻刷新
  void _connectWs() {
    try {
      _ws = WebSocketChannel.connect(
          Uri.parse('${widget.api.wsBaseUrl}/ws/orders/${widget.orderNo}'));
    } catch (_) {
      return;
    }
    _ws!.stream.listen(
      (message) {
        final data = jsonDecode(message as String) as Map<String, dynamic>;
        if (data['type'] == 'order_status' || data['type'] == 'rider_assigned') {
          _refresh();
        }
      },
      onError: (_) {},
      onDone: () {
        // 终态就不用重连了
        final status = _order?.status;
        if (status == OrderStatus.completed || status == OrderStatus.cancelled) {
          return;
        }
        Timer(const Duration(seconds: 5), () {
          if (mounted) _connectWs();
        });
      },
    );
  }

  Future<void> _refresh() async {
    try {
      final order = await widget.api.getOrder(widget.orderNo);
      final events = await widget.api.orderEvents(widget.orderNo);
      Review? review = _review;
      if (order.status == OrderStatus.completed && !_reviewChecked) {
        review = await widget.api.orderReview(widget.orderNo);
        _reviewChecked = true;
      }
      AfterSale? afterSale = _afterSale;
      if (order.status == OrderStatus.delivered ||
          order.status == OrderStatus.completed) {
        afterSale = await widget.api.orderAfterSale(widget.orderNo);
      }
      var refunds = _refunds;
      if (order.refundCents > 0) {
        try {
          refunds = await widget.api.orderRefunds(widget.orderNo);
        } catch (_) {} // 拉不到就退回汇总文案
      }
      if (mounted) {
        setState(() {
          _order = order;
          _events = events;
          _review = review;
          _afterSale = afterSale;
          _refunds = refunds;
        });
      }
    } catch (_) {}
  }

  /// 售后分流:普通售后走商家先处理;食品安全是红线,不经商家直达平台
  Future<void> _chooseAfterSaleKind() async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.support_agent),
              title: const Text('普通售后'),
              subtitle: const Text('洒漏、少送、口味等问题,商家优先处理'),
              onTap: () => Navigator.pop(sheetContext, 'normal'),
            ),
            const Divider(height: 1),
            ListTile(
              leading:
                  const Icon(Icons.report_gmailerrorred, color: Colors.red),
              title: const Text('食品安全问题',
                  style: TextStyle(
                      color: Colors.red, fontWeight: FontWeight.bold)),
              subtitle: const Text('异物、变质、食用后不适——不经商家,平台加急处理'),
              onTap: () => Navigator.pop(sheetContext, 'food_safety'),
            ),
          ],
        ),
      ),
    );
    if (choice == 'normal') {
      await _applyAfterSale();
    } else if (choice == 'food_safety') {
      await _applyFoodSafety();
    }
  }

  /// 食安投诉:强制拍照,可附医疗凭证;直达平台标红加急
  Future<void> _applyFoodSafety() async {
    var kind = 'foreign_object';
    final desc = TextEditingController();
    final images = <String>[];
    final medical = <String>[];
    var uploading = false;
    final submitted = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) {
          Future<void> pick(List<String> target) async {
            final picked = await ImagePicker().pickImage(
                source: ImageSource.gallery,
                maxWidth: 1280,
                imageQuality: 85);
            if (picked == null) return;
            setSheet(() => uploading = true);
            try {
              final url = await widget.api
                  .uploadImage(await picked.readAsBytes(), picked.name);
              setSheet(() => target.add(url));
            } catch (_) {
            } finally {
              setSheet(() => uploading = false);
            }
          }

          return Padding(
            padding: EdgeInsets.only(
                left: 16, right: 16, top: 16,
                bottom:
                    MediaQuery.of(sheetContext).viewInsets.bottom + 16),
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('食品安全投诉',
                      style: TextStyle(
                          color: Colors.red,
                          fontWeight: FontWeight.bold,
                          fontSize: 16)),
                  Text('不经商家、直达平台加急处理;核实成立全额退款(含配送费)',
                      style: Theme.of(sheetContext).textTheme.bodySmall),
                  const SizedBox(height: 8),
                  RadioGroup<String>(
                    groupValue: kind,
                    onChanged: (v) => setSheet(() => kind = v!),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        for (final (value, label) in const [
                          ('foreign_object', '吃出异物'),
                          ('spoiled', '食物变质/异味'),
                          ('sick', '食用后身体不适'),
                        ])
                          RadioListTile<String>(
                              dense: true, value: value, title: Text(label)),
                      ],
                    ),
                  ),
                  TextField(
                    controller: desc,
                    maxLength: 500,
                    maxLines: 3,
                    decoration: const InputDecoration(
                        hintText: '描述情况(何时食用、发现了什么、身体状况等)',
                        border: OutlineInputBorder()),
                  ),
                  const SizedBox(height: 4),
                  Text('问题食品拍照(必传):',
                      style: Theme.of(sheetContext).textTheme.bodySmall),
                  const SizedBox(height: 6),
                  Wrap(spacing: 6, runSpacing: 6, children: [
                    for (final url in images)
                      ClipRRect(
                        borderRadius: BorderRadius.circular(6),
                        child: Image.network(widget.api.resolveUrl(url),
                            width: 56, height: 56, fit: BoxFit.cover),
                      ),
                    if (images.length < 6)
                      OutlinedButton.icon(
                        icon: const Icon(Icons.add_a_photo, size: 16),
                        label: Text(uploading ? '上传中…' : '拍照'),
                        onPressed: uploading ? null : () => pick(images),
                      ),
                  ]),
                  const SizedBox(height: 8),
                  Text('医疗凭证(选传,食用后不适建议附上):',
                      style: Theme.of(sheetContext).textTheme.bodySmall),
                  const SizedBox(height: 6),
                  Wrap(spacing: 6, runSpacing: 6, children: [
                    for (final url in medical)
                      ClipRRect(
                        borderRadius: BorderRadius.circular(6),
                        child: Image.network(widget.api.resolveUrl(url),
                            width: 56, height: 56, fit: BoxFit.cover),
                      ),
                    if (medical.length < 6)
                      OutlinedButton.icon(
                        icon: const Icon(Icons.medical_information_outlined,
                            size: 16),
                        label: Text(uploading ? '上传中…' : '添加'),
                        onPressed: uploading ? null : () => pick(medical),
                      ),
                  ]),
                  const SizedBox(height: 12),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      style: FilledButton.styleFrom(
                          backgroundColor: Colors.red),
                      onPressed: () => Navigator.pop(sheetContext, true),
                      child: const Text('提交食安投诉'),
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
    if (submitted != true || !mounted) return;
    if (desc.text.trim().length < 4) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请描述具体情况(至少 4 个字)')));
      return;
    }
    if (images.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('食安投诉必须拍照举证(问题食品照片)')));
      return;
    }
    try {
      await widget.api.reportFoodSafety(widget.orderNo, kind,
          desc.text.trim(), images, medicalUrls: medical);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('食安投诉已提交,平台加急处理;核实成立将全额退款')));
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _applyAfterSale() async {
    final controller = TextEditingController();
    final images = <String>[];
    var uploading = false;
    final submitted = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialog) => AlertDialog(
          title: const Text('申请售后'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: controller,
                maxLength: 500,
                maxLines: 3,
                decoration: const InputDecoration(
                  hintText: '说说遇到的问题(如洒漏、少送、有异物)',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 4),
              Text('拍照举证(必传,最多 3 张):有图才能快速判责退款',
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 6),
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final url in images)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: Image.network(widget.api.resolveUrl(url),
                        width: 56, height: 56, fit: BoxFit.cover),
                  ),
                if (images.length < 3)
                  OutlinedButton.icon(
                    icon: uploading
                        ? const SizedBox(
                            width: 14, height: 14,
                            child: CircularProgressIndicator(strokeWidth: 2))
                        : const Icon(Icons.add_a_photo, size: 16),
                    label: Text(uploading ? '上传中…' : '加照片'),
                    onPressed: uploading
                        ? null
                        : () async {
                            final picked = await ImagePicker().pickImage(
                                source: ImageSource.gallery,
                                maxWidth: 1280,
                                imageQuality: 85);
                            if (picked == null) return;
                            setDialog(() => uploading = true);
                            try {
                              final url = await widget.api.uploadImage(
                                  await picked.readAsBytes(), picked.name);
                              setDialog(() => images.add(url));
                            } catch (e) {
                              if (context.mounted) {
                                ScaffoldMessenger.of(context).showSnackBar(
                                    SnackBar(content: Text('上传失败:$e')));
                              }
                            } finally {
                              setDialog(() => uploading = false);
                            }
                          },
                  ),
              ]),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('提交')),
          ],
        ),
      ),
    );
    if (submitted != true) return;
    final reason = controller.text.trim();
    if (reason.length < 4) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('请描述遇到的问题(至少 4 个字)')));
      }
      return;
    }
    if (images.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('请至少上传 1 张照片举证')));
      }
      return;
    }
    try {
      final afterSale = await widget.api
          .submitAfterSale(widget.orderNo, reason, images: images);
      if (mounted) setState(() => _afterSale = afterSale);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _call(String phone) async {
    final uri = Uri(scheme: 'tel', path: phone);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    } else if (mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('请手动拨打 $phone')));
    }
  }

  /// 送达时间条:预约单显示预约时刻;普通活跃单 = 下单时间 + 备餐 10 分钟
  /// + 路程 ETA。超过预计时间不装死,主动说"抱歉晚了"。
  String? _etaLabel(Order order) {
    const active = [OrderStatus.paid, OrderStatus.accepted,
        OrderStatus.ready, OrderStatus.pickedUp];
    if (!active.contains(order.status)) return null;
    if (order.scheduledLabel != null) return '⏰ ${order.scheduledLabel}';
    // 服务端 ETA(支付时生成,超时 15 分钟平台自动赔安抚券)优先;
    // 老订单没有 eta_at 时退回本地估算
    DateTime? expect =
        order.etaAt == null ? null : DateTime.tryParse(order.etaAt!)?.toLocal();
    if (expect == null) {
      final created = DateTime.tryParse(order.createdAt)?.toLocal();
      if (created == null || order.merchantLat == null) return null;
      final rideMin = etaMinutes(distanceMeters(order.merchantLat!,
          order.merchantLng!, order.lat, order.lng));
      expect = created.add(Duration(minutes: 10 + rideMin));
    }
    final left = expect.difference(DateTime.now()).inMinutes;
    final hhmm = '${expect.hour.toString().padLeft(2, '0')}:'
        '${expect.minute.toString().padLeft(2, '0')}';
    if (left >= 0) return '预计 $hhmm 前送达 · 还有约 $left 分钟';
    return '抱歉,比预计($hhmm)晚了一些;超 15 分钟平台自动赔安抚券';
  }

  Future<void> _submitReview(int merchantRating, int? riderRating,
      String comment, List<String> imageUrls, List<String> tags,
      bool isAnonymous) async {
    try {
      final review = await widget.api.submitReview(
        widget.orderNo,
        merchantRating: merchantRating,
        riderRating: riderRating,
        comment: comment,
        imageUrls: imageUrls,
        tags: tags,
        isAnonymous: isAnonymous,
      );
      if (mounted) setState(() => _review = review);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 改地址:选新地址 → 服务端校验(半径/一次/取餐前)并处理差价退款
  Future<void> _changeAddress(Order order) async {
    final picked = await Navigator.of(context).push<Address>(MaterialPageRoute(
        builder: (_) => AddressBookPage(api: widget.api, selectMode: true)));
    if (picked == null || !mounted) return;
    try {
      await widget.api.changeAddress(order.orderNo, picked);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('地址已修改;配送费如有差价将自动退回')));
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 催单:服务端自动判定催商家还是骑手,控频与上限也在服务端
  Future<void> _urge(Order order) async {
    try {
      final r = await widget.api.urgeOrder(order.orderNo);
      if (!mounted) return;
      final target = r['target'] == 'rider' ? '骑手' : '商家';
      final left = r['times_left'] as int? ?? 0;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('已帮你催$target(本单还可催 $left 次)')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 加急小费:无人接单时追加小费(纯用户出、100% 归骑手,平台不补贴)
  Future<void> _boostTip(Order order) async {
    const options = [200, 300, 500, 800]; // 元档:2/3/5/8
    final add = await showModalBottomSheet<int>(
      context: context,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(14),
              child: Text('加急小费,更快有人接',
                  style: TextStyle(fontWeight: FontWeight.bold)),
            ),
            const Padding(
              padding: EdgeInsets.only(bottom: 8, left: 14, right: 14),
              child: Text('小费 100% 归骑手,平台不抽成。加了会立刻通知附近骑手。',
                  style: TextStyle(fontSize: 12, color: Colors.grey)),
            ),
            for (final c in options)
              ListTile(
                leading: const Icon(Icons.bolt, color: Colors.orange),
                title: Text('加 ¥${(c / 100).toStringAsFixed(0)}'),
                onTap: () => Navigator.pop(context, c),
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (add == null) return;
    try {
      await widget.api.boostTip(order.orderNo, add);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('已加急 ¥${(add / 100).toStringAsFixed(0)},'
              '已通知附近骑手')));
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 用户取消:选原因 → 提交;窗口限制由服务端判定(超窗给出中文提示)
  Future<void> _cancelOrder(Order order) async {
    const reasons = ['点错了/重新下单', '不想要了', '地址/电话填错', '其他原因'];
    final reason = await showModalBottomSheet<String>(
      context: context,
      builder: (context) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(14),
              child: Text('选择取消原因',
                  style: TextStyle(fontWeight: FontWeight.bold)),
            ),
            for (final r in reasons)
              ListTile(
                dense: true,
                title: Text(r),
                onTap: () => Navigator.pop(context, r),
              ),
          ],
        ),
      ),
    );
    if (reason == null || !mounted) return;
    try {
      await widget.api
          .transition(order.orderNo, OrderStatus.cancelled, reason: reason);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('订单已取消,已支付金额将全额退回')));
      _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  @override
  Widget build(BuildContext context) {
    final order = _order;
    return Scaffold(
      appBar: AppBar(title: const Text('订单详情')),
      body: order == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                Center(
                  child: Column(children: [
                    Text(order.status.label,
                        style: Theme.of(context).textTheme.headlineMedium),
                    const SizedBox(height: 4),
                    if (_etaLabel(order) != null)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 4),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 12, vertical: 5),
                          decoration: BoxDecoration(
                            color: Theme.of(context)
                                .colorScheme
                                .primary
                                .withValues(alpha: 0.10),
                            borderRadius: BorderRadius.circular(14),
                          ),
                          child: Text(_etaLabel(order)!,
                              style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                  color:
                                      Theme.of(context).colorScheme.primary)),
                        ),
                      ),
                    Text('订单号 ${order.orderNo}',
                        style: Theme.of(context).textTheme.bodySmall),
                    if (order.status == OrderStatus.cancelled &&
                        order.cancelReason.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(top: 4),
                        child: Text('原因:${order.cancelReason}',
                            style: TextStyle(
                                color: Theme.of(context).colorScheme.error)),
                      ),
                  ]),
                ),
                const SizedBox(height: 16),
                // 自取单:取餐码大卡(出餐后商家凭此核销)
                if (order.pickup &&
                    order.pickupCode.isNotEmpty &&
                    order.status.index >= OrderStatus.paid.index &&
                    order.status != OrderStatus.cancelled &&
                    order.status != OrderStatus.completed)
                  Card(
                    color: Theme.of(context)
                        .colorScheme
                        .primary
                        .withValues(alpha: 0.08),
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(children: [
                        Text('取餐码',
                            style: Theme.of(context).textTheme.bodySmall),
                        Text(order.pickupCode,
                            style: Theme.of(context)
                                .textTheme
                                .displayMedium
                                ?.copyWith(
                                    fontWeight: FontWeight.bold,
                                    letterSpacing: 8,
                                    color:
                                        Theme.of(context).colorScheme.primary)),
                        const SizedBox(height: 4),
                        Text(
                            order.status == OrderStatus.ready
                                ? '餐已备好,到店报取餐码即可取餐'
                                : '出餐后到店报取餐码取餐',
                            style: Theme.of(context).textTheme.bodySmall),
                        Text('取餐点:${order.merchantName} ${order.merchantAddress}',
                            style: Theme.of(context).textTheme.bodySmall,
                            textAlign: TextAlign.center),
                      ]),
                    ),
                  ),
                if (order.status != OrderStatus.cancelled &&
                    order.status != OrderStatus.completed)
                  _OrderTimeline(events: _events, order: order),
                // 晒一晒:带「钱去哪了」分账条的分享图,金额默认打码可开关
                if (order.status == OrderStatus.completed)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        icon: const Icon(Icons.ios_share, size: 18),
                        label: const Text('晒一晒(钱去哪了,一目了然)'),
                        onPressed: () async {
                          var mask = true;
                          final go = await showDialog<bool>(
                            context: context,
                            builder: (context) => StatefulBuilder(
                              builder: (context, setState) => AlertDialog(
                                title: const Text('晒单设置'),
                                content: SwitchListTile(
                                  title: const Text('金额打码'),
                                  subtitle: const Text('关闭则显示真实金额'),
                                  value: mask,
                                  onChanged: (v) =>
                                      setState(() => mask = v),
                                ),
                                actions: [
                                  TextButton(
                                      onPressed: () =>
                                          Navigator.pop(context, false),
                                      child: const Text('取消')),
                                  FilledButton(
                                      onPressed: () =>
                                          Navigator.pop(context, true),
                                      child: const Text('生成分享图')),
                                ],
                              ),
                            ),
                          );
                          if (go != true || !context.mounted) return;
                          showShareCard(context,
                              orderShareCard(order, maskAmount: mask),
                              event: 'share_order',
                              props: {'order_no': order.orderNo});
                        },
                      ),
                    ),
                  ),
                // 地址保护:骑手到楼下后可一键临时放行完整门牌
                if (order.addrProtect &&
                    !order.addrRevealed &&
                    order.status.index >= OrderStatus.paid.index &&
                    order.status.index < OrderStatus.delivered.index)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: SizedBox(
                      width: double.infinity,
                      child: OutlinedButton.icon(
                        icon: const Icon(Icons.lock_open_outlined, size: 18),
                        label: const Text('临时放行完整门牌(骑手已到楼下时)'),
                        onPressed: () async {
                          try {
                            await widget.api.revealAddress(order.orderNo);
                            _refresh();
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                    content: Text('已放行,骑手可见完整门牌(仅本单)')));
                          } catch (e) {
                            if (!context.mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(content: Text(e.toString())));
                          }
                        },
                      ),
                    ),
                  ),
                if (_review != null && _review!.appendAt == null) ...[
                  const SizedBox(height: 4),
                  SizedBox(
                    width: double.infinity,
                    child: OutlinedButton.icon(
                      icon: const Icon(Icons.rate_review_outlined, size: 18),
                      label: const Text('追评(7 天内一次)'),
                      onPressed: () async {
                        final content = TextEditingController();
                        final ok = await showDialog<bool>(
                          context: context,
                          builder: (context) => AlertDialog(
                            title: const Text('追评'),
                            content: TextField(
                                controller: content,
                                maxLength: 200,
                                maxLines: 3,
                                decoration: const InputDecoration(
                                    hintText: '吃完过了几天,再补充点感受…',
                                    border: OutlineInputBorder())),
                            actions: [
                              TextButton(
                                  onPressed: () =>
                                      Navigator.pop(context, false),
                                  child: const Text('取消')),
                              FilledButton(
                                  onPressed: () =>
                                      Navigator.pop(context, true),
                                  child: const Text('提交')),
                            ],
                          ),
                        );
                        if (ok != true || !mounted) return;
                        final messenger = ScaffoldMessenger.of(this.context);
                        try {
                          final updated = await widget.api.appendReview(
                              _review!.id,
                              content: content.text.trim());
                          if (mounted) setState(() => _review = updated);
                        } catch (e) {
                          if (!mounted) return;
                          messenger.showSnackBar(
                              SnackBar(content: Text(e.toString())));
                        }
                      },
                    ),
                  ),
                ],
                if (order.deliveryPhotoUrl.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Row(children: [
                    const Icon(Icons.photo_camera_outlined, size: 16),
                    const SizedBox(width: 6),
                    const Text('送达留证:', style: TextStyle(fontSize: 12)),
                    TextButton(
                        onPressed: () => showDialog<void>(
                            context: context,
                            builder: (_) => Dialog(
                                child: Image.network(
                                    order.deliveryPhotoUrl))),
                        child: const Text('查看照片')),
                  ]),
                ],
                // 联系骑手/商家(配送中显性化)
                if (order.status.index >= OrderStatus.paid.index &&
                    order.status != OrderStatus.cancelled)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Row(
                      children: [
                        if (order.riderId != null)
                          Expanded(
                            child: OutlinedButton.icon(
                              icon: const Icon(Icons.chat_bubble_outline,
                                  size: 18),
                              label: const Text('骑手'),
                              onPressed: () => Navigator.of(context).push(
                                  MaterialPageRoute(
                                      builder: (_) => OrderChatPage(
                                          api: widget.api,
                                          orderNo: order.orderNo,
                                          title: '和骑手说句话',
                                          peer: 'rider',
                                          quickReplies:
                                              kCustomerQuickReplies))),
                            ),
                          ),
                        if (order.riderId != null) const SizedBox(width: 8),
                        Expanded(
                          child: OutlinedButton.icon(
                            icon: const Icon(Icons.storefront, size: 18),
                            label: const Text('商家'),
                            onPressed: () => Navigator.of(context).push(
                                MaterialPageRoute(
                                    builder: (_) => OrderChatPage(
                                        api: widget.api,
                                        orderNo: order.orderNo,
                                        title: '和商家说句话',
                                        peer: 'merchant',
                                        quickReplies:
                                            kCustomerQuickReplies))),
                          ),
                        ),
                        if (order.riderPhone.isNotEmpty) ...[
                          const SizedBox(width: 8),
                          IconButton.outlined(
                            icon: const Icon(Icons.call, size: 18),
                            tooltip: '打电话(兜底)',
                            onPressed: () => _call(order.riderPhone),
                          ),
                        ] else if (order.merchantPhone.isNotEmpty) ...[
                          const SizedBox(width: 8),
                          IconButton.outlined(
                            icon: const Icon(Icons.call, size: 18),
                            tooltip: '打电话(兜底)',
                            onPressed: () => _call(order.merchantPhone),
                          ),
                        ],
                      ],
                    ),
                  ),
                const Divider(height: 32),
                for (final item in order.items)
                  ListTile(
                    dense: true,
                    title: Text(item.name),
                    trailing: Text('${yuan(item.priceCents)} ×${item.quantity}'),
                  ),
                ListTile(
                  dense: true,
                  title: const Text('配送费'),
                  trailing: Text(yuan(order.deliveryFeeCents)),
                ),
                ListTile(
                  title: const Text('合计'),
                  trailing: Text(yuan(order.totalCents),
                      style: Theme.of(context).textTheme.titleMedium),
                ),
                if (order.refundCents > 0)
                  _RefundProgressCard(order: order, refunds: _refunds),
                if (order.commissionCents > 0) ...[
                  _MoneyFlowCard(order: order),
                  const SizedBox(height: 10),
                  // 承诺卡:品牌渐变唯一允许出现处(风格系统规则⑦)
                  const PledgeCard(
                    title: '超级赞承诺',
                    body: '商家只抽 5% · 配送费 100% 归骑手 · 账目三方公开,写进开源代码可验证',
                  ),
                ],
                const Divider(height: 32),
                Text('配送至:${order.address}'),
                const SizedBox(height: 24),
                if (order.riderId != null &&
                    (order.status == OrderStatus.ready ||
                        order.status == OrderStatus.pickedUp))
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: FilledButton.tonalIcon(
                      icon: const Icon(Icons.map),
                      label: const Text('看骑手到哪了'),
                      onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute(
                              builder: (_) => DeliveryMapPage(
                                  api: widget.api, order: order))),
                    ),
                  ),
                if (order.status == OrderStatus.delivered)
                  FilledButton(
                    onPressed: () async {
                      await widget.api
                          .transition(order.orderNo, OrderStatus.completed);
                      _refresh();
                    },
                    child: const Text('确认收货'),
                  ),
                if (order.status == OrderStatus.completed) ...[
                  OutlinedButton.icon(
                    icon: const Icon(Icons.replay),
                    label: const Text('再来一单'),
                    onPressed: () async {
                      try {
                        final shop =
                            await widget.api.merchantDetail(order.merchantId);
                        if (!context.mounted) return;
                        Navigator.of(context).push(MaterialPageRoute(
                            builder: (_) => MenuPage(
                                  api: widget.api,
                                  merchant: shop,
                                  initialCart: {
                                    for (final item in order.items)
                                      if (item.dishId > 0)
                                        item.dishId: item.quantity,
                                  },
                                )));
                      } catch (e) {
                        if (!context.mounted) return;
                        ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(content: Text(e.toString())));
                      }
                    },
                  ),
                  _review != null
                      ? _ReviewDisplay(review: _review!)
                      : _ReviewForm(
                          hasRider: order.riderId != null,
                          api: widget.api,
                          onSubmit: _submitReview,
                        ),
                ],
                // 售后:已送达/已完成订单可申请;已申请显示状态卡
                if (order.status == OrderStatus.delivered ||
                    order.status == OrderStatus.completed)
                  _afterSale == null
                      ? Align(
                          alignment: Alignment.center,
                          child: TextButton.icon(
                            icon: const Icon(Icons.support_agent, size: 18),
                            label: const Text('遇到问题?申请售后'),
                            onPressed: _chooseAfterSaleKind,
                          ),
                        )
                      : Card(
                          margin: const EdgeInsets.only(top: 8),
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(children: [
                                  Icon(
                                    switch (_afterSale!.status) {
                                      'accepted' => Icons.check_circle,
                                      'rejected' => Icons.info,
                                      _ => Icons.hourglass_top,
                                    },
                                    size: 18,
                                    color: _afterSale!.status == 'accepted'
                                        ? Colors.green
                                        : Theme.of(context)
                                            .colorScheme
                                            .primary,
                                  ),
                                  const SizedBox(width: 6),
                                  Text('售后:${_afterSale!.statusLabel}',
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleSmall
                                          ?.copyWith(
                                              fontWeight: FontWeight.bold)),
                                ]),
                                const SizedBox(height: 4),
                                Text('我的申请:${_afterSale!.reason}',
                                    style:
                                        Theme.of(context).textTheme.bodySmall),
                                if (_afterSale!.reply.isNotEmpty)
                                  Padding(
                                    padding: const EdgeInsets.only(top: 4),
                                    child: Text('商家回复:${_afterSale!.reply}'),
                                  ),
                                if (_afterSale!.status == 'rejected')
                                  Padding(
                                    padding: const EdgeInsets.only(top: 4),
                                    child: InkWell(
                                      onTap: () => Navigator.of(context).push(
                                          MaterialPageRoute(
                                              builder: (_) => SupportPage(
                                                  api: widget.api,
                                                  prefill:
                                                      '售后申诉,订单号 ${order.orderNo}:'))),
                                      child: Text('如有异议,点此联系平台客服申诉 >',
                                          style: Theme.of(context)
                                              .textTheme
                                              .bodySmall
                                              ?.copyWith(
                                                  color: Theme.of(context)
                                                      .colorScheme
                                                      .primary)),
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ),
                if (order.status.index >= OrderStatus.paid.index &&
                    order.status.index <= OrderStatus.pickedUp.index &&
                    !(order.pickup && order.status == OrderStatus.ready))
                  OutlinedButton.icon(
                    icon: const Icon(Icons.notifications_active_outlined,
                        size: 18),
                    onPressed: () => _urge(order),
                    label: const Text('催一下'),
                  ),
                // 无人接单告警中:加急小费(100% 归骑手),更快有人接
                if (order.noRiderAlerted &&
                    order.riderId == null &&
                    !order.pickup &&
                    !order.selfDelivery)
                  FilledButton.tonalIcon(
                    icon: const Icon(Icons.bolt, size: 18),
                    onPressed: () => _boostTip(order),
                    label: Text(order.tipCents > 0
                        ? '加急小费(已加 ¥${(order.tipCents / 100).toStringAsFixed(0)})'
                        : '加急小费,更快有人接'),
                  ),
                if (!order.pickup &&
                    order.parentOrderNo.isEmpty &&
                    (order.status == OrderStatus.paid ||
                        order.status == OrderStatus.accepted))
                  OutlinedButton.icon(
                    icon: const Icon(Icons.add_shopping_cart_outlined,
                        size: 18),
                    onPressed: () async {
                      await Navigator.of(context).push(MaterialPageRoute(
                          builder: (_) => AppendOrderPage(
                              api: widget.api, parent: order)));
                      _refresh();
                    },
                    label: const Text('加菜(随本单一起送)'),
                  ),
                if (!order.pickup &&
                    (order.status == OrderStatus.paid ||
                        order.status == OrderStatus.accepted ||
                        order.status == OrderStatus.ready))
                  OutlinedButton.icon(
                    icon: const Icon(Icons.edit_location_alt_outlined,
                        size: 18),
                    onPressed: () => _changeAddress(order),
                    label: const Text('改地址(骑手取餐前)'),
                  ),
                if (order.status == OrderStatus.paid ||
                    order.status == OrderStatus.accepted)
                  OutlinedButton(
                    onPressed: () => _cancelOrder(order),
                    child: Text(order.status == OrderStatus.paid
                        ? '取消订单(商家接单前免费)'
                        : '取消订单(接单 2 分钟内可反悔)'),
                  ),
                // 退款/售后:自助能退的即时退,不能的转人工带上下文(减少工单)
                if (order.status.index >= OrderStatus.accepted.index &&
                    order.status.index <= OrderStatus.delivered.index)
                  TextButton.icon(
                    icon: const Icon(Icons.support_agent_outlined, size: 18),
                    onPressed: () => _refundOrSupport(order),
                    label: const Text('退款 / 售后'),
                  ),
              ],
            ),
    );
  }

  /// 退款/售后:先判能否自助退,能则即时退,不能则转人工工单(预填上下文)
  Future<void> _refundOrSupport(Order order) async {
    Map<String, dynamic> chk;
    try {
      chk = await widget.api.selfRefundCheck(order.orderNo);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
      return;
    }
    if (!mounted) return;
    if (chk['eligible'] == true) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('自助退款'),
          content: Text('${chk['reason']},将全额退回原路。确认退款?'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: const Text('再想想')),
            FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: const Text('确认退款')),
          ],
        ),
      );
      if (ok != true) return;
      try {
        await widget.api.selfRefund(order.orderNo);
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('已退款,款项原路退回')));
        _refresh();
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.toString())));
      }
    } else {
      // 转人工:带上订单上下文预填工单
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => SupportPage(
              api: widget.api,
              prefill: (chk['ticket_context'] as String?) ?? '')));
    }
  }
}

/// 五星选择器
class _Stars extends StatelessWidget {
  const _Stars({required this.value, required this.onChanged});

  final int value;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 1; i <= 5; i++)
          IconButton(
            visualDensity: VisualDensity.compact,
            icon: Icon(
              i <= value ? Icons.star : Icons.star_border,
              color: Colors.amber,
            ),
            onPressed: () => onChanged(i),
          ),
      ],
    );
  }
}

class _ReviewForm extends StatefulWidget {
  const _ReviewForm(
      {required this.hasRider, required this.api, required this.onSubmit});

  final bool hasRider;
  final ApiClient api;
  final Future<void> Function(
      int merchantRating,
      int? riderRating,
      String comment,
      List<String> imageUrls,
      List<String> tags,
      bool isAnonymous) onSubmit;

  @override
  State<_ReviewForm> createState() => _ReviewFormState();
}

class _ReviewFormState extends State<_ReviewForm> {
  int _merchantRating = 5;
  int _riderRating = 5;
  final _comment = TextEditingController();
  final List<String> _imageUrls = [];
  final Set<String> _tags = {};
  bool _anonymous = false; // 真匿名:商家侧完全不可反查
  bool _uploading = false;
  bool _busy = false;

  /// 图评是最有说服力的口碑,选图直接上传(最多 3 张)
  Future<void> _pickImage() async {
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 1280, imageQuality: 85);
    if (picked == null) return;
    setState(() => _uploading = true);
    try {
      final url = await widget.api
          .uploadImage(await picked.readAsBytes(), picked.name);
      if (mounted) setState(() => _imageUrls.add(url));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('上传失败:$e')));
    } finally {
      if (mounted) setState(() => _uploading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('评价这一单', style: Theme.of(context).textTheme.titleMedium),
            Row(children: [
              const Text('商家'),
              _Stars(
                  value: _merchantRating,
                  onChanged: (v) => setState(() => _merchantRating = v)),
            ]),
            if (widget.hasRider)
              Row(children: [
                const Text('骑手'),
                _Stars(
                    value: _riderRating,
                    onChanged: (v) => setState(() => _riderRating = v)),
              ]),
            Wrap(
              spacing: 6,
              runSpacing: 2,
              children: [
                for (final tag in kReviewTags)
                  FilterChip(
                    label: Text(tag, style: const TextStyle(fontSize: 12)),
                    selected: _tags.contains(tag),
                    visualDensity: VisualDensity.compact,
                    onSelected: (on) => setState(() {
                      if (on && _tags.length < 4) {
                        _tags.add(tag);
                      } else {
                        _tags.remove(tag);
                      }
                    }),
                  ),
              ],
            ),
            TextField(
              controller: _comment,
              maxLength: 500,
              decoration: const InputDecoration(
                  hintText: '说说菜品和配送体验(选填)'),
            ),
            Row(
              children: [
                for (final url in _imageUrls)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: Stack(
                      children: [
                        ClipRRect(
                          borderRadius: BorderRadius.circular(8),
                          child: Image.network(
                              widget.api.resolveUrl(url),
                              width: 64, height: 64, fit: BoxFit.cover),
                        ),
                        Positioned(
                          right: 0,
                          top: 0,
                          child: InkWell(
                            onTap: () =>
                                setState(() => _imageUrls.remove(url)),
                            child: Container(
                              decoration: const BoxDecoration(
                                  color: Colors.black54,
                                  shape: BoxShape.circle),
                              child: const Icon(Icons.close,
                                  size: 16, color: Colors.white),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                if (_imageUrls.length < 3)
                  InkWell(
                    onTap: _uploading ? null : _pickImage,
                    borderRadius: BorderRadius.circular(8),
                    child: Container(
                      width: 64,
                      height: 64,
                      decoration: BoxDecoration(
                        border: Border.all(
                            color: Theme.of(context).colorScheme.outline),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: _uploading
                          ? const Center(
                              child: SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                      strokeWidth: 2)))
                          : const Icon(Icons.add_a_photo_outlined,
                              size: 22),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Row(children: [
              Expanded(
                child: CheckboxListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: const Text('匿名评价(商家无法看到你是谁)',
                      style: TextStyle(fontSize: 13)),
                  value: _anonymous,
                  onChanged: (v) =>
                      setState(() => _anonymous = v ?? false),
                ),
              ),
              FilledButton(
                onPressed: _busy
                    ? null
                    : () async {
                        setState(() => _busy = true);
                        await widget.onSubmit(
                          _merchantRating,
                          widget.hasRider ? _riderRating : null,
                          _comment.text.trim(),
                          _imageUrls,
                          _tags.toList(),
                          _anonymous,
                        );
                        if (mounted) setState(() => _busy = false);
                      },
                child: Text(_busy ? '提交中…' : '提交评价'),
              ),
            ]),
          ],
        ),
      ),
    );
  }
}

class _ReviewDisplay extends StatelessWidget {
  const _ReviewDisplay({required this.review});

  final Review review;

  String _stars(int n) => '★' * n + '☆' * (5 - n);

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(top: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('我的评价', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            Text('商家 ${_stars(review.merchantRating)}',
                style: const TextStyle(color: Colors.amber)),
            if (review.riderRating != null)
              Text('骑手 ${_stars(review.riderRating!)}',
                  style: const TextStyle(color: Colors.amber)),
            if (review.comment.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(review.comment),
            ],
          ],
        ),
      ),
    );
  }
}

/// 「我的」:头像/昵称、平台理念、收藏、发票、地址、退出。
class ProfileView extends StatefulWidget {
  const ProfileView({super.key, required this.api});

  final ApiClient api;

  @override
  State<ProfileView> createState() => _ProfileViewState();
}

class _ProfileViewState extends State<ProfileView> {
  UserProfile? _profile;
  // 营销总开关(服务端 /config):关着时邀请有礼等入口整体隐藏
  bool _marketingOn = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final profile = await widget.api.me();
      if (mounted) setState(() => _profile = profile);
    } catch (_) {}
    try {
      final config = await widget.api.platformConfig();
      if (mounted) {
        setState(() => _marketingOn = config['marketing'] == true);
      }
    } catch (_) {}
  }

  Future<void> _editBirthdayAndPush() async {
    final me = _profile ?? await widget.api.me();
    if (!mounted) return;
    final birthday = TextEditingController(text: me.birthday);
    var push = me.marketingPush;
    await showDialog<void>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => AlertDialog(
          title: const Text('生日与营销推送'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(
                controller: birthday,
                decoration: const InputDecoration(
                    labelText: '生日(MM-DD,选填)',
                    helperText: '只收集月日,生日当天送券',
                    border: OutlineInputBorder())),
            SwitchListTile(
                title: const Text('接收营销推送'),
                subtitle: const Text('生日/优惠/收藏店上新;订单通知不受影响'),
                value: push,
                onChanged: (v) => setState(() => push = v)),
          ]),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('取消')),
            FilledButton(
              onPressed: () async {
                try {
                  await widget.api.updateMe(
                      birthday: birthday.text.trim(), marketingPush: push);
                  if (context.mounted) Navigator.pop(context);
                } catch (e) {
                  if (!context.mounted) return;
                  ScaffoldMessenger.of(context)
                      .showSnackBar(SnackBar(content: Text(e.toString())));
                }
              },
              child: const Text('保存'),
            ),
          ],
        ),
      ),
    );
    _load();
  }

  Future<void> _pickAvatar() async {
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 512, imageQuality: 85);
    if (picked == null) return;
    try {
      final url = await widget.api
          .uploadImage(await picked.readAsBytes(), picked.name);
      await widget.api.updateMe(avatarUrl: url);
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  Future<void> _editName() async {
    final controller = TextEditingController(text: _profile?.name ?? '');
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('修改昵称'),
        content: TextField(
            controller: controller,
            maxLength: 50,
            decoration: const InputDecoration(border: OutlineInputBorder())),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(context, controller.text.trim()),
              child: const Text('保存')),
        ],
      ),
    );
    if (name == null || name.isEmpty) return;
    try {
      await widget.api.updateMe(name: name);
      _load();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  void _showInvoiceInfo() {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('开发票'),
        content: const Text(
            '电子发票功能将在接入微信支付后开放。\n\n'
            '现阶段如需发票,请直接联系商家或平台客服,'
            '我们会协助你完成开票。',
            style: TextStyle(height: 1.6)),
        actions: [
          TextButton(
              onPressed: () {
                Navigator.pop(context);
                Navigator.of(this.context).push(MaterialPageRoute(
                    builder: (_) => SupportPage(
                        api: widget.api, prefill: '我需要开发票,订单号:')));
              },
              child: const Text('联系客服')),
          FilledButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('我知道了')),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final profile = _profile;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        // 反作弊处置提示(可见+可申诉):绝不静默处罚
        if (profile != null && profile.riskLevel.isNotEmpty)
          Card(
            color: theme.colorScheme.errorContainer,
            child: ListTile(
              leading: Icon(Icons.info_outline,
                  color: theme.colorScheme.onErrorContainer),
              title: Text(
                  profile.riskLevel == 'frozen'
                      ? '账号使用受限(冻结,待人工复核)'
                      : '账号营销权益暂被限制',
                  style: TextStyle(
                      color: theme.colorScheme.onErrorContainer,
                      fontWeight: FontWeight.bold)),
              subtitle: Text(
                  '${profile.riskNote.isEmpty ? "系统检测到异常" : profile.riskNote}'
                  '\n下单不受影响;如有疑问点此联系客服申诉',
                  style: TextStyle(color: theme.colorScheme.onErrorContainer)),
              isThreeLine: true,
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => SupportPage(
                      api: widget.api,
                      prefill: '对账号限制有疑问,申请复核:'
                          '${profile.riskNote}'))),
            ),
          ),
        Card(
          child: ListTile(
            leading: InkWell(
              onTap: _pickAvatar,
              borderRadius: BorderRadius.circular(28),
              child: profile != null && profile.avatarUrl.isNotEmpty
                  ? CircleAvatar(
                      radius: 26,
                      backgroundImage: NetworkImage(
                          widget.api.resolveUrl(profile.avatarUrl)))
                  : const CircleAvatar(
                      radius: 26, child: Icon(Icons.add_a_photo, size: 20)),
            ),
            title: Text(profile?.name ?? widget.api.userName ?? '用户',
                style: theme.textTheme.titleLarge),
            subtitle: Text(profile?.phone ?? '感谢你支持劳动者互助平台'),
            trailing: const Icon(Icons.edit, size: 18),
            onTap: _editName,
          ),
        ),
        const SizedBox(height: 8),
        Card(
          color: theme.colorScheme.tertiaryContainer,
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            // 点进去是实数与公开账本,不是口号——信任的最终来源
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => TrustPage(api: widget.api))),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text('为什么选择超级赞?',
                            style: theme.textTheme.titleMedium?.copyWith(
                                color: theme.colorScheme.onTertiaryContainer,
                                fontWeight: FontWeight.bold)),
                      ),
                      Icon(Icons.chevron_right,
                          size: 20,
                          color: theme.colorScheme.onTertiaryContainer),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '· 商家只被抽成 5%(大平台 20%+),菜价更实在\n'
                    '· 配送费 100% 归骑手,平台分文不取\n'
                    '· 每一单的钱去了哪里,订单里全部透明可查\n\n'
                    '点击查看实时账目、资金去向与社区见证节点。',
                    style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.onTertiaryContainer,
                        height: 1.6),
                  ),
                ],
              ),
            ),
          ),
        ),
        const SizedBox(height: 8),
        // 高频三件套:快捷格(与首页金刚区同一视觉语言)
        Card(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(
              children: [
                for (final (icon, label, page) in [
                  (Icons.local_activity_outlined, '优惠券',
                      () => CouponsPage(api: widget.api) as Widget),
                  (Icons.confirmation_number_outlined, '团购券',
                      () => MyVouchersPage(api: widget.api) as Widget),
                  (Icons.favorite_outline, '我的收藏',
                      () => FavoritesPage(api: widget.api) as Widget),
                  (Icons.place_outlined, '收货地址',
                      () => AddressBookPage(api: widget.api) as Widget),
                ])
                  Expanded(
                    child: InkWell(
                      borderRadius: BorderRadius.circular(12),
                      onTap: () => Navigator.of(context).push(
                          MaterialPageRoute(builder: (_) => page())),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        child: Column(
                          children: [
                            Container(
                              width: 44,
                              height: 44,
                              decoration: BoxDecoration(
                                color: theme.colorScheme.primary
                                    .withValues(alpha: 0.10),
                                shape: BoxShape.circle,
                              ),
                              child: Icon(icon,
                                  size: 22,
                                  color: theme.colorScheme.primary),
                            ),
                            const SizedBox(height: 5),
                            Text(label,
                                style: const TextStyle(fontSize: 12)),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),
        Card(
          child: Column(children: [
            if (_marketingOn) ...[
              ListTile(
                leading: const Icon(Icons.card_giftcard_outlined),
                title: const Text('邀请有礼'),
                subtitle: const Text('好友完成首单,你俩各得券',
                    style: TextStyle(fontSize: 11)),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => InvitePage(api: widget.api))),
              ),
              const Divider(height: 1),
              ListTile(
                leading: const Icon(Icons.cake_outlined),
                title: const Text('生日与营销推送'),
                subtitle: const Text('生日当天送券;营销推送可一键关闭',
                    style: TextStyle(fontSize: 11)),
                trailing: const Icon(Icons.chevron_right),
                onTap: _editBirthdayAndPush,
              ),
              const Divider(height: 1),
            ],
            // 长辈版:大字模式,方便老人和视障用户;尊重系统字体缩放
            ValueListenableBuilder<bool>(
              valueListenable: elderMode,
              builder: (context, elder, _) => SwitchListTile(
                secondary: const Icon(Icons.text_fields),
                title: const Text('长辈版(大字模式)'),
                subtitle: const Text('放大全局字号,看得更清楚',
                    style: TextStyle(fontSize: 11)),
                value: elder,
                onChanged: (v) => setElderMode(v),
              ),
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.verified_user_outlined),
              title: const Text('实名认证'),
              subtitle: const Text('购买酒类等受限商品需先实名',
                  style: TextStyle(fontSize: 11)),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => IdentityPage(api: widget.api))),
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.receipt_outlined),
              title: const Text('开发票'),
              trailing: const Icon(Icons.chevron_right),
              onTap: _showInvoiceInfo,
            ),
            const Divider(height: 1),
            ListTile(
              leading: const Icon(Icons.support_agent_outlined),
              title: const Text('联系平台客服'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => SupportPage(api: widget.api))),
            ),
            const Divider(height: 1),
            ListTile(
              leading: Icon(Icons.logout, color: theme.colorScheme.error),
              title: Text('退出登录',
                  style: TextStyle(color: theme.colorScheme.error)),
              onTap: () {
                PushService.onLogout(); // 解绑推送别名,失败静默
                Navigator.of(context).pushAndRemoveUntil(
                    MaterialPageRoute(builder: (_) => buildUserLogin()),
                    (route) => false);
              },
            ),
          ]),
        ),
      ],
    );
  }
}

/// 我的收藏:店铺列表,点进店铺页。
class FavoritesPage extends StatelessWidget {
  const FavoritesPage({super.key, required this.api});

  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('我的收藏')),
      body: FutureBuilder(
        future: api.favorites(),
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return Center(child: Text('${snapshot.error}'));
          }
          if (!snapshot.hasData) return const SkeletonList(itemCount: 4);
          final shops = snapshot.data!;
          if (shops.isEmpty) {
            return const EmptyState(
                icon: Icons.favorite_outline,
                text: '还没有收藏的店铺\n在店铺页点❤️收藏常点的店');
          }
          return ListView.builder(
            itemCount: shops.length,
            itemBuilder: (context, i) {
              final m = shops[i];
              return ListTile(
                leading: m.logoUrl.isEmpty
                    ? const CircleAvatar(child: Icon(Icons.restaurant))
                    : CircleAvatar(
                        backgroundImage:
                            NetworkImage(api.resolveUrl(m.logoUrl))),
                title: Text(m.name),
                subtitle: Text(
                    '${m.ratingLabel}${m.isOpen ? "" : " · 休息中"}'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MenuPage(api: api, merchant: m))),
              );
            },
          );
        },
      ),
    );
  }
}

/// 「这一单的钱去哪了」—— 账目透明是 Super-Z 对抗吸血平台的武器。
/// 订单状态时间轴:已完成的步骤显示时间,当前步高亮,未来步灰色。
class _OrderTimeline extends StatelessWidget {
  const _OrderTimeline({required this.events, required this.order});

  final List<OrderEvent> events;
  final Order order;

  // 展示的关键节点(status.value -> 文案);自取单没有配送环节
  static const _steps = [
    ('paid', '已下单,等商家接单'),
    ('accepted', '商家已接单,备餐中'),
    ('ready', '出餐完成'),
    ('picked_up', '骑手已取餐,配送中'),
    ('delivered', '已送达'),
  ];
  static const _pickupSteps = [
    ('paid', '已下单,等商家接单'),
    ('accepted', '商家已接单,备餐中'),
    ('ready', '出餐完成,凭取餐码到店取餐'),
  ];

  List<(String, String)> get _mySteps => order.pickup ? _pickupSteps : _steps;

  String? _timeOf(String status) {
    for (final e in events) {
      if (e.toStatus == status) {
        final t = DateTime.tryParse(e.createdAt)?.toLocal();
        if (t == null) return null;
        String two(int n) => n.toString().padLeft(2, '0');
        return '${two(t.hour)}:${two(t.minute)}';
      }
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    // 当前进行到第几步(用订单当前状态定位)
    final currentIdx =
        _mySteps.indexWhere((s) => s.$1 == order.status.value);
    // ETA:配送中时估算送达时间
    String? etaText;
    if (!order.pickup &&
        order.merchantLat != null &&
        order.status.index < OrderStatus.delivered.index) {
      final min = etaMinutes(distanceMeters(order.merchantLat!,
          order.merchantLng!, order.lat, order.lng));
      etaText = '预计 $min 分钟内送达';
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (etaText != null) ...[
              Row(children: [
                Icon(Icons.access_time,
                    size: 18, color: theme.colorScheme.primary),
                const SizedBox(width: 6),
                Text(etaText,
                    style: TextStyle(
                        color: theme.colorScheme.primary,
                        fontWeight: FontWeight.bold)),
              ]),
              const Divider(height: 20),
            ],
            for (var i = 0; i < _mySteps.length; i++)
              _timelineRow(context, i, currentIdx),
          ],
        ),
      ),
    );
  }

  Widget _timelineRow(BuildContext context, int i, int currentIdx) {
    final theme = Theme.of(context);
    final done = currentIdx >= 0 && i <= currentIdx;
    final isCurrent = i == currentIdx;
    final time = _timeOf(_mySteps[i].$1);
    final color = done ? theme.colorScheme.primary : theme.colorScheme.outline;

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Column(
            children: [
              Icon(done ? Icons.check_circle : Icons.circle_outlined,
                  size: 18, color: color),
              if (i < _mySteps.length - 1)
                Expanded(
                  child: Container(
                    width: 2,
                    color: (currentIdx > i)
                        ? theme.colorScheme.primary
                        : theme.colorScheme.outlineVariant,
                  ),
                ),
            ],
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 14),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      _mySteps[i].$2,
                      style: TextStyle(
                        color: done
                            ? theme.colorScheme.onSurface
                            : theme.colorScheme.outline,
                        fontWeight:
                            isCurrent ? FontWeight.bold : FontWeight.normal,
                      ),
                    ),
                  ),
                  if (time != null)
                    Text(time, style: theme.textTheme.bodySmall),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 退款进度卡:逐笔退款画时间轴(受理 → 原路退回),用户不用反复问"钱呢"。
/// 钱的事用账目绿(BRAND:money 语义色)。
class _RefundProgressCard extends StatelessWidget {
  const _RefundProgressCard({required this.order, required this.refunds});

  final Order order;
  final List<RefundRecord> refunds;

  (IconData, String, Color) _statusOf(RefundRecord r, BuildContext context) {
    switch (r.status) {
      case 'success':
        return (Icons.check_circle_rounded, '已原路退回你的支付账户', kMoneyGreen);
      case 'failed':
        return (
          Icons.error_outline_rounded,
          '退款遇到问题,平台已介入处理',
          Theme.of(context).colorScheme.error
        );
      default:
        return (
          Icons.hourglass_top_rounded,
          '银行处理中,一般 1-3 个工作日到账',
          kPromoAmber
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: kMoneyGreen.withValues(alpha: .06),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.currency_yuan, size: 18, color: kMoneyGreen),
                const SizedBox(width: 8),
                Text('退款 ${yuan(order.refundCents)}',
                    style: theme.textTheme.titleSmall
                        ?.copyWith(color: kMoneyGreen)),
              ],
            ),
            if (refunds.isEmpty)
              // 流水没拉到时退回汇总文案,不留空
              Padding(
                padding: const EdgeInsets.only(top: 4, left: 26),
                child: Text('${order.refundNote},退款原路返回',
                    style: theme.textTheme.bodySmall),
              )
            else
              for (final r in refunds)
                Padding(
                  padding: const EdgeInsets.only(top: 8, left: 26),
                  child: Builder(builder: (context) {
                    final (icon, label, color) = _statusOf(r, context);
                    final day = r.createdAt.length >= 16
                        ? r.createdAt.substring(5, 16).replaceFirst('T', ' ')
                        : '';
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('${yuan(r.amountCents)} · ${r.reason}'
                            '${day.isEmpty ? '' : '($day 受理)'}',
                            style: theme.textTheme.bodySmall),
                        const SizedBox(height: 2),
                        Row(
                          children: [
                            Icon(icon, size: 15, color: color),
                            const SizedBox(width: 5),
                            Expanded(
                              child: Text(label,
                                  style: theme.textTheme.bodySmall
                                      ?.copyWith(color: color)),
                            ),
                          ],
                        ),
                      ],
                    );
                  }),
                ),
          ],
        ),
      ),
    );
  }
}

class _MoneyFlowCard extends StatelessWidget {
  const _MoneyFlowCard({required this.order});

  final Order order;

  Widget _row(BuildContext context, String who, String desc, int cents,
      {required double fraction, required Color color, VoidCallback? onInfo}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(who, style: const TextStyle(fontWeight: FontWeight.w600)),
              // 「5% 去哪了」说明入口:让质疑在产品里找到答案
              if (onInfo != null)
                GestureDetector(
                  onTap: onInfo,
                  child: Padding(
                    padding: const EdgeInsets.only(left: 3),
                    child: Icon(Icons.help_outline,
                        size: 15,
                        color: Theme.of(context).colorScheme.outline),
                  ),
                ),
              const SizedBox(width: 6),
              Expanded(
                  child: Text(desc,
                      style: Theme.of(context).textTheme.bodySmall)),
              Text(yuan(cents),
                  style: TextStyle(color: color, fontWeight: FontWeight.bold)),
            ],
          ),
          const SizedBox(height: 3),
          ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: LinearProgressIndicator(
              value: fraction,
              minHeight: 5,
              color: color,
              backgroundColor:
                  Theme.of(context).colorScheme.surfaceContainerHighest,
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final total = order.totalCents;
    final theme = Theme.of(context);
    return Card(
      color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.35),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Icon(Icons.visibility_outlined, size: 18),
              const SizedBox(width: 6),
              Text('这一单的钱去哪了',
                  style: theme.textTheme.titleSmall
                      ?.copyWith(fontWeight: FontWeight.bold)),
            ]),
            const SizedBox(height: 8),
            _row(context, '商家实收', '菜品+打包-满减,只扣 5% 服务费',
                order.merchantNetCents,
                fraction: order.merchantNetCents / total,
                color: kMoneyGreen),
            _row(
                context,
                '骑手所得',
                order.tipCents > 0 ? '配送费+小费,100% 归骑手' : '配送费 100% 归骑手',
                order.deliveryFeeCents + order.tipCents,
                fraction: (order.deliveryFeeCents + order.tipCents) / total,
                color: kMoneyGreen),
            _row(context, '平台留存', '用于服务器与平台运营',
                order.commissionCents,
                fraction: order.commissionCents / total,
                color: theme.colorScheme.primary,
                onInfo: () => showFivePercentSheet(context)),
            if (order.discountCents > 0)
              _row(context, '商家让利', '满减优惠,商家承担',
                  -order.discountCents,
                  fraction: 0, color: Colors.orange),
            if (order.subsidyCents > 0)
              _row(context, '平台补贴', '首单立减,平台承担',
                  -order.subsidyCents,
                  fraction: 0, color: Colors.pink),
            const SizedBox(height: 4),
            Text('超级赞不吸血:账目对用户、商家、骑手三方完全透明',
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.outline)),
          ],
        ),
      ),
    );
  }
}

/// 店铺页「商家」Tab:地址、营业时间、公告、平台承诺、证照标识。
class _ShopInfoTab extends StatelessWidget {
  const _ShopInfoTab({required this.api, required this.shop});

  final ApiClient api;
  final Merchant shop;

  /// 全屏看图:左右滑切换,点一下关闭
  void _openPhotoViewer(BuildContext context, int initialIndex) {
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => Scaffold(
        backgroundColor: Colors.black,
        body: GestureDetector(
          onTap: () => Navigator.of(context).pop(),
          child: PageView.builder(
            controller: PageController(initialPage: initialIndex),
            itemCount: shop.photoUrls.length,
            itemBuilder: (context, i) => InteractiveViewer(
              child: Center(
                child: Image.network(
                  api.resolveUrl(shop.photoUrls[i]),
                  fit: BoxFit.contain,
                  errorBuilder: (_, __, ___) => const Icon(
                      Icons.broken_image_outlined,
                      color: Colors.white54,
                      size: 48),
                ),
              ),
            ),
          ),
        ),
      ),
    ));
  }

  Widget _row(BuildContext context, IconData icon, String text) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: Theme.of(context).colorScheme.primary),
          const SizedBox(width: 10),
          Expanded(child: Text(text, style: const TextStyle(height: 1.4))),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hours = shop.openTime.isNotEmpty && shop.closeTime.isNotEmpty
        ? '${shop.openTime} - ${shop.closeTime}'
        : '营业中(商家手动开关)';
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Row(
          children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: shop.logoUrl.isEmpty
                  ? Container(
                      width: 64,
                      height: 64,
                      color: theme.colorScheme.surfaceContainerHighest,
                      child: Icon(Icons.restaurant,
                          color: theme.colorScheme.outline),
                    )
                  : Image.network(
                      api.resolveUrl(shop.logoUrl),
                      width: 64,
                      height: 64,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => Container(
                        width: 64,
                        height: 64,
                        color: theme.colorScheme.surfaceContainerHighest,
                        child: Icon(Icons.restaurant,
                            color: theme.colorScheme.outline),
                      ),
                    ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(shop.name, style: theme.textTheme.titleLarge),
                  Text('${shop.ratingLabel} · 月售 ${shop.monthlySales} 单',
                      style: theme.textTheme.bodySmall),
                ],
              ),
            ),
          ],
        ),
        const Divider(height: 28),
        _row(context, Icons.place_outlined, shop.address),
        _row(context, Icons.schedule, '营业时间:$hours'),
        if (shop.description.isNotEmpty)
          _row(context, Icons.storefront_outlined, shop.description),
        if (shop.announcement.isNotEmpty)
          _row(context, Icons.campaign_outlined, '公告:${shop.announcement}'),
        _row(context, Icons.verified_outlined,
            '食品经营许可证已由平台人工审核'),
        // 门店相册:商家自传的环境/后厨实拍,点开大图
        if (shop.photoUrls.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('门店实拍(${shop.photoUrls.length})',
              style: theme.textTheme.titleSmall),
          const SizedBox(height: 8),
          GridView.count(
            crossAxisCount: 3,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 6,
            crossAxisSpacing: 6,
            children: [
              for (var i = 0; i < shop.photoUrls.length; i++)
                InkWell(
                  onTap: () => _openPhotoViewer(context, i),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: Image.network(
                      api.resolveUrl(shop.photoUrls[i]),
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => Container(
                          color: theme.colorScheme.surfaceContainerHighest,
                          child: Icon(Icons.broken_image_outlined,
                              color: theme.colorScheme.outline)),
                    ),
                  ),
                ),
            ],
          ),
        ],
        const SizedBox(height: 12),
        Card(
          color: theme.colorScheme.tertiaryContainer,
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('超级赞平台承诺',
                    style: theme.textTheme.titleSmall?.copyWith(
                        color: theme.colorScheme.onTertiaryContainer,
                        fontWeight: FontWeight.bold)),
                const SizedBox(height: 6),
                Text(
                  '· 本店仅被抽成 ${(shop.commissionRate * 100).toStringAsFixed(0)}%,菜价里没有平台税\n'
                  '· 配送费 100% 归骑手\n'
                  '· 每笔订单资金流向对你完全透明',
                  style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onTertiaryContainer,
                      height: 1.7),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
