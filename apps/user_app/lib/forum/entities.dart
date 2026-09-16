// 把帖子正文切成「普通字 + 可点片段」(#话题、@超级赞号、链接)。
//
// ## 为什么不在客户端自己认
//
// §5.6 写死了:实体由服务端解析,客户端不许自己报。所以这里**不做发现,只做定位** ——
// 服务端给了哪些话题、提及、链接,就在正文里找它们的位置;找不到的就当普通字。
// 反过来也一样:正文里长得像 `#话题` 但服务端没给的(比如超过 10 个之后的、
// 查不到人的 @),一律不画成可点的 —— 点了也跳不到地方。
//
// 这么做还顺手解决了边界:话题两种写法(`#话题` / `#话题#`)、中英文标点截止,
// 都靠「服务端给的 display 是什么」加「后面跟的那个字是不是截止符」判定,
// 不用在客户端复刻一遍那条正则。

import 'models.dart';

/// 一段正文:普通字,或者一个可点的片段。
class FSegment {
  const FSegment(this.text, {this.kind = FSegmentKind.plain, this.value = ''});

  final String text;
  final FSegmentKind kind;

  /// 话题给规范化的小写 tag、提及给用户号、链接给完整地址;普通字是空串
  final String value;

  bool get isPlain => kind == FSegmentKind.plain;

  @override
  String toString() => isPlain ? text : '${kind.name}($value):$text';
}

enum FSegmentKind { plain, tag, mention, link }

/// 话题到这些字符为止(§5.6「遇到空白、`#`、中英文标点截止」)。
///
/// 只用来判定 `#话题` 这种没有闭合井号的写法后面跟的是不是截止符 ——
/// 跟的是别的字,说明服务端解析出来的那个话题不是从这里开始的。
const String fTagStopChars = ' \t\n\r #…,.!?;:"\'()[]{}<>@，。！？、；：（）【】《》〈〉「」『』“”‘’—～·|\\/';

bool _isTagStop(String ch) => fTagStopChars.contains(ch);

/// 提及后面不能再跟超级赞号的合法字符 —— 跟着就说明服务端认的是更长的那个号。
bool _isUsernameChar(String ch) =>
    RegExp(r'^[A-Za-z0-9_]$').hasMatch(ch);

class _Hit {
  _Hit(this.start, this.end, this.kind, this.value);

  final int start;
  final int end;
  final FSegmentKind kind;
  final String value;
}

/// 把 [text] 按 [entities] 切成片段。没有实体时返回一段普通字。
///
/// 重叠的片段(链接地址里带 `#锚点`、话题里含 @)只保留**起点靠前**的那个;
/// 起点一样就留长的 —— 链接总是从 `https://` 起,自然赢过里面的 `#xxx`。
List<FSegment> forumSegments(String text, FEntities entities) {
  if (text.isEmpty) return const [];
  if (entities.isEmpty) return [FSegment(text)];

  final hits = <_Hit>[];

  // 链接:服务端给的是完整地址,正文里原样出现,直接找
  for (final link in entities.links) {
    if (link.isEmpty) continue;
    for (final i in _allIndexOf(text, link)) {
      hits.add(_Hit(i, i + link.length, FSegmentKind.link, link));
    }
  }

  // 话题:先找闭合写法 `#display#`,再找开放写法 `#display`(后面必须是截止符或结尾)
  for (final tag in entities.tags) {
    final d = tag.display;
    if (d.isEmpty) continue;
    final closed = '#$d#';
    final taken = <int>{};
    for (final i in _allIndexOf(text, closed)) {
      hits.add(_Hit(i, i + closed.length, FSegmentKind.tag, tag.tag));
      taken.add(i);
    }
    final open = '#$d';
    for (final i in _allIndexOf(text, open)) {
      if (taken.contains(i)) continue; // 已经按闭合写法收走了
      final after = i + open.length;
      if (after < text.length && !_isTagStop(text[after])) continue;
      hits.add(_Hit(i, after, FSegmentKind.tag, tag.tag));
    }
  }

  // 提及:`@超级赞号`,后面不能再跟号里合法的字符
  for (final mention in entities.mentions) {
    final at = '@${mention.username}';
    if (mention.username.isEmpty) continue;
    for (final i in _allIndexOf(text, at)) {
      final after = i + at.length;
      if (after < text.length && _isUsernameChar(text[after])) continue;
      hits.add(_Hit(i, after, FSegmentKind.mention, mention.username));
    }
  }

  if (hits.isEmpty) return [FSegment(text)];
  hits.sort((a, b) => a.start != b.start ? a.start - b.start : (b.end - b.start) - (a.end - a.start));

  final out = <FSegment>[];
  var at = 0;
  for (final h in hits) {
    if (h.start < at) continue; // 和前一个重叠,丢掉
    if (h.start > at) out.add(FSegment(text.substring(at, h.start)));
    out.add(FSegment(text.substring(h.start, h.end), kind: h.kind, value: h.value));
    at = h.end;
  }
  if (at < text.length) out.add(FSegment(text.substring(at)));
  return out;
}

/// [needle] 在 [haystack] 里出现的全部起点。
Iterable<int> _allIndexOf(String haystack, String needle) sync* {
  if (needle.isEmpty) return;
  var from = 0;
  while (true) {
    final i = haystack.indexOf(needle, from);
    if (i < 0) return;
    yield i;
    from = i + needle.length;
  }
}

/// 正文字数:按 Unicode 字符数、去掉首尾空白(§5.6)。
///
/// 不能用 `String.length` —— 那是 UTF-16 码元数,一个 emoji 会算成 2 个,
/// 用户数着 500 个字发不出去,还找不到是哪一个多了。
int forumTextLength(String text) => text.trim().runes.length;

/// 发帖能不能发:正文 1–500 字,有图 / 卡片 / 投票时正文可以为空(§5.6)。
/// 返回 null 表示能发,否则是给用户看的那句话。
String? forumTextError(String text, {bool hasMedia = false, bool hasCard = false, bool hasPoll = false}) {
  final n = forumTextLength(text);
  if (n > kPostMaxChars) return '最多 $kPostMaxChars 字,已经写了 $n 字';
  if (n == 0 && !hasMedia && !hasCard && !hasPoll) return '写点什么吧';
  return null;
}
