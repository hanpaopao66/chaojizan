import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/video/danmaku/engine.dart';
import 'package:user_app/video/danmaku/settings.dart';
import 'package:user_app/video/models.dart';

/// 弹幕排布引擎(DEV-PROMPTS-40 §5.10,#360)。
///
/// 量宽用假的:每个字的宽度 = 字号。这样几何能精确算 ——
/// 屏宽 400、字号 25 时,「四个字」宽 100,滚动速度 = (400 + 100) ÷ 8000 = 0.0625 像素 / 毫秒,
/// 尾巴离开右边缘要 100 ÷ 0.0625 = 1600 毫秒。
double fakeMeasure(String text, double fontSize) => text.length * fontSize;

Danmaku dm(int id, int t, String text,
        {int mode = Danmaku.scroll, int size = 25, int color = 0xFFFFFF, String hash = 'u1', bool mine = false}) =>
    Danmaku(id: id, timeMs: t, text: text, mode: mode, size: size, color: color, userHash: hash, mine: mine);

/// 屏幕 400 × 350、字号 25:行高 35,全屏 10 条轨道
DanmakuEngine engineOf(List<Danmaku> items,
    {double w = 400, double h = 350, double fs = 25, double speed = 1, double area = 1}) {
  final e = DanmakuEngine(measure: fakeMeasure)
    ..configure(width: w, height: h, fontSize: fs, speed: speed, area: area)
    ..setItems(items);
  return e;
}

/// 从 [from] 到 [to] 每 16ms 推进一帧(最后一帧正好落在 [to]),每帧调一次 [check]
void play(DanmakuEngine e, int from, int to, [void Function(int t)? check]) {
  var t = from;
  while (true) {
    e.advance(t);
    check?.call(t);
    if (t >= to) break;
    t = min(to, t + 16);
  }
}

String randomText(Random r) => 'x' * (1 + r.nextInt(20));

