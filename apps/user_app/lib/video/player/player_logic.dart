// 播放器里能抽出来的判断,全是纯函数 / 纯 Dart 小类(DEV-PROMPTS-40 #359):
// 手势判定、清晰度选择、续播判定、雪碧图对齐、播放时长累计、时间格式。
// 控件和控制器只管接线,判断在这里,单测直接测这里。
import 'dart:math';

import '../models.dart';

// ---------------------------------------------------------------- 清晰度

/// 自动清晰度的目标档位。
///
/// 文档写的是「Wi-Fi 720、流量 480」,但分辨网络类型要插件(connectivity_plus 不是官方包),
/// 所以现在一律按 Wi-Fi 算:**有 720 就 720,没有就取不超过 720 的最高一档**。
/// 以后接了网络类型,把 [pickRendition] 的 target 按网络换成 480 就行。
const int kAutoQuality = 720;

/// 从这一 P 的档位里挑一档播。[preferred] 是用户选过的档位,0 = 自动。
///
/// - 自动:目标 [kAutoQuality];
/// - 用户选过:目标就是那一档;
/// - 目标这一档没有(换了个低分辨率的视频):取不超过目标的最高一档;
///   连这也没有(全都比目标高,只在目标比 360 还低时发生):取最低一档。
///
/// 这一 P 一档都没有(还没转码完)时返回 null。
Rendition? pickRendition(List<Rendition> list, {int preferred = 0}) {
  if (list.isEmpty) return null;
  final target = preferred > 0 ? preferred : kAutoQuality;
  Rendition? best;
  for (final r in list) {
    if (r.q == target) return r;
    if (r.q <= target && (best == null || r.q > best.q)) best = r;
  }
  if (best != null) return best;
  return list.reduce((a, b) => a.q <= b.q ? a : b);
}

/// 清晰度的短写:720P。
String qualityShort(int q) => '${q}P';

// ---------------------------------------------------------------- 倍速

/// 菜单里的倍速档位(文档:0.5–2)。
const List<double> kPlayerSpeeds = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0];

/// 长按时的倍速
const double kBoostSpeed = 3.0;

double clampSpeed(double s) => s.isNaN ? 1.0 : min(2.0, max(0.5, s));

/// 实际该用的播放速度:长按期间 3 倍速,松手回到用户选的那一档。
double effectiveSpeed(double chosen, {required bool boosting}) => boosting ? kBoostSpeed : clampSpeed(chosen);

/// 倍速的写法:0.5x、0.75x、1.0x、2.0x。
///
/// 不直接写 `'${s}x'`:网页版是 JS 数字,整数的 double 会打成「1」「2」,手机上是「1.0」「2.0」,两端不一样。
String speedText(double s) => '${s == s.roundToDouble() ? s.toStringAsFixed(1) : s.toString()}x';

/// 倍速按钮上的字:1 倍时写「倍速」(和 B 站一样,不然一排按钮里多个「1.0x」看着像坏了)。
String speedLabel(double s) => (s - 1).abs() < 0.001 ? '倍速' : speedText(s);

// ---------------------------------------------------------------- 续播

/// 续播只在「看过开头 5 秒」且「离结尾还有 5 秒以上」时生效:
/// 开头几秒跳过去没意义,快看完的跳到结尾只会立刻播完。
const int kResumeEdgeMs = 5000;

/// 历史进度 [p] 是不是这一 P([partIdx] 是分 P 的 idx 字段)、该不该跳过去。该跳就返回位置,不跳返回 null。
/// [durationMs] 用这一 P 的实际时长(播放器读出来的优先,读不到用接口给的)。
int? resumePositionMs(VProgress? p, {required int partIdx, required int durationMs}) {
  if (p == null || p.partIdx != partIdx) return null;
  final dur = durationMs > 0 ? durationMs : p.durationMs;
  if (dur <= 0) return null;
  final pos = p.positionMs;
  if (pos < kResumeEdgeMs || pos > dur - kResumeEdgeMs) return null;
  return pos;
}

