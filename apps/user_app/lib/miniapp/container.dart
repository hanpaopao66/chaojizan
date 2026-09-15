/// 小程序容器 v2(DEV-PROMPTS-39 #324):启动、呈现、宿主的那一圈界面。
///
/// ## 顶栏归宿主,页面画不到
///
/// 图标、名称、「由 XX 提供」和认证标记、`···`、关闭 —— 全是原生画在网页**外面**的,
/// 页面内容再怎么画也盖不住。这是防仿冒的关键:一个小程序可以把自己画成支付页,
/// 但画不掉顶栏上那行「由 XX 提供」。全屏时顶栏收成右上角的胶囊(`···`、关闭),
/// 浮在网页**上面**,同样盖不住;点 `···` 看得到「由 XX 提供」和认证标记。
///
/// ## 呈现:一个路由、一棵不变的树
///
/// 网页(平台视图)从头到尾待在树里同一个位置,换的只是它外面那一圈的位置和大小 —— 切全屏不会重新加载页面。
///
/// - 应用:半屏 → 全屏的弹层(拖顶栏);宽屏是居中的面板。页面调 requestFullscreen → 沉浸式全屏:
///   面板铺满整屏、系统栏藏起来、顶栏收成右上角的胶囊;exitFullscreen 回到弹层原来的大小;
/// - 小游戏:打开就是沉浸式全屏,按 superz.json 锁方向;exitFullscreen 露出顶栏(仍铺满,不变成弹层);
/// - 网页版宿主:进全屏时顺手试浏览器的全屏 API(页面里刚点过、手势还有效时才会成),
///   成不了就只在窗口里铺满、收起顶栏;用户按 Esc 退出浏览器全屏时,应用跟着回到弹层。
///   电脑上没有原生小程序容器,桌面版引导到网页版打开,行为同网页版。
///
/// 安全区照实下发;内容安全区把胶囊那一截算进去(超级赞的口径是从屏幕边算起的总边距,
/// Telegram 兼容层在 SDK 里换算成 Telegram 的口径)。
///
/// ## 返回键
///
/// 页面显示了 BackButton → 系统返回交给页面(backButtonClicked);没显示 → 关闭
///(开了关闭确认的先问一句)。全屏时也一样。
library;

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import '../session.dart';
import '../video/player/browser_fullscreen.dart';
import 'bridge.dart';
import 'controller.dart';
import 'pages.dart';
import 'theme.dart';
import 'view.dart';

/// 这个平台有没有小程序容器:手机端是原生 WebView,web 端是 iframe;桌面端两样都没有。
bool get miniAppSupported =>
    kIsWeb ||
    defaultTargetPlatform == TargetPlatform.android ||
    defaultTargetPlatform == TargetPlatform.iOS;

String get miniAppPlatform => kIsWeb
    ? 'web'
    : defaultTargetPlatform == TargetPlatform.android
        ? 'android'
        : defaultTargetPlatform == TargetPlatform.iOS
            ? 'ios'
            : 'unknown';

const kMiniAppDebugPref = 'miniapp_debug';
const kMiniAppTesterPref = 'miniapp_is_tester';

/// 弹层的三个高度(占状态栏以下可用高度的比例):打开时、拖到最低、拖到最高
const kMiniAppSheetInitial = 0.72;
const kMiniAppSheetMin = 0.45;
const kMiniAppSheetMax = 0.96;

/// 全屏时胶囊离安全区顶的距离、胶囊的高度。内容安全区的顶 = 安全区顶 + 这两项
const kCapsuleTop = 8.0;
const kCapsuleHeight = 40.0;

/// 打开一个小程序。[card] 有就立刻出启动页(图标、名字),没有(直达链接)先查一次详情。
Future<void> openMiniApp(BuildContext context, ApiClient api,
    {required String appid, MiniAppCard? card, bool trial = false, String? startParam}) async {
  final messenger = ScaffoldMessenger.maybeOf(context);
  if (!miniAppSupported) {
    // 桌面版:系统浏览器里的网页版能开(iframe 容器),直达链接 /web/#/m/<appid> 带过去
    messenger?.showSnackBar(SnackBar(
      content: const Text('这个平台还不能打开小程序,请用手机 App 或网页版'),
      action: SnackBarAction(
        label: '用网页版打开',
        onPressed: () => launchUrl(Uri.parse('${api.baseUrl}/web/#/m/$appid'),
            mode: LaunchMode.externalApplication),
      ),
    ));
    return;
  }
  if (!await ensureLoggedIn(context)) return;
  if (!context.mounted) return;
  var c = card;
  if (c == null) {
    try {
      c = (await api.miniAppDetail(appid)).card;
    } catch (e) {
      messenger?.showSnackBar(SnackBar(content: Text('$e')));
      return;
    }
    if (!context.mounted) return;
  }
  await Navigator.of(context).push(miniAppRoute(
      context, MiniAppFrame(api: api, card: c, trial: trial, startParam: startParam, fullscreen: c.isGame),
      game: c.isGame));
}

