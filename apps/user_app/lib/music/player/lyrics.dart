// 歌词:LRC(带时间轴)解析 + 按进度求当前行;认不出时间轴就当纯文本(§4 M8)。
//
// 为什么要自己解析而不是让服务端切好:歌词是音乐人自己贴上来的文本,
// 什么写法都有 —— 一行挂好几个时间标签(副歌重复)、两位或三位毫秒、
// 秒和毫秒之间用冒号、夹着 `[ar:]` 这类元信息、整篇根本没有时间标签。
// 服务端只负责原样存(`lyrics_kind` 只是个提示),显示成什么样是客户端的事。

/// 一行歌词。纯文本歌词的 [timeMs] 是 -1(没有时间轴,不参与高亮)。
class LyricLine {
  const LyricLine({required this.timeMs, required this.text});

  final int timeMs;
  final String text;

  bool get timed => timeMs >= 0;

  @override
  String toString() => '[$timeMs]$text';
}

/// 一首歌的歌词。
class Lyrics {
  const Lyrics({required this.kind, required this.lines});

  /// `lrc`(带时间轴)/ `plain`(纯文本)/ `none`(没有)
  final String kind;

  /// 按时间升序;纯文本时按原文顺序
  final List<LyricLine> lines;

  static const Lyrics none = Lyrics(kind: 'none', lines: []);

  bool get synced => kind == 'lrc';
  bool get isEmpty => lines.isEmpty;

  /// 进度 [ms] 时正在唱的是第几行。
  ///
  /// 还没到第一行(前奏)返回 -1 —— 调用方据此不高亮任何一行,
  /// 而不是硬把第一行点亮:前奏里就把第一句点亮,跟着唱会早半句。
  int indexAt(int ms) {
    if (!synced || lines.isEmpty) return -1;
    if (ms < lines.first.timeMs) return -1;
    // 二分找「最后一个时间 ≤ ms 的」。歌词行数不多,但这个方法每帧都调
    var lo = 0, hi = lines.length - 1;
    while (lo < hi) {
      final mid = (lo + hi + 1) >> 1;
      if (lines[mid].timeMs <= ms) {
        lo = mid;
      } else {
        hi = mid - 1;
      }
    }
    return lo;
  }
}

/// `[分:秒.毫秒]`。毫秒可以是 1–3 位,秒和毫秒之间 `.` 或 `:` 都有人写。
final _tag = RegExp(r'\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]');

/// `[offset:±500]`、`[ar:歌手]` 这类元信息。
final _meta = RegExp(r'^\[([a-zA-Z#]+):(.*)\]$');

/// 解析歌词。[kind] 是服务端给的提示(`lrc` / `plain` / `none`),
/// **只作参考**:说是 lrc 却一个时间标签都没有,照样按纯文本显示。
Lyrics parseLyrics(String raw, {String kind = ''}) {
  if (kind == 'none' || raw.trim().isEmpty) return Lyrics.none;
  final rows = raw.split(RegExp(r'\r\n|\r|\n'));
  final timed = <LyricLine>[];
  final plain = <String>[];
  var offsetMs = 0;

  for (final row in rows) {
    final line = row.trim();
    if (line.isEmpty) continue;

    // 先摘时间标签:可能有好几个(副歌那几句在原文里只写一遍)
    final stamps = <int>[];
    var i = 0;
    while (true) {
      final m = _tag.matchAsPrefix(line, i);
      if (m == null) break;
      final min = int.parse(m.group(1)!);
      final sec = int.parse(m.group(2)!);
      final frac = m.group(3);
      // 两位是百分之一秒(绝大多数 LRC 这么写),三位才是毫秒,一位是十分之一秒
      final ms = frac == null
          ? 0
          : (frac.length == 3
              ? int.parse(frac)
              : (frac.length == 2 ? int.parse(frac) * 10 : int.parse(frac) * 100));
      stamps.add(min * 60000 + sec * 1000 + ms);
      i = m.end;
    }

    if (stamps.isEmpty) {
      final meta = _meta.firstMatch(line);
      if (meta != null) {
        if (meta.group(1)!.toLowerCase() == 'offset') {
          offsetMs = int.tryParse(meta.group(2)!.trim().replaceAll('+', '')) ?? 0;
        }
        // ar / ti / al / by 这些不显示:播放页上面已经有歌名和歌手了
        continue;
      }
      plain.add(line);
      continue;
    }

    final text = line.substring(i).trim();
    for (final s in stamps) {
      timed.add(LyricLine(timeMs: s, text: text));
    }
  }

  if (timed.isNotEmpty) {
    // offset 正值表示整体提前显示(LRC 里 `[offset:+500]` 的通行含义):
    // 唱得比标签早半秒时贴的人写 +500,那么每一行都要早 500 毫秒亮起来
    final shifted = [
      for (final l in timed) LyricLine(timeMs: l.timeMs - offsetMs < 0 ? 0 : l.timeMs - offsetMs, text: l.text),
    ]..sort((a, b) => a.timeMs.compareTo(b.timeMs));
    // 整篇时间标签下面一个字都没有(有些文件只是拿 LRC 壳子写了元信息)
    if (shifted.every((l) => l.text.isEmpty)) {
      return plain.isEmpty
          ? Lyrics.none
          : Lyrics(kind: 'plain', lines: [for (final t in plain) LyricLine(timeMs: -1, text: t)]);
    }
    return Lyrics(kind: 'lrc', lines: shifted);
  }

  if (plain.isEmpty) return Lyrics.none;
  return Lyrics(kind: 'plain', lines: [for (final t in plain) LyricLine(timeMs: -1, text: t)]);
}
