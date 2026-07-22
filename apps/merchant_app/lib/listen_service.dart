/// 听单可靠性:语音播报 + Android 前台服务保活。
///
/// 商家的真实使用场景是手机插电放柜台、屏幕常灭。要做到"锁屏不丢单":
///  1. 前台服务(常驻通知)把进程保在前台优先级,WebSocket/轮询/定时器持续运行
///  2. 新单用真人语音循环播报,比系统提示音更能穿透后厨噪音
///  3. 引导商家把 App 加入电池优化白名单(国产 ROM 杀后台的主要豁免通道)
library;

import 'dart:io' show Platform;

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';

bool get _isAndroid => !kIsWeb && Platform.isAndroid;

/// 新单语音播报。播放失败时退回系统提示音,保证"至少响一声"。
class OrderAnnouncer {
  final AudioPlayer _player = AudioPlayer();

  Future<void> announce() async {
    HapticFeedback.vibrate();
    try {
      await _player.stop(); // 上一遍没播完就来了新单:重头播,不叠音
      await _player.play(AssetSource('new_order.m4a'));
    } catch (_) {
      SystemSound.play(SystemSoundType.alert);
    }
  }

  void dispose() {
    _player.dispose();
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
      await FlutterForegroundTask.requestNotificationPermission();
    }
    if (await FlutterForegroundTask.isIgnoringBatteryOptimizations) return;
    if (!context.mounted) return;
    final agree = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
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
