import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart' show kVideoUnsupportedHint, szCanPlayVideo;
import 'package:video_player/video_player.dart';

import '../api.dart';
import '../danmaku/danmaku_controller.dart';
import '../models.dart';
import '../nav.dart';
import 'player_logic.dart';

/// 造底层播放器。缺省是 `VideoPlayerController.networkUrl`;单测里换成假的(不碰平台通道)。
typedef SzPlayerFactory = VideoPlayerController Function(Uri url);

/// 没登录时播放心跳要带的设备号:第一次用时生成一个随机串存进 SharedPreferences,之后一直用它。
/// 服务端只拿它给「每人每天算一次播放」去重(哈希后存),不关联任何身份。
Future<String> videoDeviceId() => _deviceId ??= () async {
      final p = await SharedPreferences.getInstance();
      var id = p.getString(_deviceKey);
      if (id == null || id.isEmpty) {
        final r = Random.secure();
        id = List.generate(32, (_) => r.nextInt(16).toRadixString(16)).join();
        await p.setString(_deviceKey, id);
      }
      return id;
    }();
Future<String>? _deviceId;
const _deviceKey = 'video_device_id';

/// 只给测试用:忘掉内存里缓存的设备号(每个用例的 SharedPreferences 是新的)
@visibleForTesting
void resetVideoDeviceIdForTest() => _deviceId = null;

/// 视频播放的控制器(DEV-PROMPTS-40 #359):包一层 video_player,管清晰度、续播、倍速、
/// 分 P、网络错误重试、播放心跳,并带着这一 P 的弹幕([danmaku])。
///
/// 详情页和竖屏流都用它;画面和控件是 [SzVideoView](竖屏流直接拿 [raw] 画画面)。
///
/// - 清晰度:自动 = 有 720 就 720,没有取不超过 720 的最高一档([pickRendition]);
///   用户手动选过就一直用那一档(存 SharedPreferences),切换时保持进度、旧的接着播到新的就绪;
/// - 续播:`video.me.progress` 是这一 P、进度在 5 秒到结尾前 5 秒之间,打开时跳过去,
///   [resumeHintMs] 给界面提示「上次看到 xx:xx」(提示里有「从头看」);
/// - 连播:一 P 播完调 [onPartEnded],详情页决定接下一 P 还是相关视频;
/// - 播放心跳:播着的时候每 15 秒报一次,暂停不报;换 P、关掉时再报一次(VIDEO-API §3)。
class SzVideoController extends ChangeNotifier {
  SzVideoController({
    required VideoDetail video,
    int partIndex = 0,
    int? startMs,
    this.autoplay = true,
    SzPlayerFactory? playerFactory,
    VideoApi? api,
  })  : _video = video,
        _partIndex = video.parts.isEmpty ? 0 : partIndex.clamp(0, video.parts.length - 1),
        _pendingStartMs = startMs,
        _factory = playerFactory ?? VideoPlayerController.networkUrl,
        _apiOverride = api {
    danmaku = DanmakuController(allowDanmaku: video.allowDanmaku, isOwner: video.isOwner, api: api);
    danmaku.addListener(notifyListeners);
  }

  /// 心跳间隔(播着的时间,不是墙上时间)
  static const int heartbeatMs = 15000;

  /// 用户选过的清晰度(0 = 自动)
  static const String qualityKey = 'video_quality';

  /// 打开 / 换 P / 重试后是否自动播
  final bool autoplay;

  final SzPlayerFactory _factory;
  final VideoApi? _apiOverride;
  VideoApi get _api => _apiOverride ?? videoApi;

  /// 这一 P 的弹幕数据与设置
  late final DanmakuController danmaku;

  /// 一 P 播完:详情页决定连播下一 P 还是相关视频
  void Function(int partIndex)? onPartEnded;

  final VideoDetail _video;
  int _partIndex;
  int? _pendingStartMs;

  VideoPlayerController? _vpc;
  Future<void>? _openFuture;
  int _openGen = 0;
  bool _opening = false;
  bool _switching = false;
  bool _everOpened = false;
  bool _disposed = false;

  Rendition? _quality;
  int _preferredQ = 0;
  bool _prefsLoaded = false;

  double _speed = 1;
  bool _boosting = false;
  int _userPauses = 0;
  double _volume = 1;
  double _brightness = 1;

  String? _error;
  bool _ended = false;
  bool _endNotified = false;
  int? _resumeHintMs;
  final Set<int> _resumed = {};

  String? _notice;
  int _noticeSeq = 0;

