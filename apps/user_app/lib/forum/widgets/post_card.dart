// 帖子里带的站内卡片(§5.9)和引用框(F2)。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';
import '../nav.dart';
import 'common.dart';
import 'post_text.dart';

/// 一张站内卡片:封面 + 标题 + 副标题。点开按 `url` 走站内链接。
///
/// 服务端查不到(删了、没过审、私密)时只给 `unavailable` —— 画灰条,
/// 不画一张点不开的空卡片。
class PostCardView extends StatelessWidget {
  const PostCardView(this.card, {super.key});

  final FCard card;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    if (card.unavailable) {
      return FUnavailableTile(text: '这条${card.typeName}已不可见', compact: true);
    }
    return InkWell(
      borderRadius: BorderRadius.circular(kRadiusMd),
      onTap: () => openForumOutLink(context, card.url),
      child: Container(
        decoration: BoxDecoration(
          border: Border.all(color: sz.line),
          borderRadius: BorderRadius.circular(kRadiusMd),
        ),
        clipBehavior: Clip.antiAlias,
        child: Row(children: [
          SzImage(url: forumResolve(card.cover), name: card.title, size: 64, radius: 0),
          const SizedBox(width: 10),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                Text(card.title.isEmpty ? card.typeName : card.title,
                    maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600)),
                if (card.subtitle.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(card.subtitle,
                        maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ),
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(card.typeName, style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
                ),
              ]),
            ),
          ),
          const SizedBox(width: 8),
        ]),
      ),
    );
  }
}

/// 引用框:被引的那条帖子缩一圈画在框里(不再嵌套它自己的引用)。
///
/// 被引的删了 / 下架了,引用照样在,框里只写「这条帖子已不可见」(§5.6)。
class QuoteBox extends StatelessWidget {
  const QuoteBox(this.quote, {super.key});

  final FPost quote;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    if (quote.unavailable) {
      return FUnavailableTile(text: quote.reason.isEmpty ? '这条帖子已不可见' : quote.unavailableText, compact: true);
    }
    final author = quote.author;
    return InkWell(
      borderRadius: BorderRadius.circular(kRadiusMd),
      onTap: () => openPost(context, quote.pid),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          border: Border.all(color: sz.line),
          borderRadius: BorderRadius.circular(kRadiusMd),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            SzImage(url: forumResolve(author?.avatar ?? ''), name: author?.name ?? '', size: 18, circle: true),
            const SizedBox(width: 6),
            Flexible(
              child: Text(author?.name ?? '',
                  maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: kFontNote, fontWeight: FontWeight.w600)),
            ),
            if ((author?.username ?? '').isNotEmpty) ...[
              const SizedBox(width: 4),
              Flexible(
                child: Text('@${author!.username}',
                    maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ),
            ],
            const FDot(),
            Text(vAgo(quote.createdAt), style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          ]),
          if (quote.text.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: PostText(quote.text, quote.entities,
                  maxLines: 4, style: TextStyle(fontSize: kFontBody, color: sz.ink, height: 1.5)),
            ),
          // 引用框里不再铺图:一条引用里套四张图,整条帖子会长得没法看。
          // 只给一句「1 张图片」,点进去看
          if (quote.media.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Row(children: [
                Icon(Icons.image_outlined, size: 14, color: sz.inkFaint),
                const SizedBox(width: 4),
                Text('${quote.media.length} 张图片', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ]),
            ),
        ]),
      ),
    );
  }
}