void main() {
  group('轨道分配', () {
    test('同一时刻的三条滚动弹幕依次占第 0、1、2 条轨道', () {
      final e = engineOf([dm(1, 0, '一二三四'), dm(2, 0, '一二三四'), dm(3, 0, '一二三四')]);
      e.advance(0);
      expect([for (final s in e.active) s.track], [0, 1, 2]);
      expect([for (final s in e.active) e.yOf(s)], [0, 35, 70]);
      // 从右边缘进场
      expect(e.xOf(e.active.first, 0), 400);
    });

    test('前一条的尾巴离开右边缘,下一条才能用同一条轨道', () {
      // 四个字宽 100,尾巴 1600ms 时离开右边缘
      final early = engineOf([dm(1, 0, '一二三四'), dm(2, 1599, '一二三四')]);
      play(early, 0, 1599);
      expect(early.active.firstWhere((s) => s.item.id == 2).track, 1, reason: '1599ms 时尾巴还压在右边缘上');

      final onTime = engineOf([dm(1, 0, '一二三四'), dm(2, 1600, '一二三四')]);
      play(onTime, 0, 1600);
      final s1 = onTime.active.firstWhere((s) => s.item.id == 1);
      final s2 = onTime.active.firstWhere((s) => s.item.id == 2);
      expect(s2.track, 0);
      expect(onTime.xOf(s1, 1600) + s1.width, closeTo(400, 1e-6), reason: '前一条的尾巴刚好在右边缘');
    });

    test('后一条比前一条长(飞得快)时,光尾巴离开右边缘不够,要追不上才放同一轨道', () {
      // 短的「两个字」宽 50:速度 450/8000,尾巴 889ms 离开右边缘,8000ms 完全离开屏幕
      // 长的「十六个字」宽 400:速度 0.1,从右边缘飞到左边缘要 4000ms —— 早于 8000 − 4000 = 4000ms 放就会追尾
      final chase = engineOf([dm(1, 0, '两字'), dm(2, 1000, 'x' * 16)]);
      play(chase, 0, 1000);
      expect(chase.active.firstWhere((s) => s.item.id == 2).track, 1, reason: '1000ms 放在第 0 轨会在左边追上前一条');

      final ok = engineOf([dm(1, 0, '两字'), dm(2, 4000, 'x' * 16)]);
      play(ok, 0, 4000);
      expect(ok.active.firstWhere((s) => s.item.id == 2).track, 0);
    });
  });

  test('同轨道不重叠:随机 600 条滚动弹幕播 70 秒,每一帧同一轨道上的任意两条都不相交', () {
    final r = Random(20260912);
    final items = [for (var i = 0; i < 600; i++) dm(i + 1, r.nextInt(60000), randomText(r))];
    final e = engineOf(items);
    var frames = 0;
    play(e, 0, 70000, (t) {
      final byTrack = <int, List<DanmakuSlot>>{};
      for (final s in e.active) {
        byTrack.putIfAbsent(s.track, () => []).add(s);
      }
      for (final list in byTrack.values) {
        list.sort((a, b) => a.startMs.compareTo(b.startMs));
        for (var i = 1; i < list.length; i++) {
          final a = list[i - 1], b = list[i];
          // 先上屏的在左边:它的尾巴不能越过后上屏那条的头
          expect(e.xOf(a, t) + a.width, lessThanOrEqualTo(e.xOf(b, t) + 1e-6),
              reason: '轨道 ${a.track} 上 #${a.item.id} 和 #${b.item.id} 在 ${t}ms 重叠了');
        }
      }
      frames++;
    });
    expect(frames, greaterThan(4000));
    // 600 条在 10 条轨道里肯定有放不下的:丢了,但不是全丢
    expect(e.dropped, greaterThan(0));
    expect(e.dropped, lessThan(600));
  });

  group('放不下就丢弃', () {
    test('只有 2 条轨道时同一刻来 5 条:放 2 条、丢 3 条,不排队等', () {
      // 350 × 0.2 = 70,行高 35 → 2 条轨道
      final e = engineOf([for (var i = 1; i <= 5; i++) dm(i, 1000, '一二三四')], area: 0.2);
      expect(e.trackCount, 2);
      play(e, 0, 1000);
      expect(e.active.length, 2);
      expect(e.dropped, 3);
      // 丢了就是丢了:等轨道空出来也不会补上
      play(e, 1000, 9000);
      expect(e.active.where((s) => s.item.id > 2), isEmpty);
    });

    test('显示区域矮到一条轨道都没有:全部丢弃', () {
      final e = engineOf([dm(1, 0, '一')], h: 30);
      e.advance(0);
      expect(e.trackCount, 0);
      expect(e.active, isEmpty);
      expect(e.dropped, 1);
    });
  });

  group('顶部 / 底部弹幕', () {
    test('顶部弹幕水平居中,停 4 秒', () {
      final e = engineOf([dm(1, 1000, '一二三四', mode: Danmaku.top)]);
      play(e, 0, 1000);
      final s = e.active.single;
      expect(e.xOf(s, 1000), (400 - 100) / 2);
      expect(e.yOf(s), 0);
      e.advance(4999);
      expect(e.active, hasLength(1), reason: '4999ms 还在');
      expect(e.xOf(s, 4999), (400 - 100) / 2, reason: '停着不动');
      e.advance(5000);
      expect(e.active, isEmpty, reason: '满 4 秒就走');
    });

    test('底部弹幕从显示区域的底边往上排', () {
      final e = engineOf([
        dm(1, 0, '一', mode: Danmaku.bottom),
        dm(2, 0, '二', mode: Danmaku.bottom),
      ]);
      e.advance(0);
      expect([for (final s in e.active) e.yOf(s)], [350 - 35, 350 - 70]);
    });

    test('同一条顶部轨道:前一条停满 4 秒才能放下一条', () {
      final e = engineOf([
        dm(1, 0, '一', mode: Danmaku.top),
        dm(2, 3999, '二', mode: Danmaku.top),
        dm(3, 4000, '三', mode: Danmaku.top),
      ]);
      play(e, 0, 4000);
      final tracks = {for (final s in e.active) s.item.id: s.track};
      expect(tracks[2], 1);
      expect(tracks[3], 0);
    });

    test('速度倍数只管滚动的,顶部 / 底部照样停 4 秒', () {
      final e = engineOf([dm(1, 0, '一', mode: Danmaku.bottom)], speed: 2);
      e.advance(0);
      expect(e.active.single.durationMs, 4000);
    });
  });

  group('显示区域决定能用几条轨道', () {
    for (final (area, tracks) in [(0.25, 2), (0.5, 5), (0.75, 7), (1.0, 10)]) {
      test('${danmakuAreaLabel(area)}:$tracks 条', () {
        final e = engineOf([for (var i = 1; i <= 20; i++) dm(i, 0, '一二')], area: area);
        e.advance(0);
        expect(e.trackCount, tracks);
        expect(e.active.length, tracks);
        for (final s in e.active) {
          expect(e.yOf(s) + e.trackHeight, lessThanOrEqualTo(350 * area + 1e-6), reason: '不出显示区域');
        }
      });
    }

    test('半屏时底部弹幕贴着半屏的底边', () {
      final e = engineOf([dm(1, 0, '一', mode: Danmaku.bottom)], area: 0.5);
      e.advance(0);
      expect(e.yOf(e.active.single), 175 - 35);
    });

    test('行高 = 字号 × 1.4,字号跟着「字号缩放」', () {
      final e = engineOf([], fs: 25 * 1.5);
      expect(e.trackHeight, closeTo(25 * 1.5 * 1.4, 1e-9));
      expect(e.trackCount, (350 / (25 * 1.5 * 1.4)).floor());
    });
  });

  group('跳进度后按新时间重建', () {
    final r = Random(7);
    final items = [for (var i = 0; i < 300; i++) dm(i + 1, r.nextInt(60000), randomText(r))];
    List<(int, int, int)> snapshot(DanmakuEngine e) =>
        [for (final s in e.active) (s.item.id, s.track, s.startMs)]..sort((a, b) => a.$1 - b.$1);

    test('播到 30 秒再拖回 10 秒:屏幕上的弹幕和直接打开到 10 秒一模一样', () {
      final played = engineOf(items);
      play(played, 0, 30000);
      played.seek(10000);
      final fresh = engineOf(items)..seek(10000);
      expect(snapshot(played), snapshot(fresh));
      expect(snapshot(played), isNotEmpty);
      for (final s in played.active) {
        expect(s.item.timeMs, inInclusiveRange(10000 - played.windowMs + 1, 10000),
            reason: '只重排新时刻往前一个飞行周期里的');
      }
    });

    test('往回退当成跳进度:advance 到更早的时刻等于 seek', () {
      final a = engineOf(items);
      play(a, 0, 20000);
      a.advance(5000);
      final b = engineOf(items)..seek(5000);
      expect(snapshot(a), snapshot(b));
    });

    test('重建之后接着播,后面的弹幕照常到点上屏', () {
      final e = engineOf([dm(1, 12000, '一二'), dm(2, 15000, '三四')]);
      e.seek(13000);
      expect(e.active.map((s) => s.item.id), [1], reason: '12 秒那条还在飞');
      play(e, 13000, 15000);
      expect(e.active.map((s) => s.item.id), containsAll([1, 2]));
    });

    test('往前跳得比一个窗口还远,也按重建处理(不会把中间几千条逐条排一遍再扔掉)', () {
      final e = engineOf(items);
      e.advance(0);
      e.advance(50000);
      final fresh = engineOf(items)..seek(50000);
      expect(snapshot(e), snapshot(fresh));
    });
  });

  group('速度倍数影响飞行时间', () {
    for (final (speed, ms) in [(0.5, 16000), (1.0, 8000), (2.0, 4000)]) {
      test('${speed}x:飞过屏幕 $ms 毫秒', () {
        final e = engineOf([dm(1, 0, '一二三四')], speed: speed);
        expect(e.scrollDurationMs, ms);
        e.advance(0);
        final s = e.active.single;
        // 飞到一半时正好居中:x = 屏宽 − (屏宽 + 字宽) / 2
        expect(e.xOf(s, ms ~/ 2), closeTo((400 - 100) / 2, 1e-6));
        e.advance(ms - 1);
        expect(e.active, hasLength(1));
        expect(e.xOf(s, ms), closeTo(-100, 1e-6), reason: '到点时尾巴刚好离开左边缘');
        e.advance(ms);
        expect(e.active, isEmpty);
      });
    }

    test('改速度按当前时间重建,之后上屏的按新速度飞', () {
      final e = engineOf([dm(1, 0, '一'), dm(2, 1000, '二')]);
      e.advance(500);
      e.configure(width: 400, height: 350, fontSize: DanmakuEngine.standardSize.toDouble(), speed: 2);
      play(e, 500, 1000);
      expect(e.active.firstWhere((s) => s.item.id == 2).durationMs, 4000);
    });
  });

  group('自己刚发的弹幕', () {
    test('轨道全满也立即上屏(硬放),不算丢弃', () {
      final e = engineOf([dm(1, 1000, '一二三四'), dm(2, 1000, '一二三四')], area: 0.2);
      play(e, 0, 1000);
      expect(e.active.length, 2);
      final mine = dm(99, 1000, '我发的', mine: true);
      final slot = e.insertNow(mine);
      expect(slot, isNotNull);
      expect(slot!.forced, isTrue);
      expect(e.active.map((s) => s.item.id), contains(99));
      expect(e.dropped, 0);
    });

    test('硬放之后顺着播过它的 time_ms 不会再放一遍', () {
      final e = engineOf([]);
      e.advance(2000);
      // 暂停在 2000 时发的:time_ms 就是 2000(和「现在」相等)
      e.insertNow(dm(99, 2000, '我发的', mine: true));
      play(e, 2000, 6000);
      expect(e.active.where((s) => s.item.id == 99), hasLength(1));
      // 播放器报的位置略早于引擎时间时发的(time_ms 在「现在」之后一点)也一样
      final f = engineOf([]);
      f.advance(1000);
      f.insertNow(dm(98, 1200, '我发的', mine: true));
      play(f, 1000, 3000);
      expect(f.active.where((s) => s.item.id == 98), hasLength(1));
    });

    test('接着把含这条的新列表交给引擎,不会整屏重建', () {
      final base = [dm(1, 500, '一二'), dm(2, 800, '三四')];
      final e = engineOf(base);
      play(e, 0, 1000);
      final before = {for (final s in e.active) s.item.id: s.track};
      final mine = dm(99, 1000, '我发的', mine: true);
      final slot = e.insertNow(mine)!;
      e.setItems([...base, mine]);
      expect({for (final s in e.active) s.item.id: s.track}, {...before, 99: slot.track});
    });
  });

  group('换列表', () {
    test('新来的全在未来(预取的下一段):屏幕上正在飞的不动', () {
      final now = [dm(1, 1000, '一二'), dm(2, 1200, '三四')];
      final e = engineOf(now);
      play(e, 0, 2000);
      final before = e.active.toList();
      e.setItems([...now, dm(3, 400000, '下一段')]);
      expect(e.active, before, reason: '同样的对象、同样的轨道');
      play(e, 2000, 2100);
      expect(e.active.map((s) => s.item.id), [1, 2]);
    });

    test('窗口里的内容变了(屏蔽了某人):按当前时间重建,被屏蔽的立刻消失', () {
      final all = [dm(1, 1000, '一二', hash: 'a'), dm(2, 1200, '三四', hash: 'b')];
      final e = engineOf(all);
      play(e, 0, 2000);
      const s = DanmakuSettings(blockUsers: ['a']);
      e.setItems(all.where(s.allows).toList());
      expect(e.active.map((x) => x.item.id), [2]);
    });
  });

  test('点中哪条:按当前位置判,左右放宽一点', () {
    final e = engineOf([dm(1, 0, '一二三四', mode: Danmaku.top)]);
    e.advance(0);
    // 顶部居中:x 150–250,y 0–35
    expect(e.hitTest(200, 10)?.item.id, 1);
    expect(e.hitTest(146, 10)?.item.id, 1, reason: '左边放宽 6 像素');
    expect(e.hitTest(200, 40), isNull);
    expect(e.hitTest(100, 10), isNull);
  });

  group('屏蔽规则', () {
    test('按类型、彩色、屏蔽词(不分大小写)、屏蔽的人过滤', () {
      const s = DanmakuSettings(
        blockTop: true,
        blockColored: true,
        blockWords: ['剧透'],
        blockUsers: ['bad'],
      );
      expect(s.allows(dm(1, 0, '普通')), isTrue);
      expect(s.allows(dm(2, 0, '顶', mode: Danmaku.top)), isFalse);
      expect(s.allows(dm(3, 0, '底', mode: Danmaku.bottom)), isTrue);
      expect(s.allows(dm(4, 0, '红', color: 0xFE0302)), isFalse);
      expect(s.allows(dm(5, 0, '前方剧透预警')), isFalse);
      expect(s.allows(dm(6, 0, '路过', hash: 'bad')), isFalse);
      const w = DanmakuSettings(blockWords: ['abc']);
      expect(w.allows(dm(7, 0, 'xxABCxx')), isFalse);
      expect(const DanmakuSettings(blockScroll: true).allows(dm(8, 0, '滚')), isFalse);
      expect(const DanmakuSettings(blockBottom: true).allows(dm(9, 0, '底', mode: Danmaku.bottom)), isFalse);
    });

    test('自己发的不受屏蔽规则影响(发了看不到会以为没发出去)', () {
      const s = DanmakuSettings(blockScroll: true, blockColored: true, blockWords: ['我']);
      expect(s.allows(dm(1, 0, '我发的', color: 0xFE0302, mine: true)), isTrue);
    });

    test('存盘的设置读回来:越界的夹回范围,显示区域落回四档之一,坏数据退回缺省', () {
      final s = DanmakuSettings.fromJson({
        'enabled': false,
        'opacity': 0.05,
        'font_scale': 9,
        'speed': 0.1,
        'area': 0.6,
        'block_words': ['  剧透 ', '', 3],
        'block_users': ['a'],
      });
      expect(s.enabled, isFalse);
      expect(s.opacity, DanmakuSettings.minOpacity);
      expect(s.fontScale, DanmakuSettings.maxFontScale);
      expect(s.speed, DanmakuSettings.minSpeed);
      expect(s.area, 0.5);
      expect(s.blockWords, ['剧透']);
      final back = DanmakuSettings.fromJson(s.toJson());
      expect(back.toJson(), s.toJson());
      expect(DanmakuSettings.fromJson('坏的').toJson(), const DanmakuSettings().toJson());
    });
  });

  group('高能进度条', () {
    test('三桶滑动平均后按最大值归一', () {
      final v = danmakuDensityLevels([0, 10, 0, 0]);
      expect(v.length, 4);
      expect(v.reduce(max), 1);
      expect(v[0], closeTo(1, 1e-9));
      expect(v[1], closeTo((10 / 3) / 5, 1e-9));
      expect(v[3], 0);
    });

    test('没有弹幕就是全 0,没有桶就是空', () {
      expect(danmakuDensityLevels([0, 0, 0]), [0, 0, 0]);
      expect(danmakuDensityLevels([]), isEmpty);
    });
  });
}