/// 小程序的路由。应用的弹层自己按路由动画画遮罩(淡入)和面板(从底下升上来),
/// 所以路由本身透明、不带过渡;小游戏整页淡入。
Route<void> miniAppRoute(BuildContext context, Widget frame, {required bool game}) => PageRouteBuilder<void>(
      opaque: game,
      transitionDuration: SzMotion.of(context, SzMotion.slow),
      reverseTransitionDuration: SzMotion.of(context, SzMotion.base),
      pageBuilder: (_, __, ___) => frame,
      transitionsBuilder: (_, anim, __, child) => game ? FadeTransition(opacity: anim, child: child) : child,
    );

class MiniAppFrame extends StatefulWidget {
  const MiniAppFrame({
    super.key,
    required this.api,
    required this.card,
    this.trial = false,
    this.startParam,
    this.fullscreen = false,
    this.viewBuilder,
  });

  final ApiClient api;
  final MiniAppCard card;
  final bool trial;
  final String? startParam;

  /// 小游戏:打开就是沉浸式全屏;应用在弹层里,页面要了才全屏
  final bool fullscreen;

  /// 测试用:用它代替真正的网页(WebView / iframe 在测试环境里起不来)
  @visibleForTesting
  final Widget Function(BuildContext context, MiniAppController controller)? viewBuilder;

  @override
  State<MiniAppFrame> createState() => _MiniAppFrameState();
}

class _MiniAppFrameState extends State<MiniAppFrame> with WidgetsBindingObserver implements MiniAppUi {
  final _viewKey = GlobalKey<MiniAppViewState>();
  MiniAppController? _c;
  String? _error;
  bool _splash = true;

  /// 启动页淡出之后整个拿掉:它里面的转圈是无限动画,留在树里(哪怕透明)会一直占着帧
  bool _splashGone = false;
  bool _debug = false;
  bool? _starred;
  Timer? _splashTimer;
  Timer? _stableTimer;
  bool _closing = false;

  /// 沉浸式全屏(页面看到的 isFullscreen)。小游戏打开就是
  late bool _immersive = widget.fullscreen;

  /// 弹层的高度比例(应用、窄屏、非全屏时)。拖顶栏改它,expand() 拉到最高
  double _size = kMiniAppSheetInitial;
  bool _dragging = false;

  /// 网页版:这次全屏试过浏览器的全屏 API
  bool _browserFs = false;
  void Function()? _stopBrowserWatch;
  bool _orientationTouched = false;

