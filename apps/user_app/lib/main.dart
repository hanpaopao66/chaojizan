import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show HapticFeedback;
import 'package:geolocator/geolocator.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import 'kitchen_cam_player.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'address_pages.dart';
import 'append_order_page.dart';
import 'category_page.dart';
import 'checkout_page.dart';
import 'coupons_page.dart';
import 'group_cart_page.dart';
import 'help_page.dart';
import 'hotel_pages.dart';
import 'licenses_page.dart';
import 'messages_page.dart';
import 'mini_app_sheet.dart';
import 'mini_apps_panel.dart';
import 'money_flow_page.dart';
import 'order_filter.dart';
import 'invite_page.dart';
import 'share_card.dart';
import 'five_percent.dart';
import 'food_safety_records_page.dart';
import 'identity_page.dart';
import 'coming_soon_page.dart';
import 'feature_flags.dart';
import 'delivery_map_page.dart';
import 'errand_page.dart';
import 'payment_service.dart';
import 'reviews_page.dart';
import 'search_page.dart';
import 'session.dart';
import 'settings_page.dart';
import 'stay_order_pages.dart';
import 'transparency_page.dart';
import 'trust_page.dart';
import 'voucher_pages.dart';

// 定位失败(权限拒绝/模拟器没设位置)时的兜底坐标 demoLat/demoLng 在 session.dart

/// 一次性获取当前位置(GCJ-02),失败静默退回演示坐标。
/// 传 [context] 时,首次申请权限前先弹目的说明(商店合规:先告知后申请)。
/// 跨城提示的判据(#282)。抽成纯函数是为了能被测试锁住 ——
/// 它决定「要不要打断用户」,而打断错了比不打断更烦人。
///
/// 三个条件缺一不可:
/// - **选过收货地址**:没选的时候本来就按当前位置找店,人动了直接跟着动,
///   不需要问;
/// - **这次会话没点过「不用」**:他已经说了不换,别每次回前台再问一遍;
/// - **距离超过 30km**:同城跨区(公司→家)是最常见的正常用法,
///   在那种距离上弹提示纯属打扰。
bool shouldSuggestLocationSwitch({
  required bool hasDeliveryAddress,
  required bool dismissedThisSession,
  required double? distanceMeters,
  double thresholdMeters = 30000.0,
}) {
  if (!hasDeliveryAddress || dismissedThisSession) return false;
  if (distanceMeters == null) return false;
  return distanceMeters > thresholdMeters;
}

Future<({double lat, double lng, bool real})> resolveMyLocation(
    [BuildContext? context]) async {
  try {
    if (!await Geolocator.isLocationServiceEnabled()) throw Exception();
    var permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      if (context != null) {
        if (!context.mounted ||
            !await PermissionRationale.ensure(
                context, AppPermissionKind.location)) {
          throw Exception();
        }
      }
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
  // 可下发文案:只等本地缓存(毫秒级),不卡冷启动。
  // 网络刷新挪到同意隐私政策之后(PrivacyGate.onAgreed)——
  // 同意前发任何一个请求都算"未经同意收集",是工信部通报和商店驳回的头号事由
  await RemoteCopy.loadCached();
  runApp(const UserApp());
}

/// 「待支付」订单的统一支付入口。
///
/// 跑腿单建出来就是 pending_payment,以前下完单页面一关就再也找不到付款的地方,
/// 15 分钟后被 auto_flow 当成僵尸单清掉 —— 用户白填一遍地址,平台一分钱收不到。
/// 支付中断(切后台、微信没装、网断)留下的单同样要能从列表回到这里。
///
/// 付成了返回新订单,没付成返回 null。注意 [payOrder] 支付不成时**不抛异常**,
/// 而是原样返回状态仍为 pending_payment 的订单(它自己已经把原因提示给用户了),
/// 所以这里要看状态,不能"拿到东西就当成功"。
Future<Order?> payPendingOrder(
    ApiClient api, Order order, BuildContext context) async {
  try {
    final result = await payOrder(api, order, context);
    return result.status == OrderStatus.pendingPayment ? null : result;
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e is ApiException ? e.message : '$e'),
          duration: const Duration(seconds: 5)));
    }
    return null;
  }
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
/// 用户端是「逛」的姿势:躺着刷,信息可以密一点(#134)
ThemeData superZTheme(Brightness brightness) =>
    brandTheme(brightness, density: SzDensity.browse);

class UserApp extends StatelessWidget {
  const UserApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<bool>(
      valueListenable: elderMode,
      builder: (context, elder, _) => MaterialApp(
        title: '超级赞 · 点外卖',
        // 深浅两套令牌都在 brand.dart 里定义(第八辑 #101),
        // #111 三端逐屏走查通过后放开跟随系统
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
        // 隐私门必须在最外层:开屏页会请求 /splash 并下载开屏图,
        // 套在里面的话首次启动"同意"之前就已经联网了
        home: PrivacyGate(
            onAgreed: () async {
              // 同意之后才初始化收集类 SDK。地图 SDK 尤其不能提前:
              // 腾讯的接口是"同意前调用则地图显示为空白",
              // 而且失败是静默的 —— 没异常没日志,只有一块白板
              await PushService.init();
              await agreeAndStart();
              unawaited(RemoteCopy.refresh(rootApi));
            },
            child: SplashGate(
                app: 'user',
                tagline: '点外卖,每一单分账可查',
                subLines: const [
                  '5% 佣金封顶,账本向所有人公开',
                  '配送费一分不截留,全部归骑手',
                  '让利于民 · 取之有道 · 账目为证',
                ],
                child: AuthGate(
                    api: rootApi,
                    title: '用户端 · 点外卖',
                    role: 'customer',
                    // 游客模式(苹果审核要求):未登录直接进首页浏览,
                    // 下单/收藏/我的等动作触发时再引导登录
                    allowGuest: true,
                    homeBuilder: (_, api) => HomePage(api: api)))),
      ),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.api});

  final ApiClient api;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _tab = 0;

  /// 已经访问过的 tab。IndexedStack 保活的前提是别一上来就把三个都建起来
  final Set<int> _visited = {0};

  /// 顶部地址栏选中的收货地址;null = 用当前定位
  Address? _deliveryAddress;

  /// 当前定位落在哪个区(#284)。`_deliveryAddress` 为空时顶部显示它。
  ///
  /// 原来那里固定写「当前位置」四个字 —— 用户没法判断 App 到底定到哪了,
  /// 而这正是「换了城市要不要提示他」那条(#282)的前提:
  /// 连 App 认为自己在哪都不知道,就不会去点那个切换。
  String _hereName = '';

  /// 定位失败(权限关了/取不到)。顶部要说出来,不能继续假装「当前位置」
  bool _hereFailed = false;

  /// 消息中心红点(有新公告)
  bool _hasUnread = false;

  /// 从「我的」页的订单四格跳过来时,订单 tab 要落在哪个筛选、哪个频道上。
  ///
  /// **切 tab 而不是 push 新页** —— push 的话会多出第二个订单列表,
  /// 返回行为和底部 tab 不一致,用户点两次「订单」看到的是两个地方
  OrderFilter _ordersFilter = OrderFilter.all;
  int _ordersSegment = 0;

  void _openOrders(OrderFilter filter, {int segment = 0}) {
    setState(() {
      _ordersFilter = filter;
      _ordersSegment = segment;
      _tab = 1;
      _visited.add(1);
    });
  }

  @override
  void initState() {
    super.initState();
    Analytics.instance.init(widget.api);
    WidgetsBinding.instance.addPostFrameCallback((_) =>
        checkForUpdate(context, baseUrl: widget.api.baseUrl, app: 'user'));
    MessageCenterPage.hasUnread(widget.api).then((v) {
      if (mounted && v) setState(() => _hasUnread = true);
    });
  }

  Future<void> _pickDeliveryAddress() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    final picked = await Navigator.of(context).push<Address>(MaterialPageRoute(
        builder: (_) => AddressBookPage(api: widget.api, selectMode: true)));
    if (picked != null && mounted) {
      setState(() => _deliveryAddress = picked);
    }
  }

  @override
  Widget build(BuildContext context) {
    // 宽屏(≥600)自动换成左侧栏(#295)。底部导航是为**拇指**设计的 ——
    // 桌面上鼠标的"家"在内容附近,把导航钉在 1440px 屏的最底部,
    // 每次切页都要横跨半个屏幕跑一趟。侧栏还顺带省下 80px 竖向空间,
    // 而桌面浏览器的可视高度本来就比手机紧张(地址栏、标签栏都在吃)
    return SzNavScaffold(
      selectedIndex: _tab,
      // 宽度上限交给外壳,标题栏和内容才会用**同一个**宽度对齐。
      // 自己在 body 上套 SzContentWidth 的话,标题栏还是横跨全屏:
      // 标题贴最左、图标钉最右,而下面的内容是居中的。
      //
      // 三个 tab 不同宽,因为**内容形态不同**:首页是卡片流(可以宽一点),
      // 订单和「我的」是单列(要短行才好读)。统一限死会把卡片流也压成 720
      contentMaxWidth: _tab == 0 ? kFeedMaxWidth : kContentMaxWidth,
      onSelected: (i) => setState(() {
        _tab = i;
        _visited.add(i);
      }),
      items: const [
        SzNavItem(
            icon: Icons.storefront_outlined,
            selectedIcon: Icons.storefront,
            label: '首页'),
        SzNavItem(
            icon: Icons.receipt_long_outlined,
            selectedIcon: Icons.receipt_long,
            label: '订单'),
        SzNavItem(
            icon: Icons.person_outline,
            selectedIcon: Icons.person,
            label: '我的'),
      ],
      appBar: AppBar(
        title: _tab == 0
            // 商业平台标配:顶部地址栏,让用户知道「附近」是哪儿附近。
            // 地址与送达时间同行——打开外卖 App 第一秒只关心这两件事。
            ? InkWell(
                onTap: _pickDeliveryAddress,
                borderRadius: BorderRadius.circular(kRadiusSm),
                child: Row(
                  // 不能是 min:那样 Flexible 拿不到可用宽度,
                  // 地址还是会在老位置被截断
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    // 地址要尽量看全。原来是 17px + 写死 maxWidth 178 ——
                    // 「雁塔区T11 BLOCK(西安国际...)」这类真实地名在 390 屏上
                    // 只露得出前八九个字,剩下全是省略号,而**后半截才是**
                    // 用来分辨"是不是我家"的那部分(楼名、单元)。
                    //
                    // 字号降到 14.5,宽度改成吃掉剩余空间(Flexible)而不是
                    // 写死一个数 —— 写死的那个 178 是按 17px 定的,
                    // 字缩了它也不会跟着放宽,等于白缩。
                    Flexible(
                      child: Text(
                        _deliveryAddress?.address ??
                            (_hereFailed
                                ? '定位失败,点这里选地址'
                                : (_hereName.isEmpty ? '当前位置' : _hereName)),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 14.5,
                            fontWeight: FontWeight.w600,
                            letterSpacing: -0.2),
                      ),
                    ),
                    const SizedBox(width: 5),
                    Text('▾',
                        style: TextStyle(
                            fontSize: 11,
                            color: Theme.of(context).sz.inkMuted)),
                  ],
                ),
              )
            : Text(_tab == 1 ? '我的订单' : '我的'),
        actions: [
          // 消息中心:公告 + 订单通知,有新公告带红点
          IconButton(
            tooltip: '消息中心',
            icon: Badge(
              isLabelVisible: _hasUnread,
              smallSize: 8,
              child: const Icon(Icons.notifications_outlined),
            ),
            onPressed: () async {
              setState(() => _hasUnread = false); // 打开即已读
              await Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => MessageCenterPage(api: widget.api)));
            },
          ),
          // 「我的」tab 上换成客服 + 设置。
          //
          // 这两样一个是「随时可能要」、一个是「一年点几次的目录页」,
          // 都不该按位置在正文里排优先级 —— 提到右上角之后,正文列表
          // 少两行(63 + 46 = 109px),它们反而更好找。
          //
          // 收货地址在「我的」页的卡券网格里有一份,这里让位不丢入口;
          // 首页/订单 tab 保持原样(那两个 tab 的地址是下单上下文)
          if (_tab == 2) ...[
            IconButton(
              icon: const Icon(Icons.support_agent_outlined),
              tooltip: '联系平台客服',
              onPressed: () async {
                if (!await ensureLoggedIn(context)) return;
                if (!context.mounted) return;
                await Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => SupportPage(api: widget.api)));
              },
            ),
            IconButton(
              icon: const Icon(Icons.settings_outlined),
              tooltip: '设置',
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => SettingsPage(api: widget.api))),
            ),
          ] else
            // 搜索是主页第一交互,已做成显眼的大搜索框(点餐页顶部),
            // 这里只保留地址簿入口,避免图标堆积
            IconButton(
              icon: const Icon(Icons.place_outlined),
              tooltip: '收货地址',
              onPressed: () async {
                if (!await ensureLoggedIn(context)) return;
                if (!context.mounted) return;
                await Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => AddressBookPage(api: widget.api)));
              },
            ),
        ],
      ),
      // 底部 tab 只放功能(首页/订单/我的),业务一律走金刚区——
      // 业务会持续增加(团购/住宿/打车…),金刚区横向扩展,tab 保持稳定。
      //
      // 用 IndexedStack 保活,不再用 AnimatedSwitcher:后者三个 tab 各带一个 key,
      // 切走即销毁,从「订单」切回「首页」要重新定位 + 重拉商家列表,
      // 用户等一遍、手机费一遍电。代价是没有了那 160ms 的淡入 —— 值。
      // 但只建访问过的 tab:IndexedStack 会一次性 build 全部子树,
      // 冷启动就把订单和「我的」的请求也打出去,那是另一种浪费
      body: IndexedStack(
        index: _tab,
        children: [
          _visited.contains(0)
              ? MerchantListView(
                  api: widget.api,
                  deliveryAddress: _deliveryAddress,
                  onLocated: (name, failed) {
                    if (!mounted) return;
                    if (name == _hereName && failed == _hereFailed) return;
                    setState(() {
                      _hereName = name;
                      _hereFailed = failed;
                    });
                  },
                  onUseCurrentLocation: () {
                    // 清掉收货地址 = 回到「按当前位置找店」。
                    // 地址本身一条没删,他随时能再选回来
                    setState(() => _deliveryAddress = null);
                  })
              : const SizedBox.shrink(),
          _visited.contains(1)
              ? OrdersTab(
                  api: widget.api,
                  filter: _ordersFilter,
                  segment: _ordersSegment)
              : const SizedBox.shrink(),
          _visited.contains(2)
              ? ProfileView(api: widget.api, onOpenOrders: _openOrders)
              : const SizedBox.shrink(),
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
      {super.key,
      required this.api,
      this.deliveryAddress,
      this.category,
      this.onLocated,
      this.onUseCurrentLocation});

  final ApiClient api;

  /// 顶部地址栏选中的地址;null = 用手机定位
  final Address? deliveryAddress;

  /// 定位有结果时回报给首页:区名(拿不到就空串)+ 是否失败(#284)。
  /// 顶部地址栏靠它把「当前位置」换成真实地名
  final void Function(String hereName, bool failed)? onLocated;

  /// 用户在跨城提示条上点了「切到当前位置」(#282)——
  /// 清掉收货地址这件事只有首页做得了,列表页只负责报告
  final VoidCallback? onUseCurrentLocation;

  /// 品类模式(外卖二级页):null = 首页模式(搜索栏+金刚区+再来一单);
  /// '' = 推荐(不过滤,不带首页头部);slug = 按品类过滤
  final String? category;

  @override
  State<MerchantListView> createState() => _MerchantListViewState();
}

