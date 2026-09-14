import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:video_player/video_player.dart';

import '../../chat/ui/avatar.dart';
import '../../session.dart';
import '../api.dart';
import '../comments/comments_view.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/feed.dart';
import '../widgets/report.dart';
import '../widgets/share.dart';
import '../widgets/shop_card.dart';

/// 竖屏短视频流(#363,对标抖音):上下滑一条一条看。
///
/// 播放器池子:当前这条播放,前后各预加载一条(建好控制器、只缓冲不播),
/// 离开的暂停,离当前超过一条的释放 —— 任何时候控制器最多 3 个,连续滑 30 条内存也是平的。
class VerticalFeed extends StatefulWidget {
  const VerticalFeed({super.key, required this.active, this.onGoHot});

  /// 竖屏页签是不是正在看(切走了要全部暂停)
  final bool active;

  /// 刷完了之后「去看热门」:切到热门页签
  final VoidCallback? onGoHot;

  @override
  State<VerticalFeed> createState() => _VerticalFeedState();
}

/// 一条的播放状态。
class _Slot {
  _Slot(this.card);

  final VideoCard card;
  VideoDetail? detail;
  VideoPlayerController? ctrl;
  Object? error;
  bool disposed = false;

  /// 这次打开以来实际播了多久(播放心跳要的是这个,不是位置)
  int playedMs = 0;
  Duration _last = Duration.zero;
}

class _VerticalFeedState extends State<VerticalFeed> with WidgetsBindingObserver {
  final List<VideoCard> _items = [];
  final Set<String> _seen = {};
  final Map<int, _Slot> _slots = {};
  final PageController _pc = PageController();
  int _index = 0;
  int _page = 0;
  bool _more = true;
  bool _loading = false;
  Object? _error;
  bool _off = false;
  Timer? _beat;

  /// 这一刷是不是按个人口径排的(看过的会被滤掉,刷完了要这么告诉他)
  bool _personalized = false;

  /// 网页上浏览器不许有声音的自动播放:第一次先静音播,点一下再开声音
  bool _webMuted = kIsWeb;
  bool _clear = false;
  double _speed = 1;

