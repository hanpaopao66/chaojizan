import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';

/// 消息正文里可点的东西被点了。
class TextTapHandlers {
  const TextTapHandlers({this.onUrl, this.onMention, this.onUserId, this.onHashtag});

  final void Function(String url)? onUrl;
  final void Function(String username)? onMention;
  final void Function(int userId)? onUserId;
  final void Function(String tag)? onHashtag;
}

/// 按实体渲染的消息正文(DEV-PROMPTS-40 §5.2:偏移按 UTF-16 码元,和 Dart 字符串下标一致)。
///
/// 实体可以嵌套(粗体里套链接),所以按「所有实体的起止点」把正文切成段,
/// 每段取覆盖它的全部实体叠样式。剧透默认盖住,点一下露出来(整条消息一起露)。
class MessageText extends StatefulWidget {
  const MessageText({
    super.key,
    required this.text,
    required this.entities,
    required this.style,
    this.handlers = const TextTapHandlers(),
    this.linkColor,
    this.maxLines,
    this.trailing,
  });

  final String text;
  final List<MsgEntity> entities;
  final TextStyle style;
  final TextTapHandlers handlers;
  final Color? linkColor;
  final int? maxLines;

  /// 接在正文最后的东西(时间、勾):让它和最后一行文字挤在一起,不单独占一行
  final InlineSpan? trailing;

  @override
  State<MessageText> createState() => _MessageTextState();
}

class _MessageTextState extends State<MessageText> {
  final List<TapGestureRecognizer> _recognizers = [];
  bool _revealed = false;

  void _clear() {
    for (final r in _recognizers) {
      r.dispose();
    }
    _recognizers.clear();
  }

  @override
  void dispose() {
    _clear();
    super.dispose();
  }

  TapGestureRecognizer _tap(VoidCallback f) {
    final r = TapGestureRecognizer()..onTap = f;
    _recognizers.add(r);
    return r;
  }

  @override
  Widget build(BuildContext context) {
    _clear();
    final sz = Theme.of(context).sz;
    final spans = buildSpans(
      context,
      widget.text,
      widget.entities,
      base: widget.style,
      linkColor: widget.linkColor ?? sz.link,
      revealed: _revealed,
      onReveal: () => setState(() => _revealed = true),
      tap: _tap,
      handlers: widget.handlers,
    );
    return Text.rich(
      TextSpan(style: widget.style, children: [...spans, if (widget.trailing != null) widget.trailing!]),
      maxLines: widget.maxLines,
      overflow: widget.maxLines == null ? TextOverflow.clip : TextOverflow.ellipsis,
    );
  }
}

/// 纯粹的切段 + 叠样式(单测直接调)。
List<InlineSpan> buildSpans(
  BuildContext context,
  String text,
  List<MsgEntity> entities, {
  required TextStyle base,
  required Color linkColor,
  bool revealed = false,
  VoidCallback? onReveal,
  TapGestureRecognizer Function(VoidCallback)? tap,
  TextTapHandlers handlers = const TextTapHandlers(),
}) {
  final valid = [
    for (final e in entities)
      if (e.offset >= 0 && e.length > 0 && e.offset + e.length <= text.length) e
  ];
  if (valid.isEmpty) return [TextSpan(text: text)];
  final cuts = <int>{0, text.length};
  for (final e in valid) {
    cuts
      ..add(e.offset)
      ..add(e.offset + e.length);
  }
  final points = cuts.toList()..sort();
  final dark = Theme.of(context).brightness == Brightness.dark;
  final codeBg = dark ? Colors.white.withValues(alpha: .10) : Colors.black.withValues(alpha: .06);
  final out = <InlineSpan>[];
  for (var i = 0; i < points.length - 1; i++) {
    final a = points[i], b = points[i + 1];
    if (a >= b) continue;
    final seg = text.substring(a, b);
    final active = [for (final e in valid) if (e.offset <= a && e.offset + e.length >= b) e];
    var style = const TextStyle();
    GestureRecognizer? rec;
    var spoiler = false;
    for (final e in active) {
      switch (e.type) {
        case 'bold':
          style = style.copyWith(fontWeight: FontWeight.w700);
        case 'italic':
          style = style.copyWith(fontStyle: FontStyle.italic);
        case 'underline':
          style = style.copyWith(
              decoration: TextDecoration.combine([
            if (style.decoration != null) style.decoration!,
            TextDecoration.underline
          ]));
        case 'strike':
          style = style.copyWith(
              decoration: TextDecoration.combine([
            if (style.decoration != null) style.decoration!,
            TextDecoration.lineThrough
          ]));
        case 'code':
        case 'pre':
          style = style.copyWith(fontFamily: 'monospace', backgroundColor: codeBg);
        case 'spoiler':
          spoiler = !revealed;
        case 'url':
          final url = seg.startsWith('http') ? seg : 'https://$seg';
          style = style.copyWith(color: linkColor, decoration: TextDecoration.underline);
          if (tap != null && handlers.onUrl != null) rec = tap(() => handlers.onUrl!(url));
        case 'text_link':
          style = style.copyWith(color: linkColor, decoration: TextDecoration.underline);
          final url = e.url ?? '';
          if (tap != null && handlers.onUrl != null && url.isNotEmpty) {
            rec = tap(() => handlers.onUrl!(url));
          }
        case 'mention':
          style = style.copyWith(color: linkColor);
          final name = seg.startsWith('@') ? seg.substring(1) : seg;
          if (tap != null && handlers.onMention != null) rec = tap(() => handlers.onMention!(name));
        case 'text_mention':
          style = style.copyWith(color: linkColor);
          final uid = e.userId;
          if (tap != null && handlers.onUserId != null && uid != null) {
            rec = tap(() => handlers.onUserId!(uid));
          }
        case 'hashtag':
          style = style.copyWith(color: linkColor);
          if (tap != null && handlers.onHashtag != null) rec = tap(() => handlers.onHashtag!(seg));
      }
    }
    if (spoiler) {
      final fg = base.color ?? Theme.of(context).sz.ink;
      out.add(TextSpan(
        text: seg,
        style: style.copyWith(color: Colors.transparent, backgroundColor: fg.withValues(alpha: .35)),
        recognizer: tap != null && onReveal != null ? tap(onReveal) : null,
      ));
      continue;
    }
    out.add(TextSpan(text: seg, style: style, recognizer: rec));
  }
  return out;
}