  MiniAppCard get card => _c?.launch.card ?? widget.card;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    SharedPreferences.getInstance().then((p) {
      if (mounted) setState(() => _debug = p.getBool(kMiniAppDebugPref) ?? false);
    });
    // 小游戏:沉浸式 + 按 superz.json 锁方向(启动应答回来后再按实际值锁一次)
    if (widget.fullscreen) {
      SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
      SystemChrome.setPreferredOrientations([DeviceOrientation.portraitUp]);
      _orientationTouched = true;
    }
    _stopBrowserWatch = onBrowserFullscreenExit(_onBrowserFullscreenExit);
    WidgetsBinding.instance.addPostFrameCallback((_) => _launch());
  }

  Future<void> _launch() async {
    setState(() {
      _error = null;
      _splash = true;
      _splashGone = false;
    });
    final theme = Theme.of(context);
    try {
      final launch = await widget.api.miniAppLaunch(widget.card.appid,
          trial: widget.trial,
          startParam: widget.startParam,
          platform: miniAppPlatform,
          theme: miniAppThemeParams(theme.sz, theme.brightness));
      if (!mounted) return;
      if (widget.trial) {
        SharedPreferences.getInstance().then((p) => p.setBool(kMiniAppTesterPref, true));
      }
      final old = _c;
      final c = old ?? MiniAppController(api: widget.api, launch: launch, ui: this, platform: miniAppPlatform);
      c.launch = launch;
      if (old == null) {
        c.onSuspended = () => _closeWith('该小程序已被暂停');
        c.addListener(_onController);
        c.startPolling();
        final t = Theme.of(context);
        c.themeParams = miniAppThemeParams(t.sz, t.brightness);
        c.colorScheme = t.brightness == Brightness.dark ? 'dark' : 'light';
        c.fullscreen = _immersive;
      }
      setState(() => _c = c);
      if (old != null) _viewKey.currentState?.reload();
      if (widget.fullscreen) unawaited(_lockManifestOrientation());
      _splashTimer?.cancel();
      // ready() 八秒还没来也照常展示 —— 页面可能忘了调,不能让用户对着启动页干等
      _splashTimer = Timer(const Duration(seconds: 8), () {
        if (mounted) setState(() => _splash = false);
      });
      unawaited(widget.api.miniAppDetail(card.appid).then((d) {
        if (mounted) setState(() => _starred = d.starred);
      }).catchError((_) {}));
    } on ApiException catch (e) {
      if (!mounted) return;
      final msg = e.code == BridgeCode.appSuspended
          ? '该小程序已被暂停'
          : e.statusCode == 403
              ? '你不是这个小程序的体验者'
              : e.message;
      setState(() => _error = msg);
    }
  }

  void _onController() {
    if (!mounted) return;
    if (_c!.ready && _splash) {
      _splashTimer?.cancel();
      setState(() => _splash = false);
    } else {
      setState(() {});
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final c = _c;
    if (c == null) return;
    if (state == AppLifecycleState.resumed) {
      c.emit('activated');
      c.checkStatus();
    } else if (state == AppLifecycleState.paused) {
      c.emit('deactivated');
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final c = _c;
    if (c == null) return;
    final t = Theme.of(context);
    c.updateTheme(miniAppThemeParams(t.sz, t.brightness), t.brightness == Brightness.dark ? 'dark' : 'light');
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _splashTimer?.cancel();
    _stableTimer?.cancel();
    _stopBrowserWatch?.call();
    _c?.removeListener(_onController);
    _c?.dispose();
    if (_browserFs) unawaited(exitBrowserFullscreen());
    if (_immersive || widget.fullscreen) SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    if (_orientationTouched) SystemChrome.setPreferredOrientations(const []);
    super.dispose();
  }

  // ---------------------------------------------------------------- 关闭与返回

  void _closeWith(String message) {
    if (_closing || !mounted) return;
    _closing = true;
    final messenger = ScaffoldMessenger.maybeOf(context);
    Navigator.of(context).maybePop();
    messenger?.showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _requestClose() async {
    final c = _c;
    if (c != null && c.closingConfirmation) {
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => SzDialog(
          title: const Text('确定关闭?'),
          content: Text('「${card.name}」里的改动可能还没保存好。'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('再等等')),
            TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('关闭')),
          ],
        ),
      );
      if (ok != true) return;
    }
    if (mounted) Navigator.of(context).pop();
  }

  void _onBack() {
    final c = _c;
    if (c != null && c.backButtonVisible) {
      c.clickBack();
    } else {
      _requestClose();
    }
  }

  // ---------------------------------------------------------------- MiniAppUi

  @override
  void close() {
    if (mounted) Navigator.of(context).maybePop();
  }

  @override
  void expand() {
    if (!mounted || widget.fullscreen || _immersive) return;
    setState(() => _size = kMiniAppSheetMax);
  }

  @override
  void haptic(String type, String? style) {
    switch (type) {
      case 'impact':
        if (style == 'heavy' || style == 'rigid') {
          HapticFeedback.heavyImpact();
        } else if (style == 'medium') {
          HapticFeedback.mediumImpact();
        } else {
          HapticFeedback.lightImpact();
        }
      case 'notification':
        style == 'success' ? HapticFeedback.mediumImpact() : HapticFeedback.heavyImpact();
      default:
        HapticFeedback.selectionClick();
    }
  }

  @override
  Future<String?> showPopup(String? title, String message, List<Map<String, dynamic>> buttons) async {
    if (!mounted) return null;
    final sz = Theme.of(context).sz;
    String label(Map<String, dynamic> b) {
      final text = '${b['text'] ?? ''}'.trim();
      if (text.isNotEmpty) return text;
      return switch (b['type']) { 'ok' => '确定', 'cancel' => '取消', 'destructive' => '删除', _ => '关闭' };
    }

    return showDialog<String?>(
      context: context,
      builder: (ctx) => SzDialog(
        title: title == null || title.trim().isEmpty ? null : Text(title.trim()),
        content: Text(message),
        actions: [
          for (final b in buttons)
            TextButton(
              onPressed: () => Navigator.pop(ctx, '${b['id'] ?? ''}'),
              child: Text(label(b),
                  style: TextStyle(color: b['type'] == 'destructive' ? sz.danger : null)),
            ),
        ],
      ),
    );
  }

  @override
  Future<bool> openExternal(Uri url) async {
    if (!mounted) return false;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => SzDialog(
        title: const Text('即将离开超级赞'),
        content: Text('将用浏览器打开:\n${url.host}\n\n这个网页不归超级赞管,里面的内容和收费与平台无关。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('打开')),
        ],
      ),
    );
    if (ok != true) return false;
    try {
      return await launchUrl(url, mode: LaunchMode.externalApplication);
    } catch (_) {
      return false;
    }
  }

  @override
  Future<bool> share(String text) async {
    try {
      final r = await SharePlus.instance.share(ShareParams(text: text));
      return r.status == ShareResultStatus.success;
    } catch (_) {
      await Clipboard.setData(ClipboardData(text: text));
      if (mounted) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(const SnackBar(content: Text('已复制,去粘贴给朋友吧')));
      }
      return true;
    }
  }

  @override
  Future<bool> askProfileConsent() async {
    try {
      if ((await widget.api.miniAppDetail(card.appid)).profileGranted) return true;
    } catch (_) {}
    if (!mounted) return false;
    final sz = Theme.of(context).sz;
    final ok = await szShowSheet<bool>(
      context: context,
      builder: (ctx) => Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, kPagePad),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('「${card.name}」想获取你的昵称和头像',
              style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink)),
          const SizedBox(height: 8),
          Text('只给这一个小程序,它拿不到你的手机号。以后可以在「我的 → 设置 → 小程序授权与数据」里撤回。',
              style: TextStyle(fontSize: kFontBody, color: sz.inkMuted, height: 1.5)),
          const SizedBox(height: 18),
          Row(children: [
            Expanded(child: OutlinedButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('拒绝'))),
            const SizedBox(width: 12),
            Expanded(child: FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('允许'))),
          ]),
        ]),
      ),
    );
    return ok == true;
  }

  /// 进 / 出沉浸式全屏。手机上藏系统栏;网页版顺手试浏览器的全屏 API(成不成都在窗口里铺满)。
  @override
  Future<bool> setFullscreen(bool on) async {
    if (!mounted) return false;
    if (kIsWeb) {
      if (on) {
        _browserFs = true;
        unawaited(enterBrowserFullscreen());
      } else if (_browserFs) {
        _browserFs = false;
        unawaited(exitBrowserFullscreen());
      }
    } else {
      unawaited(SystemChrome.setEnabledSystemUIMode(on ? SystemUiMode.immersiveSticky : SystemUiMode.edgeToEdge));
    }
    if (on != _immersive) setState(() => _immersive = on);
    return true;
  }

  /// 网页版用户按 Esc(或系统手势)退出了浏览器全屏:应用跟着回到弹层,和页面调 exitFullscreen 一样发事件。
  /// 小游戏本来就铺满窗口,只是浏览器的地址栏回来了,不动它。
  void _onBrowserFullscreenExit() {
    if (!_browserFs) return;
    _browserFs = false;
    if (!widget.fullscreen && _immersive) unawaited(_c?.hostExitFullscreen());
  }

  /// 锁**当前**的横竖(和 Telegram 一样);解锁放开。网页版不锁方向。
  @override
  Future<bool> lockOrientation(bool lock) async {
    if (kIsWeb || !mounted) return false;
    _orientationTouched = true;
    if (!lock) {
      await SystemChrome.setPreferredOrientations(const []);
      return true;
    }
    final landscape = MediaQuery.orientationOf(context) == Orientation.landscape;
    await SystemChrome.setPreferredOrientations(landscape
        ? const [DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]
        : const [DeviceOrientation.portraitUp]);
    return true;
  }

  /// 小游戏打开时按 superz.json 的 orientation 锁(这一条行为不变)
  Future<void> _lockManifestOrientation() async {
    if (kIsWeb) return;
    final o = _c?.launch.orientation ?? 'portrait';
    _orientationTouched = true;
    await SystemChrome.setPreferredOrientations(o == 'landscape'
        ? const [DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]
        : o == 'any'
            ? const []
            : const [DeviceOrientation.portraitUp]);
  }

  // ---------------------------------------------------------------- 菜单

  Future<void> _menu() async {
    final c = _c;
    final sz = Theme.of(context).sz;
    Widget item(IconData icon, String text, VoidCallback onTap, {Color? color}) => ListTile(
          leading: Icon(icon, color: color ?? sz.inkMuted),
          title: Text(text, style: TextStyle(fontSize: kFontBodyLg, color: color ?? sz.ink)),
          onTap: () {
            Navigator.pop(context);
            onTap();
          },
        );
    await szShowSheet<void>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 8),
            child: _AppIdentity(card: card, trial: widget.trial, api: widget.api),
          ),
          const Divider(height: 1),
          item(Icons.info_outline, '关于这个小程序', () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => MiniAppDetailPage(api: widget.api, appid: card.appid, card: card)))),
          item(Icons.ios_share, '分享', () => share('${card.name}\n${c?.launchLink ?? ''}')),
          if (_starred != null)
            item(_starred! ? Icons.star : Icons.star_border, _starred! ? '从我的小程序移除' : '添加到我的小程序',
                () async {
              final next = !_starred!;
              try {
                await widget.api.miniAppStar(card.appid, starred: next);
                if (mounted) setState(() => _starred = next);
              } catch (_) {}
            }),
          if (c != null && c.settingsButtonVisible) item(Icons.tune, '设置', c.clickSettings),
          item(Icons.refresh, '重新进入', _launch),
          item(Icons.flag_outlined, '投诉', () => showMiniAppReportSheet(context, widget.api, card)),
          // 顶栏左边换成了返回箭头:这里留一个关闭 —— 页面一直不藏返回键,用户也关得掉(关闭确认照常)
          if (c != null && c.backButtonVisible && !_immersive) item(Icons.close, '关闭', _requestClose),
          item(Icons.delete_sweep_outlined, '清除这个小程序的数据', _clearData, color: sz.danger),
          if (_debug && c != null) item(Icons.bug_report_outlined, '桥调用日志', () => _showLog(c)),
        ]),
      ),
    );
  }

  Future<void> _clearData() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => SzDialog(
        title: const Text('清除这个小程序的数据?'),
        content: Text('「${card.name}」存在云端和这台手机上的数据都会删掉,删了找不回来。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('清除')),
        ],
      ),
    );
    if (ok != true) return;
    await _viewKey.currentState?.clearLocalData();
    try {
      await widget.api.miniAppClearData(card.appid);
    } catch (_) {}
    if (!mounted) return;
    ScaffoldMessenger.maybeOf(context)?.showSnackBar(const SnackBar(content: Text('已清除')));
    await _launch();
  }

  void _showLog(MiniAppController c) {
    final sz = Theme.of(context).sz;
    szShowSheet<void>(
      context: context,
      builder: (ctx) => SizedBox(
        height: MediaQuery.sizeOf(ctx).height * 0.6,
        child: ListView(padding: const EdgeInsets.all(kPagePad), children: [
          Text('桥调用(最近 ${c.log.length} 条)', style: TextStyle(fontSize: kFontTitle, color: sz.ink)),
          for (final e in c.log.reversed)
            Text('${e.at.toIso8601String().substring(11, 19)}  ${e.method}  ${e.ok ? '✓' : '✗ ${e.code}'}',
                style: TextStyle(fontSize: kFontNote, color: e.ok ? sz.inkMuted : sz.danger)),
          const SizedBox(height: 12),
          for (final n in c.notices.reversed) Text(n, style: TextStyle(fontSize: kFontNote, color: sz.hold)),
        ]),
      ),
    );
  }

  // ---------------------------------------------------------------- 布局

  /// 面板现在铺不铺满整屏:小游戏、全屏中的应用
  bool get _covers => widget.fullscreen || _immersive;

  /// 窄屏上的应用弹层(能拖顶栏);宽屏是居中的面板
  bool _isSheet(BuildContext context) => !_covers && isSheetBottom(context);

  /// 面板在屏幕上的位置和大小。键盘弹出时面板整个让到键盘上面
  Rect _panelRect(BoxConstraints box, MediaQueryData mq) {
    final w = box.maxWidth, h = box.maxHeight;
    final kb = mq.viewInsets.bottom;
    if (_covers) return Rect.fromLTWH(0, 0, w, h - kb);
    if (isSheetBottom(context)) {
      final avail = h - mq.padding.top;
      final ph = math.max(0.0, math.min(avail * _size, avail - kb));
      return Rect.fromLTWH(0, h - kb - ph, w, ph);
    }
    final pw = math.max(0.0, math.min(w - 48, kContentMaxWidth));
    final ph = math.max(0.0, math.min(h * 0.8, h - kb - 48));
    return Rect.fromLTWH((w - pw) / 2, (h - kb - ph) / 2, pw, ph);
  }

  void _dragUpdate(DragUpdateDetails d) {
    final avail = MediaQuery.sizeOf(context).height - MediaQuery.paddingOf(context).top;
    if (avail <= 0) return;
    setState(() {
      _dragging = true;
      _size = (_size - (d.primaryDelta ?? 0) / avail).clamp(kMiniAppSheetMin, kMiniAppSheetMax).toDouble();
    });
  }

  void _dragEnd(DragEndDetails d) {
    final v = d.primaryVelocity ?? 0;
    setState(() {
      _dragging = false;
      // 甩一下:往上甩到最高,往下甩到最低(不关闭 —— 关闭走 × 或返回键,关闭确认才拦得住)
      if (v < -700) _size = kMiniAppSheetMax;
      if (v > 700) _size = kMiniAppSheetMin;
    });
  }

  // ---------------------------------------------------------------- 画

  void _report(BoxConstraints box) {
    final c = _c;
    if (c == null || !mounted) return;
    final mq = MediaQuery.of(context);
    final bottomBar = c.mainButton.visible || c.secondaryButton.visible;
    final wideDialog = !_covers && !isSheetBottom(context);
    final atScreenBottom = !wideDialog && mq.viewInsets.bottom == 0;
    c.updateSafeArea({
      // 顶:全屏时网页顶到屏幕边,照实报状态栏 / 刘海;弹层和露出顶栏时顶栏在网页上面
      'top': _immersive ? mq.padding.top : 0,
      'bottom': bottomBar || !atScreenBottom ? 0 : mq.padding.bottom,
      'left': wideDialog ? 0 : mq.padding.left,
      'right': wideDialog ? 0 : mq.padding.right,
    }, {
      // 全屏时右上角有宿主的胶囊:内容安全区的顶把它那一截算进去
      'top': _immersive ? mq.padding.top + kCapsuleTop + kCapsuleHeight : 0,
      'bottom': 0, 'left': 0, 'right': 0,
    });
    final h = box.maxHeight;
    final expanded = _covers || !isSheetBottom(context) || _size > 0.9;
    c.updateViewport(h, stable: false, isExpanded: expanded);
    _stableTimer?.cancel();
    _stableTimer = Timer(const Duration(milliseconds: 300), () {
      if (mounted && !_dragging) c.updateViewport(h, stable: true);
    });
  }

  Widget _view(MiniAppController c) {
    final build = widget.viewBuilder;
    if (build != null) return build(context, c);
    return MiniAppView(
      key: _viewKey,
      controller: c,
      debug: _debug,
      // 宿主的菜单、弹窗盖在上面时,网页版的 iframe 先不接点击(不然点不到盖在它上面的东西)
      interactive: ModalRoute.of(context)?.isCurrent ?? true,
      onError: (m) {
        if (mounted) setState(() => _error = '页面没打开:$m');
      },
    );
  }

  Widget _body() {
    final sz = Theme.of(context).sz;
    final c = _c;
    final bg = colorOf(c?.backgroundColor) ?? colorOf(c?.launch.backgroundColor) ?? sz.paper;
    final mq = MediaQuery.of(context);
    return ColoredBox(
      color: bg,
      child: Stack(children: [
        if (c != null && _error == null)
          Positioned.fill(
            child: LayoutBuilder(builder: (context, box) {
              WidgetsBinding.instance.addPostFrameCallback((_) => _report(box));
              return _view(c);
            }),
          ),
        if (_error != null)
          _ErrorPane(message: _error!, onRetry: _launch, onClose: () => Navigator.of(context).maybePop())
        else if (!_splashGone)
          IgnorePointer(
            ignoring: !_splash,
            child: AnimatedOpacity(
              opacity: _splash ? 1 : 0,
              duration: SzMotion.of(context, SzMotion.base),
              onEnd: () {
                if (mounted && !_splash) setState(() => _splashGone = true);
              },
              child: _Splash(card: card, api: widget.api, color: bg),
            ),
          ),
        // 胶囊最后画:在网页上面,页面盖不住
        if (_immersive)
          Positioned(
            top: mq.padding.top + kCapsuleTop,
            right: mq.padding.right + 10,
            child: PointerShield(child: MiniAppCapsule(onMenu: _menu, onClose: _requestClose)),
          ),
      ]),
    );
  }

  /// 主题里的一个色(宿主下发给页面的那一套 16 个键),没有就用 [fallback]
  Color _theme(String key, Color fallback) => colorOf(_c?.themeParams[key]) ?? fallback;

  /// 底栏:和 Telegram 一样是通栏按钮,底色是 bottom_bar_bg_color(页面 setBottomBarColor 改得了)。
  /// 按钮宿主原生画,页面只给文字和状态 —— 画在网页外面,页面盖不住也仿冒不了。
  Widget _bottomBar() {
    final c = _c;
    if (c == null || !(c.mainButton.visible || c.secondaryButton.visible)) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    final bar = colorOf(c.bottomBarColor) ?? _theme('bottom_bar_bg_color', sz.surface);
    Widget button(BottomButtonState s, VoidCallback onTap, {required bool primary}) {
      // 默认色和 Telegram 一样:主按钮 button_color / button_text_color;次按钮底色同底栏、字是 button_color
      final bg = colorOf(s.color) ?? (primary ? _theme('button_color', sz.clay) : bar);
      final fg = colorOf(s.textColor) ??
          (primary ? _theme('button_text_color', sz.surface) : _theme('button_color', sz.clay));
      // 次按钮和底栏同色时描一圈发丝线,不然看不出是个按钮
      final outline = !primary && bg == bar;
      final enabled = s.active; // 和 Telegram 一样:showProgress(leaveActive) 时加载中也能点
      return Opacity(
        opacity: enabled ? 1 : 0.5,
        child: Material(
          key: ValueKey(primary ? 'miniapp-main-button' : 'miniapp-secondary-button'),
          color: bg,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
            side: outline ? BorderSide(color: _theme('line_color', sz.line)) : BorderSide.none,
          ),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: enabled ? onTap : null,
            child: SizedBox(
              height: 48,
              child: Center(
                child: s.progress
                    ? SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: fg))
                    : Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 12),
                        child: Text(s.text.isEmpty ? (primary ? '继续' : '取消') : s.text,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: fg)),
                      ),
              ),
            ),
          ),
        ),
      );
    }

    final main = c.mainButton.visible ? button(c.mainButton, c.clickMain, primary: true) : null;
    final second = c.secondaryButton.visible ? button(c.secondaryButton, c.clickSecondary, primary: false) : null;
    final pos = c.secondaryButton.position;
    final vertical = pos == 'top' || pos == 'bottom';
    final items = <Widget>[
      if (second != null && (pos == 'left' || pos == 'top')) second,
      if (main != null) main,
      if (second != null && (pos == 'right' || pos == 'bottom')) second,
    ];
    return Material(
      key: const ValueKey('miniapp-bottom-bar'),
      color: bar,
      child: DecoratedBox(
        decoration: BoxDecoration(border: Border(top: BorderSide(color: _theme('line_color', sz.line)))),
        child: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
            child: vertical
                ? Column(mainAxisSize: MainAxisSize.min, children: [
                    for (final (i, w) in items.indexed) ...[if (i > 0) const SizedBox(height: 8), w],
                  ])
                : Row(children: [
                    for (final (i, w) in items.indexed) ...[if (i > 0) const SizedBox(width: 8), Expanded(child: w)],
                  ]),
          ),
        ),
      ),
    );
  }

  /// 顶栏,照 Telegram 的排法:左边关闭(页面显示了 BackButton 时换成返回箭头),中间图标 + 名称,
  /// 右边 `···`。名称下面那一行「由 XX 提供」和认证标记**保留** —— 防仿冒靠的就是它,页面画不掉。
  /// 底色跟页面的 setHeaderColor 走,没设就是主题的 header_bg_color;字色按底色深浅自动取。
  Widget _header() {
    final sz = Theme.of(context).sz;
    final c = _c;
    final headerBg = colorOf(c?.headerColor) ?? _theme('header_bg_color', sz.paper);
    final dark = ThemeData.estimateBrightnessForColor(headerBg) == Brightness.dark;
    final fg = dark ? SzColors.dark.ink : SzColors.light.ink;
    final sheet = _isSheet(context);
    final back = c != null && c.backButtonVisible;
    // 小游戏退出全屏时面板顶到屏幕边:顶栏自己让开状态栏
    final top = widget.fullscreen ? MediaQuery.paddingOf(context).top : 0.0;
    return Material(
      key: const ValueKey('miniapp-header'),
      color: headerBg,
      child: GestureDetector(
        // 拖顶栏:弹层半屏 ↔ 全屏(只有窄屏的应用弹层能拖)
        onVerticalDragUpdate: sheet ? _dragUpdate : null,
        onVerticalDragEnd: sheet ? _dragEnd : null,
        child: Padding(
          padding: EdgeInsets.only(top: top),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (sheet)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Container(
                    width: 32, height: 4,
                    decoration: BoxDecoration(color: fg.withValues(alpha: 0.22), borderRadius: BorderRadius.circular(2))),
              ),
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 2, 4, 4),
              child: Row(children: [
                back
                    ? IconButton(onPressed: c.clickBack, icon: Icon(Icons.arrow_back, color: fg), tooltip: '返回')
                    : IconButton(onPressed: _requestClose, icon: Icon(Icons.close, color: fg), tooltip: '关闭'),
                Expanded(
                  child: _AppIdentity(
                      card: card, trial: widget.trial, api: widget.api, color: fg, compact: true, centered: true),
                ),
                IconButton(onPressed: _menu, icon: Icon(Icons.more_horiz, color: fg), tooltip: '更多'),
              ]),
            ),
            Divider(height: 1, color: _theme('line_color', sz.line)),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _onBack();
      },
      child: Scaffold(
        // 透明:应用弹层后面要看得见原来的页面;键盘避让自己算(面板整个让到键盘上面)
        backgroundColor: Colors.transparent,
        resizeToAvoidBottomInset: false,
        body: LayoutBuilder(builder: _frame),
      ),
    );
  }

  Widget _frame(BuildContext context, BoxConstraints box) {
    final sz = Theme.of(context).sz;
    final mq = MediaQuery.of(context);
    final route = ModalRoute.of(context)?.animation ?? kAlwaysCompleteAnimation;
    final rect = _panelRect(box, mq);
    final motion = _dragging ? Duration.zero : SzMotion.of(context, SzMotion.base);
    final radius = _covers
        ? BorderRadius.zero
        : isSheetBottom(context)
            ? const BorderRadius.vertical(top: Radius.circular(16))
            : BorderRadius.circular(16);
    // 树的形状在应用 / 小游戏、弹层 / 全屏之间都不变,只改位置、大小、顶栏高度 —— 网页不会被重建
    final panel = Material(
      key: const ValueKey('miniapp-panel'),
      color: sz.paper,
      clipBehavior: Clip.antiAlias,
      borderRadius: radius,
      child: Column(children: [
        ClipRect(
          child: AnimatedAlign(
            alignment: Alignment.topCenter,
            heightFactor: _immersive ? 0 : 1,
            duration: SzMotion.of(context, SzMotion.base),
            curve: SzMotion.standard,
            child: _header(),
          ),
        ),
        Expanded(child: _body()),
        _bottomBar(),
      ]),
    );
    return Stack(children: [
      if (!widget.fullscreen)
        // 应用弹层后面的遮罩:点它不关(关闭走 × 或返回键,关闭确认才拦得住)
        Positioned.fill(
          child: FadeTransition(
            opacity: route,
            child: const ModalBarrier(dismissible: false, color: Colors.black54),
          ),
        ),
      AnimatedPositioned(
        duration: motion,
        curve: SzMotion.standard,
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
        child: widget.fullscreen
            ? panel
            : SlideTransition(
                // drive 不给路由动画挂监听(CurvedAnimation 会挂,每次重建挂一个就漏了)
                position: route.drive(Tween(begin: const Offset(0, 1), end: Offset.zero)
                    .chain(CurveTween(curve: SzMotion.standard))),
                child: panel,
              ),
      ),
    ]);
  }
}

