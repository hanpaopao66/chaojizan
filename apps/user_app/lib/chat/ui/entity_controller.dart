import 'package:flutter/material.dart';

import '../models.dart';

/// 带格式的输入框控制器:文字 + 一组格式实体(粗体、斜体、链接……)。
///
/// 输入框里改了字,实体的位置要跟着挪:算出这次改动在哪(公共前缀 / 后缀),
/// 改动之后的实体整体平移,落在被删掉那一段里的实体裁掉。偏移按 UTF-16 码元,
/// 和 Dart 字符串下标、服务端 §5.2 一致,所以发出去不用再换算。
class EntityTextController extends TextEditingController {
  EntityTextController({super.text}) {
    _last = text;
  }

  List<MsgEntity> entities = [];
  String _last = '';

  static const formatTypes = ['bold', 'italic', 'underline', 'strike', 'spoiler', 'code'];

  @override
  set value(TextEditingValue newValue) {
    final old = _last;
    final now = newValue.text;
    if (old != now) {
      entities = shiftEntities(entities, old, now);
      _last = now;
    }
    super.value = newValue;
  }

  /// 给选中的一段加 / 去掉某种格式(已经整段是这个格式就去掉)。
  void toggle(String type, {String? url}) {
    final sel = selection;
    if (!sel.isValid || sel.isCollapsed) return;
    final a = sel.start, b = sel.end;
    final exact = entities.where((e) => e.type == type && e.offset == a && e.length == b - a).toList();
    if (exact.isNotEmpty) {
      entities = [...entities]..removeWhere(exact.contains);
    } else {
      entities = [
        ...entities.where((e) => !(e.type == type && e.offset < b && e.offset + e.length > a)),
        MsgEntity(type, a, b - a, url: url),
      ];
    }
    notifyListeners();
  }

  void clearAll() {
    entities = [];
    _last = '';
    clear();
  }

  void setWith(String text, List<MsgEntity> ents) {
    _last = text;
    entities = [for (final e in ents) if (formatTypes.contains(e.type) || e.type == 'text_link' || e.type == 'text_mention') e];
    value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: text.length));
  }

  /// 发出去的实体:去掉空的、越界的,按位置排好。
  List<MsgEntity> outgoing() {
    final t = text;
    final out = [
      for (final e in entities)
        if (e.length > 0 && e.offset >= 0 && e.offset + e.length <= t.length) e
    ]..sort((x, y) => x.offset != y.offset ? x.offset.compareTo(y.offset) : y.length.compareTo(x.length));
    return out;
  }

  @override
  TextSpan buildTextSpan({required BuildContext context, TextStyle? style, required bool withComposing}) {
    if (entities.isEmpty) {
      return super.buildTextSpan(context: context, style: style, withComposing: withComposing);
    }
    final t = text;
    final cuts = <int>{0, t.length};
    for (final e in entities) {
      if (e.offset >= 0 && e.offset + e.length <= t.length) {
        cuts
          ..add(e.offset)
          ..add(e.offset + e.length);
      }
    }
    final pts = cuts.toList()..sort();
    final link = Theme.of(context).colorScheme.primary;
    final children = <TextSpan>[];
    for (var i = 0; i < pts.length - 1; i++) {
      final a = pts[i], b = pts[i + 1];
      if (a >= b) continue;
      var s = const TextStyle();
      for (final e in entities) {
        if (e.offset <= a && e.offset + e.length >= b) {
          s = switch (e.type) {
            'bold' => s.copyWith(fontWeight: FontWeight.w700),
            'italic' => s.copyWith(fontStyle: FontStyle.italic),
            'underline' => s.copyWith(decoration: TextDecoration.underline),
            'strike' => s.copyWith(decoration: TextDecoration.lineThrough),
            'code' => s.copyWith(fontFamily: 'monospace'),
            'spoiler' => s.copyWith(backgroundColor: link.withValues(alpha: .18)),
            'text_link' || 'text_mention' => s.copyWith(color: link),
            _ => s,
          };
        }
      }
      children.add(TextSpan(text: t.substring(a, b), style: s));
    }
    return TextSpan(style: style, children: children);
  }
}

