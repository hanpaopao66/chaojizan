// 弹幕排布引擎(DEV-PROMPTS-40 §5.10,#360)。纯 Dart,不 import Flutter,单测直接跑。
//
// 规矩和文档逐条对应:
//
// - 滚动弹幕分轨道,行高 = 字号 × 1.4(这里的字号已经乘过视口缩放和设置里的「字号缩放」);
//   轨道高度按**标准字号(25)**算,小字号(18)的弹幕也占一整条轨道 —— 行高不齐的话,
//   相邻两条轨道的字会上下错开,看着像排版坏了;
// - 一条滚动弹幕从右边缘进、左边缘出,全程固定 8 秒:速度 = (屏宽 + 文字宽) ÷ 8s,
//   设置里的速度倍数(0.5×–2×)直接除这 8 秒;
// - 同一轨道**前一条的尾巴离开右边缘**才放下一条。光有这一条还不够:文字越长飞得越快,
//   后一条比前一条长的话,会在屏幕左半边追尾。所以再加一条「追不上」:前一条完全离开屏幕时,
//   后一条的头还没到左边缘。两条都满足才放 —— 这样「同轨道不重叠」是真成立的,单测按几何量;
// - 顶部 / 底部弹幕水平居中停 4 秒;顶部从上往下占轨道,底部从显示区域的底边往上;
// - 哪条轨道都放不下就**丢弃**,不排队等:等到有空位的时候,早就对不上那一刻的画面了;
// - 显示区域(1/4、半屏、3/4、全屏)只决定能用几条轨道;
// - 跳进度后按新时间重建:把新时刻往前一个飞行周期内的弹幕按时间顺序重新排一遍 ——
//   屏幕上的样子和一直顺着播到这里接近,而且确定、可复现(同一时刻重建两次结果一样)。
//
// 时间一律是**视频时间**(毫秒):倍速播放时视频时间走得快,弹幕跟着快;暂停时视频时间不走,弹幕就停。
// 引擎本身不计时,由弹幕层每帧把当前视频时间喂进来(advance)。
import 'dart:math';

import '../models.dart';

/// 量文字宽度:给文字和字号(像素),回像素宽。界面里用 TextPainter 量;单测里给个假的
/// (比如「每个字 = 字号宽」),这样引擎的几何可以精确断言。
typedef DanmakuMeasure = double Function(String text, double fontSize);

/// 一条排上了屏的弹幕。
class DanmakuSlot {
  DanmakuSlot._({
    required this.item,
    required this.mode,
    required this.track,
    required this.startMs,
    required this.durationMs,
    required this.width,
    required this.fontSize,
    required this.speed,
    required this.forced,
  });

  final Danmaku item;

  /// 1 滚动 / 4 底部 / 5 顶部(不认识的模式按滚动处理)
  final int mode;

  /// 第几条轨道:滚动和顶部从上往下数,底部从下往上数
  final int track;

  /// 上屏时刻(视频时间)。一般就是弹幕的 time_ms;自己刚发的是「现在」
  final int startMs;

  /// 在屏幕上待多久
  final int durationMs;

  /// 文字宽(像素)
  final double width;

  /// 这一条的字号(像素)
  final double fontSize;

  /// 滚动速度(像素 / 毫秒);顶部 / 底部是 0
  final double speed;

  /// 自己刚发的、没有空轨道也硬放上来的
  final bool forced;

  int get endMs => startMs + durationMs;
  bool get scrolling => mode == Danmaku.scroll;
}

/// 弹幕排布:给定视口、字号、速度、显示区域和按时间排好的弹幕,算出任一时刻屏幕上有哪些、各在哪。
class DanmakuEngine {
  DanmakuEngine({required this.measure});

  /// 滚动弹幕飞过屏幕的时长(速度倍数 1 时)
  static const int scrollMs = 8000;

  /// 顶部 / 底部弹幕停留的时长(不受速度倍数影响 —— 速度设置管的是「飞」)
  static const int fixedMs = 4000;