/// 图标 + 名称 + 「由 XX 提供 · 认证」。顶栏、菜单共用 —— 同一个应用在哪儿都是同一副样子。
///
/// 「由 XX 提供」这一行和认证标记是防仿冒的关键:它画在网页外面,页面画不掉,也没法冒充成别人。
/// [centered] 是顶栏的排法(照 Telegram:图标和名称居中一行,「由 XX 提供」在下面一行)。
class _AppIdentity extends StatelessWidget {
  const _AppIdentity(
      {required this.card, required this.api, this.trial = false, this.color, this.compact = false, this.centered = false});

  final MiniAppCard card;
  final ApiClient api;
  final bool trial;
  final Color? color;
  final bool compact;
  final bool centered;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final ink = color ?? sz.ink;
    final dev = card.developer;
    final muted = ink.withValues(alpha: 0.62);
    final name = Text(card.name,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(fontSize: compact ? kFontBodyLg : kFontTitle, fontWeight: FontWeight.w600, color: ink));
    final badge = trial
        ? [
            const SizedBox(width: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
              decoration: BoxDecoration(color: sz.claySoft, borderRadius: BorderRadius.circular(4)),
              child: Text('体验版', style: TextStyle(fontSize: kFontMicro, color: sz.clay)),
            ),
          ]
        : const <Widget>[];
    // 「由 XX 提供 · 企业 · 已认证」一整句一个 Text;认证过的(或官方)后面跟一个认证标记
    final provider = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Flexible(
          child: Text(
            '由 ${dev.name.isEmpty ? '开发者' : dev.name} 提供${dev.label.isEmpty ? '' : ' · ${dev.label}'}',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: kFontMicro, color: muted),
          ),
        ),
        if (dev.verified || dev.official)
          Padding(
            padding: const EdgeInsets.only(left: 3),
            child: Icon(Icons.verified, key: const ValueKey('miniapp-verified'), size: 12, color: muted),
          ),
      ],
    );
    if (centered) {
      return Column(mainAxisSize: MainAxisSize.min, children: [
        Row(mainAxisSize: MainAxisSize.min, children: [
          MiniAppIcon(card: card, api: api, size: 20),
          const SizedBox(width: 6),
          Flexible(child: name),
          ...badge,
        ]),
        const SizedBox(height: 1),
        provider,
      ]);
    }
    return Row(children: [
      MiniAppIcon(card: card, api: api, size: compact ? 28 : 40),
      const SizedBox(width: 10),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Row(children: [Flexible(child: name), ...badge]),
          provider,
        ]),
      ),
    ]);
  }
}

