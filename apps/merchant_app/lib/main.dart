import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'dish_manage_page.dart';
import 'web_limits_banner.dart';
import 'finance_page.dart';
import 'hotel/hotel_home_page.dart';
import 'license_page.dart';
import 'listen_service.dart';
import 'messages_page.dart';
import 'onboarding.dart';
import 'printer_service.dart';
import 'reviews_page.dart';
import 'rider_track_page.dart';
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
            onAgreed: () async {
              // 同意之后才初始化收集类 SDK。地图 SDK 尤其不能提前:
              // 腾讯的接口是"同意前调用则地图显示为空白",
              // 而且失败是静默的 —— 没异常没日志,只有一块白板
              await PushService.init();
              await agreeAndStart();
            },
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

/// 审核状态门禁:没申请→开店引导页;待审核→进度页;被驳回→原因页;通过→接单页
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

  /// 我能操作的全部门店(单店商家就一个元素)。给顶栏的切店入口用。
  List<Map<String, dynamic>> _shops = const [];

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
      // **先问有哪些店,再问当前这家**。顺序不能反 —— 连锁账号没选门店时
      // /merchants/me 是 404(后端不猜是哪家),先调它会把连锁老板
      // 一路带进"还没开店"的入驻引导页。
      final brand = await widget.api.myBrand();
      final shops =
          ((brand['shops'] as List?) ?? const []).cast<Map<String, dynamic>>();
      if (shops.isNotEmpty) {
        final current = widget.api.shopId;
        // 存的门店已不在可操作范围(被移出品牌/店被划走)就退回第一家,
        // 否则会一直卡在 404
        if (current == null || !shops.any((s) => s['id'] == current)) {
          await widget.api.setShopId(shops.first['id'] as int);
        }
      }
      final shop = shops.isEmpty ? null : await widget.api.myShop();
      if (mounted) {
        setState(() {
          _shops = shops;
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
    // 入驻四态(onboarding.dart):没店→引导页;驳回→原因+回填重提;
    // 待审→进度页(本 Gate 轮询,通过自动切工作台);通过→工作台
    if (shop == null) {
      return OnboardingWelcomePage(api: widget.api, onSubmitted: _load);
    }
    // 连锁:一家新店在审或被驳回,不该把整个总部也挡在门外 ——
    // 那几家正常营业的店还在等着接单
    if (shop.isRejected) {
      return _withShopEscape(
          RejectedShopPage(api: widget.api, shop: shop, onSubmitted: _load),
          shop);
    }
    if (shop.isPending) {
      return _withShopEscape(
          PendingReviewPage(api: widget.api, shop: shop), shop);
    }
    // 业态分叉:同一个 App,登录后按 biz_type 进入不同工作台
    // **key 绑门店 id**:切店时强制换一个 State。
    // 不加的话 Flutter 会复用同一个 State(同类型同位置),initState 不再跑 ——
    // 听单 WebSocket 还连着上一家店、营业开关还是上一家的值,
    // 而屏幕上的店名已经变了。这种错屏商家看不出来。
    if (shop.bizType == 'hotel') {
      return HotelHomePage(
          key: ValueKey('shop-${shop.id}'),
          api: widget.api,
          shop: shop,
          onShopChanged: _load);
    }
    return MerchantHomePage(
      key: ValueKey('shop-${shop.id}'),
      api: widget.api,
      shop: shop,
      // 单店商家传空:工作台据此完全不渲染切店入口,界面与从前一样
      shops: _shops.length > 1 ? _shops : const [],
      onSwitchShop: _switchShop,
    );
  }

  /// 给"在审/被驳回"这类整屏拦截页挂一个切到其他门店的出口。
  /// 单店商家没有其他门店可切,原样返回(界面与从前一字不差)。
  Widget _withShopEscape(Widget page, Merchant shop) {
    final others = _shops
        .where((s) => s['id'] != shop.id && s['status'] == 'approved')
        .toList();
    if (others.isEmpty) return page;
    return Stack(children: [
      page,
      Positioned(
        left: 0,
        right: 0,
        bottom: 24,
        child: Center(
          child: FilledButton.tonalIcon(
            icon: const Icon(Icons.swap_horiz),
            label: Text('切换到其他门店(${others.length} 家在营业)'),
            onPressed: () => _switchShop(others.first['id'] as int),
          ),
        ),
      ),
    ]);
  }

  /// 切店:换 id 后把整个 Gate 重新加载一遍。
  ///
  /// 不做局部刷新是有意的 —— 工作台里挂着上一家店的订单列表、听单
  /// WebSocket、今日营业额,漏掉任何一处就是"切到二店,屏幕上还是总店的
  /// 单",而这种错屏商家完全看不出来。切店是低频动作,重来一次不亏。
  Future<void> _switchShop(int id) async {
    if (id == widget.api.shopId) return;
    await widget.api.setShopId(id);
    if (mounted) setState(() => _loaded = false);
    await _load();
  }
}

class MerchantHomePage extends StatefulWidget {
  const MerchantHomePage({
    super.key,
    required this.api,
    required this.shop,
    this.shops = const [],
    this.onSwitchShop,
  });

  final ApiClient api;
  final Merchant shop;

  /// 连锁:可切换的门店。单店商家为空,顶栏就不出切店入口。
  final List<Map<String, dynamic>> shops;
  final Future<void> Function(int shopId)? onSwitchShop;

  @override
  State<MerchantHomePage> createState() => _MerchantHomePageState();
}

/// 宽屏下每个 tab 的内容限宽。**appBar 和 body 用同一个值**才对得齐。
///
/// `responsive.dart` 的三个常量各有各的内容形态,别按"看着差不多"随手选:
///
/// - 订单 / 菜品是**卡片流** → [kFeedMaxWidth](1080);
/// - 对账要并排放表格和图表 → [kWideMaxWidth](1440);
/// - 店铺是**单列设置页**(一列入口条和开关) → [kContentMaxWidth](720)。
///
/// 店铺页原来跟着订单走 1080:一条 `SzEntryTile` 拉到 1080px,
/// 图标钉在最左、状态值钉在最右,中间隔着一米空白 ——
/// 这就是 `responsive.dart` 类文档里举的那个反例。
double merchantTabMaxWidth(int tab) => switch (tab) {
      2 => kWideMaxWidth,
      3 => kContentMaxWidth,
      _ => kFeedMaxWidth,
    };

class _MerchantHomePageState extends State<MerchantHomePage>
    with WidgetsBindingObserver {
  int _tab = 0;
  int _segment = 0; // 0 待接单 / 1 进行中 / 2 历史
  List<Order> _orders = [];
  late bool _isOpen = widget.shop.isOpen;
  Timer? _timer;
  Timer? _alertTimer;
  Timer? _wsPing;
  WebSocketChannel? _ws;
  bool _wsConnected = false;

  /// 重连节奏。**一次断线只排一次重连** —— 为什么需要这个见 [ReconnectPolicy]
  final _reconnect = ReconnectPolicy();

  /// 排队中的那一个重连定时器。**只能有一个**:
  /// 原来是每次 `Timer(...)` 裸着新建,谁也不认识谁,取消不掉也数不清
  Timer? _reconnectTimer;

  /// App 是不是在前台。**后台时轮询要降频** —— 见 [didChangeAppLifecycleState]。
  bool _foreground = true;

  /// 最后一次**成功**拉到订单列表的时间。null = 从来没成功过
  DateTime? _lastOrdersOkAt;

  /// 最近一次拉取失败的原因;空串 = 上一次是成功的
  String _ordersError = '';

  /// 待接单**单独按状态拉**的那一份。null = 这一轮没拉(窗口没被截断)。
  /// 为什么需要它见 [_pendingInWindow]。
  List<Order>? _pendingFetched;

  // ---------- 「历史」分段的自有分页 ----------
  //
  // 「历史」原本是从 `_orders`(最近 20 单)里过滤出来的,没有翻页。
  // 一家一天 40 单的店,过了午市点「历史」可能一条都没有 ——
  // 而屏幕会说「这一栏没有订单」。名字是「历史」,内容是「最近 20 单的残余」。
  //
  // 这里给它自己的游标。**用游标不用 offset**:翻页期间还在进新单,
  // offset 会漏单或重复(api_client.myOrders 的注释里是同一条理由)。
  final List<Order> _historyMore = [];

  /// 历史最多留 200 条(10 页)。
  ///
  /// `_historyMore` 原本只增不减:商家一直开着 App 反复翻,连锁总部长期
  /// 挂机可能攒到几千条,全在内存里、全参与每帧的 diff(#33 第 5 节遗留)。
  ///
  /// 选上限而不是「切走分段就清空」:清空的话商家翻了五页、切去看一眼
  /// 待接单再回来,五页全没了 —— 那是拿体验换内存。到上限后**明说**
  /// 去哪找更早的,和提现记录那 100 条一个口径(不静默停住)。
  static const _kHistoryMax = 200;
  String? _historyCursor;
  bool _historyLoading = false;
  bool _historyEnd = false;

  // 今日 · 待办卡(工作台第一眼):30 秒一刷,失败保留上次的数
  Map<String, dynamic>? _today;
  Map<String, dynamic>? _todos;
  Timer? _todayTimer;

  // 忙碌模式:高峰压单的中间态(不闭店,ETA 放宽 + 用户端亮"出餐较慢"标)
  late DateTime? _busyUntil = DateTime.tryParse(widget.shop.busyUntil ?? '');

  bool get _busyActive =>
      _busyUntil != null && _busyUntil!.isAfter(DateTime.now().toUtc());

  Future<void> _busySheet() async {
    if (_busyActive) {
      final minutesLeft =
          _busyUntil!.difference(DateTime.now().toUtc()).inMinutes + 1;
      final end = await showDialog<bool>(
        context: context,
        builder: (dialog) => SzDialog(
          title: const Text('忙碌模式生效中'),
          content: Text('还剩约 $minutesLeft 分钟自动恢复。\n'
              '期间新单的预计送达时间已放宽,用户端显示「出餐较慢」。'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialog, false),
                child: const Text('继续忙碌')),
            FilledButton(
                onPressed: () => Navigator.pop(dialog, true),
                child: const Text('提前结束')),
          ],
        ),
      );
      if (end != true) return;
      try {
        final shop = await widget.api.setBusy(off: true);
        if (mounted) {
          setState(() => _busyUntil = DateTime.tryParse(shop.busyUntil ?? ''));
        }
      } catch (e) {
        _snack(e is ApiException ? e.message : '$e');
      }
      return;
    }
    int minutes = 60;
    int extra = 10;
    final ok = await showDialog<bool>(
      context: context,
      builder: (dialog) => StatefulBuilder(
        builder: (dialog, setDialog) => SzDialog(
          title: const Text('开启忙碌模式'),
          content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('高峰压单不用闭店:新单预计送达自动放宽,'
                    '用户下单前就看到「出餐较慢」。到点自动恢复。'),
                const SizedBox(height: 12),
                const Text('忙碌时长'),
                const SizedBox(height: 4),
                SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(value: 30, label: Text('30分')),
                    ButtonSegment(value: 60, label: Text('1小时')),
                    ButtonSegment(value: 120, label: Text('2小时')),
                  ],
                  selected: {minutes},
                  onSelectionChanged: (s) => setDialog(() => minutes = s.first),
                ),
                const SizedBox(height: 12),
                const Text('出餐加时'),
                const SizedBox(height: 4),
                SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(value: 10, label: Text('+10分')),
                    ButtonSegment(value: 15, label: Text('+15分')),
                    ButtonSegment(value: 20, label: Text('+20分')),
                  ],
                  selected: {extra},
                  onSelectionChanged: (s) => setDialog(() => extra = s.first),
                ),
              ]),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dialog, false),
                child: const Text('取消')),
            FilledButton(
                onPressed: () => Navigator.pop(dialog, true),
                child: const Text('开启')),
          ],
        ),
      ),
    );
    if (ok != true) return;
    try {
      final shop =
          await widget.api.setBusy(minutes: minutes, extraMinutes: extra);
      if (mounted) {
        setState(() => _busyUntil = DateTime.tryParse(shop.busyUntil ?? ''));
        _snack('忙碌模式已开启,$minutes 分钟后自动恢复');
      }
    } catch (e) {
      _snack(e is ApiException ? e.message : '$e');
    }
  }

  // 搜单:顾客打电话来查单,翻列表翻不到才需要这个框
  bool _searchMode = false;
  final _searchCtrl = TextEditingController();
  List<Order> _searchResults = [];
  Timer? _searchDebounce;

  bool get _searchActive => _searchMode && _searchCtrl.text.trim().length >= 3;

  void _onSearchChanged(String value) {
    _searchDebounce?.cancel();
    final q = value.trim();
    if (q.length < 3) {
      setState(() => _searchResults = []);
      return;
    }
    _searchDebounce = Timer(const Duration(milliseconds: 400), () async {
      try {
        final results = await widget.api.myOrders(q: q, limit: 50);
        if (mounted && _searchCtrl.text.trim() == q) {
          setState(() => _searchResults = results);
        }
      } catch (_) {/* 搜索失败不打扰,继续输入会重试 */}
    });
  }

  final OrderAnnouncer _announcer = OrderAnnouncer();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      checkForUpdate(context, baseUrl: widget.api.baseUrl, app: 'merchant');
      // 锁屏不丢单三件套:权限引导 → 前台服务 → 语音催单。
      // **只在营业中才起前台服务** —— 见 _syncKeepAlive
      await ListenKeepAlive.ensurePermissions(context);
      await _syncKeepAlive();
    });
    _refresh();
    _refreshToday();
    _restartTimers();
    _connectWs();
  }

  /// 切前后台。
  ///
  /// ## 为什么必须有这个(#291)
  ///
  /// 商家反馈「后台待机发热严重」。查下来是三件事叠在一起:
  ///
  /// 1. `ListenKeepAlive` 的前台服务带 `allowWakeLock: true` ——
  ///    熄屏后 CPU 不休眠(这是**故意的**,不然听不到单);
  /// 2. 三个定时器在后台照常全速跑:15 秒拉一次订单、30 秒拉一次今日统计、
  ///    10 秒查一次要不要催单。**每分钟 6 次网络请求,一整夜不停**;
  /// 3. 这个页面此前**一个生命周期监听都没有**(用户端有 3 处、骑手端 1 处,
  ///    就商家端漏了)。
  ///
  /// CPU 不许休眠 + 每 10 秒一次网络 I/O = 手机一直温着。
  ///
  /// ## 改成什么
  ///
  /// **不动听单能力**:WebSocket 保持连着、前台服务保持、催单语音保持 ——
  /// 那是这个 App 存在的理由。降的是**白烧的那部分**:
  ///
  /// - 订单轮询在后台只在 **WS 断线时**才跑。WS 连着的时候它一条新信息
  ///   都带不来,纯属重复(见 `_restartTimers`);
  /// - 今日统计后台直接停 —— 熄着屏没人看仪表盘数字;
  /// - 回到前台立刻补一次全量刷新,不靠下一个 tick。
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final fg = state == AppLifecycleState.resumed;
    if (fg == _foreground) return;
    _foreground = fg;
    _restartTimers();
    if (fg) {
      // 回前台立刻补齐,别等下一个 tick —— 后台期间可能已经进了新单
      _refresh();
      _refreshToday();
    }
  }

  /// 按前后台重排定时器。
  ///
  /// 三个定时器的取舍各不相同,所以没有"统一降频"这种做法:
  ///
  /// | | 前台 | 后台 | 为什么 |
  /// |---|---|---|---|
  /// | 订单轮询 | 15 秒 | **60 秒,且只在 WS 断线时** | WS 连着时它带不来新信息 |
  /// | 今日统计 | 30 秒 | **停** | 熄着屏没人看仪表盘 |
  /// | 催单语音 | 10 秒 | 10 秒(不动) | 这是商家要听见的东西 |
  void _restartTimers() {
    _timer?.cancel();
    _todayTimer?.cancel();
    _alertTimer?.cancel();

    // 轮询保底:WebSocket 断线期间也不会漏单。
    // 后台拉长到 60 秒,而且 WS 连着就整轮跳过 —— 那时候它是纯重复请求
    _timer = Timer.periodic(Duration(seconds: _foreground ? 15 : 60), (_) {
      if (!_foreground && _wsConnected) return;
      _refresh();
    });

    // 今日统计只在前台刷:后台熄着屏,这几个数字没人看
    if (_foreground) {
      _todayTimer =
          Timer.periodic(const Duration(seconds: 30), (_) => _refreshToday());
    }

    // 持续催单:只要有待接订单,每 10 秒语音播报一次,直到商家处理。
    // **前后台一个节奏,不降频** —— 后台听不见催单等于这个 App 白做
    //
    // ⚠️ 判据走 [_pendingCount],**不是** `_orders.any(paid)`。
    // `_orders` 是 20 条的窗口:午高峰压过 20 单时,更早的未接单掉出窗口,
    // 这里就再也不响了 —— 而那恰恰是商家最需要被叫醒的时候。
    // 催单语音是漏单的最后一道防线,它的判据必须是全量的那个数。
    _alertTimer = Timer.periodic(const Duration(seconds: 10), (_) {
      if (_pendingCount > 0) _announcer.announce();
    });
  }

  /// 前台服务(唤醒锁)跟着营业状态走。
  ///
  /// 之前是进这个页面就无条件 `start()`,只在 `dispose()` 才 `stop()` ——
  /// 也就是说**打烊一整晚,唤醒锁照样握着、订单照样轮询**。
  /// 关了店还在听单,听到了也不能接。
  Future<void> _syncKeepAlive() async {
    if (_isOpen) {
      await ListenKeepAlive.start();
    } else {
      await ListenKeepAlive.stop();
    }
  }

  /// 营业 / 打烊开关。
  ///
  /// ## 失败回弹必须说话
  ///
  /// 原来是 `catch (e) { setState(() => _isOpen = !v); }` —— 拿到了 `e` 却
  /// 一个字都不说。早上开店点「营业」,网卡一下,开关自己弹回「已打烊」,
  /// 商家看一眼觉得点错了、或者根本没看,收起手机去备餐 ——
  /// **一整天零单**,到晚上才发现店压根没开过。
  ///
  /// 「开关弹回去了」在界面上和「我自己点的」长得一模一样,
  /// 所以必须由文案讲清楚:没成功、现在是什么状态、怎么补救。
  Future<void> _setOpen(bool v) async {
    setState(() => _isOpen = v);
    try {
      await widget.api.setShopOpen(v);
      // 打烊就放掉唤醒锁 —— 关了店还握着,听到单也不能接,
      // 纯烧电。开门再拿回来
      await _syncKeepAlive();
    } catch (e) {
      if (!mounted) return;
      setState(() => _isOpen = !v);
      final why = e is ApiException ? e.message : '$e';
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(
          backgroundColor: Theme.of(context).sz.danger,
          duration: const Duration(seconds: 8),
          content: Text(v
              ? '没能开店:$why\n店铺还是「已打烊」,现在收不到单'
              : '没能打烊:$why\n店铺还是「营业中」'),
          action: SnackBarAction(
            label: '重试',
            textColor: Colors.white,
            onPressed: () => _setOpen(v),
          ),
        ));
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _timer?.cancel();
    _alertTimer?.cancel();
    _todayTimer?.cancel();
    _searchDebounce?.cancel();
    _searchCtrl.dispose();
    _wsPing?.cancel();
    _reconnectTimer?.cancel();
    _closeWs();
    _announcer.dispose();
    ListenKeepAlive.stop();
    super.dispose();
  }

  /// 关掉当前连接。`close()` 可能带着「这条连接本来就没连上」的错误回来,
  /// 不接就是一条未处理的异步异常(控制台一片红);这里只是清理,吞掉即可
  void _closeWs() {
    final old = _ws;
    _ws = null;
    old?.sink.close().catchError((_) {});
  }

  /// 实时听单通道:新单推送 → 响铃 + 振动 + 横幅
  ///
  /// ## 这里曾经会把手机连炸
  ///
  /// 原来 `onError` 和 `onDone` 各挂了一次 `_scheduleReconnect()`。看着像两条
  /// 互斥的路径,实际不是:`web_socket_channel` 连不上的时候是先 `addError()`
  /// 再 `close()`,**两个回调必然都触发**,于是一次断线排两个重连,
  /// 每个重连再各排两个 —— 30 秒后 64 条连接,一分钟后四千条。
  /// 而旧的 `_ws` 从来不 close,活下来的连接还都在收推送,同一单播报好几遍。
  ///
  /// 商家的听单机卡死 = 漏单 = 直接少一天营业额,所以这里四道都得有:
  /// 判重(`ReconnectPolicy`)、关旧连接、单一定时器、指数退避。
  void _connectWs() {
    if (!mounted) return;
    // 防重入:定时器和生命周期回调可能同时想连一条
    if (!_reconnect.beginConnect()) return;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;

    // **旧连接先关掉。** 不关的话它还活着、还在收推送 ——
    // 重连出来的新连接叠上去,同一单会被播报两遍
    _wsPing?.cancel();
    _closeWs();

    final uri = Uri.parse(
        '${widget.api.wsBaseUrl}/ws/merchants/${widget.shop.id}?token=${widget.api.token}');
    try {
      _ws = WebSocketChannel.connect(uri);
    } catch (_) {
      _scheduleReconnect();
      return;
    }
    final ws = _ws!;
    // 握手真成了才算连上:退避在这里归零,指示灯也在这里转绿。
    // 等第一条消息才转绿是不准的 —— 服务端空闲时一条都不发
    ws.ready.then((_) {
      if (!mounted || !identical(_ws, ws)) return;
      _reconnect.onConnected();
      if (!_wsConnected) setState(() => _wsConnected = true);
    }, onError: (_) => _scheduleReconnect(ws));
    _wsPing = Timer.periodic(
        const Duration(seconds: 30), (_) => _ws?.sink.add('ping'));
    ws.stream.listen(
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
        } else if (data['type'] == 'bad_review') {
          // 差评即时横幅:响应越快挽回余地越大;点按钮直达评价页
          if (mounted) {
            ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              backgroundColor: Theme.of(context).sz.danger,
              duration: const Duration(seconds: 8),
              content:
                  Text('💬 收到 ${data['rating']} 星评价:${data['summary'] ?? ''}'),
              action: SnackBarAction(
                label: '去回复',
                textColor: Colors.white,
                onPressed: () => Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => MerchantReviewsPage(
                        api: widget.api, initialFilter: 1))),
              ),
            ));
          }
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
      // 这两个回调**都会**在连不上时触发,判重交给 ReconnectPolicy。
      // 带上 ws:上一条连接的收尾事件不该把新连接顶掉
      onError: (_) => _scheduleReconnect(ws),
      onDone: () => _scheduleReconnect(ws),
    );
  }

  /// [from] 是发出这次断线通知的连接。不是当前那条就忽略 ——
  /// 旧连接关掉时的 onDone 会晚一步到,不认人就会把刚连上的新连接也重连掉
  void _scheduleReconnect([WebSocketChannel? from]) {
    if (!mounted) return;
    if (from != null && !identical(_ws, from)) return;
    _wsPing?.cancel();
    if (_wsConnected) setState(() => _wsConnected = false);
    // null = 这次断线已经排过重连了(onError 和 onDone 会一前一后都进来)
    final delay = _reconnect.schedule();
    if (delay == null) return;
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, () {
      if (mounted) _connectWs();
    });
  }

  /// 服务端聚合的待接单数(`/merchants/me/todos` 的 `pending_orders`,
  /// 服务端是 `count(Order.id) where status == PAID`,全量、无窗口)。
  /// null = 还没拉到(冷启动的头几百毫秒)。
  int? get _serverPending => _todos?['pending_orders'] as int?;

  /// **窗口里**看得见的待接单。
  ///
  /// ⚠️ 这不是总数。`myOrders()` 默认 `limit=20`,服务端按 `created_at desc`
  /// 切片、**不带状态过滤**(orders.py)。午高峰 20 单以上时,更早的未接单
  /// 会掉出这个窗口 —— 而 `_orders` 这一个列表同时驱动顶栏的「N 单待接」、
  /// 三个分段的内容、以及每 10 秒一次的催单语音。三条链一起断:
  /// 看不见、数不到、**也不再催**。
  ///
  /// 而这一页早就把权威数拉下来了(`_todos`),只是一次都没用。
  List<Order> get _pendingInWindow =>
      _orders.where((o) => o.status == OrderStatus.paid).toList();

  /// 待接单列表:窗口截断了就用单独拉的那一份,没截断就用窗口里那些。
  List<Order> get _pendingList => _pendingFetched ?? _pendingInWindow;

  /// 待接单总数。
  ///
  /// 单独拉过就用那一份的长度(它是同一轮刷新里按状态拿的,精确);
  /// 没拉过就取「服务端说的」和「窗口里数的」两者的大者 ——
  /// `/todos` 30 秒一刷,而 WebSocket 推进来的新单立刻就在列表里,
  /// 那几十秒窗口比服务端新;反过来,超过 20 单的那部分只有服务端知道。
  int get _pendingCount =>
      _pendingFetched?.length ??
      math.max(_serverPending ?? 0, _pendingInWindow.length);

  /// 待接单掉出窗口时,按状态单独再拉一次。
  ///
  /// **平时这一次请求不会发出去**:服务端说的待接数和窗口里数出来的一致,
  /// 就说明没被截断。只有午高峰真压了 20 单以上才多花一个来回 ——
  /// 而那正是这个 App 存在的时刻。
  Future<void> _syncPending(List<Order> window) async {
    final server = _serverPending;
    final visible = window.where((o) => o.status == OrderStatus.paid).length;
    if (server == null || server <= visible) {
      if (_pendingFetched != null && mounted) {
        setState(() => _pendingFetched = null);
      }
      return;
    }
    try {
      // 走枚举不写字面量:服务端 `OrderStatus(status)` 认的就是这个值
      final all =
          await widget.api.myOrders(status: OrderStatus.paid.value, limit: 50);
      if (mounted) setState(() => _pendingFetched = all);
    } catch (_) {
      // 拉不到就退回窗口里那些:少显示几单,但**绝不清空** ——
      // 和 _refresh 失败时保留上一次结果是同一条理由
    }
  }

  /// 「历史」分段该显示的单。窗口里那些 + 翻页拿到的更早的,按单号去重。
  ///
  /// 去重是必要的:翻页之后又进了新单,`_orders` 会整体往前挪,
  /// 原来窗口最末那几单就和 `_historyMore` 的头几单重了。
  List<Order> get _historyList {
    const done = {
      OrderStatus.delivered,
      OrderStatus.completed,
      OrderStatus.cancelled,
    };
    final seen = <String>{};
    final out = <Order>[];
    for (final o in [..._orders, ..._historyMore]) {
      if (!done.contains(o.status)) continue;
      if (seen.add(o.orderNo)) out.add(o);
    }
    return out;
  }

  /// 下一页的游标 = 目前已知**最早**一单的下单时间。
  String? get _historyCursorNext {
    if (_historyCursor != null) return _historyCursor;
    return _orders.isEmpty ? null : _orders.last.createdAt;
  }

  /// 历史栏还有没有「更早的」可翻。
  bool get _historyHasMore =>
      !_historyEnd &&
      _historyCursorNext != null &&
      _historyMore.length < _kHistoryMax;

  /// 到上限了(不是翻到底了)。两者的文案必须不一样 ——
  /// 「没有更早的」和「这里不再往下翻」是两件事
  bool get _historyCapped =>
      !_historyEnd && _historyMore.length >= _kHistoryMax;

  Future<void> _loadMoreHistory() async {
    if (_historyLoading || _historyEnd) return;
    final cursor = _historyCursorNext;
    if (cursor == null) return;
    setState(() => _historyLoading = true);
    try {
      final page = await widget.api.myOrders(before: cursor, limit: 20);
      if (!mounted) return;
      setState(() {
        _historyMore.addAll(page);
        _historyCursor = page.isEmpty ? cursor : page.last.createdAt;
        // 回不满一页 = 到底了
        _historyEnd = page.length < 20;
      });
    } catch (e) {
      if (mounted) _snack(e is ApiException ? e.message : '$e');
    } finally {
      if (mounted) setState(() => _historyLoading = false);
    }
  }

  /// 切到「历史」时,窗口里一条历史单都没有就先自动翻一页。
  ///
  /// 不自动翻的话,商家看到的是「这一栏没有订单」—— 而更早的单明明还在。
  /// 「没有」和「这一页没有」在屏幕上长得一样,是这一栏最危险的歧义。
  void _maybeAutoLoadHistory() {
    if (_segment != 2 || _historyLoading || !_historyHasMore) return;
    if (_historyList.isEmpty) _loadMoreHistory();
  }

  /// 拉订单列表。
  ///
  /// ⚠️ **失败绝不能静默。** 这里原本是 `catch (_) {}` ——
  /// 而 `_orders` 同时驱动订单列表**和持续催单语音**(见 initState 里的
  /// `_alertTimer`)。拉不到的时候:列表是空的、语音不响,
  /// 而顶部的连接指示灯还是绿的(WebSocket 连着 ≠ 列表拉到了)。
  /// 商家看到的是「一切正常,今天没单」,实际上单在往里进。
  ///
  /// 午高峰漏一单,这个平台赔不起。
  ///
  /// 两条处置:
  /// 1. 失败**不清空 `_orders`** —— 保留上一次的结果,比变成空列表安全;
  /// 2. 记下最后一次成功的时间,顶部横条按"新鲜度"报警。
  Future<void> _refresh() async {
    try {
      final orders = await widget.api.myOrders();
      if (mounted) {
        setState(() {
          _orders = orders;
          _lastOrdersOkAt = DateTime.now();
          _ordersError = '';
        });
      }
      _autoPrintNew(orders);
      await _syncPending(orders);
      _maybeAutoLoadHistory();
    } catch (e) {
      if (mounted) {
        setState(() => _ordersError = e is ApiException ? e.message : '$e');
      }
    }
  }

  /// 订单列表是不是"陈"了。超过 1 分钟没成功拉到就算 ——
  /// 正常轮询是 15 秒一次,连着失败 4 次说明真出问题了
  bool get _ordersStale {
    if (_lastOrdersOkAt == null) {
      return _ordersError.isNotEmpty; // 首次就失败
    }
    return DateTime.now().difference(_lastOrdersOkAt!).inSeconds > 60;
  }

  /// 顶部警示条:**首次加载失败不能和「今天没单」长得一样**
  Widget? _staleBanner() {
    if (!_ordersStale) return null;
    final never = _lastOrdersOkAt == null;
    final mins =
        never ? 0 : DateTime.now().difference(_lastOrdersOkAt!).inMinutes;
    return SzRetryBanner(
      text: never
          ? '订单列表没能加载出来 —— 下面的空白不代表没有单,点这里重试'
          : '订单列表已经 $mins 分钟没更新成功,可能有新单没显示。点这里重试',
      onRetry: _refresh,
    );
  }

  Future<void> _refreshToday() async {
    // 两个请求互不依赖,先都发出去再逐个 await。
    // 看板拉不到不打扰接单主流程,所以两个都走 soft —— 保留上一次的值
    final todayF = widget.api.merchantToday();
    final todosF = widget.api.merchantTodos();
    final g = SzGather();
    final today = await g.soft(todayF, _today);
    final todos = await g.soft(todosF, _todos);
    if (mounted) {
      setState(() {
        _today = today;
        _todos = todos;
      });
      // 刚拿到权威的待接数,立刻和窗口对一次。
      // **不能只在 `_refresh()` 里对**:冷启动时这两个请求是并发的,
      // `_refresh()` 跑完时 `_todos` 还是 null,那一轮 `_syncPending` 只能空跑 ——
      // 于是「掉出窗口的未接单」要等下一个 15 秒的 tick 才浮出来
      await _syncPending(_orders);
      _maybeAutoLoadHistory();
    }
  }

  /// 待办行的数据源:欠着没处理的事,每项一个 chip。
  ///
  /// **这仍是那一份待办**(判据 5:不另做待办区)。#33 只改排法 ——
  /// 原先 `Wrap` 两行 62px,现在横向可滚一行 43px,文案去掉冗余词
  /// (「售后待处理 2」→「售后 2」)。数字、去向、口径一个没动。
  List<(String, VoidCallback)> _todoRows() {
    final todos = _todos;
    if (todos == null) return const [];
    final rows = <(String, VoidCallback)>[];
    void addRow(String key, String label, VoidCallback onTap) {
      final n = todos[key] as int? ?? 0;
      if (n > 0) rows.add(('$label $n', onTap));
    }

    addRow('after_sales', '售后', () => setState(() => _tab = 3));
    // 差评只出一行:overdue 是 unreplied 的**子集**,分两行的话
    // 同一条差评会被数两遍,商家看到"2 件事"其实只有 1 条。
    // 超 24 小时的把紧迫性写进同一行文案(与 merchant-web 同口径)
    final badUnreplied = todos['bad_reviews_unreplied'] as int? ?? 0;
    final badOverdue = todos['bad_reviews_overdue'] as int? ?? 0;
    if (badUnreplied > 0) {
      rows.add((
        badOverdue > 0
            ? '差评 $badUnreplied(超24h $badOverdue)'
            : '差评 $badUnreplied',
        () {
          Navigator.of(context).push(MaterialPageRoute(
              builder: (_) =>
                  MerchantReviewsPage(api: widget.api, initialFilter: 1)));
        }
      ));
    }
    addRow('coupon_batches_low', '券快发完', () => setState(() => _tab = 3));
    addRow('flash_expiring', '折扣到期', () => setState(() => _tab = 1));
    addRow('messages_unread', '消息', () {
      Navigator.of(context)
          .push(MaterialPageRoute(
              builder: (_) => MerchantMessagesPage(api: widget.api)))
          .then((_) => _refreshToday());
    });
    return rows;
  }

  /// 今日条:今天卖了多少。整条可点 → 对账 tab。
  ///
  /// 78px 的卡压到 46px 的 `SzEntryTile`(#33 4.1)。订单页是**干活页**,
  /// 首屏内容不可替换(必须是订单)—— 所以顶上这几块的正确动作是
  /// **把地方腾出来**,而不是往里塞更好看的东西。
  ///
  /// 昨日只留单量:昨日金额是对账页的数,这里要的只是「比昨天多还是少」。
  Widget _todayTile() {
    final today = _today?['today'] as Map<String, dynamic>?;
    if (today == null) return const SizedBox.shrink();
    final yesterday = _today?['yesterday'] as Map<String, dynamic>?;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: SzEntryGroup(children: [
        SzEntryTile(
          title: '今日 ${today['orders']} 单 · '
              '${yuan(today['gmv_cents'] as int? ?? 0)}',
          value: yesterday == null ? null : '昨日 ${yesterday['orders']} 单',
          onTap: () => setState(() => _tab = 2),
        ),
      ]),
    );
  }

  /// 待办条:横向可滚一行,**非零才出现**。
  ///
  /// 固定 43px:8/9 的上下留白 + 26 的 chip。横向滚动而不是换行 ——
  /// 待办最多五项,而干活页每多一行就少小半张订单卡。
  Widget _todoStrip() {
    final rows = _todoRows();
    if (rows.isEmpty) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    return SizedBox(
      height: 43,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(12, 9, 12, 8),
        itemCount: rows.length,
        separatorBuilder: (_, __) => const SizedBox(width: 6),
        itemBuilder: (context, i) {
          final (label, onTap) = rows[i];
          return InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(12),
            child: Container(
              alignment: Alignment.center,
              padding: const EdgeInsets.symmetric(horizontal: 10),
              decoration: BoxDecoration(
                color: sz.danger.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(12),
              ),
              child:
                  Text(label, style: TextStyle(fontSize: 12, color: sz.danger)),
            ),
          );
        },
      ),
    );
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
      // 待办数也要跟着走:不刷的话 `/todos` 最长 30 秒才更新,
      // 而这期间 [_pendingCount] 还按旧值催 —— 接完最后一单还在响
      _refreshToday();
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
      builder: (context) => SzDialog(
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
      _refreshToday(); // 同 _act:拒完单 [_pendingCount] 要立刻降下来
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
    }
  }

  /// 缺货退款:弹层选菜品和份数,退对应的钱(不用整单拒)
  Future<void> _refundSheet(Order order) async {
    final result = await szShowSheet<(int, int)>(
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
      builder: (context) => SzDialog(
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

  /// 读屏用的订单指代:「尾号 3721 · 48 元」。
  ///
  /// 一屏十几单时,读屏用户听到的原本只有"聊天,按钮""打印,按钮" ——
  /// 光标停在谁身上全靠数。接单/拒单按错的代价是真金白银,得把订单说清楚
  String _orderSpeech(Order order) {
    final no = order.orderNo;
    final tail = no.length > 4 ? no.substring(no.length - 4) : no;
    return '尾号 $tail,${(order.totalCents / 100).toStringAsFixed(2)} 元';
  }

  /// 卡片右上角的「⋯」:聊天 / 打印小票 / 缺货退款(#33 4.1 第 4 点)。
  ///
  /// 这三个从动作行收进菜单,动作行只留主操作(拒单/接单/出餐完成…)。
  /// 换来的是窄屏上动作行不再折行:卡从 238 回到 180 以下,首屏多放一张。
  ///
  /// ⚠️ **这一条改了手势习惯**:打印小票从 1 触摸变 2 触摸。之所以是它们
  /// 三个而不是别的 —— 主操作每单必点,这三个是**偶尔**才点:
  /// 聊天要顾客先问、打印小票绝大多数店已经开了自动出票(蓝牙/云打印
  /// 在支付成功时就打了)、缺货退款是异常路径。
  ///
  /// 历史单(default 分支)本来就没有动作行,也就没有这个菜单 —— 保持原样。
  Future<void> _flagSheet(Order order) async {
    await szShowSheet<bool>(
      context: context,
      builder: (context) =>
          FlagOrderSheet(api: widget.api, orderNo: order.orderNo),
    );
  }

  Widget? _moreMenuFor(Order order) {
    final who = _orderSpeech(order);
    final canRefund = order.status == OrderStatus.paid ||
        order.status == OrderStatus.accepted;
    const live = {
      OrderStatus.paid,
      OrderStatus.accepted,
      OrderStatus.ready,
      OrderStatus.pickedUp,
    };
    // 标记异常发生在**单子结束之后** —— 争议(说少了一份、乱打差评)
    // 那时候才出现。所以已送达/已完成/已取消的单也要有这个菜单,
    // 只是里面只有「标记异常」一项。
    const done = {
      OrderStatus.delivered,
      OrderStatus.completed,
      OrderStatus.cancelled,
    };
    final canFlag = done.contains(order.status);
    if (!live.contains(order.status) && !canFlag) return null;
    return Semantics(
      label: '更多操作,$who',
      button: true,
      excludeSemantics: true,
      child: SizedBox(
        width: 40,
        height: 40,
        child: PopupMenuButton<String>(
          tooltip: '更多',
          padding: EdgeInsets.zero,
          icon: const Icon(Icons.more_horiz, size: 20),
          onSelected: (v) {
            switch (v) {
              case 'chat':
                Navigator.of(context).push(MaterialPageRoute(
                    builder: (_) => OrderChatPage(
                        api: widget.api,
                        orderNo: order.orderNo,
                        title: '和顾客说句话',
                        quickReplies: kMerchantQuickReplies)));
              case 'print':
                _printTicket(order);
              case 'refund':
                _refundSheet(order);
              case 'flag':
                _flagSheet(order);
            }
          },
          itemBuilder: (_) => [
            const PopupMenuItem(
              value: 'chat',
              child: ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(Icons.chat_bubble_outline, size: 20),
                title: Text('和顾客说句话'),
              ),
            ),
            if (!canFlag)
              const PopupMenuItem(
                value: 'print',
                child: ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.print_outlined, size: 20),
                  title: Text('打印小票'),
                ),
              ),
            if (canRefund)
              const PopupMenuItem(
                value: 'refund',
                child: ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.remove_shopping_cart_outlined, size: 20),
                  title: Text('缺货退款'),
                ),
              ),
            // 单子结束之后才给 —— 争议是那时候才出现的
            if (canFlag)
              const PopupMenuItem(
                value: 'flag',
                child: ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.flag_outlined, size: 20),
                  title: Text('标记异常'),
                ),
              ),
          ],
        ),
      ),
    );
  }

  /// 动作行:**只留主操作**。
  ///
  /// 聊天 / 打印小票 / 缺货退款收进了卡片右上角的「⋯」(见 [_moreMenuFor])
  /// —— 它们挤在这一行时,窄屏上要折成两行,一张卡 180 → 238。
  List<Widget> _actionsFor(Order order) {
    final who = _orderSpeech(order);
    switch (order.status) {
      case OrderStatus.paid:
        return [
          // 拒单和接单在屏幕上挨着,读屏时更要说清是哪一单
          Semantics(
            label: '拒单,$who',
            excludeSemantics: true,
            button: true,
            child: OutlinedButton(
                onPressed: () => _reject(order), child: const Text('拒单')),
          ),
          Semantics(
            label: '接单,$who',
            excludeSemantics: true,
            button: true,
            child: FilledButton(
                onPressed: _acting.contains(order.orderNo)
                    ? null
                    : () => _act(order, OrderStatus.accepted),
                child: Text(_acting.contains(order.orderNo) ? '处理中…' : '接单')),
          ),
        ];
      case OrderStatus.accepted:
        return [
          Semantics(
            label: '出餐完成,$who',
            excludeSemantics: true,
            button: true,
            child: FilledButton(
                onPressed: _acting.contains(order.orderNo)
                    ? null
                    : () => _act(order, OrderStatus.ready),
                child: Text(_acting.contains(order.orderNo) ? '处理中…' : '出餐完成')),
          ),
        ];
      case OrderStatus.ready:
        return [
          // 平台配送且骑手已接:看骑手到哪了(顾客催单先打给店家,
          // 店家不该两眼一抹黑)
          if (!order.pickup &&
              !order.selfDelivery &&
              order.riderId != null) ...[
            OutlinedButton.icon(
                icon: const Icon(Icons.delivery_dining, size: 18),
                onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                        builder: (_) =>
                            RiderTrackPage(api: widget.api, order: order))),
                label: const Text('骑手位置')),
          ],
          if (order.pickup) ...[
            Semantics(
              label: '核销取餐码,$who',
              excludeSemantics: true,
              button: true,
              child: FilledButton.icon(
                  icon: const Icon(Icons.qr_code, size: 18),
                  onPressed: () => _verifyPickup(order),
                  label: const Text('核销取餐码')),
            ),
          ],
          if (order.selfDelivery) ...[
            // 出发前先看清送去哪、多远。远近全靠猜的话,
            // 猜错就是自己骑半小时送一单 3 块钱配送费的活
            OutlinedButton.icon(
                icon: const Icon(Icons.map_outlined, size: 18),
                onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                        builder: (_) => SelfDeliveryMapPage(order: order))),
                label: const Text('地图')),
            Semantics(
              label: '开始配送,自送,$who',
              excludeSemantics: true,
              button: true,
              child: FilledButton.icon(
                  icon: const Icon(Icons.delivery_dining, size: 18),
                  onPressed: () => _act(order, OrderStatus.pickedUp),
                  label: const Text('开始配送(自送)')),
            ),
          ],
        ];
      case OrderStatus.pickedUp:
        return [
          if (!order.selfDelivery && order.riderId != null) ...[
            OutlinedButton.icon(
                icon: const Icon(Icons.delivery_dining, size: 18),
                onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                        builder: (_) =>
                            RiderTrackPage(api: widget.api, order: order))),
                label: const Text('骑手位置')),
          ],
          // 自送的商家在路上,和骑手是同一种处境:需要导航,而不是一行文字地址。
          // 此前商家端全程没有地图,自送只能对着地址自己找
          if (order.selfDelivery) ...[
            OutlinedButton.icon(
                icon: const Icon(Icons.navigation_outlined, size: 18),
                onPressed: () => navigateTo(context,
                    lat: order.lat,
                    lng: order.lng,
                    name: order.address,
                    mode: NavMode.ride),
                label: const Text('导航')),
            FilledButton(
                onPressed: () => _act(order, OrderStatus.delivered),
                child: const Text('已送达')),
          ],
        ];
      default:
        return const [];
    }
  }

  /// 「进行中」这一栏的状态集合。分段标签的数字和列表内容共用它 ——
  /// 两处各写一套迟早对不上(#33 第 6 节:同一个数不要有第二个来源)。
  static const _ongoingStatuses = {
    OrderStatus.accepted,
    OrderStatus.ready,
    OrderStatus.pickedUp,
  };

  /// 进行中的单数。
  ///
  /// ⚠️ 这是**窗口里**数出来的(`_orders` 默认 20 条),和 `_pendingCount`
  /// 不一样 —— 待接单有服务端聚合兜底,进行中没有对应字段。所以标签只写
  /// 「进行中 N」:N 就是这一栏此刻能看到的条数,不冒充全量。
  int get _ongoingCount =>
      _orders.where((o) => _ongoingStatuses.contains(o.status)).length;

  List<Order> get _filteredOrders {
    if (_searchActive) return _searchResults;
    const ongoing = _ongoingStatuses;
    return switch (_segment) {
      // 待接单和历史都不再从 20 条窗口里过滤
      // —— 见 [_pendingInWindow]、[_historyList]
      0 => _pendingList,
      1 => _orders.where((o) => ongoing.contains(o.status)).toList(),
      _ => _historyList,
    };
  }

  /// 历史栏底下那一条「看更早的订单」。
  ///
  /// 只在**历史**栏出现,而且只在服务端还可能有更早的单时出现 ——
  /// 翻到底之后它自己消失,不留一个点了没反应的按钮。
  bool get _showHistoryMore =>
      !_searchMode && _segment == 2 && (_historyHasMore || _historyCapped);

  /// 历史正在翻页(空态文案要跟着变:「没有」和「还在翻」不是一回事)。
  bool get _historyPending => _segment == 2 && _historyLoading;

  /// 订单流:窄屏单列,可用宽度 ≥700 时两栏(#33 4.1 宽屏)。
  ///
  /// **判据是可用宽度不是平台** —— 平板横屏、网页版窗口拉宽都算。
  /// 每栏约 520:一张 1080 通栏的订单卡,取餐码在最左、接单按钮在最右,
  /// 中间隔着一片空白,眼睛得来回扫。
  ///
  /// ## 为什么两栏用 Wrap 而不是 GridView
  ///
  /// 订单卡高度不定(待接单 180、自送待取餐带地图按钮更高、历史单最矮)。
  /// `GridView` 要固定 `mainAxisExtent`:给小了高卡溢出(而这一页刚为
  /// 溢出打过一仗),给大了矮卡下面全是空白。
  ///
  /// 代价是 `Wrap` 不做按需构建。**窄屏保留 `ListView.builder`** ——
  /// 手机上列表可能很长;两栏只在宽屏走,那是店里的电脑,而历史栏本身
  /// 已经封顶 [_kHistoryMax] 条。
  Widget _orderFeed() {
    return LayoutBuilder(builder: (context, c) {
      final orders = _filteredOrders;
      if (c.maxWidth < 700) {
        return ListView.builder(
          itemCount: orders.length + (_showHistoryMore ? 1 : 0),
          itemBuilder: (context, i) => i >= orders.length
              ? _historyMoreTile()
              : _orderCard(orders[i]),
        );
      }
      // 卡片自带 12 的横向 margin,所以每栏宽度直接对半分
      final colWidth = c.maxWidth / 2;
      return SingleChildScrollView(
        // 两栏时也要能下拉刷新:列表不满一屏时 Wrap 撑不满,
        // 没有 AlwaysScrollable 就拉不动
        physics: const AlwaysScrollableScrollPhysics(),
        child: Column(children: [
          Wrap(
            children: [
              for (final o in orders)
                SizedBox(width: colWidth, child: _orderCard(o)),
            ],
          ),
          if (_showHistoryMore) _historyMoreTile(),
        ]),
      );
    });
  }

  /// 一张订单卡。
  ///
  /// 抽成方法是为了让窄屏的 `ListView.builder` 和宽屏两栏共用同一张卡
  /// (#33 4.1 宽屏)—— 两处各画一张的话,改一处忘一处。
  Widget _orderCard(Order order) {
    final sz = Theme.of(context).sz;
    final isNew = order.status ==
        OrderStatus.paid;
    return Container(
      margin:
          const EdgeInsets.symmetric(
              horizontal: 12,
              vertical: 5),
      decoration: BoxDecoration(
        color: sz.surface,
        borderRadius:
            BorderRadius.circular(
                kRadiusMd),
        border: Border.all(
            // 出餐超时:整卡 danger 描边,后厨一眼看到该催
            color: order.readyLate
                ? sz.danger
                : sz.line,
            width: order.readyLate
                ? 1.5
                : 1),
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
      // 「⋯」用 Stack 浮在右上角而不是
      // 排进标题行:40×40 的触控区排进去
      // 会把那一行从 20 撑到 40,而这一点
      // 改造的全部意义就是省高度(实测
      // 排进去 196、浮起来 176)
      child: Stack(children: [
      Padding(
        padding:
            const EdgeInsets.fromLTRB(
                12, 11, 12, 11),
        child: Column(
          crossAxisAlignment:
              CrossAxisAlignment.start,
          children: [
            Row(
                crossAxisAlignment:
                    CrossAxisAlignment
                        .start,
                children: [
                  Expanded(
                      child: Text(
                          order.summary,
                          style: TextStyle(
                              fontSize:
                                  14.5,
                              fontWeight:
                                  FontWeight
                                      .w600,
                              color: sz
                                  .ink))),
                  const SizedBox(
                      width: 8),
                  SzChip(
                      order
                          .status.label,
                      color: isNew
                          ? sz.clay
                          : sz.inkMuted,
                      dense: true),
                  // 「⋯」浮在卡片右上角
                  // (下面的 Stack),
                  // 这里只给它让出位置
                  if (_moreMenuFor(
                          order) !=
                      null)
                    const SizedBox(
                        width: 34),
                ]),
            const SizedBox(height: 5),
            Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  if (order
                      .parentOrderNo
                      .isNotEmpty)
                    SzChip(
                        '加·随${order.parentOrderNo.substring(order.parentOrderNo.length - 6)}',
                        color: sz.earn,
                        dense: true),
                  if (_urgedOrders
                      .contains(order
                          .orderNo))
                    SzChip('催',
                        color:
                            sz.danger,
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
            if (order.scheduledLabel !=
                null)
              Padding(
                padding:
                    const EdgeInsets
                        .only(top: 4),
                child: Text(
                    '⏰ ${order.scheduledLabel},请按时出餐',
                    style: TextStyle(
                        fontSize: 12,
                        color: sz.hold,
                        fontWeight:
                            FontWeight
                                .w600)),
              ),
            if (isNew)
              _waitTimer(order),
            // 备餐计时:接单后按承诺出餐时长计时,超时高亮
            if (order.status ==
                OrderStatus.accepted)
              _prepTimer(order),
            const SizedBox(height: 5),
            Row(children: [
              Text(
                  yuan(
                      order.totalCents),
                  style: szMoney(
                      fontSize: 14,
                      fontWeight:
                          FontWeight
                              .w600,
                      color: sz.ink)),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                    order.address,
                    maxLines: 1,
                    overflow:
                        TextOverflow
                            .ellipsis,
                    style: TextStyle(
                        fontSize: 12,
                        color: sz
                            .inkMuted)),
              ),
            ]),
            if (order.remark.isNotEmpty)
              Text('备注:${order.remark}',
                  style: TextStyle(
                      fontSize: 12,
                      color:
                          sz.inkMuted)),
            if (order.status ==
                    OrderStatus
                        .cancelled &&
                order.cancelReason
                    .isNotEmpty)
              Text(
                  '取消原因:${order.cancelReason}',
                  style: TextStyle(
                      fontSize: 12,
                      color:
                          sz.danger)),
            if (order.refundCents > 0)
              Text(
                  '已退款 ${yuan(order.refundCents)}(${order.refundNote})',
                  style: TextStyle(
                      fontSize: 12,
                      color:
                          sz.danger)),
            if (_actionsFor(order)
                .isNotEmpty) ...[
              const SizedBox(height: 6),
              // ⚠️ **Wrap 不是 Row。**
              //
              // 待接单那一行实测本征宽
              // 354px,而卡片内容区在 390 屏
              // 上只有 340(360 屏 310、
              // 320 屏 270);自送待取餐那一行
              // 要 410px。`RenderFlex` 溢出时
              // `remainingSpace =
              // max(0, delta)`,`end` 对齐
              // 于是退化成 start ——
              // **被挤出去的是最后一个孩子**,
              // 也就是「接单」和
              // 「开始配送(自送)」。而 Row
              // 默认 Clip.none,它照样被画出来:
              // 390 上压在描边上,360 上有一截
              // 跑到屏幕外。
              //
              // 换 Wrap 之后放不下就折行,
              // 一个按钮都不丢。代价是 ≤390 屏
              // 上这张卡实测 180 → 238;
              // ≥430 仍是一行 180。这一页的
              // `_todayCard()` 为一模一样的
              // 溢出换过 Wrap,同一条理由。
              Wrap(
                alignment:
                    WrapAlignment.end,
                spacing: 8,
                runSpacing: 4,
                children:
                    _actionsFor(order),
              ),
            ],
          ],
        ),
      ),
      if (_moreMenuFor(order) != null)
        Positioned(
            // 和卡片自己的 12 内边距对齐,
            // 否则按钮会压在描边上
            top: 3,
            right: 12,
            child:
                _moreMenuFor(order)!),
      ]),
    );
  }

  Widget _historyMoreTile() => Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 16),
        child: _historyCapped
            // 停在这里要说清楚为什么,以及更早的去哪找。
            // 按钮悄悄消失的话,商家会以为「就这些了」
            ? Text(
                '这里最多显示最近 $_kHistoryMax 单。更早的在'
                '「对账 → 导出对账单(CSV)」里,逐单明细都在',
                textAlign: TextAlign.center,
                style: TextStyle(
                    fontSize: 12,
                    height: 1.5,
                    color: Theme.of(context).sz.inkMuted))
            : OutlinedButton(
                onPressed: _historyLoading ? null : _loadMoreHistory,
                child: Text(_historyLoading ? '正在翻…' : '看更早的订单'),
              ),
      );

  @override
  Widget build(BuildContext context) {
    // **不是** `_orders.where(paid).length` —— 那是 20 条窗口里的数。见 [_pendingCount]
    final pending = _pendingCount;
    final ongoing = _ongoingCount;
    // 宽屏(≥600)换左侧栏(#295)。商家端尤其需要:网页版和桌面版是
    // 「坐在店里的电脑前接单」的场景,鼠标跑到 1440px 屏底部切页太远
    return SzNavScaffold(
      selectedIndex: _tab,
      // 宽度上限交给外壳,标题栏和内容才用**同一个**宽度对齐。
      // 对账页要放表格和图表,用宽一档;其余是单列信息流
      contentMaxWidth: merchantTabMaxWidth(_tab),
      onSelected: (i) => setState(() => _tab = i),
      items: const [
        SzNavItem(
            icon: Icons.receipt_long_outlined,
            selectedIcon: Icons.receipt_long,
            label: '订单'),
        SzNavItem(
            icon: Icons.restaurant_menu_outlined,
            selectedIcon: Icons.restaurant_menu,
            label: '菜品'),
        SzNavItem(
            icon: Icons.bar_chart_outlined,
            selectedIcon: Icons.bar_chart,
            label: '对账'),
        SzNavItem(
            icon: Icons.store_outlined, selectedIcon: Icons.store, label: '店铺'),
      ],
      appBar: AppBar(
        leading: _searchMode && _tab == 0
            ? IconButton(
                icon: const Icon(Icons.arrow_back),
                onPressed: () => setState(() {
                  _searchMode = false;
                  _searchCtrl.clear();
                  _searchResults = [];
                }),
              )
            : null,
        title: _searchMode && _tab == 0
            ? TextField(
                controller: _searchCtrl,
                autofocus: true,
                decoration: const InputDecoration(
                    hintText: '订单号后几位 / 取餐码 / 手机尾号', border: InputBorder.none),
                onChanged: _onSearchChanged,
              )
            : widget.shops.length > 1
                ? _ShopSwitcher(
                    shops: widget.shops,
                    currentId: widget.shop.id,
                    currentName: widget.shop.name,
                    subtitle: switch (_tab) {
                      1 => '菜品管理',
                      2 => '对账',
                      3 => '店铺',
                      _ => '订单',
                    },
                    onSwitch: widget.onSwitchShop,
                  )
                : Text(switch (_tab) {
                    1 => '菜品管理',
                    2 => '对账',
                    3 => '店铺',
                    _ => '订单',
                  }),
        actions: [
          if (_tab == 0 && !_searchMode)
            IconButton(
              tooltip: '搜单',
              icon: const Icon(Icons.search),
              onPressed: () => setState(() => _searchMode = true),
            ),
          // 忙碌模式走 owner-only 接口,店员点了只会报错 —— 不给店员看入口
          if (!_searchMode && !widget.shop.viewerIsStaff)
            IconButton(
              tooltip: _busyActive ? '忙碌中,点击查看' : '高峰忙碌模式',
              icon: Icon(
                _busyActive
                    ? Icons.local_fire_department
                    : Icons.local_fire_department_outlined,
                color: _busyActive ? Theme.of(context).sz.hold : null,
              ),
              onPressed: _busySheet,
            ),
          Row(children: [
            // 口径是**两者都好**才显示正常:WebSocket 连着不等于列表拉到了。
            // 只看 WS 的话会出现"灯是绿的、列表是空的"这种最误导人的组合
            // 这盏灯是纯图标,不读出来等于没有 —— 而它答的正是
            // 「我现在还能不能收到单」
            Semantics(
              // 网页版的口径不一样,不能照搬 App 的「正常」。
              //
              // 浏览器没有前台服务:标签页一关、或者被浏览器休眠,
              // WebSocket 就断了 —— 而这时候灯还是绿的,商家以为在听单,
              // 实际上单进来没人知道。这是**最误导的那种绿灯**。
              //
              // 所以 web 上明说"只在这个页面开着时有效"。
              label: _ordersStale
                  ? '订单列表已过期,可能收不到新单'
                  : !_wsConnected
                      ? '接单提醒未连接'
                      : kIsWeb
                          ? '接单提醒正常,但只在这个页面开着时有效'
                          : '接单提醒正常',
              child: Icon(
                _wsConnected && !_ordersStale
                    ? Icons.notifications_active
                    : Icons.notifications_off,
                size: 18,
                color: _ordersStale
                    ? Theme.of(context).sz.danger
                    : (_wsConnected
                        ? Theme.of(context).sz.earn
                        : Theme.of(context).sz.inkMuted),
              ),
            ),
            const SizedBox(width: 8),
            Text(widget.shop.foodSafetyHold
                ? '食安停业'
                : (_isOpen ? '营业中' : '已打烊')),
            Switch(
              // 食安停业闸门置位时商家自己开不回来(服务端也会 403),
              // 直接禁用开关比让他点了报错好
              value: _isOpen,
              onChanged: widget.shop.foodSafetyHold
                  ? null
                  : _setOpen,
            ),
            const SizedBox(width: 8),
          ]),
        ],
      ),
      // 证照横幅横跨所有 tab:它是唯一一件"到点就自动出事"的事
      // (过期 → 7 天宽限 → 自动停业),不该只在某一个页面里出现
      body: Column(children: [
        // 网页版一进来就说清楚它能干什么、不能干什么。
        //
        // 商家最容易误解的就是听单:网页版**不能替代手机 App** ——
        // 浏览器没有前台服务,标签页一关或被休眠,WebSocket 就断了。
        // 不说清楚的话,他会以为开着网页就等于在听单。
        if (kIsWeb) const WebLimitsBanner(),
        LicenseBanner(api: widget.api, shop: widget.shop),
        Expanded(
            child: _tab == 1
                ? DishManagePage(api: widget.api)
                : _tab == 2
                    ? (widget.shop.viewerIsOwner
                        // 连锁的区域经理拿不到资金视图(服务端 403)。与其让人点进来
                        // 看一个红色报错,不如直接说清楚这不是给他看的
                        ? FinancePage(api: widget.api)
                        : const _NoFinanceForManager())
                    : _tab == 3
                        ? ShopTabPage(
                            api: widget.api,
                            onOpenFinance: () => setState(() => _tab = 2))
                        : Column(
                            children: [
                              // 平台公告(费率调整、新功能上线等,发通知不用发版)
                              AnnouncementBanner(
                                  api: widget.api, audience: 'merchant'),
                              if (!_searchMode) _todayTile(),
                              if (!_searchMode) _todoStrip(),
                              if (!_searchMode)
                                Padding(
                                  padding:
                                      const EdgeInsets.fromLTRB(12, 8, 12, 4),
                                  child: SegmentedButton<int>(
                                    // 数字跟着栏走:顶栏的「N 单待接」搬到这里
                                    // (#33 判据 1 在商家端不成立 —— 右上角
                                    // 三格被营业开关/听单灯/忙碌模式占着,
                                    // 而连锁店名今天就已经被截断)。
                                    //
                                    // ⚠️ 两个数各自是**这一栏实际能看到的条数**:
                                    // 待接走 `_pendingCount`(服务端聚合,不受
                                    // 20 条窗口截断);进行中是窗口内数出来的,
                                    // 所以它只敢叫「进行中」,不敢叫「全部进行中」。
                                    segments: [
                                      ButtonSegment(
                                          value: 0,
                                          label: Text(pending > 0
                                              ? '待接单 $pending'
                                              : '待接单')),
                                      ButtonSegment(
                                          value: 1,
                                          label: Text(ongoing > 0
                                              ? '进行中 $ongoing'
                                              : '进行中')),
                                      // 历史不给数字:它是分页拉的,给了就是撒谎
                                      const ButtonSegment(
                                          value: 2, label: Text('历史')),
                                    ],
                                    selected: {_segment},
                                    onSelectionChanged: (s) {
                                      setState(() => _segment = s.first);
                                      _maybeAutoLoadHistory();
                                    },
                                  ),
                                ),
                              // 拉不到订单时的警示条。**必须在列表上方、必须显眼** ——
                              // 空列表和"加载失败"长得一样,是商家端最危险的歧义
                              if (_staleBanner() != null) _staleBanner()!,
                              Expanded(
                                child: RefreshIndicator(
                                  onRefresh: _refresh,
                                  child: _filteredOrders.isEmpty
                                      ? ListView(children: [
                                          Padding(
                                              padding: const EdgeInsets.all(24),
                                              child: Center(
                                                  child: Text(_searchMode
                                                      ? (_searchActive
                                                          ? '没有匹配的订单'
                                                          : '输入订单号后几位、取餐码或手机尾号(至少 3 位)')
                                                      // 拉取失败时不说"没有订单" ——
                                                      // 那是在替一个未知状态下结论
                                                      : (_ordersStale
                                                          ? '订单列表没能加载出来'
                                                          : _historyPending
                                                              ? '正在翻更早的订单…'
                                                              : '这一栏没有订单'))),
                                          ),
                                          // 空着也要给出口:这一栏空不代表更早的也空
                                          if (_showHistoryMore)
                                            _historyMoreTile(),
                                        ])
                                      : _orderFeed(),
                                ),
                              ),
                            ],
                          )),
      ]),
    );
  }
}