class _MerchantListViewState extends State<MerchantListView>
    with WidgetsBindingObserver {
  bool _realLocation = true;

  /// 上一次真实定位到的坐标(#282 判断「是不是换城市了」用的基准)。
  /// 注意它和 `_myLat/_myLng` 不是一回事:后者是**正在用来找店的**位置,
  /// 选了收货地址时那是地址的坐标,而这个始终是人所在的位置
  double? _hereLat;
  double? _hereLng;

  /// 跨城提示条要显示的当前城市名;空 = 还没拿到(不影响提示,见 #282)
  String _farCity = '';

  /// 用户在这次会话里点过「不用」。**存内存不落盘** ——
  /// 重启 App 重新判断,他下次打开时人可能真的在新城市待下来了
  bool _farDismissed = false;

  /// 刚选过地址,在人移动之前不提示(见 didUpdateWidget 的注释)
  bool _suppressFarUntilMove = false;

  /// 选地址那一刻人在哪。人从这里挪开够远了,才认为「他自己跑远了」,
  /// 提示条才有意义
  ({double lat, double lng})? _hereAtPick;

  /// 上次为「是不是换城市了」取定位的时刻。resumed 会因为切通知栏、
  /// 接电话反复触发,不压一下会变成每分钟几次定位
  DateTime? _lastHereCheck;

  /// 用户在「定位没拿到」时手选的城市(#283)。空 = 没选过
  String _pickedCity = '';

  /// 跨城判据:30km。同城跨区(公司→家)不该提示 —— 那是最常见的正常用法
  static const _kFarMeters = 30000.0;

  /// 两次位置复核的最小间隔
  static const _kHereCheckGap = Duration(minutes: 5);

  /// 曝光去重交给 Analytics 的会话级 once(退出登录会清)——
  /// 用页面内的 static Set 的话,换账号后新账号的曝光永远不再上报
  void _trackImpression(int merchantId) {
    Analytics.trackOnce('impression_shop:$merchantId', 'impression_shop',
        {'merchant_id': merchantId});
  }

  /// 定位正常但该区域无商家:已降级展示演示城市数据(审核兜底)
  bool _fellBack = false;
  double _myLat = demoLat;
  double _myLng = demoLng;
  String _sort = 'distance';

  // 筛选:与搜索页同一套条件。null / false = 不限
  int? _radiusM;
  double? _minRating;
  bool _hasPromo = false;
  int? _maxMinOrderCents;

  int get _filterCount => [
        _radiusM != null,
        _minRating != null,
        _hasPromo,
        _maxMinOrderCents != null,
      ].where((on) => on).length;

  late Future<List<Merchant>> _future = _load();

  /// 再来一单:最近点过的店(按商家去重,最多 6 家)
  List<Order> _reorder = [];

  /// 我的常点:近 90 天点得最多的单品(#119)
  List<FrequentDish> _frequent = [];

  /// 5% 承诺条关掉了没有。
  ///
  /// **默认不关**,但关了就永久关 —— 它是一句宣言,老用户看过一次就够了,
  /// 天天顶在首页上是打扰。想再看的话「我的 → 钱去哪了」一直在那儿,
  /// 这条只是入口不是唯一入口。
  bool _pledgeHidden = false;

  static const _kPledgeHidden = 'home_pledge_hidden';

  /// 小程序清单(#278):空(含游客 401)时下拉手势整个不生效 ——
  /// 没有内容的抽屉比没有抽屉更糟
  List<MiniAppInfo> _miniApps = const [];

  /// 列表到顶后继续下拉的累计拉距;>0 时顶部预览条露头
  double _miniPull = 0;
  bool _miniArmed = false;
  bool _miniOpening = false;

  @override
  void initState() {
    super.initState();
    // 首页要跟随位置(#281):App 从后台回来时人可能已经换了城市。
    // 全 App 此前只有订单详情/地图/拼单页监听生命周期,首页反而没有
    if (widget.category == null) WidgetsBinding.instance.addObserver(this);
    _loadRecent();
    _restorePledge();
    _loadMiniApps();
  }

  @override
  void dispose() {
    if (widget.category == null) WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _recheckHere();
  }

  /// 回到前台时复核「人还在原来那片吗」(#281/#282)。
  ///
  /// **只取定位,不重拉列表** —— 拉不拉由跨城判断说了算。
  /// 用 `getLastKnownPosition` 优先:我们只要判断是不是换了城市,
  /// 不需要为此唤醒 GPS;拿不到才退回一次低精度定位。
  Future<void> _recheckHere() async {
    if (!mounted || widget.category != null) return;
    final now = DateTime.now();
    if (_lastHereCheck != null &&
        now.difference(_lastHereCheck!) < _kHereCheckGap) {
      return; // 切个通知栏、接个电话都会触发 resumed,不压会变成每分钟几次定位
    }
    _lastHereCheck = now;
    try {
      var p = await Geolocator.getLastKnownPosition();
      p ??= await Geolocator.getCurrentPosition(
          locationSettings: const LocationSettings(
              accuracy: LocationAccuracy.low, timeLimit: Duration(seconds: 6)));
      final gcj = wgs84ToGcj02(p.latitude, p.longitude);
      if (!mounted) return;
      // 人从「选地址那一刻所在的位置」挪开够远了 —— 现在提示才说得通
      if (_suppressFarUntilMove && _hereAtPick != null) {
        final moved = Geolocator.distanceBetween(
            _hereAtPick!.lat, _hereAtPick!.lng, gcj.lat, gcj.lng);
        if (moved > _kFarMeters) _suppressFarUntilMove = false;
      }
      _hereLat = gcj.lat;
      _hereLng = gcj.lng;
      // 没选收货地址时,人动了就直接跟着动 —— 这本来就是「按当前位置找店」,
      // 不需要问他(要问的是"你选了别处的地址"那种,见下面 _farFromHere)
      if (widget.deliveryAddress == null &&
          Geolocator.distanceBetween(_myLat, _myLng, gcj.lat, gcj.lng) >
              _kFarMeters) {
        setState(() => _future = _load());
        return;
      }
      if (_farFromHere) setState(() {}); // 让提示条出现
      _resolveHereName();
    } catch (_) {
      // 复核失败不打扰:上一次的位置继续用,提示条也不出
    }
  }

  /// 正在用来找店的位置,和人所在的位置差得够远吗(#282)。
  ///
  /// 用直线距离不用城市名:城市名要多一次逆地理,而且直辖市/省直管县的
  /// 口径很乱(「北京市」vs「北京」vs「东城区」),拿它当判据会误报。
  bool get _farFromHere => shouldSuggestLocationSwitch(
        hasDeliveryAddress: widget.deliveryAddress != null,
        dismissedThisSession: _farDismissed || _suppressFarUntilMove,
        distanceMeters: _hereLat == null
            ? null
            : Geolocator.distanceBetween(
                _myLat, _myLng, _hereLat!, _hereLng!),
        thresholdMeters: _kFarMeters,
      );

  /// 拿当前定位的区名,给顶部地址栏(#284)和跨城提示条用。
  /// **拿不到不影响任何判断** —— 提示条会退化成不带地名的说法
  Future<void> _resolveHereName() async {
    final lat = _hereLat, lng = _hereLng;
    if (lat == null || lng == null) return;
    try {
      final poi = await widget.api.geoReverse(lat, lng);
      if (!mounted) return;
      // **要 name 不要 district**:name 是腾讯的「推荐地址」
      // (「紫薇臻品」「XX 大厦」),district 是完整行政区划串
      // (「陕西省西安市雁塔区XX路」)。服务端 geo.py 那里特意开了 get_poi=1,
      // 注释写着「纯行政区划当收货地址没用,得给出骑手找得到的参照物」——
      // 顶部要显示的是同一种东西:用户一眼认得出「这是我家楼下」
      final name = poi.name.isNotEmpty ? poi.name : poi.district;
      _farCity = name;
      widget.onLocated?.call(name, false);
      if (_farFromHere) setState(() {});
    } catch (_) {
      // 逆地理失败:顶部保持「当前位置」,提示条用不带地名的文案
    }
  }


  Future<void> _loadMiniApps() async {
    if (widget.category != null) return; // 面板只属于首页,品类页不呼出
    // 桌面端没有小程序容器(WebView 插件不支持桌面,桌面也没有 iframe)。
    // **连清单都不拉** —— 拉回来只会渲染出一排点不开的入口。
    // web 现在能用了(iframe + postMessage,见 mini_app_host_web.dart)
    if (!miniAppSupported) return;
    try {
      final apps = await widget.api.miniApps();
      if (mounted) setState(() => _miniApps = apps);
    } catch (_) {
      // 游客/网络失败:按没有小程序处理,静默
    }
  }

  /// 与 RefreshIndicator 的共存口径(#278 的验收重点):不抢、不禁用。
  /// 浅拉松手 → 刷新,和从前一样;深拉过 kMiniAppsPullThreshold 松手 →
  /// 面板展开(此时刷新也会触发,列表在面板底下顺手更新了,无害)。
  /// Android 默认 clamping 没有 overscroll 位移,用 OverscrollNotification
  /// 累计拉距;iOS bouncing 用负 pixels —— 两平台靠同一个阈值对齐手感
  bool _onScrollForMiniApps(ScrollNotification n) {
    if (widget.category != null || _miniApps.isEmpty) return false;
    double? pull;
    if (n is OverscrollNotification &&
        n.dragDetails != null &&
        n.overscroll < 0 &&
        n.metrics.extentBefore <= 0) {
      pull = _miniPull - n.overscroll;
    } else if (n is ScrollUpdateNotification &&
        n.dragDetails != null &&
        n.metrics.pixels < 0) {
      pull = -n.metrics.pixels;
    }
    if (pull != null) {
      final p = pull;
      final armed = p >= kMiniAppsPullThreshold;
      if (armed && !_miniArmed) HapticFeedback.mediumImpact();
      setState(() {
        _miniPull = p;
        _miniArmed = armed;
      });
      return false;
    }
    final released = n is ScrollEndNotification ||
        (n is ScrollUpdateNotification && n.dragDetails == null);
    if (released && _miniPull > 0) {
      final open = _miniArmed && !_miniOpening;
      setState(() {
        _miniPull = 0;
        _miniArmed = false;
      });
      if (open) {
        _miniOpening = true;
        showMiniAppsPanel(context, api: widget.api, apps: _miniApps)
            .whenComplete(() => _miniOpening = false);
      }
    }
    return false;
  }

  Future<void> _restorePledge() async {
    final sp = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() => _pledgeHidden = sp.getBool(_kPledgeHidden) ?? false);
  }

  Future<void> _hidePledge() async {
    setState(() => _pledgeHidden = true);
    final sp = await SharedPreferences.getInstance();
    await sp.setBool(_kPledgeHidden, true);
    if (!mounted) return;
    // 说清楚去哪还能看到 —— 不说的话用户以为这个入口没了
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      content: Text('已收起。想看分账明细,「我的 → 这钱怎么算的」一直在'),
      duration: Duration(seconds: 4),
    ));
  }

  Future<void> _loadRecent() async {
    // 两块首页数据并发拉:互不依赖,串起来发就是白等一个来回。
    // 各自兜底,一个挂了不影响另一个
    final ordersF = widget.api.myOrders();
    final frequentF = widget.api.myFrequentDishes();
    try {
      final orders = await ordersF;
      final seen = <int>{};
      final recent = <Order>[];
      for (final o in orders) {
        if (o.status != OrderStatus.completed &&
            o.status != OrderStatus.delivered) {
          continue;
        }
        // 跑腿单不进「再来一单」。它的 merchantId 指向「本城跑腿服务」
        // 那个虚拟主体,点进去是一张空菜单 —— 而且"再来一单"对跑腿
        // 本来就不成立:上次寄的东西和这次要寄的没有任何关系
        if (o.isErrand) continue;
        if (seen.add(o.merchantId)) recent.add(o);
        if (recent.length >= 6) break;
      }
      if (mounted) setState(() => _reorder = recent);
    } catch (_) {}
    try {
      final frequent = await frequentF;
      if (mounted) setState(() => _frequent = frequent);
    } catch (_) {}
  }

  /// 常点单品进店:直接把这道菜预填进购物车,不用再翻菜单
  Future<void> _openFrequent(FrequentDish f) async {
    if (!f.merchantOpen) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${f.merchantName} 现在没营业')));
      return;
    }
    try {
      final merchant = await widget.api.merchantDetail(f.merchantId);
      if (!mounted) return;
      Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => MenuPage(
              api: widget.api,
              merchant: merchant,
              initialCart: {f.dishId: 1})));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
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
      // 他刚**主动**选了一个地址 —— 那是明确的意图表达,别扭头就问
      // 「你人不在那儿,要切回来吗」。在西安选北京的地址给朋友点单,
      // 是完全正常的用法(选存的地址把配送点挪过去、点那边的店,
      // 本来就是这个功能存在的理由)。
      //
      // 提示条要管的是**另一件事**:他没重新选地址,而人自己跑远了。
      // 所以这里先压住,等 _recheckHere() 发现人真的移动了再放开
      _suppressFarUntilMove = true;
      _hereAtPick = (_hereLat == null || _hereLng == null)
          ? null
          : (lat: _hereLat!, lng: _hereLng!);
      setState(() => _future = _load());
    }
  }

  /// 第二页起追加的商家。服务端一页 50 家,真实城市不止 50 家 ——
  /// 老口径没有分页,第 51 家起用户永远看不到,而那条「排序只按你选的口径」
  /// 的承诺在被截断的列表上是不成立的
  final List<Merchant> _more = [];
  bool _loadingMore = false;
  bool _noMore = false;
  static const _pageSize = 50; // 与服务端 merchants.py 的 _PAGE_MAX 一致

  /// 触底加载下一页。失败就停,不反复重试打服务器;用户下拉刷新可以重来
  Future<void> _loadMore(int loaded) async {
    if (_loadingMore || _noMore) return;
    _loadingMore = true;
    try {
      final next = await widget.api.merchants(
          lat: _myLat, lng: _myLng, sort: _sort, category: widget.category,
          radiusM: _radiusM, minRating: _minRating, hasPromo: _hasPromo,
          maxMinOrderCents: _maxMinOrderCents, offset: loaded);
      if (!mounted) return;
      setState(() {
        _more.addAll(next);
        _noMore = next.length < _pageSize;
      });
    } catch (_) {
      _noMore = true;
    } finally {
      _loadingMore = false;
    }
  }

  Future<List<Merchant>> _load() async {
    // 换排序/换筛选/下拉刷新都会走这里,分页状态跟着从头来
    _more.clear();
    _loadingMore = false;
    _noMore = false;
    final address = widget.deliveryAddress;
    if (address != null) {
      _realLocation = true; // 用户手选地址,视为精确
      _myLat = address.lat;
      _myLng = address.lng;
    } else {
      final location = mounted ? await resolveMyLocation(context) : await resolveMyLocation();
      _realLocation = location.real; // FutureBuilder 完成时会重建,无需 setState
      _myLat = location.lat;
      _myLng = location.lng;
      if (location.real) {
        // 人所在的位置,和「用来找店的位置」分开记(#282):
        // 选了收货地址时后者是地址的坐标,而这个始终是人在哪
        _hereLat = location.lat;
        _hereLng = location.lng;
        _lastHereCheck = DateTime.now();
        _resolveHereName();
      } else {
        widget.onLocated?.call('', true); // 顶部要说「定位失败」,不装作有位置
      }
    }
    _fellBack = false;
    var list = await widget.api.merchants(
        lat: _myLat, lng: _myLng, sort: _sort, category: widget.category,
        radiusM: _radiusM, minRating: _minRating, hasPromo: _hasPromo,
        maxMinOrderCents: _maxMinOrderCents);
    // 审核兜底:定位正常但离已开通城市远(如审核人员在外地/海外)时列表为空,
    // 降级展示演示城市商家——数据链路与真实用户一致,可浏览可下单
    if (list.isEmpty && _realLocation && address == null) {
      final demo = await widget.api.merchants(
          lat: demoLat, lng: demoLng, sort: _sort, category: widget.category,
          radiusM: _radiusM, minRating: _minRating, hasPromo: _hasPromo,
          maxMinOrderCents: _maxMinOrderCents);
      if (demo.isNotEmpty) {
        _fellBack = true;
        _myLat = demoLat;
        _myLng = demoLng;
        list = demo;
      }
    }
    return list;
  }

  /// 跨城提示条(#282):**非阻断,不是弹窗**。
  ///
  /// 判据在 `_farFromHere`。这里只负责说清楚三件事:你在哪、现在按哪找店、
  /// 要不要换 —— 然后**等他点**。
  ///
  /// ⚠️ 绝不自动切:人在北京出差、给西安家里老人点单是最常见的场景之一。
  /// App 因为「你人在北京」把地址偷偷改掉,他不看第二眼就会把饭点到
  /// 自己出差的酒店。静默改比不改更糟。
  Widget _farBanner() {
    final sz = Theme.of(context).sz;
    final to = widget.deliveryAddress?.address ?? '';
    final short = to.length > 12 ? '${to.substring(0, 12)}…' : to;
    return Container(
      margin: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 0),
      padding: const EdgeInsets.fromLTRB(12, 10, 8, 10),
      decoration: BoxDecoration(
        color: sz.claySoft,
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      child: Row(children: [
        Icon(Icons.my_location, size: 18, color: sz.clay),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            _farCity.isEmpty
                ? '你现在好像不在「$short」附近,正在按这个地址找店'
                : '你现在好像在$_farCity附近,正在按「$short」找店',
            style: TextStyle(fontSize: 12.5, height: 1.4, color: sz.ink),
          ),
        ),
        TextButton(
          onPressed: () {
            widget.onUseCurrentLocation?.call();
          },
          child: const Text('切到当前位置'),
        ),
        // 「不用」只记在内存里:重启 App 重新判断 —— 他下次打开时
        // 人可能真的在新城市待下来了
        IconButton(
          tooltip: '不用',
          icon: const Icon(Icons.close, size: 18),
          onPressed: () => setState(() => _farDismissed = true),
        ),
      ]),
    );
  }

  /// 按指定坐标找店。手选城市(#283)走它 —— 不再碰定位,
  /// 也不走 `_load()` 里那条「空了就降级演示城市」的兜底:
  /// 他明确选了城市,那个城市没店就该照实说没店
  Future<List<Merchant>> _loadAt(double lat, double lng) async {
    _more.clear();
    _loadingMore = false;
    _noMore = false;
    return widget.api.merchants(
        lat: lat, lng: lng, sort: _sort, category: widget.category,
        radiusM: _radiusM, minRating: _minRating, hasPromo: _hasPromo,
        maxMinOrderCents: _maxMinOrderCents);
  }

  /// 手选城市之后按该城市找店(#283)。
  ///
  /// city → 坐标走服务端的 POI 搜索(`geoTips` 用城市名限定区域),
  /// 取第一条的坐标当城市中心 —— 不在客户端塞一张城市坐标表:
  /// 那张表迟早和服务端的开城清单对不上,而且新开一个城市就要发一次版。
  Future<void> _useCity(String city) async {
    if (city.isEmpty) return;
    await CityPref.save(city);
    if (!mounted) return;
    setState(() => _pickedCity = city);
    try {
      final tips = await widget.api.geoTips(city, city: city);
      if (tips.isEmpty || !mounted) return;
      setState(() {
        _realLocation = true; // 他自己选的,不再是「没定位」那种状态
        _fellBack = false;
        _myLat = tips.first.lat;
        _myLng = tips.first.lng;
        _future = _loadAt(tips.first.lat, tips.first.lng);
      });
    } catch (_) {
      if (mounted) _snackCityFailed();
    }
  }

  void _snackCityFailed() {
    ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('这个城市暂时查不到位置,换一个试试')));
  }

  /// 空品类招商位:该品类还没有商家,把空状态变成入驻引导
  Widget _categoryVacancy() {
    return Padding(
      padding: const EdgeInsets.only(top: 28),
      child: SzEmpty(
        art: BrandArt.bowl,
        text: RemoteCopy.text('home.category_vacancy',
            '该品类商家入驻中\n总负担 5% 封顶 · 入驻免费 · 没有竞价排名'),
        actionLabel: '我有店,去入驻',
        onAction: () => launchUrl(
            Uri.parse('${widget.api.baseUrl}/join/merchant'),
            mode: LaunchMode.externalApplication),
      ),
    );
  }

  /// 排序:选中态墨色实底,比描边笃定。「离我近」就是按距离排,
  /// 别叫「综合」——叫综合就等于给暗箱排序留了口子。
  Widget _sortChips() {
    const options = [
      ('distance', '离我近'),
      ('rating', '评分优先'),
      ('sales', '月售优先'),
    ];
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 6),
      child: Row(
        children: [
          for (final (value, label) in options)
            Padding(
              padding: const EdgeInsets.only(right: 7),
              child: SzChip(
                label,
                selected: _sort == value,
                onTap: () => setState(() {
                  _sort = value;
                  _future = _load();
                }),
              ),
            ),
          const Spacer(),
          // 筛选与排序分开:排序改的是次序,筛选改的是集合。
          // 选中数直接写在标签上,用户不用点开也知道自己筛过什么
          SzChip(
            _filterCount == 0 ? '筛选' : '筛选 · $_filterCount',
            selected: _filterCount > 0,
            onTap: _openFilterSheet,
          ),
        ],
      ),
    );
  }

  /// 筛选面板。条件与搜索页一致,改完点「看结果」才发请求 ——
  /// 逐项即时重查会让用户在四个条件之间来回等
  Future<void> _openFilterSheet() async {
    var radius = _radiusM;
    var rating = _minRating;
    var promo = _hasPromo;
    var minOrder = _maxMinOrderCents;

    final applied = await szShowSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) {
          final sz = Theme.of(sheetContext).sz;
          Widget group<T>(String title, T? current, List<(T?, String)> options,
              void Function(T?) onPick) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SzSectionTitle(title),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final (value, label) in options)
                      SzChip(label,
                          selected: current == value,
                          onTap: () => setSheet(() => onPick(value))),
                  ],
                ),
                const SizedBox(height: 18),
              ],
            );
          }

          return SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(kPagePad),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  group<int>('配送距离', radius, const [
                    (null, '不限'),
                    (1000, '1km 内'),
                    (2000, '2km 内'),
                    (3000, '3km 内'),
                  ], (v) => radius = v),
                  group<double>('评分', rating, const [
                    (null, '不限'),
                    (4.0, '4.0 分以上'),
                    (4.5, '4.5 分以上'),
                  ], (v) => rating = v),
                  group<int>('起送价', minOrder, const [
                    (null, '不限'),
                    (1500, '¥15 以内'),
                    (2000, '¥20 以内'),
                    (3000, '¥30 以内'),
                  ], (v) => minOrder = v),
                  const SzSectionTitle('优惠'),
                  const SizedBox(height: 8),
                  SzChip('只看有优惠的',
                      selected: promo,
                      onTap: () => setSheet(() => promo = !promo)),
                  const SizedBox(height: 6),
                  Text('优惠是商家自己出的满减满赠,平台不出补贴也不摊派',
                      style: Theme.of(sheetContext)
                          .textTheme
                          .bodySmall
                          ?.copyWith(color: sz.inkMuted)),
                  const SizedBox(height: 20),
                  Row(children: [
                    TextButton(
                      onPressed: () => setSheet(() {
                        radius = null;
                        rating = null;
                        promo = false;
                        minOrder = null;
                      }),
                      child: const Text('清空'),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: FilledButton(
                        onPressed: () => Navigator.of(sheetContext).pop(true),
                        child: const Text('看结果'),
                      ),
                    ),
                  ]),
                ],
              ),
            ),
          );
        },
      ),
    );

    if (applied != true || !mounted) return;
    setState(() {
      _radiusM = radius;
      _minRating = rating;
      _hasPromo = promo;
      _maxMinOrderCents = minOrder;
      _future = _load();
    });
  }

  /// 筛完一家不剩:别丢一个干巴巴的空状态给用户,给一键清空的出口
  Widget _filteredEmpty() => Padding(
        padding: const EdgeInsets.only(top: 28),
        child: SzEmpty(
          art: BrandArt.bowl,
          text: '当前筛选条件下附近没有商家',
          actionLabel: '清空筛选',
          onAction: () => setState(() {
            _radiusM = null;
            _minRating = null;
            _hasPromo = false;
            _maxMinOrderCents = null;
            _future = _load();
          }),
        ),
      );

  /// 大搜索框:商业外卖首页的第一交互,直接可见可点(不藏在图标里)。
  /// 不放口号横幅——信任靠订单里可查的账单传达,不靠喊。
  Widget _searchBar() {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 0),
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) =>
                SearchPage(api: widget.api, lat: _myLat, lng: _myLng))),
        child: Container(
          height: 42,
          padding: const EdgeInsets.symmetric(horizontal: 16),
          decoration: BoxDecoration(
            color: sz.surface,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: sz.line),
          ),
          child: Row(
            children: [
              Icon(Icons.search, color: sz.inkFaint, size: 19),
              const SizedBox(width: 8),
              Text('搜店铺、搜菜名',
                  style: TextStyle(color: sz.inkMuted, fontSize: 13.5)),
            ],
          ),
        ),
      ),
    );
  }

  /// 5% 承诺条:全首页唯一一处 claySoft。左侧衬线大字是这套视觉的记忆点。
  /// 点进去看单笔分账(#107 的「钱去哪了」页;资质/入口在那条任务里收口)。
  ///
  /// **可以永久关掉。** 它是一句宣言,老用户看过一次就够了 ——
  /// 天天顶在首页上就从"我们不黑你"变成了打扰。关掉不影响任何功能:
  /// 「我的 → 这钱怎么算的」一直在。
  Widget _promiseStrip() {
    final sz = Theme.of(context).sz;
    if (_pledgeHidden) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 0),
      child: InkWell(
        borderRadius: BorderRadius.circular(kRadiusMd),
        onTap: () => openMoneyFlow(context, widget.api),
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 11, 14, 11),
          decoration: BoxDecoration(
            color: sz.claySoft,
            borderRadius: BorderRadius.circular(kRadiusMd),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Text('5%',
                  style: szFigure(
                      fontSize: 22,
                      fontWeight: FontWeight.w600,
                      color: sz.clay)),
              const SizedBox(width: 12),
              // 正文与链接分成两行:混在一段里,窄屏会把「这钱怎么算的 →」
              // 从中间折断,下划线跟着断成两截
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                        RemoteCopy.text('pledge.commission',
                            '商家总负担 5% 封顶,配送费 100% 归骑手'),
                        style: TextStyle(
                            fontSize: 12, height: 1.5, color: sz.ink)),
                    const SizedBox(height: 2),
                    Text('这钱怎么算的 →',
                        style: TextStyle(
                            fontSize: 12,
                            height: 1.4,
                            color: sz.clay,
                            decoration: TextDecoration.underline,
                            decorationColor: sz.clay)),
                  ],
                ),
              ),
              // 关闭:热区做到 40×40(图标只有 16,光按图标点不中)。
              // 放在整条 InkWell 里面,所以要自己吃掉点击,
              // 否则点关闭会连带触发"进分账页"
              Semantics(
                label: '不再显示这条承诺',
                button: true,
                child: InkWell(
                  borderRadius: BorderRadius.circular(20),
                  onTap: _hidePledge,
                  child: SizedBox(
                    width: 40,
                    height: 40,
                    child: Icon(Icons.close, size: 16, color: sz.inkMuted),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// 金刚区:业务矩阵。已上线的三项做成描述性宽卡(标题 + 一行副文案),
  /// 未上线的愿景位仍是紧凑格——每个占位都是一句"我们打算怎么不黑"的宣言,
  /// 是愿景展示位,不是空头支票堆。
  ///
  /// 图标位用衬线单字而不是 Material 图标:一屏里图标越少,
  /// 真正要你点的那一个越显眼。
  Widget _kingKong() {
    final sz = Theme.of(context).sz;

    Widget comingEntry(IconData icon, String label, String coming, String blood) {
      return InkWell(
        borderRadius: BorderRadius.circular(kRadiusSm),
        // 占位业务点进落地页:把行业问题和我们的姿态讲清楚,不是糊弄的"敬请期待"
        onTap: () => Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => ComingSoonPage(
                name: label, icon: icon, blood: blood, promise: coming))),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 10),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, color: sz.inkFaint, size: 21),
              const SizedBox(height: 6),
              Text(label,
                  style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
            ],
          ),
        ),
      );
    }

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 0),
          // 自动换行,**列数按频道个数选** —— 关键是避开「末行只剩一个」。
          //
          // 之前写死 3 列,而上线频道正好是 4 个,排出来就是 3+1:
          // 第二行一张卡孤零零靠左,右边整整空掉三分之二。
          // 这就是"挤到一边"。4 个改成 2 列排成 2×2,一格不空。
          //
          // 规则在 shared 的 channelGridColumns 里,有测试锁着 ——
          // 加频道时排版会不会退化成孤儿行,不该靠人肉数格子
          // 排版全在 shared 的 SzChannelGrid 里(有测试锁着:末行不孤单、
          // 频道多了自动换聚合式、长辈版 1.4× 下不撑爆)。
          // 这里只管点了之后去哪 —— 那是各端自己的事
          child: SzChannelGrid(onTap: (ch) async {
            // 跑腿单一建出来就是「待支付」,必须把订单接回来直接进支付。
            // 之前这里和其他频道一样 push 完就不管返回值,
            // 结果用户填完地址、看完报价、点了下单,页面一关单子就没了
            if (ch.key == 'errand') {
              final created = await Navigator.of(context).push<Order>(
                  MaterialPageRoute<Order>(
                      builder: (_) => ErrandPage(api: widget.api)));
              // 用 State 的 mounted 而不是 context.mounted:
              // 这个 context 是 State 的,分析器要求两者对上
              if (created == null || !mounted) return;
              final paid = await payPendingOrder(widget.api, created, context);
              if (!mounted) return;
              // 付没付成都进详情:付成了能看进度,没付成那里有「去支付」
              await Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => OrderDetailPage(
                      api: widget.api, orderNo: (paid ?? created).orderNo)));
              return;
            }
            final route = switch (ch.key) {
              'food' => MaterialPageRoute<void>(
                  builder: (_) => CategoryPage(
                      api: widget.api,
                      deliveryAddress: widget.deliveryAddress)),
              'stay' => MaterialPageRoute<void>(
                  builder: (_) => HotelListPage(
                      api: widget.api, lat: _myLat, lng: _myLng)),
              'voucher' => MaterialPageRoute<void>(
                  builder: (_) => DealsPage(api: widget.api)),
              // 跑腿在上面单独处理(要接住订单去支付),不走这个 switch
              // 注册了但还没接页面的频道:不跳空白页,直接不响应
              _ => null,
            };
            if (route != null) Navigator.of(context).push(route);
          }),
        ),
        // 未上线业务的愿景占位:审核包里整体隐藏(feature_flags.dart)
        if (kShowComingSoonBiz)
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 0),
            child: GridView.count(
              crossAxisCount: 5,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              childAspectRatio: 1.05,
              children: [
                comingEntry(Icons.local_taxi_outlined, '打车',
                    '司机不被抽走三成车费', '司机每单被抽走两三成,高峰还有乘客看不见的差价'),
                comingEntry(Icons.cleaning_services_outlined, '家政',
                    '阿姨的钱不过中介的手', '中介两头收费,阿姨的月薪被抽走两到四成'),
                comingEntry(Icons.build_outlined, '维修',
                    '明码标价,不搞小病大修', '上门费加虚报故障,"小病大修"成了行业默认'),
                comingEntry(Icons.local_shipping_outlined, '货运',
                    '不收会员费,不用算法压价', '司机先交会员费才能接单,算法再一路压运价'),
                comingEntry(Icons.badge_outlined, '零工',
                    '日结工资一分不被中介截', '劳务中介层层转包,日结工资被截走一两成'),
              ],
            ),
          ),
      ],
    );
  }

  /// 再来一单:外卖最高频的路径是回头单,抬到首屏(Grab 的 Order it again)
  Widget _reorderRow() {
    final sz = Theme.of(context).sz;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 20, kPagePad, 9),
          child: const SzSectionTitle('再来一单'),
        ),
        SizedBox(
          // 卡高跟着字号缩放走:写死 88 的话,长辈版/系统大字下
          // 摘要那行会被从中间切断(1.3× 实测)
          height: 88 * MediaQuery.textScalerOf(context).scale(1.0).clamp(1.0, 1.5),
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: kPagePad),
            itemCount: _reorder.length,
            separatorBuilder: (_, __) => const SizedBox(width: 9),
            itemBuilder: (context, i) {
              final order = _reorder[i];
              return SizedBox(
                width: 168,
                child: SzCard(
                  onTap: () => _openReorder(order),
                  padding: const EdgeInsets.all(11),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                          order.merchantName.isEmpty
                              ? '常点的店'
                              : order.merchantName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                              fontWeight: FontWeight.w600,
                              fontSize: 13,
                              color: sz.ink)),
                      const SizedBox(height: 2),
                      Expanded(
                        child: Text(order.summary,
                            // 字号放大后两行塞不下,降成一行省略号,
                            // 比让第二行被从中间切断体面
                            maxLines: MediaQuery.textScalerOf(context)
                                        .scale(1.0) >
                                    1.15
                                ? 1
                                : 2,
                            overflow: TextOverflow.ellipsis,
                            style:
                                TextStyle(fontSize: 11, color: sz.inkMuted)),
                      ),
                      Text(yuan(order.totalCents),
                          style: szMoney(fontSize: 12.5, color: sz.inkMuted)),
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

  /// 我的常点:比「再来一单」更细一档 —— 整单重下改一个菜就得重翻菜单,
  /// 这里按单品复购,点一下就进店带着这道菜。次数是真实下单数,不可运营干预。
  Widget _frequentRow() {
    final sz = Theme.of(context).sz;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 20, kPagePad, 9),
          child: const SzSectionTitle('我的常点'),
        ),
        SizedBox(
          height:
              104 * MediaQuery.textScalerOf(context).scale(1.0).clamp(1.0, 1.5),
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: kPagePad),
            itemCount: _frequent.length,
            separatorBuilder: (_, __) => const SizedBox(width: 9),
            itemBuilder: (context, i) {
              final f = _frequent[i];
              return SizedBox(
                width: 150,
                child: Opacity(
                  // 打烊的店淡掉但不隐藏:藏起来用户会以为自己的常点丢了
                  opacity: f.merchantOpen ? 1 : 0.45,
                  child: SzCard(
                    onTap: () => _openFrequent(f),
                    padding: const EdgeInsets.all(10),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SzImage(
                          url: f.imageUrl.isEmpty
                              ? ''
                              : widget.api.resolveUrl(f.imageUrl),
                          name: f.dishName,
                          size: 40,
                        ),
                        const SizedBox(width: 9),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(f.dishName,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                      fontWeight: FontWeight.w600,
                                      fontSize: 12.5,
                                      color: sz.ink)),
                              Text(f.merchantName,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                      fontSize: 10.5, color: sz.inkMuted)),
                              const Spacer(),
                              Text(yuan(f.priceCents),
                                  style:
                                      szMoney(fontSize: 12.5, color: sz.ink)),
                              Text(
                                  f.merchantOpen
                                      ? '点过 ${f.times} 次'
                                      : '休息中 · 点过 ${f.times} 次',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(
                                      fontSize: 10, color: sz.inkMuted)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),
      ],
    );
  }

  /// 商家行:62px 缩略图 + 店名 + 两行 meta,行间 1px 发丝线。
  ///
  /// 从 132px 大封面改成缩略图,是为了让店名和价格先被读到;
  /// 但招牌菜三连保留——那是"这家卖什么、多少钱"的决策信息,
  /// 属于功能不属于装饰,不能顺手删掉。
  Widget _bigMerchantCard(Merchant m) {
    final sz = Theme.of(context).sz;
    // 距离优先用**服务端算的**(#294):它是 PostGIS 球面距离,
    // 比客户端 haversine 准,而且和排序用的是同一个数 ——
    // 各算各的会出现「排在前面的反而显示更远」
    final dist = m.distanceM ?? distanceMeters(_myLat, _myLng, m.lat, m.lng);
    final eta = etaMinutes(dist);
    // 曝光埋点:商家漏斗最上面那一级(此前只有"进店"往下)。
    // 每店每次冷启动只报一次 —— 滚动列表来回划不该刷出几十条,
    // 且埋点口径不变:只记登录用户的产品行为,不采设备指纹
    _trackImpression(m.id);

    // 缺图占位统一走 SzImage:底色按名称哈希取,同一家店永远同一个色
    Widget thumb(String url, String name, double size) => SzImage(
          url: url.isEmpty ? '' : widget.api.resolveUrl(url),
          name: name,
          size: size,
          categoryIcon: merchantCategoryIcon(m.category),
        );

    // 一行小字:标签之间用「·」隔开,排不下就截断
    Widget dim(String t, {Color? color}) => Text(t,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontSize: 11.5, color: color ?? sz.inkMuted));

    return InkWell(
      onTap: () => Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => MenuPage(api: widget.api, merchant: m))),
      child: Container(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 12),
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: sz.line)),
        ),
        // 图定高 100,右侧四行 spaceBetween 撑满 —— 图下不留空白。
        //
        // 上一版是 62px 缩略图配右侧 109px 的内容,图**下方空着 47px**,
        // 那正是列表看着松散的来源。现在反过来:让图当高度基准,
        // 文字排布跟着它走,两边齐平。
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            thumb(m.logoUrl, m.name, 100),
            const SizedBox(width: 10),
            Expanded(
              child: SizedBox(
                height: 100,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(m.name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: sz.ink)),

                    // 第二行:评分 · 月售 · 人均。
                    // 三个都是"这家店怎么样"的判断依据,放一起。
                    // 没有的如实写「暂无评价」「新店」—— 不知道就说不知道,
                    // 和首页那几个 0 是同一条(#296)
                    Row(children: [
                      if (m.ratingAvg != null) ...[
                        Text('${m.ratingAvg}',
                            style: szFigure(fontSize: 12, color: sz.hold)),
                        Text(' 分',
                            style: TextStyle(
                                fontSize: 11.5, color: sz.inkMuted)),
                        const SizedBox(width: 8),
                      ] else ...[
                        dim('暂无评价', color: sz.inkFaint),
                        const SizedBox(width: 8),
                      ],
                      if (m.monthlySales > 0) ...[
                        dim('月售 ${m.monthlySales}'),
                        const SizedBox(width: 8),
                      ],
                      // Flexible:窄屏或长辈版下这一行会排不开,
                      // 让最后一项先截断,而不是整行溢出画出界
                      Flexible(
                        child: m.avgSpendCents != null
                            ? dim('人均 ${yuanShort(m.avgSpendCents!)}')
                            : dim('新店', color: sz.inkFaint),
                      ),
                    ]),

                    // 第三行:左边是钱,右边是路。
                    //
                    // 左右分栏是这一版的关键 —— 上一版全挤在左边,一行
                    // 只装得下一组信息,于是要么换行要么装不下。
                    //
                    // ⚠️ **不显示配送费。** 它取决于距离 + 夜间 + 天气,
                    // 只有服务端算得准;客户端凑一个数出来,就会出现
                    // 「列表说 ¥3,结算页说 ¥5」—— 同一件事两个答案,
                    // 那正是 #295 花力气修掉的毛病,不能在这儿再造一个。
                    // 真要显示,得让列表接口把它一起算出来。
                    Row(children: [
                      dim('起送 ${yuanShort(m.minOrderCents)}'),
                      const Spacer(),
                      // 距离时长不许被挤掉:它是右栏的锚,
                      // 排不下时该让左边先让
                      Flexible(child: dim('${distanceLabel(dist)} · $eta 分钟')),
                    ]),

                    // 第四行:券 → 封签 → 法定标识,按"帮不帮得上决策"排序。
                    //
                    // 券用实底(全卡最扎眼的一处,它直接影响下不下单),
                    // 封签用描边,法定标识退成灰字排最后 ——
                    // 明厨亮灶与堂食是总局令 123 号要求列表页展示的,
                    // **两种状态都要标**,所以没装的店也照写,只是不抢眼
                    Row(children: [
                      // 券最多两个:三个就把这一行挤满,法定标识没地方站
                      for (final label in m.promoLabels.take(2)) ...[
                        Flexible(child: _solidChip(label, sz)),
                        const SizedBox(width: 6),
                      ],
                      if (m.busyActive) ...[
                        SzChip('出餐较慢', color: sz.hold, dense: true),
                        const SizedBox(width: 6),
                      ],
                      if (m.foodSeal) ...[
                        SzChip('封签', color: sz.earn, dense: true),
                        const SizedBox(width: 6),
                      ],
                      Flexible(
                        child: dim(
                          '${m.dineInLabel} · '
                          '${m.kitchenCam ? '有明厨亮灶' : '无明厨亮灶'}',
                          color: sz.inkFaint,
                        ),
                      ),
                    ]),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// 券:实底小标签。全卡唯一一处实底 —— 它是最直接影响下单的信息。
  Widget _solidChip(String text, SzColors sz) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
        decoration: BoxDecoration(
          color: sz.hold.withValues(alpha: .12),
          borderRadius: BorderRadius.circular(4),
        ),
        child: Text(text,
            style: TextStyle(fontSize: 11, color: sz.hold)),
      );

  Widget _bigCardSkeleton() {
    final sz = Theme.of(context).sz;
    Widget block(double h, double w) => Container(
        height: h,
        width: w,
        decoration: BoxDecoration(
            color: sz.surfaceAlt, borderRadius: BorderRadius.circular(4)));
    return Container(
      padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 14),
      decoration:
          BoxDecoration(border: Border(bottom: BorderSide(color: sz.line))),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          block(62, 62),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                block(15, 140),
                const SizedBox(height: 8),
                block(11, double.infinity),
                const SizedBox(height: 6),
                block(11, 180),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Stack(children: [
      NotificationListener<ScrollNotification>(
        onNotification: _onScrollForMiniApps,
        child: _buildList(context),
      ),
      // 下拉预览条:跟手露头,盖在列表上方(#278)
      if (_miniPull > 0)
        Positioned(
          top: 0,
          left: 0,
          right: 0,
          child: MiniAppsPeek(pull: _miniPull, apps: _miniApps),
        ),
    ]);
  }

  Widget _buildList(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async {
        _loadRecent();
        _loadMiniApps(); // 登录状态变过的话,清单跟着刷新
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
                    // 人不在收货地址那一片了(#282)。非阻断,他点了才换
                    if (_farFromHere) _farBanner(),
                    _kingKong(),
                    _promiseStrip(),
                    if (_frequent.isNotEmpty) _frequentRow(),
                    if (_reorder.isNotEmpty) _reorderRow(),
                  ]),
                ),
              SliverPersistentHeader(
                pinned: true,
                delegate: _PinnedChipsDelegate(_sortChips()),
              ),
              SliverList(
                delegate: SliverChildListDelegate([
              if ((!_realLocation || _fellBack) && merchants != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 0),
                  // 定位没拿到时,原来只有一句「正在展示演示区域的商家」——
                  // 西安的用户会对着成都的店干看着(#283)。现在给他一条出路:
                  // 直接选城市。演示城市那条降级**没有删**,它是应用商店
                  // 审核员在外地/海外时的兜底,只是不再是唯一选择
                  child: Row(children: [
                    Expanded(
                      child: Text(
                          _fellBack
                              ? '您所在区域暂未开通,正在展示演示城市商家'
                              : '未获取到定位,正在展示演示区域的商家(下拉重试)',
                          style: TextStyle(
                              fontSize: 12,
                              height: 1.5,
                              color: Theme.of(context).sz.inkMuted)),
                    ),
                    const SizedBox(width: 8),
                    SzCityChip(
                      city: _pickedCity,
                      loadCities: widget.api.openCities,
                      onChanged: _useCity,
                    ),
                  ]),
                ),
              if (snapshot.hasError)
                SzError(
                    error: snapshot.error,
                    onRetry: () => setState(() => _future = _load())),
              if (!snapshot.hasData && !snapshot.hasError) ...[
                _bigCardSkeleton(),
                _bigCardSkeleton(),
              ] else if (merchants != null && merchants.isEmpty)
                // 先认筛选:筛没了跟"这一带没商家"是两回事,给的出口也不同
                _filterCount > 0
                    ? _filteredEmpty()
                // 空品类不摆烂:空状态变招商位(平台没钱补贴,但入驻免费是真的)
                : (widget.category?.isNotEmpty ?? false)
                    ? _categoryVacancy()
                    : const Padding(
                        padding: EdgeInsets.only(top: 40),
                        child: SzEmpty(
                            art: BrandArt.bowl,
                            text: '附近暂时没有营业的商家\n下拉刷新试试'),
                      ),
                ]),
              ),
              // 商家卡片按需构建。原来是 SliverChildListDelegate 里 for 展开,
              // 进首页就把全部卡片一次性建出来,商家一多首帧就卡
              if (merchants != null)
                SliverList.builder(
                  itemCount: merchants.length + _more.length,
                  itemBuilder: (context, i) {
                    // 触底预加载:首页不满一页就说明后面没有了,不用白跑一趟
                    if (i == merchants.length + _more.length - 1 &&
                        merchants.length >= _pageSize) {
                      WidgetsBinding.instance.addPostFrameCallback((_) =>
                          _loadMore(merchants.length + _more.length));
                    }
                    final m = i < merchants.length
                        ? merchants[i]
                        : _more[i - merchants.length];
                    return FadeSlideIn(index: i, child: _bigMerchantCard(m));
                  },
                ),
              SliverToBoxAdapter(
                child: Column(children: [
                  // 排序口径的兜底承诺:钱买不到靠前的位置
                  if (merchants != null && merchants.isNotEmpty)
                    Padding(
                      padding:
                          const EdgeInsets.fromLTRB(kPagePad, 18, kPagePad, 0),
                      child: Text('没有竞价排名 · 排序只按你选的口径',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                              fontSize: 11.5,
                              color: Theme.of(context).sz.inkMuted)),
                    ),
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
      // 并发:店铺详情和菜单互不依赖,串起来发等于让用户多等一个来回
      final (detail, dishes) = await (
        widget.api.merchantDetail(widget.merchant.id),
        widget.api.menu(widget.merchant.id),
      ).wait;
      bool fav = _isFavorite;
      if (widget.api.isLoggedIn) {
        try {
          fav = (await widget.api.favoriteIds()).contains(widget.merchant.id);
        } catch (_) {}
      }
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
    final confirmed = await szShowSheet<bool>(
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
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    final action = await szShowSheet<String>(
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
          builder: (context) => SzDialog(
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

  Future<void> _checkout() async {
    // 游客加购随意,结算需要登录(登录成功后购物车原样保留)
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
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
    final sz = theme.sz;
    final rate = (shop.commissionRate * 100).toStringAsFixed(0);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(shop.name,
              style: TextStyle(
                  fontSize: 21,
                  fontWeight: FontWeight.w600,
                  letterSpacing: -0.3,
                  color: sz.ink)),
          const SizedBox(height: 6),
          InkWell(
            onTap: () => _tabController.animateTo(1), // 切到「评价」Tab
            child: Row(
              children: [
                Flexible(
                  child: Text(
                      [
                        '${shop.ratingLabel} · 月售 ${shop.monthlySales} 单 · 配送费 ¥3 起',
                        if (shop.minOrderCents > 0)
                          '¥${shop.minOrderCents ~/ 100} 起送',
                        ...shop.promoLabels,
                      ].join(' · '),
                      style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
                ),
                Icon(Icons.chevron_right, size: 14, color: sz.inkFaint),
              ],
            ),
          ),
          // 明厨亮灶的链接标识(#155)。**位置是法规指定的**:
          // 总局令第 123 号第二十五条要求"在其主页面显著位置设置
          // 「明厨亮灶」的链接标识" —— 店铺页顶部信息行的正下方,
          // 就是这家店的"主页面显著位置"。
          //
          // 没装的店也显示(灰色「无明厨亮灶」),因为第十三条要标的是两种。
          const SizedBox(height: 9),
          SzKitchenCamChip(
            has: shop.kitchenCam,
            label: shop.kitchenCamLabel,
            onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
              builder: (_) => KitchenCamPage(
                shopName: shop.name,
                load: () => widget.api.kitchenCamOf(shop.id),
                // 真播放器只在用户端注入 —— 骑手端/商家端不看直播,
                // 不该为此各装一个原生播放器
                playerBuilder: (url) => KitchenCamPlayer(url: url),
              ),
            )),
          ),
          // 堂食标识(#187):第 123 号令第十二条要求商家主页面也要展示,
          // 位置紧挨明厨亮灶那一条。三态照实显示,未填报不猜
          const SizedBox(height: 7),
          Row(children: [
            Icon(
                shop.dineInStatus == 'yes'
                    ? Icons.restaurant
                    : Icons.storefront_outlined,
                size: 14,
                color: shop.dineInStatus == 'yes' ? sz.earn : sz.inkMuted),
            const SizedBox(width: 5),
            Text(shop.dineInLabel,
                style: TextStyle(
                    fontSize: 12,
                    color: shop.dineInStatus == 'yes' ? sz.earn : sz.inkMuted)),
          ]),
          // 把平台主张落到这一家店:抽象的「5% 封顶」在这里变成
          // 「你这一单便宜在哪」——这是店铺页唯一该讲平台的地方
          const SizedBox(height: 11),
          SzCard(
            padding: const EdgeInsets.fromLTRB(13, 11, 13, 11),
            child: Text.rich(
              TextSpan(children: [
                const TextSpan(text: '这家店在超级赞只被抽 '),
                TextSpan(
                    text: '$rate%',
                    style: szFigure(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: sz.clay)),
                const TextSpan(text: ',省下的抽成让在了菜价上——菜价里没有平台税。'),
              ]),
              style: TextStyle(fontSize: 12, height: 1.55, color: sz.ink),
            ),
          ),
          if (shop.foodSeal)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(children: [
                Icon(Icons.verified_user_outlined, size: 16, color: sz.earn),
                const SizedBox(width: 6),
                Expanded(
                  child: Text('商家声明:打包使用一次性食安封签,拆封即留痕'
                      '(商家自述,非平台核验)',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: sz.inkMuted)),
                ),
              ]),
            ),
          // 忙碌模式:先说清楚再让用户下单,而不是下了单再超时
          if (shop.busyActive)
            Container(
              margin: const EdgeInsets.only(top: 8),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: sz.hold.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(children: [
                Icon(Icons.schedule, size: 16, color: sz.hold),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                      '商家高峰忙碌中,出餐较慢,预计送达时间已相应放宽',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: sz.hold)),
                ),
              ]),
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
    final sz = Theme.of(context).sz;
    return Container(
      width: 84,
      color: sz.surfaceAlt,
      child: ListView(
        children: [
          for (final c in _categories)
            InkWell(
              onTap: () => setState(() => _category = c),
              child: Container(
                padding:
                    const EdgeInsets.symmetric(vertical: 13, horizontal: 8),
                decoration: BoxDecoration(
                  color: c == _category ? sz.paper : Colors.transparent,
                  border: Border(
                    left: BorderSide(
                      width: 2,
                      color: c == _category ? sz.clay : Colors.transparent,
                    ),
                  ),
                ),
                child: Text(
                  c,
                  style: TextStyle(
                    fontSize: 12.5,
                    color: c == _category ? sz.ink : sz.inkMuted,
                    fontWeight:
                        c == _category ? FontWeight.w600 : FontWeight.w400,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  /// 菜品缩略图。从 64 收到 58:图越小,菜名和价格越先被读到。
  Widget _dishImage(Dish dish) => SzImage(
        url: dish.imageUrl.isEmpty ? '' : widget.api.resolveUrl(dish.imageUrl),
        name: dish.name,
        size: 58,
      );

  /// 购物车条的动态提示:差多少能满减最有推动力,够了就明说已减多少。
  /// 规则取商家的 promoRules(与结算页、后端同一份数据,不另算一套)。
  String _cartNote() {
    if (_cart.isEmpty) return '配送费按距离结算 · 100% 归骑手';
    final shop = _detail ?? widget.merchant;
    final rules = List.of(shop.promoRules)
      ..sort((a, b) => a.thresholdCents.compareTo(b.thresholdCents));
    if (rules.isEmpty) return '配送费按距离结算 · 100% 归骑手';

    // 已达成的最高档
    final hit = rules.where((r) => _totalCents >= r.thresholdCents).toList();
    // 下一档
    final next =
        rules.where((r) => _totalCents < r.thresholdCents).toList();
    if (next.isNotEmpty) {
      final gap = next.first.thresholdCents - _totalCents;
      final off = yuan(next.first.offCents);
      return hit.isEmpty
          ? '再点 ${yuan(gap)} 可减 $off'
          : '已减 ${yuan(hit.last.offCents)} · 再点 ${yuan(gap)} 可减 $off';
    }
    return '已减 ${yuan(hit.last.offCents)} · 另计配送费';
  }

  Widget _stepper(Dish dish, int quantity, void Function(Dish, int) change) {
    return SzStepper(
      quantity: quantity,
      // 库存到顶就不给加(原逻辑靠 onPressed: null 置灰,这里保持同一口径)
      onAdd: () {
        if (dish.stock > quantity) change(dish, 1);
      },
      onRemove: () => change(dish, -1),
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
                avatar: Icon(Icons.card_giftcard,
                    size: 16, color: Theme.of(context).sz.clay),
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
        // 非供应时段与售罄同等对待:能看见、看得懂为什么、但点不了
        final soldOut = dish.stock <= 0 || !dish.servableNow;
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
                              color: Theme.of(context).sz.claySoft,
                              borderRadius: BorderRadius.circular(3),
                            ),
                            child: Text('酒',
                                style: TextStyle(
                                    fontSize: 10, color: Theme.of(context).sz.hold)),
                          ),
                        ],
                      ]),
                      // 商家自述的客观标签(新品/招牌/辣度/忌口提示)。
                      // 含"含花生""含香菜"这类是为了让有忌口的人一眼看到
                      if (dish.badges.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Wrap(spacing: 4, runSpacing: 2, children: [
                            for (final badge in dish.badges)
                              // 忌口类("含花生")关乎安全,不能用最淡的墨色:
                              // inkFaint 在骨白底上对比度只有 2.5,不过 AA(4.5)
                              SzChip(badge,
                                  color: kAllergenBadges.contains(badge)
                                      ? Theme.of(context).sz.danger
                                      : Theme.of(context).sz.inkMuted,
                                  dense: true),
                          ]),
                        ),
                      // 套餐:直接把"里面有什么"写在列表行,
                      // 用户不用点进去才知道自己买的是什么
                      if (dish.isCombo && dish.comboDishes.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Text(
                              '含 ${dish.comboDishes.map((c) => '${c['name']}×${c['quantity']}').join(' + ')}',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                  fontSize: 11.5,
                                  color: Theme.of(context).sz.inkMuted)),
                        ),
                      // 非供应时段:说清楚什么时候能点,而不是让菜凭空消失
                      if (!dish.servableNow && dish.serveWindow.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Text('${dish.serveWindow} 供应',
                              style: TextStyle(
                                  fontSize: 11.5,
                                  color: Theme.of(context).sz.hold)),
                        ),
                      if (dish.description.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 2),
                          child: Text(dish.description,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                  fontSize: 11.5,
                                  color: Theme.of(context).sz.inkMuted)),
                        ),
                      const SizedBox(height: 2),
                      Row(
                        children: [
                          // 价格用墨色不用强调色:一屏里 clay 只留给"要你点的那一个"
                          Text(
                            soldOut
                                // 估清 = 今日售罄(明天自动恢复),区别于长期没货
                                ? (dish.soldOutToday ? '今日售罄' : '已售罄')
                                : dish.hasOptions
                                    ? '${yuan(dish.effectivePriceCents)} 起'
                                    : yuan(dish.effectivePriceCents),
                            style: soldOut
                                ? TextStyle(
                                    fontSize: 13,
                                    color: Theme.of(context).sz.inkMuted)
                                : szMoney(
                                    fontSize: 14,
                                    fontWeight: FontWeight.w600,
                                    color: Theme.of(context).sz.ink),
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
                                    Theme.of(context).sz.hold.withValues(alpha: 0.15),
                                borderRadius: BorderRadius.circular(3),
                              ),
                              child: Text('限时',
                                  style: TextStyle(
                                      fontSize: 10, color: Theme.of(context).sz.hold)),
                            ),
                          ],
                          // 套餐:划线单点合计 + "省 X" —— 省多少是套餐
                          // 唯一要说清楚的事
                          if (!soldOut && dish.comboSaveCents > 0) ...[
                            const SizedBox(width: 4),
                            Text(yuan(dish.comboOriginalCents),
                                style: TextStyle(
                                    fontSize: 11,
                                    color:
                                        Theme.of(context).colorScheme.outline,
                                    decoration: TextDecoration.lineThrough)),
                            const SizedBox(width: 3),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 4, vertical: 1),
                              decoration: BoxDecoration(
                                color: Theme.of(context)
                                    .sz
                                    .earn
                                    .withValues(alpha: 0.15),
                                borderRadius: BorderRadius.circular(3),
                              ),
                              child: Text('省${yuan(dish.comboSaveCents)}',
                                  style: TextStyle(
                                      fontSize: 10,
                                      color: Theme.of(context).sz.earn)),
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
    szShowSheet(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) {
          final theme = Theme.of(context);
          final quantity = _qtyOf(dish);
          final soldOut = dish.stock <= 0 || !dish.servableNow;
          return SafeArea(
            // 必须可滚动:菜品描述最长 200 字,加上忌口标签换行,
            // 在小屏或大字号(textScaler 上限 1.6)下会把底部的
            // 「加入购物车」按钮挤出屏幕 —— release 构建是**静默裁切**,
            // 那道菜就变成点不了了。高度也封顶,不让弹层顶满全屏
            child: ConstrainedBox(
              constraints: BoxConstraints(
                  maxHeight: MediaQuery.of(sheetContext).size.height * 0.85),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                // 大图:缺图时是同一套占位(色底 + 菜名首字),不是灰图标
                SzCover(
                  url: dish.imageUrl.isEmpty
                      ? ''
                      : widget.api.resolveUrl(dish.imageUrl),
                  name: dish.name,
                  height: 200,
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
                      if (dish.badges.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Wrap(spacing: 6, runSpacing: 4, children: [
                          for (final badge in dish.badges)
                            SzChip(badge,
                                color: kAllergenBadges.contains(badge)
                                    ? Theme.of(context).sz.danger
                                    : Theme.of(context).sz.inkMuted,
                                dense: true),
                        ]),
                      ],
                      if (dish.description.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        Text(dish.description,
                            style: theme.textTheme.bodyMedium?.copyWith(
                                color: Theme.of(context).sz.inkMuted)),
                      ],
                      if (dish.isAlcohol) ...[
                        const SizedBox(height: 6),
                        Text('🍺 酒类商品:未成年人禁止购买,下单需完成实名认证',
                            style: theme.textTheme.bodySmall?.copyWith(
                                color: Theme.of(context).sz.hold,
                                fontWeight: FontWeight.w600)),
                      ],
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          Text(yuan(dish.effectivePriceCents),
                              style: szMoney(
                                  fontSize: 24,
                                  fontWeight: FontWeight.w600,
                                  color: theme.sz.ink)),
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
              ),
            ),
          );
        },
      ),
    );
  }

  void _openCartSheet() {
    szShowSheet(
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
                          tooltip: '减少',
                          visualDensity: VisualDensity.compact,
                          icon: const Icon(Icons.remove_circle_outline),
                          onPressed: () => change(line, -1),
                        ),
                        Text('${line.quantity}'),
                        IconButton(
                          tooltip: '增加',
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
      // 原来这里只有一行错误文字,没有重试:菜单没加载出来就等于进不了这家店
      body = SzError(
          error: _error,
          onRetry: () {
            setState(() {
              _error = null;
              _loaded = false;
            });
            _load();
          });
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

    return SzPageScaffold(
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
              color: _isFavorite ? Theme.of(context).sz.danger : null,
            ),
            onPressed: () async {
              if (!await ensureLoggedIn(context)) return;
              if (!mounted) return;
              final next = !_isFavorite;
              setState(() => _isFavorite = next); // 先响应再请求,失败回滚
              try {
                final res =
                    await widget.api.setFavorite(widget.merchant.id, next);
                // 收藏有礼:券到手要让人看见,不然商家的钱白花
                final coupon = res['coupon'] as Map<String, dynamic>?;
                // 用 context.mounted:这里的 context 来自外层 builder,
                // 与 State.mounted 不是同一个东西
                if (coupon != null && context.mounted) {
                  final off = yuan(coupon['amount_cents'] as int? ?? 0);
                  final min = coupon['min_spend_cents'] as int? ?? 0;
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                    content: Text(min > 0
                        ? '收藏成功,商家送你一张满${yuan(min)}减$off 的券'
                        : '收藏成功,商家送你一张 $off 无门槛券'),
                    action: SnackBarAction(
                      label: '看券包',
                      onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute<void>(
                              builder: (_) => CouponsPage(api: widget.api))),
                    ),
                  ));
                }
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
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
          decoration: BoxDecoration(
            color: Theme.of(context).sz.surface,
            border: Border(top: BorderSide(color: Theme.of(context).sz.line)),
          ),
          child: Row(
            children: [
              TweenAnimationBuilder<double>(
                key: ValueKey(_totalCount), // 数量一变,重放一次轻微放大
                // 原来是 elasticOut 弹跳 350ms:回弹属于"卖萌"的动效,
                // 和这套克制的观感对不上。改成 easeOutCubic 200ms,
                // 只给一下"数字变了"的确认,不表演
                tween: Tween(begin: 0.88, end: 1.0),
                duration: const Duration(milliseconds: 200),
                curve: Curves.easeOutCubic,
                builder: (context, scale, child) =>
                    Transform.scale(scale: scale, child: child),
                child: Badge.count(
                  count: _totalCount,
                  isLabelVisible: _totalCount > 0,
                  child: IconButton(
                    tooltip: '查看购物车',
                    icon: const Icon(Icons.shopping_cart_outlined),
                    onPressed: _cart.isEmpty ? null : _openCartSheet,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(_cart.isEmpty ? '¥0.00' : yuan(_totalCents),
                        style: szMoney(
                            fontSize: 20,
                            fontWeight: FontWeight.w600,
                            color: _cart.isEmpty
                                ? Theme.of(context).sz.inkMuted
                                : Theme.of(context).sz.ink)),
                    const SizedBox(height: 1),
                    Text(_cartNote(),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                            fontSize: 10.5,
                            color: Theme.of(context).sz.inkMuted)),
                  ],
                ),
              ),
              const SizedBox(width: 10),
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

/// 订单 tab:类型切换(点外卖/住宿);团购券在「我的-我的券包」保持原习惯,
/// 这里给个快捷入口不搬家
class OrdersTab extends StatefulWidget {
  const OrdersTab({
    super.key,
    required this.api,
    this.filter = OrderFilter.all,
    this.segment = 0,
  });

  final ApiClient api;

  /// 从「我的」页四格跳过来时带的筛选;直接点底部 tab 时是 [OrderFilter.all]
  final OrderFilter filter;

  /// 0 = 点外卖,1 = 住宿
  final int segment;

  @override
  State<OrdersTab> createState() => _OrdersTabState();
}

class _OrdersTabState extends State<OrdersTab> {
  late int _segment = widget.segment;
  late OrderFilter _filter = widget.filter;

  @override
  void initState() {
    super.initState();
    authTick.addListener(_onAuthChanged); // 游客登录成功后刷新
  }

  /// 这个 tab 在 IndexedStack 里是保活的 —— 从「我的」页再跳一次过来,
  /// State 不会重建,只有 widget 换新。不接这一下的话第二次点「待评价」
  /// 会停在上一次的筛选上
  @override
  void didUpdateWidget(OrdersTab old) {
    super.didUpdateWidget(old);
    if (widget.filter != old.filter || widget.segment != old.segment) {
      setState(() {
        _filter = widget.filter;
        _segment = widget.segment;
      });
    }
  }

  @override
  void dispose() {
    authTick.removeListener(_onAuthChanged);
    super.dispose();
  }

  void _onAuthChanged() {
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.api.isLoggedIn) {
      // 游客态:不请求订单接口,展示登录引导
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.receipt_long_outlined,
              size: 56, color: Theme.of(context).colorScheme.outline),
          const SizedBox(height: 12),
          const Text('登录后查看你的订单'),
          const SizedBox(height: 12),
          FilledButton(
              onPressed: () => ensureLoggedIn(context),
              child: const Text('登录 / 注册')),
        ]),
      );
    }
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
        child: Row(children: [
          // 频道归属标(#132):切换器只说"看哪一类",这个标说"你正在看的是
          // 哪个频道",带频道色 —— 聚合平台里用户经常忘了自己在哪个世界。
          // 频道多起来后这里会换成可横滑的频道条,现在两段够用
          SzChannelChip(_segment == 0 ? 'food' : 'stay', dense: false),
          const SizedBox(width: 10),
          Expanded(
            child: SegmentedButton<int>(
              segments: const [
                ButtonSegment(value: 0, label: Text('点外卖')),
                ButtonSegment(value: 1, label: Text('住宿')),
              ],
              selected: {_segment},
              onSelectionChanged: (s) => setState(() => _segment = s.first),
            ),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => MyVouchersPage(api: widget.api))),
            child: const Text('券包'),
          ),
        ]),
      ),
      // 状态筛选:「我的」页四格点进来要有地方落。
      // 横滑而不是折行 —— 五个筛选在 320 窄屏 + 长辈版下排不进一行
      SizedBox(
        height: 42,
        child: ListView(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
          children: [
            for (final f in OrderFilter.values)
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: SzChip(f.label,
                    selected: _filter == f,
                    onTap: () => setState(() => _filter = f)),
              ),
          ],
        ),
      ),
      Expanded(
        child: _segment == 0
            ? OrderListView(api: widget.api, filter: _filter)
            : StayOrderListView(api: widget.api, filter: _filter),
      ),
    ]);
  }
}