/// 小程序的脸:平台图片地址画图,一个汉字画衬线字块。
class MiniAppIcon extends StatelessWidget {
  const MiniAppIcon({super.key, required this.card, required this.api, this.size = 40});

  final MiniAppCard card;
  final ApiClient api;
  final double size;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final icon = card.icon.trim();
    final isImage = icon.startsWith('/img/') || icon.startsWith('http');
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: sz.surface,
        borderRadius: BorderRadius.circular(size * 0.24),
        border: Border.all(color: sz.line),
      ),
      child: isImage
          ? SzImage(url: icon.startsWith('/') ? api.resolveUrl(icon) : icon, name: card.name, size: size, radius: size * 0.24)
          : Text(miniAppGlyphOf(card),
              style: szDisplay(fontSize: size * 0.42, fontWeight: FontWeight.w600, color: sz.inkMuted, height: 1.0)),
    );
  }
}

/// 格子里画哪个字:运营或开发者配的一个汉字照用;emoji、多个字退回名字的第一个字。
String miniAppGlyphOf(MiniAppCard a) {
  final icon = a.icon.trim();
  if (icon.isNotEmpty && icon.runes.length == 1 && _isCjk(icon.runes.first)) return icon;
  return szInitialOf(a.name);
}

bool _isCjk(int r) =>
    (r >= 0x3400 && r <= 0x9FFF) || (r >= 0xF900 && r <= 0xFAFF) || (r >= 0x20000 && r <= 0x2FA1F);

