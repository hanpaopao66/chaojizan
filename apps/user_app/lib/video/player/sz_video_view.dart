import 'dart:async';
import 'dart:math';

import 'package:clock/clock.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:video_player/video_player.dart';

import '../danmaku/layer.dart';
import '../danmaku/sheets.dart';
import '../models.dart';
import 'browser_fullscreen.dart';
import 'controls.dart';
import 'player_logic.dart';
import 'sz_video_controller.dart';

/// 视频播放器(#359):16:9 画面 + 全套控件 + 手势 + 弹幕层。
///
/// 全屏按钮自己推一个全屏路由:横屏视频把屏幕转成横屏,竖屏视频不转;退出全屏回到这里。
/// [onBack] 给了就在左上角放返回键(详情页传 pop);[title] 只在全屏的顶栏里显示。
///
/// 手势(判定逻辑在 player_logic.dart,单测覆盖):
///
/// | 手势 | 作用 |
/// |---|---|
/// | 单击 | 显示 / 隐藏控件(点中一条弹幕则出弹幕菜单) |
/// | 双击 | 暂停 / 播放 |
/// | 横滑 | 快进快退,松手才跳,滑的时候显示目标时间和缩略图 |
/// | 左半边上下滑 | 亮度(盖一层黑模拟,见 [dimAlphaFor]) |
/// | 右半边上下滑 | 音量(播放器音量,不是系统音量) |
/// | 长按 | 3 倍速,松手恢复 |
///
/// 控件 3 秒不动自动隐藏(暂停、出错、播完时常驻)。全屏时左侧有锁,锁上后只剩解锁按钮。
class SzVideoView extends StatefulWidget {
  const SzVideoView({super.key, required this.controller, this.onBack, this.title});

  final SzVideoController controller;
  final VoidCallback? onBack;
  final String? title;

  @override
  State<SzVideoView> createState() => _SzVideoViewState();
}

class _SzVideoViewState extends State<SzVideoView> {
  /// 从全屏回来时加一,让画面换一个新的 VideoPlayer。
  ///
  /// 网页版的 VideoPlayer 是一个 `<video>` 元素的平台视图,同一个元素只能待在一处:
  /// 全屏页的平台视图建出来时把它挪走了,回来时这里原来那个平台视图已经是空的(黑屏)。
  /// 换 key 重建一个平台视图,元素就挪回来了。手机上重建一个 Texture 没有副作用。
  int _gen = 0;
  bool _entering = false;

  Future<void> _enterFullscreen() async {
    if (_entering) return;
    _entering = true;
    final c = widget.controller;
    c.fullscreen = true;
    // 网页版先进浏览器真全屏(要在点击事件里同步发起,所以放在所有 await 之前),
    // 进去了再锁方向:手机浏览器只在全屏里认方向锁。手机 App 上这一步是空的,直接锁方向。
    // 横屏视频转横屏;竖屏视频不转(锁竖屏,手机横着拿也不转过去)
    final orientations = c.isVertical
        ? const [DeviceOrientation.portraitUp]
        : const [DeviceOrientation.landscapeLeft, DeviceOrientation.landscapeRight];
    unawaited(enterBrowserFullscreen().whenComplete(() => SystemChrome.setPreferredOrientations(orientations)));
    unawaited(SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky));
    unawaited(c.keepPlayingAcrossViewChange());
    await Navigator.of(context, rootNavigator: true).push(PageRouteBuilder<void>(
      settings: const RouteSettings(name: 'video-fullscreen'),
      transitionDuration: const Duration(milliseconds: 180),
      reverseTransitionDuration: const Duration(milliseconds: 180),
      pageBuilder: (_, __, ___) => _FullscreenPage(controller: c, title: widget.title),
      transitionsBuilder: (_, a, __, child) => FadeTransition(opacity: a, child: child),
    ));
    // 和小程序容器退出全屏时一样恢复:方向放开、系统栏回来
    unawaited(exitBrowserFullscreen());
    unawaited(SystemChrome.setPreferredOrientations(const []));
    unawaited(SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge));
    c.fullscreen = false;
    _entering = false;
    unawaited(c.keepPlayingAcrossViewChange());
    if (mounted) setState(() => _gen++);
  }

  @override
  Widget build(BuildContext context) {
    return AspectRatio(
      aspectRatio: 16 / 9,
      child: _PlayerFrame(
        controller: widget.controller,
        fullscreen: false,
        onBack: widget.onBack,
        title: widget.title,
        videoKey: ValueKey('inline-$_gen'),
        onFullscreen: _enterFullscreen,
      ),
    );
  }
}

/// 全屏页:整屏黑底,只放播放器。用 Scaffold(不带 appBar)是为了弹幕菜单这些 SnackBar 有地方显示。
class _FullscreenPage extends StatelessWidget {
  const _FullscreenPage({required this.controller, this.title});