class OrderListView extends StatefulWidget {
  const OrderListView(
      {super.key, required this.api, this.filter = OrderFilter.all});

  final ApiClient api;

  /// 状态筛选。**在已拉到的页上过滤,不改分页请求** ——
  /// 服务端的 `status` 参数只收单个状态(见 routers/orders.py),
  /// 而「进行中」是四个状态、「待评价」还要看 has_review,
  /// 一个参数表达不了。混着用会让游标分页和过滤互相打架
  final OrderFilter filter;

  @override
  State<OrderListView> createState() => _OrderListViewState();
}

class _OrderListViewState extends State<OrderListView> {
  late Future<List<Order>> _future = _loadOrders();

  /// 各单的聊天未读数。骑手/商家发来的消息以前在列表上毫无痕迹,
  /// 用户不点进详情就永远不知道有人在等回话
  final Map<String, int> _unread = {};

  Future<List<Order>> _loadOrders() async {
    final orders = await widget.api.myOrders();
    // 只查进行中的单:已完成/已取消的单不会再有人说话,
    // 给全部订单各发一个请求纯属浪费
    final active = orders
        .where((o) =>
            o.status != OrderStatus.completed &&
            o.status != OrderStatus.cancelled)
        .take(6)
        .toList();
    final counts = await Future.wait(active
        .map((o) => widget.api.orderUnread(o.orderNo).onError((_, __) => 0)));
    if (!mounted) return orders;
    _unread
      ..clear()
      ..addEntries(
          [for (final (i, o) in active.indexed) MapEntry(o.orderNo, counts[i])]);
    return orders;
  }