  /// 行高 = 字号 × 1.4
  static const double lineHeight = 1.4;

  /// 标准字号(接口里的 size = 25)
  static const int standardSize = 25;

  final DanmakuMeasure measure;

  double _width = 0;
  double _height = 0;
  double _fontSize = 25;
  double _speed = 1;
  double _area = 1;

  List<Danmaku> _items = const [];
  int _cursor = 0;
  int _now = 0;
  bool _started = false;
  int _dropped = 0;

  final List<DanmakuSlot> _active = [];
  List<DanmakuSlot?> _scroll = const [];
  List<DanmakuSlot?> _top = const [];
  List<DanmakuSlot?> _bottom = const [];

  /// 自己刚发的那条已经硬放上屏了,顺着播到它的 time_ms 时别再放一遍
  final Set<int> _skipOnce = {};

  /// 量过的宽度按弹幕对象缓存。字号一变整个换掉(Expando 不能清空,只能重建)
  Expando<double> _widths = Expando();

  double get width => _width;
  double get height => _height;

  /// 标准字号(25)对应的像素
  double get fontSize => _fontSize;
  double get speed => _speed;
  double get area => _area;
  double get trackHeight => _fontSize * lineHeight;

  /// 能用几条轨道:显示区域的高度 ÷ 行高,向下取整
  int get trackCount => trackHeight <= 0 ? 0 : max(0, (_height * _area / trackHeight + 1e-9).floor());

  /// 这一档速度下,滚动弹幕飞过屏幕要多久(视频时间)
  int get scrollDurationMs => (scrollMs / _speed).round();

  /// 重建要往前看多远:最长的那种弹幕在屏上待的时间
  int get windowMs => max(scrollDurationMs, fixedMs);

  /// 引擎推进到的时刻
  int get nowMs => _now;

  /// 现在屏幕上的弹幕(按上屏先后)
  List<DanmakuSlot> get active => List.unmodifiable(_active);

  /// 从开始到现在丢了几条(放不下的)。调试和单测看
  int get dropped => _dropped;

  /// 全部弹幕(按时间排好的)
  List<Danmaku> get items => List.unmodifiable(_items);

  /// 视口、字号、速度、显示区域。有变化就按当前时间重建(字号或屏宽一变,旧的排布全都不对了)。
  void configure({
    required double width,
    required double height,
    required double fontSize,
    double speed = 1,
    double area = 1,
  }) {
    final s = speed.isNaN ? 1.0 : speed.clamp(0.25, 4.0).toDouble();
    final a = area.isNaN ? 1.0 : area.clamp(0.0, 1.0).toDouble();
    if (width == _width && height == _height && fontSize == _fontSize && s == _speed && a == _area) return;
    if (fontSize != _fontSize) _widths = Expando();
    _width = max(0, width);
    _height = max(0, height);
    _fontSize = max(1, fontSize);
    _speed = s;
    _area = a;
    if (_started) seek(_now);
  }

  /// 字体变了(网页版的中文回落字体是用到才下载的,下载完同一段字宽度就变了):
  /// 量过的宽度全部作废,按当前时间重建。
  void remeasure() {
    _widths = Expando();
    if (_started) seek(_now);
  }

  /// 换一份弹幕(拉到新的一段、屏蔽规则变了、换 P)。不要求排好序,这里排。
  ///
  /// 只有「当前时刻往前一个窗口里」的内容变了才重建;新来的全在未来(预取的下一段)就只换列表,
  /// 屏幕上正在飞的那些不动 —— 不然每拉到一段,满屏弹幕就会闪一下换个位置。
  void setItems(List<Danmaku> items) {
    final sorted = [...items]..sort(_byTime);
    if (!_started) {
      _items = sorted;
      _cursor = 0;
      return;
    }
    final before = _windowIds(_items);
    _items = sorted;
    if (!_sameIds(before, _windowIds(sorted))) {
      seek(_now);
      return;
    }
    _cursor = _upperBound(_now);
  }

