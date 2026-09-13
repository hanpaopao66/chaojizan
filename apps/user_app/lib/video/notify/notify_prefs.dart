import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'notify_format.dart';

/// 「视频互动」会话底部的「静音」和「提醒设置」(设计稿 C)。
///
/// **只存在这台设备上。** 服务端没有互动提醒的开关 —— 互动提醒本来就不发系统推送,
/// 只在 App 里亮角标(social_notify.py);所以这里能管的也就是角标:
/// 静音 = 这个会话的角标变灰、不进底栏;提醒设置 = 哪几类算进未读。
class VideoNotifyPrefs extends ChangeNotifier {
  VideoNotifyPrefs._();

  static final VideoNotifyPrefs instance = VideoNotifyPrefs._();

  static const _kMuted = 'video_notify_muted';
  static const _kKinds = 'video_notify_badge_kinds';

  bool muted = false;

  /// 算进未读角标的那几类;默认四类都算
  Set<String> kinds = {for (final (k, _) in notifyKinds) k};

  bool _loaded = false;

  Future<void> load() async {
    if (_loaded) return;
    _loaded = true;
    try {
      final p = await SharedPreferences.getInstance();
      muted = p.getBool(_kMuted) ?? false;
      final saved = p.getStringList(_kKinds);
      if (saved != null) kinds = saved.toSet();
      notifyListeners();
    } catch (_) {
      // 读不到就按默认:不静音、四类都算
    }
  }

  Future<void> setMuted(bool v) async {
    muted = v;
    notifyListeners();
    try {
      final p = await SharedPreferences.getInstance();
      await p.setBool(_kMuted, v);
    } catch (_) {}
  }

  Future<void> setKind(String kind, bool on) async {
    kinds = {...kinds}..removeWhere((k) => k == kind);
    if (on) kinds.add(kind);
    notifyListeners();
    try {
      final p = await SharedPreferences.getInstance();
      await p.setStringList(_kKinds, kinds.toList());
    } catch (_) {}
  }
}
