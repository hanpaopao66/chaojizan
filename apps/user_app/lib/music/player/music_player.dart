// 全 App 一个播放器(DEV-PROMPTS-41 §9):队列、播放模式、音质、进度、定时关闭、
// 收听上报、播放地址过期自动重签。迷你条、播放页、各个列表页都看着这一个对象。
//
// ## 为什么音频后端要抽成接口
//
// `audioplayers` 是平台通道:widget 测试里没有那条通道,构造一个 AudioPlayer 就开始等回应。
// 于是「队列走到底怎么办」「随机放会不会重复」「拖了进度条收听时长该不该涨」这些
// **纯逻辑**的事,只要播放器直接 new 了 AudioPlayer 就一条也写不了断言。
// 抽一层之后:线上是 [AudioPlayersBackend],测试是假的,逻辑一字不改。
import 'dart:async';
import 'dart:math';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../api.dart';
import '../models.dart';
import '../nav.dart';

/// 播放模式(§2.1:列表循环 / 单曲循环 / 随机)。
enum MusicMode {
  listLoop,
  single,
  shuffle;

  String get label => switch (this) {
        MusicMode.listLoop => '列表循环',
        MusicMode.single => '单曲循环',
        MusicMode.shuffle => '随机播放',
      };
}

/// 音频后端:播放器只认这几件事。
abstract class MusicAudioBackend {
  Stream<Duration> get onPosition;
  Stream<Duration> get onDuration;
  Stream<void> get onComplete;

  /// 播放器自己报的错(播到一半断网、地址过期被挡)
  Stream<Object> get onError;

  /// 从头播这个地址。放不了就抛 —— 调用方据此重签地址再试一次。
  Future<void> play(String url);
  Future<void> pause();
  Future<void> resume();
  Future<void> stop();
  Future<void> seek(Duration to);
  Future<void> dispose();
}

/// 线上的后端:audioplayers。
///
/// [AudioContextConfig.stayAwake] 开着 —— 安卓拿 `PARTIAL_WAKE_LOCK`(清单里的 WAKE_LOCK),
/// iOS 走 `AVAudioSessionCategory.playback`(Info.plist 的 `UIBackgroundModes: audio`),
/// 锁屏之后声音接着走。**这一批不做锁屏控制条**(§4 M9):那要安卓前台服务和通知,
/// 五端构建风险大,留给下一批。
class AudioPlayersBackend implements MusicAudioBackend {
  AudioPlayersBackend() {
    unawaited(_init());
  }

  final AudioPlayer _player = AudioPlayer();
  final StreamController<Object> _errors = StreamController<Object>.broadcast();

  Future<void> _init() async {
    try {
      await _player.setReleaseMode(ReleaseMode.stop);
      // 后台可播:这一句不设的话,锁屏或切后台时安卓直接把声音掐了
      await _player.setAudioContext(AudioContextConfig(stayAwake: true).build());
    } catch (_) {
      // 设不上就按平台缺省播:锁屏会停,但不该因此连歌都放不了
    }
    // 平台那边的故障(地址被挡、解码失败)是以**流错误**的形式过来的,
    // 不是一个事件 —— 只 listen 数据不接 onError 的话,它会变成未捕获异常
    _player.eventStream.listen((_) {}, onError: (Object e) {
      if (!_errors.isClosed) _errors.add(e);
    });
  }

  @override
  Stream<Duration> get onPosition => _player.onPositionChanged;

  @override
  Stream<Duration> get onDuration => _player.onDurationChanged;

  @override
  Stream<void> get onComplete => _player.onPlayerComplete;

  @override
  Stream<Object> get onError => _errors.stream;

  @override
  Future<void> play(String url) => _player.play(UrlSource(url));

  @override
  Future<void> pause() => _player.pause();

  @override
  Future<void> resume() => _player.resume();

  @override
  Future<void> stop() => _player.stop();

  @override
  Future<void> seek(Duration to) => _player.seek(to);

  @override
  Future<void> dispose() async {
    await _errors.close();
    await _player.dispose();
  }
}

/// 播放器。`AnimatedBuilder(animation: MusicPlayer.instance)` 看状态。
class MusicPlayer extends ChangeNotifier {
  MusicPlayer({MusicAudioBackend? backend, MusicApi? api})
      : _injected = backend,
        _api = api;

  /// 全 App 一个。后端是**用到时才建**的 —— 只是引用一下这个单例
  /// (比如挂迷你条)不该去碰平台通道。
  static final MusicPlayer instance = MusicPlayer();

  final MusicAudioBackend? _injected;
  final MusicApi? _api;