  // 分页:老口径是服务端写死 limit(50) 不分页,用户超过 50 单后就永远看不到
  // 更早的订单——跟「每一单的账都可查」直接冲突。改成游标分页 + 触底加载。
  final List<Order> _loaded = [];
  bool _loadingMore = false;
  bool _noMore = false;

  Future<void> _loadMore() async {
    if (_loadingMore || _noMore || _loaded.isEmpty) return;
    setState(() => _loadingMore = true);
    try {
      final more = await widget.api.myOrders(before: _loaded.last.createdAt);
      if (!mounted) return;
      setState(() {
        _loaded.addAll(more);
        _noMore = more.isEmpty;
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  void _reset() {
    _loaded.clear();
    _noMore = false;
    _future = _loadOrders();
  }

  /// 状态语义色:进行中 = 品牌橙(需要关注),完成 = 账目绿(钱已结清),取消 = 灰
  Color _statusColor(OrderStatus status, ThemeData theme) => switch (status) {
        OrderStatus.completed => Theme.of(context).sz.earn,
        OrderStatus.cancelled => theme.colorScheme.outline,
        _ => theme.colorScheme.primary,
      };

  /// 订单时间:近的说「多久前」,远的才给日期。
  /// 外卖是分钟级的生意,「12 分钟前」和「7/27 17:21」的信息量差很远。
  String _timeLabel(Order order) => szTimeAgo(order.createdAt);

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
                    // 有人在等你回话:红点比什么文案都管用
                    if ((_unread[order.orderNo] ?? 0) > 0) ...[
                      Icon(Icons.mark_chat_unread,
                          size: 15, color: theme.colorScheme.primary),
                      const SizedBox(width: 4),
                      Text('${_unread[order.orderNo]}',
                          style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w700,
                              color: theme.colorScheme.primary)),
                      const SizedBox(width: 8),
                    ],
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
                      style: TextStyle(
                          fontSize: 12,
                          color: Theme.of(context).sz.hold,
                          fontWeight: FontWeight.w600)),
                ],
                if (order.selfDelivery) ...[
                  const SizedBox(height: 4),
                  Text('🛵 商家自送',
                      style: TextStyle(
                          fontSize: 12,
                          color: Theme.of(context).sz.earn,
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
                    // 待支付的单必须在列表里就能付。跑腿单建出来就是这个状态,
                    // 支付中断(切后台、网断)留下的单也落在这儿
                    if (order.status == OrderStatus.pendingPayment)
                      SizedBox(
                        height: 30,
                        child: FilledButton(
                          style: FilledButton.styleFrom(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 12),
                              visualDensity: VisualDensity.compact),
                          onPressed: () async {
                            final paid = await payPendingOrder(
                                widget.api, order, context);
                            if (paid != null && mounted) setState(_reset);
                          },
                          child: const Text('去支付',
                              style: TextStyle(fontSize: 12)),
                        ),
                      ),
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
      onRefresh: () async => setState(_reset),
      child: FutureBuilder(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return SzError(
                error: snapshot.error, onRetry: () => setState(_reset));
          }
          if (!snapshot.hasData) {
            return const SkeletonList();
          }
          // 第一页由 future 给,后续页累加进 _loaded
          if (_loaded.isEmpty) _loaded.addAll(snapshot.data!);
          final orders =
              _loaded.where(widget.filter.matchesFood).toList();
          // 筛选后可能一屏都填不满 —— 那样用户滚不动,触底加载永远不触发,
          // 更早的同类订单就永远看不到。这里替他把下一页要来
          if (orders.length < 6 && !_noMore && !_loadingMore &&
              _loaded.isNotEmpty) {
            WidgetsBinding.instance
                .addPostFrameCallback((_) => _loadMore());
          }
          if (orders.isEmpty) {
            return ListView(children: [
              const SizedBox(height: 120),
              SzEmpty(
                  art: BrandArt.receipt,
                  text: widget.filter == OrderFilter.all
                      ? '还没有订单\n去点一单支持身边小店吧'
                      : '没有${widget.filter.label}的订单'),
            ]);
          }
          return NotificationListener<ScrollNotification>(
            onNotification: (n) {
              // 触底前 400px 就开始加载,滚到底时下一页通常已经在了
              if (n.metrics.pixels >= n.metrics.maxScrollExtent - 400) {
                _loadMore();
              }
              return false;
            },
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: orders.length + 1,
              itemBuilder: (context, i) {
                if (i == orders.length) {
                  if (_loadingMore) {
                    return const Padding(
                      padding: EdgeInsets.all(20),
                      child: Center(
                          child: SizedBox(
                              width: 20,
                              height: 20,
                              child:
                                  CircularProgressIndicator(strokeWidth: 2))),
                    );
                  }
                  if (_noMore && orders.length > 10) {
                    return Padding(
                      padding: const EdgeInsets.fromLTRB(0, 16, 0, 24),
                      child: Text('没有更早的订单了',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                              fontSize: 11.5,
                              color: Theme.of(context).sz.inkMuted)),
                    );
                  }
                  return const SizedBox(height: 8);
                }
                return _orderCard(orders[i], i);
              },
            ),
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

class _OrderDetailPageState extends State<OrderDetailPage>
    with WidgetsBindingObserver {
  Order? _order;
  Review? _review;
  AfterSale? _afterSale;
  List<OrderEvent> _events = [];
  List<RefundRecord> _refunds = [];
  Map<String, dynamic>? _foodSafety;
  int _unread = 0;
  bool _reviewChecked = false;
  String? _error;
  Timer? _timer;
  WebSocketChannel? _ws;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refresh();
    _connectWs();
    _startPolling();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _ws?.sink.close();
    super.dispose();
  }

  /// 退到后台就停表。原来不判生命周期,用户切走之后这一页还在每 15 秒
  /// 发一轮请求,费流量费电,回前台时刷一次就够了
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _refresh();
      _startPolling();
    } else {
      _timer?.cancel();
      _timer = null;
    }
  }