  static String? _deviceId;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadMore();
    _beat = Timer.periodic(const Duration(seconds: 15), (_) => _heartbeat());
    HardwareKeyboard.instance.addHandler(_onHardwareKey);
  }

  @override
  void didUpdateWidget(VerticalFeed old) {
    super.didUpdateWidget(old);
    if (old.active != widget.active) _syncPlayback();
  }

  /// 上面盖了一整页(点进 UP 主空间、搜索、详情)时这一页的 ticker 会被关掉:
  /// 借这个信号暂停,不然视频在别的页面底下接着出声。评论这类半屏弹层不算盖住,照常播
  bool _onstage = true;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // 底部切到别的 tab 时 IndexedStack 只是把这页藏起来(ticker 照开),要另看 Visibility
    final on = TickerMode.valuesOf(context).enabled && Visibility.of(context);
    if (on != _onstage) {
      _onstage = on;
      _syncPlayback();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) {
      for (final s in _slots.values) {
        s.ctrl?.pause();
      }
    } else {
      _syncPlayback();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    HardwareKeyboard.instance.removeHandler(_onHardwareKey);
    _beat?.cancel();
    _wheelQuiet?.cancel();
    _heartbeat();
    for (final s in _slots.values) {
      _release(s);
    }
    _pc.dispose();
    super.dispose();
  }

  Future<void> _loadMore() async {
    if (_loading || !_more) return;
    setState(() => _loading = true);
    try {
      final r = await videoApi.vertical(_page);
      if (!mounted) return;
      setState(() {
        for (final c in r.items) {
          if (_seen.add(c.vid)) _items.add(c);
        }
        _more = r.hasMore && r.items.isNotEmpty;
        _personalized = r.extra['personalized'] == true;
        _page++;
        _error = null;
      });
      _ensureWindow();
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = e;
          _off = VideoApi.isOff(e);
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  /// 当前、前一条、后一条要有控制器;其余的释放。
  void _ensureWindow() {
    final keep = {_index - 1, _index, _index + 1}.where((i) => i >= 0 && i < _items.length).toSet();
    for (final i in _slots.keys.toList()) {
      if (!keep.contains(i)) {
        _release(_slots.remove(i)!);
      }
    }
    for (final i in keep) {
      if (!_slots.containsKey(i)) {
        final s = _Slot(_items[i]);
        _slots[i] = s;
        unawaited(_prepare(i, s));
      }
    }
    _syncPlayback();
    if (_index >= _items.length - 3) _loadMore();
  }

  Future<void> _prepare(int i, _Slot s) async {
    try {
      final d = await videoApi.detail(s.card.vid);
      if (s.disposed) return;
      s.detail = d;
      if (d.parts.isEmpty || d.parts.first.renditions.isEmpty) throw StateError('没有可以播放的清晰度');
      // Windows / Linux 没有播放器实现,不建控制器(建了 initialize 抛、dispose 一直等);
      // 界面上按平台说原因,不说「这条放不出来」
      if (!szCanPlayVideo) throw UnsupportedError(kVideoUnsupportedHint);
      final part = d.parts.first;
      // 竖屏一屏就是手机大小:有 720 用 720,没有取不超过 720 的最高档(省流量)
      final r = [...part.renditions]..sort((a, b) => b.q.compareTo(a.q));
      final pick = r.firstWhere((x) => x.q <= 720, orElse: () => r.last);
      final c = VideoPlayerController.networkUrl(Uri.parse(videoResolve(pick.url)));
      s.ctrl = c;
      await c.initialize();
      if (s.disposed) {
        await c.dispose();
        return;
      }
      await c.setLooping(true);
      await c.setPlaybackSpeed(_speed);
      if (_webMuted) await c.setVolume(0);
      c.addListener(() => _track(s));
      if (mounted) setState(() {});
      _syncPlayback();
    } catch (e) {
      s.error = e;
      if (mounted) setState(() {});
    }
  }

  void _track(_Slot s) {
    final c = s.ctrl;
    if (c == null) return;
    final pos = c.value.position;
    if (c.value.isPlaying) {
      final d = pos - s._last;
      // 循环回到开头时 d 是负的;拖进度条的跳变也不算播放时长
      if (d > Duration.zero && d < const Duration(seconds: 2)) s.playedMs += d.inMilliseconds;
    }
    s._last = pos;
  }

  void _release(_Slot s) {
    s.disposed = true;
    _report(s);
    final c = s.ctrl;
    s.ctrl = null;
    if (c != null) unawaited(c.dispose());
  }

  void _syncPlayback() {
    for (final e in _slots.entries) {
      final c = e.value.ctrl;
      if (c == null || !c.value.isInitialized) continue;
      final shouldPlay = widget.active && _onstage && !_userPaused && e.key == _index;
      if (shouldPlay && !c.value.isPlaying) {
        unawaited(c.play().catchError((Object _) async {
          // 浏览器拦了有声自动播放:静音再播
          _webMuted = true;
          await c.setVolume(0);
          await c.play();
        }));
      } else if (!shouldPlay && c.value.isPlaying) {
        unawaited(c.pause());
      }
    }
  }

  Future<void> _heartbeat() async {
    final s = _slots[_index];
    if (s != null && (s.ctrl?.value.isPlaying ?? false)) await _report(s);
  }

  Future<void> _report(_Slot s) async {
    final d = s.detail;
    final c = s.ctrl;
    if (d == null || c == null || d.parts.isEmpty || s.playedMs <= 0) return;
    try {
      _deviceId ??= await _loadDeviceId();
      await videoApi.view(d.vid,
          partId: d.parts.first.id,
          positionMs: c.value.position.inMilliseconds,
          playedMs: s.playedMs,
          deviceId: rootApi.isLoggedIn ? null : _deviceId);
    } catch (_) {}
  }

  static Future<String> _loadDeviceId() async {
    final sp = await SharedPreferences.getInstance();
    var id = sp.getString('video_device_id');
    if (id == null || id.isEmpty) {
      final r = Random.secure();
      id = List.generate(24, (_) => r.nextInt(16).toRadixString(16)).join();
      await sp.setString('video_device_id', id);
    }
    return id;
  }

  /// 倍速写法:1x、1.25x(不写成 1.0x)
  static String _sx(double x) => x == x.roundToDouble() ? '${x.toInt()}x' : '${x}x';

  void _onPage(int i) {
    setState(() {
      _index = i;
      _userPaused = false;
    });
    _ensureWindow();
  }

  /// 用户自己点的暂停:要记住,不然旁边那条预加载好了一调 _syncPlayback 又给播起来了
  bool _userPaused = false;

  void _togglePlay() {
    final c = _slots[_index]?.ctrl;
    if (c == null || !c.value.isInitialized) return;
    if (_webMuted) unawaited(_unmute());
    _userPaused = c.value.isPlaying;
    unawaited(_userPaused ? c.pause() : c.play());
    setState(() {});
  }

  // 电脑上:滚轮一格翻一条,方向键上下也能翻(和抖音网页版一样)。
  // 触控板一次轻扫会连着来几十个小滚动事件,还带惯性尾巴:
  // 翻过一条就上锁,滚动事件停够 300ms 才解锁,不然一扫翻好几条
  bool _wheelLocked = false;
  double _wheelAcc = 0;
  Timer? _wheelQuiet;

  void _onWheel(double dy) {
    _wheelQuiet?.cancel();
    _wheelQuiet = Timer(const Duration(milliseconds: 300), () {
      _wheelLocked = false;
      _wheelAcc = 0;
    });
    if (_wheelLocked) return;
    _wheelAcc += dy;
    if (_wheelAcc.abs() < 30) return;
    _wheelLocked = true;
    _step(_wheelAcc > 0 ? 1 : -1);
  }

  /// 刷到底了在最后多放一页「刷完了」
  int get _pageCount => _items.length + (_more ? 0 : 1);

  /// 从头再拉一遍(刷完了点「刷新」)
  Future<void> _reload() async {
    for (final s in _slots.values) {
      _release(s);
    }
    _slots.clear();
    setState(() {
      _items.clear();
      _seen.clear();
      _page = 0;
      _more = true;
      _index = 0;
      _userPaused = false;
      _error = null;
    });
    if (_pc.hasClients) _pc.jumpToPage(0);
    await _loadMore();
  }

  void _step(int dir) {
    final to = _index + dir;
    if (to < 0 || to >= _pageCount || !_pc.hasClients) return;
    unawaited(_pc.animateToPage(to, duration: const Duration(milliseconds: 280), curve: Curves.easeOutCubic));
  }

  /// 键盘直接挂在 HardwareKeyboard 上,不靠焦点:点页签、点按钮都会把焦点带走,
  /// 靠焦点的话切进来按方向键常常没反应。上面有弹层(评论、菜单)或正在打字时不接
  bool _onHardwareKey(KeyEvent e) {
    if (!mounted || !widget.active || !_onstage || _items.isEmpty) return false;
    if (!(ModalRoute.of(context)?.isCurrent ?? true)) return false;
    if (FocusManager.instance.primaryFocus?.context?.widget is EditableText) return false;
    return _onKey(e) == KeyEventResult.handled;
  }

  KeyEventResult _onKey(KeyEvent e) {
    if (e is! KeyDownEvent && e is! KeyRepeatEvent) return KeyEventResult.ignored;
    final k = e.logicalKey;
    if (k == LogicalKeyboardKey.arrowDown || k == LogicalKeyboardKey.pageDown) {
      _step(1);
    } else if (k == LogicalKeyboardKey.arrowUp || k == LogicalKeyboardKey.pageUp) {
      _step(-1);
    } else if (k == LogicalKeyboardKey.space && e is KeyDownEvent) {
      _togglePlay();
    } else {
      return KeyEventResult.ignored;
    }
    return KeyEventResult.handled;
  }

  Future<void> _unmute() async {
    if (!_webMuted) return;
    setState(() => _webMuted = false);
    for (final s in _slots.values) {
      await s.ctrl?.setVolume(1);
    }
  }

  // ---------------- 操作 ----------------

  void _toast(String s) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  Future<void> _like(_Slot s, {bool onlyLike = false}) async {
    final d = s.detail;
    if (d == null) return;
    if (!await ensureLoggedIn(context)) return;
    final me = d.me ??= VideoMe();
    if (onlyLike && me.liked) return;
    final want = onlyLike ? true : !me.liked;
    setState(() {
      me.liked = want;
      d.card.likes += want ? 1 : -1;
    });
    try {
      final r = await videoApi.like(d.vid, want);
      if (mounted) {
        setState(() {
          me.liked = r['liked'] == true;
          d.card.likes = vInt(r['likes']);
        });
      }
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _favorite(_Slot s) async {
    final d = s.detail;
    if (d == null) return;
    if (!await ensureLoggedIn(context)) return;
    final me = d.me ??= VideoMe();
    try {
      final r = await videoApi.favorite(d.vid, folderIds: me.favorited ? const [] : null);
      if (mounted) {
        setState(() {
          me.favorited = r['favorited'] == true;
          me.folderIds = [for (final x in vList(r['folder_ids'])) vInt(x)];
          d.card.favorites = vInt(r['favorites']);
        });
        _toast(me.favorited ? '已收藏到默认收藏夹' : '已取消收藏');
      }
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _follow(_Slot s) async {
    final up = s.detail?.uploader;
    if (up == null) return;
    if (!await ensureLoggedIn(context)) return;
    try {
      final r = await videoApi.follow(up.id, true);
      if (mounted) {
        setState(() => s.detail!.card.uploader = up.copyWith(followed: r['followed'] == true, fans: vInt(r['fans'])));
      }
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _comments(_Slot s) async {
    final d = s.detail;
    if (d == null) return;
    await szShowSheet<void>(
      context: context,
      builder: (ctx) => SizedBox(
        height: MediaQuery.of(ctx).size.height * .72,
        child: VideoComments(
          vid: d.vid,
          uploaderId: d.uploader?.id ?? 0,
          allowComments: d.allowComments,
          onCount: (n) {
            if (mounted) setState(() => d.card.commentCount = n);
          },
        ),
      ),
    );
  }

  Future<void> _longPress(_Slot s) async {
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
              leading: const Icon(Icons.not_interested),
              title: const Text('不感兴趣'),
              onTap: () => Navigator.pop(ctx, 'no')),
          ListTile(
              leading: const Icon(Icons.flag_outlined),
              title: const Text('举报'),
              onTap: () => Navigator.pop(ctx, 'report')),
          ListTile(
            leading: const Icon(Icons.speed),
            title: Text('倍速(现在 ${_sx(_speed)})'),
            onTap: () => Navigator.pop(ctx, 'speed'),
          ),
          ListTile(
            leading: Icon(_clear ? Icons.visibility_outlined : Icons.visibility_off_outlined),
            title: Text(_clear ? '显示按钮和文字' : '清屏'),
            onTap: () => Navigator.pop(ctx, 'clear'),
          ),
          // 推荐理由在流里那张卡上(详情接口不带)
          if (s.card.why.isNotEmpty)
            ListTile(
                leading: const Icon(Icons.help_outline),
                title: const Text('为什么推荐给我'),
                onTap: () => Navigator.pop(ctx, 'why')),
        ]),
      ),
    );
    if (pick == null || !mounted) return;
    switch (pick) {
      case 'no':
        if (!await ensureLoggedIn(context)) return;
        try {
          await videoApi.notInterested(s.card.vid);
          _toast('好的,以后少推这类');
          if (_index + 1 < _items.length) {
            await _pc.nextPage(duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
          }
        } on ApiException catch (e) {
          _toast(e.message);
        }
      case 'report':
        if (!await ensureLoggedIn(context)) return;
        if (mounted) await reportTarget(context, targetType: 'video', vid: s.card.vid);
      case 'speed':
        final sp = await szShowSheet<double>(
          context: context,
          builder: (ctx) => SafeArea(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              for (final x in const [0.5, 0.75, 1.0, 1.25, 1.5, 2.0])
                ListTile(
                    title: Text(_sx(x)),
                    trailing: x == _speed ? const Icon(Icons.check) : null,
                    onTap: () => Navigator.pop(ctx, x)),
            ]),
          ),
        );
        if (sp != null) {
          setState(() => _speed = sp);
          for (final x in _slots.values) {
            await x.ctrl?.setPlaybackSpeed(sp);
          }
        }
      case 'clear':
        setState(() => _clear = !_clear);
      case 'why':
        if (mounted) await showWhySheet(context, s.card);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_items.isEmpty) {
      return ColoredBox(
        color: Colors.black,
        child: Center(
          child: _loading
              ? const CircularProgressIndicator(color: Colors.white)
              : Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Text(
                      _off ? '视频功能暂未开放' : (_error != null ? '没加载出来' : (_personalized ? '竖屏视频你都看过了' : '还没有竖屏视频')),
                      style: const TextStyle(color: Colors.white70),
                    ),
                    if (_error == null && !_off && _personalized) ...[
                      const SizedBox(height: 6),
                      const Text('看过一半以上的,7 天内不会再推给你',
                          textAlign: TextAlign.center, style: TextStyle(color: Colors.white38, fontSize: kFontNote)),
                    ],
                    if (!_off) ...[
                      const SizedBox(height: 12),
                      Row(mainAxisSize: MainAxisSize.min, children: [
                        TextButton(onPressed: _reload, child: Text(_error != null ? '重试' : '刷新')),
                        if (widget.onGoHot != null && _error == null)
                          TextButton(onPressed: widget.onGoHot, child: const Text('去看热门')),
                      ]),
                    ],
                  ]),
                ),
        ),
      );
    }
    return ColoredBox(
      color: Colors.black,
      child: PageView.builder(
        controller: _pc,
        scrollDirection: Axis.vertical,
        onPageChanged: _onPage,
        itemCount: _pageCount,
        // 鼠标也能拖着翻(网页默认只认触摸)
        scrollBehavior: ScrollConfiguration.of(context).copyWith(dragDevices: PointerDeviceKind.values.toSet()),
        itemBuilder: (context, i) {
          if (i >= _items.length) {
            return _EndCard(personalized: _personalized, onReload: _reload, onGoHot: widget.onGoHot);
          }
          final s = _slots[i];
          // 滚轮事件在条目这一层先认领:PageView 自己处理滚轮是按像素挪,
          // 挪不到半页就弹回去,看起来就是「滚了没反应」
          return Listener(
            onPointerSignal: (e) {
              if (e is PointerScrollEvent) {
                GestureBinding.instance.pointerSignalResolver
                    .register(e, (ev) => _onWheel((ev as PointerScrollEvent).scrollDelta.dy));
              }
            },
            child: _VerticalItem(
              key: ValueKey(_items[i].vid),
              card: _items[i],
              slot: s,
              clear: _clear,
              webMuted: _webMuted,
              onUnmute: _unmute,
              onTogglePlay: _togglePlay,
              onLike: () => s == null ? null : _like(s),
              onDoubleTapLike: () => s == null ? null : _like(s, onlyLike: true),
              onFavorite: () => s == null ? null : _favorite(s),
              onFollow: () => s == null ? null : _follow(s),
              onComments: () => s == null ? null : _comments(s),
              onShare: () => s?.detail == null ? null : shareVideo(context, s!.detail!.card),
              onLongPress: () => s == null ? null : _longPress(s),
              onOpenSpace: () {
                final up = s?.detail?.uploader ?? _items[i].uploader;
                if (up != null) openUpSpace(context, up.id);
              },
            ),
          );
        },
      ),
    );
  }
}