  /// 推进到 [nowMs]:把这段时间里到点的弹幕按顺序排上屏,把飞完 / 停够了的拿掉。
  /// 倒退、或者往前跳得比一个窗口还远,当成跳进度处理(重建)。
  List<DanmakuSlot> advance(int nowMs) {
    if (!_started || nowMs < _now || nowMs - _now > windowMs) {
      seek(nowMs);
      return _active;
    }
    while (_cursor < _items.length && _items[_cursor].timeMs <= nowMs) {
      final d = _items[_cursor++];
      if (_skipOnce.remove(d.id)) continue;
      _place(d, d.timeMs);
    }
    _now = nowMs;
    _active.removeWhere((s) => s.endMs <= nowMs);
    return _active;
  }

  /// 跳到 [nowMs] 并重建:清空屏幕,把 (nowMs − 窗口, nowMs] 里的弹幕按时间顺序重新排。
  void seek(int nowMs) {
    _started = true;
    _now = nowMs;
    _active.clear();
    _skipOnce.clear();
    final n = trackCount;
    _scroll = List<DanmakuSlot?>.filled(n, null);
    _top = List<DanmakuSlot?>.filled(n, null);
    _bottom = List<DanmakuSlot?>.filled(n, null);
    var i = _upperBound(nowMs - windowMs);
    for (; i < _items.length && _items[i].timeMs <= nowMs; i++) {
      _place(_items[i], _items[i].timeMs);
    }
    _cursor = i;
    _active.removeWhere((s) => s.endMs <= nowMs);
  }

  /// 自己刚发出去的弹幕:插进列表,**现在**就上屏。没有空轨道也硬放(放在最快空出来的那条上)——
  /// 别人的弹幕放不下可以丢,自己的丢了用户会以为没发出去。
  DanmakuSlot? insertNow(Danmaku d) {
    if (!_started) seek(_now);
    final idx = _upperBound(d.timeMs);
    _items = [..._items]..insert(idx, d);
    if (d.timeMs <= _now) {
      // 游标永远停在「第一条 time_ms > 现在」,插在它前面就把游标往后挪一格,算它已经放过了
      _cursor++;
    } else {
      // 发的时刻在「现在」之后(暂停时刚好卡在边界上):顺着播到它的时候跳过一次
      _skipOnce.add(d.id);
    }
    return _place(d, _now, forced: true);
  }

  /// [slot] 在 [atMs] 时刻的左边缘 x。
  double xOf(DanmakuSlot slot, [int? atMs]) {
    if (!slot.scrolling) return (_width - slot.width) / 2;
    return _width - slot.speed * ((atMs ?? _now) - slot.startMs);
  }

  /// [slot] 所在轨道的顶边 y。
  double yOf(DanmakuSlot slot) {
    if (slot.mode == Danmaku.bottom) return _height * _area - (slot.track + 1) * trackHeight;
    return slot.track * trackHeight;
  }

  /// 点在 (x, y) 上的是哪条弹幕(后上屏的压在上面,先查它)。左右各放宽 [slop] 像素,手指粗。
  DanmakuSlot? hitTest(double x, double y, {double slop = 6}) {
    for (var i = _active.length - 1; i >= 0; i--) {
      final s = _active[i];
      final left = xOf(s);
      final top = yOf(s);
      if (x >= left - slop && x <= left + s.width + slop && y >= top && y <= top + trackHeight) return s;
    }
    return null;
  }

  // ---------------------------------------------------------------- 排布

  double _fontOf(Danmaku d) => _fontSize * (d.size <= 0 ? standardSize : d.size) / standardSize;

  double _widthOf(Danmaku d, double fs) => _widths[d] ??= max(0.0, measure(d.text, fs));

