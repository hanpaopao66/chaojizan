import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../chat/store.dart';
import 'notify_format.dart';

/// 「视频互动」会话底部的「静音」和「提醒设置」(设计稿 C)。
///
/// **存在服务端**:`social_profiles.notify` 里的 `interactions`(false = 静音)和
/// `interactions_reply / _at / _like / _system`(哪几类算未读),读写走 `GET / PATCH /social/v1/me`。
/// 换手机、网页版看到的是同一份;在一台设备上改了,服务端推用户事件 `settings`,别的设备当场跟着变。
///
/// 互动提醒本来就不发系统推送,只亮 App 里的角标(social_notify.py),所以这里管的就是角标:
/// 静音 = 这个会话的角标变灰、不进底栏;提醒设置 = 哪几类算进未读。
/// 本机只缓存上一次拿到的值,离线启动时先顶上。
class VideoNotifyPrefs extends ChangeNotifier {
  VideoNotifyPrefs._();

  static final VideoNotifyPrefs instance = VideoNotifyPrefs._();

  static const _kMuted = 'video_notify_muted';
  static const _kKinds = 'video_notify_badge_kinds';

  bool muted = false;

  /// 算进未读角标的那几类;默认四类都算
  Set<String> kinds = {for (final (k, _) in notifyKinds) k};

  bool _cacheLoaded = false;

  /// 先用本机缓存顶上,再问服务端要最新的一份。登录后、回到前台、打开视频互动时都会调,可以重复调
  Future<void> load() async {
    if (!_cacheLoaded) {
      _cacheLoaded = true;
      try {
        final p = await SharedPreferences.getInstance();
        muted = p.getBool(_kMuted) ?? muted;
        final saved = p.getStringList(_kKinds);
        if (saved != null) kinds = saved.toSet();
        notifyListeners();
      } catch (_) {
        // 读不到就按默认:不静音、四类都算
      }
    }
    final api = ChatStore.instance.apiOrNull;
    if (api == null) return; // 没登录:先用缓存
    try {
      applyServer((await api.me())['notify']);
    } catch (_) {
      // 离线:先用缓存,下次再对齐
    }
  }

  /// 服务端给的 notify(`GET /social/v1/me` 的返回,或者用户事件 `settings` 的 data.notify)
  void applyServer(Object? notify) {
    if (notify is! Map) return;
    final m = notify.cast<String, dynamic>();
    final nextMuted = m['interactions'] == false;
    final nextKinds = {for (final (k, _) in notifyKinds) if (m['interactions_$k'] != false) k};
    if (nextMuted == muted && setEquals(nextKinds, kinds)) return;
    muted = nextMuted;
    kinds = nextKinds;
    notifyListeners();
    unawaited(_cache());
  }

  Future<void> setMuted(bool v) => _patch({'interactions': !v}, () => muted = v);

  Future<void> setKind(String kind, bool on) => _patch({'interactions_$kind': on}, () {
        kinds = {...kinds}..remove(kind);
        if (on) kinds.add(kind);
      });

  /// 先改界面,再写服务端;写失败退回原样并把错抛给调用方提示。没登录时只改本机
  Future<void> _patch(Map<String, bool> notify, void Function() apply) async {
    final oldMuted = muted;
    final oldKinds = kinds;
    apply();
    notifyListeners();
    final api = ChatStore.instance.apiOrNull;
    if (api == null) {
      await _cache();
      return;
    }
    try {
      applyServer((await api.patchMe({'notify': notify}))['notify']);
      await _cache();
    } catch (e) {
      muted = oldMuted;
      kinds = oldKinds;
      notifyListeners();
      rethrow;
    }
  }

  Future<void> _cache() async {
    try {
      final p = await SharedPreferences.getInstance();
      await p.setBool(_kMuted, muted);
      await p.setStringList(_kKinds, kinds.toList());
    } catch (_) {}
  }
}
