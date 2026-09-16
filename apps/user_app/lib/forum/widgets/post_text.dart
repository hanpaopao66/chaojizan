// 帖子正文:按服务端给的实体把 #话题、@超级赞号、链接画成可点的片段(§5.6)。
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';
import 'package:url_launcher/url_launcher.dart';

import '../entities.dart';
import '../models.dart';
import '../nav.dart';
import 'common.dart';

/// 正文富文本。
///
/// 点话题进话题页、点 @ 进那个人的论坛主页、点链接:本站的直接在 App 里开,
/// 站外的问一句再交给浏览器 —— 和聊天里的外链同一个口径,不替人点。
class PostText extends StatefulWidget {
  const PostText(this.text, this.entities, {super.key, this.maxLines, this.style, this.onTap});

  final String text;
  final FEntities entities;
  final int? maxLines;
  final TextStyle? style;

  /// 点在**普通字**上时做什么(整条帖子可点时传打开详情)
  final VoidCallback? onTap;

  @override
  State<PostText> createState() => _PostTextState();
}

class _PostTextState extends State<PostText> {
  /// TapGestureRecognizer 必须自己 dispose,不然每次重建都漏一个
  final _recognizers = <TapGestureRecognizer>[];

  @override
  void dispose() {
    for (final r in _recognizers) {
      r.dispose();
    }
    super.dispose();
  }

  void _clear() {
    for (final r in _recognizers) {
      r.dispose();
    }
    _recognizers.clear();
  }

  @override
  Widget build(BuildContext context) {
    if (widget.text.isEmpty) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    final base = widget.style ?? TextStyle(fontSize: kFontBodyLg, color: sz.ink, height: 1.55);
    final linkStyle = base.copyWith(color: sz.link);
    _clear();
    final spans = <InlineSpan>[];
    for (final seg in forumSegments(widget.text, widget.entities)) {
      if (seg.isPlain) {
        spans.add(TextSpan(text: seg.text, style: base));
        continue;
      }
      final r = TapGestureRecognizer()..onTap = () => _tap(seg);
      _recognizers.add(r);
      spans.add(TextSpan(text: seg.text, style: linkStyle, recognizer: r));
    }
    final rich = Text.rich(
      TextSpan(children: spans),
      maxLines: widget.maxLines,
      overflow: widget.maxLines == null ? TextOverflow.clip : TextOverflow.ellipsis,
    );
    // onTap 给了的话,普通字那部分也要能点开详情 —— 片段上的手势优先
    return widget.onTap == null
        ? rich
        : GestureDetector(behavior: HitTestBehavior.translucent, onTap: widget.onTap, child: rich);
  }

  Future<void> _tap(FSegment seg) async {
    switch (seg.kind) {
      case FSegmentKind.tag:
        // display 是作者原样写的,标题上用它;跳转按规范化的小写 tag
        await openTag(context, seg.value, display: seg.text.replaceAll('#', ''));
      case FSegmentKind.mention:
        final m = widget.entities.mentions.where((x) => x.username == seg.value);
        if (m.isEmpty) return;
        if (mounted) await openForumProfile(context, m.first.id);
      case FSegmentKind.link:
        await openForumOutLink(context, seg.value);
      case FSegmentKind.plain:
        break;
    }
  }
}

/// 帖子里的外链:本站的 `/forum/…` 直接在 App 里开;别的先问一句再交给浏览器。
///
/// 不问就跳的话,一条帖子里贴个链接就能把人带走 —— 站内链接是我们认得的,
/// 站外的得让人自己决定。
Future<void> openForumOutLink(BuildContext context, String raw) async {
  final uri = Uri.tryParse(raw);
  if (uri == null) return;
  if (handleForumLink(context, uri)) return;
  if (!context.mounted) return;
  final go = await szShowSheet<bool>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(kPagePad),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('要打开这个链接吗?', style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(raw, maxLines: 3, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontNote, color: Theme.of(ctx).sz.inkMuted)),
          const SizedBox(height: 16),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('打开')),
          const SizedBox(height: 8),
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
        ]),
      ),
    ),
  );
  if (go != true) return;
  try {
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  } catch (e) {
    if (context.mounted) fToast(context, '打不开这个链接');
  }
}
