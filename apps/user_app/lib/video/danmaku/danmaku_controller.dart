import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';

import '../api.dart';
import '../models.dart';
import '../nav.dart';
import 'engine.dart';
import 'settings.dart';

/// 一个分 P 的弹幕数据和弹幕设置(DEV-PROMPTS-40 §5.10、VIDEO-API §6)。
///
/// - 拉取:6 分钟一段,当前段 + 下一段(播放位置每变一次问一下,缺哪段补哪段);换 P 全部清空;
/// - 高能进度条:整 P 按 5 秒一桶的弹幕数,换 P 拉一次;
/// - 设置:全 App 一份,存 SharedPreferences。同时开着好几个播放器(竖屏流预加载)时,
///   在一个里改了,别的立刻跟着变 —— 所以设置放在静态的 [_shared] 上,每个控制器只是订阅它;
/// - 发送:接口回来的那条立即上屏(带边框)。弹幕层按 [sentSeq] 拿到它,硬塞上屏;
/// - 屏蔽:按类型 / 彩色 / 屏蔽词 / 屏蔽某人([DanmakuSettings.allows]),[visible] 是过滤后的。
///
/// UP 主关了弹幕([allowDanmaku] 为假)时既不拉也不画(和 B 站一样,关了就是整个视频不显示弹幕),
/// 发送入口显示「UP 主关闭了弹幕」。
class DanmakuController extends ChangeNotifier {
  DanmakuController({bool allowDanmaku = true, bool isOwner = false, VideoApi? api})
      : _allow = allowDanmaku,
        _isOwner = isOwner,
        _apiOverride = api {
    _shared.addListener(_onShared);
  }

  static const String prefsKey = 'video_danmaku_settings';

  /// 一段 6 分钟(VIDEO-API §6)
  static const int segmentMs = 6 * 60 * 1000;

  /// 一段拉失败了,隔这么久再试(不然每 100ms 一次位置更新就重试一次)
  static const Duration retryAfter = Duration(seconds: 15);

  static final ValueNotifier<DanmakuSettings> _shared = ValueNotifier(const DanmakuSettings());
  static Future<void>? _loading;

  /// 只给测试用:把全局设置清回缺省、下次重新从 SharedPreferences 读。
  @visibleForTesting
  static void resetSharedForTest() {
    _shared.value = const DanmakuSettings();
    _loading = null;
  }

  final VideoApi? _apiOverride;
  VideoApi get _api => _apiOverride ?? videoApi;

  bool _allow;
  final bool _isOwner;
  bool _disposed = false;

  int? _partId;
  int _gen = 0;
  int _segmentCount = 1;
  final Map<int, List<Danmaku>> _segments = {};
  final Set<int> _pending = {};
  final Map<int, DateTime> _failedAt = {};

  List<Danmaku>? _items;
  List<Danmaku>? _visible;
  int _version = 0;

  List<int> _density = const [];
  List<double>? _levels;
  int _densityBucketMs = 5000;

  final List<Danmaku> _sentLog = [];
  int _sentSeq = 0;

  /// UP 主有没有开弹幕。详情里的 allow_danmaku,拉段时服务端回的值更新它
  bool get allowDanmaku => _allow;

  /// 这一刻屏幕上该不该有弹幕:UP 主开着、用户也开着
  bool get showing => _allow && settings.enabled;

  DanmakuSettings get settings => _shared.value;

  int? get partId => _partId;

  /// 数据或屏蔽规则变了就加一。弹幕层拿它判断要不要把新列表交给引擎
  int get version => _version;

  /// 已经拉到的全部弹幕(按时间)
  List<Danmaku> get items => _items ??= [
        for (final k in (_segments.keys.toList()..sort())) ..._segments[k]!,
      ];

  /// 过了屏蔽规则、该画的
  List<Danmaku> get visible => _visible ??= showing ? items.where(settings.allows).toList() : const [];

  /// 高能进度条的原始计数(每 [densityBucketMs] 一桶)
  List<int> get density => _density;
  int get densityBucketMs => _densityBucketMs;

  /// 高能进度条每桶的高度 0–1
  List<double> get densityLevels => _levels ??= danmakuDensityLevels(_density);

