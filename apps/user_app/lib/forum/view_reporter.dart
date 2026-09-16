// 浏览数上报(F5:客户端批量报展示过的帖子,服务端按人按天去重)。
//
// ## 为什么攒起来报
//
// 一屏能看见五六条,滑一分钟能过几十条。一条一个请求的话,光滑动就把
// 「每分钟 120 次」的限流(§5.10)吃光了,后面真该报的反而报不上去。
// 所以:攒着,**每 5 秒或满 50 条**发一次(50 是 `/posts/views` 的 `pids` 上限)。
//
// 去重在本地也做一遍(同一条滑回来不再报)—— 服务端按人按天去重,重复报不会多算,
// 但白白占请求配额。进程重启后集合清空,那条会再报一次,服务端照样只算一次。

import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';

/// 没登录时浏览上报带的设备号:第一次用时生成一个随机串存下来,之后一直用它。
/// 服务端只拿它按天去重(F5),不关联任何身份。
///
/// 和视频那个各存各的 key —— 两边共用一个号的话,谁清了缓存另一边的去重也跟着断。
Future<String> forumDeviceId() => _deviceId ??= () async {
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
const _deviceKey = 'forum_device_id';

/// 只给测试用:忘掉内存里缓存的设备号
@visibleForTesting
void resetForumDeviceIdForTest() => _deviceId = null;

/// 一批最多这么多条(§8.3 `POST /posts/views` 的 `pids` ≤ 50)
const int kViewBatchMax = 50;

/// 攒多久发一次
const Duration kViewFlushEvery = Duration(seconds: 5);

/// 展示过的帖子攒起来批量上报。
///
/// 页面 dispose 时调 [dispose] —— 它会把手里剩的最后一批发出去。
class ForumViewReporter {
  ForumViewReporter(this._send, {this.deviceId, Duration? every})
      : _every = every ?? kViewFlushEvery;

  /// 真正发出去的那一下。抽成参数是为了测试里不碰网络。
  final Future<void> Function(List<String> pids, String? deviceId) _send;

  /// 没登录时带上设备号,服务端按设备去重(F5)
  final String? deviceId;
  final Duration _every;

  final _pending = <String>[];
  final _seen = <String>{};
  Timer? _timer;
  bool _sending = false;
  bool _disposed = false;

  /// 这一屏露出来的帖子。占位条目不报 —— 它没内容可看。
  void saw(FPost post) => sawPid(post.unavailable ? '' : post.pid);

  void sawPid(String pid) {
    if (_disposed || pid.isEmpty || !_seen.add(pid)) return;
    _pending.add(pid);
    if (_pending.length >= kViewBatchMax) {
      unawaited(flush());
      return;
    }
    _timer ??= Timer(_every, () => unawaited(flush()));
  }

  /// 立刻把手里的发出去。发失败就丢掉这一批 —— 浏览数不是账,少一次不用补。
  Future<void> flush() async {
    _timer?.cancel();
    _timer = null;
    if (_sending || _pending.isEmpty) return;
    final batch = _pending.sublist(0, min(kViewBatchMax, _pending.length));
    _pending.removeRange(0, batch.length);
    _sending = true;
    try {
      await _send(batch, deviceId);
    } catch (_) {
      // 静默:上报失败不该弹给用户看
    } finally {
      _sending = false;
      // 一批里装不下的,接着排下一次
      if (_pending.isNotEmpty && !_disposed) _timer ??= Timer(_every, () => unawaited(flush()));
    }
  }

  void dispose() {
    _timer?.cancel();
    _timer = null;
    if (_pending.isNotEmpty) unawaited(flush());
    _disposed = true;
  }

  /// 还没发出去的条数(测试用)
  int get pendingCount => _pending.length;
}