  int _lastPosMs = 0;
  final PlayAccumulator _acc = PlayAccumulator();
  Timer? _hb;
  int _sinceReportMs = 0;

  bool _fullscreen = false;

  // ---------------------------------------------------------------- 状态

  VideoDetail get video => _video;
  int get partIndex => _partIndex;

  VideoPart get part => _video.parts.isEmpty ? const VideoPart(id: 0, idx: 0, title: '') : _video.parts[_partIndex];

  /// 底层播放器(竖屏流要直接画画面)。切清晰度、换 P、重试时会换成新的,拿的时候别缓存
  VideoPlayerController? get raw => _vpc;

  bool get initialized => _vpc?.value.isInitialized ?? false;

  Duration get position => initialized ? _vpc!.value.position : Duration(milliseconds: _lastPosMs);

  Duration get duration {
    final d = initialized ? _vpc!.value.duration : Duration.zero;
    return d > Duration.zero ? d : Duration(milliseconds: part.durationMs);
  }

  bool get playing => _vpc?.value.isPlaying ?? false;

  /// 该转圈的时候:正在建播放器、正在切清晰度、播放器在缓冲
  bool get buffering => _opening || _switching || (_vpc?.value.isBuffering ?? false);

  /// 这一 P 播完了(停在结尾)
  bool get ended => _ended;

  /// 放不了时给用户看的一句话(界面上点一下调 [retry])
  String? get error => _error;

  /// 这一 P 的全部档位(高到低)
  List<Rendition> get qualities => part.renditions;

  /// 正在播的档位
  Rendition? get quality => _quality;

  /// 清晰度是不是「自动」
  bool get autoQuality => _preferredQ == 0;

  /// 用户选的倍速(长按 3 倍速时这里不变)
  double get speed => _speed;

  /// 正在长按 3 倍速
  bool get boosting => _boosting;

  double get volume => _volume;

  /// 亮度 0–1。没有亮度插件,界面按它在画面上盖一层黑([dimAlphaFor]),只能往暗调
  double get brightness => _brightness;

  /// 打开时续播跳到了哪(界面提示「上次看到 xx:xx」,点「从头看」或者提示消失后清掉)
  int? get resumeHintMs => _resumeHintMs;

  /// 给界面的一句短提示(「已切换到 720P 准高清」)。[noticeSeq] 变了就是有新的
  String? get notice => _notice;
  int get noticeSeq => _noticeSeq;

  /// 画面宽高比:播放器读到了用播放器的,没读到用分 P 的宽高,都没有按 16:9
  double get aspectRatio {
    if (initialized) {
      final a = _vpc!.value.aspectRatio;
      if (a > 0 && a.isFinite) return a;
    }
    return part.w > 0 && part.h > 0 ? part.w / part.h : 16 / 9;
  }

  /// 竖屏视频:全屏时不转横屏
  bool get isVertical => aspectRatio < 1;

  bool get hasNextPart => _partIndex + 1 < _video.parts.length;

  /// 在不在全屏(SzVideoView 推全屏页时设置)
  bool get fullscreen => _fullscreen;
  set fullscreen(bool v) {
    if (_fullscreen == v) return;
    _fullscreen = v;
    notifyListeners();
  }

  // ---------------------------------------------------------------- 打开

  /// 建播放器、选清晰度、续播定位。重复调用拿到的是同一次打开;SzVideoView 挂上时也会调。
  Future<void> initialize() => _openFuture ??= _open(startMs: _pendingStartMs, play: autoplay);

  Future<void> _loadPrefs() async {
    if (_prefsLoaded) return;
    _prefsLoaded = true;
    try {
      final p = await SharedPreferences.getInstance();
      _preferredQ = p.getInt(qualityKey) ?? 0;
    } catch (_) {
      // 读不到就按自动
    }
  }

  Future<void> _savePreferredQ() async {
    try {
      final p = await SharedPreferences.getInstance();
      await p.setInt(qualityKey, _preferredQ);
    } catch (_) {}
  }

  String _resolve(String url) => _api.api.resolveUrl(url);

  /// 把接口给的相对地址(`/video/v1/vod/…`、`/img/…`)补全,和播放地址用同一个 ApiClient
  String resolveUrl(String path) => _resolve(path);

