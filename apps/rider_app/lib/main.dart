import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import 'alert_prefs.dart';
import 'dispatch_spec_page.dart';
import 'hall_widgets.dart';
import 'hardship_sheet.dart';
import 'location_service.dart';
import 'map_page.dart';
import 'offer_sheet.dart';
import 'pool_map_page.dart';
import 'profile_page.dart';
import 'task_panel.dart';
import 'verify_page.dart';
import 'wallet_page.dart';

// GPS 不可用时(如 iOS 模拟器没设置位置)的兜底坐标,保证开发期照常演示
const fallbackLat = 30.6605;
const fallbackLng = 104.0815;

/// 全端共用的 ApiClient 单例(会话持久化在它身上)
final rootApi = ApiClient();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // 推送 SDK 的初始化在用户同意隐私政策之后(PrivacyGate.onAgreed),
  // 同意前启动收集类 SDK 是应用商店审核红线
  // 可下发文案:只等本地缓存(毫秒级),网络刷新后台跑,不卡冷启动
  await RemoteCopy.loadCached();
  unawaited(RemoteCopy.refresh(rootApi));
  runApp(const RiderApp());
}

class RiderApp extends StatelessWidget {
  const RiderApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '超级赞骑手端',
      // 深浅两套令牌都在 brand.dart 里定义(第八辑 #101),#111 走查后放开。
      // 主强调取频道色「跑」(2026-09 浅色定稿:抢单、底部导航选中都是它);
      // 动效不回弹 —— 骑手在路上看手机,回弹那一下是在跟他抢注意力
      theme: brandTheme(Brightness.light,
          density: SzDensity.operate, accentTone: 3, bouncy: false),
      darkTheme: brandTheme(Brightness.dark,
          density: SzDensity.operate, accentTone: 3, bouncy: false),
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
        onAgreed: () async {
                  // 同意之后才初始化收集类 SDK。地图 SDK 尤其不能提前:
                  // 腾讯的接口是"同意前调用则地图显示为空白",
                  // 而且失败是静默的 —— 没异常没日志,只有一块白板
                  await PushService.init();
                  await agreeAndStart();
                },
        child: AuthGate(
          api: rootApi,
          title: '骑手端 · 抢单配送',
          role: 'rider',
          // 登录即进抢单大厅(对齐美团众包等行业惯例):实名认证不再整 App 门禁,
          // 改为跑单前置——上线/抢单时校验并引导,首页横幅常驻提示
          homeBuilder: (_, api) => RiderHomePage(api: api),
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

class _RiderHomePageState extends State<RiderHomePage>
    with WidgetsBindingObserver {
  int _tab = 0;
  bool _online = false;
  int? _grabRadiusKm; // 接单半径偏好(null=不限),服务端持久化
  /// 被骑手自己的偏好挡掉的单数。摆出来是**这一批的重点**:
  /// 悄悄过滤会变成"今天怎么没单",他不会想到是两个月前设的一个开关
  int _filteredByPrefs = 0;

  /// 因为定位取不到而**没生效**的接单偏好键(服务端算的)。
  ///
  /// 接单半径和只看顺路都要靠骑手位置算,位置没上报或过期(Redis 5 分钟)
  /// 时它们静默失效 —— 而界面上 chip 还选着「3km」。
  /// 骑手不会想到是定位的问题,只会觉得"这破筛选没用"。
  List<String> _stalePrefs = const [];

  /// 等餐补偿开没开(服务端 flags.wait_comp_on,当前默认关)。
  /// 关着的时候,卡片上的「含等餐 N 分钟」要标明不计费
  bool _waitCompOn = true;
  /// 其余接单偏好(单价下限 / 只看顺路 / 避开酒类)
  Map<String, dynamic> _prefs = const {};
  bool _gpsActive = false;

  /// 定位出问题了的一句话;null = 正常。
  ///
  /// 定位死掉是骑手端最难自己发现的故障:界面上什么都不变,单就是不来了。
  /// 他能想到的是"今天单少",想不到"我的定位半小时前就断了"。
  String? _gpsProblem;

  List<Order> _available = [];

  /// 最后一次**成功**刷新的时间。null = 从来没成功过。
  ///
  /// 和商家端 `_lastOrdersOkAt` 同一套口径:失败**不清空** `_available`/`_mine`,
  /// 保留上一次的结果比变成空列表安全 —— 空列表会被读成"没单"。
  DateTime? _lastRefreshOkAt;

  /// 最近一次刷新失败的原因;空串 = 上一次是成功的
  String _refreshError = '';

  /// 抢单池怎么看:综合(服务端算的)/ 离我最近 / 配送费高 / 顺路 / 帮我送。
  ///
  /// **不做服务端持久化**:这是个当下的选择,不是长期偏好 ——
  /// 他午高峰想按配送费挑、收工前想按距离挑,不该被记成"这个人偏好配送费"。
  ///
  /// 给这个切换本身是有立场的:dispatch.py 写着「算法只负责把信息排得
  /// 更有用」,那**排得对不对该由骑手说了算**。我们已经把算法公开给他看,
  /// 却不让他换个排法,中间是断的。默认为什么是「综合」见 [HallSort]。
  HallSort _sort = HallSort.composite;
  List<Order> _mine = [];

  // 这里原来有个 `_todayDone` getter,给「我的」页算今日单量和收入。
  //
  // **它恒为空。** `_mine` 只留 accepted/ready/pickedUp(见下面赋值处),
  // 而 `_todayDone` 从 `_mine` 里筛 completed||delivered ——
  // 两个集合不相交,所以「我的」页那两个数字对每个骑手每一天都是 0。
  //
  // 就算筛对了也还是错的:源头 `myOrders()` 默认 limit=20,
  // 在一页列表上求和却安「今日收入」这个名字,和用户端刚删掉的
  // 「累计优惠」是同一个错误。
  //
  // 「我的」页改成直接读服务端的全量聚合。统计该服务端算,不该客户端凑。
  Timer? _pollTimer;
  Timer? _keepaliveTimer;
  final _location = LocationService();

  /// 骑手当前位置(GCJ-02),地图页监听它实时刷新
  final _riderPosition = ValueNotifier<({double lat, double lng})?>(null);

  /// 今日所得(大厅顶上那张卡)。worklog 是服务端全量聚合,30 秒拉一次就够
  Map<String, dynamic>? _worklog;
  DateTime? _worklogAt;

  /// 新单推送正在展示的那一单(设计稿 5c);null = 没有弹层
  Order? _offer;
  bool _offerGrabbed = false;

  /// 在大厅卡片上刚抢到的那一单:按钮换成成功块,停一下再切到「进行中」。
  ///
  /// 连同原来的位置一起记着:抢到后池子一刷新这单就不在里面了,
  /// 不钉住的话卡片当场消失,「已抢到」根本没机会露面
  Order? _grabbedOrder;
  int _grabbedIndex = 0;

  /// 下拉刷新时 +1:卡片入场动画重播;轮询刷新不动它,就不重播(动效规范)
  int _hallGen = 0;

  /// 进行中各单的顾客未读消息数(任务卡上的「用户 N 条」)
  Map<String, int> _unread = const {};
  DateTime? _unreadAt;

  /// 账本看哪一段:0 今天 / 1 本周 / 2 本月(标题栏右边的文字页签)
  int _ledgerPeriod = 0;

  /// 新单提醒的声音 / 震动(「我的 → 新单提醒」,存在本机)
  RiderAlertPrefs _alerts = const RiderAlertPrefs();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) =>
        checkForUpdate(context, baseUrl: widget.api.baseUrl, app: 'rider'));
    _loadVerify(); // 认证状态:只做提示与跑单前置,不挡浏览
    RiderAlertPrefs.load().then((p) {
      if (mounted) setState(() => _alerts = p);
    });
    _refresh();
    _startPolling();
  }

  /// 轮询分三档,不能一刀切停掉。
  ///
  /// 骑手是全天挂机的重度用户,5 秒一次拉单在后台照跑等于白烧电。但服务端
  /// 目前**没有骑手新单推送**(push.py 只推商家新单和用户订单状态),
  /// 新单提醒完全依赖这个轮询——后台直接停会让骑手漏单。所以:
  ///  - 未上线:后台彻底停(没上线时 availableOrders 本来就是空的)
  ///  - 已上线 + 后台:降到 20 秒(仍会响铃提醒,耗电降到四分之一)
  ///  - 前台:5 秒
  /// 等骑手新单推送接上后,后台这一档可以彻底停掉。
  void _startPolling({bool background = false}) {
    _pollTimer?.cancel();
    if (background && !_online) return;
    final period = background ? const Duration(seconds: 20) : const Duration(seconds: 5);
    _pollTimer = Timer.periodic(period, (_) => _refresh());
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _refresh();
      _startPolling();
    } else if (state == AppLifecycleState.paused ||
        state == AppLifecycleState.hidden) {
      _startPolling(background: true);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
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

  /// 配送费构成一行文案:`基础 4.00 · 夜间 1.00 · 上楼 3.00`。
  ///
  /// 中文名一律用服务端下发的 `fee_part_labels`,不在客户端另写一份 ——
  /// 两份口径迟早会分叉,而这里分叉的后果是"骑手端说 3 块爬楼费、
  /// 顾客端说 3 块远距离费",两边都不信平台了。
  /// 服务端漏给名字时退回原始 key,总比吞掉这一项强。
  String _feePartsLine(Order order, {bool skipBase = false}) {
    final parts = <String>[];
    order.feeParts.forEach((k, v) {
      if (v <= 0 || (skipBase && k == 'base')) return;
      parts.add('${order.feePartLabels[k] ?? k} ${(v / 100).toStringAsFixed(2)}');
    });
    return parts.join(' · ');
  }

  /// 疲劳状态(null = 未取到/未上线)
  Map<String, dynamic>? _fatigue;

  Future<void> _refresh() async {
    try {
      // 服务端已按「综合分 = 距离 - 等待加权」排好(顺路信息也来自服务端),
      // 客户端不再自行重排,避免把等久的老单永远压在底部
      // with_meta 版:除了单子还带回「被你自己的偏好挡掉了几单」。
      // 挡掉的单还在池子里等别人抢 —— 不说出来,骑手只会以为"今天没单"
      final pool = _online
          ? await widget.api.availablePool()
          : (
              items: <Order>[],
              filteredByPrefs: 0,
              hasLocation: true,
              stalePrefs: const <String>[],
              waitCompOn: true,
            );
      final available = pool.items;
      _filteredByPrefs = pool.filteredByPrefs;
      _stalePrefs = pool.stalePrefs;
      _waitCompOn = pool.waitCompOn;
      final mine = await widget.api.myOrders();
      // 疲劳提醒:只提醒不断单(见服务端 labor_guard)。
      // 取不到就不显示 —— 疲劳提示挂了不该影响接单
      if (_online) {
        try {
          _fatigue = await widget.api.riderFatigue();
        } catch (_) {
          _fatigue = null;
        }
      } else {
        _fatigue = null;
      }

      // 今日所得 30 秒拉一次:它是服务端聚合,不跟着 5 秒的抢单池一起刷
      if (_worklogAt == null ||
          DateTime.now().difference(_worklogAt!).inSeconds >= 30) {
        try {
          _worklog = await widget.api.riderWorklog();
          _worklogAt = DateTime.now();
        } catch (_) {} // 拉不到就显示「—」,不挡抢单
      }

      // 新的可抢订单出现 → 响铃 + 振动 + 推一张单子上来。
      // 首轮加载不响(上线那一刻池子里的单都是「新」的,全响一遍就是炸铃)
      final fresh = available
          .where((o) => !_seenOrderNos.contains(o.orderNo))
          .toList();
      _seenOrderNos.addAll(available.map((o) => o.orderNo));
      if (!_firstLoad && _online && fresh.isNotEmpty && mounted) {
        _announce(fresh);
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
          _lastRefreshOkAt = DateTime.now();
          _refreshError = '';
        });
      }
      await _refreshUnread();
    } catch (e) {
      // **一个字都不说是不行的。**
      //
      // 原来这里是 `catch (_) {}`:骑手在电梯里、在地库里打开 App,
      // 抢单页一片空白 —— 和"现在真的没单"长得一模一样;
      // 切到「我的」,手上明明有单,页面写着"没有进行中的配送"。
      //
      // 失败**不清空已有的列表**(上一次的结果比空列表安全),
      // 只记下错误和最后一次成功的时间,由 [_refreshStale] 决定怎么说。
      if (mounted) {
        setState(() =>
            _refreshError = e is ApiException ? e.message : '$e');
      }
    }
  }

  /// 从来没成功拉到过数据。首次失败**不能**和"没有数据"共用一个界面
  bool get _neverLoaded => _lastRefreshOkAt == null;

  /// 数据是不是"陈"了。超过 1 分钟没成功刷新就算 ——
  /// 前台 5 秒一轮,连着失败十几次说明是真出问题了(和商家端同一口径)
  bool get _refreshStale {
    if (_lastRefreshOkAt == null) return _refreshError.isNotEmpty;
    return DateTime.now().difference(_lastRefreshOkAt!).inSeconds > 60;
  }

  /// 顶部警示条:**列表还有旧数据能看,但它可能已经不对了**
  Widget _staleBanner(String what) {
    if (!_refreshStale || _neverLoaded) return const SizedBox.shrink();
    final mins = DateTime.now().difference(_lastRefreshOkAt!).inMinutes;
    return SzRetryBanner(
      text: '$what已经 $mins 分钟没刷新成功了,下面是旧的。点这里重试',
      onRetry: _refresh,
    );
  }

  /// 定位异常横幅。
  ///
  /// 说的是**后果**不是现象:骑手不关心"位置流终止了",
  /// 他要知道的是"这会让你收不到单/顾客看不到你走到哪儿了"
  Widget? _gpsBanner() {
    final problem = _gpsProblem;
    if (problem == null || !_online) return null;
    final sz = Theme.of(context).sz;
    return Material(
      color: sz.danger.withValues(alpha: .12),
      child: InkWell(
        onTap: () => _toggleOnline(true), // 重新走一遍定位启动
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Row(children: [
            Icon(Icons.location_off, size: 18, color: sz.danger),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                  '$problem\n定位不准的时候,按距离筛的单会漏掉,顾客也看不到你走到哪儿了。点这里重开定位',
                  style: TextStyle(
                      fontSize: 12.5, height: 1.4, color: sz.danger)),
            ),
          ]),
        ),
      ),
    );
  }

  /// 定位状态变了才 setState —— 保活定时器 15 秒一跳,不判重会一直重建
  void _setGpsProblem(String? message) {
    if (_gpsProblem == message) return;
    if (!mounted) {
      _gpsProblem = message;
      return;
    }
    setState(() => _gpsProblem = message);
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
      builder: (context) => SzDialog(
        title: const Text('🆘 紧急求助'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            Expanded(
              child: FilledButton.icon(
                style: FilledButton.styleFrom(backgroundColor: Theme.of(context).sz.danger),
                icon: const Icon(Icons.emergency),
                label: const Text('110'),
                onPressed: () => launchUrl(Uri.parse('tel:110')),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: FilledButton.icon(
                style: FilledButton.styleFrom(backgroundColor: Theme.of(context).sz.hold),
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
              style: FilledButton.styleFrom(backgroundColor: Theme.of(context).sz.danger),
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

  // ---------- 实名认证状态(跑单前置,不挡浏览) ----------
  RiderProfile? _verify;

  Future<void> _loadVerify() async {
    try {
      final p = await widget.api.riderProfile();
      if (mounted) setState(() => _verify = p);
    } catch (_) {} // 拉不到状态不挡首页,上线/抢单时服务端仍会兜底校验
  }

  /// 跑单动作前置校验:未认证弹窗引导,审核中提示等待。返回 true = 放行
  Future<bool> _ensureVerified() async {
    final p = _verify;
    if (p != null && p.isApproved) return true;
    if (p != null && p.status == 'pending') {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('实名认证审核中,通过后即可上线接单')));
      return false;
    }
    final go = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: const Text('跑单需要先完成实名认证'),
        content: Text(p != null && p.status == 'rejected'
            ? '上次认证被驳回:${p.rejectReason}\n修改后重新提交即可'
            : '按监管要求,接单配送需实名(身份证+健康证)。'
              '提交后平台尽快审核,通过即可开跑。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('再逛逛')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('去认证')),
        ],
      ),
    );
    if (go == true && mounted) {
      await Navigator.of(context).push(MaterialPageRoute(
          builder: (_) => RiderVerifyFlowPage(api: widget.api)));
      _loadVerify();
    }
    return false;
  }

  /// 首页横幅:未认证/审核中/被驳回时常驻提示(通过后消失)
  Widget? _verifyBanner() {
    final p = _verify;
    if (p == null || p.isApproved) return null;
    final sz = Theme.of(context).sz;
    final (text, color) = switch (p.status) {
      'pending' => ('实名认证审核中,通过后即可上线接单', sz.inkMuted),
      'rejected' => ('认证被驳回:${p.rejectReason} · 点击重新提交', sz.danger),
      _ => ('完成实名认证(身份证+健康证),即可开始接单赚钱 →', sz.clay),
    };
    return InkWell(
      onTap: () async {
        await Navigator.of(context).push(MaterialPageRoute(
            builder: (_) => RiderVerifyFlowPage(api: widget.api)));
        _loadVerify();
      },
      child: Container(
        width: double.infinity,
        color: color.withValues(alpha: 0.10),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        child: Row(children: [
          Icon(Icons.verified_user_outlined, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(
              child: Text(text,
                  style: TextStyle(color: color, fontSize: 13,
                      fontWeight: FontWeight.w600))),
        ]),
      ),
    );
  }

  Future<void> _toggleOnline(bool value) async {
    if (value && !await _ensureVerified()) return;
    final ({String warning, String autoPrefHint}) res;
    try {
      res = await widget.api.setOnline(value);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(e.toString())));
      return;
    }
    setState(() => _online = value);

    // 服务端这两句以前被 setOnline 的 void 返回值吞掉了。
    //
    // autoPrefHint = 平台这次替他改了什么(新手默认收窄半径)——
    // 不说的话就是静默给人设了个筛选,他只会觉得"今天怎么单少了",
    // 而这正是我们刚修过的那类问题。
    if (mounted && res.autoPrefHint.isNotEmpty) {
      setState(() => _grabRadiusKm = 3); // 和服务端 NOVICE_RADIUS_KM 一致
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(res.autoPrefHint),
        duration: const Duration(seconds: 7),
        action: SnackBarAction(label: '去改', onPressed: _openPrefs),
      ));
    } else if (mounted && res.warning.isNotEmpty) {
      // 培训宽限提醒。不挡上线 —— 挡了就是让他今天没饭吃
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(res.warning),
        duration: const Duration(seconds: 7),
      ));
    }

    if (value) {
      // 商店合规:首次调系统定位弹窗前先说明目的
      final String? error;
      if (mounted &&
          !await PermissionRationale.ensure(
              context, AppPermissionKind.locationRider)) {
        error = '未授予定位权限,无法记录配送轨迹';
      } else {
        // 定位流中途断掉(关定位/进地库/权限被撤)也要被人知道 ——
        // 在此之前它是静默终止的:订阅死了,界面上什么都不变
        _location.onError = (message) {
          _gpsActive = false;
          _setGpsProblem(message);
        };
        // 真实 GPS:移动 10 米上报一次
        error = await _location.start(_report);
      }
      _gpsActive = error == null;
      _setGpsProblem(null);
      if (error != null && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('$error(先用演示坐标继续)')));
      }
      _keepaliveTimer?.cancel();
      // 静止时每 15 秒保活一次,防止后台位置过期;GPS 不可用则上报兜底坐标。
      //
      // ⚠️ **过期的坐标绝对不能报。** 定位死掉之后 `lastFix` 会一直停在
      // 最后一个点上,原来这里照报不误 —— 服务端于是每 15 秒收到一次
      // "他还在这儿",那套「位置过期就停用接单半径筛选」的保护
      // **永远不会触发**。骑手被一个假心跳挡在筛选外面,还以为是没单。
      //
      // 宁可不报:不报会让服务端的位置自然过期,保护按设计生效。
      _keepaliveTimer = Timer.periodic(const Duration(seconds: 15), (_) {
        final fix = _location.lastFix;
        switch (keepAliveDecision(fix: fix, gpsActive: _gpsActive)) {
          case PositionReport.fix:
            _setGpsProblem(null);
            _report(fix!.lat, fix.lng);
          case PositionReport.fallback:
            _report(fallbackLat, fallbackLng);
          case PositionReport.waiting:
            _setGpsProblem('定位还没拿到第一个点');
          case PositionReport.stale:
            final mins = DateTime.now().difference(fix!.at).inMinutes;
            _setGpsProblem('定位已经 $mins 分钟没更新了,位置可能是旧的');
        }
      });
      if (!_gpsActive) _report(fallbackLat, fallbackLng);
    } else {
      _location.stop();
      _keepaliveTimer?.cancel();
      _keepaliveTimer = null;
      _setGpsProblem(null);
    }
    // 上线后的第一轮只记下池子里已有的单,不当新单响铃。
    // 原来这个标志在 initState 那一轮(下线状态、池子是空的)就用掉了,
    // 于是一上线,池子里现有的每一单都被当成新单:铃响、弹层
    if (value) _firstLoad = true;
    _refresh();
  }

  /// 正在抢的单号:抢单是最会手快连点的场景,没有这个标志的话
  /// 第一次成功、第二次被服务端拒绝,骑手会看到一个错误提示以为没抢到。
  /// 商家「接单」和用户「提交订单」都有防重标志,这里原先漏了。
  final Set<String> _grabbing = {};

  /// 抢单。成功后按钮换成「已抢到」停 [SzSuccessSwap.hold](动效规范 06),
  /// 再切到「进行中」—— 原来是一条 SnackBar + 立刻跳走,
  /// 骑手手指还没离开屏幕页面就换了,常常以为自己没点上又点一次。
  Future<void> _grab(Order order, {bool fromOffer = false}) async {
    if (_grabbing.contains(order.orderNo)) return;
    if (!await _ensureVerified()) {
      if (fromOffer && mounted) setState(() => _offer = null);
      return;
    }
    if (!mounted) return;
    setState(() => _grabbing.add(order.orderNo));
    try {
      await widget.api.grabOrder(order.orderNo);
      if (!mounted) return;
      setState(() {
        _grabbing.remove(order.orderNo);
        if (fromOffer) {
          _offerGrabbed = true;
        } else {
          final at = _sortedAvailable.indexWhere((o) => o.orderNo == order.orderNo);
          _grabbedOrder = order;
          _grabbedIndex = at < 0 ? 0 : at;
        }
      });
      _refresh();
      await Future<void>.delayed(SzSuccessSwap.hold);
      if (!mounted) return;
      setState(() {
        if (fromOffer) {
          _offer = null;
          _offerGrabbed = false;
        }
        _grabbedOrder = null;
        _tab = 1;
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
      setState(() {
        if (fromOffer) _offer = null;
      });
      _refresh();
    } finally {
      if (mounted) setState(() => _grabbing.remove(order.orderNo));
    }
  }

  /// 新单来了:按「新单提醒」的设置响一声、震一下,再把最值得看的那一单
  /// 推上来(设计稿 5c)。
  ///
  /// 只响不弹的三种情况:屏幕上已经有一张新单弹层;页面上压着别的东西
  /// (取餐核验、地图、设置页 —— 一张单子盖在另一件正在做的事上,
  /// 比漏看一张单更容易出错);疲劳到了「降频」档(labor_guard 的本意是让人歇)。
  void _announce(List<Order> fresh) {
    if (_alerts.sound) SystemSound.play(SystemSoundType.alert);
    if (_alerts.vibrate) HapticFeedback.vibrate();
    final throttled = _fatigue?['level'] == 'throttle';
    final covered = !(ModalRoute.of(context)?.isCurrent ?? true);
    if (_offer != null || throttled || covered) return;
    // 按骑手当前选的看法取第一单:他选了「配送费高」,就推最贵的那张
    final ordered = _sortOrders(fresh);
    if (ordered.isEmpty) return;
    setState(() {
      _offer = ordered.first;
      _offerGrabbed = false;
    });
  }

  /// 进行中各单的未读消息数。只在「进行中」那一页上拉,15 秒一次 ——
  /// 五秒一轮的抢单池刷新里每单再打一个请求不值当
  Future<void> _refreshUnread() async {
    if (_tab != 1 || _mine.isEmpty) return;
    if (_unreadAt != null &&
        DateTime.now().difference(_unreadAt!).inSeconds < 15) {
      return;
    }
    _unreadAt = DateTime.now();
    final out = <String, int>{};
    await Future.wait(_mine.take(5).map((o) async {
      try {
        out[o.orderNo] = await widget.api.orderUnread(o.orderNo);
      } catch (_) {}
    }));
    if (mounted) setState(() => _unread = out);
  }

  /// 送达:保护单引导拍照留证(深夜强制,白天可选,放门口拍一张)
  /// 送达。先问**交付方式**,放门口才要照片(#303)。
  ///
  /// 原来的判据是"这单是不是地址保护单",维度用错了:
  ///
  /// - **当面交给顾客**:有人接了就是证据,拍照多余,而且尴尬 ——
  ///   举着手机拍一个正在接餐的人,谁都不舒服;
  /// - **放门口**:没有人证,照片是你唯一的自保。顾客三天后说没收到,
  ///   没照片就是各执一词。
  ///
  /// 所以当面交付一律不拦(赶时间的时候多一道手续,收益只有一张
  /// 没人会看的照片),放门口一律要拍 —— 白天放门口也一样说不清。
  Future<void> _deliver(Order order) async {
    var photoUrl = '';
    final handoff = await showDialog<String>(
      context: context,
      builder: (context) => SzDialog(
        title: const Text('怎么交付的?'),
        content: const Text('放门口请拍一张照片 —— '
            '万一顾客说没收到,这张照片替你说话。\n\n'
            '照片只有这一单的顾客和平台看得到。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, 'hand'),
              child: const Text('当面交给顾客')),
          FilledButton(
              onPressed: () => Navigator.pop(context, 'leave'),
              child: const Text('放门口,去拍照')),
        ],
      ),
    );
    if (handoff == null || !mounted) return;
    if (handoff == 'leave') {
      if (!await PermissionRationale.ensure(context, AppPermissionKind.camera,
          reason: '用于拍摄送达凭证照片。\n拒绝不影响其他功能。')) {
        return;
      }
      try {
        final picked = await ImagePicker().pickImage(
            source: ImageSource.camera, maxWidth: 1280, imageQuality: 80);
        if (picked == null) return;
        final bytes = await picked.readAsBytes();
        // 送达留证:拍的是别人家门口,只有该单顾客和平台看得到(#124)
        photoUrl = await widget.api
            .uploadImage(bytes, picked.name, purpose: 'delivery_proof');
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.toString())));
        return;
      }
    }
    // 放门口却没拍成(相机权限没给、取消了):**不提交**。
    // 服务端会拒(422),但在这儿就说清楚比让他吃一个报错好
    if (handoff == 'leave' && photoUrl.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('放门口的单要有照片才能点送达;'
                '当面交给顾客的话选「当面交给顾客」')));
      }
      return;
    }
    // 送达同样按单号防重:拍照上传后有一段等待,这期间很容易再点一下
    if (_grabbing.contains(order.orderNo)) return;
    if (mounted) setState(() => _grabbing.add(order.orderNo));
    try {
      await widget.api.transition(order.orderNo, OrderStatus.delivered,
          photoUrl: photoUrl, handoff: handoff);
      _refresh();
      // 送到之后再问"这单好不好送"(#301)。**先把餐送到,再说钱的事** ——
      // 送达前弹这个是在他赶时间的时候加手续。
      // 可以直接关掉,不填不影响任何东西
      if (mounted) {
        await HardshipSheet.show(context, widget.api, order.orderNo);
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _grabbing.remove(order.orderNo));
    }
  }

  /// 地址不准反馈:只沉淀不追责,攒两条用户下单会收到核对提示
  Future<void> _reportAddress(Order order) async {
    final note = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
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
  /// 帮送没拍物品照就点「已取件」时提醒一次,但**不拦**。
  ///
  /// 拦住的代价是骑手站在楼道里被一个弹窗卡住整单,
  /// 而不拍的代价是万一起纠纷双方各执一词 —— 后者他自己承担,
  /// 所以说清楚就够了,不该由平台替他决定。
  Future<void> _pickUpErrandAware(Order order) async {
    if (order.isErrand &&
        !order.isErrandBuy &&
        order.pickupPhotoUrl.isEmpty) {
      final go = await showDialog<bool>(
        context: context,
        builder: (dlg) => SzDialog(
          title: const Text('还没拍物品照'),
          content: const Text('东西是顾客的,平台不做保价 —— '
              '万一说少了件或者磕坏了,没有照片双方只能各执一词。\n\n'
              '拍一张只要几秒,拍完再取件。'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dlg, true),
                child: const Text('不拍了,直接取件')),
            FilledButton(
                onPressed: () => Navigator.pop(dlg, false),
                child: const Text('去拍一张')),
          ],
        ),
      );
      if (!mounted) return;
      if (go != true) {
        await _uploadPickupPhoto(order);
        return;
      }
    }
    // 跑腿单直接取件,不弹「取餐核验」。
    //
    // 那个核验对的是**小票上的单号尾号**,而跑腿没有商家、没有小票 ——
    // 让骑手去核对一个不存在的东西,他只能去点「核验不了?强制取餐」,
    // 于是每一单跑腿取件都在服务端留下一条「强制取餐(未通过尾号核验)」。
    // 那条记录是给"拿错别人的餐"追溯用的,不该被跑腿单填满
    if (order.isErrand) {
      try {
        await widget.api.transition(order.orderNo, OrderStatus.pickedUp);
        if (!mounted) return;
        await _refresh();
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(e is ApiException ? e.message : '$e')));
      }
      return;
    }
    await _pickUp(order);
  }

  Future<void> _pickUp(Order order) async {
    final code = TextEditingController();
    var error = '';
    var failures = 0;
    var submitting = false;
    final done = await szShowSheet<bool>(
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

  /// 标记到店。等餐时长 = 取餐时刻 − 到店时刻,是**申诉超时时的证据**。
  ///
  /// 带上当前坐标让服务端校验一下(离店太远会被拒,防随手乱点把证据搞脏);
  /// 没定位就不带 —— 定位取不到不该让人连到店都标不了。
  Future<void> _markArrived(Order order) async {
    try {
      await widget.api.markArrivedShop(order.orderNo,
          lat: _riderPosition.value?.lat, lng: _riderPosition.value?.lng);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('已记录到店时间 —— 等餐太久时这是你的凭据')));
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  /// 帮买:填小票实付 + 传照片。
  ///
  /// 超出可自行垫付的上限时服务端会拒,并提示先点「要多花钱」问顾客 ——
  /// **骑手不该被迫做"超了一点点先垫上"这个判断题**,
  /// 那是把平台的规则缺失转嫁给收入最低的那个人。
  Future<void> _submitReceipt(Order order) async {
    final amount = TextEditingController(
        text: (order.goodsBudgetCents / 100).toStringAsFixed(2));
    String? photo;
    final ok = await szShowSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (sheet) => StatefulBuilder(
        builder: (sheet, setSheet) => Padding(
          padding: EdgeInsets.only(
              left: 16, right: 16, top: 16,
              bottom: MediaQuery.of(sheet).viewInsets.bottom + 16),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text('填小票 · ${order.orderNo.substring(order.orderNo.length - 6)}',
                style: Theme.of(sheet).textTheme.titleMedium),
            Text('顾客预估 ${yuan(order.goodsBudgetCents)};'
                '小票顾客也看得到,照实填就行',
                style: Theme.of(sheet).textTheme.bodySmall),
            const SizedBox(height: 8),
            TextField(
              controller: amount,
              keyboardType:
                  const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: '小票实付(元)', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                icon: const Icon(Icons.photo_camera_outlined, size: 18),
                onPressed: () async {
                  try {
                    final picked = await ImagePicker().pickImage(
                        source: ImageSource.camera,
                        maxWidth: 1280, imageQuality: 80);
                    if (picked == null) return;
                    final bytes = await picked.readAsBytes();
                    // 小票是对账依据,顾客也看得到 —— 与送达留证同一条
                    // 可见性口径(该单当事人 + 平台)
                    final url = await widget.api.uploadImage(
                        bytes, picked.name, purpose: 'delivery_proof');
                    setSheet(() => photo = url);
                  } catch (e) {
                    if (!sheet.mounted) return;
                    ScaffoldMessenger.of(sheet).showSnackBar(
                        SnackBar(content: Text('$e')));
                  }
                },
                label: Text(photo == null ? '拍小票' : '已拍 ✓'),
              ),
            ),
            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: photo == null
                    ? null
                    : () => Navigator.pop(sheet, true),
                child: const Text('提交'),
              ),
            ),
          ]),
        ),
      ),
    );
    if (ok != true || photo == null || !mounted) return;
    final cents = ((double.tryParse(amount.text) ?? 0) * 100).round();
    try {
      await widget.api.submitReceipt(order.orderNo,
          actualCents: cents, receiptUrl: photo!);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('小票已提交,多退少补由平台处理')));
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      // 超上限时服务端会 409。**光把它的话显示出来是不够的** ——
      // 提示里写着"先问顾客",而骑手手上并没有"问"这个按钮:
      // 小票交不了,加价也发不出,这一单就卡死在超市里了。
      // 所以直接把 409 转成入口,他站在收银台前一下就能问出去
      if (e is ApiException && e.statusCode == 409) {
        await _requestRaise(order, cents, e.message);
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(e is ApiException ? e.message : '$e'),
          duration: const Duration(seconds: 8)));
    }
  }

  /// 帮买:超出可自行垫付的上限,发起「要多花钱」确认。
  ///
  /// 上限是多少**不在这里算**。同一条规则在客户端再实现一遍,
  /// 迟早会和服务端分叉,而分叉的那天没人会发现 ——
  /// 所以由服务端拒绝、客户端只负责把拒绝变成一个可点的入口。
  Future<void> _requestRaise(Order order, int cents, String why) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (dlg) => SzDialog(
        title: const Text('要多花钱,先问顾客'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(why),
          const SizedBox(height: 8),
          Text('会告诉顾客这一单要 ${yuan(cents)}(他预估 '
              '${yuan(order.goodsBudgetCents)})。'
              '他同意了你再买 —— 别自己垫。'),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dlg, false),
              child: const Text('先不问')),
          FilledButton(
              onPressed: () => Navigator.pop(dlg, true),
              child: const Text('问顾客')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await widget.api.requestRaise(order.orderNo, cents);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('已问顾客,等他回复;同意了再买')));
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  /// 帮送:取件拍照。东西是顾客的,平台既不知道原样也不做保价,
  /// 出了丢件/损坏纠纷,这张照片是唯一能说明「拿到手时是什么样」的东西。
  ///
  /// 不卡取件 —— 人在楼道里手忙脚乱,卡住照片等于卡住整单。
  /// 但没拍就点已取件时要把后果说清楚:到时候双方只能各执一词。
  Future<void> _uploadPickupPhoto(Order order) async {
    try {
      final picked = await ImagePicker().pickImage(
          source: ImageSource.camera, maxWidth: 1280, imageQuality: 80);
      if (picked == null) return;
      final bytes = await picked.readAsBytes();
      // 与送达留证同一条可见性口径(该单当事人 + 平台)
      final url = await widget.api
          .uploadImage(bytes, picked.name, purpose: 'delivery_proof');
      await widget.api.uploadPickupPhoto(order.orderNo, url);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('物品照已存,丢件纠纷时以它为准')));
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  /// 帮买:到店发现没货。商品款全额退顾客,跑腿费只收到店那一段 ——
  /// 你确实跑了这一趟,不白跑
  Future<void> _markUnavailable(Order order) async {
    final note = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (dlg) => SzDialog(
        title: const Text('买不到?'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('商品款会全额退给顾客,跑腿费只收到店那一段的距离费 ——'
              '你确实跑了这一趟,不白跑。'),
          const SizedBox(height: 8),
          TextField(
            controller: note,
            decoration: const InputDecoration(
                hintText: '说一句什么情况(如:货架空了)',
                border: OutlineInputBorder()),
          ),
        ]),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(dlg, false),
              child: const Text('再找找')),
          FilledButton(
              onPressed: () => Navigator.pop(dlg, true),
              child: const Text('确认买不到')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await widget.api.markUnavailable(order.orderNo, note.text.trim());
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('已按买不到处理,商品款全额退顾客')));
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  /// 「我到收货点了」。
  ///
  /// 到这一下到点送达之间的时长,花在找门牌、等门禁、等电梯、爬楼、
  /// 打电话让人下来上面 —— 这是"场景难度"唯一可测量的部分,
  /// 而在这之前平台对这几分钟一无所知。
  ///
  /// 提示文案要说清楚这个数**不用来考核他**:有了时长数据之后,
  /// "送得慢的骑手"是一个非常容易顺手做出来的指标,而平台不做骑手评分。
  /// 不说清楚,他会以为自己被掐表了,然后开始提前点。
  Future<void> _markArrivedDrop(Order order) async {
    try {
      await widget.api.markArrivedDrop(order.orderNo,
          lat: _riderPosition.value?.lat, lng: _riderPosition.value?.lng);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('已记录到达时间。这段时间只用来了解这个点位难不难送,'
              '不考核你'),
          duration: Duration(seconds: 5)));
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
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
    final ok = await szShowSheet<bool>(
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
                            if (!await PermissionRationale.ensure(
                                sheetContext, AppPermissionKind.camera,
                                reason: '用于拍摄配送异常的现场照片。\n拒绝不影响其他功能。')) {
                              return;
                            }
                            final picked = await ImagePicker().pickImage(
                                source: ImageSource.camera,
                                maxWidth: 1280,
                                imageQuality: 85);
                            if (picked == null) return;
                            setSheet(() => uploading = true);
                            try {
                              final bytes = await picked.readAsBytes();
                              final url = await widget.api
                                  .uploadImage(bytes, picked.name,
                                      purpose: 'incident');
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
    final ok = await szShowSheet<bool>(
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

  /// 疲劳提示条(#144)。**只提醒,不断单** ——
  /// 骑手要吃饭,一刀切断人家收入是另一种不尊重;但平台不能装作没看见。
  Widget _fatigueBar() {
    final msg = _fatigue?['message'] as String?;
    if (msg == null || msg.isEmpty) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    final throttle = _fatigue?['level'] == 'throttle';
    return Container(
      margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
      decoration: BoxDecoration(
        color: (throttle ? sz.hold : sz.earn).withValues(alpha: .10),
        borderRadius: BorderRadius.circular(kRadiusSm),
      ),
      child: Row(children: [
        Icon(throttle ? Icons.bedtime_outlined : Icons.local_cafe_outlined,
            size: 17, color: throttle ? sz.hold : sz.earn),
        const SizedBox(width: 8),
        Expanded(
          child: Text(msg,
              style: TextStyle(fontSize: 12.5, height: 1.4, color: sz.ink)),
        ),
      ]),
    );
  }

  /// 按当前看法排好的抢单池。
  ///
  /// 综合 = **原样用服务端的顺序**,不在客户端重排 —— 那个顺序里
  /// 含了顺路增量、等待时长加权这些客户端算不出来的东西。
  /// 其余几档是骑手自己要的单一维度。缺字段的排最后:服务端拿不到定位时
  /// distance_m 是空的,把它们当成 0 会顶到最前面,而那是**最没把握**的几单。
  List<Order> _sortOrders(List<Order> src) {
    final list = [...src];
    double toShop(Order o) =>
        o.distanceM?.toDouble() ?? _distanceToShop(o) ?? double.infinity;
    switch (_sort) {
      case HallSort.composite:
        return list;
      case HallSort.nearest:
        list.sort((a, b) => toShop(a).compareTo(toShop(b)));
      case HallSort.highFee:
        list.sort((a, b) => HallOrderCard.riderTakeCents(b)
            .compareTo(HallOrderCard.riderTakeCents(a)));
      case HallSort.sameWay:
        // 同店 > 顺路(绕得少的在前)> 其余按服务端原序
        int rank(Order o) => o.sameShop ? 0 : (o.sameWay ? 1 : 2);
        list.sort((a, b) {
          final r = rank(a).compareTo(rank(b));
          if (r != 0) return r;
          return (a.detourM ?? 1 << 30).compareTo(b.detourM ?? 1 << 30);
        });
      case HallSort.errand:
        return list.where((o) => o.isErrand).toList();
    }
    return list;
  }

  List<Order> get _sortedAvailable => _sortOrders(_available);

  /// 「费高」的门槛:眼前这些单里骑手实得排前四分之一的那一档。
  ///
  /// 服务端没有这个标 —— 它是**相对于大厅里此刻这些单**的,不是一个绝对价。
  /// 少于 4 单不标(三单里挑一个「费高」没有意义);大家都一个价也不标。
  int? get _highFeeCents {
    if (_available.length < 4) return null;
    final fees = _available.map(HallOrderCard.riderTakeCents).toList()..sort();
    final q = fees[(fees.length * 3) ~/ 4];
    return q > fees[fees.length ~/ 2] ? q : null;
  }

  HallTag _tagFor(Order o) {
    if (o.sameShop || o.sameWay) return HallTag.sameWay;
    final hi = _highFeeCents;
    if (hi != null && HallOrderCard.riderTakeCents(o) >= hi) {
      return HallTag.highFee;
    }
    return HallTag.open;
  }

  /// 「380m」:有服务端算的骑行距离就用它,没有才退回本地直线,并带「≈」
  /// —— 直线系统性低估(实测差 19%),不标出来骑手会按它判断「近」。
  ///
  /// 用紧凑单位(m / km):它挂在地址那一行的末尾,是一个角标位的数,
  /// 稿子上也是这么写的;句子里的距离仍然用中文单位(distanceLabel)
  String? _toShopText(Order o) {
    final routed = o.distanceM?.toDouble();
    final d = routed ?? _distanceToShop(o);
    if (d == null) return null;
    return routed == null ? '≈${distanceLabelShort(d)}' : distanceLabelShort(d);
  }

  String? _tripText(Order o) {
    final t = o.tripM?.toDouble() ?? _tripDistance(o);
    return t == null ? null : distanceLabelShort(t);
  }

  /// 抢单卡底部那一行:出餐状态、全程几分钟、时薪、跑腿费口径、配送费里的加价。
  ///
  /// 配送费构成(夜间 / 上楼 / 难度)是**接单前就摊开**的那条原则 ——
  /// 别家骑手端只给一个总数,骑手要跑到楼下才知道是 6 楼没电梯
  String _hallNote(Order o) {
    final parts = <String>[];
    if (o.isErrand) {
      parts.add('帮我送 · 跑腿费 ${yuan(o.deliveryFeeCents)} − 2%');
      if (o.errandNote.isNotEmpty) parts.add(o.errandNote);
    } else if (o.status == OrderStatus.ready) {
      parts.add('已出餐');
    } else if ((o.estWaitMinutes ?? 0) > 0) {
      // 稿子上写的是钟点(「出餐 12:01」),比「等餐约 29 分钟」好对表
      final t = DateTime.now().add(Duration(minutes: o.estWaitMinutes!.round()));
      parts.add('出餐约 ${_clock(t)}'
          '${o.waitSource == "declared" ? "(商家自报)" : ""}'
          // 等餐补偿关着时明说:这段时间算在耗时里,但没有钱
          '${_waitCompOn ? "" : "·等餐不计费"}');
    }
    if (o.estMinutes != null) parts.add('全程约 ${o.estMinutes!.round()} 分钟');
    if (o.centsPerMinute != null && o.centsPerMinute! > 0) {
      parts.add('≈¥${(o.centsPerMinute! * 60 / 100).toStringAsFixed(0)}/小时');
    }
    final extras = _feePartsLine(o, skipBase: true);
    if (extras.isNotEmpty) parts.add('含 $extras');
    if (o.remark.isNotEmpty) parts.add(o.remark);
    return parts.join(' · ');
  }

  /// 条件行:只在真有这件事时出现,不占固定高度
  List<({String text, Color color})> _alertsFor(Order o) {
    final sz = Theme.of(context).sz;
    return [
      if (o.scheduledLabel != null)
        (text: '预约单 · ${o.scheduledLabel}', color: sz.hold),
      // 被催标记:骑手端没有 WS、推送也可能没配 —— 轮询拉回来的这行字
      // 就是催单能到骑手眼前的唯一通道。提醒而不施压,安全永远在快前面
      if (o.urgeCount > 0)
        (
          text: '用户催了${o.urgeCount > 1 ? " ${o.urgeCount} 次" : ""},'
              '放心按安全速度骑',
          color: sz.hold
        ),
      if (o.parentOrderNo.isNotEmpty)
        (
          text: '追加单,随 #${o.parentOrderNo.substring(o.parentOrderNo.length - 6)}'
              ' 一起取送',
          color: sz.earn
        ),
      // 顺路**带上绕路多少米**,不给一句模糊的「顺路」
      if (o.sameShop)
        (text: '同店取餐 · 和手头单是一家店', color: sz.earn)
      else if (o.sameWay)
        (
          text: '${o.sameWayLevel == "strong" ? "强" : ""}顺路 · '
              '比只送手头单多跑约 ${o.detourM ?? 0} 米',
          color: sz.earn
        ),
      // 样本不足就直说不知道 —— 拿 3 单算出来的数摆给骑手看比不给更误导
      if (o.dropP75Minutes != null)
        (
          text: '这个点位送到手上平均还要 ${o.dropP75Minutes!.round()} 分钟'
              '(${o.dropSample} 单实测)',
          color: sz.inkMuted
        ),
      if (o.isErrandBuy && o.goodsRaiseStatus == 'pending')
        (
          text: '已问顾客能不能花 ${yuan(o.goodsRaiseCents ?? 0)},等他回复;别先垫钱',
          color: sz.hold
        ),
      if (o.isErrandBuy && o.goodsRaiseStatus == 'approved')
        (text: '顾客同意花到 ${yuan(o.goodsRaiseCents ?? 0)},可以买了', color: sz.earn),
      if (o.isErrandBuy && o.goodsRaiseStatus == 'rejected')
        (
          text: '顾客不同意多花钱 —— 按「买不到」处理,商品款全额退他,'
              '你的跑腿费照收到店那一段',
          color: sz.hold
        ),
      if (o.hasAlcohol) (text: '含酒精饮品,送达请查验收件人年龄', color: sz.hold),
      // 这个地方难在哪 —— 接单前就说(#301)。是跑过这里的骑手告诉我们的
      if (o.hardshipNote.isNotEmpty) (text: '难送:${o.hardshipNote}', color: sz.hold),
    ];
  }

  /// 新单弹层那一行:什么时候能出餐、顾客那边显示几点送到
  String _offerInfo(Order o) {
    final eta = o.etaClock;
    final parts = <String>[
      if (o.status == OrderStatus.ready)
        '已出餐'
      else if ((o.estWaitMinutes ?? 0) > 0)
        '预计出餐 ${_clock(DateTime.now().add(Duration(minutes: o.estWaitMinutes!.round())))}',
      if (eta != null) '用户参考送达 $eta',
    ];
    return parts.join('   ');
  }

  static String _clock(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  /// 接单半径:只看 N 公里内的单(顺路单豁免),服务端持久化。
  /// 原来在大厅里单独占一行,现在收进「接单偏好」面板的最上面
  Future<void> _setRadius(int? km) async {
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

  /// 「你设的筛选现在没生效」。
  ///
  /// 和下面 [_filteredHint] 是同一种病的两面:一个是**挡掉了你不知道**,
  /// 一个是**没挡住你也不知道**。后者更坏 —— 骑手以为自己只看 3 公里内,
  /// 实际收到的是全城,接了一单才发现要骑十公里。
  Widget _stalePrefHint() {
    if (_stalePrefs.isEmpty) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    const names = <String, String>{
      'grab_radius_km': '接单半径',
      'grab_same_way_only': '只看顺路',
      'go_home_on': '只看往回走的单',
    };
    final which = _stalePrefs.map((k) => names[k] ?? k).join('、');
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      child: Row(children: [
        Icon(Icons.location_off_outlined, size: 15, color: sz.danger),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
              '定位没拿到,「$which」现在没生效 —— 下面是全部的单,不是筛过的',
              style: TextStyle(fontSize: 12, height: 1.4, color: sz.danger)),
        ),
      ]),
    );
  }

  /// 「被你自己的设置挡掉了 N 单」。
  ///
  /// 这一条是接单偏好这个功能能不能做的**前提**:过滤器悄悄生效,
  /// 表现出来就是"今天怎么一直没单",而骑手不会想到去翻两个月前
  /// 设过的一个开关 —— 他只会觉得平台不给他派单。
  Widget _filteredHint() {
    if (_filteredByPrefs <= 0) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      child: Row(children: [
        Icon(Icons.filter_alt_outlined, size: 15, color: sz.inkMuted),
        const SizedBox(width: 6),
        Expanded(
          child: Text('另有 $_filteredByPrefs 单被你自己的接单偏好挡住了',
              style: TextStyle(fontSize: 12, color: sz.inkMuted)),
        ),
        TextButton(
          onPressed: _openPrefs,
          style: TextButton.styleFrom(
              visualDensity: VisualDensity.compact,
              padding: const EdgeInsets.symmetric(horizontal: 8)),
          child: const Text('去看看', style: TextStyle(fontSize: 12)),
        ),
      ]),
    );
  }

  /// 接单偏好设置面板。
  ///
  /// 每一项都写清楚"这只影响你看到什么" —— 骑手很容易把它理解成
  /// "平台按这个给我派单",然后指望调高下限就能多挣钱。
  Future<void> _openPrefs() async {
    try {
      _prefs = await widget.api.riderPreferences();
    } catch (_) {
      // 读不到就用手上这份(可能为空):设置页打不开比显示旧值更糟
    }
    if (!mounted) return;
    await szShowSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (sheet) => StatefulBuilder(builder: (sheet, setSheet) {
        Future<void> patch(Map<String, dynamic> body) async {
          try {
            final saved = await widget.api.updateRiderPreferences(body);
            setSheet(() => _prefs = saved);
            setState(() => _grabRadiusKm = saved['grab_radius_km'] as int?);
            _refresh();
          } catch (e) {
            if (!sheet.mounted) return;
            ScaffoldMessenger.of(sheet).showSnackBar(
                SnackBar(content: Text(e is ApiException ? e.message : '$e')));
          }
        }

        final minFee = (_prefs['grab_min_fee_cents'] as num?)?.toInt() ?? 0;
        // null = 没设过,用平台默认。和"设成 3"要能区分开 ——
        // 这两件事在界面上说的话不一样
        final myMaxActive = (_prefs['rider_max_active'] as num?)?.toInt();
        // 平台硬上限。服务端给,拿不到时按 3 兜底(和 config 默认一致)
        final maxActiveCap =
            (_prefs['max_active_cap'] as num?)?.toInt() ?? 3;
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Row(children: [
                Text('接单偏好',
                    style: Theme.of(sheet).textTheme.titleMedium),
                const Spacer(),
              ]),
              const Padding(
                padding: EdgeInsets.only(top: 4, bottom: 8),
                child: Text(
                    '下面除了「同时接单上限」,其余几项只改「你看到哪些单」。'
                    '被挡掉的单还在池子里等别人抢,平台不会因为你设了偏好'
                    '就少派单给你。',
                    style: TextStyle(fontSize: kFontNote)),
              ),
              Align(
                alignment: Alignment.centerLeft,
                child: Text('接单半径(顺路单不受限)',
                    style: Theme.of(sheet).textTheme.bodySmall),
              ),
              const SizedBox(height: 4),
              Wrap(spacing: 6, children: [
                for (final (km, label) in const [
                  (null, '不限'), (1, '1km'), (2, '2km'), (3, '3km'), (5, '5km'),
                ])
                  ChoiceChip(
                    label: Text(label),
                    visualDensity: VisualDensity.compact,
                    selected: _grabRadiusKm == km,
                    onSelected: (_) async {
                      await _setRadius(km);
                      setSheet(() {});
                    },
                  ),
              ]),
              // 总览图回答「这些单挨得近吗」,「怎么排的」回答「凭什么这么排」——
              // 两个都是看整个池子时才有的问题,和偏好放在一起
              Row(children: [
                TextButton.icon(
                  icon: const Icon(Icons.map_outlined, size: 18),
                  label: const Text('取餐点总览'),
                  onPressed: () => Navigator.of(sheet).push(
                      MaterialPageRoute<void>(
                          builder: (_) => RiderPoolMapPage(
                              orders: _sortedAvailable,
                              riderPosition: _riderPosition))),
                ),
                TextButton.icon(
                  icon: const Icon(Icons.help_outline, size: 18),
                  label: const Text('抢单怎么排的'),
                  onPressed: () => Navigator.of(sheet).push(
                      MaterialPageRoute<void>(
                          builder: (_) => DispatchSpecPage(api: widget.api))),
                ),
              ]),
              const Divider(height: 1),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _prefs['grab_same_way_only'] == true,
                onChanged: (v) => patch({'grab_same_way_only': v}),
                title: const Text('只看顺路单'),
                subtitle: const Text(
                    '下班捎一单的话开这个。手上没单时不生效 ——'
                    '那时无所谓顺不顺路',
                    style: TextStyle(fontSize: 12)),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _prefs['grab_avoid_alcohol'] == true,
                onChanged: (v) => patch({'grab_avoid_alcohol': v}),
                title: const Text('不看含酒的单'),
                subtitle: const Text('送达要查收件人年龄,不想沾这个麻烦就关掉',
                    style: TextStyle(fontSize: 12)),
              ),
              // 收工方向(#264):顺路按手上单算,而手上没单时它不生效 ——
              // 收工那一刻恰恰是手上快空了的时候。用当前位置当方向:
              // 骑手要回家时,人多半已经在往那边走了
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                value: _prefs['go_home_on'] == true,
                onChanged: (v) async {
                  if (!v) {
                    await patch({'go_home_on': false});
                    return;
                  }
                  // 没设过方向:用当前位置当方向。
                  // 用已有的 _location.lastFix,不另起一套定位请求
                  if (_prefs['go_home_lat'] == null) {
                    final fix = _location.lastFix;
                    if (fix == null) {
                      if (!sheet.mounted) return;
                      ScaffoldMessenger.of(sheet).showSnackBar(const SnackBar(
                          content: Text('还没拿到定位,没法设收工方向 —— '
                              '等一下或检查定位权限')));
                      return;
                    }
                    await patch({
                      'go_home': {'lat': fix.lat, 'lng': fix.lng},
                      'go_home_on': true,
                    });
                    return;
                  }
                  await patch({'go_home_on': true});
                },
                title: const Text('只看往回走的单(收工用)'),
                subtitle: const Text(
                    '按你现在的位置当方向。开着的时候只显示不绕远的单,'
                    '别忘了收工后关掉 —— 白天开着会一直只看一个方向',
                    style: TextStyle(fontSize: 12)),
              ),
              if (_prefs['go_home_lat'] != null)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    style: TextButton.styleFrom(
                        visualDensity: VisualDensity.compact,
                        padding: EdgeInsets.zero),
                    onPressed: () {
                      final fix = _location.lastFix;
                      if (fix == null) {
                        patch({'go_home': null});
                        return;
                      }
                      patch({
                        'go_home': {'lat': fix.lat, 'lng': fix.lng},
                        'go_home_on': true,
                      });
                    },
                    child: const Text('用现在的位置重设方向',
                        style: TextStyle(fontSize: 12)),
                  ),
                ),
              const SizedBox(height: 4),
              Align(
                alignment: Alignment.centerLeft,
                child: Text('同时最多接几单',
                    style: Theme.of(sheet).textTheme.bodySmall),
              ),
              // 这一项和上面几条**不一样**:它真的会拦住接单,
              // 不只是改你看到什么。所以副文案要单独说清楚。
              //
              // 档位上限跟服务端给的 max_active_cap 走,不写死 ——
              // 平台调这个常数时不该要求骑手更新 App
              Wrap(spacing: 6, children: [
                for (final n in [
                  null,
                  for (var i = 1; i <= maxActiveCap; i++) i,
                ])
                  ChoiceChip(
                    label: Text(n == null ? '默认($maxActiveCap)' : '$n 单',
                        style: const TextStyle(fontSize: 12)),
                    visualDensity: VisualDensity.compact,
                    selected: myMaxActive == n,
                    onSelected: (_) => patch({'rider_max_active': n}),
                  ),
              ]),
              const Padding(
                padding: EdgeInsets.only(top: 4, bottom: 4),
                child: Text(
                    '手头压太多单容易超时,而超时的差评算在你头上。'
                    '刚上手的话先设 1 单,顺了再往上加。',
                    style: TextStyle(fontSize: 11)),
              ),
              const SizedBox(height: 4),
              Align(
                alignment: Alignment.centerLeft,
                child: Text('低于这个价的不显示',
                    style: Theme.of(sheet).textTheme.bodySmall),
              ),
              Wrap(spacing: 6, children: [
                for (final (cents, label) in const [
                  (0, '不限'), (400, '4元'), (600, '6元'),
                  (800, '8元'), (1200, '12元'),
                ])
                  ChoiceChip(
                    label: Text(label, style: const TextStyle(fontSize: 12)),
                    visualDensity: VisualDensity.compact,
                    selected: minFee == cents,
                    onSelected: (_) => patch({'grab_min_fee_cents': cents}),
                  ),
              ]),
              const SizedBox(height: 8),
              const Text(
                  '想彻底歇一会儿就用上面的「下线」开关,别把下限拉满 ——'
                  '那样你会以为是平台没给你派单。',
                  style: TextStyle(fontSize: 11)),
            ]),
          ),
        );
      }),
    );
  }

  /// 同店多单时的批量条:「这家店的 3 单一起标到店 / 一起取餐」。
  ///
  /// 午高峰一家店压着三四单是常态,而「到店」这个动作**物理上只发生
  /// 一次** —— 站在店门口点三次,第三次点的时候等餐时长已经比第一次
  /// 少了半分钟,这个证据本身就被操作方式污染了。
  ///
  /// 只有真的同店多单才出现;一单的时候不显示,免得占掉一整行。
  Widget _batchBar() {
    final byShop = <int, List<Order>>{};
    for (final o in _mine) {
      if (o.status == OrderStatus.pickedUp) continue;
      if (o.parentOrderNo.isNotEmpty) continue; // 追加单随原单,不单独算
      byShop.putIfAbsent(o.merchantId, () => []).add(o);
    }
    final groups = byShop.entries.where((e) => e.value.length >= 2).toList();
    if (groups.isEmpty) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    return Column(
      children: [
        for (final g in groups)
          Card(
            margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
            color: sz.earn.withValues(alpha: .08),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
              child: Row(children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${g.value.first.merchantName} · ${g.value.length} 单',
                          style: const TextStyle(
                              fontSize: 13.5, fontWeight: FontWeight.w600)),
                      Text('同一家店,一次点完就行',
                          style: TextStyle(fontSize: 11, color: sz.inkMuted)),
                    ],
                  ),
                ),
                if (g.value.any((o) => o.arrivedShopAt.isEmpty))
                  OutlinedButton(
                      onPressed: () => _batch(g.key, arrived: true),
                      child: const Text('全到店')),
                if (g.value.any((o) => o.status == OrderStatus.ready)) ...[
                  const SizedBox(width: 8),
                  FilledButton(
                      onPressed: () => _batch(g.key, arrived: false),
                      child: const Text('全取餐')),
                ],
              ]),
            ),
          ),
      ],
    );
  }

  /// 逐单执行不整体回滚 —— 所以结果也要逐单说。
  /// 骑手站在店门口要的是"哪几单好了、哪单还得再点一下",不是一个 409。
  Future<void> _batch(int merchantId, {required bool arrived}) async {
    try {
      final fix = _location.lastFix;
      final r = arrived
          ? await widget.api.batchArrived(merchantId,
              lat: fix?.lat, lng: fix?.lng)
          : await widget.api.batchPicked(merchantId);
      if (!mounted) return;
      final failed = ((r['items'] as List?) ?? const [])
          .cast<Map<String, dynamic>>()
          .where((i) => i['ok'] != true)
          .toList();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(failed.isEmpty
            ? '${r['note']}'
            : '${r['note']};没成的:'
                '${failed.map((f) => "${f["order_no"]} ${f["reason"]}").join("、")}'),
        duration: Duration(seconds: failed.isEmpty ? 3 : 8),
      ));
      await _refresh();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e is ApiException ? e.message : '$e')));
    }
  }

  void _openMap(Order order) {
    Navigator.of(context).push(MaterialPageRoute(
        builder: (_) =>
            DeliveryMapPage(order: order, riderPosition: _riderPosition)));
  }

  /// 去下一站的外部导航:没取餐去店里,取了餐去送达点
  void _navigateTask(Order order) {
    final picked = order.status == OrderStatus.pickedUp;
    if (!picked && order.merchantLat != null && order.merchantLng != null) {
      navigateTo(context,
          lat: order.merchantLat!,
          lng: order.merchantLng!,
          name: order.merchantName,
          mode: NavMode.ride);
      return;
    }
    navigateTo(context,
        lat: order.lat, lng: order.lng, name: order.address, mode: NavMode.ride);
  }

  void _openChat(Order order) {
    Navigator.of(context)
        .push(MaterialPageRoute(
            builder: (_) => OrderChatPage(
                api: widget.api,
                orderNo: order.orderNo,
                quickReplies: kRiderQuickReplies)))
        .then((_) {
      _unreadAt = null; // 看完回来立刻刷一次未读数
      _refreshUnread();
    });
  }

  /// 任务卡上的动作:**一个主按钮**(下一步该做的那件事)+ 一排小字按钮。
  ///
  /// 状态 → 主按钮:
  /// - 商家还在做(accepted):没到店是「我到店了」;到了就是灰的「等商家出餐」
  ///   —— 取餐要等商家点出餐,按钮亮着点下去只会被服务端拒;
  /// - 已出餐(ready):「已取到餐」(跑腿是「已取到件」,不走小票尾号核验);
  /// - 已取餐(pickedUp):「已送达」。
  ///
  /// 「我到店了」「我到了」是等餐 / 送到手上那段时长的**证据**,不是必经步骤,
  /// 所以在 ready / pickedUp 时退到小字按钮里。
  List<TaskAction> _taskActions(Order order) {
    final busy = _grabbing.contains(order.orderNo);
    final arrived = order.arrivedShopAt.isNotEmpty;
    final arriveLabel = order.isErrand ? '我到取件点了' : '我到店了';
    final a = <TaskAction>[];
    switch (order.status) {
      case OrderStatus.accepted:
        a.add(arrived
            ? const TaskAction('等商家出餐', null, primary: true)
            : TaskAction(arriveLabel, () => _markArrived(order), primary: true));
      case OrderStatus.ready:
        a.add(TaskAction(order.isErrand ? '已取到件' : '已取到餐',
            busy ? null : () => _pickUpErrandAware(order),
            primary: true));
        // 帮买:先填小票再谈取件 —— 小票是这一单唯一的对账依据,顾客也看得到
        if (order.isErrandBuy && order.goodsActualCents == null) {
          a.add(TaskAction('填小票', () => _submitReceipt(order)));
          a.add(TaskAction('买不到', () => _markUnavailable(order)));
        }
        // 帮送:物品照。东西是顾客的,平台不做保价也不知道原样
        if (order.isErrand && !order.isErrandBuy) {
          a.add(TaskAction(order.pickupPhotoUrl.isEmpty ? '拍物品照' : '重拍物品照',
              () => _uploadPickupPhoto(order)));
        }
        if (!arrived) a.add(TaskAction(arriveLabel, () => _markArrived(order)));
      case OrderStatus.pickedUp:
        a.add(TaskAction(busy ? '提交中…' : '已送达',
            busy ? null : () => _deliver(order),
            primary: true));
        if (order.arrivedDropAt.isEmpty) {
          a.add(TaskAction('我到了', () => _markArrivedDrop(order)));
        }
        a.add(TaskAction('地址不准', () => _reportAddress(order)));
      default:
        break;
    }
    // 未取餐且非追加单可转单;追加单随原单一起转
    if (order.status != OrderStatus.pickedUp && order.parentOrderNo.isEmpty) {
      a.add(TaskAction('转单', () => _transferOrder(order)));
    }
    a.add(TaskAction('异常上报', () => _reportIssue(order)));
    a.add(TaskAction('全屏地图', () => _openMap(order)));
    return a;
  }

  /// 下线要不要先问一句:手上还有单的时候问 —— 下线只是不收新单,
  /// 手上的单照常送;不说清楚,骑手会以为下线就把手上的单丢了
  Future<void> _tapOnlinePill() async {
    if (_online && _mine.isNotEmpty) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (dlg) => SzDialog(
          title: const Text('下线?'),
          content: Text('手上还有 ${_mine.length} 单没送完。下线后不再收新单,'
              '手上的单照常送完。'),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(dlg, false),
                child: const Text('先不下线')),
            FilledButton(
                onPressed: () => Navigator.pop(dlg, true),
                child: const Text('下线')),
          ],
        ),
      );
      if (ok != true) return;
    }
    await _toggleOnline(!_online);
  }

  PreferredSizeWidget _hallAppBar() {
    final sz = Theme.of(context).sz;
    final city = _verify?.city ?? '';
    return AppBar(
      title: const Text('接单大厅'),
      actions: [
        SzStatePill(
          label: _online
              ? (city.isEmpty ? '在线' : '在线 · $city')
              : '已下线 · 点这里上线',
          on: _online,
          onTap: _tapOnlinePill,
        ),
        // SOS 在大厅右上角(稿子上这里只有状态 pill;求助入口不能因为对齐稿子而没了)。
        // 长按 3 秒才触发,防误触
        Tooltip(
          message: '长按 3 秒紧急求助',
          child: GestureDetector(
            onLongPress: _triggerSos,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(10, 12, 14, 12),
              child: Icon(Icons.sos, color: sz.danger),
            ),
          ),
        ),
      ],
    );
  }

  Widget _hallTab() {
    final sz = Theme.of(context).sz;
    final today = HallTodayCard(
      earnedCents: (_worklog?['today_earned_cents'] as num?)?.toInt(),
      orders: (_worklog?['today_orders'] as num?)?.toInt(),
      onOpenLedger: () => setState(() => _tab = 2),
    );
    if (!_online) {
      return RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 24),
          children: [
            today,
            const SizedBox(height: 48),
            Center(
              child: Text('现在是下线状态,不会收到新单',
                  style: TextStyle(fontSize: kFontBodyLg, color: sz.inkMuted)),
            ),
            const SizedBox(height: 16),
            Center(
              child: FilledButton(
                style: FilledButton.styleFrom(minimumSize: const Size(200, 52)),
                onPressed: () => _toggleOnline(true),
                child: const Text('上线接单'),
              ),
            ),
          ],
        ),
      );
    }
    var list = _sortedAvailable;
    final pinned = _grabbedOrder;
    if (pinned != null && !list.any((o) => o.orderNo == pinned.orderNo)) {
      list = [...list]..insert(_grabbedIndex.clamp(0, list.length), pinned);
    }
    return RefreshIndicator(
      onRefresh: () async {
        setState(() => _hallGen++);
        await _refresh();
      },
      child: ListView.builder(
        padding: const EdgeInsets.only(bottom: 24),
        itemCount: list.length + 1,
        itemBuilder: (context, i) {
          if (i == 0) {
            // 疲劳提示在最上面:它比任何一单都重要
            return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              _staleBanner('抢单池'),
              _fatigueBar(),
              Padding(
                padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 0),
                child: today,
              ),
              const SizedBox(height: 6),
              HallSortBar(
                value: _sort,
                onChanged: (s) => setState(() => _sort = s),
                onOpenPrefs: _openPrefs,
              ),
              _stalePrefHint(),
              _filteredHint(),
              if (list.isEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(kPagePad, 40, kPagePad, 0),
                  child: Column(children: [
                    Text(
                        _sort == HallSort.errand
                            ? '大厅里暂时没有帮我送的单'
                            : '大厅里暂时没有单',
                        style: TextStyle(
                            fontSize: kFontBodyLg, color: sz.inkMuted)),
                    const SizedBox(height: 6),
                    Text('有新单会响铃,并从底部推上来',
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ]),
                ),
              const SizedBox(height: 4),
            ]);
          }
          final o = list[i - 1];
          return Padding(
            key: ValueKey('$_hallGen-${o.orderNo}'),
            padding: const EdgeInsets.fromLTRB(kPagePad, 5, kPagePad, 4),
            child: SzEnter(
              index: i - 1,
              child: HallOrderCard(
                order: o,
                tag: _tagFor(o),
                toShopText: _toShopText(o),
                tripText: _tripText(o),
                note: _hallNote(o),
                alerts: _alertsFor(o),
                grabbing: _grabbing.contains(o.orderNo),
                grabbed: _grabbedOrder?.orderNo == o.orderNo,
                onGrab: () => _grab(o),
                onOpenRoute: () => _openMap(o),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _taskTab() => TaskPanel(
        orders: _mine,
        riderPosition: _riderPosition,
        actionsFor: _taskActions,
        alertsFor: _alertsFor,
        unread: _unread,
        onChat: _openChat,
        onCall: (o) => launchUrl(Uri.parse('tel:${o.privacyPhone}')),
        onSos: _triggerSos,
        onNavigate: _navigateTask,
        onGoHall: () => setState(() => _tab = 0),
        onRefresh: _refresh,
        api: widget.api,
        header: Column(mainAxisSize: MainAxisSize.min, children: [
          _staleBanner('配送列表'),
          _batchBar(),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final banner = _verifyBanner();
    final gpsBanner = _gpsBanner();
    // 首次就没拉到:**整页错误态**,绝不能让它长得像"今天没单"。
    // 有过一次成功就退回顶部横条 —— 旧列表还能看,别把能用的也拿走
    final firstLoadFailed = _neverLoaded && _refreshError.isNotEmpty;
    final Widget tabBody;
    if (firstLoadFailed && _tab <= 1) {
      tabBody = RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(children: [
          SizedBox(
            height: 360,
            child: SzError(
                error: _tab == 0
                    ? '抢单池没能加载出来:$_refreshError\n这不代表现在没有单'
                    : '你的配送单没能加载出来:$_refreshError\n'
                        '手上的单还在,只是这会儿显示不出来',
                onRetry: _refresh),
          ),
        ]),
      );
    } else {
      tabBody = switch (_tab) {
        0 => _hallTab(),
        1 => _taskTab(),
        2 => WalletPage(api: widget.api, period: _ledgerPeriod),
        _ => RiderProfilePage(
            api: widget.api,
            onOpenWallet: () => setState(() => _tab = 2),
            onOpenOrders: () => setState(() => _tab = 1),
            alerts: _alerts,
            onAlertsChanged: (p) => setState(() => _alerts = p),
          ),
      };
    }
    // 认证提示 + 定位异常横幅置顶(恢复后自动消失)。
    // 定位挂了影响的是**每一个** tab,所以放在页面级
    final banners = <Widget>[
      if (banner != null) banner,
      if (gpsBanner != null) gpsBanner,
    ];
    // 「进行中」「我的」两页没有标题栏(稿子上一个是满屏地图,一个是身份卡当页头),
    // 横幅得自己让开状态栏
    final noBar = _tab == 1 || _tab == 3;
    final page = banners.isEmpty
        ? tabBody
        : Column(children: [
            noBar
                ? SafeArea(bottom: false, child: Column(children: banners))
                : Column(children: banners),
            Expanded(
              child: noBar
                  ? MediaQuery.removePadding(
                      context: context, removeTop: true, child: tabBody)
                  : tabBody,
            ),
          ]);

    // 宽屏(≥600)换左侧栏(#295)。骑手端跑在手机上时几乎都是 compact,
    // 这一条主要为平板横屏和站点里架着看单的平板
    final scaffold = SzNavScaffold(
      selectedIndex: _tab,
      // 进行中是地图,用宽档;其余是单列信息流
      contentMaxWidth: _tab == 1 ? kWideMaxWidth : kContentMaxWidth,
      onSelected: (i) {
        setState(() => _tab = i);
        if (i == 1) {
          _unreadAt = null;
          _refreshUnread();
        }
      },
      items: [
        const SzNavItem(
            icon: Icons.list_alt_outlined,
            selectedIcon: Icons.list_alt,
            label: '大厅'),
        // 手上几单写在标签里(稿子:「进行中 · 1」),不挂红色角标 ——
        // 这不是待办提醒,是一个状态
        SzNavItem(
            icon: Icons.two_wheeler_outlined,
            selectedIcon: Icons.two_wheeler,
            label: _mine.isEmpty ? '进行中' : '进行中 · ${_mine.length}'),
        const SzNavItem(
            icon: Icons.account_balance_wallet_outlined,
            selectedIcon: Icons.account_balance_wallet,
            label: '账本'),
        const SzNavItem(
            icon: Icons.person_outline, selectedIcon: Icons.person, label: '我的'),
      ],
      appBar: switch (_tab) {
        0 => _hallAppBar(),
        2 => AppBar(
            title: const Text('账本'),
            actions: [
              SzTextTabs(
                labels: WalletPage.periods,
                index: _ledgerPeriod,
                onChanged: (i) => setState(() => _ledgerPeriod = i),
              ),
              const SizedBox(width: 12),
            ],
          ),
        _ => null,
      },
      body: page,
    );
    final offer = _offer;
    if (offer == null) return scaffold;
    return Stack(children: [
      scaffold,
      Positioned.fill(
        child: RiderOfferOverlay(
          key: ValueKey(offer.orderNo),
          order: offer,
          toShopText: _toShopText(offer),
          tripText: _tripText(offer),
          infoLine: _offerInfo(offer),
          sameWay: offer.sameShop || offer.sameWay,
          grabbing: _grabbing.contains(offer.orderNo),
          grabbed: _offerGrabbed,
          vibrate: _alerts.vibrate,
          onGrab: () => _grab(offer, fromOffer: true),
          onDismiss: () {
            if (mounted) setState(() => _offer = null);
          },
        ),
      ),
    ]);
  }
}
