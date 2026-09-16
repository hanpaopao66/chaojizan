// 播放器逻辑(DEV-PROMPTS-41 §9、§5.5):队列、三种播放模式、插到下一首、
// 收听毫秒数按实听算、播放地址过期自动重签。
//
// 音频后端换成假的 —— 线上那个是平台通道,widget 测试里根本没有那条通道,
// 于是这些**纯逻辑**的事一条也写不了断言(见 music_player.dart 顶上的说明)。
import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:user_app/music/api.dart';
import 'package:user_app/music/models.dart';
import 'package:user_app/music/player/music_player.dart';

/// 假后端:记下被要求播的地址,位置和播完由测试自己喂。
class FakeBackend implements MusicAudioBackend {
  final _pos = StreamController<Duration>.broadcast();
  final _dur = StreamController<Duration>.broadcast();
  final _done = StreamController<void>.broadcast();
  final _err = StreamController<Object>.broadcast();

  /// 依次播过的地址
  final List<String> played = [];
  final List<Duration> seeks = [];
  int pauses = 0;
  int resumes = 0;
  int stops = 0;

  /// 命中这些片段的地址一律播不了(模拟签名过期被挡)
  final Set<String> broken = {};

  @override
  Stream<Duration> get onPosition => _pos.stream;
  @override
  Stream<Duration> get onDuration => _dur.stream;
  @override
  Stream<void> get onComplete => _done.stream;
  @override
  Stream<Object> get onError => _err.stream;

  @override
  Future<void> play(String url) async {
    if (broken.any(url.contains)) throw Exception('403');
    played.add(url);
  }

  @override
  Future<void> pause() async => pauses++;
  @override
  Future<void> resume() async => resumes++;
  @override
  Future<void> stop() async => stops++;
  @override
  Future<void> seek(Duration to) async {
    seeks.add(to);
    _at = to.inMilliseconds;
  }

  @override
  Future<void> dispose() async {}

  int _at = 0;

  /// 喂一条位置事件并等它被处理完
  Future<void> tick(int ms) async {
    _at = ms;
    _pos.add(Duration(milliseconds: ms));
    await pumpEventQueue();
  }

  /// 一路播到 [ms]。真播放器大约 200 毫秒报一次位置,这里按秒喂 ——
  /// 一步跨过去的话播放器那边会当成「有人拖了进度条」,本来就不该算听过。
  Future<void> playTo(int ms, {int step = 1000}) async {
    var at = _at;
    while (at + step < ms) {
      at += step;
      await tick(at);
    }
    await tick(ms);
  }

  Future<void> emitDuration(int ms) async {
    _dur.add(Duration(milliseconds: ms));
    await pumpEventQueue();
  }

  Future<void> complete() async {
    _done.add(null);
    await pumpEventQueue();
  }

  Future<void> fail(Object e) async {
    _err.add(e);
    await pumpEventQueue();
  }
}

/// 记下所有请求的假接口;`/stream` 每次签一个新地址(第几次签写在地址里)。
class Recorder {
  final List<({String method, String path, Map<String, dynamic> body})> calls = [];
  int signs = 0;

  /// 这些歌的 hq 是空的(源码率低于 192k,§4 M4)
  final Set<String> noHq = {};

