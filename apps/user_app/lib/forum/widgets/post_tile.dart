// 一条帖子长什么样(§2.2 对标 X):头像、名字、@号、时间、「已编辑」、正文实体可点、
// 九宫格图、卡片、引用框、投票、操作栏。时间线、详情页、搜索结果、书签全用它。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart' show vConfirm, vDateTime;
import '../models.dart';
import '../nav.dart';
import 'common.dart';
import 'poll_view.dart';
import 'post_card.dart';
import 'post_media.dart';
import 'post_text.dart';
import 'report.dart';

/// 一条帖子。
///
/// 删了 / 下架了 / 拉黑关系的那一条,服务端只给 `{pid, unavailable, reason}`,
/// 这里画成一条灰条占位 —— **不能直接跳过**:回复串少一环,读起来就接不上了。
class PostTile extends StatefulWidget {
  const PostTile({
    super.key,
    required this.post,
    this.onChanged,
    this.onDeleted,
    this.onTap,
    this.detail = false,
    this.showActions = true,
    this.repostBy,
    this.repostAt,
    this.threadLine = false,
    this.showRank = false,
  });

  final FPost post;

  /// 这条帖子的状态变了(赞了、转发了、投票了):让外面的列表重画
  final VoidCallback? onChanged;

  /// 删掉了:让外面的列表把它移走
  final void Function(String pid)? onDeleted;

  /// 点整条(时间线里是打开详情;详情页本身不给)
  final VoidCallback? onTap;

  /// 详情页里的那一条:正文大一号、时间摊成整行、计数摊成一行
  final bool detail;
  final bool showActions;

  /// 转发条目:顶上那一行「小王 转发了」
  final VPerson? repostBy;
  final DateTime? repostAt;

  /// 串里的上文:头像下面画一条竖线连到下一条
  final bool threadLine;

  /// 推荐时间线:底下给一行「为什么推荐」
  final bool showRank;

  @override
  State<PostTile> createState() => _PostTileState();
}

class _PostTileState extends State<PostTile> {
  bool _busy = false;

  /// 投完票之后服务端重算的那一份。父列表里的 FPost 是 final,只能在这一层顶上
  FPoll? _poll;

  FPost get post => widget.post;

  FPoll? get poll => _poll ?? post.poll;

