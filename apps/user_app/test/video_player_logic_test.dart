import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/video/api.dart';
import 'package:user_app/video/danmaku/danmaku_controller.dart';
import 'package:user_app/video/danmaku/layer.dart';
import 'package:user_app/video/danmaku/sheets.dart';
import 'package:user_app/video/models.dart';
import 'package:user_app/video/player/controls.dart';
import 'package:user_app/video/player/player_logic.dart';
import 'package:user_app/video/player/sz_video_controller.dart';
import 'package:user_app/video/player/sz_video_view.dart';
import 'package:video_player/video_player.dart';

/// 播放器(DEV-PROMPTS-40 #359)。
///
/// 前半是纯函数:手势判定、清晰度选择、雪碧图坐标、续播判定、播放时长累计;
/// 后半把 [SzVideoView] 真的挂起来,用假播放器([FakePlayer],不碰平台通道)和假接口(MockClient)
/// 走一遍手势、续播、切清晰度、出错重试、连播、心跳、弹幕拉取和发送 —— 这些都是接线,
/// 纯函数测得再全,接错一根线用户照样用不了。

// ---------------------------------------------------------------- 假播放器与假接口

class FakePlayer extends VideoPlayerController {
  FakePlayer(super.url, {this.fail = false, this.durationMs = 60000}) : super.networkUrl() {
    all.add(this);
  }

  static final List<FakePlayer> all = [];
  static int failNext = 0;

  /// 接下来建的播放器读出来的时长(和测试视频的 duration_ms 对上)
  static int nextDurationMs = 60000;

  final bool fail;
  final int durationMs;
  final List<String> calls = [];
  bool disposed = false;

  @override
  Future<void> initialize() async {
    calls.add('init');
    if (fail) throw Exception('网络断了');
    value = value.copyWith(
      isInitialized: true,
      duration: Duration(milliseconds: durationMs),
      size: const Size(1280, 720),
    );
  }

  @override
  Future<void> play() async {
    calls.add('play');
    value = value.copyWith(isPlaying: true, isCompleted: false);
  }

  @override
  Future<void> pause() async {
    calls.add('pause');
    value = value.copyWith(isPlaying: false);
  }

  @override
  Future<void> seekTo(Duration position) async {
    calls.add('seek:${position.inMilliseconds}');
    value = value.copyWith(position: position);
  }

  @override
  Future<void> setPlaybackSpeed(double speed) async {
    calls.add('speed:$speed');
    value = value.copyWith(playbackSpeed: speed);
  }

  @override
  Future<void> setVolume(double volume) async {
    value = value.copyWith(volume: volume);
  }

  /// 模拟播完:平台会暂停并停在结尾
  void finish() => value = value.copyWith(isPlaying: false, isCompleted: true, position: value.duration);

  @override
  Future<void> dispose() async {
    disposed = true;
    await super.dispose();
  }
}

VideoPlayerController fakeFactory(Uri url) {
  final fail = FakePlayer.failNext > 0;
  if (fail) FakePlayer.failNext--;
  return FakePlayer(url, fail: fail, durationMs: FakePlayer.nextDurationMs);
}

/// 接口假数据:记下每个请求,弹幕段 / 高能进度条 / 心跳 / 发弹幕按路径回
class FakeServer {
  final List<http.Request> requests = [];
  int? sendStatus;

  List<http.Request> hits(String pathPart, [String method = 'GET']) =>
      [for (final r in requests) if (r.method == method && r.url.path.contains(pathPart)) r];