  final SzVideoController controller;
  final String? title;

  @override
  Widget build(BuildContext context) {
    void back() => Navigator.of(context).maybePop();
    return Scaffold(
      backgroundColor: Colors.black,
      resizeToAvoidBottomInset: false,
      body: _PlayerFrame(
        controller: controller,
        fullscreen: true,
        onBack: back,
        title: title,
        videoKey: const ValueKey('fullscreen'),
        onFullscreen: back,
      ),
    );
  }
}

enum _Panel { none, more, quality, speed, parts }

class _PlayerFrame extends StatefulWidget {
  const _PlayerFrame({
    required this.controller,
    required this.fullscreen,
    required this.videoKey,
    required this.onFullscreen,
    this.onBack,
    this.title,
  });

  final SzVideoController controller;
  final bool fullscreen;
  final Key videoKey;
  final VoidCallback onFullscreen;
  final VoidCallback? onBack;
  final String? title;

  @override
  State<_PlayerFrame> createState() => _PlayerFrameState();
}

class _PlayerFrameState extends State<_PlayerFrame> {
  static const _hideAfter = Duration(seconds: 3);

  final _layerKey = GlobalKey<DanmakuLayerState>();
  final _taps = TapSequence();
  // 判单双击的计时。用 package:clock 的而不是 Stopwatch():线上一样是真实时间,
  // widget 测试里跟着模拟时间走 —— Stopwatch 量的是真实时间,测试机一忙就把双击判成两次单击
  final _clock = clock.stopwatch()..start();

  bool _controls = true;
  Timer? _hideTimer;
  bool _locked = false;
  bool _wasPlaying = false;
  bool _wasEnded = false;
  bool _hadError = false;

  Timer? _tapTimer;
  Danmaku? _tapHit;

  PlayerGesture? _drag;
  int _dragFromMs = 0;
  double _dragFromLevel = 0;
  double _dragDx = 0;
  double _dragDy = 0;
  int? _seekTo;
  bool _scrubbing = false;

  _Panel _panel = _Panel.none;

  String? _toast;
  Timer? _toastTimer;
  int _seenNotice = 0;
  int? _resumeSeen;
  Timer? _resumeTimer;

  SzVideoController get c => widget.controller;
  bool get fs => widget.fullscreen;

  void Function()? _unlistenFs;

  @override
  void initState() {
    super.initState();
    _seenNotice = c.noticeSeq;
    c.addListener(_onController);
    if (!c.initialized && c.error == null) unawaited(c.initialize());
    _watchResume();
    _kickHide();
    HardwareKeyboard.instance.addHandler(_onKey);
    // 网页版按 Esc 是浏览器自己退的全屏,页面收不到那个键:跟着把全屏页也退掉
    if (fs) {
      _unlistenFs = onBrowserFullscreenExit(() {
        if (mounted && (ModalRoute.of(context)?.isCurrent ?? false)) widget.onFullscreen();
      });
    }
  }

  /// 电脑上的快捷键(和 B 站网页版一样):空格播放 / 暂停、← → 快退快进 5 秒、↑ ↓ 音量、F 全屏、D 弹幕开关。
  /// 被别的页面盖着(小窗那一个在全屏页底下)、上面有弹层、正在打字的时候不接
  bool _onKey(KeyEvent e) {
    if (e is! KeyDownEvent && e is! KeyRepeatEvent) return false;
    if (!mounted || !TickerMode.valuesOf(context).enabled) return false;
    if (!(ModalRoute.of(context)?.isCurrent ?? true)) return false;
    if (FocusManager.instance.primaryFocus?.context?.widget is EditableText) return false;
    final k = e.logicalKey;
    final down = e is KeyDownEvent;
    if (k == LogicalKeyboardKey.space && down) {
      unawaited(c.togglePlay());
      _showControls();
    } else if (k == LogicalKeyboardKey.arrowRight || k == LogicalKeyboardKey.arrowLeft) {
      final step = k == LogicalKeyboardKey.arrowRight ? 5000 : -5000;
      final to = (c.position.inMilliseconds + step).clamp(0, max(0, c.duration.inMilliseconds - 500)).toInt();
      unawaited(c.seekTo(Duration(milliseconds: to)));
      _showControls();
    } else if (k == LogicalKeyboardKey.arrowUp || k == LogicalKeyboardKey.arrowDown) {
      final v = (c.volume + (k == LogicalKeyboardKey.arrowUp ? .1 : -.1)).clamp(0.0, 1.0);
      unawaited(c.setVolume(v));
      _showToast('音量 ${(v * 100).round()}%');
    } else if (k == LogicalKeyboardKey.keyF && down) {
      widget.onFullscreen();
    } else if (k == LogicalKeyboardKey.keyD && down && c.danmaku.allowDanmaku) {
      final on = !c.danmaku.settings.enabled;
      unawaited(c.danmaku.setEnabled(on));
      _showToast(on ? '弹幕已打开' : '弹幕已关闭');
    } else {
      return false;
    }
    return true;
  }

