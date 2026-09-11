/// 听单可靠性:语音播报 + Android 前台服务保活。
///
/// 商家的真实使用场景是手机插电放柜台、屏幕常灭。要做到"锁屏不丢单":
///  1. 前台服务(常驻通知)把进程保在前台优先级,WebSocket/轮询/定时器持续运行
///  2. 新单用真人语音循环播报,比系统提示音更能穿透后厨噪音
///  3. 引导商家把 App 加入电池优化白名单(国产 ROM 杀后台的主要豁免通道)
library;

import 'dart:async';
import 'dart:io' show Platform;

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:superz_shared/superz_shared.dart';

bool get _isAndroid => !kIsWeb && Platform.isAndroid;

/// 新单语音播报。播放失败时退回系统提示音,保证"至少响一声"。
///
/// [announce] 的 `times`:外卖新单按动效规范 07 响**两声**,两声之间隔 600ms
/// (第一声播完再等 600ms,不叠音)。住宿接单页照旧一声。
class OrderAnnouncer {
  factory OrderAnnouncer() {
    // 播放器第一次要响时才建:一建出来就去初始化原生播放插件,
    // 一单没来的时候不必先占着
    AudioPlayer? player;
    StreamSubscription<void>? relay;
    final completions = StreamController<void>.broadcast();
    AudioPlayer ensure() {
      final existing = player;
      if (existing != null) return existing;
      final p = AudioPlayer();
      relay = p.onPlayerComplete.listen(completions.add);
      return player = p;
    }
    return OrderAnnouncer.custom(
      playOnce: () async {
        final p = ensure();
        await p.stop(); // 上一遍没播完就来了新单:重头播,不叠音
        await p.play(AssetSource('new_order.m4a'));
      },
      completions: completions.stream,
      onDispose: () {
        relay?.cancel();
        completions.close();
        player?.dispose();
      },
    );
  }

  /// 把「播一声」和「播完了」换成别的实现 —— 测试里没有播放器插件,
  /// 两声的节奏只能这样量
  OrderAnnouncer.custom({
    required Future<void> Function() playOnce,
    required Stream<void> completions,
    VoidCallback? onDispose,
  })  : _play = playOnce,
        _onDispose = onDispose {
    _done = completions.listen((_) => _next());
  }

  final Future<void> Function() _play;
  final VoidCallback? _onDispose;
  late final StreamSubscription<void> _done;

  /// 两声之间的间隔(规范 07)
  static const gap = Duration(milliseconds: 600);

  /// 这一轮还剩几声
  int _left = 0;

  /// 排队中的下一声。**只能有一个**,新的一轮进来先取消上一轮剩下的
  Timer? _gapTimer;

  Future<void> announce({int times = 1}) async {
    HapticFeedback.vibrate();
    _gapTimer?.cancel();
    _left = times - 1;
    await _playOnce();
  }

  void _next() {
    if (_left <= 0) return;
    _left--;
    _gapTimer?.cancel();
    _gapTimer = Timer(gap, _playOnce);
  }

  Future<void> _playOnce() async {
    try {
      await _play();
    } catch (_) {
      SystemSound.play(SystemSoundType.alert);
      // 播放失败就收不到「播完」事件,第二声按间隔直接排上
      _next();
    }
  }

  void dispose() {
    _gapTimer?.cancel();
    _done.cancel();
    _onDispose?.call();
  }
}

/// 前台服务保活(仅 Android;iOS/桌面/web 全部静默跳过)。
class ListenKeepAlive {
  static bool _inited = false;

  static void _init() {
    if (_inited) return;
    _inited = true;
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'superz_listen_orders',
        channelName: '听单服务',
        channelDescription: '保持商家端在后台持续接收新订单',
        channelImportance: NotificationChannelImportance.LOW,
        priority: NotificationPriority.LOW,
      ),
      iosNotificationOptions: const IOSNotificationOptions(
        showNotification: false,
      ),
      foregroundTaskOptions: ForegroundTaskOptions(
        eventAction: ForegroundTaskEventAction.nothing(),
        allowWakeLock: true, // 熄屏后 CPU 不休眠,定时器/WS 才能继续跑
        allowWifiLock: true,
      ),
    );
  }

  static Future<void> start() async {
    if (!_isAndroid) return;
    _init();
    if (await FlutterForegroundTask.isRunningService) return;
    await FlutterForegroundTask.startService(
      notificationTitle: '超级赞正在听单',
      notificationText: '营业中,新订单会语音播报',
    );
  }

  static Future<void> stop() async {
    if (!_isAndroid) return;
    if (await FlutterForegroundTask.isRunningService) {
      await FlutterForegroundTask.stopService();
    }
  }

  /// 首次进入接单页时引导授权:通知权限(Android 13+)+ 电池优化白名单。
  /// 都是听单可靠性的硬前提,拒绝也不阻塞,只是下次进入再提醒。
  static Future<void> ensurePermissions(BuildContext context) async {
    if (!_isAndroid) return;
    final np = await FlutterForegroundTask.checkNotificationPermission();
    if (np != NotificationPermission.granted) {
      // 商店合规:调系统通知权限弹窗前先说明目的;拒绝不阻塞听单
      if (context.mounted &&
          await PermissionRationale.ensure(
              context, AppPermissionKind.notification,
              reason: '用于在后台接收新订单提醒(实时听单)。\n拒绝后可能错过新订单。')) {
        await FlutterForegroundTask.requestNotificationPermission();
      }
    }
    if (await FlutterForegroundTask.isIgnoringBatteryOptimizations) return;
    if (!context.mounted) return;
    final agree = await showDialog<bool>(
      context: context,
      builder: (context) => SzDialog(
        title: const Text('别让系统杀掉听单'),
        content: const Text('部分手机会自动清理后台应用,导致锁屏后收不到新订单。\n\n'
            '请在接下来的系统弹窗里允许「忽略电池优化」,'
            '并建议在系统设置中允许本应用自启动。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('暂不')),
          FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('去设置')),
        ],
      ),
    );
    if (agree == true) {
      await FlutterForegroundTask.requestIgnoreBatteryOptimization();
    }
  }
}
