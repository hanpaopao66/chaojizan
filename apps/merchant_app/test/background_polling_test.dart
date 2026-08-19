import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// 后台轮询节奏 —— **直接读源码断言**,不是常量比常量。
///
/// ## 这个测试防的是什么
///
/// 商家反馈「APK 后台待机发热严重」(#291)。查下来是三件事叠在一起:
///
/// 1. `ListenKeepAlive` 的前台服务带 `allowWakeLock: true` ——
///    熄屏后 CPU 不休眠。这是**故意的**,不然听不到新单;
/// 2. 三个定时器在后台照常全速跑:15 秒拉订单、30 秒拉今日统计、
///    10 秒查要不要催单 —— 每分钟 6 次网络请求,一整夜不停;
/// 3. 两个接单页此前**一个生命周期监听都没有**(用户端有 3 处、
///    骑手端 1 处,就商家端漏了)。
///
/// CPU 不许休眠 + 每 10 秒一次网络 I/O = 手机一直温着。
///
/// ## 为什么读源码而不是比常量
///
/// 第一版这个测试写成了 `expect(bgOrders, 60)` 这种常量比常量 ——
/// 谁把 `_restartTimers` 整个删掉它都是绿的,纯装饰。
///
/// 这类退化**本来就没有症状**:功能全对、日志干净、测试全绿,
/// 只是手机热、电掉得快;等商家来说的时候已经这样跑了很久。
/// 靠一个自己不会红的测试守着,等于没守。
void main() {
  // ⚠️ 在 test() 外面**不能用 expect**(会抛 OutsideTestException),
  // 所以文件不存在时直接抛 —— 效果一样是红,但报错说得清是哪个文件
  String read(String rel) {
    final f = File(rel);
    if (!f.existsSync()) {
      throw StateError('找不到 $rel —— 文件挪了要同步改这个测试');
    }
    return f.readAsStringSync();
  }

  final pages = {
    '外卖接单页': read('lib/main.dart'),
    '住宿接单页': read('lib/hotel/stay_orders_page.dart'),
  };

  group('两个接单页都要有生命周期感知', () {
    pages.forEach((name, src) {
      test('$name 混入 WidgetsBindingObserver 并注册/注销', () {
        expect(src, contains('with WidgetsBindingObserver'),
            reason: '$name 没有生命周期感知,后台定时器会全速跑');
        expect(src, contains('WidgetsBinding.instance.addObserver(this)'),
            reason: '$name 混入了但没注册,回调根本不会触发');
        expect(src, contains('WidgetsBinding.instance.removeObserver(this)'),
            reason: '$name 没注销 observer,页面销毁后还会收到回调');
      });

      test('$name 实现了 didChangeAppLifecycleState', () {
        expect(src, contains('didChangeAppLifecycleState'),
            reason: '$name 没实现生命周期回调');
        expect(src, contains('AppLifecycleState.resumed'),
            reason: '$name 没判断前台状态');
      });

      test('$name 后台轮询要跳过(WS 连着时)', () {
        // 这一句是省电的核心:WS 连着的时候轮询一条新信息都带不来
        expect(src, contains('if (!_foreground && _wsConnected) return;'),
            reason: '$name 后台没跳过重复轮询 —— 这是发热的主因');
      });
    });
  });

  group('轮询节奏', () {
    /// 从 `Duration(seconds: _foreground ? A : B)` 里抠出前后台的秒数。
    (int, int) intervals(String src) {
      final m = RegExp(r'Duration\(seconds:\s*_foreground\s*\?\s*(\d+)\s*:\s*(\d+)\)')
          .firstMatch(src);
      expect(m, isNotNull,
          reason: '找不到前后台分档的轮询间隔 —— 是不是又改回单一节奏了?');
      return (int.parse(m!.group(1)!), int.parse(m.group(2)!));
    }

    pages.forEach((name, src) {
      test('$name 后台比前台慢,且不超过每分钟一次', () {
        final (fg, bg) = intervals(src);
        expect(bg, greaterThan(fg), reason: '$name 后台轮询没比前台慢');
        expect(bg, greaterThanOrEqualTo(60),
            reason: '$name 后台轮询快于 60 秒又开始烧电了(当前 $bg 秒)');
        // 降耗不能拿前台体验换:商家盯着屏幕时新单要立刻出现
        expect(fg, lessThanOrEqualTo(20),
            reason: '$name 前台刷新慢于 20 秒,商家会觉得"单没进来"(当前 $fg 秒)');
      });
    });
  });

  group('不许动的东西', () {
    test('催单语音没有前后台分档', () {
      // 后台听不见催单 = 这个 App 白做。**故意不优化**这一条
      for (final entry in pages.entries) {
        final alertBlock = RegExp(
            r'_alertTimer = Timer\.periodic\(\s*(?:const )?Duration\(([^)]*)\)')
            .firstMatch(entry.value);
        expect(alertBlock, isNotNull, reason: '${entry.key} 找不到催单定时器');
        expect(alertBlock!.group(1), isNot(contains('_foreground')),
            reason: '${entry.key} 的催单语音被降频了 —— '
                '锁屏漏单比发热严重得多');
      }
    });

    test('前台服务(唤醒锁)本身没被删掉', () {
      // 省电不能靠"干脆别听单了"。唤醒锁是这个 App 的功能前提,
      // 要降的是白烧的轮询,不是听单能力
      for (final entry in pages.entries) {
        expect(entry.value, contains('ListenKeepAlive'),
            reason: '${entry.key} 把前台服务删了 —— 那会直接漏单');
      }
    });
  });

  test('打烊要放掉唤醒锁', () {
    // 之前是进页面就无条件 start()、只在 dispose() 才 stop() ——
    // 打烊一整晚照样握着唤醒锁轮询,关了店听到单也不能接
    final src = pages['外卖接单页']!;
    expect(src, contains('_syncKeepAlive'),
        reason: '前台服务没跟营业状态联动');
    expect(RegExp(r'_syncKeepAlive').allMatches(src).length,
        greaterThanOrEqualTo(3),
        reason: '_syncKeepAlive 要在:定义、初始化、营业开关切换 三处出现');
  });
}