  /// 自己发出去的弹幕的流水号。弹幕层记着自己看到哪了,用 [sentSince] 取新的
  int get sentSeq => _sentSeq;

  /// [seq] 之后发出去的(最多留最近 20 条;弹幕层每帧都来取,不会积压)
  List<Danmaku> sentSince(int seq) {
    final n = min(_sentSeq - seq, _sentLog.length);
    if (n <= 0) return const [];
    return _sentLog.sublist(_sentLog.length - n);
  }

  /// 能不能删这条:自己发的,或者我是 UP 主(接口也是这么判的)
  bool canDelete(Danmaku d) => d.mine || _isOwner;

  // ---------------------------------------------------------------- 设置

  /// 从 SharedPreferences 读设置。全 App 只读一次,之后都用内存里那份
  Future<void> loadSettings() => _loading ??= () async {
        try {
          final p = await SharedPreferences.getInstance();
          final raw = p.getString(prefsKey);
          if (raw != null && raw.isNotEmpty) _shared.value = DanmakuSettings.fromJson(jsonDecode(raw));
        } catch (_) {
          // 读不出来(存坏了、测试环境没有平台通道)就用缺省设置,弹幕照常能看
        }
      }();

  /// 改设置。拖滑块时每一帧都在改,[persist] 为假只改内存,松手时再存一次
  Future<void> updateSettings(DanmakuSettings s, {bool persist = true}) async {
    _shared.value = s;
    if (!persist) return;
    try {
      final p = await SharedPreferences.getInstance();
      await p.setString(prefsKey, jsonEncode(s.toJson()));
    } catch (_) {
      // 存不上只是下次打开恢复缺省,不影响这次
    }
  }

  Future<void> setEnabled(bool on) => updateSettings(settings.copyWith(enabled: on));

  Future<void> blockUser(String hash) async {
    if (hash.isEmpty || settings.blockUsers.contains(hash)) return;
    final list = [...settings.blockUsers, hash];
    if (list.length > DanmakuSettings.maxBlockUsers) list.removeAt(0);
    await updateSettings(settings.copyWith(blockUsers: list));
  }

  Future<void> unblockUser(String hash) =>
      updateSettings(settings.copyWith(blockUsers: [...settings.blockUsers]..remove(hash)));

  /// 加一个屏蔽词。空的、重复的、超过上限的返回 false
  Future<bool> addBlockWord(String word) async {
    final w = word.trim();
    if (w.isEmpty) return false;
    final lower = w.toLowerCase();
    if (settings.blockWords.any((x) => x.toLowerCase() == lower)) return false;
    if (settings.blockWords.length >= DanmakuSettings.maxBlockWords) return false;
    await updateSettings(settings.copyWith(blockWords: [...settings.blockWords, w]));
    return true;
  }

  Future<void> removeBlockWord(String word) =>
      updateSettings(settings.copyWith(blockWords: [...settings.blockWords]..remove(word)));

  void _onShared() {
    if (_disposed) return;
    _visible = null;
    _version++;
    notifyListeners();
  }

  // ---------------------------------------------------------------- 拉取

  /// 换到这一 P(换 P 时调)。清空旧的,拉高能进度条和前两段
  void attachPart(int partId, {required int durationMs}) {
    if (_partId == partId) return;
    _gen++;
    _partId = partId;
    _segments.clear();
    _pending.clear();
    _failedAt.clear();
    _sentLog.clear();
    _density = const [];
    _levels = null;
    _segmentCount = max(1, (durationMs / segmentMs).ceil());
    _bump();
    if (!_allow || partId <= 0) return;
    unawaited(_loadDensity());
    onPosition(0);
  }

  /// 播放位置变了:确保当前段和下一段在手里
  void onPosition(int ms) {
    if (!_allow || _partId == null || _partId! <= 0) return;
    final seg = max(0, ms) ~/ segmentMs;
    _ensure(seg);
    if (seg + 1 < _segmentCount) _ensure(seg + 1);
  }

  void _ensure(int seg) {
    if (_segments.containsKey(seg) || _pending.contains(seg)) return;
    final failed = _failedAt[seg];
    if (failed != null && DateTime.now().difference(failed) < retryAfter) return;
    unawaited(_fetch(seg));
  }