/// 发送前把 Markdown 记号换成格式(和 Telegram 一样):`**粗体**`、`__斜体__`、`~~删除线~~`、
/// `||剧透||`、`` `代码` ``、```` ```语言\n代码块``` ````。
///
/// 纯函数(单测锁住):返回去掉记号之后的文字和实体;[existing] 是用户用选中菜单加的格式,跟着挪。
/// 几条规矩,都是为了不误伤普通文字:
/// - 记号里面要有字,而且不能以空格开头或结尾(`2 ** 3 ** 4` 不算粗体);
/// - `__` 两边要是非字母数字(`snake__case__name` 不动);
/// - 代码、代码块里面不再解析;链接(http://、https://、www.)里面不解析 —— `/__init__/` 是路径不是斜体。
(String, List<MsgEntity>) parseMarkdown(String src, List<MsgEntity> existing) {
  var text = src;
  var ents = [...existing];

  void del(int a, int n) {
    text = text.replaceRange(a, a + n, '');
    final out = <MsgEntity>[];
    for (final e in ents) {
      final s = e.offset < a ? e.offset : (e.offset < a + n ? a : e.offset - n);
      final end0 = e.offset + e.length;
      final t = end0 <= a ? end0 : (end0 <= a + n ? a : end0 - n);
      if (t > s) out.add(MsgEntity(e.type, s, t - s, url: e.url, userId: e.userId, language: e.language));
    }
    ents = out;
  }

  bool overlapsCode(int a, int b) =>
      ents.any((e) => (e.type == 'code' || e.type == 'pre') && e.offset < b && e.offset + e.length > a);

  bool insideLink(int a, int b) {
    for (final m in RegExp(r'(https?://|www\.)\S+', caseSensitive: false).allMatches(text)) {
      if (m.start < b && m.end > a) return true;
    }
    return false;
  }

  // 1. 代码块
  final fence = RegExp(r'```([\s\S]+?)```');
  var from = 0;
  while (true) {
    final m = fence.allMatches(text, from).firstOrNull;
    if (m == null) break;
    var inner = m.group(1)!;
    var open = 3;
    String? lang;
    final lm = RegExp(r'^([A-Za-z0-9_+\-]{1,20})\n').firstMatch(inner);
    if (lm != null) {
      lang = lm.group(1);
      open += lm.end;
      inner = inner.substring(lm.end);
    } else if (inner.startsWith('\n')) {
      open += 1;
      inner = inner.substring(1);
    }
    var close = 3;
    if (inner.endsWith('\n') && inner.length > 1) {
      close += 1;
      inner = inner.substring(0, inner.length - 1);
    }
    if (inner.trim().isEmpty) {
      from = m.end;
      continue;
    }
    final start = m.start;
    del(m.end - close, close);
    del(start, open);
    ents.add(MsgEntity('pre', start, inner.length, language: lang));
    from = start + inner.length;
  }

  // 2. 行内代码
  final tick = RegExp(r'`([^`\n]+)`');
  from = 0;
  while (true) {
    final m = tick.allMatches(text, from).firstOrNull;
    if (m == null) break;
    if (overlapsCode(m.start, m.end)) {
      from = m.end;
      continue;
    }
    final len = m.group(1)!.length;
    final start = m.start;
    del(m.end - 1, 1);
    del(start, 1);
    ents.add(MsgEntity('code', start, len));
    from = start + len;
  }

  // 3. 成对记号
  for (final (mark, type) in const [('**', 'bold'), ('__', 'italic'), ('~~', 'strike'), ('||', 'spoiler')]) {
    final q = RegExp.escape(mark);
    final re = RegExp('$q(\\S(?:[\\s\\S]*?\\S)?)$q');
    from = 0;
    while (true) {
      final m = re.allMatches(text, from).firstOrNull;
      if (m == null) break;
      var ok = !overlapsCode(m.start, m.end) && !insideLink(m.start, m.end);
      if (ok && mark == '__') {
        final before = m.start > 0 ? text[m.start - 1] : ' ';
        final after = m.end < text.length ? text[m.end] : ' ';
        final word = RegExp(r'[A-Za-z0-9]');
        ok = !word.hasMatch(before) && !word.hasMatch(after);
      }
      if (!ok) {
        from = m.start + 1;
        continue;
      }
      final len = m.group(1)!.length;
      final start = m.start;
      del(m.end - mark.length, mark.length);
      del(start, mark.length);
      ents.add(MsgEntity(type, start, len));
      from = start;
    }
  }
  // 4. 首尾空白去掉(实体跟着挪 / 裁),和服务端存的保持一致;代码块里的缩进不动
  final pres = ents.where((e) => e.type == 'pre');
  var lead = text.length - text.trimLeft().length;
  for (final p in pres) {
    if (p.offset < lead) lead = p.offset;
  }
  if (lead > 0) del(0, lead);
  var keep = text.trimRight().length;
  for (final p in ents.where((e) => e.type == 'pre')) {
    if (p.offset + p.length > keep) keep = p.offset + p.length;
  }
  if (keep < text.length) del(keep, text.length - keep);
  ents.sort((x, y) => x.offset != y.offset ? x.offset.compareTo(y.offset) : y.length.compareTo(x.length));
  return (text, ents);
}

/// 纯函数:文字从 [old] 改成 [now] 之后,实体怎么挪(单测锁住)。
List<MsgEntity> shiftEntities(List<MsgEntity> entities, String old, String now) {
  if (entities.isEmpty) return entities;
  var p = 0;
  final minLen = old.length < now.length ? old.length : now.length;
  while (p < minLen && old.codeUnitAt(p) == now.codeUnitAt(p)) {
    p++;
  }
  var s = 0;
  while (s < minLen - p &&
      old.codeUnitAt(old.length - 1 - s) == now.codeUnitAt(now.length - 1 - s)) {
    s++;
  }
  final delStart = p, delEnd = old.length - s; // 旧文字里被替换掉的 [delStart, delEnd)
  final insLen = now.length - s - p; // 新插进来的长度
  final out = <MsgEntity>[];
  for (final e in entities) {
    var a = e.offset, b = e.offset + e.length;
    if (b <= delStart) {
      // 在改动之前:不动
    } else if (a >= delEnd) {
      a += insLen - (delEnd - delStart);
      b += insLen - (delEnd - delStart);
    } else {
      // 和改动有交叠:在实体内部打字 → 实体跟着变长;删掉的部分裁掉
      final newA = a < delStart ? a : delStart;
      final tail = b > delEnd ? b - delEnd : 0;
      final head = delStart - newA;
      final inside = a <= delStart && b >= delEnd;
      b = newA + head + (inside ? insLen : 0) + tail;
      a = newA;
    }
    if (b > a && b <= now.length) {
      out.add(MsgEntity(e.type, a, b - a, url: e.url, userId: e.userId, language: e.language));
    }
  }
  return out;
}