  late final MusicAudioBackend _be = _injected ?? AudioPlayersBackend();
  MusicApi get _music => _api ?? musicApi;

  /// 进度跳动超过这么多毫秒就不算「听过」:那是拖动或缓冲跳,不是真听了(§5.5)。
  /// audioplayers 大约 200 毫秒报一次位置,2 秒的余量足够盖住卡顿。
  static const int _maxTickMs = 2000;

  // ---------------- 状态 ----------------

  /// 当前队列。同一首歌只在队列里出现一次
  final List<MTrack> queue = [];
  int index = -1;
  MusicMode mode = MusicMode.listLoop;
  bool playing = false;

  /// 正在取地址 / 缓冲
  bool buffering = false;
  Duration position = Duration.zero;
  Duration duration = Duration.zero;

  /// 音质:标准 / 高品质(§4 M4),记在本机
  String quality = kQualityStd;

  /// 这一队是从哪进来的(`playlist:mp…`、`chart:hot`、`daily`),收听上报原样带给服务端
  String playContextKey = '';

  /// 这首放不了时的那句话(整页不用报错,迷你条上提一下就行)
  String? notice;

  /// 有话要说时喊一声(App 外壳接上去弹 SnackBar)。播放器不持有 BuildContext。
  void Function(String message)? onNotice;

  MTrack? get current => index >= 0 && index < queue.length ? queue[index] : null;
  bool get hasTrack => current != null;

  /// 拖动条的比例;还不知道时长时按 0 算
  double get progress {
    final d = duration.inMilliseconds;
    if (d <= 0) return 0;
    return (position.inMilliseconds / d).clamp(0.0, 1.0);
  }

  // ---------------- 定时关闭 ----------------

  /// 到点自动停(15 / 30 / 60 分钟)。没设是 null
  DateTime? sleepUntil;

  /// 「播完这首再停」
  bool sleepAfterTrack = false;
  Timer? _sleepTimer;

  Duration? get sleepRemaining {
    final t = sleepUntil;
    if (t == null) return null;
    final left = t.difference(DateTime.now());
    return left.isNegative ? Duration.zero : left;
  }

  // ---------------- 收听上报 ----------------

  /// 这首**实际听了**多少毫秒。拖过去的那一段不算(§5.5 的门槛按实听算)
  int _listenedMs = 0;
  int _lastPosMs = 0;
  String? _reportingTid;

  @visibleForTesting
  int get listenedMs => _listenedMs;

  String _deviceId = '';

  // ---------------- 随机顺序 ----------------

  /// 随机模式下这一轮的顺序(队列下标的一个排列)。**走完一轮才重洗**,
  /// 不是每次随机取一首 —— 那样会出现连着两次放同一首。
  final List<int> _order = [];
  int _orderPos = 0;

  bool _wired = false;
  Future<void>? _loading;

  /// 连着放不了几首了。整队都放不了时别无限往下跳
  int _failures = 0;

  // ---------------- 本机设置 ----------------

  /// 读出音质、播放模式和设备号。播之前会自己调一次,外壳也可以在启动时先调。
  Future<void> load() => _loading ??= _doLoad();

  Future<void> _doLoad() async {
    try {
      final sp = await SharedPreferences.getInstance();
      final q = sp.getString('music_quality');
      if (q == kQualityHq || q == kQualityStd) quality = q!;
      final m = sp.getString('music_mode');
      mode = MusicMode.values.firstWhere((e) => e.name == m, orElse: () => MusicMode.listLoop);
      var id = sp.getString('music_device_id') ?? '';
      if (id.isEmpty) {
        // 没登录的人按设备去重收听(§5.4)。只是个随机串,不含任何设备信息
        final r = Random();
        id = List.generate(16, (_) => '0123456789abcdef'[r.nextInt(16)]).join();
        await sp.setString('music_device_id', id);
      }
      _deviceId = id;
    } catch (_) {
      // 读不出来就用缺省值,不能因为本机设置读不到就放不了歌
    }
    notifyListeners();
  }

