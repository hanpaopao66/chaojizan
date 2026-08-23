import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import 'appeal_page.dart';
import 'location_service.dart';
import 'map_page.dart';
import 'pool_map_page.dart';
import 'verify_page.dart';
import 'wallet_page.dart';
import 'dispatch_spec_page.dart';
import 'profile_page.dart';

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
      // 深浅两套令牌都在 brand.dart 里定义(第八辑 #101),#111 走查后放开
      theme: brandTheme(Brightness.light, density: SzDensity.operate),
      darkTheme: brandTheme(Brightness.dark, density: SzDensity.operate),
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

  /// 抢单池排序。0 综合(服务端算的)/ 1 配送费 / 2 距离 / 3 等待时长。
  ///
  /// **不做服务端持久化**:这是个当下的选择,不是长期偏好 ——
  /// 他午高峰想按配送费挑、收工前想按距离挑,不该被记成"这个人偏好配送费"。
  ///
  /// 给这个切换本身是有立场的:dispatch.py 写着「算法只负责把信息排得
  /// 更有用」,那**排得对不对该由骑手说了算**。我们已经把算法公开给他看,
  /// 却不让他换个排法,中间是断的。
  int _sortMode = 0;
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

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) =>
        checkForUpdate(context, baseUrl: widget.api.baseUrl, app: 'rider'));
    _loadVerify(); // 认证状态:只做提示与跑单前置,不挡浏览
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
  String _feePartsLine(Order order) {
    final parts = <String>[];
    order.feeParts.forEach((k, v) {
      if (v <= 0) return;
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
            );
      final available = pool.items;
      _filteredByPrefs = pool.filteredByPrefs;
      _stalePrefs = pool.stalePrefs;
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
          _lastRefreshOkAt = DateTime.now();
          _refreshError = '';
        });
      }
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
    _refresh();
  }

  /// 正在抢的单号:抢单是最会手快连点的场景,没有这个标志的话
  /// 第一次成功、第二次被服务端拒绝,骑手会看到一个错误提示以为没抢到。
  /// 商家「接单」和用户「提交订单」都有防重标志,这里原先漏了。
  final Set<String> _grabbing = {};

  Future<void> _grab(Order order) async {
    if (_grabbing.contains(order.orderNo)) return;
    if (!await _ensureVerified()) return;
    if (!mounted) return;
    setState(() => _grabbing.add(order.orderNo));
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
          .showSnackBar(SnackBar(content: Text('$e')));
      _refresh();
    } finally {
      if (mounted) setState(() => _grabbing.remove(order.orderNo));
    }
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

  /// 按当前排序模式排好的抢单池。
  ///
  /// 综合(0)= **原样用服务端的顺序**,不在客户端重排 —— 那个顺序里
  /// 含了顺路增量、等待时长加权这些客户端算不出来的东西。
  ///
  /// 其余三档是骑手自己要的单一维度。缺字段的排最后:
  /// 服务端拿不到定位时 distance_m 是空的,把它们当成 0 会顶到最前面,
  /// 而那是**最没把握**的几单。
  List<Order> get _sortedAvailable {
    if (_sortMode == 0) return _available;
    final list = [..._available];
    switch (_sortMode) {
      case 1: // 配送费(含小费),高的在前
        list.sort((a, b) => (b.deliveryFeeCents + b.tipCents)
            .compareTo(a.deliveryFeeCents + a.tipCents));
      case 2: // 到店距离,近的在前;没算出距离的沉底
        list.sort((a, b) => (a.distanceM ?? 1 << 30)
            .compareTo(b.distanceM ?? 1 << 30));
      case 3: // 等待时长,等久的在前(下单时间早的)
        list.sort((a, b) => a.createdAt.compareTo(b.createdAt));
    }
    return list;
  }

  /// 排序切换。
  ///
  /// 放在「抢单怎么排的」入口旁边:换了排法之后**更**该能查
  /// 综合分是怎么算的。
  Widget _sortBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: Row(children: [
        Text('排序', style: Theme.of(context).textTheme.bodySmall),
        const SizedBox(width: 8),
        Expanded(
          child: Wrap(spacing: 6, children: [
            for (final (mode, label) in const [
              (0, '综合'), (1, '配送费'), (2, '距离'), (3, '等待久'),
            ])
              ChoiceChip(
                label: Text(label, style: const TextStyle(fontSize: 12)),
                visualDensity: VisualDensity.compact,
                selected: _sortMode == mode,
                onSelected: (_) => setState(() => _sortMode = mode),
              ),
          ]),
        ),
      ]),
    );
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
        // 总览图放这儿而不是每张卡上:卡上的「看路线」回答「这一单在哪」,
        // 这个回答「这些单挨得近吗」—— 后者是看整个池子时才有的问题(#297)
        IconButton(
          icon: const Icon(Icons.map_outlined, size: 20),
          tooltip: '取餐点总览',
          onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
              builder: (_) => RiderPoolMapPage(
                  orders: _sortedAvailable, riderPosition: _riderPosition))),
        ),
        IconButton(
          icon: const Icon(Icons.tune, size: 20),
          tooltip: '接单偏好',
          onPressed: _openPrefs,
        ),
        // 算法公开的入口就放在排序结果旁边 —— 公开给外人看却不给骑手看
        // 是本末倒置。骑手对着这个池子最常问的就是"凭什么这么排"
        IconButton(
          icon: const Icon(Icons.help_outline, size: 20),
          tooltip: '抢单怎么排的',
          onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
              builder: (_) => DispatchSpecPage(api: widget.api))),
        ),
      ]),
    );
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
                    style: TextStyle(fontSize: 12)),
              ),
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

  Widget _orderCard(Order order, {List<Widget> actions = const []}) {
    // 户外 + 单手 + 可能戴手套:卡片内边距和行距都比另外两端松
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(14),
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
                  style: TextStyle(
                      color: Theme.of(context).sz.hold, fontWeight: FontWeight.bold)),
            if (order.parentOrderNo.isNotEmpty)
              Text(
                  '📎 追加单,随#${order.parentOrderNo.substring(order.parentOrderNo.length - 6)} 一起取送',
                  style: TextStyle(
                      color: Theme.of(context).sz.earn, fontWeight: FontWeight.bold)),
            // 顺路标记:**带上绕路多少米**,不给一句模糊的「顺路」。
            // 旧口径只比两个送达点的距离,会把「送达点相邻但取餐点在反方向
            // 3 公里」的单也标成顺路 —— 骑手信了就多跑近 6 公里。
            // 现在按绕路增量判,并把这个数摆出来让骑手自己核
            if (order.sameShop || order.sameWay)
              Text(
                  order.sameShop
                      ? '🛵 同店取餐 · 与手头单一家店,取餐几乎不多花时间'
                      : '🛵 ${order.sameWayLevel == "strong" ? "强" : ""}顺路 · '
                          '比只送手头单多跑约 ${order.detourM ?? 0} 米',
                  style: TextStyle(
                      color: Theme.of(context).sz.earn, fontWeight: FontWeight.bold)),
            // 整单跑程 + 耗时 + 时薪。
            //
            // 旧版只显示「到店多远」和总价 —— 而一个 3 公里 8 块的单和一个
            // 1 公里 4 块的单哪个划算,**不看总价看时薪**。实测:前者时薪
            // ¥14.2/小时、后者 ¥21.8/小时,总价高的反而不划算。
            if (order.tripM != null)
              Text(
                  '跑程:到店 ${order.distanceM ?? 0} 米 + 送 ${order.tripM} 米'
                  '${order.distanceSource == "straight" ? "(直线估算)" : ""}',
                  style: TextStyle(
                      fontSize: 12, color: Theme.of(context).sz.inkMuted)),
            if (order.estMinutes != null)
              Row(children: [
                Text('约 ${order.estMinutes!.toStringAsFixed(0)} 分钟',
                    style: TextStyle(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600,
                        color: Theme.of(context).sz.ink)),
                if ((order.estWaitMinutes ?? 0) > 0) ...[
                  const SizedBox(width: 4),
                  Text(
                      '(含等餐 ${order.estWaitMinutes!.toStringAsFixed(0)}'
                      '${order.waitSource == "declared" ? "·商家自报" : ""})',
                      style: TextStyle(
                          fontSize: 11, color: Theme.of(context).sz.inkMuted)),
                ],
                const Spacer(),
                if (order.centsPerMinute != null && order.centsPerMinute! > 0)
                  Text(
                      '≈ ¥${(order.centsPerMinute! * 60 / 100).toStringAsFixed(0)}/小时',
                      style: TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                          color: Theme.of(context).sz.earn)),
              ]),
            // 这个收货点历史上要花多久。**样本不足就直说不知道** ——
            // 拿 3 单算出来的数摆给骑手看,比不给更误导
            if (order.dropP75Minutes != null)
              Text(
                  '这个点位:送到手上平均还要 '
                  '${order.dropP75Minutes!.toStringAsFixed(0)} 分钟'
                  '(${order.dropSample} 单实测)',
                  style: TextStyle(
                      fontSize: 12, color: Theme.of(context).sz.inkMuted)),
            // 跑腿单:标出来并写清寄什么 —— 骑手取件时要照着核对,
            // 而"取餐"这个词对跑腿是错的(那里没有餐也没有店)
            if (order.isErrand)
              Text(
                  '🎒 跑腿单 · ${order.errandNote.isEmpty ? "物品" : order.errandNote}',
                  style: TextStyle(
                      color: Theme.of(context).sz.earn,
                      fontWeight: FontWeight.bold)),
            // 帮买加价的进展。不显示的话骑手站在收银台前完全不知道
            // 该等还是该走 —— 而这三种状态下他要做的事完全不同
            if (order.isErrandBuy && order.goodsRaiseStatus == 'pending')
              Text('⏳ 已问顾客能不能花 ${yuan(order.goodsRaiseCents ?? 0)},'
                  '等他回复;别先垫钱',
                  style: TextStyle(
                      color: Theme.of(context).sz.hold,
                      fontWeight: FontWeight.bold)),
            if (order.isErrandBuy && order.goodsRaiseStatus == 'approved')
              Text('✅ 顾客同意花到 ${yuan(order.goodsRaiseCents ?? 0)},可以买了',
                  style: TextStyle(
                      color: Theme.of(context).sz.earn,
                      fontWeight: FontWeight.bold)),
            if (order.isErrandBuy && order.goodsRaiseStatus == 'rejected')
              Text('❌ 顾客不同意多花钱 —— 按「买不到」处理,商品款全额退他,'
                  '你的跑腿费照收到店那一段',
                  style: TextStyle(
                      color: Theme.of(context).sz.hold,
                      fontWeight: FontWeight.bold)),
            if (order.hasAlcohol)
              Text('🍺 含酒精饮品,送达请查验收件人年龄',
                  style: TextStyle(
                      color: Theme.of(context).sz.hold, fontWeight: FontWeight.bold)),
            Text('${order.isErrand ? "取件" : "取餐"}:'
                '${order.merchantName} · ${order.merchantAddress}'),
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
              // 两段路都优先用**服务端算的骑行路径距离**(#293)。
              //
              // 原来是 `_distanceToShop(order) ?? order.distanceM` ——
              // 客户端直线优先、服务端路径兜底,**正好反了**:
              // 直线系统性低估(实测成都两点直线 1467m、骑行 1745m,差 19%),
              // 骑手按直线判断「顺路、近」接了单,实际要多骑三成。
              //
              // 本地定位的价值是「更新快」,但它只能算直线;服务端那个数
              // 走的是腾讯骑行路网,含单行道和过街。所以:
              // **有路网数就用路网数,没有才退回本地直线并标出来**。
              final routed = order.distanceM?.toDouble();
              final toShop = routed ?? _distanceToShop(order);
              final trip = order.tripM?.toDouble() ?? _tripDistance(order);
              // 直线兜底时说一句,别让骑手以为这是骑行距离
              final approx = routed == null && toShop != null;
              // 说人话(#293):「距你 1.7km」看不出要骑多久,也看不出
              // 这一单总共要跑多远。骑手真正要判断的是两件事:
              // 「我去取要多久」「取到之后还要跑多远」——
              // 所以两段分开写清楚,并且各带一个骑行分钟数
              final parts = [
                if (toShop != null)
                  '去取餐 ${distanceLabel(toShop)}'
                      '(约 ${rideMinutes(toShop)} 分钟)${approx ? ' 直线估算' : ''}',
                if (trip != null) '再送 ${distanceLabel(trip)}',
                if (toShop != null && trip != null)
                  '全程 ${distanceLabel(toShop + trip)}',
              ];
              final sz = Theme.of(context).sz;
              final mine = order.deliveryFeeCents + order.tipCents;
              // 骑手端最该被一眼看到的是"这一单我能拿多少",
              // 所以金额比别处再大一档,并明说没人从里面抽走
              return Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(yuan(mine),
                              style: szMoney(
                                  fontSize: 22,
                                  fontWeight: FontWeight.w600,
                                  color: sz.earn)),
                          Text(
                              order.tipCents > 0
                                  ? '配送费 + 小费,100% 归你'
                                  : '配送费 100% 归你,平台不抽',
                              style: TextStyle(
                                  fontSize: 11, color: sz.inkMuted)),
                          // 这 8 块钱是怎么来的 —— **接单前就摊开**。
                          // 别家骑手端只给一个总数,骑手要跑到楼下才知道
                          // 是 6 楼没电梯;知道钱里有 3 块是爬楼费,
                          // 才谈得上"判断这单值不值"
                          if (order.feeParts.isNotEmpty)
                            Padding(
                              padding: const EdgeInsets.only(top: 2),
                              child: Text(
                                  _feePartsLine(order),
                                  style: TextStyle(
                                      fontSize: 11, color: sz.inkMuted)),
                            ),
                        ],
                      ),
                      const Spacer(),
                      if (parts.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 2),
                          child: Text(parts.join(' · '),
                              style: TextStyle(
                                  fontSize: 12, color: sz.inkMuted)),
                        ),
                    ]),
              );
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
    final banner = _verifyBanner();
    final gpsBanner = _gpsBanner();
    // 首次就没拉到:**整页错误态**,绝不能让它长得像"今天没单"。
    // 有过一次成功就退回顶部横条 —— 旧列表还能看,别把能用的也拿走
    final firstLoadFailed = _neverLoaded && _refreshError.isNotEmpty;
    final tabList = _tab == 0
        ? RefreshIndicator(
            onRefresh: _refresh,
            child: !_online
                ? ListView(children: const [
                    Padding(
                        padding: EdgeInsets.all(24),
                        child: Text('上线后开始接单(右上角开关)'))
                  ])
                : ListView.builder(
                        itemCount: _sortedAvailable.length + 1,
                        itemBuilder: (context, i) {
                          if (i == 0) {
                            // 疲劳提示置顶:它比任何一单都重要
                            return Column(children: [
                              _staleBanner('抢单池'),
                              _fatigueBar(),
                              _sortBar(),
                              _radiusBar(),
                              _stalePrefHint(),
                              _filteredHint(),
                            ]);
                          }
                          return _orderCard(
                          _sortedAvailable[i - 1],
                          actions: [
                            OutlinedButton(
                                onPressed: () =>
                                    _openMap(_sortedAvailable[i - 1]),
                                child: const Text('看路线')),
                            // 户外单手操作:主按钮高 52、宽一点,戴手套也点得中
                            Builder(builder: (context) {
                              final o = _sortedAvailable[i - 1];
                              final busy = _grabbing.contains(o.orderNo);
                              return FilledButton(
                                  style: FilledButton.styleFrom(
                                      minimumSize: const Size(112, 52)),
                                  onPressed: busy ? null : () => _grab(o),
                                  child: Text(busy ? '抢单中…' : '抢单'));
                            }),
                          ],
                        );
                        },
                      ),
          )
        : RefreshIndicator(
            onRefresh: _refresh,
            child: _mine.isEmpty
                ? ListView(children: [
                    _staleBanner('配送列表'),
                    const Padding(
                        padding: EdgeInsets.all(24),
                        child: Text('没有进行中的配送')),
                  ])
                : ListView.builder(
                    itemCount: _mine.length + 1,
                    itemBuilder: (context, i) {
                      if (i == 0) {
                        return Column(
                            children: [_staleBanner('配送列表'), _batchBar()]);
                      }
                      final order = _mine[i - 1];
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
                      // 未取餐时给「我到店了」:等餐时长 = 取餐 − 到店,
                      // 是申诉超时时的证据。在店里干等二十分钟不该算到
                      // 骑手头上,而在这之前他没有办法证明这件事
                      if (order.status != OrderStatus.pickedUp &&
                          order.arrivedShopAt.isEmpty) {
                        actions.add(OutlinedButton.icon(
                            icon: const Icon(Icons.storefront, size: 18),
                            onPressed: () => _markArrived(order),
                            label: Text(order.isErrand ? '我到取件点了' : '我到店了')));
                      }
                      // 未取餐(接单中/待取餐)且非追加单可转单;追加单随原单一起转
                      if (order.status != OrderStatus.pickedUp &&
                          order.parentOrderNo.isEmpty) {
                        actions.add(OutlinedButton.icon(
                            icon: const Icon(Icons.swap_horiz, size: 18),
                            onPressed: () => _transferOrder(order),
                            label: const Text('转单')));
                      }
                      if (order.status == OrderStatus.ready) {
                        // 帮买:先填小票再谈取件 —— 小票是这一单唯一的
                        // 对账依据,顾客也看得到
                        if (order.isErrandBuy &&
                            order.goodsActualCents == null) {
                          actions.add(OutlinedButton.icon(
                              icon: const Icon(Icons.receipt_long, size: 18),
                              onPressed: () => _submitReceipt(order),
                              label: const Text('填小票')));
                          actions.add(TextButton(
                              onPressed: () => _markUnavailable(order),
                              child: const Text('买不到')));
                        }
                        // 帮送:物品照。东西是顾客的,平台不做保价也不知道原样,
                        // 出了丢件/损坏纠纷只有这张照片说得清
                        if (order.isErrand && !order.isErrandBuy) {
                          actions.add(OutlinedButton.icon(
                              icon: Icon(
                                  order.pickupPhotoUrl.isEmpty
                                      ? Icons.photo_camera_outlined
                                      : Icons.check_circle_outline,
                                  size: 18),
                              onPressed: () => _uploadPickupPhoto(order),
                              label: Text(order.pickupPhotoUrl.isEmpty
                                  ? '拍物品照'
                                  : '已拍 ✓')));
                        }
                        actions.add(FilledButton(
                            onPressed: () => _pickUpErrandAware(order),
                            child: Text(order.isErrand ? '已取件' : '已取餐')));
                      } else if (order.status == OrderStatus.delivered ||
                          order.status == OrderStatus.completed) {
                        // 送完了才谈得上「这单超时不怪我」——
                        // 进行中的单该先把它送完
                        actions.add(TextButton(
                            onPressed: () => Navigator.of(context).push(
                                MaterialPageRoute(
                                    builder: (_) => RiderAppealPage(
                                        api: widget.api, order: order))),
                            child: const Text('申诉')));
                      } else if (order.status == OrderStatus.pickedUp) {
                        // 「我到了」:到这里到点送达之间的时长花在找门、
                        // 等门禁、等电梯、爬楼上。点了才有数,不点不猜
                        if (order.arrivedDropAt.isEmpty) {
                          actions.add(OutlinedButton.icon(
                              icon: const Icon(Icons.pin_drop_outlined,
                                  size: 18),
                              onPressed: () => _markArrivedDrop(order),
                              label: const Text('我到了')));
                        }
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

    // 一次都没成功拉到过:**整页错误态**。
    //
    // 这是这一批在骑手端要修的核心 —— 抢单页一片空白和"现在真的没单"
    // 长得一模一样;「我的」页写着"没有进行中的配送",而他手上明明有单。
    // 电梯、地库、信号弱在这份工作里是常态,不是边角情况。
    //
    // 有过一次成功就不走这里,退回顶部的 [_staleBanner] —— 旧列表还能看,
    // 别把本来能用的东西也一起拿走。
    final body = firstLoadFailed
        ? RefreshIndicator(
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
          )
        : tabList;

    final tabBody = switch (_tab) {
      2 => WalletPage(api: widget.api),
      3 => RiderProfilePage(
          api: widget.api,
          onOpenWallet: () => setState(() => _tab = 2),
          onOpenOrders: () => setState(() => _tab = 1),
        ),
      _ => body,
    };
    // 认证提示 + 定位异常横幅置顶(恢复后自动消失)。
    // 定位挂了影响的是**每一个** tab —— 抢单靠它筛,配送靠它给顾客看进度,
    // 所以放在页面级而不是塞进抢单列表里
    final banners = <Widget>[
      if (banner != null) banner,
      if (gpsBanner != null) gpsBanner,
    ];
    final page = banners.isEmpty
        ? tabBody
        : Column(children: [...banners, Expanded(child: tabBody)]);

    // 宽屏(≥600)换左侧栏(#295)。
    //
    // 骑手端跑在手机上的时候几乎都是 compact,这一条主要为**平板横屏**
    // 和调度台场景 —— 有的团队会把一台平板架在站点里看单
    return SzNavScaffold(
      selectedIndex: _tab,
      // 骑手端是单列信息流(单卡、钱包流水),用窄一档。
      // 宽度交给外壳,标题栏才会跟内容对齐
      contentMaxWidth: kContentMaxWidth,
      onSelected: (i) => setState(() => _tab = i),
      items: const [
        SzNavItem(
            icon: Icons.flash_on_outlined,
            selectedIcon: Icons.flash_on,
            label: '抢单'),
        SzNavItem(
            icon: Icons.moped_outlined, selectedIcon: Icons.moped, label: '配送'),
        SzNavItem(
            icon: Icons.account_balance_wallet_outlined,
            selectedIcon: Icons.account_balance_wallet,
            label: '钱包'),
        SzNavItem(
            icon: Icons.person_outline,
            selectedIcon: Icons.person,
            label: '我的'),
      ],
      appBar: AppBar(
        title: Text(switch (_tab) {
          0 => '抢单大厅',
          1 => '我的配送',
          2 => '我的钱包',
          _ => '我的',
        }),
        leading: Tooltip(
          message: '长按 3 秒紧急求助',
          child: GestureDetector(
            onLongPress: _triggerSos,
            child: Icon(Icons.sos, color: Theme.of(context).sz.danger),
          ),
        ),
        actions: [
          Row(children: [
            Icon(
              _gpsActive ? Icons.gps_fixed : Icons.gps_off,
              size: 18,
              color: _gpsActive ? Theme.of(context).sz.earn : Theme.of(context).sz.inkMuted,
            ),
            const SizedBox(width: 4),
            Text(_online ? '接单中' : '已下线'),
            Switch(value: _online, onChanged: _toggleOnline),
            const SizedBox(width: 8),
          ]),
        ],
      ),
      body: page,
    );
  }
}