  MusicApi build() => MusicApi(ApiClient(
        baseUrl: 'http://test.local',
        httpClient: MockClient((req) async {
          final body = req.body.isEmpty ? <String, dynamic>{} : jsonDecode(req.body) as Map<String, dynamic>;
          calls.add((method: req.method, path: req.url.path, body: body));
          if (req.url.path.endsWith('/stream')) {
            signs++;
            final tid = req.url.pathSegments[req.url.pathSegments.length - 2];
            return http.Response(
              jsonEncode({
                'std': '/music/v1/stream/$tid/std.m4a?s=sig$signs',
                'hq': noHq.contains(tid) ? null : '/music/v1/stream/$tid/hq.m4a?s=sig$signs',
                'expires_at': DateTime.now().add(const Duration(hours: 6)).toIso8601String(),
              }),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          return http.Response(jsonEncode({'counted': true}), 200,
              headers: {'content-type': 'application/json; charset=utf-8'});
        }),
      ));

  List<({String method, String path, Map<String, dynamic> body})> get plays =>
      [for (final c in calls) if (c.path.endsWith('/play')) c];
}

MTrack track(String tid, {int durationMs = 200000, String? title}) =>
    MTrack.fromJson({'tid': tid, 'title': title ?? '歌 $tid', 'duration_ms': durationMs});

void main() {
  // package_info_plus 在测试环境没有平台通道,不铺好的话第一个请求永远不返回
  setUpAll(() {
    TestWidgetsFlutterBinding.ensureInitialized();
    PackageInfo.setMockInitialValues(
      appName: 'user_app',
      packageName: 'com.superz.user',
      version: '0.1.0',
      buildNumber: '1',
      buildSignature: '',
    );
  });

  setUp(() => SharedPreferences.setMockInitialValues({}));

  late FakeBackend be;
  late Recorder rec;
  late MusicPlayer p;

  MusicPlayer make() {
    be = FakeBackend();
    rec = Recorder();
    return p = MusicPlayer(backend: be, api: rec.build());
  }

  Future<void> playThree() async {
    make();
    await p.playContext([track('mt1'), track('mt2'), track('mt3')], contextKey: 'playlist:mpX');
  }

  group('队列', () {
    test('按上下文播:第一首开播,队列和上下文都记下', () async {
      await playThree();
      expect(p.queue.length, 3);
      expect(p.index, 0);
      expect(p.current!.tid, 'mt1');
      expect(p.playing, isTrue);
      expect(p.playContextKey, 'playlist:mpX');
      expect(be.played.single, contains('mt1'));
    });

    test('从中间开播', () async {
      make();
      await p.playContext([track('mt1'), track('mt2'), track('mt3')], start: 2);
      expect(p.current!.tid, 'mt3');
    });

    test('start 越界时夹回范围内,不崩', () async {
      make();
      await p.playContext([track('mt1'), track('mt2')], start: 99);
      expect(p.index, 1);
    });

    test('同一首歌在队列里只留一条', () async {
      make();
      await p.playContext([track('mt1'), track('mt2'), track('mt1')]);
      expect(p.queue.map((t) => t.tid).toList(), ['mt1', 'mt2']);
    });

    test('空队列进来什么也不做', () async {
      make();
      await p.playContext([]);
      expect(p.hasTrack, isFalse);
      expect(be.played, isEmpty);
    });

    test('加到队尾去重,不动正在放的那首', () async {
      await playThree();
      p.addToQueue([track('mt3'), track('mt9')]);
      expect(p.queue.map((t) => t.tid).toList(), ['mt1', 'mt2', 'mt3', 'mt9']);
      expect(p.current!.tid, 'mt1');
    });

    test('移掉别的位置:正在放的不受影响,下标跟着挪', () async {
      await playThree();
      await p.playAt(2); // 在放 mt3
      await p.removeAt(0); // 移掉前面的 mt1
      expect(p.queue.map((t) => t.tid).toList(), ['mt2', 'mt3']);
      expect(p.current!.tid, 'mt3');
      expect(p.index, 1);
    });

    test('移掉正在放的那首:顶上来的那首接着放', () async {
      await playThree();
      await p.removeAt(0);
      expect(p.current!.tid, 'mt2');
      expect(be.played.last, contains('mt2'));
    });

    test('移掉最后一首正在放的:回到队首接着放', () async {
      await playThree();
      await p.playAt(2);
      await p.removeAt(2);
      expect(p.queue.length, 2);
      expect(p.current!.tid, 'mt1');
    });

    test('移到一首不剩:停下,不再有当前歌', () async {
      make();
      await p.playContext([track('mt1')]);
      await p.removeAt(0);
      expect(p.hasTrack, isFalse);
      expect(p.playing, isFalse);
      expect(be.stops, greaterThan(0));
    });

    test('清空队列:停下、上下文也清掉', () async {
      await playThree();
      await p.clearQueue();
      expect(p.queue, isEmpty);
      expect(p.index, -1);
      expect(p.playContextKey, '');
      expect(p.playing, isFalse);
    });
  });

  group('插到下一首', () {
    test('新歌插在当前这首后面,不打断正在放的', () async {
      await playThree();
      p.insertNext(track('mt9'));
      expect(p.queue.map((t) => t.tid).toList(), ['mt1', 'mt9', 'mt2', 'mt3']);
      expect(p.current!.tid, 'mt1');
      expect(be.played.length, 1);
    });

    test('已经在队列后面的那首挪过来,不会出现两条一样的', () async {
      await playThree();
      p.insertNext(track('mt3'));
      expect(p.queue.map((t) => t.tid).toList(), ['mt1', 'mt3', 'mt2']);
    });

    test('已经在队列前面的那首挪过来,当前下标跟着修正', () async {
      await playThree();
      await p.playAt(2); // 在放 mt3,下标 2
      p.insertNext(track('mt1')); // 把前面的 mt1 挪到 mt3 后面
      expect(p.queue.map((t) => t.tid).toList(), ['mt2', 'mt3', 'mt1']);
      expect(p.current!.tid, 'mt3');
    });

    test('插的就是正在放的那首:什么也不动', () async {
      await playThree();
      p.insertNext(track('mt1'));
      expect(p.queue.map((t) => t.tid).toList(), ['mt1', 'mt2', 'mt3']);
    });

    test('队列空着时插一首就成了当前这首', () async {
      make();
      p.insertNext(track('mt9'));
      expect(p.queue.single.tid, 'mt9');
      expect(p.index, 0);
    });
  });

  group('播放模式', () {
    test('列表循环:走到底回到第一首', () async {
      await playThree();
      await p.next();
      expect(p.current!.tid, 'mt2');
      await p.next();
      expect(p.current!.tid, 'mt3');
      await p.next();
      expect(p.current!.tid, 'mt1');
    });

    test('列表循环:上一首从第一首退到最后一首', () async {
      await playThree();
      await p.prev();
      expect(p.current!.tid, 'mt3');
    });

    test('单曲循环:播完了重放这一首', () async {
      await playThree();
      await p.setMode(MusicMode.single);
      await be.complete();
      await pumpEventQueue();
      expect(p.current!.tid, 'mt1');
      expect(be.played.length, 2);
      expect(be.played.last, contains('mt1'));
    });

    test('单曲循环:用户按「下一首」照样往下走(不然像按钮坏了)', () async {
      await playThree();
      await p.setMode(MusicMode.single);
      await p.next();
      expect(p.current!.tid, 'mt2');
    });

    test('随机:一轮之内每首恰好放一次,走完才重洗', () async {
      make();
      await p.playContext([for (var i = 1; i <= 6; i++) track('mt$i')]);
      await p.setMode(MusicMode.shuffle);
      final round = <String>[p.current!.tid];
      for (var i = 0; i < 5; i++) {
        await p.next();
        round.add(p.current!.tid);
      }
      expect(round.toSet().length, 6, reason: '一轮里不该重复:$round');
      // 走完一轮之后重洗,下一首还在这六首里
      await p.next();
      expect(p.queue.map((t) => t.tid), contains(p.current!.tid));
    });

    test('随机:切过去时正在放的那首排头,下一首不会又是它', () async {
      make();
      await p.playContext([for (var i = 1; i <= 5; i++) track('mt$i')]);
      await p.playAt(3);
      await p.setMode(MusicMode.shuffle);
      expect(p.shuffleOrder.first, 3);
      await p.next();
      expect(p.current!.tid, isNot('mt4'));
    });

    test('随机:上一首退回刚才那首', () async {
      make();
      await p.playContext([for (var i = 1; i <= 5; i++) track('mt$i')]);
      await p.setMode(MusicMode.shuffle);
      final first = p.current!.tid;
      await p.next();
      await p.prev();
      expect(p.current!.tid, first);
    });

    test('随机:手点队列里某一首之后,下一首从它往后走', () async {
      make();
      await p.playContext([for (var i = 1; i <= 5; i++) track('mt$i')]);
      await p.setMode(MusicMode.shuffle);
      await p.playAt(2);
      final order = p.shuffleOrder;
      final at = order.indexOf(2);
      await p.next();
      final expected = at + 1 < order.length ? order[at + 1] : null;
      if (expected != null) expect(p.index, expected);
    });

    test('只有一首歌时三种模式都不会走出边界', () async {
      make();
      await p.playContext([track('mt1')]);
      for (final m in MusicMode.values) {
        await p.setMode(m);
        await p.next();
        expect(p.current!.tid, 'mt1');
        await p.prev();
        expect(p.current!.tid, 'mt1');
      }
    });

    test('队列空着时按上一首 / 下一首不崩', () async {
      make();
      await p.next();
      await p.prev();
      expect(p.hasTrack, isFalse);
    });

    test('模式在三种之间轮着切,并记在本机', () async {
      make();
      expect(p.mode, MusicMode.listLoop);
      await p.cycleMode();
      expect(p.mode, MusicMode.single);
      await p.cycleMode();
      expect(p.mode, MusicMode.shuffle);
      await p.cycleMode();
      expect(p.mode, MusicMode.listLoop);

      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('music_mode'), 'listLoop');
    });
  });

  group('收听上报(§5.5 按实际听的毫秒数)', () {
    test('切歌时把这首实听了多久报上去', () async {
      await playThree();
      await be.tick(1000);
      await be.tick(2000);
      await be.tick(3000);
      await p.next();
      final r = rec.plays.single;
      expect(r.path, '/music/v1/tracks/mt1/play');
      expect(r.body['ms_listened'], 3000);
      expect(r.body['context'], 'playlist:mpX');
    });

    test('拖过去的那一段不算听过', () async {
      await playThree();
      await be.tick(1000);
      await be.tick(2000);
      // 从 2 秒拖到 100 秒:中间那 98 秒一秒也没听
      await p.seekTo(const Duration(milliseconds: 100000));
      await be.tick(101000);
      await be.tick(102000);
      await p.next();
      expect(rec.plays.single.body['ms_listened'], 4000);
    });

    test('往回拖再听一遍,听过的时长接着涨', () async {
      await playThree();
      await be.playTo(5000);
      await p.seekTo(const Duration(milliseconds: 1000));
      await be.playTo(3000);
      await p.next();
      // 第一遍 5 秒 + 回头又听的 2 秒
      expect(rec.plays.single.body['ms_listened'], 7000);
    });

    test('一步跨过去的位置当成拖动,不算听过', () async {
      await playThree();
      // 播放器两次上报之间差了半分钟,只可能是有人拖了条或者卡了
      await be.tick(30000);
      await p.next();
      expect(rec.plays, isEmpty);
    });

    test('暂停的时候不涨', () async {
      await playThree();
      await be.tick(1000);
      await p.pause();
      await be.tick(2000);
      await be.tick(3000);
      await p.toggle(); // 接着播
      await be.tick(4000);
      await p.next();
      // 1 秒(暂停前)+ 1 秒(恢复后那一跳)
      expect(rec.plays.single.body['ms_listened'], 2000);
    });

    test('播完时按时长补齐最后那一下', () async {
      make();
      await p.playContext([track('mt1', durationMs: 5000), track('mt2')]);
      await be.emitDuration(5000);
      await be.playTo(4800);
      await be.complete();
      await pumpEventQueue();
      expect(rec.plays.single.body['ms_listened'], 5000);
    });

    test('一下也没听就切走的不报', () async {
      await playThree();
      await p.next();
      expect(rec.plays, isEmpty);
    });

    test('每首各报各的,不会串味', () async {
      await playThree();
      await be.tick(2000);
      await p.next();
      await be.tick(1000);
      await p.next();
      expect(rec.plays.length, 2);
      expect(rec.plays[0].path, contains('mt1'));
      expect(rec.plays[0].body['ms_listened'], 2000);
      expect(rec.plays[1].path, contains('mt2'));
      expect(rec.plays[1].body['ms_listened'], 1000);
    });

    test('没登录也带设备号(§5.4 按人去重,没登录按设备)', () async {
      await playThree();
      await be.tick(1000);
      await p.next();
      expect('${rec.plays.single.body['device_id']}'.length, 16);
    });
  });

  group('播放地址', () {
    test('列表里的歌没带地址时,播之前现签一次', () async {
      await playThree();
      expect(rec.signs, 1);
      expect(be.played.single, contains('sig1'));
    });

    test('地址还没过期就直接用,不多签一次', () async {
      make();
      final t = track('mt1');
      t.stream = MStream(std: '/已有的.m4a', expiresAt: DateTime.now().add(const Duration(hours: 5)));
      await p.playContext([t]);
      expect(rec.signs, 0);
      expect(be.played.single, '/已有的.m4a');
    });

    test('地址快过期了先重签(留两分钟余量)', () async {
      make();
      final t = track('mt1');
      t.stream = MStream(std: '/旧的.m4a', expiresAt: DateTime.now().add(const Duration(seconds: 30)));
      await p.playContext([t]);
      expect(rec.signs, 1);
      expect(be.played.single, contains('sig1'));
    });

    test('拿着旧地址被挡(403):重签一次再试,这次放得出来', () async {
      make();
      final t = track('mt1');
      // 服务端提前撤了签名:客户端这边看着还没到期
      t.stream = MStream(std: '/挡掉的.m4a', expiresAt: DateTime.now().add(const Duration(hours: 5)));
      be.broken.add('挡掉的');
      await p.playContext([t]);
      expect(rec.signs, 1);
      expect(p.playing, isTrue);
      expect(be.played.single, contains('sig1'));
    });

    test('重签之后还是放不了:跳下一首并说一句', () async {
      make();
      be.broken.add('mt1');
      final said = <String>[];
      p.onNotice = said.add;
      await p.playContext([track('mt1'), track('mt2')]);
      expect(p.current!.tid, 'mt2');
      expect(p.playing, isTrue);
      expect(said.single, contains('已跳到下一首'));
    });

    test('整队都放不了时停下,不原地打转', () async {
      make();
      be.broken
        ..add('mt1')
        ..add('mt2');
      final said = <String>[];
      p.onNotice = said.add;
      await p.playContext([track('mt1'), track('mt2')]);
      expect(p.playing, isFalse);
      expect(said.last, contains('暂时放不了'));
    });

    test('播到一半被挡:重签接着播,进度不丢', () async {
      await playThree();
      await be.tick(30000);
      await be.fail(Exception('连接断了'));
      await pumpEventQueue();
      expect(rec.signs, 2);
      expect(p.playing, isTrue);
      expect(be.seeks.last, const Duration(milliseconds: 30000));
    });
  });

  group('音质(§4 M4)', () {
    test('缺省标准,切到高品质后记在本机', () async {
      await playThree();
      expect(p.quality, kQualityStd);
      await p.setQuality(kQualityHq);
      expect(p.quality, kQualityHq);
      final sp = await SharedPreferences.getInstance();
      expect(sp.getString('music_quality'), kQualityHq);
    });

    test('切音质时重开流并跳回原来的进度', () async {
      await playThree();
      await be.tick(40000);
      await p.setQuality(kQualityHq);
      expect(be.played.last, contains('hq.m4a'));
      expect(be.seeks.last, const Duration(milliseconds: 40000));
    });

    test('切音质不当成切歌:这首听了多久接着算', () async {
      await playThree();
      await be.playTo(10000);
      await p.setQuality(kQualityHq);
      expect(rec.plays, isEmpty);
      expect(p.listenedMs, 10000);
    });

    test('这首歌没有高品质档时回落标准,不是放不出来', () async {
      make();
      rec.noHq.add('mt1');
      await p.playContext([track('mt1')]);
      await p.setQuality(kQualityHq);
      expect(be.played.last, contains('std.m4a'));
    });

    test('启动时读回上次选的音质', () async {
      SharedPreferences.setMockInitialValues({'music_quality': kQualityHq, 'music_mode': 'shuffle'});
      make();
      await p.load();
      expect(p.quality, kQualityHq);
      expect(p.mode, MusicMode.shuffle);
    });
  });

  group('进度与播放键', () {
    test('拖动条按时长夹在范围内', () async {
      await playThree();
      await be.emitDuration(60000);
      await p.seekTo(const Duration(milliseconds: 90000));
      expect(p.position, const Duration(milliseconds: 60000));
      await p.seekTo(const Duration(milliseconds: -5));
      expect(p.position, Duration.zero);
    });

    test('还不知道时长时比例是 0,不会除零', () async {
      await playThree();
      expect(p.progress, 0);
      await be.emitDuration(100000);
      await be.tick(25000);
      expect(p.progress, closeTo(0.25, 0.001));
    });

    test('播 / 暂停一下一下来回切', () async {
      await playThree();
      expect(p.playing, isTrue);
      await p.toggle();
      expect(p.playing, isFalse);
      expect(be.pauses, 1);
      await p.toggle();
      expect(p.playing, isTrue);
      expect(be.resumes, 1);
    });

    test('没歌的时候按播放键什么也不发生', () async {
      make();
      await p.toggle();
      expect(be.resumes, 0);
    });
  });

  group('定时关闭', () {
    test('「播完这首再停」:这首播完就停,而且只停这一次', () async {
      await playThree();
      final said = <String>[];
      p.onNotice = said.add;
      p.setSleepAfterTrack(true);
      await be.complete();
      await pumpEventQueue();
      expect(p.playing, isFalse);
      expect(p.sleepAfterTrack, isFalse);
      expect(said.single, contains('停'));
      // 还停在原来那首上,没往下跳
      expect(p.current!.tid, 'mt1');
    });

    test('「播完这首再停」不拦用户自己按的下一首', () async {
      await playThree();
      p.setSleepAfterTrack(true);
      await p.next();
      expect(p.current!.tid, 'mt2');
      expect(p.playing, isTrue);
    });

    test('设了分钟数就有倒计时,取消之后没有', () async {
      await playThree();
      p.setSleepTimer(const Duration(minutes: 30));
      expect(p.sleepUntil, isNotNull);
      expect(p.sleepRemaining!.inMinutes, inInclusiveRange(29, 30));
      p.setSleepTimer(null);
      expect(p.sleepUntil, isNull);
      expect(p.sleepRemaining, isNull);
    });

    test('两种定时互斥:设了分钟数就不再是「播完这首」', () async {
      await playThree();
      p.setSleepAfterTrack(true);
      p.setSleepTimer(const Duration(minutes: 15));
      expect(p.sleepAfterTrack, isFalse);
      p.setSleepAfterTrack(true);
      expect(p.sleepUntil, isNull);
    });

    test('时间到了就停下', () async {
      await playThree();
      final said = <String>[];
      p.onNotice = said.add;
      // 真实时间走的定时器,验的是「到点真会停」,所以拨一个短的而不是 15 分钟
      p.setSleepTimer(const Duration(milliseconds: 30));
      await Future<void>.delayed(const Duration(milliseconds: 80));
      await pumpEventQueue();
      expect(p.playing, isFalse);
      expect(p.sleepUntil, isNull);
      expect(be.stops, greaterThan(0));
      expect(said.single, contains('停'));
    });

    test('取消之后到了原来那个点也不会停', () async {
      await playThree();
      p.setSleepTimer(const Duration(milliseconds: 30));
      p.setSleepTimer(null);
      await Future<void>.delayed(const Duration(milliseconds: 80));
      expect(p.playing, isTrue);
    });
  });
}