  Future<void> _fetch(int seg) async {
    final part = _partId!;
    final gen = _gen;
    _pending.add(seg);
    try {
      final r = await _api.danmakuSegment(part, seg);
      // 回来时已经换了 P(或者页面关了):这份是旧 P 的,扔掉。别碰新 P 的 _pending
      if (_disposed || gen != _gen) return;
      _pending.remove(seg);
      _failedAt.remove(seg);
      if (vInt(r['segments']) > 0) _segmentCount = vInt(r['segments']);
      if (r['allow_danmaku'] == false) _allow = false;
      _segments[seg] = [for (final x in vList(r['items'])) Danmaku.fromJson(x)];
      _bump();
    } catch (_) {
      if (_disposed || gen != _gen) return;
      _pending.remove(seg);
      _failedAt[seg] = DateTime.now();
    }
  }

  Future<void> _loadDensity() async {
    final part = _partId!;
    final gen = _gen;
    try {
      final r = await _api.danmakuDensity(part);
      if (_disposed || gen != _gen) return;
      _density = [for (final x in vList(r['counts'])) vInt(x)];
      _densityBucketMs = vInt(r['bucket_ms']) > 0 ? vInt(r['bucket_ms']) : 5000;
      _levels = null;
      notifyListeners();
    } catch (_) {
      // 高能进度条是锦上添花,拉不到就不画
    }
  }

  void _bump() {
    if (_disposed) return;
    _items = null;
    _visible = null;
    _version++;
    notifyListeners();
  }

  // ---------------------------------------------------------------- 发送 / 删除 / 举报

  /// 发一条。成功返回接口给的那条(已经带 id、user_hash,文字是服务端整理过的),并立即上屏;
  /// 失败抛 [ApiException],detail 直接给用户看(限流、屏蔽词、UP 主关了……)。
  Future<Danmaku> send({
    required int timeMs,
    required String text,
    int mode = Danmaku.scroll,
    int color = kDanmakuWhite,
    int size = DanmakuEngine.standardSize,
  }) async {
    final part = _partId;
    if (part == null || part <= 0) throw ApiException(0, '视频还没加载好,稍等一下再发');
    if (!_allow) throw ApiException(403, 'UP 主关闭了弹幕');
    final got = await _api.sendDanmaku(part, timeMs: timeMs, text: text, mode: mode, color: color, size: size);
    // 接口回的 mine 本来就是 true;这里再兜一下,边框和「不受屏蔽规则影响」都靠它
    final d = got.mine
        ? got
        : Danmaku(id: got.id, timeMs: got.timeMs, text: got.text, mode: got.mode, color: got.color,
            size: got.size, userHash: got.userHash, mine: true);
    if (_disposed || part != _partId) return d;
    final seg = max(0, d.timeMs) ~/ segmentMs;
    final list = _segments[seg] ??= [];
    var i = list.length;
    while (i > 0 && list[i - 1].timeMs > d.timeMs) {
      i--;
    }
    list.insert(i, d);
    _sentLog.add(d);
    if (_sentLog.length > 20) _sentLog.removeAt(0);
    _sentSeq++;
    // 高能进度条跟着涨一格,不用重拉
    final b = d.timeMs ~/ _densityBucketMs;
    if (b >= 0 && b < _density.length) {
      _density = [..._density]..[b] += 1;
      _levels = null;
    }
    // 发了却看不到(弹幕关着)会以为没发出去:发的时候顺手打开
    if (!settings.enabled) unawaited(setEnabled(true));
    _bump();
    return d;
  }

  /// 删一条(自己发的,或者 UP 主删自己视频下的)
  Future<void> delete(Danmaku d) async {
    await _api.deleteDanmaku(d.id);
    if (_disposed) return;
    for (final list in _segments.values) {
      list.removeWhere((x) => x.id == d.id);
    }
    _bump();
  }

  /// 举报一条(原因代码见 VIDEO-API 0.8;X999 要写说明)
  Future<Map<String, dynamic>> report(Danmaku d, String reasonCode, {String note = ''}) =>
      _api.report(targetType: 'danmaku', targetId: d.id, reasonCode: reasonCode, note: note);

  @override
  void dispose() {
    _disposed = true;
    _shared.removeListener(_onShared);
    super.dispose();
  }
}