  late final VideoApi api = VideoApi(ApiClient(
    baseUrl: 'http://test.local',
    httpClient: MockClient((req) async {
      requests.add(req);
      final path = req.url.path;
      Object? body;
      if (path.endsWith('/danmaku/density')) {
        body = {'part_id': 221, 'bucket_ms': 5000, 'counts': [0, 3, 8, 2]};
      } else if (path.contains('/parts/') && path.endsWith('/danmaku') && req.method == 'GET') {
        final seg = int.parse(req.url.queryParameters['segment'] ?? '0');
        final part = int.parse(path.split('/')[4]);
        body = {
          'part_id': part,
          'segment': seg,
          'segment_ms': 360000,
          'segments': 3,
          'allow_danmaku': true,
          'items': [
            {'id': part * 100 + seg, 'time_ms': seg * 360000 + 1000, 'mode': 1, 'color': 16777215, 'size': 25,
             'text': 'P$part 第 $seg 段', 'user_hash': 'aad60552', 'mine': false},
          ],
        };
      } else if (path.contains('/parts/') && path.endsWith('/danmaku') && req.method == 'POST') {
        if (sendStatus != null) {
          return http.Response(jsonEncode({'detail': '弹幕发得太快了,3 秒一条'}), sendStatus!,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }
        final b = jsonDecode(req.body) as Map<String, dynamic>;
        body = {'id': 900, ...b, 'user_hash': 'me000001', 'mine': true, 'created_at': '2026-09-13T02:09:39+00:00'};
      } else if (path.endsWith('/view')) {
        body = {'counted': true, 'views': 1};
      } else {
        return http.Response(jsonEncode({'detail': '没有这个接口'}), 404);
      }
      return http.Response(jsonEncode(body), 200, headers: {'content-type': 'application/json; charset=utf-8'});
    }),
  ));
}

Map<String, dynamic> videoJson({
  Map<String, dynamic>? progress,
  bool allowDanmaku = true,
  int parts = 1,
  List<int> qs = const [720, 480, 360],
  int durationMs = 60000,
}) =>
    {
      'vid': 'svTestVideo1',
      'title': '测试视频',
      'cover': '',
      'duration_ms': durationMs,
      'is_vertical': false,
      'allow_danmaku': allowDanmaku,
      'parts': [
        for (var i = 0; i < parts; i++)
          {
            'id': 221 + i,
            'idx': i,
            'title': '第 ${i + 1} P',
            'status': 'ready',
            'duration_ms': durationMs,
            'w': 1280,
            'h': 720,
            'renditions': [
              for (final q in qs)
                {'q': q, 'w': q * 16 ~/ 9, 'h': q, 'url': '/video/v1/vod/svTestVideo1/${221 + i}/$q.mp4?u=1&e=2&s=x'},
            ],
          },
      ],
      'me': progress == null
          ? null
          : {'liked': false, 'coins': 0, 'coin_max': 2, 'favorited': false, 'folder_ids': <int>[], 'progress': progress},
    };

Rendition rq(int q) => Rendition(q: q, w: q * 16 ~/ 9, h: q, url: '/$q.mp4');

void main() {
  // ================================================================ 纯函数

  group('手势判定', () {
    test('横滑一律是快进快退,竖滑按按下的位置分:左半边亮度、右半边音量(正中间算右边)', () {
      expect(classifyDrag(horizontal: true, startX: 10, width: 400), PlayerGesture.seek);
      expect(classifyDrag(horizontal: true, startX: 390, width: 400), PlayerGesture.seek);
      expect(classifyDrag(horizontal: false, startX: 10, width: 400), PlayerGesture.brightness);
      expect(classifyDrag(horizontal: false, startX: 199.9, width: 400), PlayerGesture.brightness);
      expect(classifyDrag(horizontal: false, startX: 200, width: 400), PlayerGesture.volume);
      expect(classifyDrag(horizontal: false, startX: 390, width: 400), PlayerGesture.volume);
    });

    test('单击 / 双击:300ms 内、48 像素内的第二下是双击', () {
      expect(classifyTapUp(nowMs: 1000, x: 100, y: 100), PlayerGesture.tap, reason: '第一下');
      expect(classifyTapUp(nowMs: 1250, x: 110, y: 95, lastUpMs: 1000, lastX: 100, lastY: 100),
          PlayerGesture.doubleTap);
      expect(classifyTapUp(nowMs: 1300, x: 100, y: 100, lastUpMs: 1000, lastX: 100, lastY: 100),
          PlayerGesture.doubleTap, reason: '正好 300ms 还算');
      expect(classifyTapUp(nowMs: 1301, x: 100, y: 100, lastUpMs: 1000, lastX: 100, lastY: 100), PlayerGesture.tap,
          reason: '超时了就是新的一下');
      expect(classifyTapUp(nowMs: 1100, x: 200, y: 100, lastUpMs: 1000, lastX: 100, lastY: 100), PlayerGesture.tap,
          reason: '离得太远(两根手指先后点两处)不算双击');
    });

    test('一串单击:双击之后紧跟的第三下重新算第一下;等够时限没来第二下才是单击', () {
      final s = TapSequence();
      expect(s.up(0, 50, 50), PlayerGesture.tap);
      expect(s.stillSingle(0), isTrue);
      expect(s.up(200, 52, 50), PlayerGesture.doubleTap);
      expect(s.stillSingle(0), isFalse, reason: '第一下已经被配成双击了,不能再当单击处理');
      expect(s.up(350, 50, 50), PlayerGesture.tap, reason: '第三下不会和第二下再配成双击');
      expect(s.stillSingle(350), isTrue);
    });

    test('横滑快进快退:满屏宽一滑 = min(时长, 2 分钟),夹在 0 到时长之间', () {
      expect(seekTargetMs(startMs: 10000, dx: 200, width: 400, durationMs: 60000), 40000);
      expect(seekTargetMs(startMs: 10000, dx: -400, width: 400, durationMs: 60000), 0);
      expect(seekTargetMs(startMs: 50000, dx: 400, width: 400, durationMs: 60000), 60000);
      // 30 分钟的视频,满屏一滑只走 2 分钟
      expect(seekTargetMs(startMs: 600000, dx: 400, width: 400, durationMs: 1800000), 720000);
      expect(seekTargetMs(startMs: 5000, dx: 100, width: 0, durationMs: 60000), 5000);
    });

    test('上下滑调亮度 / 音量:往上是加,滑满播放器高度 = 0 到 100%', () {
      expect(levelAfterDrag(start: 0.5, dy: -100, height: 200), 1.0);
      expect(levelAfterDrag(start: 0.5, dy: 50, height: 200), 0.25);
      expect(levelAfterDrag(start: 0.2, dy: 300, height: 200), 0.0);
      expect(levelAfterDrag(start: 0.4, dy: 10, height: 0), 0.4);
    });

    test('长按 3 倍速,松手回到选的那一档;倍速夹在 0.5–2', () {
      expect(effectiveSpeed(1.25, boosting: true), kBoostSpeed);
      expect(effectiveSpeed(1.25, boosting: false), 1.25);
      expect(clampSpeed(5), 2.0);
      expect(clampSpeed(0.1), 0.5);
      expect(speedLabel(1.0), '倍速');
      expect(speedLabel(1.25), '1.25x');
      expect(speedLabel(0.5), '0.5x');
      expect(speedLabel(2.0), '2.0x');
      expect([for (final s in kPlayerSpeeds) speedText(s)], ['0.5x', '0.75x', '1.0x', '1.25x', '1.5x', '2.0x']);
    });

    test('亮度用黑色遮罩模拟:亮度 1 不盖,0 盖 70%', () {
      expect(dimAlphaFor(1), 0);
      expect(dimAlphaFor(0), closeTo(0.7, 1e-9));
      expect(dimAlphaFor(0.5), closeTo(0.35, 1e-9));
      expect(dimAlphaFor(3), 0);
    });
  });

  group('清晰度选择', () {
    test('自动:有 720 就 720', () {
      expect(pickRendition([rq(1080), rq(720), rq(480), rq(360)])!.q, 720);
      expect(pickRendition([rq(720), rq(480), rq(360)])!.q, 720);
    });

    test('自动:没有 720 取不超过 720 的最高一档(和档位顺序无关)', () {
      expect(pickRendition([rq(480), rq(360)])!.q, 480);
      expect(pickRendition([rq(360), rq(1080), rq(480)])!.q, 480);
      expect(pickRendition([rq(360)])!.q, 360);
    });

    test('手动选过的档位优先;这个视频没有那一档就取不超过它的最高一档', () {
      final all = [rq(1080), rq(720), rq(480), rq(360)];
      expect(pickRendition(all, preferred: 1080)!.q, 1080);
      expect(pickRendition(all, preferred: 360)!.q, 360);
      expect(pickRendition([rq(720), rq(480), rq(360)], preferred: 1080)!.q, 720);
    });

    test('全都比目标高时取最低一档;一档都没有(还在转码)返回 null', () {
      expect(pickRendition([rq(1080), rq(720)], preferred: 480)!.q, 720);
      expect(pickRendition(const []), isNull);
    });
  });

  group('雪碧图坐标(SpriteInfo.cellAt)', () {
    // 10 × 10 一张,每格 1 秒,共 250 格 = 3 张(最后一张只用了一半)
    const s = SpriteInfo(intervalMs: 1000, cols: 10, rows: 10, w: 160, h: 90, count: 250, urls: ['a', 'b', 'c']);

    test('0 毫秒是第 0 张左上角', () {
      expect(s.cellAt(0), (sheet: 0, row: 0, col: 0));
      expect(s.cellAt(999), (sheet: 0, row: 0, col: 0));
      expect(s.cellAt(1000), (sheet: 0, row: 0, col: 1));
      expect(s.cellAt(-3000), (sheet: 0, row: 0, col: 0), reason: '负数当 0');
    });

    test('跨张:第 99 格是第 0 张右下角,第 100 格是第 1 张左上角', () {
      expect(s.cellAt(99000), (sheet: 0, row: 9, col: 9));
      expect(s.cellAt(100000), (sheet: 1, row: 0, col: 0));
      expect(s.cellAt(123456), (sheet: 1, row: 2, col: 3));
    });

    test('最后一格,以及超出时长的都落在最后一格', () {
      expect(s.cellAt(249000), (sheet: 2, row: 4, col: 9));
      expect(s.cellAt(9999999), (sheet: 2, row: 4, col: 9));
    });

    test('没有缩略图、或者张数对不上时返回 null(不画,不崩)', () {
      const none = SpriteInfo(intervalMs: 1000, cols: 10, rows: 10, w: 160, h: 90, count: 0, urls: []);
      expect(none.cellAt(0), isNull);
      const short = SpriteInfo(intervalMs: 1000, cols: 10, rows: 10, w: 160, h: 90, count: 250, urls: ['a', 'b']);
      expect(short.cellAt(249000), isNull);
      expect(short.cellAt(150000), (sheet: 1, row: 5, col: 0));
    });

    test('对齐值:按它把放大后的整张图摆进一格大小的框,露出来的正好是那一格', () {
      expect(spriteAlignment(col: 0, row: 0, cols: 10, rows: 10), (x: -1.0, y: -1.0));
      expect(spriteAlignment(col: 9, row: 9, cols: 10, rows: 10), (x: 1.0, y: 1.0));
      expect(spriteAlignment(col: 0, row: 0, cols: 1, rows: 1), (x: 0.0, y: 0.0));
      // Align 的摆法:子节点左上角 = (框 − 子) × (对齐 + 1) / 2。框 = 一格,子 = cols 格
      const cell = 160.0;
      for (var col = 0; col < 10; col++) {
        final a = spriteAlignment(col: col, row: 0, cols: 10, rows: 10);
        final left = (cell - cell * 10) * (a.x + 1) / 2;
        expect(left, closeTo(-col * cell, 1e-9), reason: '第 $col 列');
      }
    });

    test('缩略图大小保持一格的宽高比(竖屏视频的格子是瘦高的)', () {
      expect(spriteThumbSize(s), (w: 160.0, h: 90.0));
      const tall = SpriteInfo(intervalMs: 1000, cols: 10, rows: 10, w: 160, h: 284, count: 1, urls: ['a']);
      final t = spriteThumbSize(tall);
      expect(t.h, closeTo(90, 1e-9));
      expect(t.w, closeTo(160 * 90 / 284, 1e-9));
    });
  });

  group('续播判定', () {
    VProgress p(int idx, int pos, [int dur = 60000]) => VProgress(partIdx: idx, positionMs: pos, durationMs: dur);

    test('是这一 P、进度在 5 秒到结尾前 5 秒之间才跳', () {
      expect(resumePositionMs(p(0, 20000), partIdx: 0, durationMs: 60000), 20000);
      expect(resumePositionMs(p(0, 5000), partIdx: 0, durationMs: 60000), 5000);
      expect(resumePositionMs(p(0, 55000), partIdx: 0, durationMs: 60000), 55000);
    });

    test('开头 5 秒内、结尾 5 秒内、别的 P、没有历史:都不跳', () {
      expect(resumePositionMs(p(0, 4999), partIdx: 0, durationMs: 60000), isNull);
      expect(resumePositionMs(p(0, 55001), partIdx: 0, durationMs: 60000), isNull);
      expect(resumePositionMs(p(1, 20000), partIdx: 0, durationMs: 60000), isNull);
      expect(resumePositionMs(null, partIdx: 0, durationMs: 60000), isNull);
    });

    test('播放器读不到时长时用历史里记的时长', () {
      expect(resumePositionMs(p(0, 20000, 30000), partIdx: 0, durationMs: 0), 20000);
      expect(resumePositionMs(p(0, 26000, 30000), partIdx: 0, durationMs: 0), isNull);
      expect(resumePositionMs(p(0, 20000, 0), partIdx: 0, durationMs: 0), isNull);
    });
  });

  test('时间格式:分钟补两位,超过一小时带小时', () {
    expect(playerClock(0), '00:00');
    expect(playerClock(65000), '01:05');
    expect(playerClock(3723000), '1:02:03');
    expect(playerClock(-10), '00:00');
  });

  test('播放时长只算播放位置往前走的:跳进度、暂停都不算', () {
    final a = PlayAccumulator();
    for (var t = 0; t <= 5000; t += 100) {
      a.onPosition(t, playing: true);
    }
    expect(a.playedMs, 5000);
    a.onPosition(40000, playing: true); // 没打招呼的跳进度(比如别处 seek 了)
    expect(a.playedMs, 5000);
    a.onSeek(10000);
    a.onPosition(10300, playing: true);
    expect(a.playedMs, 5300);
    a.onPosition(10600, playing: false); // 暂停 / 缓冲
    a.onPosition(10900, playing: true);
    expect(a.playedMs, 5600);
    a.reset();
    expect(a.playedMs, 0);
  });

  // ================================================================ 挂起来跑

  group('SzVideoView 接线', () {
    late FakeServer server;

    setUpAll(() {
      PackageInfo.setMockInitialValues(
        appName: 'user_app',
        packageName: 'com.superz.user',
        version: '0.1.0',
        buildNumber: '1',
        buildSignature: '',
      );
    });

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      DanmakuController.resetSharedForTest();
      resetVideoDeviceIdForTest();
      FakePlayer.all.clear();
      FakePlayer.failNext = 0;
      FakePlayer.nextDurationMs = 60000;
      server = FakeServer();
    });

    SzVideoController make(Map<String, dynamic> json) =>
        SzVideoController(video: VideoDetail.fromJson(json), playerFactory: fakeFactory, api: server.api);

    Future<SzVideoController> mount(WidgetTester tester, Map<String, dynamic> json) async {
      final c = make(json);
      await tester.pumpWidget(MaterialApp(
        theme: brandTheme(Brightness.light),
        home: Scaffold(
          body: Column(children: [
            SzVideoView(controller: c, onBack: () {}, title: '测试视频'),
            DanmakuSendBar(controller: c),
          ]),
        ),
      ));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      return c;
    }

    Future<void> unmount(WidgetTester tester, SzVideoController c) async {
      await tester.pumpWidget(const SizedBox());
      c.dispose();
      // 进出全屏时挂着的「挪完接着播」还有两拍延时,等它们走完(dispose 之后它们什么也不做)
      await tester.pump(const Duration(seconds: 1));
    }

    FakePlayer player() => FakePlayer.all.last;

    double uiOpacity(WidgetTester tester) => tester
        .widget<AnimatedOpacity>(
            find.ancestor(of: find.byTooltip('更多'), matching: find.byType(AnimatedOpacity)).first)
        .opacity;

    Offset center(WidgetTester tester) => tester.getCenter(find.byType(SzVideoView));

    testWidgets('打开:自动清晰度选 720、自动播放、拉当前段和下一段弹幕与高能进度条', (tester) async {
      FakePlayer.nextDurationMs = 780000; // 13 分钟 = 3 段
      final c = await mount(tester, videoJson(durationMs: 780000));
      expect(player().dataSource, contains('/221/720.mp4'));
      expect(c.quality!.q, 720);
      expect(c.autoQuality, isTrue);
      expect(c.playing, isTrue);
      expect(server.hits('/danmaku').map((r) => r.url.queryParameters['segment']).whereType<String>(),
          containsAll(['0', '1']));
      expect(server.hits('/danmaku').where((r) => r.url.queryParameters['segment'] == '2'), isEmpty,
          reason: '只预取当前段和下一段');
      expect(server.hits('/danmaku/density'), hasLength(1));
      expect(c.danmaku.items.map((d) => d.text), containsAll(['P221 第 0 段', 'P221 第 1 段']));
      expect(find.byType(DanmakuLayer), findsOneWidget);

      // 播到第 7 分钟(第 1 段):补拉第 2 段
      await c.seekTo(const Duration(minutes: 7));
      await tester.pump();
      expect(server.hits('/danmaku').where((r) => r.url.queryParameters['segment'] == '2'), hasLength(1));
      await unmount(tester, c);
    });

    testWidgets('续播:上次看到 20 秒 → 打开就跳过去并提示,点「从头看」回到 0', (tester) async {
      final c = await mount(tester, videoJson(progress: {'part_idx': 0, 'position_ms': 20000, 'duration_ms': 60000}));
      expect(player().calls, contains('seek:20000'));
      expect(c.resumeHintMs, 20000);
      expect(find.text('上次看到 00:20'), findsOneWidget);
      await tester.tap(find.text('从头看'));
      await tester.pump();
      expect(c.position, Duration.zero);
      expect(c.resumeHintMs, isNull);
      expect(find.text('上次看到 00:20'), findsNothing);
      await unmount(tester, c);
    });

    testWidgets('续播:进度在开头 5 秒内不跳、不提示;提示 6 秒后自己消失', (tester) async {
      final c = await mount(tester, videoJson(progress: {'part_idx': 0, 'position_ms': 3000, 'duration_ms': 60000}));
      expect(player().calls.where((x) => x.startsWith('seek:')), isEmpty);
      expect(c.resumeHintMs, isNull);
      await unmount(tester, c);

      final d = await mount(tester, videoJson(progress: {'part_idx': 0, 'position_ms': 30000, 'duration_ms': 60000}));
      expect(find.text('上次看到 00:30'), findsOneWidget);
      await tester.pump(const Duration(seconds: 7));
      expect(find.text('上次看到 00:30'), findsNothing);
      await unmount(tester, d);
    });

    testWidgets('单击显示 / 隐藏控件;播放中 3 秒不动自动隐藏;双击暂停 / 播放', (tester) async {
      final c = await mount(tester, videoJson());
      expect(uiOpacity(tester), 1);
      await tester.pump(const Duration(milliseconds: 3200));
      expect(uiOpacity(tester), 0, reason: '播放中 3 秒自动隐藏');

      await tester.tapAt(center(tester));
      await tester.pump(const Duration(milliseconds: kDoubleTapMs + 10));
      expect(uiOpacity(tester), 1, reason: '单击叫出控件');
      await tester.tapAt(center(tester));
      await tester.pump(const Duration(milliseconds: kDoubleTapMs + 10));
      expect(uiOpacity(tester), 0, reason: '再单击收起');

      await tester.tapAt(center(tester));
      await tester.pump(const Duration(milliseconds: 40));
      await tester.tapAt(center(tester));
      await tester.pump();
      expect(c.playing, isFalse, reason: '双击暂停');
      await tester.pump(const Duration(seconds: 4));
      expect(uiOpacity(tester), 1, reason: '暂停时控件常驻');
      await tester.tapAt(center(tester));
      await tester.pump(const Duration(milliseconds: 40));
      await tester.tapAt(center(tester));
      await tester.pump();
      expect(c.playing, isTrue, reason: '再双击接着播');
      await unmount(tester, c);
    });

    testWidgets('长按 3 倍速,松手回到原来的倍速', (tester) async {
      final c = await mount(tester, videoJson());
      await c.setSpeed(1.25);
      final g = await tester.startGesture(center(tester));
      await tester.pump(const Duration(milliseconds: 600));
      expect(c.boosting, isTrue);
      expect(player().value.playbackSpeed, kBoostSpeed);
      expect(find.text('3 倍速播放中'), findsOneWidget);
      await g.up();
      await tester.pump();
      expect(c.boosting, isFalse);
      expect(player().value.playbackSpeed, 1.25);
      expect(c.speed, 1.25);
      await unmount(tester, c);
    });

    testWidgets('横滑快进快退:滑动时不跳、松手才跳;左边竖滑调亮度、右边竖滑调音量', (tester) async {
      final c = await mount(tester, videoJson());
      final box = tester.getRect(find.byType(SzVideoView));
      // 半屏宽 = 时长(1 分钟)的一半
      final g = await tester.startGesture(box.center);
      await g.moveBy(Offset(box.width / 4, 0));
      await g.moveBy(Offset(box.width / 4, 0));
      await tester.pump();
      expect(c.position, Duration.zero, reason: '滑的过程中只显示目标时间');
      expect(find.textContaining('00:30 / 01:00'), findsWidgets);
      await g.up();
      await tester.pump();
      expect(c.position.inMilliseconds, closeTo(30000, 200));

      await tester.dragFrom(Offset(box.left + box.width * 0.25, box.center.dy), Offset(0, box.height / 2));
      await tester.pump();
      expect(c.brightness, closeTo(0.5, 0.02), reason: '左边往下滑半个高度,亮度降一半');
      expect(c.volume, 1.0);

      await tester.dragFrom(Offset(box.left + box.width * 0.75, box.center.dy), Offset(0, box.height / 4));
      await tester.pump();
      expect(c.volume, closeTo(0.75, 0.02));
      expect(player().value.volume, closeTo(0.75, 0.02), reason: '音量真的设到了播放器上');
      await unmount(tester, c);
    });

    testWidgets('控件露出来时,从顶栏 / 底栏的空白处起手也能滑(只有按钮挡手势)', (tester) async {
      final c = await mount(tester, videoJson());
      expect(uiOpacity(tester), 1, reason: '刚打开控件是露着的');
      final box = tester.getRect(find.byType(SzVideoView));
      // 顶栏中间那一溜(返回键和「更多」之间)往下滑半个高度
      await tester.dragFrom(Offset(box.left + box.width * 0.25, box.top + 20), Offset(0, box.height / 2));
      await tester.pump();
      expect(c.brightness, closeTo(0.5, 0.02));
      // 底栏的时间文字上起手往上滑,右半边是音量
      final time = tester.getCenter(find.text('00:00 / 01:00'));
      await tester.dragFrom(time, Offset(0, -box.height / 4));
      await tester.pump();
      expect(c.volume, 1.0, reason: '音量本来就满,往上滑还是满');
      await tester.dragFrom(time, Offset(0, box.height / 8));
      await tester.pump();
      expect(c.volume, lessThan(1.0), reason: '往下滑音量降下来,说明时间文字没把手势吃掉');
      await unmount(tester, c);
    });

    testWidgets('切清晰度:保持进度、旧的释放、记住选择(下次打开还用它);切回自动', (tester) async {
      final c = await mount(tester, videoJson());
      await c.seekTo(const Duration(seconds: 12));
      final old = player();
      await c.setQuality(c.qualities.firstWhere((r) => r.q == 480));
      await tester.pump();
      expect(player(), isNot(same(old)));
      expect(player().dataSource, contains('/480.mp4'));
      expect(player().calls, contains('seek:12000'));
      expect(player().value.isPlaying, isTrue, reason: '原来在播,换过去接着播');
      expect(old.disposed, isTrue);
      expect(c.quality!.q, 480);
      expect(find.text('已切换到 480P 标清'), findsOneWidget);
      expect((await SharedPreferences.getInstance()).getInt(SzVideoController.qualityKey), 480);
      await unmount(tester, c);

      final again = await mount(tester, videoJson());
      expect(again.quality!.q, 480, reason: '记住了用户的选择');
      await again.setAutoQuality();
      await tester.pump();
      expect(again.quality!.q, 720);
      expect((await SharedPreferences.getInstance()).getInt(SzVideoController.qualityKey), 0);
      await unmount(tester, again);
    });

    testWidgets('「更多」面板里选清晰度和倍速', (tester) async {
      final c = await mount(tester, videoJson());
      await tester.tap(find.byTooltip('更多'));
      await tester.pump();
      expect(find.text('自动(720P)'), findsOneWidget);
      await tester.tap(find.text('360P'));
      await tester.pump();
      expect(c.quality!.q, 360);
      await tester.tap(find.byTooltip('更多'));
      await tester.pump();
      await tester.tap(find.text('1.5x'));
      await tester.pump();
      expect(c.speed, 1.5);
      expect(player().value.playbackSpeed, 1.5);
      await unmount(tester, c);
    });

    testWidgets('网络错误:显示「加载失败,点击重试」,点一下重新加载并接着播', (tester) async {
      FakePlayer.failNext = 1;
      final c = await mount(tester, videoJson());
      expect(c.error, isNotNull);
      expect(find.text('加载失败,点击重试'), findsOneWidget);
      await tester.tap(find.text('加载失败,点击重试'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(c.error, isNull);
      expect(c.playing, isTrue);
      expect(find.text('加载失败,点击重试'), findsNothing);
      await unmount(tester, c);
    });

    testWidgets('一 P 播完调 onPartEnded(只调一次);往回拖不会再报;有下一 P 时给「下一 P」', (tester) async {
      final c = await mount(tester, videoJson(parts: 2));
      final ended = <int>[];
      c.onPartEnded = ended.add;
      await tester.pump(const Duration(milliseconds: 3200));
      expect(uiOpacity(tester), 0, reason: '播着的时候控件已经自己藏起来了');
      player().finish();
      await tester.pump();
      expect(ended, [0]);
      expect(c.ended, isTrue);
      expect(uiOpacity(tester), 1, reason: '播完了控件要回来,不然停在最后一帧不知道是卡了还是完了');
      expect(find.text('重播'), findsOneWidget);
      expect(find.text('下一 P'), findsOneWidget);

      await c.seekTo(const Duration(seconds: 10));
      await tester.pump();
      expect(ended, [0], reason: '播完后往回拖,isCompleted 还没清,不能当成又播完了一次');
      expect(c.ended, isFalse);

      await c.switchPart(1);
      await tester.pump();
      expect(c.partIndex, 1);
      expect(player().dataSource, contains('/222/720.mp4'));
      expect(c.danmaku.items, isNotEmpty);
      expect(c.danmaku.items.every((d) => d.text.startsWith('P222')), isTrue, reason: '换 P 清空旧弹幕');
      await unmount(tester, c);
    });

    testWidgets('播放心跳:播着每 15 秒一次、暂停不报、关掉时再报一次;没登录带 device_id', (tester) async {
      final c = await mount(tester, videoJson());
      await tester.pump(const Duration(seconds: 16));
      expect(server.hits('/view', 'POST'), hasLength(1));
      await c.pause();
      await tester.pump(const Duration(seconds: 31));
      expect(server.hits('/view', 'POST'), hasLength(1), reason: '暂停不报');
      await unmount(tester, c);
      final views = server.hits('/view', 'POST');
      expect(views, hasLength(2), reason: '关掉时再报一次');
      final body = jsonDecode(views.last.body) as Map<String, dynamic>;
      expect(body['part_id'], 221);
      expect(body.containsKey('position_ms'), isTrue);
      expect(body.containsKey('played_ms'), isTrue);
      expect((body['device_id'] as String).length, 32);
      expect((await SharedPreferences.getInstance()).getString('video_device_id'), body['device_id']);
    });

    testWidgets('发弹幕:接口回来的那条立即进列表(mine、带流水号);失败抛出服务端的 detail', (tester) async {
      final c = await mount(tester, videoJson());
      final d = await c.danmaku.send(timeMs: 1500, text: '前排', color: 0xFE0302);
      await tester.pump();
      expect(d.mine, isTrue);
      expect(c.danmaku.sentSeq, 1);
      expect(c.danmaku.sentSince(0).single.id, 900);
      expect(c.danmaku.visible.map((x) => x.id), contains(900));
      final posted = jsonDecode(server.hits('/danmaku', 'POST').single.body) as Map<String, dynamic>;
      expect(posted, {'time_ms': 1500, 'text': '前排', 'mode': 1, 'color': 0xFE0302, 'size': 25});

      server.sendStatus = 429;
      await expectLater(
        c.danmaku.send(timeMs: 2000, text: '再来'),
        throwsA(isA<ApiException>().having((e) => e.message, 'message', '弹幕发得太快了,3 秒一条')),
      );
      await unmount(tester, c);
    });

    testWidgets('弹幕开关:关了弹幕层就不画;UP 主关了弹幕既不拉也不给发', (tester) async {
      final c = await mount(tester, videoJson());
      expect(find.byType(DanmakuLayer), findsOneWidget);
      await tester.tap(find.byTooltip('关闭弹幕').last);
      await tester.pump();
      expect(c.danmaku.settings.enabled, isFalse);
      expect(find.byType(DanmakuLayer), findsNothing);
      await unmount(tester, c);

      server.requests.clear();
      final off = await mount(tester, videoJson(allowDanmaku: false));
      expect(find.text('UP 主关闭了弹幕'), findsOneWidget);
      expect(find.byType(DanmakuLayer), findsNothing);
      expect(server.hits('/danmaku'), isEmpty);
      await unmount(tester, off);
    });

    testWidgets('拖进度条:拖的时候不跳、显示目标时间,松手才跳', (tester) async {
      final c = await mount(tester, videoJson());
      final bar = tester.getRect(find.byType(PlayerProgressBar));
      final g = await tester.startGesture(Offset(bar.left + 2, bar.center.dy));
      await g.moveBy(Offset(bar.width / 4, 0));
      await g.moveBy(Offset(bar.width / 4, 0));
      await tester.pump();
      expect(c.position, Duration.zero);
      await g.up();
      await tester.pump();
      expect(c.position.inMilliseconds, closeTo(30000, 600));
      await unmount(tester, c);
    });

    testWidgets('进出全屏时网页版的 <video> 会被浏览器停一下:挪完接着播;用户自己按了暂停就不动', (tester) async {
      final c = await mount(tester, videoJson());
      unawaited(c.keepPlayingAcrossViewChange());
      // 浏览器把元素暂停了(元素离开文档),不是用户按的
      player().value = player().value.copyWith(isPlaying: false);
      await tester.pump(const Duration(milliseconds: 350));
      expect(c.playing, isTrue);

      unawaited(c.keepPlayingAcrossViewChange());
      await c.pause();
      await tester.pump(const Duration(seconds: 1));
      expect(c.playing, isFalse, reason: '用户自己暂停的,不能给他又播起来');
      await unmount(tester, c);
    });

    testWidgets('全屏:推一个全屏页(顶栏有标题和返回),锁上后双击不暂停,返回回到原页', (tester) async {
      final c = await mount(tester, videoJson());
      await tester.tap(find.byTooltip('全屏'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(c.fullscreen, isTrue);
      expect(find.text('测试视频'), findsOneWidget);
      expect(find.byTooltip('退出全屏'), findsOneWidget);

      await tester.tap(find.byTooltip('锁定'));
      await tester.pump();
      final mid = tester.getCenter(find.byType(Scaffold).last);
      await tester.tapAt(mid);
      await tester.pump(const Duration(milliseconds: 40));
      await tester.tapAt(mid);
      await tester.pump();
      expect(c.playing, isTrue, reason: '锁着的时候双击不暂停');
      expect(find.byTooltip('更多'), findsNothing, reason: '锁着只剩解锁按钮');
      await tester.tap(find.byTooltip('解锁'));
      await tester.pump();

      await tester.tap(find.byTooltip('退出全屏'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(c.fullscreen, isFalse);
      expect(find.byType(SzVideoView), findsOneWidget);
      await unmount(tester, c);
    });
  });
}