  bool get _isMine => rootApi.userId != null && post.author?.id == rootApi.userId;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    if (post.unavailable) return FUnavailableTile(text: post.unavailableText);
    final author = post.author;
    return InkWell(
      onTap: widget.onTap,
      child: Padding(
        padding: EdgeInsets.fromLTRB(kPagePad, 10, kPagePad, widget.showActions ? 2 : 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (widget.repostBy != null) _repostHeader(context, sz),
          if (post.pinned) _pinnedHeader(context, sz),
          if (widget.detail)
            _detailBody(context, sz, author)
          else
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Column(children: [
                GestureDetector(
                  onTap: author == null ? null : () => openForumProfile(context, author.id),
                  child: SzImage(
                      url: forumResolve(author?.avatar ?? ''),
                      name: author?.name ?? '',
                      size: 40,
                      circle: true),
                ),
                // 串里的竖线:上文那几条的头像底下连一条线,一眼看出是一串
                if (widget.threadLine)
                  Expanded(child: Container(width: 2, margin: const EdgeInsets.only(top: 4), color: sz.line)),
              ]),
              const SizedBox(width: 10),
              Expanded(child: _compactBody(context, sz, author)),
            ]),
        ]),
      ),
    );
  }

  Widget _repostHeader(BuildContext context, SzColors sz) => Padding(
        padding: const EdgeInsets.only(left: 30, bottom: 4),
        child: Row(children: [
          Icon(Icons.repeat, size: 13, color: sz.inkMuted),
          const SizedBox(width: 6),
          Flexible(
            child: GestureDetector(
              onTap: () => openForumProfile(context, widget.repostBy!.id),
              child: Text('${widget.repostBy!.name} 转发了',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, fontWeight: FontWeight.w600)),
            ),
          ),
          if (widget.repostAt != null) ...[
            const FDot(),
            Text(vAgo(widget.repostAt), style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          ],
        ]),
      );

  Widget _pinnedHeader(BuildContext context, SzColors sz) => Padding(
        padding: const EdgeInsets.only(left: 30, bottom: 4),
        child: Row(children: [
          Icon(Icons.push_pin_outlined, size: 13, color: sz.inkMuted),
          const SizedBox(width: 6),
          Text('置顶', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ]),
      );

  /// 时间线里的样子:头像在左,名字和时间挤在一行
  Widget _compactBody(BuildContext context, SzColors sz, VPerson? author) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Flexible(
          child: GestureDetector(
            onTap: author == null ? null : () => openForumProfile(context, author.id),
            child: Text(author?.name ?? '',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w700)),
          ),
        ),
        if ((author?.username ?? '').isNotEmpty) ...[
          const SizedBox(width: 4),
          Flexible(
            child: Text('@${author!.username}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ),
        ],
        const FDot(),
        Text(vAgo(post.createdAt), style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        if (post.edited) ...[
          const FDot(),
          GestureDetector(
            onTap: () => _openEdits(context),
            child: Text('已编辑', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          ),
        ],
        const Spacer(),
        _menu(context),
      ]),
      if (post.isReply && post.replyToAuthor != null)
        Padding(
          padding: const EdgeInsets.only(top: 2),
          child: Text('回复 @${post.replyToAuthor!.username ?? post.replyToAuthor!.name}',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
      ..._content(context, sz),
      if (widget.showActions) _actions(context, sz),
      if (widget.showRank) _rankLine(context, sz),
    ]);
  }

  /// 详情页里那一条:头像和名字占一整行,正文大一号,时间和计数各占一行
  Widget _detailBody(BuildContext context, SzColors sz, VPerson? author) {
    final created = post.createdAt;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        GestureDetector(
          onTap: author == null ? null : () => openForumProfile(context, author.id),
          child: SzImage(
              url: forumResolve(author?.avatar ?? ''), name: author?.name ?? '', size: 44, circle: true),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: GestureDetector(
            onTap: author == null ? null : () => openForumProfile(context, author.id),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(author?.name ?? '',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w700)),
              if ((author?.username ?? '').isNotEmpty)
                Text('@${author!.username}',
                    maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ]),
          ),
        ),
        _menu(context),
      ]),
      if (post.isReply && post.replyToAuthor != null)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text('回复 @${post.replyToAuthor!.username ?? post.replyToAuthor!.name}',
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        ),
      ..._content(context, sz, big: true),
      const SizedBox(height: 10),
      Row(children: [
        if (created != null)
          Text(vDateTime(created), style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        if (post.edited) ...[
          const FDot(),
          GestureDetector(
            onTap: () => _openEdits(context),
            child: Text('已编辑', style: TextStyle(fontSize: kFontNote, color: sz.link)),
          ),
        ],
        const FDot(),
        Text('${post.counts.views} 次浏览', style: szTabular(fontSize: kFontNote, color: sz.inkMuted)),
      ]),
      const SizedBox(height: 8),
      Divider(height: 1, color: sz.line),
      _detailCounts(context, sz),
      Divider(height: 1, color: sz.line),
      if (widget.showActions) _actions(context, sz),
    ]);
  }

  /// 正文 + 图 + 卡片 + 引用 + 投票
  List<Widget> _content(BuildContext context, SzColors sz, {bool big = false}) {
    final style = big
        ? TextStyle(fontSize: kFontTitle, color: sz.ink, height: 1.6)
        : TextStyle(fontSize: kFontBodyLg, color: sz.ink, height: 1.55);
    return [
      if (post.text.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: PostText(post.text, post.entities, style: style, onTap: widget.onTap),
        ),
      if (post.media.isNotEmpty)
        Padding(padding: const EdgeInsets.only(top: 8), child: PostMedia(post.media)),
      if (post.card != null)
        Padding(padding: const EdgeInsets.only(top: 8), child: PostCardView(post.card!)),
      if (post.quote != null)
        Padding(padding: const EdgeInsets.only(top: 8), child: QuoteBox(post.quote!)),
      if (poll != null)
        Padding(
          padding: const EdgeInsets.only(top: 10),
          child: PollView(poll!, busy: _busy, onVote: _vote),
        ),
    ];
  }

  Widget _detailCounts(BuildContext context, SzColors sz) {
    final c = post.counts;
    Widget one(String n, String label, VoidCallback? onTap) => InkWell(
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Text(n, style: szTabular(fontSize: kFontBody, fontWeight: FontWeight.w700, color: sz.ink)),
              const SizedBox(width: 3),
              Text(label, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ]),
          ),
        );
    return Wrap(spacing: 10, children: [
      one('${c.reposts}', '转发', null),
      one('${c.quotes}', '引用', c.quotes > 0 ? () => openQuotes(context, post.pid) : null),
      one('${c.likes}', '赞', c.likes > 0 ? () => openLikers(context, post.pid) : null),
      one('${c.bookmarks}', '书签', null),
    ]);
  }

  Widget _rankLine(BuildContext context, SzColors sz) {
    final why = fRankWhy(post.rank);
    if (why.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 2, bottom: 4),
      child: Text('为什么推荐:$why', style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
    );
  }

  /// 操作栏:回复 / 转发 / 赞 / 浏览 / 书签 / 分享
  Widget _actions(BuildContext context, SzColors sz) {
    final c = post.counts;
    final v = post.viewer;
    // 「谁能回复」限制到我头上了(F4):按钮置灰,点一下说明为什么
    final canReply = post.canReply;
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        FActionButton(
          icon: Icons.mode_comment_outlined,
          count: c.replies,
          tooltip: canReply ? '回复' : '只有${post.replyPolicyName}能回复',
          onTap: canReply ? () => _reply(context) : () => _whyCantReply(context),
        ),
        FActionButton(
          icon: Icons.repeat,
          count: c.reposts + c.quotes,
          active: v.reposted,
          activeColor: sz.earn,
          tooltip: '转发',
          onTap: _busy ? null : () => _repostMenu(context),
        ),
        FActionButton(
          icon: Icons.favorite_outline,
          activeIcon: Icons.favorite,
          count: c.likes,
          active: v.liked,
          activeColor: sz.danger,
          tooltip: '赞',
          onTap: _busy ? null : () => _like(context),
        ),
        if (!widget.detail)
          FActionButton(
            icon: Icons.bar_chart,
            count: c.views,
            showZero: true,
            tooltip: '浏览',
            onTap: null,
          ),
        FActionButton(
          icon: Icons.bookmark_border,
          activeIcon: Icons.bookmark,
          active: v.bookmarked,
          tooltip: '书签(只有你看得到)',
          onTap: _busy ? null : () => _bookmark(context),
        ),
        FActionButton(
          icon: Icons.ios_share,
          tooltip: '分享',
          onTap: () => shareForumPost(context, post),
        ),
      ]),
    );
  }

  Widget _menu(BuildContext context) {
    final mine = _isMine;
    final canEdit = mine && fCanEdit(post);
    return PopupMenuButton<String>(
      icon: Icon(Icons.more_horiz, size: 18, color: Theme.of(context).sz.inkMuted),
      padding: EdgeInsets.zero,
      tooltip: '更多',
      onSelected: (v) => _onMenu(context, v),
      itemBuilder: (_) => [
        if (canEdit) const PopupMenuItem(value: 'edit', child: Text('编辑')),
        if (post.edited) const PopupMenuItem(value: 'edits', child: Text('编辑历史')),
        if (mine) PopupMenuItem(value: 'pin', child: Text(post.pinned ? '取消置顶' : '置顶到主页')),
        const PopupMenuItem(value: 'copy', child: Text('复制链接')),
        if (!mine) const PopupMenuItem(value: 'report', child: Text('举报')),
        if (mine) const PopupMenuItem(value: 'appeal', child: Text('对下架申诉')),
        if (mine) const PopupMenuItem(value: 'delete', child: Text('删除')),
      ],
    );
  }

  Future<void> _onMenu(BuildContext context, String v) async {
    switch (v) {
      case 'edit':
        await _edit(context);
      case 'edits':
        await _openEdits(context);
      case 'pin':
        await _pin(context);
      case 'copy':
        await shareForumPost(context, post);
      case 'report':
        await reportForumPost(context, post.pid);
      case 'appeal':
        await appealForumPost(context, post.pid);
      case 'delete':
        await _delete(context);
    }
  }

  void _whyCantReply(BuildContext context) =>
      fToast(context, '这条帖子只有${post.replyPolicyName}能回复');

  Future<void> _reply(BuildContext context) async {
    final made = await openCompose(context, replyToPid: post.pid, origin: post);
    if (made == null) return;
    post.counts.replies++;
    widget.onChanged?.call();
    if (mounted) setState(() {});
  }

  Future<void> _repostMenu(BuildContext context) async {
    if (!await ensureLoggedIn(context)) return;
    if (!context.mounted) return;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (post.viewer.reposted)
            ListTile(leading: const Icon(Icons.repeat), title: const Text('取消转发'),
                onTap: () => Navigator.pop(ctx, 'unrepost'))
          else
            ListTile(leading: const Icon(Icons.repeat), title: const Text('转发'),
                onTap: () => Navigator.pop(ctx, 'repost')),
          ListTile(leading: const Icon(Icons.format_quote), title: const Text('引用'),
              onTap: () => Navigator.pop(ctx, 'quote')),
        ]),
      ),
    );
    if (pick == null || !context.mounted) return;
    if (pick == 'quote') {
      final made = await openCompose(context, quotePid: post.pid, origin: post);
      if (made != null) {
        post.counts.quotes++;
        widget.onChanged?.call();
        if (mounted) setState(() {});
      }
      return;
    }
    await _repost(context, pick == 'repost');
  }

  Future<void> _repost(BuildContext context, bool on) async {
    final v = post.viewer;
    final before = v.reposted;
    final beforeCount = post.counts.reposts;
    // 先画上,失败再退回去 —— 点一下等一个来回才变色,手感太黏
    setState(() {
      _busy = true;
      v.reposted = on;
      post.counts.reposts = (beforeCount + (on ? 1 : -1)).clamp(0, 1 << 30);
    });
    try {
      final r = await forumApi.repost(post.pid, on);
      v.reposted = r['reposted'] == true;
      post.counts.reposts = vInt(r['reposts']);
      widget.onChanged?.call();
    } on ApiException catch (e) {
      v.reposted = before;
      post.counts.reposts = beforeCount;
      if (context.mounted) fToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _like(BuildContext context) async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    final v = post.viewer;
    final before = v.liked;
    final beforeCount = post.counts.likes;
    setState(() {
      _busy = true;
      v.liked = !before;
      post.counts.likes = (beforeCount + (before ? -1 : 1)).clamp(0, 1 << 30);
    });
    try {
      final r = await forumApi.like(post.pid, !before);
      v.liked = r['liked'] == true;
      post.counts.likes = vInt(r['likes']);
      widget.onChanged?.call();
    } on ApiException catch (e) {
      v.liked = before;
      post.counts.likes = beforeCount;
      if (context.mounted) fToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _bookmark(BuildContext context) async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    final v = post.viewer;
    final before = v.bookmarked;
    setState(() {
      _busy = true;
      v.bookmarked = !before;
    });
    try {
      final r = await forumApi.bookmark(post.pid, !before);
      v.bookmarked = r['bookmarked'] == true;
      widget.onChanged?.call();
      if (context.mounted) fToast(context, v.bookmarked ? '已加书签,只有你看得到' : '已取消书签');
    } on ApiException catch (e) {
      v.bookmarked = before;
      if (context.mounted) fToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _vote(int option) async {
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    setState(() => _busy = true);
    try {
      // 投完才给票数(§8.1),所以要拿服务端重算的这一份换掉手里的
      final next = await forumApi.vote(post.pid, option);
      widget.onChanged?.call();
      if (mounted) setState(() => _poll = next);
    } on ApiException catch (e) {
      if (mounted) fToast(context, e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _edit(BuildContext context) async {
    final made = await openCompose(context, edit: post);
    if (made != null) widget.onChanged?.call();
  }

  Future<void> _openEdits(BuildContext context) => openEdits(context, post.pid);

  Future<void> _pin(BuildContext context) async {
    try {
      await forumApi.pin(post.pid, !post.pinned);
      if (context.mounted) fToast(context, post.pinned ? '已取消置顶' : '已置顶到主页');
      widget.onChanged?.call();
    } on ApiException catch (e) {
      if (context.mounted) fToast(context, e.message);
    }
  }

  Future<void> _delete(BuildContext context) async {
    final ok = await vConfirm(context,
        title: '删掉这条帖子?', body: '下面的回复会留着,这一条显示「这条帖子已删除」。', ok: '删除', danger: true);
    if (!ok || !context.mounted) return;
    try {
      await forumApi.deletePost(post.pid);
      widget.onDeleted?.call(post.pid);
      if (context.mounted) fToast(context, '已删除');
    } on ApiException catch (e) {
      if (context.mounted) fToast(context, e.message);
    }
  }
}