/// 竖屏里的一条:画面、右侧栏、底部信息、进度条、手势。
class _VerticalItem extends StatefulWidget {
  const _VerticalItem({
    super.key,
    required this.card,
    required this.slot,
    required this.clear,
    required this.webMuted,
    required this.onUnmute,
    required this.onTogglePlay,
    required this.onLike,
    required this.onDoubleTapLike,
    required this.onFavorite,
    required this.onFollow,
    required this.onComments,
    required this.onShare,
    required this.onLongPress,
    required this.onOpenSpace,
  });

  final VideoCard card;
  final _Slot? slot;
  final bool clear;
  final bool webMuted;
  final VoidCallback onUnmute;
  final VoidCallback onTogglePlay;
  final VoidCallback onLike;
  final VoidCallback onDoubleTapLike;
  final VoidCallback onFavorite;
  final VoidCallback onFollow;
  final VoidCallback onComments;
  final VoidCallback onShare;
  final VoidCallback onLongPress;
  final VoidCallback onOpenSpace;

  @override
  State<_VerticalItem> createState() => _VerticalItemState();
}

class _VerticalItemState extends State<_VerticalItem> with TickerProviderStateMixin {
  final List<({Offset at, AnimationController anim})> _hearts = [];
  bool _dragging = false;
  double _dragValue = 0;
  VideoPlayerController? _listened;