  Future<void> _save(String key, String value) async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setString(key, value);
    } catch (_) {}
  }

  /// 换音质。正在放的歌要重开流,播起来跳回原来的进度。
  Future<void> setQuality(String q) async {
    if (q != kQualityStd && q != kQualityHq) return;
    if (q == quality) return;
    quality = q;
    notifyListeners();
    await _save('music_quality', q);
    if (current != null && playing) {
      await _start(at: position, keepListen: true);
    }
  }

  Future<void> setMode(MusicMode m) async {
    if (m == mode) return;
    mode = m;
    if (m == MusicMode.shuffle) _reshuffle();
    notifyListeners();
    await _save('music_mode', m.name);
  }

  /// 三种模式轮着来
  Future<void> cycleMode() =>
      setMode(MusicMode.values[(MusicMode.values.indexOf(mode) + 1) % MusicMode.values.length]);

  // ---------------- 播 ----------------

  /// 按上下文播一队歌。[start] 是先播第几首,[contextKey] 原样报给服务端。
  Future<void> playContext(List<MTrack> tracks, {int start = 0, String contextKey = ''}) async {
    final list = _dedup(tracks);
    if (list.isEmpty) return;
    await load();
    await _flushListen();
    queue
      ..clear()
      ..addAll(list);
    playContextKey = contextKey;
    index = start.clamp(0, queue.length - 1);
    _failures = 0;
    _reshuffle();
    await _start();
  }

  /// 单独播一首(详情页的大播放键)。已经在队列里就跳过去,不在就插到下一首再跳。
  Future<void> playTrack(MTrack t, {String contextKey = ''}) async {
    final at = queue.indexWhere((x) => x.tid == t.tid);
    if (at >= 0) {
      await playAt(at);
      return;
    }
    if (queue.isEmpty) {
      await playContext([t], contextKey: contextKey);
      return;
    }
    await load();
    await _flushListen();
    queue.insert(index + 1, t);
    index = index + 1;
    if (contextKey.isNotEmpty) playContextKey = contextKey;
    _failures = 0;
    _reshuffle();
    await _start();
  }

  /// 跳到队列里的第 [i] 首
  Future<void> playAt(int i) async {
    if (i < 0 || i >= queue.length) return;
    await load();
    await _flushListen();
    index = i;
    _failures = 0;
    _syncOrderToIndex();
    await _start();
  }

  /// 插到下一首。已经在队列里的就挪过来,不会出现两条一样的。
  void insertNext(MTrack t) {
    if (queue.isEmpty) {
      queue.add(t);
      index = 0;
      _reshuffle();
      notifyListeners();
      return;
    }
    final at = queue.indexWhere((x) => x.tid == t.tid);
    if (at == index) return;
    if (at >= 0) {
      queue.removeAt(at);
      if (at < index) index--;
    }
    queue.insert(index + 1, t);
    _reshuffle();
    notifyListeners();
  }

  /// 加到队尾
  void addToQueue(Iterable<MTrack> tracks) {
    final have = {for (final t in queue) t.tid};
    var added = 0;
    for (final t in tracks) {
      if (have.add(t.tid)) {
        queue.add(t);
        added++;
      }
    }
    if (added == 0) return;
    if (index < 0) index = 0;
    _reshuffle();
    notifyListeners();
  }

  /// 从队列里移掉一首。移的正好是在放的那首时,顶上来的那首接着放。
  Future<void> removeAt(int i) async {
    if (i < 0 || i >= queue.length) return;
    if (i != index) {
      queue.removeAt(i);
      if (i < index) index--;
      _reshuffle();
      notifyListeners();
      return;
    }
    await _flushListen();
    queue.removeAt(i);
    if (queue.isEmpty) {
      index = -1;
      _order.clear();
      await _hardStop();
      return;
    }
    index = i >= queue.length ? 0 : i;
    _failures = 0;
    _reshuffle();
    await _start();
  }

  /// 拖着换队列里的顺序。正在放的那首跟着它自己走 —— 把它拖到别处不该换歌。
  ///
  /// [to] 是**拔掉之后**的落点(`onReorderItem` 给的就是这个),不用再自己减一。
  void reorder(int from, int to) {
    if (from < 0 || from >= queue.length) return;
    final at = to;
    if (at < 0 || at >= queue.length || at == from) return;
    final t = queue.removeAt(from);
    queue.insert(at, t);
    if (index == from) {
      index = at;
    } else if (from < index && at >= index) {
      index--;
    } else if (from > index && at <= index) {
      index++;
    }
    _reshuffle();
    notifyListeners();
  }

  Future<void> clearQueue() async {
    await _flushListen();
    queue.clear();
    index = -1;
    _order.clear();
    playContextKey = '';
    await _hardStop();
  }

  /// 播 / 暂停
  Future<void> toggle() async {
    if (current == null) return;
    if (playing) {
      playing = false;
      notifyListeners();
      await _be.pause();
    } else {
      playing = true;
      notifyListeners();
      await _be.resume();
    }
  }

  Future<void> pause() async {
    if (!playing) return;
    playing = false;
    notifyListeners();
    await _be.pause();
  }

  /// 下一首。[auto] = 播完 / 放不了自动切;false = 用户按的。
  ///
  /// 单曲循环和「播完这首再停」只管**自动切**:用户按了「下一首」还不动,
  /// 那是按钮坏了。
  Future<void> next({bool auto = false}) async {
    if (queue.isEmpty) return;
    await _flushListen();
    if (auto && sleepAfterTrack) {
      sleepAfterTrack = false;
      await _hardStop();
      _notice('已按设置停下');
      return;
    }
    if (auto && mode == MusicMode.single) {
      await _start();
      return;
    }
    index = _stepIndex(1);
    await _start();
  }

  Future<void> prev() async {
    if (queue.isEmpty) return;
    await _flushListen();
    index = _stepIndex(-1);
    _failures = 0;
    await _start();
  }

  Future<void> seekTo(Duration to) async {
    final d = duration.inMilliseconds;
    final ms = d > 0 ? to.inMilliseconds.clamp(0, d) : max(0, to.inMilliseconds);
    // 先把「上一次的位置」挪到目标上:跳过去的那一段不能算听过(§5.5)
    _lastPosMs = ms;
    position = Duration(milliseconds: ms);
    notifyListeners();
    await _be.seek(position);
  }

  // ---------------- 定时关闭 ----------------

  void setSleepTimer(Duration? d) {
    _sleepTimer?.cancel();
    _sleepTimer = null;
    sleepAfterTrack = false;
    if (d == null) {
      sleepUntil = null;
      notifyListeners();
      return;
    }
    sleepUntil = DateTime.now().add(d);
    _sleepTimer = Timer(d, () {
      sleepUntil = null;
      unawaited(_hardStop());
      _notice('已按设置停下');
    });
    notifyListeners();
  }

  void setSleepAfterTrack(bool on) {
    _sleepTimer?.cancel();
    _sleepTimer = null;
    sleepUntil = null;
    sleepAfterTrack = on;
    notifyListeners();
  }

  // ---------------- 内部 ----------------

  static List<MTrack> _dedup(Iterable<MTrack> tracks) {
    final seen = <String>{};
    return [
      for (final t in tracks)
        if (t.tid.isNotEmpty && seen.add(t.tid)) t,
    ];
  }

  void _notice(String message) {
    notice = message;
    notifyListeners();
    onNotice?.call(message);
  }

  void _wire() {
    if (_wired) return;
    _wired = true;
    _be.onPosition.listen((p) {
      final ms = p.inMilliseconds;
      final delta = ms - _lastPosMs;
      // 只有「正常往前走的一小步」才算听过:拖动、缓冲跳、重头开始都不算
      if (playing && delta > 0 && delta <= _maxTickMs) _listenedMs += delta;
      _lastPosMs = ms;
      position = p;
      notifyListeners();
    });
    _be.onDuration.listen((d) {
      if (d > Duration.zero) {
        duration = d;
        notifyListeners();
      }
    });
    _be.onComplete.listen((_) {
      // 播完那一下位置事件可能没报满,按时长补齐,不然最后几百毫秒白听了
      final d = duration.inMilliseconds;
      if (d > 0 && _lastPosMs < d) {
        final rest = d - _lastPosMs;
        if (rest <= _maxTickMs) _listenedMs += rest;
        _lastPosMs = d;
      }
      playing = false;
      unawaited(next(auto: true));
    });
    _be.onError.listen((e) => unawaited(_recover(e)));
  }

  /// 取播放地址。快过期了先重签(§5.5:签 6 小时)。
  Future<String> _urlFor(MTrack t) async {
    var s = t.stream;
    if (s == null || s.isEmpty || s.expiredBy(DateTime.now())) {
      s = await _music.stream(t.tid);
      t.stream = s;
    }
    return s.urlFor(quality);
  }

  /// 开播当前这首。[at] 给了就播起来跳过去(换音质);[keepListen] 为真时
  /// 不重置收听计数(还是同一首,只是换了一档码率)。
  Future<void> _start({Duration? at, bool keepListen = false}) async {
    final t = current;
    if (t == null) return;
    _wire();
    notice = null;
    buffering = true;
    if (!keepListen) {
      _listenedMs = 0;
      _reportingTid = t.tid;
      duration = Duration(milliseconds: t.durationMs);
      position = Duration.zero;
    }
    _lastPosMs = at?.inMilliseconds ?? 0;
    if (at != null) position = at;
    // 先把「在放」立起来:后端第一批位置事件可能在 play() 返回之前就到了,
    // 那时候标记还是假的话,开头这一两秒就白听了(收听门槛按实听算)
    playing = true;
    notifyListeners();

    try {
      await _be.play(await _urlFor(t));
    } catch (_) {
      // 地址过期或被挡(403 / 404):重签一次再试 —— 手机睡了一夜再点播放就是这个情形
      try {
        t.stream = await _music.stream(t.tid);
        await _be.play(t.stream!.urlFor(quality));
      } catch (e2) {
        await _skipBroken(t, e2);
        return;
      }
    }
    if (at != null && at > Duration.zero) {
      try {
        await _be.seek(at);
      } catch (_) {}
    }
    playing = true;
    buffering = false;
    _failures = 0;
    notifyListeners();
  }

  /// 播到一半出错:重签一次接着播(位置保留),还不行就跳下一首。
  Future<void> _recover(Object e) async {
    final t = current;
    if (t == null || !playing) return;
    final at = position;
    try {
      t.stream = await _music.stream(t.tid);
      await _be.play(t.stream!.urlFor(quality));
      if (at > Duration.zero) await _be.seek(at);
      _lastPosMs = at.inMilliseconds;
      playing = true;
      notifyListeners();
    } catch (e2) {
      await _skipBroken(t, e2);
    }
  }

  /// 这首真放不了:说一句,跳下一首。整队都放不了时停下,别原地打转。
  Future<void> _skipBroken(MTrack t, Object e) async {
    playing = false;
    buffering = false;
    _failures++;
    notifyListeners();
    if (queue.length <= 1 || _failures >= queue.length) {
      _failures = 0;
      await _hardStop();
      _notice('「${t.title}」暂时放不了');
      return;
    }
    _notice('「${t.title}」暂时放不了,已跳到下一首');
    index = _stepIndex(1);
    await _start();
  }

  Future<void> _hardStop() async {
    playing = false;
    buffering = false;
    position = Duration.zero;
    notifyListeners();
    if (!_wired) return;
    try {
      await _be.stop();
    } catch (_) {}
  }

  /// 把这首实际听了多久报上去(§5.5:切歌或播完时报)。报不上去不影响听歌。
  Future<void> _flushListen() async {
    final tid = _reportingTid;
    final ms = _listenedMs;
    _reportingTid = null;
    _listenedMs = 0;
    _lastPosMs = 0;
    if (tid == null || ms <= 0) return;
    try {
      await _music.reportPlay(tid, msListened: ms, deviceId: _deviceId, context: playContextKey);
    } catch (_) {}
  }

  /// 往前 / 往后一首的下标。随机模式走这一轮洗好的顺序,走完一轮重洗。
  int _stepIndex(int step) {
    if (queue.length <= 1) return 0;
    if (mode != MusicMode.shuffle) {
      return (index + step + queue.length) % queue.length;
    }
    if (_order.length != queue.length) _reshuffle();
    if (step > 0) {
      _orderPos++;
      if (_orderPos >= _order.length) {
        // 一轮放完了才重洗:每次现摇一个下标的话,连着两次摇到同一首就等于卡带
        _reshuffle(keepCurrentFirst: false);
        _orderPos = 0;
      }
    } else {
      _orderPos = _orderPos > 0 ? _orderPos - 1 : _order.length - 1;
    }
    return _order[_orderPos];
  }

  /// 重洗顺序。[keepCurrentFirst] 时把正在放的那首排到头一位,
  /// 这样「下一首」不会又是它(队列刚变过、刚切到随机模式都走这一支)。
  void _reshuffle({bool keepCurrentFirst = true}) {
    _order
      ..clear()
      ..addAll(List.generate(queue.length, (i) => i));
    _order.shuffle(_random);
    _orderPos = 0;
    if (!keepCurrentFirst || index < 0 || index >= queue.length) return;
    final at = _order.indexOf(index);
    if (at > 0) {
      _order
        ..removeAt(at)
        ..insert(0, index);
    }
  }

  /// 用户直接点了队列里的某一首:把随机顺序的游标挪到它身上,
  /// 不然下一首会从「上一次随机走到的地方」接着走,看着像乱跳。
  void _syncOrderToIndex() {
    if (mode != MusicMode.shuffle) return;
    if (_order.length != queue.length) {
      _reshuffle();
      return;
    }
    final at = _order.indexOf(index);
    if (at >= 0) _orderPos = at;
  }

  final Random _random = Random();

  @visibleForTesting
  List<int> get shuffleOrder => List.unmodifiable(_order);

  @override
  void dispose() {
    _sleepTimer?.cancel();
    if (_wired) unawaited(_be.dispose());
    super.dispose();
  }
}