// ---------------------------------------------------------------- 时间

/// 播放器里的时间:01:05、12:30、1:02:03(和 B 站一样分钟补两位;超过一小时带小时)。
String playerClock(int ms) {
  final s = max(0, ms) ~/ 1000;
  final h = s ~/ 3600, m = (s % 3600) ~/ 60, sec = s % 60;
  String two(int x) => x.toString().padLeft(2, '0');
  return h > 0 ? '$h:${two(m)}:${two(sec)}' : '${two(m)}:${two(sec)}';
}

// ---------------------------------------------------------------- 手势

/// 播放器上一次触摸的归类。
enum PlayerGesture {
  /// 单击:显示 / 隐藏控件
  tap,

  /// 双击:暂停 / 播放
  doubleTap,

  /// 横滑:快进快退
  seek,

  /// 左半边上下滑:亮度
  brightness,

  /// 右半边上下滑:音量
  volume,

  /// 长按:3 倍速,松手恢复
  longPress,
}

/// 两次单击间隔不超过这么久、离得不超过 [kDoubleTapSlop] 算双击(和系统的双击时限一致)
const int kDoubleTapMs = 300;
const double kDoubleTapSlop = 48;

/// 抬手时判单击还是双击。
///
/// 不用 Flutter 自带的双击识别:它和单击、拖动一起进手势竞技场,单击要等它超时才触发,
/// 还会吞掉紧跟着的拖动。这里只让 TapGestureRecognizer 报「抬手」,单双击自己判 ——
/// [lastUpMs] / [lastX] / [lastY] 是上一次**还没被认成双击**的抬手。
/// 返回 [PlayerGesture.doubleTap] 就立刻处理;返回 [PlayerGesture.tap] 表示「可能是单击」,
/// 调用方要再等 [kDoubleTapMs],期间没有第二下才当单击处理。
PlayerGesture classifyTapUp({
  required int nowMs,
  required double x,
  required double y,
  int? lastUpMs,
  double? lastX,
  double? lastY,
}) {
  if (lastUpMs == null || lastX == null || lastY == null) return PlayerGesture.tap;
  final dt = nowMs - lastUpMs;
  if (dt < 0 || dt > kDoubleTapMs) return PlayerGesture.tap;
  final dist = sqrt(pow(x - lastX, 2) + pow(y - lastY, 2));
  return dist <= kDoubleTapSlop ? PlayerGesture.doubleTap : PlayerGesture.tap;
}

/// 一串单击的状态:记着上一次还没配成双击的抬手。
///
/// 用法:每次抬手调 [up];回 doubleTap 立刻处理,回 tap 就等 [kDoubleTapMs] 之后问 [stillSingle]
/// —— 期间来了第二下,那一下会把这次配成双击,[stillSingle] 就回 false。
/// 双击之后状态清空,紧接着的第三下重新算第一下(不会和第二下又配成一次双击)。
class TapSequence {
  int? _lastMs;
  double? _lastX;
  double? _lastY;

  PlayerGesture up(int nowMs, double x, double y) {
    final g = classifyTapUp(nowMs: nowMs, x: x, y: y, lastUpMs: _lastMs, lastX: _lastX, lastY: _lastY);
    if (g == PlayerGesture.doubleTap) {
      reset();
    } else {
      _lastMs = nowMs;
      _lastX = x;
      _lastY = y;
    }
    return g;
  }

  /// [upMs] 那次抬手等够了时限还是单击吗(没被后面一下配成双击)
  bool stillSingle(int upMs) => _lastMs == upMs;

  void reset() {
    _lastMs = null;
    _lastX = null;
    _lastY = null;
  }
}

/// 拖动一开始判是哪种:横向 = 快进快退;竖向看起点在左半边还是右半边 = 亮度 / 音量。
///
/// [horizontal] 由手势竞技场决定(横向和竖向两个拖动识别器谁先越过阈值谁赢),
/// [startX] 是**按下时**的横坐标(识别器设了 DragStartBehavior.down)。正中间算右边(音量)。
PlayerGesture classifyDrag({required bool horizontal, required double startX, required double width}) {
  if (horizontal) return PlayerGesture.seek;
  return startX < width / 2 ? PlayerGesture.brightness : PlayerGesture.volume;
}