  @override
  void didUpdateWidget(_VerticalItem old) {
    super.didUpdateWidget(old);
    _listen();
  }

  @override
  void initState() {
    super.initState();
    _listen();
  }

  void _listen() {
    final c = widget.slot?.ctrl;
    if (c == _listened) return;
    _listened?.removeListener(_onTick);
    _listened = c;
    c?.addListener(_onTick);
  }

  void _onTick() {
    if (mounted && !_dragging) setState(() {});
  }

  @override
  void dispose() {
    _listened?.removeListener(_onTick);
    for (final h in _hearts) {
      h.anim.dispose();
    }
    super.dispose();
  }

  void _heart(Offset at) {
    // 系统关了动态效果:不飘心,直接给终态(右侧栏的心变成 clay)
    if (SzMotion.off(context)) {
      HapticFeedback.lightImpact();
      widget.onDoubleTapLike();
      return;
    }
    final a = AnimationController(vsync: this, duration: const Duration(milliseconds: 700));
    final entry = (at: at, anim: a);
    setState(() => _hearts.add(entry));
    a.forward().whenComplete(() {
      if (!mounted) return;
      setState(() => _hearts.remove(entry));
      a.dispose();
    });
    HapticFeedback.lightImpact();
    widget.onDoubleTapLike();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.slot;
    final c = s?.ctrl;
    final d = s?.detail;
    final card = d?.card ?? widget.card;
    final ready = c != null && c.value.isInitialized;
    final paused = ready && !c.value.isPlaying;
    final dur = ready ? c.value.duration : Duration(milliseconds: card.durationMs);
    final pos = ready ? c.value.position : Duration.zero;
    final progress = dur.inMilliseconds > 0 ? (pos.inMilliseconds / dur.inMilliseconds).clamp(0.0, 1.0) : 0.0;
    final up = d?.uploader ?? card.uploader;
    // 点赞原来是抖音的粉红、收藏是亮金 —— 换成 clay 和 hold,黑底上照样跳得出来,和全站一个调(设计稿 F)
    final sz = Theme.of(context).sz;
    final shade = [Shadow(offset: const Offset(0, 1), blurRadius: 4, color: Colors.black.withValues(alpha: .6))];
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: widget.onTogglePlay,
      onDoubleTapDown: (e) => _heart(e.localPosition),
      onDoubleTap: () {},
      onLongPress: widget.onLongPress,
      // 左滑进 UP 主空间(和抖音一样)
      onHorizontalDragEnd: (e) {
        if ((e.primaryVelocity ?? 0) < -400) widget.onOpenSpace();
      },
      child: Stack(fit: StackFit.expand, children: [
        if (ready)
          Center(
            // 网页上播放器是一个 <video> 平台视图,它的手势识别器会进竞技场而且从不认输,
            // 单击的判定一拖到竞技场清场就被它赢走(双击不受影响)—— 画面本身不接指针
            child: IgnorePointer(child: AspectRatio(aspectRatio: c.value.aspectRatio, child: VideoPlayer(c))),
          )
        else if (card.cover.isNotEmpty)
          Image(image: szNetImage(videoResolve(card.cover)), fit: BoxFit.contain),
        if (!ready && s?.error == null) const Center(child: CircularProgressIndicator(color: Colors.white54)),
        if (s?.error != null)
          Center(
              child: Text(szCanPlayVideo ? '这条放不出来,往下滑看下一条' : kVideoUnsupportedHint,
                  style: const TextStyle(color: Colors.white70))),
        if (paused) const Center(child: Icon(Icons.play_arrow_rounded, size: 84, color: Colors.white70)),
        if (widget.webMuted && ready)
          Positioned(
            top: 14,
            left: 14,
            child: GestureDetector(
              onTap: widget.onUnmute,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 5),
                decoration: BoxDecoration(color: Colors.black45, borderRadius: BorderRadius.circular(16)),
                child: const Row(mainAxisSize: MainAxisSize.min, children: [
                  Icon(Icons.volume_off_outlined, color: Colors.white, size: 15),
                  SizedBox(width: 5),
                  Text('点一下开声音', style: TextStyle(color: Colors.white, fontSize: kFontNote)),
                ]),
              ),
            ),
          ),
        for (final h in _hearts)
          AnimatedBuilder(
            animation: h.anim,
            builder: (_, __) {
              final t = h.anim.value;
              return Positioned(
                left: h.at.dx - 40,
                top: h.at.dy - 40 - 60 * t,
                child: Opacity(
                  opacity: (1 - t).clamp(0.0, 1.0),
                  child: Transform.scale(
                      scale: .8 + .6 * Curves.easeOut.transform(t),
                      child: Icon(Icons.favorite, color: sz.clay, size: 80)),
                ),
              );
            },
          ),
        if (!widget.clear) ...[
          // 右侧栏:头像(没关注时底下一个 clay 小加号)/ 赞 / 评论 / 收藏 / 分享
          Positioned(
            right: 10,
            bottom: 96,
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              GestureDetector(
                onTap: widget.onOpenSpace,
                child: Stack(clipBehavior: Clip.none, alignment: Alignment.bottomCenter, children: [
                  Container(
                    decoration:
                        BoxDecoration(shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 1.5)),
                    child: ChatAvatar(name: up?.name ?? '', url: up?.avatar ?? '', size: 46),
                  ),
                  if (up != null && !up.followed && rootApi.userId != up.id)
                    Positioned(
                      bottom: -9,
                      child: GestureDetector(
                        onTap: widget.onFollow,
                        child: CircleAvatar(
                            radius: 10,
                            backgroundColor: sz.clay,
                            child: const Icon(Icons.add, size: 14, color: Colors.white)),
                      ),
                    ),
                ]),
              ),
              const SizedBox(height: 20),
              _RailButton(
                icon: Icons.favorite,
                color: (d?.me?.liked ?? false) ? sz.clay : Colors.white,
                label: vCount(card.likes),
                semantic: '点赞',
                onTap: widget.onLike,
              ),
              _RailButton(
                  icon: Icons.chat_bubble_outline,
                  label: vCount(card.commentCount),
                  semantic: '评论',
                  onTap: widget.onComments),
              _RailButton(
                icon: (d?.me?.favorited ?? false) ? Icons.star : Icons.star_border,
                color: (d?.me?.favorited ?? false) ? sz.hold : Colors.white,
                label: vCount(card.favorites),
                semantic: '收藏',
                onTap: widget.onFavorite,
              ),
              _RailButton(
                  icon: Icons.reply, flip: true, label: vCount(card.shares), semantic: '分享', onTap: widget.onShare),
            ]),
          ),
          // 底部:@UP 主、标题、话题;挂了店的再加一行店名(有合作标「合作」,D16)
          Positioned(
            left: 14,
            right: 84,
            bottom: 30,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              GestureDetector(
                onTap: widget.onOpenSpace,
                child: Text('@${up?.name ?? ''}',
                    style: TextStyle(
                        color: Colors.white, fontWeight: FontWeight.w600, fontSize: kFontTitle, shadows: shade)),
              ),
              const SizedBox(height: 6),
              Text(card.title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: Colors.white, fontSize: kFontBodyLg, height: 1.45, shadows: shade)),
              if (card.tags.isNotEmpty) ...[
                const SizedBox(height: 6),
                Wrap(spacing: 10, children: [
                  for (final t in card.tags.take(4))
                    GestureDetector(
                      onTap: () =>
                          Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => _TagSearch(tag: t))),
                      child: Text('#$t',
                          style: TextStyle(
                              color: Colors.white, fontSize: kFontBodyLg, fontWeight: FontWeight.w600, shadows: shade)),
                    ),
                ]),
              ],
              if (d?.shop != null) ...[
                const SizedBox(height: 8),
                VideoShopChip(shop: d!.shop!, collab: d.shopCollab == true || card.collab),
              ],
            ]),
          ),
        ],
        // 进度条:平时一条细线,拖的时候变粗并显示时间
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onHorizontalDragStart: (e) => setState(() {
              _dragging = true;
              _dragValue = progress;
            }),
            onHorizontalDragUpdate: (e) {
              final w = context.size?.width ?? 1;
              setState(() => _dragValue = (_dragValue + e.delta.dx / w).clamp(0.0, 1.0));
            },
            onHorizontalDragEnd: (_) {
              if (ready) c.seekTo(Duration(milliseconds: (dur.inMilliseconds * _dragValue).round()));
              setState(() => _dragging = false);
            },
            child: SizedBox(
              height: 22,
              child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                if (_dragging)
                  Text('${vDuration((dur.inMilliseconds * _dragValue).round())} / ${vDuration(dur.inMilliseconds)}',
                      style: szTabular(
                          color: Colors.white,
                          fontSize: kFontTitle,
                          fontWeight: FontWeight.w600,
                          shadows: const [Shadow(blurRadius: 6)])),
                LinearProgressIndicator(
                  value: _dragging ? _dragValue : progress,
                  minHeight: _dragging ? 6 : 2.5,
                  backgroundColor: Colors.white.withValues(alpha: .22),
                  color: Colors.white,
                ),
              ]),
            ),
          ),
        ),
      ]),
    );
  }
}