  @override
  void didUpdateWidget(_PlayerFrame oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.controller, widget.controller)) {
      oldWidget.controller.removeListener(_onController);
      widget.controller.addListener(_onController);
      _seenNotice = c.noticeSeq;
      if (!c.initialized && c.error == null) unawaited(c.initialize());
    }
  }

  @override
  void dispose() {
    c.removeListener(_onController);
    HardwareKeyboard.instance.removeHandler(_onKey);
    _unlistenFs?.call();
    _hideTimer?.cancel();
    _tapTimer?.cancel();
    _toastTimer?.cancel();
    _resumeTimer?.cancel();
    // 长按着退出页面(或者锁屏按了返回)时松手事件不会来,别让 3 倍速留在控制器上
    if (c.boosting) unawaited(c.endBoost());
    super.dispose();
  }

  void _onController() {
    if (!mounted) return;
    if (c.noticeSeq != _seenNotice) {
      _seenNotice = c.noticeSeq;
      final n = c.notice;
      if (n != null) _showToast(n);
    }
    _watchResume();
    // 视频停下来(暂停、播完、出错)时把控件叫出来:控件是播着的时候自己隐藏的,
    // 停了还藏着的话,用户看到的是一个不动的画面,不知道是卡了还是完了
    final stopped = (_wasPlaying && !c.playing && !c.buffering) ||
        (c.ended && !_wasEnded) ||
        (c.error != null && !_hadError);
    _wasPlaying = c.playing;
    _wasEnded = c.ended;
    _hadError = c.error != null;
    if (stopped && !_controls && !_locked) _controls = true;
    if (!_canAutoHide) {
      _cancelHide();
    } else if (_controls && _hideTimer == null) {
      _kickHide();
    }
    setState(() {});
  }

  // ---------------------------------------------------------------- 控件显隐

  /// 暂停、出错、播完、菜单开着、正拖着的时候控件不自动隐藏(锁上时那颗锁照样 3 秒后隐藏)
  bool get _canAutoHide =>
      _locked ||
      (c.playing && c.error == null && !c.ended && _panel == _Panel.none && !_scrubbing && _drag == null);

  void _cancelHide() {
    _hideTimer?.cancel();
    _hideTimer = null;
  }

  void _kickHide() {
    _cancelHide();
    if (!_canAutoHide) return;
    _hideTimer = Timer(_hideAfter, () {
      _hideTimer = null;
      if (mounted && _canAutoHide) setState(() => _controls = false);
    });
  }

  void _showControls() {
    if (!_controls) setState(() => _controls = true);
    _kickHide();
  }

  void _toggleControls() {
    setState(() => _controls = !_controls);
    if (_controls) _kickHide();
  }

  void _showToast(String s) {
    _toastTimer?.cancel();
    setState(() => _toast = s);
    _toastTimer = Timer(const Duration(seconds: 2), () {
      if (mounted) setState(() => _toast = null);
    });
  }

  void _watchResume() {
    final at = c.resumeHintMs;
    if (at == null || at == _resumeSeen) return;
    _resumeSeen = at;
    _resumeTimer?.cancel();
    _resumeTimer = Timer(const Duration(seconds: 6), c.dismissResumeHint);
  }

  void _openPanel(_Panel p) {
    setState(() => _panel = p);
    _cancelHide();
  }

  void _closePanel() {
    setState(() => _panel = _Panel.none);
    _kickHide();
  }

  void _toggleLock() {
    setState(() {
      _locked = !_locked;
      _panel = _Panel.none;
      _controls = true;
    });
    _kickHide();
  }

  Future<void> _toggleDanmaku() async {
    final on = !c.danmaku.settings.enabled;
    await c.danmaku.setEnabled(on);
    _showToast(on ? '弹幕已打开' : '弹幕已关闭');
    _kickHide();
  }

  // ---------------------------------------------------------------- 手势

  void _onTapUp(TapUpDetails d) {
    if (_locked) {
      _toggleControls();
      return;
    }
    if (_panel != _Panel.none) {
      _closePanel();
      return;
    }
    final now = _clock.elapsedMilliseconds;
    final p = d.localPosition;
    final g = _taps.up(now, p.dx, p.dy);
    // 鼠标和手指是两套习惯(B 站网页版 / App 各是各的):鼠标单击 = 播放 / 暂停、双击 = 全屏,
    // 控件靠悬停出来;手指单击 = 叫出 / 收起控件、双击 = 播放 / 暂停。
    // 不分的话,鼠标一移过来控件就出来了,再一点反而把控件收了,看着像点了没反应
    final mouse = d.kind == PointerDeviceKind.mouse;
    if (g == PlayerGesture.doubleTap) {
      _tapTimer?.cancel();
      _tapHit = null;
      if (mouse) {
        widget.onFullscreen();
      } else {
        unawaited(c.togglePlay());
        _showControls();
      }
      return;
    }
    // 点中哪条弹幕要在抬手这一刻判:等单击确认的 300ms 里弹幕已经飞出去十几像素了
    _tapHit = c.danmaku.showing ? _layerKey.currentState?.hitTest(p) : null;
    _tapTimer?.cancel();
    _tapTimer = Timer(const Duration(milliseconds: kDoubleTapMs), () {
      if (!mounted || !_taps.stillSingle(now)) return;
      _taps.reset();
      final hit = _tapHit;
      _tapHit = null;
      if (hit != null) {
        unawaited(showDanmakuActions(context, c, hit));
      } else if (mouse) {
        unawaited(c.togglePlay());
        _showControls();
      } else {
        _toggleControls();
      }
    });
  }

  void _onDragStart(bool horizontal, DragStartDetails d, Size size) {
    if (_locked) return;
    _tapTimer?.cancel();
    _taps.reset();
    final g = classifyDrag(horizontal: horizontal, startX: d.localPosition.dx, width: size.width);
    _drag = g;
    _dragDx = 0;
    _dragDy = 0;
    switch (g) {
      case PlayerGesture.seek:
        _dragFromMs = c.position.inMilliseconds;
        _seekTo = _dragFromMs;
        precacheSprites(context, c);
      case PlayerGesture.brightness:
        _dragFromLevel = c.brightness;
      case PlayerGesture.volume:
        _dragFromLevel = c.volume;
      default:
        break;
    }
    _cancelHide();
    setState(() {});
  }

  void _onDragUpdate(DragUpdateDetails d, Size size) {
    final g = _drag;
    if (g == null) return;
    _dragDx += d.delta.dx;
    _dragDy += d.delta.dy;
    switch (g) {
      case PlayerGesture.seek:
        _seekTo = seekTargetMs(
            startMs: _dragFromMs, dx: _dragDx, width: size.width, durationMs: c.duration.inMilliseconds);
      case PlayerGesture.brightness:
        c.setBrightness(levelAfterDrag(start: _dragFromLevel, dy: _dragDy, height: size.height));
      case PlayerGesture.volume:
        unawaited(c.setVolume(levelAfterDrag(start: _dragFromLevel, dy: _dragDy, height: size.height)));
      default:
        break;
    }
    setState(() {});
  }

  void _onDragEnd() {
    final g = _drag;
    final to = _seekTo;
    _drag = null;
    _seekTo = null;
    if (g == PlayerGesture.seek && to != null) unawaited(c.seekTo(Duration(milliseconds: to)));
    setState(() {});
    _kickHide();
  }

  void _onScrub(bool on) {
    setState(() => _scrubbing = on);
    if (on) {
      _cancelHide();
    } else {
      _kickHide();
    }
  }

  Future<void> _openSender() async {
    _cancelHide();
    await showDanmakuSender(context, c);
    _kickHide();
  }

  // ---------------------------------------------------------------- 画面

  @override
  Widget build(BuildContext context) {
    Widget frame = LayoutBuilder(builder: (context, box) {
      final size = Size(box.maxWidth, box.maxHeight);
      final ui = _controls && !_locked;
      return MouseRegion(
        // 网页 / 桌面上鼠标一动就把控件叫出来(手机上没有悬停,不影响)
        onHover: (_) => _controls ? _kickHide() : _showControls(),
        child: ColoredBox(
          color: Colors.black,
          child: ClipRect(
            child: Stack(fit: StackFit.expand, children: [
              _picture(),
              if (c.brightness < 0.999)
                IgnorePointer(child: ColoredBox(color: Colors.black.withValues(alpha: dimAlphaFor(c.brightness)))),
              if (c.danmaku.showing) IgnorePointer(child: DanmakuLayer(key: _layerKey, controller: c)),
              Positioned.fill(child: _gestures(size)),
              IgnorePointer(child: _indicators()),
              if (c.error != null)
                _errorView()
              else if (c.ended && !c.buffering)
                _endedView(),
              if (!c.playing && !c.ended && c.error == null && !c.buffering && c.initialized)
                _centerPlay(ui),
              // 锁上以后只剩那颗解锁按钮:顶栏底栏直接不建(只是透明的话还能被读屏和键盘点到)
              if (!_locked) _topBar(ui),
              if (!_locked) _bottomBar(ui),
              if (fs) _lockButton(_controls),
              // 拖进度条 / 横滑的时候先收起续播提示,不然和缩略图叠在一起
              if (c.resumeHintMs != null && !_locked && !_scrubbing && _drag == null) _resumeHint(ui),
              if (_toast != null && !_locked) _toastView(ui),
              if (_panel != _Panel.none) _panelView(size),
            ]),
          ),
        ),
      );
    });
    if (fs) {
      // 锁着的时候系统返回键不退全屏(横屏看剧最常见的误触),只把解锁按钮叫出来
      frame = PopScope(
        canPop: !_locked,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop) _showControls();
        },
        child: frame,
      );
    }
    return frame;
  }

  Widget _picture() {
    final raw = c.raw;
    final ready = raw != null && raw.value.isInitialized;
    final cover = c.video.card.cover;
    return Stack(fit: StackFit.expand, children: [
      // 画面出来之前先垫封面,别让人对着黑屏等
      if (!ready && cover.isNotEmpty)
        Image(
          image: szNetImage(c.resolveUrl(cover)),
          fit: BoxFit.contain,
          errorBuilder: (_, __, ___) => const SizedBox.shrink(),
        ),
      if (raw != null)
        Center(
          child: AspectRatio(
            aspectRatio: c.aspectRatio,
            child: KeyedSubtree(key: widget.videoKey, child: VideoPlayer(raw)),
          ),
        ),
    ]);
  }

  Widget _gestures(Size size) => GestureDetector(
        behavior: HitTestBehavior.opaque,
        // 拖动的起点取按下的位置(不是越过阈值的位置):左右半边按按下的地方分
        dragStartBehavior: DragStartBehavior.down,
        onTapUp: _onTapUp,
        onLongPressStart: _locked ? null : (_) => c.startBoost(),
        onLongPressEnd: (_) => c.endBoost(),
        onLongPressCancel: () => c.endBoost(),
        onHorizontalDragStart: _locked ? null : (d) => _onDragStart(true, d, size),
        onHorizontalDragUpdate: _locked ? null : (d) => _onDragUpdate(d, size),
        onHorizontalDragEnd: _locked ? null : (_) => _onDragEnd(),
        onHorizontalDragCancel: _locked ? null : _onDragEnd,
        onVerticalDragStart: _locked ? null : (d) => _onDragStart(false, d, size),
        onVerticalDragUpdate: _locked ? null : (d) => _onDragUpdate(d, size),
        onVerticalDragEnd: _locked ? null : (_) => _onDragEnd(),
        onVerticalDragCancel: _locked ? null : _onDragEnd,
      );

  Widget _indicators() {
    Widget? center;
    final g = _drag;
    if (g == PlayerGesture.seek && _seekTo != null) {
      final to = _seekTo!;
      final delta = ((to - _dragFromMs) / 1000).round();
      center = Column(mainAxisSize: MainAxisSize.min, children: [
        if (c.part.sprite != null) ...[
          SpriteThumb(controller: c, ms: to, maxWidth: fs ? 200 : 144, maxHeight: fs ? 113 : 81),
          const SizedBox(height: 6),
        ],
        PlayerPill(
          child: Text.rich(TextSpan(children: [
            TextSpan(text: playerClock(to), style: const TextStyle(fontSize: kFigureMd, fontWeight: FontWeight.w600)),
            TextSpan(text: ' / ${playerClock(c.duration.inMilliseconds)}'),
            TextSpan(text: '   ${delta >= 0 ? '+' : '−'}${delta.abs()} 秒'),
          ])),
        ),
      ]);
    } else if (g == PlayerGesture.brightness || g == PlayerGesture.volume) {
      final bright = g == PlayerGesture.brightness;
      final v = bright ? c.brightness : c.volume;
      final icon = bright
          ? Icons.brightness_6_outlined
          : (v <= 0 ? Icons.volume_off_outlined : Icons.volume_up_outlined);
      center = PlayerPill(
        child: SizedBox(
          width: 150,
          child: Row(children: [
            Icon(icon, color: Colors.white, size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: ClipRRect(
                borderRadius: BorderRadius.circular(2),
                child: LinearProgressIndicator(
                  value: v,
                  minHeight: 4,
                  color: kPlayerAccent,
                  backgroundColor: Colors.white.withValues(alpha: .25),
                ),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(width: 34, child: Text('${(v * 100).round()}%', textAlign: TextAlign.end)),
          ]),
        ),
      );
    } else if (c.buffering && c.error == null) {
      center = const SizedBox(
        width: 34,
        height: 34,
        child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white),
      );
    }
    return Stack(fit: StackFit.expand, children: [
      if (center != null) Center(child: center),
      if (c.boosting)
        Positioned(
          top: fs ? 24 : 12,
          left: 0,
          right: 0,
          child: const Center(
            child: PlayerPill(
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.fast_forward_rounded, color: Colors.white, size: 18),
                SizedBox(width: 4),
                Text('3 倍速播放中'),
              ]),
            ),
          ),
        ),
    ]);
  }

  Widget _errorView() => Positioned.fill(
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: c.retry,
          child: Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.error_outline, color: Colors.white70, size: 32),
              const SizedBox(height: 8),
              Text(c.error!, style: kPlayerText, textAlign: TextAlign.center),
            ]),
          ),
        ),
      );

  Widget _endedView() {
    Widget action(IconData icon, String label, VoidCallback onTap) => InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(kRadiusMd),
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Icon(icon, color: Colors.white, size: 30),
              const SizedBox(height: 4),
              Text(label, style: kPlayerNote),
            ]),
          ),
        );
    return Positioned.fill(
      child: ColoredBox(
        color: Colors.black.withValues(alpha: .45),
        child: Center(
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            action(Icons.replay_rounded, '重播', () => c.play()),
            if (c.hasNextPart) ...[
              const SizedBox(width: 28),
              action(Icons.skip_next_rounded, '下一 P', () => c.switchPart(c.partIndex + 1)),
            ],
          ]),
        ),
      ),
    );
  }

  Widget _centerPlay(bool visible) => Center(
        child: IgnorePointer(
          ignoring: !visible,
          child: AnimatedOpacity(
            opacity: visible ? 1 : 0,
            duration: const Duration(milliseconds: 200),
            child: Material(
              color: Colors.black.withValues(alpha: .35),
              shape: const CircleBorder(),
              child: IconButton(
                tooltip: '播放',
                iconSize: 40,
                onPressed: c.play,
                icon: const Icon(Icons.play_arrow_rounded, color: Colors.white),
              ),
            ),
          ),
        ),
      );

  Widget _fade(bool visible, Widget child) => IgnorePointer(
        ignoring: !visible,
        child: AnimatedOpacity(opacity: visible ? 1 : 0, duration: const Duration(milliseconds: 200), child: child),
      );

  /// 控件条的渐变底色**不接手势**,只有按钮接。
  ///
  /// 底色接手势的话,控件露出来时上下两条加起来占了小窗将近一半高,从那里起手的横滑、竖滑全没反应
  /// (走查时实测:在顶栏那一溜往下滑调亮度,纹丝不动)。B 站也是只有按钮本身挡手势。
  Widget _barBackground({required bool top}) => Positioned.fill(
        child: IgnorePointer(
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: top ? Alignment.topCenter : Alignment.bottomCenter,
                end: top ? Alignment.bottomCenter : Alignment.topCenter,
                colors: [Colors.black.withValues(alpha: top ? .6 : .65), Colors.black.withValues(alpha: 0)],
              ),
            ),
          ),
        ),
      );

  /// 控件条上的纯文字(标题、时间)也不接手势,理由同上
  Widget _label(String s, TextStyle style) =>
      IgnorePointer(child: Text(s, maxLines: 1, overflow: TextOverflow.ellipsis, style: style));

  Widget _topBar(bool visible) {
    final title = widget.title;
    return Positioned(
      top: 0,
      left: 0,
      right: 0,
      child: _fade(
        visible,
        Stack(children: [
          _barBackground(top: true),
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: SafeArea(
              top: fs,
              bottom: false,
              left: fs,
              right: fs,
              child: SizedBox(
                height: 44,
                child: Row(children: [
                  if (widget.onBack != null)
                    PlayerIconButton(
                      icon: Icons.arrow_back_ios_new_rounded,
                      tooltip: fs ? '退出全屏' : '返回',
                      size: 20,
                      onPressed: widget.onBack,
                    )
                  else
                    const SizedBox(width: 12),
                  Expanded(
                    child: fs && title != null && title.isNotEmpty
                        ? _label(title, kPlayerText.copyWith(fontSize: kFontBodyLg, fontWeight: FontWeight.w600))
                        : const SizedBox.shrink(),
                  ),
                  PlayerIconButton(icon: Icons.more_vert, tooltip: '更多', onPressed: () => _openPanel(_Panel.more)),
                ]),
              ),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _bottomBar(bool visible) => Positioned(
        left: 0,
        right: 0,
        bottom: 0,
        child: _fade(
          visible,
          Stack(children: [
            _barBackground(top: false),
            Padding(
              padding: const EdgeInsets.only(top: 18),
              child: SafeArea(
                top: false,
                bottom: fs,
                left: fs,
                right: fs,
                child: fs ? _fullBottom() : _inlineBottom(),
              ),
            ),
          ]),
        ),
      );

  Widget _playButton() => PlayerIconButton(
        icon: c.playing ? Icons.pause_rounded : Icons.play_arrow_rounded,
        tooltip: c.playing ? '暂停' : '播放',
        size: 28,
        onPressed: c.togglePlay,
      );

  Widget _danmakuToggle() {
    final on = c.danmaku.settings.enabled;
    return PlayerIconButton(
      icon: on ? Icons.subtitles_outlined : Icons.subtitles_off_outlined,
      tooltip: on ? '关闭弹幕' : '打开弹幕',
      onPressed: _toggleDanmaku,
    );
  }

  Widget _inlineBottom() {
    final pos = c.position.inMilliseconds;
    final dur = c.duration.inMilliseconds;
    return Row(children: [
      _playButton(),
      Expanded(child: PlayerProgressBar(controller: c, onScrub: _onScrub)),
      const SizedBox(width: 8),
      _label('${playerClock(pos)} / ${playerClock(dur)}', kPlayerMicro),
      if (c.danmaku.allowDanmaku) _danmakuToggle(),
      PlayerIconButton(icon: Icons.fullscreen_rounded, tooltip: '全屏', size: 26, onPressed: widget.onFullscreen),
    ]);
  }

  Widget _fullBottom() {
    final pos = c.position.inMilliseconds;
    final dur = c.duration.inMilliseconds;
    final allow = c.danmaku.allowDanmaku;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(children: [
          _label(playerClock(pos), kPlayerNote),
          const SizedBox(width: 10),
          Expanded(child: PlayerProgressBar(controller: c, onScrub: _onScrub)),
          const SizedBox(width: 10),
          _label(playerClock(dur), kPlayerNote),
        ]),
      ),
      LayoutBuilder(builder: (context, box) {
        // 竖屏视频的全屏只有手机那么宽:输入条放不下就换成一个图标
        final narrow = box.maxWidth < 560;
        return Row(children: [
          const SizedBox(width: 4),
          _playButton(),
          if (c.hasNextPart)
            PlayerIconButton(
              icon: Icons.skip_next_rounded,
              tooltip: '下一 P',
              size: 26,
              onPressed: () => c.switchPart(c.partIndex + 1),
            ),
          if (allow) _danmakuToggle(),
          if (allow)
            PlayerIconButton(icon: Icons.tune, tooltip: '弹幕设置', onPressed: () => showDanmakuSettings(context, c.danmaku)),
          if (allow && !narrow)
            Expanded(child: _sendPill())
          else ...[
            if (allow) PlayerIconButton(icon: Icons.edit_outlined, tooltip: '发弹幕', onPressed: _openSender),
            const Spacer(),
          ],
          PlayerTextButton(label: speedLabel(c.speed), onPressed: () => _openPanel(_Panel.speed)),
          PlayerTextButton(
            label: c.autoQuality ? '自动' : qualityShort(c.quality?.q ?? 0),
            onPressed: () => _openPanel(_Panel.quality),
          ),
          if (c.video.parts.length > 1) PlayerTextButton(label: '选集', onPressed: () => _openPanel(_Panel.parts)),
          const SizedBox(width: 4),
        ]);
      }),
    ]);
  }

  Widget _sendPill() => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8),
        child: Material(
          color: Colors.white.withValues(alpha: .16),
          borderRadius: BorderRadius.circular(16),
          child: InkWell(
            borderRadius: BorderRadius.circular(16),
            onTap: _openSender,
            child: Container(
              height: 32,
              alignment: Alignment.centerLeft,
              padding: const EdgeInsets.symmetric(horizontal: 14),
              child: Text('发个友善的弹幕见证当下',
                  maxLines: 1, overflow: TextOverflow.ellipsis, style: kPlayerNote.copyWith(color: Colors.white70)),
            ),
          ),
        ),
      );

  Widget _lockButton(bool visible) {
    final pad = MediaQuery.paddingOf(context);
    return Positioned(
      left: 12 + pad.left,
      top: 0,
      bottom: 0,
      child: Center(
        child: _fade(
          visible,
          Material(
            color: Colors.black.withValues(alpha: .38),
            shape: const CircleBorder(),
            child: IconButton(
              tooltip: _locked ? '解锁' : '锁定',
              onPressed: _toggleLock,
              icon: Icon(_locked ? Icons.lock_outline_rounded : Icons.lock_open_rounded, color: Colors.white),
            ),
          ),
        ),
      ),
    );
  }

  double _bottomInset(bool controlsUp) {
    final pad = fs ? MediaQuery.paddingOf(context).bottom : 0.0;
    return (controlsUp ? (fs ? 100.0 : 58.0) : 10.0) + pad;
  }

  Widget _resumeHint(bool controlsUp) => Positioned(
        left: 12 + (fs ? MediaQuery.paddingOf(context).left : 0),
        bottom: _bottomInset(controlsUp),
        child: PlayerPill(
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Text('上次看到 ${playerClock(c.resumeHintMs ?? 0)}'),
            const SizedBox(width: 10),
            GestureDetector(
              onTap: () {
                c.restartFromBeginning();
                _showToast('从头开始播放');
              },
              child: Text('从头看', style: TextStyle(color: kPlayerAccent, fontWeight: FontWeight.w600)),
            ),
          ]),
        ),
      );

  Widget _toastView(bool controlsUp) => Positioned(
        left: 12 + (fs ? MediaQuery.paddingOf(context).left : 0),
        bottom: _bottomInset(controlsUp) + (c.resumeHintMs != null ? 38 : 0),
        child: IgnorePointer(child: PlayerPill(child: Text(_toast!))),
      );

  // ---------------------------------------------------------------- 右侧面板

  Widget _panelView(Size size) {
    final w = min(320.0, size.width * (fs ? 0.42 : 0.66));
    return Positioned.fill(
      child: Stack(children: [
        Positioned.fill(child: GestureDetector(behavior: HitTestBehavior.opaque, onTap: _closePanel)),
        Positioned(
          top: 0,
          bottom: 0,
          right: 0,
          width: w,
          child: ColoredBox(
            color: Colors.black.withValues(alpha: .86),
            child: SafeArea(left: false, top: fs, bottom: fs, child: _panelBody()),
          ),
        ),
      ]),
    );
  }

  Widget _panelBody() {
    Widget header(String t) => Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 6),
          child: Text(t, style: kPlayerNote.copyWith(color: Colors.white60)),
        );
    Widget option(String label, bool selected, VoidCallback onTap, {String? note}) => InkWell(
          onTap: () {
            _closePanel();
            onTap();
          },
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: Row(children: [
              Expanded(
                child: Text(label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: kPlayerText.copyWith(
                        color: selected ? kPlayerAccent : Colors.white,
                        fontWeight: selected ? FontWeight.w600 : FontWeight.w400)),
              ),
              if (note != null) Text(note, style: kPlayerMicro.copyWith(color: Colors.white60)),
            ]),
          ),
        );
    Widget chip(String label, bool selected, VoidCallback onTap) => InkWell(
          onTap: () {
            _closePanel();
            onTap();
          },
          borderRadius: BorderRadius.circular(kRadiusSm),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(kRadiusSm),
              border: Border.all(color: selected ? kPlayerAccent : Colors.white30),
            ),
            child: Text(label, style: kPlayerNote.copyWith(color: selected ? kPlayerAccent : Colors.white)),
          ),
        );
    final autoQ = pickRendition(c.qualities);
    final parts = c.video.parts;

    switch (_panel) {
      case _Panel.quality:
        return ListView(padding: EdgeInsets.zero, children: [
          header('清晰度'),
          option('自动', c.autoQuality, c.setAutoQuality, note: autoQ == null ? null : qualityShort(autoQ.q)),
          for (final r in c.qualities) option(r.label, !c.autoQuality && c.quality?.q == r.q, () => c.setQuality(r)),
        ]);
      case _Panel.speed:
        return ListView(padding: EdgeInsets.zero, children: [
          header('倍速'),
          for (final s in kPlayerSpeeds.reversed)
            option(s == 1 ? '${speedText(s)} 正常' : speedText(s), (c.speed - s).abs() < 0.001, () => c.setSpeed(s)),
        ]);
      case _Panel.parts:
        return ListView(padding: EdgeInsets.zero, children: [
          header('选集(${parts.length})'),
          for (var i = 0; i < parts.length; i++)
            option('P${i + 1}  ${parts[i].title}', i == c.partIndex, () => c.switchPart(i),
                note: vDuration(parts[i].durationMs)),
        ]);
      case _Panel.more:
        return ListView(padding: const EdgeInsets.only(bottom: 12), children: [
          header('清晰度'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Wrap(spacing: 8, runSpacing: 8, children: [
              chip(autoQ == null ? '自动' : '自动(${qualityShort(autoQ.q)})', c.autoQuality, c.setAutoQuality),
              for (final r in c.qualities)
                chip(qualityShort(r.q), !c.autoQuality && c.quality?.q == r.q, () => c.setQuality(r)),
            ]),
          ),
          header('倍速'),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Wrap(spacing: 8, runSpacing: 8, children: [
              for (final s in kPlayerSpeeds) chip(speedText(s), (c.speed - s).abs() < 0.001, () => c.setSpeed(s)),
            ]),
          ),
          if (parts.length > 1) ...[
            const SizedBox(height: 6),
            option('选集', false, () => _openPanel(_Panel.parts), note: 'P${c.partIndex + 1} / ${parts.length}'),
          ],
          if (c.danmaku.allowDanmaku) option('弹幕设置', false, () => showDanmakuSettings(context, c.danmaku)),
        ]);
      case _Panel.none:
        return const SizedBox.shrink();
    }
  }
}