/// 横滑快进快退:手指从起点横移 [dx] 像素,跳到哪。
///
/// 满屏宽一滑 = min(时长, 2 分钟):短视频能精细到秒,长视频一滑也不会飞出去十几分钟。
int seekTargetMs({required int startMs, required double dx, required double width, required int durationMs}) {
  if (durationMs <= 0 || width <= 0) return max(0, startMs);
  final span = min(durationMs, 120000);
  final t = startMs + dx / width * span;
  return t.round().clamp(0, durationMs);
}

/// 上下滑调亮度 / 音量:从 [start] 开始,手指往上移 [dy](往上是负数)。滑满播放器高度 = 0 到 100%。
double levelAfterDrag({required double start, required double dy, required double height}) {
  if (height <= 0) return start;
  return min(1.0, max(0.0, start - dy / height));
}

/// 没有亮度插件,调亮度就是在画面上盖一层黑:亮度 1 = 不盖,0 = 盖 70% 的黑
/// (全黑的话画面彻底看不见,用户会以为坏了)。只能往暗调,调不过系统亮度。
double dimAlphaFor(double brightness) => (1 - min(1.0, max(0.0, brightness))) * 0.7;

// ---------------------------------------------------------------- 雪碧图

/// 雪碧图上第 [row] 行第 [col] 列那一格,放进一格大小的框里时的对齐值(-1 左 / 上,1 右 / 下)。
///
/// 做法:把整张图按「一格 = 框的大小」放大到 cols × rows 个框那么大,再按这个对齐值摆进一格大小的框,
/// 框外的裁掉,露出来的正好是那一格。只有一列 / 一行时居中(0)。
({double x, double y}) spriteAlignment({required int col, required int row, required int cols, required int rows}) {
  double a(int i, int n) => n <= 1 ? 0 : -1 + 2 * i / (n - 1);
  return (x: a(col, cols), y: a(row, rows));
}

/// 缩略图显示多大:保持一格的宽高比,塞进 [maxW] × [maxH] 以内(竖屏视频的格子是瘦高的)。
({double w, double h}) spriteThumbSize(SpriteInfo s, {double maxW = 160, double maxH = 90}) {
  if (s.w <= 0 || s.h <= 0) return (w: maxW, h: maxH);
  final k = min(maxW / s.w, maxH / s.h);
  return (w: s.w * k, h: s.h * k);
}

// ---------------------------------------------------------------- 播放时长

/// 算「这次打开以来实际播放了多久」(心跳里的 played_ms):**播放位置往前走了多少**,
/// 拖进度条跳过去的不算、暂停不算。
///
/// 用位置差不用墙上时钟:卡顿缓冲时墙上时钟在走、画面没动,那段不该算;倍速时位置走得快,
/// 看完的内容也确实多 —— 服务端「满 5 秒或 30% 算一次播放」要的就是看了多少内容。
class PlayAccumulator {
  /// 两次位置更新之间往前走了超过这么多,当成跳进度(播放器 100ms 报一次位置,3 倍速也就 300ms)
  static const int jumpMs = 4000;

  int _played = 0;
  int? _last;

  int get playedMs => _played;

  /// 播放器报了一次位置。[playing] 为假(暂停、缓冲)时只记位置不计时长。
  void onPosition(int ms, {required bool playing}) {
    final last = _last;
    _last = ms;
    if (!playing || last == null) return;
    final d = ms - last;
    if (d > 0 && d <= jumpMs) _played += d;
  }

  /// 主动跳了进度:从新位置重新接着算,跳过去的那段不算
  void onSeek(int ms) => _last = ms;

  /// 换 P 了:从 0 算起
  void reset() {
    _played = 0;
    _last = null;
  }
}