class _RailButton extends StatelessWidget {
  const _RailButton(
      {required this.icon,
      required this.label,
      required this.onTap,
      required this.semantic,
      this.color = Colors.white,
      this.flip = false});

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final String semantic;
  final Color color;
  final bool flip;

  @override
  Widget build(BuildContext context) {
    // 线图标 30,下面一行等宽数字(设计稿 F);黑白两种画面上都靠一层阴影托着
    Widget i = Icon(icon, color: color, size: 30, shadows: const [Shadow(blurRadius: 6)]);
    if (flip) i = Transform.flip(flipX: true, child: i);
    return Semantics(
      button: true,
      label: semantic,
      child: InkResponse(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 7),
          child: Column(children: [
            i,
            const SizedBox(height: 3),
            Text(label,
                style: szTabular(color: Colors.white, fontSize: kFontNote, shadows: const [Shadow(blurRadius: 4)])),
          ]),
        ),
      ),
    );
  }
}

/// 点话题:搜这个标签
class _TagSearch extends StatelessWidget {
  const _TagSearch({required this.tag});

  final String tag;

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: Text('#$tag')),
      body: VideoFeed(load: (page, _) => videoApi.search(tag, page: page), emptyText: '没有带这个标签的视频'),
    );
  }
}

/// 刷到底:说清楚为什么没了,给两个出口。
class _EndCard extends StatelessWidget {
  const _EndCard({required this.personalized, required this.onReload, this.onGoHot});

  final bool personalized;
  final VoidCallback onReload;
  final VoidCallback? onGoHot;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.check_circle_outline, color: Colors.white54, size: 44),
          const SizedBox(height: 12),
          const Text('竖屏视频暂时刷完了', style: TextStyle(color: Colors.white, fontSize: kFontTitle)),
          if (personalized) ...[
            const SizedBox(height: 6),
            const Text('看过一半以上的,7 天内不会再推给你',
                textAlign: TextAlign.center, style: TextStyle(color: Colors.white54, fontSize: kFontNote)),
          ],
          const SizedBox(height: 16),
          Row(mainAxisSize: MainAxisSize.min, children: [
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.white, side: const BorderSide(color: Colors.white38)),
              onPressed: onReload,
              child: const Text('刷新'),
            ),
            if (onGoHot != null) ...[
              const SizedBox(width: 12),
              FilledButton(onPressed: onGoHot, child: const Text('去看热门')),
            ],
          ]),
        ]),
      ),
    );
  }
}