/// 顶栏门店切换(仅连锁可见)。
///
/// 做成"店名 + 小箭头"而不是一个独立的设置项:切店是接单过程中随时会做的
/// 动作(总部同时盯三家),埋进二级菜单等于没有。单店商家看不到它。
class _ShopSwitcher extends StatelessWidget {
  const _ShopSwitcher({
    required this.shops,
    required this.currentId,
    required this.currentName,
    required this.subtitle,
    required this.onSwitch,
  });

  final List<Map<String, dynamic>> shops;
  final int currentId;
  final String currentName;
  final String subtitle;
  final Future<void> Function(int shopId)? onSwitch;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onSwitch == null ? null : () => _pick(context),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Flexible(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(currentName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w600)),
              Text(subtitle,
                  style: TextStyle(
                      fontSize: 12,
                      color: Theme.of(context).colorScheme.onSurfaceVariant)),
            ],
          ),
        ),
        const Icon(Icons.expand_more, size: 20),
      ]),
    );
  }

  Future<void> _pick(BuildContext context) async {
    final picked = await szShowSheet<int>(
      context: context,
      showDragHandle: true,
      builder: (sheet) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text('切换门店',
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            ),
          ),
          for (final s in shops)
            ListTile(
              leading: Icon(
                s['id'] == currentId
                    ? Icons.radio_button_checked
                    : Icons.radio_button_unchecked,
                color: s['id'] == currentId
                    ? Theme.of(context).colorScheme.primary
                    : null,
              ),
              title: Text('${s['name']}'),
              subtitle: Text('${s['address'] ?? ''}',
                  maxLines: 1, overflow: TextOverflow.ellipsis),
              // 审核中/打烊直接标出来:切过去发现一片空白再回头找原因,
              // 比在这里多两个字贵得多
              trailing: s['status'] != 'approved'
                  ? const Text('审核中', style: TextStyle(fontSize: 12))
                  : (s['is_open'] == false
                      ? const Text('打烊', style: TextStyle(fontSize: 12))
                      : null),
              onTap: () => Navigator.pop(sheet, s['id'] as int),
            ),
        ]),
      ),
    );
    if (picked != null && picked != currentId) await onSwitch!(picked);
  }
}