class _Splash extends StatelessWidget {
  const _Splash({required this.card, required this.api, required this.color});

  final MiniAppCard card;
  final ApiClient api;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ColoredBox(
      color: color,
      child: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          MiniAppIcon(card: card, api: api, size: 64),
          const SizedBox(height: 14),
          Text(card.name, style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink)),
          const SizedBox(height: 4),
          Text('由 ${card.developer.name.isEmpty ? '开发者' : card.developer.name} 提供',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          const SizedBox(height: 22),
          SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: sz.inkFaint)),
        ]),
      ),
    );
  }
}

class _ErrorPane extends StatelessWidget {
  const _ErrorPane({required this.message, required this.onRetry, required this.onClose});

  final String message;
  final VoidCallback onRetry;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ColoredBox(
      color: sz.paper,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(kPagePad * 1.5),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.cloud_off_outlined, size: 40, color: sz.inkFaint),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center, style: TextStyle(fontSize: kFontBodyLg, color: sz.ink)),
            const SizedBox(height: 18),
            Row(mainAxisSize: MainAxisSize.min, children: [
              OutlinedButton(onPressed: onClose, child: const Text('关闭')),
              const SizedBox(width: 12),
              FilledButton(onPressed: onRetry, child: const Text('重试')),
            ]),
          ]),
        ),
      ),
    );
  }
}

/// 全屏时的宿主胶囊:`···` 和关闭。浮在页面**上面**,页面盖不住;应用、小游戏全屏时都是它。
class MiniAppCapsule extends StatelessWidget {
  const MiniAppCapsule({super.key, required this.onMenu, required this.onClose});

  final VoidCallback onMenu;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Material(
      color: sz.surface.withValues(alpha: 0.86),
      shape: StadiumBorder(side: BorderSide(color: sz.line)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        IconButton(
            visualDensity: VisualDensity.compact, onPressed: onMenu, icon: Icon(Icons.more_horiz, color: sz.ink), tooltip: '更多'),
        Container(width: 1, height: 16, color: sz.line),
        IconButton(
            visualDensity: VisualDensity.compact, onPressed: onClose, icon: Icon(Icons.close, color: sz.ink), tooltip: '关闭'),
      ]),
    );
  }
}
