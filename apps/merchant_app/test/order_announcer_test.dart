import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:merchant_app/listen_service.dart';

/// 新单提示音的节奏(动效规范 07):「叮」两声,**第一声播完**再隔 600ms 响第二声;
/// 播放失败时退回系统提示音,两声照样有。
///
/// 测试环境里没有播放器插件,所以用 [OrderAnnouncer.custom] 换掉「播一声」
/// 和「播完了」—— 真播放器的这两件事就是 AudioPlayer 的 play 和 onPlayerComplete。
/// 时间用 testWidgets 的假时钟推(`t.pump(时长)`)。
void main() {
  /// 截下平台通道,数系统提示音和震动
  List<String> hookPlatform(WidgetTester t) {
    final calls = <String>[];
    t.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      calls.add(call.method);
      return null;
    });
    addTearDown(() => t.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    return calls;
  }

  testWidgets('两声:第一声播完隔 600ms 再响第二声,一轮只震一次', (t) async {
    final calls = hookPlatform(t);
    var played = 0;
    final done = StreamController<void>.broadcast();
    final a = OrderAnnouncer.custom(
        playOnce: () async => played++, completions: done.stream);
    a.announce(times: 2);
    await t.pump();
    expect(played, 1);
    // 第一声还没播完:不许叠上第二声
    await t.pump(const Duration(seconds: 2));
    expect(played, 1);
    done.add(null); // 第一声播完
    await t.pump(const Duration(milliseconds: 599));
    expect(played, 1);
    await t.pump(const Duration(milliseconds: 1));
    expect(played, 2);
    // 第二声播完:这一轮就结束了
    done.add(null);
    await t.pump(const Duration(seconds: 2));
    expect(played, 2);
    expect(calls.where((c) => c == 'HapticFeedback.vibrate'), hasLength(1));
    a.dispose();
  });

  testWidgets('播放失败:系统提示音照样两声,间隔 600ms', (t) async {
    final calls = hookPlatform(t);
    final a = OrderAnnouncer.custom(
        playOnce: () async => throw Exception('no player'),
        completions: const Stream.empty());
    a.announce(times: 2);
    await t.pump();
    expect(calls.where((c) => c == 'SystemSound.play'), hasLength(1));
    await t.pump(const Duration(milliseconds: 600));
    expect(calls.where((c) => c == 'SystemSound.play'), hasLength(2),
        reason: '播放器坏了也要「至少响」,而且照样是两声');
    a.dispose();
  });

  testWidgets('新的一轮进来,上一轮还没响的第二声作废 —— 不叠音', (t) async {
    hookPlatform(t);
    var played = 0;
    final done = StreamController<void>.broadcast();
    final a = OrderAnnouncer.custom(
        playOnce: () async => played++, completions: done.stream);
    a.announce(times: 2);
    await t.pump();
    done.add(null);
    await t.pump();
    // 间隔里又来了新单:重新从第一声起
    a.announce(times: 2);
    await t.pump(const Duration(seconds: 1));
    expect(played, 2, reason: '上一轮排着的第二声不该再响');
    a.dispose();
  });

  testWidgets('住宿接单页照旧一声(默认 times = 1)', (t) async {
    hookPlatform(t);
    var played = 0;
    final done = StreamController<void>.broadcast();
    final a = OrderAnnouncer.custom(
        playOnce: () async => played++, completions: done.stream);
    a.announce();
    await t.pump();
    done.add(null);
    await t.pump(const Duration(seconds: 2));
    expect(played, 1);
    a.dispose();
  });
}