/// 非经营者本人(连锁区域经理)看到的对账页占位。
class _NoFinanceForManager extends StatelessWidget {
  const _NoFinanceForManager();

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.lock_outline, size: 40, color: muted),
          const SizedBox(height: 12),
          const Text('对账只对经营者本人开放',
              style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(
            '你是这家店的区域经理:改价、改设置、接单出餐都能做,'
            '但营业额、提现和收款账户只有店铺登记的经营者本人能看。',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 13, color: muted),
          ),
        ]),
      ),
    );
  }
}

/// 标记异常订单的表单。
///
/// ## 这张表单的重点是文案,不是控件
///
/// 平台**不给商家拉黑顾客的权力** —— 给了它会变成报复工具(差评了就拉黑)。
/// 作为交换,平台做一件单店做不到的事:把多家店的标记放在一起看,
/// 因为真正的职业索赔是跨店行为。
///
/// 代价是商家标记完**不会立刻发生任何事**,体感是「我说了没用」。
/// 所以这里必须原样说清楚会发生什么、多久有回音 —— 说不清楚的话,
/// 商家会以为按下去就解决了,然后在没解决时觉得平台在敷衍。
class FlagOrderSheet extends StatefulWidget {
  const FlagOrderSheet({super.key, required this.api, required this.orderNo});