  Future<void> _open({int? startMs, required bool play}) async {
    final gen = ++_openGen;
    _opening = true;
    _error = null;
    _ended = false;
    _endNotified = false;
    _notify();
    await _loadPrefs();
    unawaited(danmaku.loadSettings());
    danmaku.attachPart(part.id, durationMs: part.durationMs);
    if (gen != _openGen || _disposed) return;

    // Windows / Linux 没有 video_player 的实现:建了控制器 initialize 会抛、dispose 会一直等,
    // 在这之前拦下,错误位上直接写原因(点一下重试还是这句,不会转圈)
    if (!szCanPlayVideo) {
      _opening = false;
      _error = kVideoUnsupportedHint;
      _notify();
      return;
    }
    final r = pickRendition(part.renditions, preferred: _preferredQ);
    if (r == null) {
      _opening = false;
      _error = part.status == 'ready' ? '这一 P 暂时放不了' : '这一 P 还在转码,稍后再来';
      _notify();
      return;
    }
    final vpc = _factory(Uri.parse(_resolve(r.url)));
    try {
      await vpc.initialize();
    } catch (_) {
      unawaited(_safeDispose(vpc));
      if (gen != _openGen || _disposed) return;
      _opening = false;
      _error = '加载失败,点击重试';
      _notify();
      return;
    }
    if (gen != _openGen || _disposed) {
      unawaited(_safeDispose(vpc));
      return;
    }

    // 定位:明确给了起点(历史记录点进来、重试、换 P 带时间)就去那;否则看能不能续播
    var at = startMs;
    if (at == null && !_resumed.contains(part.idx)) {
      _resumed.add(part.idx);
      at = resumePositionMs(_video.me?.progress, partIdx: part.idx, durationMs: vpc.value.duration.inMilliseconds);
      _resumeHintMs = at;
    }
    _pendingStartMs = null;
    try {
      if (at != null && at > 0) await vpc.seekTo(Duration(milliseconds: at));
      await vpc.setVolume(_volume);
      await vpc.setPlaybackSpeed(effectiveSpeed(_speed, boosting: _boosting));
    } catch (_) {
      // 设不上音量 / 倍速不致命,照常播
    }
    if (gen != _openGen || _disposed) {
      unawaited(_safeDispose(vpc));
      return;
    }
    _lastPosMs = at ?? 0;
    _acc.onSeek(_lastPosMs);
    _quality = r;
    _vpc = vpc;
    _everOpened = true;
    vpc.addListener(_onPlayer);
    _opening = false;
    _startHeartbeat();
    _notify();
    if (play) await _playSafely(vpc);
  }

  Future<void> _playSafely(VideoPlayerController vpc) async {
    try {
      await vpc.play();
    } catch (_) {
      // 网页版没有用户手势时浏览器会拒绝自动播放:停在第一帧,等用户点播放
    }
  }

  static Future<void> _safeDispose(VideoPlayerController vpc) async {
    try {
      await vpc.dispose();
    } catch (_) {}
  }

  void _detachPlayer() {
    final old = _vpc;
    _vpc = null;
    if (old == null) return;
    old.removeListener(_onPlayer);
    unawaited(_safeDispose(old));
  }