  /// WebSocket 为主,慢轮询兜底(断线期间也不至于卡住)。
  /// 订单到终态后不会再变,继续轮询是白跑
  void _startPolling() {
    _timer?.cancel();
    if (_isFinal(_order?.status)) return;
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _refresh());
  }

  static bool _isFinal(OrderStatus? s) =>
      s == OrderStatus.completed || s == OrderStatus.cancelled;

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
      // 主数据并发拉。这两个互不依赖,串起来发等于让用户白等一个来回
      final (order, events) = await (
        widget.api.getOrder(widget.orderNo),
        widget.api.orderEvents(widget.orderNo),
      ).wait;

      // 附属数据也并发,而且各自兜底 —— 评价拉不到不该把整页打回错误态
      final needReview =
          order.status == OrderStatus.completed && !_reviewChecked;
      final needAfterSale = order.status == OrderStatus.delivered ||
          order.status == OrderStatus.completed;
      final (review, afterSale, refunds, foodSafety, unread) = await (
        needReview
            ? widget.api
                .orderReview(widget.orderNo)
                .onError((_, __) => _review)
            : Future<Review?>.value(_review),
        needAfterSale
            ? widget.api
                .orderAfterSale(widget.orderNo)
                .onError((_, __) => _afterSale)
            : Future<AfterSale?>.value(_afterSale),
        order.refundCents > 0
            // 拉不到就退回汇总文案
            ? widget.api
                .orderRefunds(widget.orderNo)
                .onError((_, __) => _refunds)
            : Future<List<RefundRecord>>.value(_refunds),
        // 食安投诉状态:投诉能提交却查不到进度,比没有入口更伤人
        widget.api
            .foodSafetyOfOrder(widget.orderNo)
            .onError((_, __) => _foodSafety),
        // 聊天未读:骑手/商家发来的消息以前完全不提醒,用户看不到就回不了
        _isFinal(order.status)
            ? Future<int>.value(0)
            : widget.api.orderUnread(widget.orderNo).onError((_, __) => _unread),
      ).wait;
      if (needReview) _reviewChecked = true;

      if (mounted) {
        setState(() {
          _order = order;
          _events = events;
          _review = review;
          _afterSale = afterSale;
          _refunds = refunds;
          _foodSafety = foodSafety;
          _unread = unread;
          _error = null;
        });
      }
      if (_isFinal(order.status)) _startPolling(); // 到终态就停表
    } catch (e) {
      // 原来这里是 catch (_) {},首次加载失败就永远转圈:
      // 没提示、没重试、用户只能杀进程
      if (mounted && _order == null) {
        setState(() => _error = e is ApiException ? e.message : '$e');
      }
    }
  }

  /// 售后分流:普通售后走商家先处理;食品安全是红线,不经商家直达平台
  Future<void> _chooseAfterSaleKind() async {
    final choice = await szShowSheet<String>(
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
                  Icon(Icons.report_gmailerrorred, color: Theme.of(context).sz.danger),
              title: Text('食品安全问题',
                  style: TextStyle(
                      color: Theme.of(context).sz.danger, fontWeight: FontWeight.bold)),
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

  /// 食安投诉:强制上传照片(走相册,不申请相机),可附医疗凭证;直达平台标红加急
  Future<void> _applyFoodSafety() async {
    var kind = 'foreign_object';
    final desc = TextEditingController();
    final images = <String>[];
    final medical = <String>[];
    var uploading = false;
    final submitted = await szShowSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheetContext) => StatefulBuilder(
        builder: (sheetContext, setSheet) {
          Future<void> pick(List<String> target) async {
            if (!await PermissionRationale.ensure(
                sheetContext, AppPermissionKind.photos)) {
              return;
            }
            final picked = await ImagePicker().pickImage(
                source: ImageSource.gallery,
                maxWidth: 1280,
                imageQuality: 85);
            if (picked == null) return;
            setSheet(() => uploading = true);
            try {
              final url = await widget.api
                  .uploadImage(await picked.readAsBytes(), picked.name,
              purpose: 'food_safety');
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
                  Text('食品安全投诉',
                      style: TextStyle(
                          color: Theme.of(context).sz.danger,
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
                  Text('问题食品照片(必传):',
                      style: Theme.of(sheetContext).textTheme.bodySmall),
                  const SizedBox(height: 6),
                  Wrap(spacing: 6, runSpacing: 6, children: [
                    for (final url in images)
                      ClipRRect(
                        borderRadius: BorderRadius.circular(6),
                        child: Image(image: szNetImage(widget.api.resolveUrl(url)),
                            width: 56, height: 56, fit: BoxFit.cover),
                      ),
                    if (images.length < 6)
                      OutlinedButton.icon(
                        icon: const Icon(Icons.add_a_photo, size: 16),
                        label: Text(uploading ? '上传中…' : '选图片'),
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
                        child: Image(image: szNetImage(widget.api.resolveUrl(url)),
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
                          backgroundColor: Theme.of(context).sz.danger),
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
          const SnackBar(content: Text('食安投诉必须上传问题食品照片')));
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
        builder: (context, setDialog) => SzDialog(
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
              Text('上传照片(必传,最多 3 张):有图才能快速判责退款',
                  style: Theme.of(context).textTheme.bodySmall),
              const SizedBox(height: 6),
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final url in images)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: Image(image: szNetImage(widget.api.resolveUrl(url)),
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
                            if (!await PermissionRationale.ensure(
                                context, AppPermissionKind.photos)) {
                              return;
                            }
                            final picked = await ImagePicker().pickImage(
                                source: ImageSource.gallery,
                                maxWidth: 1280,
                                imageQuality: 85);
                            if (picked == null) return;
                            setDialog(() => uploading = true);
                            try {
                              final url = await widget.api.uploadImage(
                                  purpose: 'after_sale',
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
      // etaMinutes 里**已经含 20 分钟出餐**,不能再外加一个 10 ——
      // 原来那样是把备餐算了两遍(#295)
      expect = created.add(Duration(
          minutes: etaMinutes(distanceMeters(
              order.merchantLat!, order.merchantLng!, order.lat, order.lng))));
    }
    final left = expect.difference(DateTime.now()).inMinutes;
    final hhmm = '${expect.hour.toString().padLeft(2, '0')}:'
        '${expect.minute.toString().padLeft(2, '0')}';
    if (left >= 0) return '预计 $hhmm 前送达 · 还有约 $left 分钟';
    return '抱歉,比预计($hhmm)晚了一些;超 15 分钟平台自动赔安抚券';
  }

  Future<void> _submitReview(int merchantRating, int? riderRating,
      String comment, List<String> imageUrls, List<String> tags,
      List<String> riderTags, bool isAnonymous) async {
    try {
      final review = await widget.api.submitReview(
        widget.orderNo,
        merchantRating: merchantRating,
        riderRating: riderRating,
        comment: comment,
        imageUrls: imageUrls,
        tags: tags,
        riderTags: riderTags,
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
    final add = await szShowSheet<int>(
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
            Padding(
              padding: EdgeInsets.only(bottom: 8, left: 14, right: 14),
              child: Text('小费 100% 归骑手,平台不抽成。加了会立刻通知附近骑手。',
                  style: TextStyle(fontSize: 12, color: Theme.of(context).sz.inkMuted)),
            ),
            for (final c in options)
              ListTile(
                leading: Icon(Icons.bolt, color: Theme.of(context).sz.hold),
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
    final reason = await szShowSheet<String>(
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

  /// 骑手发起的加价确认。同意与否都由你决定 ——
  /// 不回复的后果是骑手一直站在那里,所以文案直接把两条路都写清楚。
  /// 食安投诉状态。以前投诉能提交却查不到进度,用户交完照片就没下文了 ——
  /// 对一个把食安当卖点的平台,投诉黑洞比没有投诉入口更伤
  Widget _foodSafetyCard(Map<String, dynamic> report) {
    final theme = Theme.of(context);
    final status = report['status'] as String? ?? 'open';
    final (label, color) = switch (status) {
      'confirmed' => ('投诉成立,平台已处理', theme.sz.earn),
      'dismissed' => ('调查后未认定', theme.colorScheme.outline),
      _ => ('平台受理中', theme.colorScheme.primary),
    };
    final actions = (report['actions'] as List?) ?? const [];
    final latest = actions.isEmpty ? null : actions.last as Map;
    final note = (latest?['note'] as String?) ?? '';
    return Card(
      color: color.withValues(alpha: 0.08),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.health_and_safety_outlined, size: 18, color: color),
            const SizedBox(width: 6),
            Expanded(
                child: Text('食品安全投诉 · $label',
                    style: theme.textTheme.titleSmall
                        ?.copyWith(color: color, fontWeight: FontWeight.w700))),
          ]),
          if (note.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(note, style: theme.textTheme.bodySmall),
          ],
          if (status == 'open') ...[
            const SizedBox(height: 6),
            Text('食安投诉不经商家,由平台直接处理。处理完会推送通知你。',
                style: theme.textTheme.bodySmall),
          ],
        ]),
      ),
    );
  }

  Widget _raiseAskCard(Order order) {
    final want = order.goodsRaiseCents ?? 0;
    final over = want - order.goodsBudgetCents;
    return Card(
      color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.08),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('骑手问你:要多花点钱吗',
              style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          Text('你预估 ${yuan(order.goodsBudgetCents)},'
              '实际要 ${yuan(want)}(多 ${yuan(over)})。'),
          const SizedBox(height: 4),
          Text('同意 → 骑手照买,差额之后跟你结;'
              '不同意 → 按买不到处理,商品款全额退你,'
              '跑腿费只收骑手到店那一段的距离费。',
              style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: OutlinedButton(
                onPressed: () => _decideRaise(order, false),
                child: const Text('不同意'),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: FilledButton(
                onPressed: () => _decideRaise(order, true),
                child: Text('同意,花到 ${yuan(want)}'),
              ),
            ),
          ]),
        ]),
      ),
    );
  }

  /// 小票。**商品款平台一分不抽**,按小票实付结给骑手 ——
  /// 这句话只有在你能看到小票时才成立,所以它必须在这一页上。
  Widget _receiptCard(Order order) {
    final actual = order.goodsActualCents ?? 0;
    final diff = actual - order.goodsBudgetCents;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('小票', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 6),
          Text('你预估 ${yuan(order.goodsBudgetCents)} · '
              '小票实付 ${yuan(actual)}'),
          if (diff < 0)
            Text('少花了 ${yuan(-diff)},已原路退给你',
                style: TextStyle(color: Theme.of(context).sz.earn)),
          if (diff > 0)
            Text('多花了 ${yuan(diff)}',
                style: TextStyle(color: Theme.of(context).sz.hold)),
          const SizedBox(height: 4),
          Text('商品款平台一分不抽,按小票实付结给骑手',
              style: Theme.of(context).textTheme.bodySmall),
          if (order.goodsReceiptUrl.isNotEmpty) ...[
            const SizedBox(height: 10),
            // 点开能放大 —— 小票上的字本来就小,缩在卡片里等于没给看
            InkWell(
              onTap: () => showDialog<void>(
                context: context,
                builder: (_) => Dialog(
                  backgroundColor: Colors.transparent,
                  child: InteractiveViewer(
                      child: Image(
                          image: szNetImage(widget.api
                              .resolveUrl(order.goodsReceiptUrl)))),
                ),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image(
                    image: szNetImage(
                        widget.api.resolveUrl(order.goodsReceiptUrl)),
                    fit: BoxFit.cover),
              ),
            ),
          ],
        ]),
      ),
    );
  }

  Future<void> _decideRaise(Order order, bool agree) async {
    try {
      await widget.api.decideRaise(order.orderNo, agree);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(agree ? '已告诉骑手可以买' : '已告诉骑手不用买了')));
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final order = _order;
    return SzPageScaffold(
      appBar: AppBar(title: const Text('订单详情')),
      body: order == null
          ? (_error != null
              // 加载失败要给得出去也回得来:原来这里只有一个转圈
              ? SzError(
                  error: _error,
                  onRetry: () {
                    setState(() => _error = null);
                    _refresh();
                  })
              : const Center(child: CircularProgressIndicator()))
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
                // 待支付:这一页最重要的动作就是付款,排在所有卡片之前。
                // 没有这个入口的时候,跑腿单进来只能干看着,15 分钟后自动作废
                if (order.status == OrderStatus.pendingPayment)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: FilledButton(
                      onPressed: () async {
                        final paid =
                            await payPendingOrder(widget.api, order, context);
                        if (paid != null && mounted) await _refresh();
                      },
                      child: Text('去支付 ${yuan(order.totalCents)}'),
                    ),
                  ),
                if (_foodSafety != null) ...[
                  _foodSafetyCard(_foodSafety!),
                  const SizedBox(height: 8),
                ],
                // 帮买:骑手问「要多花钱吗」。**这个卡必须排在最前面** ——
                // 骑手正站在货架前等回复,埋在页面下半段等于让他一直站着
                if (order.isErrandBuy && order.goodsRaiseStatus == 'pending')
                  _raiseAskCard(order),
                // 帮买:小票。代买最容易起的纠纷是「你是不是多报了」,
                // 把小票摊开这个纠纷根本不会发生
                if (order.isErrandBuy && order.goodsActualCents != null)
                  _receiptCard(order),
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
                        // 自取单的用户是要**自己走过去**的,一行文字地址不够用。
                        // 商家没上报坐标时不显示按钮 —— 给一个点了会导到
                        // (0,0) 的按钮,比不给更糟
                        if (order.merchantLat != null &&
                            order.merchantLng != null)
                          TextButton.icon(
                            icon: const Icon(Icons.navigation_outlined,
                                size: 16),
                            label: const Text('导航去店里'),
                            onPressed: () => navigateTo(context,
                                lat: order.merchantLat!,
                                lng: order.merchantLng!,
                                name: order.merchantName,
                                mode: NavMode.walk),
                          ),
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
                              builder: (context, setState) => SzDialog(
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
                          builder: (context) => SzDialog(
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
                                child: Image(image: szNetImage(order.deliveryPhotoUrl)))),
                        child: const Text('查看照片')),
                  ]),
                ],
                // 联系骑手/商家(配送中显性化)
                if (order.status.index >= OrderStatus.paid.index &&
                    order.status != OrderStatus.cancelled)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Column(children: [
                      // 未读提醒。以前骑手/商家发消息用户这边一点动静都没有,
                      // 只能靠自己想起来点进去看
                      if (_unread > 0)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 6),
                          child: Row(children: [
                            Icon(Icons.mark_chat_unread_outlined,
                                size: 16,
                                color: Theme.of(context).colorScheme.primary),
                            const SizedBox(width: 6),
                            Text('有 $_unread 条新消息',
                                style: TextStyle(
                                    fontSize: 12.5,
                                    fontWeight: FontWeight.w600,
                                    color:
                                        Theme.of(context).colorScheme.primary)),
                          ]),
                        ),
                      Row(
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
                        if (order.riderId != null && !order.isErrand)
                          const SizedBox(width: 8),
                        // 跑腿单没有商家。这个按钮留着会把人引到
                        // 「本城跑腿服务」那个虚拟主体的聊天窗 ——
                        // 那头没有人,发出去的消息永远没有回音
                        if (!order.isErrand)
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
                    ]),
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
                  // 下单前看得到、下单后看不到,等于没说清楚 ——
                  // 顾客回头质疑"为什么这单贵两块"时,拆分要还在这里。
                  // 读的是下单那一刻的快照,不按现在的费率重算
                  subtitle: order.feeParts.isEmpty
                      ? null
                      : Text(
                          order.feeParts.entries
                              .where((e) => e.value > 0)
                              .map((e) =>
                                  '${order.feePartLabels[e.key] ?? e.key} '
                                  '${(e.value / 100).toStringAsFixed(2)}')
                              .join(' · '),
                          style: TextStyle(
                              fontSize: 11,
                              color: Theme.of(context).sz.inkMuted)),
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
                  _MoneyFlowCard(order: order, api: widget.api),
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
                          hasMerchant: !order.isErrand,
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
                                        ? Theme.of(context).sz.earn
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
                // 账目透明是一级入口:与「催一下」平级摆着,不藏在页尾
                if (order.commissionCents > 0)
                  OutlinedButton.icon(
                    icon: const Icon(Icons.pie_chart_outline, size: 18),
                    onPressed: () => Navigator.of(context).push(
                        MaterialPageRoute(
                            builder: (_) => MoneyFlowPage(
                                api: widget.api, order: order))),
                    label: const Text('钱去哪了'),
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
        builder: (context) => SzDialog(
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
            tooltip: '评分',
            visualDensity: VisualDensity.compact,
            icon: Icon(
              i <= value ? Icons.star : Icons.star_border,
              color: Theme.of(context).sz.hold,
            ),
            onPressed: () => onChanged(i),
          ),
      ],
    );
  }
}

