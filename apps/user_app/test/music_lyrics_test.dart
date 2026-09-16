// LRC 解析与按进度取行(DEV-PROMPTS-41 §4 M8)。
//
// 歌词是音乐人自己贴的文本,什么写法都有 —— 这一组把见过的写法各钉一条。
import 'package:flutter_test/flutter_test.dart';
import 'package:user_app/music/player/lyrics.dart';

void main() {
  group('LRC 解析', () {
    test('最常见的写法:两位毫秒,一行一个时间标签', () {
      final l = parseLyrics('[00:12.00]第一句\n[00:17.20]第二句\n[01:05.50]第三句');
      expect(l.kind, 'lrc');
      expect(l.synced, isTrue);
      expect(l.lines.length, 3);
      expect(l.lines[0].timeMs, 12000);
      expect(l.lines[0].text, '第一句');
      // 两位是百分之一秒:.20 是 200 毫秒,不是 20 毫秒
      expect(l.lines[1].timeMs, 17200);
      expect(l.lines[2].timeMs, 65500);
    });

    test('一行挂好几个时间标签(副歌在原文里只写一遍)', () {
      final l = parseLyrics('[00:10.00][01:20.30][02:30.00]我们一起唱\n[00:15.00]中间那句');
      expect(l.lines.length, 4);
      // 摊开之后按时间排好序,原文里挤在一行不影响顺序
      expect(l.lines.map((e) => e.timeMs).toList(), [10000, 15000, 80300, 150000]);
      expect(l.lines[0].text, '我们一起唱');
      expect(l.lines[1].text, '中间那句');
      expect(l.lines[2].text, '我们一起唱');
    });

    test('三位毫秒、一位十分之一秒、没有毫秒,三种都认', () {
      final l = parseLyrics('[00:01.123]甲\n[00:02.5]乙\n[00:03]丙');
      expect(l.lines[0].timeMs, 1123);
      expect(l.lines[1].timeMs, 2500);
      expect(l.lines[2].timeMs, 3000);
    });

    test('秒和毫秒之间写冒号的也认', () {
      final l = parseLyrics('[00:12:34]甲');
      expect(l.lines.single.timeMs, 12340);
    });

    test('分钟超过 99 的长音频', () {
      final l = parseLyrics('[123:45.60]很后面');
      expect(l.lines.single.timeMs, 123 * 60000 + 45600);
    });

    test('[offset:] 正值整体提前,负值推后,不会提前到负数', () {
      final early = parseLyrics('[offset:+500]\n[00:10.00]甲\n[00:20.00]乙');
      expect(early.lines[0].timeMs, 9500);
      expect(early.lines[1].timeMs, 19500);

      final late = parseLyrics('[offset:-500]\n[00:10.00]甲');
      expect(late.lines.single.timeMs, 10500);

      // 头一句本来就在 0.2 秒,再提前 1 秒也只能到 0
      final clamped = parseLyrics('[offset:+1000]\n[00:00.20]甲');
      expect(clamped.lines.single.timeMs, 0);
    });

    test('ar / ti / al / by 这类元信息不显示', () {
      final l = parseLyrics('[ti:晚风]\n[ar:小林]\n[al:夏天]\n[by:某某]\n[00:05.00]正文');
      expect(l.lines.length, 1);
      expect(l.lines.single.text, '正文');
    });

    test('时间标签后面没字的空行留着:间奏里不该还高亮着上一句', () {
      final l = parseLyrics('[00:05.00]甲\n[00:10.00]\n[00:30.00]乙');
      expect(l.lines.length, 3);
      expect(l.lines[1].text, '');
      expect(l.indexAt(15000), 1);
    });

    test('整篇只有壳子、一个字都没有时回落纯文本', () {
      final l = parseLyrics('[ti:晚风]\n[00:05.00]\n[00:10.00]\n这是一句没打轴的');
      expect(l.kind, 'plain');
      expect(l.lines.single.text, '这是一句没打轴的');
    });
  });

  group('纯文本回落', () {
    test('一个时间标签都没有时按纯文本,行号是 -1', () {
      final l = parseLyrics('第一句\n第二句\n\n第三句');
      expect(l.kind, 'plain');
      expect(l.synced, isFalse);
      expect(l.lines.length, 3);
      expect(l.lines.every((e) => !e.timed), isTrue);
      // 空行丢掉,不在纯文本里留空档
      expect(l.lines.map((e) => e.text).toList(), ['第一句', '第二句', '第三句']);
    });

    test('服务端说是 lrc 但正文没打轴,照样按纯文本', () {
      final l = parseLyrics('就是一段话', kind: 'lrc');
      expect(l.kind, 'plain');
    });

    test('空歌词 / kind 是 none 时是空', () {
      expect(parseLyrics('').isEmpty, isTrue);
      expect(parseLyrics('   \n  ').isEmpty, isTrue);
      expect(parseLyrics('有字的', kind: 'none').isEmpty, isTrue);
      expect(Lyrics.none.kind, 'none');
    });

    test('Windows 换行(\\r\\n)和老 Mac 换行(\\r)都切得开', () {
      expect(parseLyrics('甲\r\n乙\r丙').lines.length, 3);
    });
  });

  group('按进度取当前行', () {
    final l = parseLyrics('[00:05.00]甲\n[00:10.00]乙\n[00:20.00]丙');

    test('前奏里不高亮任何一行', () {
      // 第一句还没到就点亮它的话,跟着唱会早半句
      expect(l.indexAt(0), -1);
      expect(l.indexAt(4999), -1);
    });

    test('正好卡在时间点上算这一行', () {
      expect(l.indexAt(5000), 0);
      expect(l.indexAt(10000), 1);
      expect(l.indexAt(20000), 2);
    });

    test('两行之间算上一行,最后一行之后一直是最后一行', () {
      expect(l.indexAt(7000), 0);
      expect(l.indexAt(19999), 1);
      expect(l.indexAt(600000), 2);
    });

    test('纯文本和空歌词一律 -1(没有时间轴就没有「当前行」)', () {
      expect(parseLyrics('一段话').indexAt(10000), -1);
      expect(Lyrics.none.indexAt(0), -1);
    });

    test('只有一行时,到点之后一直是它', () {
      final one = parseLyrics('[00:03.00]只此一句');
      expect(one.indexAt(0), -1);
      expect(one.indexAt(3000), 0);
      expect(one.indexAt(999999), 0);
    });
  });
}