  void _onPlayer() {
    final vpc = _vpc;
    if (vpc == null || _disposed) return;
    final v = vpc.value;
    if (v.hasError && _error == null) {
      // 播到一半断网:位置记下来,重试时从这接着放
      _error = '加载失败,点击重试';
    }
    if (v.isInitialized) {
      final pos = v.position.inMilliseconds;
      _acc.onPosition(pos, playing: v.isPlaying && !v.isBuffering);
      if (!v.hasError) _lastPosMs = pos;
      danmaku.onPosition(pos);
      // 播完 = 停着、而且停在结尾。只看 isCompleted 不行:它要等下一次真的播起来才清掉,
      // 播完后往回拖进度条时它还是 true —— 那样会再报一次「播完了」,详情页就自己跳到下一 P 去了
      final nearEnd = v.duration > Duration.zero && v.position >= v.duration - const Duration(milliseconds: 300);
      final done = !v.isPlaying && nearEnd && (v.isCompleted || v.position >= v.duration);
      if (done && !_ended) {
        _ended = true;
        unawaited(_report());
        if (!_endNotified) {
          _endNotified = true;
          final idx = _partIndex;
          // 放到下一个微任务里:详情页在回调里多半会换 P,换 P 要释放这个播放器,
          // 而现在还在它的 notifyListeners 里 —— 在通知途中释放会触发断言
          scheduleMicrotask(() {
            if (!_disposed && idx == _partIndex) onPartEnded?.call(idx);
          });
        }
      } else if (!done && _ended && v.isPlaying) {
        _ended = false;
        _endNotified = false;
      }
    }
    notifyListeners();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  void _say(String s) {
    _notice = s;
    _noticeSeq++;
    _notify();
  }

  // ---------------------------------------------------------------- 播放控制

  Future<void> play() async {
    final vpc = _vpc;
    if (vpc == null) {
      if (_error != null) return retry();
      return initialize();
    }
    if (_ended) {
      _ended = false;
      _endNotified = false;
      await vpc.seekTo(Duration.zero);
      _acc.onSeek(0);
    }
    await _playSafely(vpc);
    _notify();
  }

  Future<void> pause() async {
    _userPauses++;
    await _vpc?.pause();
    _notify();
  }

  /// 画面要换个地方显示(进出全屏)之前调。
  ///
  /// 网页版的画面是一个 `<video>` 元素,挪进新的平台视图时会短暂离开文档,浏览器按规范会把它暂停
  /// (实测进全屏就停在那一帧)。调的时候在播,就等挪完(等两拍)接着播;期间用户自己按了暂停就不动。
  /// 手机上画面是纹理,换地方不会暂停,这里等于什么都不做。
  Future<void> keepPlayingAcrossViewChange() async {
    if (!playing) return;
    final pauses = _userPauses;
    for (final ms in const [300, 500]) {
      await Future<void>.delayed(Duration(milliseconds: ms));
      final vpc = _vpc;
      if (_disposed || _userPauses != pauses || vpc == null) return;
      if (!playing && !_ended && _error == null) await _playSafely(vpc);
    }
  }

  Future<void> togglePlay() => playing ? pause() : play();

  Future<void> seekTo(Duration d) async {
    final dur = duration;
    var t = d < Duration.zero ? Duration.zero : d;
    if (dur > Duration.zero && t > dur) t = dur;
    final ms = t.inMilliseconds;
    _acc.onSeek(ms);
    _lastPosMs = ms;
    // 用户自己挑了位置,「上次看到 xx:xx」的提示就没用了
    _resumeHintMs = null;
    if (t < dur) {
      _ended = false;
      _endNotified = false;
    }
    danmaku.onPosition(ms);
    final vpc = _vpc;
    if (vpc == null || !vpc.value.isInitialized) {
      _pendingStartMs = ms;
      _notify();
      return;
    }
    await vpc.seekTo(t);
    _notify();
  }

  /// 倍速 0.5–2(长按的 3 倍速走 [startBoost])
  Future<void> setSpeed(double s) async {
    _speed = clampSpeed(s);
    await _applySpeed();
    _notify();
  }

  Future<void> _applySpeed() async {
    final vpc = _vpc;
    if (vpc == null || !vpc.value.isInitialized) return;
    final want = effectiveSpeed(_speed, boosting: _boosting);
    try {
      await vpc.setPlaybackSpeed(want);
    } catch (_) {
      // iOS 上有的视频放不了 2 倍以上(AVPlayer 报错):长按就退到 2 倍
      if (want > 2) {
        try {
          await vpc.setPlaybackSpeed(2);
        } catch (_) {}
      }
    }
  }

  /// 长按开始:3 倍速(只在播着的时候)
  Future<void> startBoost() async {
    if (_boosting || !playing) return;
    _boosting = true;
    _notify();
    await _applySpeed();
  }

  /// 松手:回到用户选的倍速
  Future<void> endBoost() async {
    if (!_boosting) return;
    _boosting = false;
    _notify();
    await _applySpeed();
  }

  Future<void> setVolume(double v) async {
    _volume = min(1.0, max(0.0, v));
    _notify();
    try {
      await _vpc?.setVolume(_volume);
    } catch (_) {}
  }

  void setBrightness(double b) {
    _brightness = min(1.0, max(0.0, b));
    _notify();
  }

  /// 续播提示上点了「从头看」
  Future<void> restartFromBeginning() async {
    _resumeHintMs = null;
    await seekTo(Duration.zero);
  }

  /// 续播提示显示够了
  void dismissResumeHint() {
    if (_resumeHintMs == null) return;
    _resumeHintMs = null;
    _notify();
  }

  // ---------------------------------------------------------------- 清晰度

  /// 切到 [r] 这一档,记住用户的选择。旧的播放器一直播到新的就绪,再定位到最新进度换上 —— 画面不断。
  Future<void> setQuality(Rendition r) async {
    _preferredQ = r.q;
    unawaited(_savePreferredQ());
    await _switchTo(r);
  }

  /// 切回「自动」
  Future<void> setAutoQuality() async {
    _preferredQ = 0;
    unawaited(_savePreferredQ());
    final r = pickRendition(part.renditions);
    if (r == null) return;
    if (r.q == _quality?.q) {
      _say('已切换到自动(${qualityShort(r.q)})');
      return;
    }
    await _switchTo(r, auto: true);
  }

  Future<void> _switchTo(Rendition r, {bool auto = false}) async {
    final old = _vpc;
    if (old == null || !old.value.isInitialized) {
      // 还没打开 / 出错了:按新的选择重新打开
      _detachPlayer();
      final f = _open(startMs: _lastPosMs > 0 ? _lastPosMs : _pendingStartMs, play: true);
      _openFuture = f;
      return f;
    }
    if (r.url == _quality?.url) return;
    final gen = ++_openGen;
    _switching = true;
    _notify();
    final vpc = _factory(Uri.parse(_resolve(r.url)));
    try {
      await vpc.initialize();
    } catch (_) {
      unawaited(_safeDispose(vpc));
      if (gen == _openGen && !_disposed) {
        _switching = false;
        _say('切换清晰度失败,还在播原来的');
      }
      return;
    }
    if (gen != _openGen || _disposed || !identical(old, _vpc)) {
      unawaited(_safeDispose(vpc));
      return;
    }
    final at = old.value.position;
    final wasPlaying = old.value.isPlaying;
    try {
      await vpc.seekTo(at);
      await vpc.setVolume(_volume);
      await vpc.setPlaybackSpeed(effectiveSpeed(_speed, boosting: _boosting));
    } catch (_) {}
    if (gen != _openGen || _disposed || !identical(old, _vpc)) {
      unawaited(_safeDispose(vpc));
      return;
    }
    _detachPlayer();
    _vpc = vpc;
    _quality = r;
    _switching = false;
    _acc.onSeek(at.inMilliseconds);
    vpc.addListener(_onPlayer);
    if (wasPlaying) await _playSafely(vpc);
    _say(auto ? '已切换到自动(${qualityShort(r.q)})' : '已切换到 ${r.label}');
  }

  // ---------------------------------------------------------------- 分 P 与重试

  /// 换到第 [index] P(下标,不是 idx)。[startMs] 给了就从那开始,否则按续播规则。
  Future<void> switchPart(int index, {int? startMs}) async {
    if (index < 0 || index >= _video.parts.length) return;
    if (index == _partIndex && startMs == null && _vpc != null && _error == null) return;
    // 旧的这 P 最后报一次(续播记的是它的位置)
    if (_everOpened) unawaited(_report());
    _stopHeartbeat();
    _detachPlayer();
    _partIndex = index;
    _quality = null;
    _error = null;
    _ended = false;
    _endNotified = false;
    _resumeHintMs = null;
    _boosting = false;
    _lastPosMs = startMs ?? 0;
    _acc.reset();
    _notify();
    final f = _open(startMs: startMs, play: true);
    _openFuture = f;
    return f;
  }

  /// 网络错误后重试:从出错时的位置接着放
  Future<void> retry() {
    final at = _lastPosMs > 0 ? _lastPosMs : _pendingStartMs;
    _detachPlayer();
    final f = _open(startMs: at, play: true);
    _openFuture = f;
    return f;
  }

  // ---------------------------------------------------------------- 播放心跳

  void _startHeartbeat() {
    _hb ??= Timer.periodic(const Duration(seconds: 1), (_) {
      if (!playing || buffering) return;
      _sinceReportMs += 1000;
      if (_sinceReportMs >= heartbeatMs) {
        _sinceReportMs = 0;
        unawaited(_report());
      }
    });
  }

  void _stopHeartbeat() {
    _hb?.cancel();
    _hb = null;
    _sinceReportMs = 0;
  }

  /// 报一次心跳。位置和时长在第一个 await 之前取好 —— dispose 里调它时播放器随后就释放了
  Future<void> _report() async {
    if (_video.parts.isEmpty || part.id <= 0) return;
    final partId = part.id;
    final pos = position.inMilliseconds;
    final played = _acc.playedMs;
    final api = _api;
    try {
      final device = api.api.isLoggedIn ? null : await videoDeviceId();
      await api.view(_video.vid, partId: partId, positionMs: pos, playedMs: played, deviceId: device);
    } catch (_) {
      // 心跳丢一次无所谓:played_ms 是累计值,下一次会一起带上
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _stopHeartbeat();
    if (_everOpened) unawaited(_report());
    _detachPlayer();
    danmaku.removeListener(notifyListeners);
    danmaku.dispose();
    super.dispose();
  }
}