class _ReviewForm extends StatefulWidget {
  const _ReviewForm(
      {required this.hasRider,
      required this.hasMerchant,
      required this.api,
      required this.onSubmit});

  final bool hasRider;

  /// 跑腿单没有商家(merchant_id 指向虚拟服务主体)。
  /// 让人给一个不存在的经营者打星,打完还进不了任何人的看板
  final bool hasMerchant;
  final ApiClient api;
  final Future<void> Function(
      int merchantRating,
      int? riderRating,
      String comment,
      List<String> imageUrls,
      List<String> tags,
      List<String> riderTags,
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
  // 配送标签单独收:配送是平台的事,这组标签只挂骑手评分,不进商家维度
  final Set<String> _riderTags = {};
  bool _anonymous = false; // 真匿名:商家侧完全不可反查
  bool _uploading = false;
  bool _busy = false;

  /// 图评是最有说服力的口碑,选图直接上传(最多 3 张)
  Future<void> _pickImage() async {
    if (!await PermissionRationale.ensure(context, AppPermissionKind.photos)) {
      return;
    }
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 1280, imageQuality: 85);
    if (picked == null) return;
    setState(() => _uploading = true);
    try {
      final url = await widget.api
          .uploadImage(await picked.readAsBytes(), picked.name,
              purpose: 'review');
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
            if (widget.hasMerchant) ...[
              Row(children: [
                const Text('商家'),
                _Stars(
                    value: _merchantRating,
                    onChanged: (v) => setState(() => _merchantRating = v)),
              ]),
              // 商家维度标签(正向 + 负向,归因到商家能改的事)
              Wrap(
                spacing: 6,
                runSpacing: 2,
                children: [
                  for (final tag in [...kReviewTags, ...kMerchantNegTags])
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
            ],
            if (widget.hasRider) ...[
              Row(children: [
                const Text('骑手'),
                _Stars(
                    value: _riderRating,
                    onChanged: (v) => setState(() => _riderRating = v)),
              ]),
              // 配送标签只挂骑手评分:配送由平台负责,
              // 配送原因的反馈不计入商家评分
              Wrap(
                spacing: 6,
                runSpacing: 2,
                children: [
                  for (final tag in kRiderReviewTags)
                    FilterChip(
                      label: Text(tag, style: const TextStyle(fontSize: 12)),
                      selected: _riderTags.contains(tag),
                      visualDensity: VisualDensity.compact,
                      onSelected: (on) => setState(() {
                        if (on && _riderTags.length < 3) {
                          _riderTags.add(tag);
                        } else {
                          _riderTags.remove(tag);
                        }
                      }),
                    ),
                ],
              ),
              Text('配送由平台负责,配送方面的反馈不计入商家评分',
                  style: TextStyle(
                      fontSize: 11, color: Theme.of(context).sz.inkMuted)),
            ],
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
                          child: Image(image: szNetImage(widget.api.resolveUrl(url)),
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
                        // 轻提示(可跳过不强制):给商家打了低分,但选的全是
                        // 配送标签 —— 配送由平台负责,别让商家背骑手的锅
                        if (_merchantRating <= 3 &&
                            _tags.isEmpty &&
                            _riderTags.isNotEmpty) {
                          final go = await showDialog<bool>(
                            context: context,
                            builder: (dialog) => SzDialog(
                              content: const Text(
                                  '你选的都是配送方面的反馈 —— 配送由平台负责,'
                                  '建议低分打给骑手评分,不影响商家。\n'
                                  '当然,如果对商家也不满意,可以直接提交。'),
                              actions: [
                                TextButton(
                                    onPressed: () =>
                                        Navigator.pop(dialog, true),
                                    child: const Text('直接提交')),
                                FilledButton(
                                    onPressed: () =>
                                        Navigator.pop(dialog, false),
                                    child: const Text('回去改一下')),
                              ],
                            ),
                          );
                          if (go != true) return;
                        }
                        setState(() => _busy = true);
                        await widget.onSubmit(
                          _merchantRating,
                          widget.hasRider ? _riderRating : null,
                          _comment.text.trim(),
                          _imageUrls,
                          _tags.toList(),
                          widget.hasRider ? _riderTags.toList() : const [],
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
                style: TextStyle(color: Theme.of(context).sz.hold)),
            if (review.riderRating != null)
              Text('骑手 ${_stars(review.riderRating!)}',
                  style: TextStyle(color: Theme.of(context).sz.hold)),
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
/// 「我的」页。
///
/// ## 分块的依据(#296)
///
/// 改版前是一条从上到下的 ListView:12 个入口挤在一张卡里,高频的
/// (订单、账目)和一年点一次的(注销、协议)靠**位置**区分优先级,
/// 而位置这件事用户扫不出来 —— 真机 390×844 上首屏只看得到 8 个入口,
/// 那张 12 条的大卡首屏只露 1 条。
///
/// 现在自上而下是:风控横幅 → 身份行 → **账目透明卡** → 订单四格 →
/// 卡券网格 → 设置类列表。
///
/// ## 为什么黄金位给账目而不是权益
///
/// 商业平台在这个位置放会员等级。我们不做会员体系(没有补贴预算,
/// 也不靠积分粘人),而**账目透明是这个平台唯一别人抄不走的东西**。
///
/// 这个位置不是新选的:首页那条 5% 承诺条可以被用户永久关掉,
/// 而关掉它的前提写在 `_promiseStrip` 的注释里 ——
/// 「关掉不影响任何功能:『我的 → 这钱怎么算的』一直在」。
/// 那句话早就把「我的」页指定成账目透明的常驻入口了,这里只是兑现它。
///
/// 顺带:账目三个入口**游客也能用**(`openMoneyFlow` 拉不到订单时回落
/// 说明弹层,信任页走公开接口),所以它也是未登录首屏唯一不发灰的块。
class ProfileView extends StatefulWidget {
  const ProfileView({super.key, required this.api, this.onOpenOrders});

  final ApiClient api;

  /// 点订单四格时切到订单 tab 并带上筛选。
  ///
  /// 为什么是回调不是 push:`_tab` 在外壳的 State 里,这一页够不着;
  /// 而 push 一个新的订单列表页会造出第二个订单列表,
  /// 返回行为和底部 tab 不一致。null = 没接外壳(测试里),按钮仍可点但不跳
  final void Function(OrderFilter filter, {int segment})? onOpenOrders;

  @override
  State<ProfileView> createState() => _ProfileViewState();
}

class _ProfileViewState extends State<ProfileView> {
  UserProfile? _profile;
  // 营销总开关(服务端 /config):关着时邀请有礼等入口整体隐藏
  bool _marketingOn = false;

  /// 订单四格的角标数据源。**只用已拉到的这一页算。**
  ///
  /// 服务端按 created_at desc 排、一页 20 条,而待支付/进行中的单必然是
  /// 最新的那批 —— 所以从第一页数出来的数字,对任何「同时未完结订单
  /// 少于 20」的用户都是准的。超过 20 的极端情况在角标上显示「20+」,
  /// 不假装知道确切数(见 SzIconGrid)。
  ///
  /// 这里**没有**旧版那个「累计优惠 / 已完成订单」三格数字卡:
  /// 它拿同一个 limit=20 的列表算「累计」,第 21 单之后就是错的,
  /// 而且错得悄无声息。要找回来的话得服务端算,不该在入口页上。
  List<Order> _orders = const [];
  List<StayOrder> _stays = const [];

  /// 顶上那张账目卡关掉了没有。**默认不关,关了就永久关。**
  ///
  /// 和首页 `_promiseStrip` 同一个道理:「5% 平台只抽这么多」是一句宣言,
  /// 老用户看过一次就够,天天顶在页首就从"我们不黑你"变成了打扰。
  ///
  /// ⚠️ 但**关法不一样**。首页那条敢整条消失,是因为它的注释里写着
  /// 「『我的 → 这钱怎么算的』一直在」—— 它敢消失是因为这张卡兜着。
  /// 这张卡是终点站:平台账本除了这里只有分账页里那一个入口,
  /// 平台体检更是只有平台账本里那一个。承诺条关掉 + 这张卡也关掉 +
  /// 一单没下过,这两页就从 App 里彻底没了。
  ///
  /// 所以这里**关掉的是卡,不是入口**:卡收起的同时,
  /// 三条入口落到 [_entryList] 里(见那儿的 `if (_ledgerHidden)`)。
  bool _ledgerHidden = false;

  static const _kLedgerHidden = 'profile_ledger_hidden';

  @override
  void initState() {
    super.initState();
    authTick.addListener(_load); // 游客登录成功后刷新
    _load();
    _restoreLedger();
  }

  Future<void> _restoreLedger() async {
    final sp = await SharedPreferences.getInstance();
    if (!mounted) return;
    setState(() => _ledgerHidden = sp.getBool(_kLedgerHidden) ?? false);
  }

  Future<void> _hideLedger() async {
    setState(() => _ledgerHidden = true);
    final sp = await SharedPreferences.getInstance();
    await sp.setBool(_kLedgerHidden, true);
    if (!mounted) return;
    // 说清楚去哪还能看到 —— 不说的话用户以为这几个入口没了
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
      content: Text('已收起。钱去哪了 / 平台账本 / 平台体检 已移到本页下方的设置里'),
      duration: Duration(seconds: 4),
    ));
  }

  @override
  void dispose() {
    authTick.removeListener(_load);
    super.dispose();
  }

  Future<void> _load() async {
    // 四块数据并发拉。**先把 Future 全发出去再逐个 await** ——
    // 串行的话进「我的」要连等四个来回才看得全
    final loggedIn = widget.api.isLoggedIn;
    final profileF = loggedIn ? widget.api.me() : null;
    final configF = widget.api.platformConfig();
    final ordersF = loggedIn ? widget.api.myOrders() : null;
    // 住宿单单独一个接口(和外卖是两套平行的竖井)。多这一个来回是为了
    // 待支付角标能把住宿算进去 —— 住宿的待支付单 15 分钟不付就自动关闭,
    // 角标漏数它是用户真金白银的损失
    final staysF = loggedIn ? widget.api.myStayOrders() : null;
    if (profileF != null) {
      try {
        final profile = await profileF;
        if (mounted) setState(() => _profile = profile);
      } catch (_) {}
    } else if (mounted) {
      setState(() => _profile = null);
    }
    try {
      final config = await configF;
      if (mounted) {
        setState(() => _marketingOn = config['marketing'] == true);
      }
    } catch (_) {}
    if (ordersF != null) {
      try {
        final orders = await ordersF;
        if (mounted) setState(() => _orders = orders);
      } catch (_) {}
    } else if (mounted) {
      setState(() => _orders = const []);
    }
    if (staysF != null) {
      try {
        final stays = await staysF;
        if (mounted) setState(() => _stays = stays);
      } catch (_) {}
    } else if (mounted) {
      setState(() => _stays = const []);
    }
  }

  /// 某个筛选下有多少单(外卖 + 住宿)。
  int _count(OrderFilter f) =>
      _orders.where(f.matchesFood).length +
      _stays.where(f.matchesStay).length;

  /// 点这一格该落在哪个频道:哪边有就落哪边,两边都有落外卖。
  int _segmentFor(OrderFilter f) =>
      _orders.where(f.matchesFood).isEmpty &&
              _stays.where(f.matchesStay).isNotEmpty
          ? 1
          : 0;

  void _openOrders(OrderFilter f) =>
      widget.onOpenOrders?.call(f, segment: _segmentFor(f));

  Future<void> _editBirthdayAndPush() async {
    final me = _profile ?? await widget.api.me();
    if (!mounted) return;
    final birthday = TextEditingController(text: me.birthday);
    var push = me.marketingPush;
    await showDialog<void>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setState) => SzDialog(
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
    if (!await PermissionRationale.ensure(context, AppPermissionKind.photos,
        reason: '用于选取头像图片并上传。\n拒绝不影响其他功能。')) {
      return;
    }
    final picked = await ImagePicker().pickImage(
        source: ImageSource.gallery, maxWidth: 512, imageQuality: 85);
    if (picked == null) return;
    try {
      final url = await widget.api
          .uploadImage(await picked.readAsBytes(), picked.name,
              purpose: 'avatar');
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
      builder: (context) => SzDialog(
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
      builder: (context) => SzDialog(
        title: const Text('开发票'),
        content: const Text(
            '电子发票功能将在接入微信支付后开放。\n\n'
            '现阶段如需发票,请直接联系商家或平台客服,'
            '我们会协助你完成开票。',
            style: TextStyle(height: 1.6)),
        actions: [
          TextButton(
              onPressed: () async {
                Navigator.pop(context);
                if (!await ensureLoggedIn(this.context)) return;
                if (!mounted) return;
                await Navigator.of(this.context).push(MaterialPageRoute(
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
    final profile = _profile;
    final guest = !widget.api.isLoggedIn;
    // 营销入口的闸门:总开关开着、已登录、**而且账号没被风控限制**。
    // 少最后一条的话,「营销权益暂被限制」的账号照样能点进邀请有礼 ——
    // 要么那个处置是假的,要么用户点进去才发现是死路。
    //
    // 要求 profile 非空是为了别闪:加载中先显示、拿到 risk_level 再收回去,
    // 比一直不显示更糟
    final marketing =
        _marketingOn && !guest && profile != null && profile.riskLevel.isEmpty;
    return ListView(
      padding: const EdgeInsets.all(16),
      // 块与块之间只留白,**不画分隔线** —— 卡片自己的 1px 描边已经在分区了,
      // 再加横线就是同一件事说两遍
      children: [
        if (profile != null && profile.riskLevel.isNotEmpty) ...[
          _riskBanner(context, profile),
          const SizedBox(height: 12),
        ],
        guest ? _loginCard(context) : _identityRow(context, profile),
        const SizedBox(height: 12),
        // 关掉之后连同它的间距一起消失 —— 留一个 12px 的空档
        // 就是"关了但还占着位"
        if (!_ledgerHidden) ...[
          _ledgerCard(context),
          const SizedBox(height: 12),
        ],
        // 游客不渲染订单区:四个 0 角标的格子就是灰占位,
        // 而订单 tab 自己已经有登录引导了
        if (!guest) ...[
          _ordersCard(context),
          const SizedBox(height: 12),
        ],
        _quickGrid(context),
        _serviceGrid(context),
        const SizedBox(height: 12),
        _entryList(context, marketing: marketing),
      ],
    );
  }

  /// 反作弊处置提示(可见 + 可申诉):绝不静默处罚。
  ///
  /// **一分不缩。** 这是「到点就自动出事」的提醒,不是装饰性横幅 ——
  /// 密度改造不许拿它开刀
  Widget _riskBanner(BuildContext context, UserProfile profile) {
    final theme = Theme.of(context);
    return Card(
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
                prefill: '对账号限制有疑问,申请复核:${profile.riskNote}'))),
      ),
    );
  }

  /// 游客态:登录/注册占位卡,不请求任何个人接口。
  Widget _loginCard(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: ListTile(
        leading:
            const CircleAvatar(radius: 26, child: Icon(Icons.person_outline)),
        title: Text('登录 / 注册', style: theme.textTheme.titleLarge),
        subtitle: const Text('登录后查看订单、收藏与优惠券'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => ensureLoggedIn(context),
      ),
    );
  }

  /// 身份行:头像(点=换头像)+ 昵称(点=改昵称)+ 手机号。
  Widget _identityRow(BuildContext context, UserProfile? profile) {
    final theme = Theme.of(context);
    return Card(
      child: ListTile(
        // 自己的头像:缺图时也用 SzImage(名字首字),但压一个相机角标
        // 保住"点这里换头像"的提示——这里要的是促使补图,不只是好看
        leading: InkWell(
          onTap: _pickAvatar,
          borderRadius: BorderRadius.circular(26),
          child: Stack(clipBehavior: Clip.none, children: [
            SzImage(
                url: profile == null || profile.avatarUrl.isEmpty
                    ? ''
                    : widget.api.resolveUrl(profile.avatarUrl),
                name: profile?.name ?? widget.api.userName ?? '我',
                size: 52,
                circle: true),
            Positioned(
              right: -2,
              bottom: -2,
              child: Container(
                padding: const EdgeInsets.all(3),
                decoration: BoxDecoration(
                  color: theme.sz.surface,
                  shape: BoxShape.circle,
                  border: Border.all(color: theme.sz.line),
                ),
                child: Icon(Icons.photo_camera_outlined,
                    size: 11, color: theme.sz.inkMuted),
              ),
            ),
          ]),
        ),
        // 首帧用会话里缓存的昵称/手机号,**不要拿默认值或口号顶上** ——
        // 「感谢你支持劳动者互助平台」占在手机号的位置上,接口一回来
        // 闪成真号,用户看到的是"先给我看了个别的,然后偷偷换掉了"。
        // 缓存里也没有(极少见:刚装且还没登录成功过)时留空,
        // 空白至少是诚实的
        title: Text(profile?.name ?? widget.api.userName ?? '',
            style: theme.textTheme.titleLarge),
        subtitle: Text(profile?.phone ?? widget.api.userPhone ?? ''),
        trailing: const Icon(Icons.edit, size: 18),
        onTap: _editName,
      ),
    );
  }

  /// 账目透明卡 —— 这一页的黄金位。
  ///
  /// 商业平台在这个位置放会员等级和成长值。我们放这个,因为**它才是
  /// 这个平台要用户记住的东西**,而它此前埋在一串列表里的第五块。
  ///
  /// 卡里**只放入口,不放数字**。不是为了省事:旧版那张「累计优惠 /
  /// 已完成订单」的三格数字卡拿 limit=20 的订单列表算「累计」,
  /// 第 21 单之后就是错的。一个把账目透明当立身之本的平台,
  /// 顶上挂两个静悄悄算错的数字,比不显示糟得多。
  Widget _ledgerCard(BuildContext context) {
    final sz = Theme.of(context).sz;
    Widget entry(String label, VoidCallback onTap, {bool last = false}) =>
        Expanded(
          child: Padding(
            padding: EdgeInsets.only(right: last ? 0 : 8),
            child: Material(
              color: sz.surface,
              borderRadius: BorderRadius.circular(kRadiusSm),
              child: InkWell(
                onTap: onTap,
                borderRadius: BorderRadius.circular(kRadiusSm),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 9),
                  child: Text(label,
                      maxLines: 2,
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: kFontNote,
                          height: 1.2,
                          fontWeight: FontWeight.w500,
                          color: sz.ink)),
                ),
              ),
            ),
          ),
        );

    return Container(
      // 全页唯一一张有色卡:和首页那条 5% 承诺条同一套视觉语言,
      // 「这两处说的是同一件事」不用写出来
      decoration: BoxDecoration(
        color: sz.claySoft,
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      padding: const EdgeInsets.all(kCardPad),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            // 标题两截仍按基线对齐(衬线的 5% 和黑体的中文各有各的字高),
            // 所以关闭键**不能进这个 Row** —— 一个没有基线的盒子塞进
            // baseline 行里,对齐会退化成按顶边排
            Expanded(
              child: Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Text('5%',
                        style: szFigure(
                            fontSize: 20,
                            fontWeight: FontWeight.w600,
                            color: sz.clay)),
                    const SizedBox(width: 8),
                    Text('平台只抽这么多',
                        style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: sz.ink)),
                  ]),
            ),
            // 关闭:热区做到 40×40(图标只有 16,光按图标点不中),
            // 和首页承诺条同一套尺寸。
            //
            // **不用 OverflowBox 去省那 16px 高。** 试过:画出来是 40×40,
            // 但父级 SizedBox 只有 24 高,命中测试在它那儿就被挡掉了 ——
            // 量尺寸的断言照样绿,手指点上去只有 40×24 管用。
            // 高度的账在卡的内边距上找补(见 padding)
            Semantics(
              label: '不再显示这张账目卡',
              button: true,
              child: InkWell(
                borderRadius: BorderRadius.circular(20),
                onTap: _hideLedger,
                child: SizedBox(
                  width: 40,
                  height: 40,
                  child: Icon(Icons.close, size: 16, color: sz.inkMuted),
                ),
              ),
            ),
          ]),
          const SizedBox(height: 4),
          // 立场整卡说一次,不摊到每个入口上(同 SzEntryGroup.footnote 的规矩)
          Text('每一单的钱去了哪里,平台的账本长什么样,都查得到',
              style: TextStyle(
                  fontSize: kFontNote, height: 1.4, color: sz.inkMuted)),
          const SizedBox(height: 12),
          Row(children: [
            entry('钱去哪了', () => openMoneyFlow(context, widget.api)),
            entry(
                '平台账本',
                () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => TrustPage(api: widget.api)))),
            // 直达入口:这一页是我们和三大平台唯一的结构性差别,
            // 不该只藏在信任页里点两层才看得到
            entry(
                '平台体检',
                () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => TransparencyPage(api: widget.api))),
                last: true),
          ]),
        ],
      ),
    );
  }

  /// 订单四格:按状态直达。
  ///
  /// 底部的「订单」tab 是全部订单的入口,这里给的是**分流 + 数字**。
  /// 角标是这一块存在的全部理由 —— 没有数字的四个格子只是四个
  /// 通往同一个列表的重复入口。
  Widget _ordersCard(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Card(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        InkWell(
          onTap: () => _openOrders(OrderFilter.all),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(kCardPad, 12, 8, 0),
            child: Row(children: [
              Text('我的订单',
                  style: TextStyle(
                      fontSize: kFontBodyLg,
                      fontWeight: FontWeight.w600,
                      color: sz.ink)),
              const Spacer(),
              Text('全部订单',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              Icon(Icons.chevron_right, size: 16, color: sz.inkFaint),
            ]),
          ),
        ),
        SzIconGrid(items: [
          for (final (icon, filter) in [
            (Icons.account_balance_wallet_outlined, OrderFilter.pendingPayment),
            (Icons.local_shipping_outlined, OrderFilter.active),
            (Icons.rate_review_outlined, OrderFilter.toReview),
            (Icons.assignment_return_outlined, OrderFilter.refund),
          ])
            SzIconGridItem(
              icon: icon,
              label: filter.label,
              badge: filter.badged ? _count(filter) : 0,
              onTap: () => _openOrders(filter),
            ),
        ]),
      ]),
    );
  }

  /// 卡券与常用:四个平级入口,标题两三个字,给不出状态值 —— 网格档。
  ///
  /// 每格 23px,同样四条排成列表要 184px。收货地址在这里留一份,
  /// 所以「我的」tab 的 AppBar 才腾得出位置给客服和设置
  Widget _quickGrid(BuildContext context) {
    return Card(
      child: SzIconGrid(items: [
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
          SzIconGridItem(
            icon: icon,
            label: label,
            onTap: () async {
              if (!await ensureLoggedIn(context)) return;
              if (!context.mounted) return;
              await Navigator.of(context)
                  .push(MaterialPageRoute(builder: (_) => page()));
            },
          ),
      ]),
    );
  }

  /// 找平台的四类事 + 查账的三个入口:全部横过来。
  ///
  /// ## 为什么这几条该是网格而不是列表条
  ///
  /// 判据没变,还是 `SzIconGrid` 文档里那条:**标题两三个字就说清、
  /// 彼此完全平级、给不出状态值**。这六条正好全中 ——
  /// 「帮助中心」「意见反馈」「平台账本」都是一看就懂的名词,
  /// 没有"当前是什么值"可言,也不需要一句解释。
  ///
  /// 排成竖列的代价是每条 46px 只放三四个字。横过来之后
  /// **六条 ≈ 100px,原来要 276px**。
  ///
  /// ## 分成两行,不是拼成一行
  ///
  /// 前三条是「找人」(问、说、查自己的投诉),后三条是「查账」。
  /// 挤成一行六格的话,每格在 375px 屏上只剩 57px —— 四个字要折两行,
  /// 而且两类事混在一起,扫一眼分不出哪三个是一伙的。
  ///
  /// 一行三个是刻意的:格子宽 114px,四个字一行放得下,
  /// 两组之间天然断开,不用加分组头(那要 41px)。
  Widget _serviceGrid(BuildContext context) {
    Future<void> guarded(Widget Function() page) async {
      if (!await ensureLoggedIn(context)) return;
      if (!context.mounted) return;
      await Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => page()));
    }

    return Card(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        SzIconGrid(items: [
          SzIconGridItem(
            icon: Icons.help_outline,
            label: '帮助中心',
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
                builder: (_) => HelpCenterPage(api: widget.api))),
          ),
          SzIconGridItem(
            icon: Icons.rate_review_outlined,
            label: '意见反馈',
            onTap: () => guarded(() => FeedbackPage(api: widget.api)),
          ),
          // 食安投诉查得到进度,投诉才不是黑洞。
          // 标签里的「我的」说明是查自己的,别省 —— 省了就像个投诉入口,
          // 而这里是**看自己投诉办到哪一步**
          SzIconGridItem(
            icon: Icons.health_and_safety_outlined,
            label: '我的食安投诉',
            onTap: () => guarded(() => FoodSafetyRecordsPage(api: widget.api)),
          ),
        ]),
        // 账目卡收起时,它的三个入口落在这儿。**只在收起时出现** ——
        // 卡开着还挂一份就是同一个入口在一页上出现两次。
        //
        // 这不是"顺手也放一份",是这张卡能被关掉的前提:平台账本除了那张卡
        // 只有分账页里一个入口,平台体检更是只有平台账本里一个,
        // 而分账页要么从首页那条(也能关)进、要么得先有一笔带佣金的订单。
        // 少了这一段,关卡片 = 删功能
        if (_ledgerHidden) ...[
          const Divider(height: 1),
          SzIconGrid(items: [
            SzIconGridItem(
              icon: Icons.pie_chart_outline,
              label: '钱去哪了',
              onTap: () => openMoneyFlow(context, widget.api),
            ),
            SzIconGridItem(
              icon: Icons.account_balance_outlined,
              label: '平台账本',
              onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => TrustPage(api: widget.api))),
            ),
            SzIconGridItem(
              icon: Icons.monitor_heart_outlined,
              label: '平台体检',
              onTap: () => Navigator.of(context).push(MaterialPageRoute(
                  builder: (_) => TransparencyPage(api: widget.api))),
            ),
          ]),
        ],
      ]),
    );
  }

  /// 设置类列表:需要一句说明、或者有状态值可显示的入口。
  ///
  /// **一张卡,不加分组头。** 分组头 41px、脚注 23px —— 上面三张卡的
  /// 卡片边界已经把结构表达完了,再加两个分组头就是白付 82px
  /// (这一课记在 `entry_tile_test.dart` 里:第一版改造正是栽在这儿)。
  ///
  /// 长辈版排第一是刻意的:它是全页唯一一个**目标用户就是看不清这一页**
  /// 的入口。埋在第三张卡中间,或者收进右上角那个没有文字标签的齿轮里,
  /// 等于对这批人关门。它 72px 很贵,但那 72px 买的是 Switch 的 48px
  /// 触控区 —— 给这批人缩触控区是本末倒置。
  Future<void> _openIdentity() async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    await Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => IdentityPage(api: widget.api)));
  }

  Widget _entryList(BuildContext context, {required bool marketing}) {
    return Card(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        // 长辈版:大字模式,方便老人和视障用户;尊重系统字体缩放。
        // 开关类入口:trailing 给 Switch,整行可点也切换。
        // 「放大全局字号」这句留着 —— 老人要的正是这个确认
        ValueListenableBuilder<bool>(
          valueListenable: elderMode,
          builder: (context, elder, _) => SzEntryTile(
            icon: Icons.text_fields,
            title: '长辈版(大字模式)',
            hint: '放大全局字号,看得更清楚',
            trailing: Switch(value: elder, onChanged: (v) => setElderMode(v)),
            onTap: () => setElderMode(!elder),
          ),
        ),
        const Divider(height: 1),
        // 账号相关三个入口:横过来 + 一句合并的脚注。
        //
        // ## 有说明、有状态值的怎么也能进网格
        //
        // 前一版把「有 hint 或有 value」一律判成不能进网格,判死了。
        // 两样都能安置:
        //
        // - **说明合进脚注**。三条各挂一句 hint 是 3×17px,而这几句说的
        //   其实是同一件事(账号能干什么)—— 合成一段 footnote,
        //   一次说完,还更连贯;
        // - **状态值收进弹窗**。「生日与推送」点开本来就是个弹窗
        //   (`_editBirthdayAndPush`,里面有生日输入框和推送开关),
        //   行上那个「已开启」只是省下一次点击。而这是**设置一次就不管**
        //   的偏好,不是每次进页面都要确认的东西 —— 用一整行换那一眼,
        //   不划算。
        //
        // 三条 63+63+46=172px → 网格 82px + 脚注两行 28px。
        if (marketing) ...[
          SzIconGrid(items: [
            SzIconGridItem(
              icon: Icons.verified_user_outlined,
              label: '实名认证',
              onTap: _openIdentity,
            ),
            SzIconGridItem(
              icon: Icons.card_giftcard_outlined,
              label: '邀请有礼',
              onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(builder: (_) => InvitePage(api: widget.api))),
            ),
            SzIconGridItem(
              icon: Icons.cake_outlined,
              label: '生日与推送',
              onTap: _editBirthdayAndPush,
            ),
          ]),
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 0, 14, 10),
            child: Text(
              '实名后才能买酒类等受限商品;邀请好友完成首单,你俩各得券;'
              '生日当天送券,营销推送可随时关掉(订单通知不受影响)。',
              style: TextStyle(
                  fontSize: kFontMicro, color: Theme.of(context).sz.inkMuted),
            ),
          ),
        ] else
          // 关掉营销时只剩实名一条 —— 一格网格是三分之一宽的孤格,
          // 不如老老实实一条列表条,说明也留在原位
          SzEntryTile(
            icon: Icons.verified_user_outlined,
            title: '实名认证',
            hint: '购买酒类等受限商品需先实名',
            onTap: _openIdentity,
          ),
        const Divider(height: 1),
        // 旧版的 hint 是「配送范围 / 退款规则 / 常见问题」—— 那是一份目录,
        // 目的页自己会答。入口列表回答「这是什么」就够了
        // 点进去只会说「接入微信支付后开放」—— 那就把答案摆在行上,
        // 用户不用点就知道。`value:` 槽位最正当的用法之一:
        // 把一次注定落空的跳转换成同一行的一个词
        SzEntryTile(
          icon: Icons.receipt_outlined,
          title: '开发票',
          value: '暂未开放',
          onTap: _showInvoiceInfo,
        ),
        const Divider(height: 1),
        // 商店审核要求:我的页可达协议全文。
        // 设置页里也有一份,但合规项上「2 跳可达算不算可达」是拿被打回
        // 赌的,46px 不值这个风险 —— 留着
        SzEntryTile(
          icon: Icons.description_outlined,
          title: '用户协议与隐私政策',
          onTap: () => showLegalSheet(context),
        ),
      ]),
    );
  }
}

