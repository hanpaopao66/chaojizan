// 弹幕设置(DEV-PROMPTS-40 §5.10):开关、不透明度、字号、速度、显示区域、屏蔽规则。
// 纯 Dart,和引擎一样不碰 Flutter —— 过滤规则要单测,落盘由 DanmakuController 负责。
import 'dart:math';

import '../models.dart';

/// 发弹幕能选的颜色(24 位 RGB)。白色在第一个,是缺省;其余照 B 站的常用色取,
/// 都是深色描边下还看得清的亮色 —— 太暗的颜色压在视频上看不见,干脆不给选。
const List<int> kDanmakuColors = [
  0xFFFFFF, // 白
  0xFE0302, // 红
  0xFF7204, // 橙
  0xFFD302, // 黄
  0x00CD00, // 绿
  0x00A2FF, // 蓝
  0xCC0273, // 紫红
  0x89D5FF, // 天蓝
];

const int kDanmakuWhite = 0xFFFFFF;

/// 显示区域的四档:1/4、半屏、3/4、全屏。
const List<double> kDanmakuAreas = [0.25, 0.5, 0.75, 1.0];

String danmakuAreaLabel(double a) => a <= 0.25 ? '1/4' : (a <= 0.5 ? '半屏' : (a <= 0.75 ? '3/4' : '全屏'));

double _clamp(double v, double lo, double hi) => v.isNaN ? lo : max(lo, min(hi, v));

/// 取最近的一档显示区域。存下来的值被手改过、或者以后改了档位,都不会落在档外。
double snapDanmakuArea(double a) {
  var best = kDanmakuAreas.last;
  for (final x in kDanmakuAreas) {
    if ((x - a).abs() < (best - a).abs()) best = x;
  }
  return best;
}

/// 一份弹幕设置。不可变:改一项就 copyWith 出一份新的,DanmakuController 负责存盘和通知。
class DanmakuSettings {
  const DanmakuSettings({
    this.enabled = true,
    this.opacity = 0.8,
    this.fontScale = 1.0,
    this.speed = 1.0,
    this.area = 1.0,
    this.blockTop = false,
    this.blockBottom = false,
    this.blockScroll = false,
    this.blockColored = false,
    this.blockWords = const [],
    this.blockUsers = const [],
  });

  /// 总开关
  final bool enabled;

  /// 不透明度 0.2–1。缺省 0.8:全不透明的弹幕压在画面上太抢,B 站缺省也不是 100%
  final double opacity;

  /// 字号缩放 0.5–1.5
  final double fontScale;

  /// 飞行速度倍数 0.5–2(2 = 4 秒飞过屏幕)
  final double speed;

  /// 显示区域:屏幕从上往下的比例,只取 [kDanmakuAreas] 里的四档
  final double area;

  final bool blockTop;
  final bool blockBottom;
  final bool blockScroll;

  /// 屏蔽彩色:只留白色弹幕
  final bool blockColored;

  /// 屏蔽词(包含即屏蔽,不分大小写)
  final List<String> blockWords;

  /// 屏蔽的人(弹幕的 user_hash,反推不出是谁,所以列表里也只能显示这串哈希)
  final List<String> blockUsers;

  static const double minOpacity = 0.2;
  static const double minFontScale = 0.5;
  static const double maxFontScale = 1.5;
  static const double minSpeed = 0.5;
  static const double maxSpeed = 2.0;

  /// 屏蔽词最多存多少个:每条弹幕都要和全部屏蔽词比一遍,几千个词会让拉段之后的过滤卡一下
  static const int maxBlockWords = 100;
  static const int maxBlockUsers = 500;

  DanmakuSettings copyWith({
    bool? enabled,
    double? opacity,
    double? fontScale,
    double? speed,
    double? area,
    bool? blockTop,
    bool? blockBottom,
    bool? blockScroll,
    bool? blockColored,
    List<String>? blockWords,
    List<String>? blockUsers,
  }) =>
      DanmakuSettings(
        enabled: enabled ?? this.enabled,
        opacity: _clamp(opacity ?? this.opacity, minOpacity, 1),
        fontScale: _clamp(fontScale ?? this.fontScale, minFontScale, maxFontScale),
        speed: _clamp(speed ?? this.speed, minSpeed, maxSpeed),
        area: snapDanmakuArea(area ?? this.area),
        blockTop: blockTop ?? this.blockTop,
        blockBottom: blockBottom ?? this.blockBottom,
        blockScroll: blockScroll ?? this.blockScroll,
        blockColored: blockColored ?? this.blockColored,
        blockWords: blockWords ?? this.blockWords,
        blockUsers: blockUsers ?? this.blockUsers,
      );

  Map<String, dynamic> toJson() => {
        'enabled': enabled,
        'opacity': opacity,
        'font_scale': fontScale,
        'speed': speed,
        'area': area,
        'block_top': blockTop,
        'block_bottom': blockBottom,
        'block_scroll': blockScroll,
        'block_colored': blockColored,
        'block_words': blockWords,
        'block_users': blockUsers,
      };

  /// 从存盘的 JSON 读回来。缺字段给缺省、越界的夹回范围 —— 存的东西坏了也只是退回缺省,不崩。
  factory DanmakuSettings.fromJson(Object? j) {
    final m = vMap(j);
    const d = DanmakuSettings();
    bool b(String k, bool def) => m[k] is bool ? m[k] as bool : def;
    double n(String k, double def) => m[k] is num ? (m[k] as num).toDouble() : def;
    List<String> s(String k, int cap) =>
        [for (final x in vList(m[k])) if (x is String && x.trim().isNotEmpty) x.trim()].take(cap).toList();
    return d.copyWith(
      enabled: b('enabled', d.enabled),
      opacity: n('opacity', d.opacity),
      fontScale: n('font_scale', d.fontScale),
      speed: n('speed', d.speed),
      area: n('area', d.area),
      blockTop: b('block_top', false),
      blockBottom: b('block_bottom', false),
      blockScroll: b('block_scroll', false),
      blockColored: b('block_colored', false),
      blockWords: s('block_words', maxBlockWords),
      blockUsers: s('block_users', maxBlockUsers),
    );
  }

  /// 这条弹幕按屏蔽规则该不该显示。
  ///
  /// **自己发的一律显示**:刚发出去的弹幕要立即上屏给自己看到,
  /// 发之前自己设了「屏蔽滚动」也一样 —— 不然用户会以为没发出去,再发一遍。
  bool allows(Danmaku d) {
    if (d.mine) return true;
    switch (d.mode) {
      case Danmaku.top:
        if (blockTop) return false;
      case Danmaku.bottom:
        if (blockBottom) return false;
      default:
        if (blockScroll) return false;
    }
    if (blockColored && (d.color & 0xFFFFFF) != kDanmakuWhite) return false;
    if (d.userHash.isNotEmpty && blockUsers.contains(d.userHash)) return false;
    if (blockWords.isNotEmpty) {
      final t = d.text.toLowerCase();
      for (final w in blockWords) {
        if (w.isNotEmpty && t.contains(w.toLowerCase())) return false;
      }
    }
    return true;
  }
}