  DanmakuSlot? _place(Danmaku d, int t, {bool forced = false}) {
    final n = trackCount;
    if (n <= 0 && !forced) {
      _dropped++;
      return null;
    }
    final mode = d.mode == Danmaku.top || d.mode == Danmaku.bottom ? d.mode : Danmaku.scroll;
    final fs = _fontOf(d);
    final w = _widthOf(d, fs);
    final lanes = mode == Danmaku.top ? _top : (mode == Danmaku.bottom ? _bottom : _scroll);
    final dur = mode == Danmaku.scroll ? scrollDurationMs : fixedMs;
    final v = mode == Danmaku.scroll ? (_width + w) / dur : 0.0;

    double readyAt(DanmakuSlot? last) {
      if (last == null) return double.negativeInfinity;
      if (mode != Danmaku.scroll) return last.endMs.toDouble();
      // 1) 前一条的尾巴离开右边缘;2) 前一条完全离开屏幕时,新的这条的头还没到左边缘(追不上)
      final double tailOut = last.startMs + (last.speed > 0 ? last.width / last.speed : 0.0);
      final double noCatchUp = last.endMs - (v > 0 ? _width / v : 0.0);
      return max(tailOut, noCatchUp);
    }

    var pick = -1;
    for (var k = 0; k < lanes.length; k++) {
      if (t >= readyAt(lanes[k]) - 1e-6) {
        pick = k;
        break;
      }
    }
    if (pick < 0) {
      if (!forced) {
        _dropped++;
        return null;
      }
      // 硬放:挑最快空出来的那条(没有轨道可用时就放第 0 条)
      pick = 0;
      var best = double.infinity;
      for (var k = 0; k < lanes.length; k++) {
        final r = readyAt(lanes[k]);
        if (r < best) {
          best = r;
          pick = k;
        }
      }
    }
    final slot = DanmakuSlot._(
      item: d,
      mode: mode,
      track: pick,
      startMs: t,
      durationMs: dur,
      width: w,
      fontSize: fs,
      speed: v,
      forced: forced,
    );
    if (pick < lanes.length) lanes[pick] = slot;
    _active.add(slot);
    return slot;
  }

  // ---------------------------------------------------------------- 工具

  static int _byTime(Danmaku a, Danmaku b) => a.timeMs != b.timeMs ? a.timeMs - b.timeMs : a.id - b.id;

  /// 第一条 time_ms > [ms] 的下标
  int _upperBound(int ms) {
    var lo = 0, hi = _items.length;
    while (lo < hi) {
      final mid = (lo + hi) >> 1;
      if (_items[mid].timeMs <= ms) {
        lo = mid + 1;
      } else {
        hi = mid;
      }
    }
    return lo;
  }

  List<int> _windowIds(List<Danmaku> list) => [
        for (final d in list)
          if (d.timeMs > _now - windowMs && d.timeMs <= _now) d.id,
      ];

  static bool _sameIds(List<int> a, List<int> b) {
    if (a.length != b.length) return false;
    final sa = a.toSet();
    return b.every(sa.contains);
  }
}

/// 高能进度条:每 5 秒一桶的弹幕数 → 每桶 0–1 的高度。
///
/// 先做三桶滑动平均再按最大值归一:原始计数一桶一个样,画出来是锯齿;
/// 平均一下才是「这一段弹幕多」的起伏,和 B 站那条曲线一个意思。全是 0 就全是 0(不画)。
List<double> danmakuDensityLevels(List<int> counts) {
  if (counts.isEmpty) return const [];
  final n = counts.length;
  final smooth = List<double>.generate(n, (i) {
    var sum = 0.0, k = 0;
    for (var j = i - 1; j <= i + 1; j++) {
      if (j < 0 || j >= n) continue;
      sum += max(0, counts[j]);
      k++;
    }
    return sum / k;
  });
  final top = smooth.reduce(max);
  if (top <= 0) return List<double>.filled(n, 0);
  return [for (final x in smooth) x / top];
}
