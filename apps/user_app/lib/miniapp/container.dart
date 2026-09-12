/// 小程序容器 v2(DEV-PROMPTS-39 #324):启动、呈现、宿主的那一圈界面。
///
/// ## 顶栏归宿主,页面画不到
///
/// 图标、名称、「由 XX 提供」和认证标记、`···`、关闭 —— 全是原生画在网页**外面**的,
/// 页面内容再怎么画也盖不住。这是防仿冒的关键:一个小程序可以把自己画成支付页,
/// 但画不掉顶栏上那行「由 XX 提供」。小游戏全屏时顶栏收成右上角的胶囊,同样盖不住。
///
/// ## 呈现
///
/// - 应用:半屏 → 全屏的弹层(拖顶栏);
/// - 小游戏:全屏路由,沉浸式,按 superz.json 锁方向,安全区照实下发。
///
/// ## 返回键
///
/// 页面显示了 BackButton → 系统返回交给页面(backButtonClicked);没显示 → 关闭
///(开了关闭确认的先问一句)。
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import '../session.dart';
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

/// 打开一个小程序。[card] 有就立刻出启动页(图标、名字),没有(直达链接)先查一次详情。
Future<void> openMiniApp(BuildContext context, ApiClient api,
    {required String appid, MiniAppCard? card, bool trial = false, String? startParam}) async {
  final messenger = ScaffoldMessenger.maybeOf(context);
  if (!miniAppSupported) {
    messenger?.showSnackBar(const SnackBar(content: Text('这个平台还不能打开小程序,请用手机 App 或网页版')));
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
  final frame = MiniAppFrame(
      api: api, card: c, trial: trial, startParam: startParam, fullscreen: c.isGame);
  if (c.isGame) {
    await Navigator.of(context).push(PageRouteBuilder(
      opaque: true,
      transitionDuration: SzMotion.of(context, SzMotion.base),
      pageBuilder: (_, __, ___) => frame,
      transitionsBuilder: (_, anim, __, child) => FadeTransition(opacity: anim, child: child),
    ));
  } else {
    await szShowSheet<void>(context: context, builder: (_) => frame, isDismissible: false);
  }
}

class MiniAppFrame extends StatefulWidget {
  const MiniAppFrame({
    super.key,
    required this.api,
    required this.card,
    this.trial = false,
    this.startParam,
    this.fullscreen = false,
  });

  final ApiClient api;
  final MiniAppCard card;
  final bool trial;
  final String? startParam;

  /// 小游戏全屏打开;应用在弹层里
  final bool fullscreen;

  @override
  State<MiniAppFrame> createState() => _MiniAppFrameState();
}

class _MiniAppFrameState extends State<MiniAppFrame> with WidgetsBindingObserver implements MiniAppUi {
  final _sheet = DraggableScrollableController();
  final _viewKey = GlobalKey<MiniAppViewState>();
  MiniAppController? _c;
  String? _error;
  bool _splash = true;
  bool _debug = false;
  bool? _starred;
  Timer? _splashTimer;
  Timer? _stableTimer;
  bool _closing = false;

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
    }
    WidgetsBinding.instance.addPostFrameCallback((_) => _launch());
  }

  Future<void> _launch() async {
    setState(() {
      _error = null;
      _splash = true;
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
      }
      setState(() => _c = c);
      if (old != null) _viewKey.currentState?.reload();
      if (widget.fullscreen) unawaited(lockOrientation(true));
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
    _c?.removeListener(_onController);
    _c?.dispose();
    _sheet.dispose();
    if (widget.fullscreen) {
      SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
      SystemChrome.setPreferredOrientations(const []);
    }
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
    if (_sheet.isAttached) {
      _sheet.animateTo(0.96, duration: SzMotion.of(context, SzMotion.base), curve: SzMotion.standard);
    }
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

  @override
  Future<bool> setFullscreen(bool on) async => widget.fullscreen;

  @override
  Future<bool> lockOrientation(bool lock) async {
    if (kIsWeb) return false;
    if (!lock) {
      await SystemChrome.setPreferredOrientations(const []);
      return true;
    }
    final o = _c?.launch.orientation ?? 'portrait';
    await SystemChrome.setPreferredOrientations(o == 'landscape'
        ? const [DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight]
        : o == 'any'
            ? const []
            : const [DeviceOrientation.portraitUp]);
    return true;
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

  // ---------------------------------------------------------------- 画

  void _report(BoxConstraints box) {
    final c = _c;
    if (c == null) return;
    final mq = MediaQuery.of(context);
    final bottomBar = c.mainButton.visible || c.secondaryButton.visible;
    c.updateSafeArea({
      'top': widget.fullscreen ? mq.padding.top : 0,
      'bottom': bottomBar ? 0 : mq.padding.bottom,
      'left': mq.padding.left,
      'right': mq.padding.right,
    }, {
      // 全屏时右上角有宿主的胶囊,内容要让开它
      'top': widget.fullscreen ? mq.padding.top + 48 : 0,
      'bottom': 0, 'left': 0, 'right': 0,
    });
    final h = box.maxHeight;
    final expanded = !_sheet.isAttached || _sheet.size > 0.9;
    c.updateViewport(h, stable: false, isExpanded: expanded);
    _stableTimer?.cancel();
    _stableTimer = Timer(const Duration(milliseconds: 300), () {
      if (mounted) c.updateViewport(h, stable: true);
    });
  }

  Widget _body() {
    final sz = Theme.of(context).sz;
    final c = _c;
    final bg = colorOf(c?.backgroundColor) ?? colorOf(c?.launch.backgroundColor) ?? sz.paper;
    return ColoredBox(
      color: bg,
      child: Stack(children: [
        if (c != null && _error == null)
          Positioned.fill(
            child: LayoutBuilder(builder: (context, box) {
              WidgetsBinding.instance.addPostFrameCallback((_) => _report(box));
              return MiniAppView(
                key: _viewKey,
                controller: c,
                debug: _debug,
                onError: (m) {
                  if (mounted) setState(() => _error = '页面没打开:$m');
                },
              );
            }),
          ),
        if (_error != null)
          _ErrorPane(message: _error!, onRetry: _launch, onClose: () => Navigator.of(context).maybePop())
        else
          IgnorePointer(
            ignoring: !_splash,
            child: AnimatedOpacity(
              opacity: _splash ? 1 : 0,
              duration: SzMotion.of(context, SzMotion.base),
              child: _Splash(card: card, api: widget.api, color: bg),
            ),
          ),
        if (widget.fullscreen)
          Positioned(
            top: MediaQuery.paddingOf(context).top + 8,
            right: 10,
            child: _Capsule(onMenu: _menu, onClose: _requestClose),
          ),
      ]),
    );
  }

  Widget _bottomBar() {
    final c = _c;
    if (c == null || !(c.mainButton.visible || c.secondaryButton.visible)) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    Widget button(BottomButtonState s, VoidCallback onTap, {required bool primary}) {
      final bg = colorOf(s.color) ?? (primary ? sz.clay : sz.surface);
      final fg = colorOf(s.textColor) ?? (primary ? sz.surface : sz.ink);
      final child = s.progress
          ? SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: fg))
          : Text(s.text.isEmpty ? (primary ? '继续' : '取消') : s.text,
              maxLines: 1, overflow: TextOverflow.ellipsis);
      final enabled = s.active && !s.progress;
      return primary
          ? FilledButton(
              style: FilledButton.styleFrom(backgroundColor: bg, foregroundColor: fg, minimumSize: const Size.fromHeight(46)),
              onPressed: enabled ? onTap : null,
              child: child)
          : OutlinedButton(
              style: OutlinedButton.styleFrom(foregroundColor: fg, backgroundColor: bg, minimumSize: const Size.fromHeight(46)),
              onPressed: enabled ? onTap : null,
              child: child);
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
      color: sz.paper,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 8),
          child: vertical
              ? Column(mainAxisSize: MainAxisSize.min, children: [
                  for (final (i, w) in items.indexed) ...[if (i > 0) const SizedBox(height: 8), w],
                ])
              : Row(children: [
                  for (final (i, w) in items.indexed) ...[if (i > 0) const SizedBox(width: 10), Expanded(child: w)],
                ]),
        ),
      ),
    );
  }

  Widget _header(ScrollController? drag) {
    final sz = Theme.of(context).sz;
    final c = _c;
    final headerBg = colorOf(c?.headerColor) ?? sz.paper;
    final dark = ThemeData.estimateBrightnessForColor(headerBg) == Brightness.dark;
    final fg = dark ? SzColors.dark.ink : SzColors.light.ink;
    return Material(
      color: headerBg,
      child: SingleChildScrollView(
        controller: drag,
        physics: const ClampingScrollPhysics(),
        child: Column(children: [
          // 拖拽条由 szShowSheet 按主题画(底部弹层才有),这里不再画第二条
          Padding(
            padding: const EdgeInsets.fromLTRB(6, 4, 6, 4),
            child: Row(children: [
              if (c != null && c.backButtonVisible)
                IconButton(onPressed: c.clickBack, icon: Icon(Icons.arrow_back, color: fg), tooltip: '返回')
              else
                const SizedBox(width: 10),
              Expanded(child: _AppIdentity(card: card, trial: widget.trial, api: widget.api, color: fg, compact: true)),
              IconButton(onPressed: _menu, icon: Icon(Icons.more_horiz, color: fg), tooltip: '更多'),
              IconButton(onPressed: _requestClose, icon: Icon(Icons.close, color: fg), tooltip: '关闭'),
            ]),
          ),
          Divider(height: 1, color: sz.line),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final page = PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _onBack();
      },
      child: widget.fullscreen
          ? Scaffold(body: Column(children: [Expanded(child: _body()), _bottomBar()]))
          : _sheetBody(),
    );
    return page;
  }

  Widget _sheetBody() {
    Widget content(ScrollController? drag) =>
        Column(children: [_header(drag), Expanded(child: _body()), _bottomBar()]);
    if (!isSheetBottom(context)) {
      return SizedBox(height: MediaQuery.sizeOf(context).height * 0.8, child: content(null));
    }
    return DraggableScrollableSheet(
      controller: _sheet,
      expand: false,
      initialChildSize: 0.72,
      minChildSize: 0.45,
      maxChildSize: 0.96,
      builder: (context, drag) => content(drag),
    );
  }
}

/// 图标 + 名称 + 「由 XX 提供 · 认证」。顶栏、菜单、启动页共用 —— 同一个应用在哪儿都是同一副样子。
class _AppIdentity extends StatelessWidget {
  const _AppIdentity({required this.card, required this.api, this.trial = false, this.color, this.compact = false});

  final MiniAppCard card;
  final ApiClient api;
  final bool trial;
  final Color? color;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final ink = color ?? sz.ink;
    final dev = card.developer;
    return Row(children: [
      MiniAppIcon(card: card, api: api, size: compact ? 28 : 40),
      const SizedBox(width: 10),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            Flexible(
              child: Text(card.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: compact ? kFontBodyLg : kFontTitle, fontWeight: FontWeight.w600, color: ink)),
            ),
            if (trial) ...[
              const SizedBox(width: 6),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                decoration: BoxDecoration(color: sz.claySoft, borderRadius: BorderRadius.circular(4)),
                child: Text('体验版', style: TextStyle(fontSize: kFontMicro, color: sz.clay)),
              ),
            ],
          ]),
          Text(
            '由 ${dev.name.isEmpty ? '开发者' : dev.name} 提供${dev.label.isEmpty ? '' : ' · ${dev.label}'}',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: kFontMicro, color: ink.withValues(alpha: 0.62)),
          ),
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

/// 小游戏全屏时的宿主胶囊:`···` 和关闭。浮在页面**上面**,页面盖不住。
class _Capsule extends StatelessWidget {
  const _Capsule({required this.onMenu, required this.onClose});

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