/// 我的收藏:店铺列表,点进店铺页。
class FavoritesPage extends StatefulWidget {
  const FavoritesPage({super.key, required this.api});

  final ApiClient api;

  @override
  State<FavoritesPage> createState() => _FavoritesPageState();
}

class _FavoritesPageState extends State<FavoritesPage> {
  // 收藏页原来直接在 build 里 api.favorites():每次 rebuild 都重新请求,
  // 而且加载失败没有重试出口。改成持有 future,重试就是换一个 future
  late Future<List<Merchant>> _future = widget.api.favorites();
  ApiClient get api => widget.api;

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: const Text('我的收藏')),
      body: FutureBuilder(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return SzError(
                error: snapshot.error,
                onRetry: () => setState(() => _future = api.favorites()));
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
                leading: SzImage(
                    url: m.logoUrl.isEmpty ? '' : api.resolveUrl(m.logoUrl),
                    name: m.name,
                    size: 44,
                    categoryIcon: merchantCategoryIcon(m.category)),
                title: Text(m.name),
                // 明厨亮灶标识:收藏也是商家列表页面 ——
                // 法规要求的不是"首页那一个列表",漏掉的那个就是合规缺口
                subtitle: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text('${m.ratingLabel}${m.isOpen ? "" : " · 休息中"}'),
                    SzKitchenCamChip(
                        has: m.kitchenCam,
                        label: m.kitchenCamLabel,
                        compact: true),
                  ],
                ),
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
    // 还要多久:**用服务端算好的 eta_at**(#295)。
    //
    // 这里原本自己算「直线距离 ÷ 常量速度」,而订单列表卡片用的是
    // order.etaAt(服务端按腾讯骑行路网 + 这家店的实测出餐时间算的)——
    // 同一个订单,列表说「还有 20 分钟」,点进去说「12 分钟内送达」。
    //
    // 打开订单页第一眼只想知道"还要多久",这一眼就得和别处对得上;
    // 拿不到 eta_at 就整行不显示,不自己编一个。
    String? etaText;
    final etaAt = order.etaAt == null
        ? null
        : DateTime.tryParse(order.etaAt!)?.toLocal();
    if (!order.pickup &&
        etaAt != null &&
        order.status.index < OrderStatus.delivered.index) {
      final left = etaAt.difference(DateTime.now()).inMinutes;
      final hhmm = '${etaAt.hour.toString().padLeft(2, '0')}:'
          '${etaAt.minute.toString().padLeft(2, '0')}';
      // 还有多久 + 几点到**都给**,和订单列表卡片同一个口径:
      // 「还有 20 分钟」答的是"我等不等得起",「18:40」答的是
      // "我 7 点出门来不来得及"。超时了就直说超时 ——
      // 「马上就到」喊了二十分钟,比晚到本身更伤人
      etaText = left > 0
          ? '预计还有 $left 分钟送到(约 $hhmm)'
          : (left > -5
              ? '马上就到'
              : '比预计($hhmm)晚了 ${-left} 分钟,骑手还在路上');
    }

    final sz = theme.sz;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // 状态 eyebrow + 一句话大标题:打开订单页第一眼只想知道"还要多久"
        if (etaText != null) ...[
          Text(_mySteps[currentIdx.clamp(0, _mySteps.length - 1)].$2,
              style: TextStyle(
                  fontSize: 11, letterSpacing: 1.2, color: sz.inkMuted)),
          const SizedBox(height: 5),
          Text.rich(
            TextSpan(children: [
              const TextSpan(text: '预计 '),
              TextSpan(
                  text: etaText.replaceAll(RegExp(r'[^0-9]'), ''),
                  style: szFigure(fontSize: 26, fontWeight: FontWeight.w600)),
              const TextSpan(text: ' 分钟内送达'),
            ]),
            style: TextStyle(
                fontSize: 22, fontWeight: FontWeight.w500, color: sz.ink),
          ),
          const SizedBox(height: 16),
        ],
        const SzSectionTitle('进度'),
        const SizedBox(height: 10),
        SzCard(
          child: SzTimeline(steps: [
            for (var i = 0; i < _mySteps.length; i++)
              SzStep(
                _mySteps[i].$2,
                subtitle: _timeOf(_mySteps[i].$1),
                state: currentIdx < 0 || i > currentIdx
                    ? SzStepState.todo
                    : (i == currentIdx ? SzStepState.now : SzStepState.done),
              ),
          ]),
        ),
      ],
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
        return (Icons.check_circle_rounded, '已原路退回你的支付账户', Theme.of(context).sz.earn);
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
          Theme.of(context).sz.hold
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: Theme.of(context).sz.earn.withValues(alpha: .06),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.currency_yuan, size: 18, color: Theme.of(context).sz.earn),
                const SizedBox(width: 8),
                Text('退款 ${yuan(order.refundCents)}',
                    style: theme.textTheme.titleSmall
                        ?.copyWith(color: Theme.of(context).sz.earn)),
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