  final ApiClient api;
  final String orderNo;

  @override
  State<FlagOrderSheet> createState() => _FlagOrderSheetState();
}

class _FlagOrderSheetState extends State<FlagOrderSheet> {
  String _kind = 'claim';
  final _reason = TextEditingController();
  bool _busy = false;

  static const _kinds = {
    'claim': '疑似职业索赔',
    'review': '疑似恶意差评',
    'other': '其他异常',
  };

  @override
  void dispose() {
    _reason.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final reason = _reason.text.trim();
    if (reason.length < 5) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('请写清楚为什么可疑(至少 5 个字)——平台要靠这段话去核查')));
      return;
    }
    setState(() => _busy = true);
    try {
      final r = await widget.api.flagOrder(widget.orderNo, _kind, reason);
      if (!mounted) return;
      Navigator.pop(context, true);
      // 结果用对话框而不是 SnackBar:这段话是承诺,一闪而过的提示读不完
      showDialog<void>(
        context: context,
        builder: (context) => SzDialog(
          title: const Text('已上报'),
          content: Text('${r['note'] ?? ''}'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('知道了')),
          ],
        ),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: EdgeInsets.fromLTRB(
          20, 8, 20, MediaQuery.of(context).viewInsets.bottom + 24),
      child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('标记异常订单',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 4),
            Text('订单 #${widget.orderNo.substring(widget.orderNo.length - 6)}',
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            const SizedBox(height: 16),
            Wrap(
              spacing: 8,
              children: [
                for (final e in _kinds.entries)
                  ChoiceChip(
                    label: Text(e.value),
                    selected: _kind == e.key,
                    onSelected: (_) => setState(() => _kind = e.key),
                  ),
              ],
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _reason,
              maxLines: 3,
              maxLength: 300,
              decoration: const InputDecoration(
                labelText: '为什么可疑',
                hintText: '越具体越有用:说了什么、要求什么、有没有凭证',
              ),
            ),
            // 这一段是这张表单的重点。不说清楚,商家会以为按下去就解决了
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: sz.surfaceAlt,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('标记之后会发生什么',
                        style: TextStyle(
                            fontSize: kFontBody,
                            fontWeight: FontWeight.w700,
                            color: sz.ink)),
                    const SizedBox(height: 6),
                    Text(
                        '· 上报平台核查,**不会自动对这位顾客做任何处置**。\n'
                        '· 我们不给商家拉黑顾客的权力 —— 那会变成报复工具。\n'
                        '· 职业索赔多是跨店行为:同一个人在几家店用同样的话术,'
                        '单店看不出来,平台把多家的标记放在一起才看得见。\n'
                        '· 核查有结果会在这里更新状态,并给你发一条通知。',
                        style: TextStyle(
                            fontSize: kFontNote,
                            height: 1.6,
                            color: sz.inkMuted)),
                  ]),
            ),
            const SizedBox(height: 14),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: _busy ? null : _submit,
                child: Text(_busy ? '上报中…' : '上报平台'),
              ),
            ),
          ]),
    );
  }
}