/// 订单详情里的分账预览:三条 SzMoneyFlow + 一句"点开看完整口径"。
/// 完整版在 MoneyFlowPage(#107),这里只做预览,两处口径同源。
class _MoneyFlowCard extends StatelessWidget {
  const _MoneyFlowCard({required this.order, required this.api});

  final Order order;
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final total = order.totalCents;
    if (total <= 0) return const SizedBox.shrink();
    final riderGot = order.deliveryFeeCents + order.tipCents;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SzSectionTitle('这一单的钱去哪了'),
        const SizedBox(height: 9),
        SzLedgerCard(
          onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => MoneyFlowPage(api: api, order: order))),
          padding:
              const EdgeInsets.symmetric(horizontal: kCardPad, vertical: 2),
          child: SzMoneyFlow(
            whyLabel: '为什么是 5%',
            items: [
              SzFlowItem(
                name: '商家实收',
                amountCents: order.merchantNetCents,
                fraction: order.merchantNetCents / total,
                note: '菜品 + 打包 − 满减,只扣 5% 服务费',
              ),
              if (riderGot > 0)
                SzFlowItem(
                  name: '骑手所得',
                  amountCents: riderGot,
                  fraction: riderGot / total,
                  note: order.tipCents > 0
                      ? '配送费 + 小费 100% 归骑手'
                      : '配送费 100% 归骑手,平台分文不取',
                ),
              SzFlowItem(
                name: '平台留存',
                amountCents: order.commissionCents,
                fraction: order.commissionCents / total,
                note: '服务器、客服与赔付池',
                isHold: true,
                onWhy: () => showFivePercentSheet(context),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Text('点开可看完整分账口径,账目对用户、商家、骑手三方公开。',
            style: TextStyle(fontSize: 11.5, color: sz.inkMuted)),
      ],
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
                child: Image(image: szNetImage(api.resolveUrl(shop.photoUrls[i])),
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
            SzImage(
                url: shop.logoUrl.isEmpty ? '' : api.resolveUrl(shop.logoUrl),
                name: shop.name,
                size: 64,
                categoryIcon: merchantCategoryIcon(shop.category)),
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
        // 证照公示(亮照经营,电商法要求):从"一句话声明"升级为可查验的公示页
        InkWell(
          onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(
              builder: (_) => ShopLicensesPage(
                  api: api, merchantId: shop.id, shopName: shop.name))),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 6),
            child: Row(children: [
              Icon(Icons.verified_outlined,
                  size: 18, color: Theme.of(context).sz.inkMuted),
              const SizedBox(width: 10),
              const Expanded(child: Text('证照信息(平台人工审核)')),
              Icon(Icons.chevron_right,
                  size: 18, color: Theme.of(context).sz.inkMuted),
            ]),
          ),
        ),
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
                    child: Image(image: szNetImage(api.resolveUrl(shop.photoUrls[i])),
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
