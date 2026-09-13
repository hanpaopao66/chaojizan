import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/ui/avatar.dart';
import '../../session.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/report.dart';

/// 视频评论(#362):楼中楼(一级评论 + 回复,回复里显示「回复 @某人」)、赞 / 踩(踩数不显示)、
/// 热度 / 时间排序、UP 主置顶一条、UP 主删自己视频下的评论、作者标「UP 主」、@ 提及高亮。
/// 详情页的「评论」页签和竖屏流的评论弹层共用。
class VideoComments extends StatefulWidget {
  const VideoComments({super.key, required this.vid, required this.uploaderId, this.allowComments = true,
      this.focusCommentId, this.focusRootId, this.scrollController, this.onCount});

  final String vid;
  final int uploaderId;
  final bool allowComments;

  /// 互动消息跳过来:定位到这条(在第一页里就高亮;是楼里的回复就打开那一楼 [focusRootId])
  final int? focusCommentId;
  final int? focusRootId;
  final ScrollController? scrollController;
  final void Function(int count)? onCount;

  @override
  State<VideoComments> createState() => _VideoCommentsState();
}

class _VideoCommentsState extends State<VideoComments> with AutomaticKeepAliveClientMixin {
  final List<VComment> _items = [];
  String _sort = 'hot';
  String? _cursor;
  bool _more = true;
  bool _loading = false;
  Object? _error;
  int _count = 0;
  bool _allow = true;
  int? _highlight;
  bool _focusDone = false;

  bool get _isUp => rootApi.userId == widget.uploaderId;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _allow = widget.allowComments;
    _highlight = widget.focusCommentId;
    _reload();
  }

  Future<void> _reload() async {
    _items.clear();
    _cursor = null;
    _more = true;
    await _loadMore();
    final f = widget.focusCommentId, root = widget.focusRootId;
    if (!_focusDone && f != null && root != null && root != f && mounted) {
      // 楼里的回复:直接打开那一楼并高亮它(只看一级评论的第一页多半找不到它);只在第一次打开时跳
      _focusDone = true;
      await _openReplies(root, focus: f);
    }
  }

  Future<void> _loadMore() async {
    if (_loading || !_more) return;
    setState(() => _loading = true);
    try {
      final r = await videoApi.comments(widget.vid, sort: _sort, cursor: _cursor);
      if (!mounted) return;
      setState(() {
        _items.addAll(r.items.where((c) => !_items.any((x) => x.id == c.id)));
        _cursor = r.nextCursor;
        _more = r.nextCursor != null;
        _count = vInt(r.extra['count']);
        _allow = r.extra['allow_comments'] != false;
        _error = null;
      });
      widget.onCount?.call(_count);
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _toast(String s) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  Future<void> _compose({VComment? replyTo}) async {
    if (!_allow) {
      _toast('UP 主关闭了这个视频的评论');
      return;
    }
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    final text = await showCommentInput(context, hint: replyTo == null ? '发一条友善的评论' : '回复 @${replyTo.user.name}');
    if (text == null || text.trim().isEmpty) return;
    try {
      final c = await videoApi.comment(widget.vid, text.trim(), parentId: replyTo?.id);
      if (!mounted) return;
      setState(() {
        if (replyTo == null) {
          // 新评论放最上面(置顶的下面)
          final at = _items.indexWhere((x) => !x.pinned);
          _items.insert(at < 0 ? _items.length : at, c);
        } else {
          final root = _items.firstWhere((x) => x.id == (replyTo.rootId ?? replyTo.id), orElse: () => replyTo);
          root.replyCount += 1;
          root.replies = [...root.replies, c];
        }
        _count += 1;
      });
      widget.onCount?.call(_count);
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _vote(VComment c, int v) async {
    if (!await ensureLoggedIn(context)) return;
    final next = c.myVote == v ? 0 : v;
    try {
      final r = await videoApi.voteComment(c.id, next);
      if (mounted) {
        setState(() {
          c.likes = vInt(r['likes']);
          c.myVote = vInt(r['my_vote']);
        });
      }
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _menu(VComment c) async {
    final mine = rootApi.userId == c.user.id;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.reply_outlined), title: const Text('回复'), onTap: () => Navigator.pop(ctx, 'reply')),
          ListTile(leading: const Icon(Icons.copy), title: const Text('复制'), onTap: () => Navigator.pop(ctx, 'copy')),
          if (_isUp && c.rootId == null)
            ListTile(
                leading: Icon(c.pinned ? Icons.push_pin : Icons.push_pin_outlined),
                title: Text(c.pinned ? '取消置顶' : '置顶'),
                onTap: () => Navigator.pop(ctx, 'pin')),
          if (mine || _isUp)
            ListTile(
                leading: Icon(Icons.delete_outline, color: Theme.of(ctx).sz.danger),
                title: Text('删除', style: TextStyle(color: Theme.of(ctx).sz.danger)),
                onTap: () => Navigator.pop(ctx, 'delete')),
          if (!mine)
            ListTile(leading: const Icon(Icons.flag_outlined), title: const Text('举报'), onTap: () => Navigator.pop(ctx, 'report')),
        ]),
      ),
    );
    if (pick == null || !mounted) return;
    try {
      switch (pick) {
        case 'reply':
          await _compose(replyTo: c);
        case 'copy':
          await Clipboard.setData(ClipboardData(text: c.text));
          _toast('已复制');
        case 'pin':
          await videoApi.pinComment(c.id, !c.pinned);
          await _reload();
        case 'delete':
          final ok = await showDialog<bool>(
            context: context,
            builder: (ctx) => SzDialog(
              title: const Text('删除这条评论?'),
              content: Text(c.rootId == null ? '楼里的回复会一起不再显示。' : '删掉就没有了。'),
              actions: [
                TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
                FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('删除')),
              ],
            ),
          );
          if (ok != true) return;
          await videoApi.deleteComment(c.id);
          setState(() {
            _items.removeWhere((x) => x.id == c.id);
            for (final x in _items) {
              if (x.replies.any((r) => r.id == c.id)) {
                x.replies = x.replies.where((r) => r.id != c.id).toList();
                x.replyCount = (x.replyCount - 1).clamp(0, 1 << 30);
              }
            }
          });
        case 'report':
          if (!await ensureLoggedIn(context)) return;
          if (mounted) await reportTarget(context, targetType: 'comment', targetId: c.id);
      }
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _openReplies(int rootOrReplyId, {int? focus}) async {
    await Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => _RepliesPage(
        commentId: rootOrReplyId,
        vid: widget.vid,
        uploaderId: widget.uploaderId,
        allowComments: _allow,
        focusId: focus,
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final sz = Theme.of(context).sz;
    return Column(children: [
      Expanded(
        child: NotificationListener<ScrollNotification>(
          onNotification: (n) {
            if (n.metrics.pixels > n.metrics.maxScrollExtent - 300) _loadMore();
            return false;
          },
          child: ListView.builder(
            controller: widget.scrollController,
            itemCount: _items.length + 2,
            itemBuilder: (context, i) {
              if (i == 0) {
                return Padding(
                  padding: const EdgeInsets.fromLTRB(kPagePad, 8, 8, 0),
                  child: Row(children: [
                    Text('评论 $_count', style: const TextStyle(fontWeight: FontWeight.w600)),
                    const Spacer(),
                    TextButton.icon(
                      icon: const Icon(Icons.sort, size: 18),
                      label: Text(_sort == 'hot' ? '按热度' : '按时间'),
                      onPressed: () {
                        setState(() => _sort = _sort == 'hot' ? 'new' : 'hot');
                        _reload();
                      },
                    ),
                  ]),
                );
              }
              if (i == _items.length + 1) {
                return Padding(
                  padding: const EdgeInsets.all(20),
                  child: Center(
                    child: _loading
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                        : (_error != null
                            ? TextButton(onPressed: _loadMore, child: const Text('没加载出来,点这里重试'))
                            : Text(_items.isEmpty ? (_allow ? '还没有评论,来抢第一条' : 'UP 主关闭了评论') : (_more ? '' : '没有更多了'),
                                style: TextStyle(color: sz.inkFaint, fontSize: kFontNote))),
                  ),
                );
              }
              final c = _items[i - 1];
              return CommentTile(
                comment: c,
                highlight: _highlight == c.id,
                onVote: (v) => _vote(c, v),
                onReply: () => _compose(replyTo: c),
                onMore: () => _menu(c),
                onOpenReplies: () => _openReplies(c.id),
                onReplyMore: (r) => _menu(r),
              );
            },
          ),
        ),
      ),
      SafeArea(
        top: false,
        child: InkWell(
          onTap: () => _compose(),
          child: Container(
            margin: const EdgeInsets.fromLTRB(12, 6, 12, 8),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(color: sz.surfaceAlt, borderRadius: BorderRadius.circular(20)),
            child: Row(children: [
              Text(_allow ? '发一条友善的评论' : 'UP 主关闭了评论', style: TextStyle(color: sz.inkMuted)),
            ]),
          ),
        ),
      ),
    ]);
  }
}

/// 一条评论(一级评论带前 3 条回复的预览)。
class CommentTile extends StatelessWidget {
  const CommentTile({super.key, required this.comment, required this.onVote, required this.onReply,
      required this.onMore, this.onOpenReplies, this.onReplyMore, this.highlight = false, this.isReply = false});

  final VComment comment;
  final void Function(int vote) onVote;
  final VoidCallback onReply;
  final VoidCallback onMore;
  final VoidCallback? onOpenReplies;
  final void Function(VComment reply)? onReplyMore;
  final bool highlight;
  final bool isReply;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final c = comment;
    return Container(
      color: highlight ? sz.claySoft.withValues(alpha: .6) : null,
      padding: EdgeInsets.fromLTRB(isReply ? 56 : kPagePad, 10, kPagePad, 6),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        GestureDetector(
          onTap: () => openUpSpace(context, c.user.id),
          child: ChatAvatar(name: c.user.name, url: c.user.avatar, size: isReply ? 28 : 36),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Flexible(
                child: Text(c.user.name,
                    maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ),
              if (c.isUp)
                Container(
                  margin: const EdgeInsets.only(left: 4),
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  decoration: BoxDecoration(border: Border.all(color: sz.clay), borderRadius: BorderRadius.circular(3)),
                  child: Text('UP 主', style: TextStyle(fontSize: kFontMicro, color: sz.clay)),
                ),
              if (c.pinned)
                Container(
                  margin: const EdgeInsets.only(left: 4),
                  padding: const EdgeInsets.symmetric(horizontal: 4),
                  decoration: BoxDecoration(color: sz.clay, borderRadius: BorderRadius.circular(3)),
                  child: const Text('置顶', style: TextStyle(fontSize: kFontMicro, color: Colors.white)),
                ),
            ]),
            const SizedBox(height: 3),
            GestureDetector(
              onLongPress: onMore,
              child: Text.rich(TextSpan(children: [
                if (c.replyTo != null)
                  TextSpan(text: '回复 @${c.replyTo!['name'] ?? ''}:', style: TextStyle(color: sz.link)),
                ...mentionSpans(c.text, c.mentions, sz.link),
              ]), style: const TextStyle(fontSize: kFontBodyLg, height: 1.4)),
            ),
            const SizedBox(height: 4),
            Row(children: [
              Text(vAgo(c.createdAt), style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
              const SizedBox(width: 12),
              _VoteButton(icon: c.myVote == 1 ? Icons.thumb_up : Icons.thumb_up_outlined, active: c.myVote == 1,
                  label: c.likes > 0 ? vCount(c.likes) : '', onTap: () => onVote(1)),
              const SizedBox(width: 10),
              // 踩数不对外(#362):只显示我踩没踩
              _VoteButton(icon: c.myVote == -1 ? Icons.thumb_down : Icons.thumb_down_outlined, active: c.myVote == -1,
                  label: '', onTap: () => onVote(-1)),
              const SizedBox(width: 10),
              InkWell(onTap: onReply, child: Icon(Icons.chat_bubble_outline, size: 16, color: sz.inkFaint)),
              const Spacer(),
              InkWell(onTap: onMore, child: Icon(Icons.more_vert, size: 18, color: sz.inkFaint)),
            ]),
            if (!isReply && (c.replies.isNotEmpty || c.replyCount > 0))
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(top: 6),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(color: sz.surfaceAlt, borderRadius: BorderRadius.circular(kRadiusSm)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final r in c.replies.take(3))
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: GestureDetector(
                        onLongPress: onReplyMore == null ? null : () => onReplyMore!(r),
                        child: Text.rich(
                          TextSpan(children: [
                            TextSpan(text: r.user.name, style: TextStyle(color: sz.link)),
                            if (r.isUp) TextSpan(text: '(UP 主)', style: TextStyle(color: sz.clay)),
                            if (r.replyTo != null)
                              TextSpan(text: ' 回复 @${r.replyTo!['name'] ?? ''}', style: TextStyle(color: sz.link)),
                            const TextSpan(text: ':'),
                            ...mentionSpans(r.text, r.mentions, sz.link),
                          ]),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(fontSize: kFontBody),
                        ),
                      ),
                    ),
                  if (c.replyCount > c.replies.take(3).length || onOpenReplies != null)
                    InkWell(
                      onTap: onOpenReplies,
                      child: Text('共 ${c.replyCount} 条回复 >', style: TextStyle(fontSize: kFontNote, color: sz.link)),
                    ),
                ]),
              ),
          ]),
        ),
      ]),
    );
  }
}

class _VoteButton extends StatelessWidget {
  const _VoteButton({required this.icon, required this.active, required this.label, required this.onTap});

  final IconData icon;
  final bool active;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: onTap,
      child: Row(children: [
        Icon(icon, size: 16, color: active ? sz.clay : sz.inkFaint),
        if (label.isNotEmpty) ...[
          const SizedBox(width: 3),
          Text(label, style: TextStyle(fontSize: kFontMicro, color: active ? sz.clay : sz.inkFaint)),
        ],
      ]),
    );
  }
}

/// 评论正文里的 @ 高亮(只高亮服务端认出来的注册用户名,别的原样当文字)。
List<InlineSpan> mentionSpans(String text, List<Map<String, dynamic>> mentions, Color link) {
  final names = {for (final m in mentions) '${m['username'] ?? ''}'.toLowerCase()}..remove('');
  if (names.isEmpty) return [TextSpan(text: text)];
  final out = <InlineSpan>[];
  final re = RegExp(r'@([A-Za-z][A-Za-z0-9_]{3,31})');
  var last = 0;
  for (final m in re.allMatches(text)) {
    if (!names.contains(m.group(1)!.toLowerCase())) continue;
    if (m.start > last) out.add(TextSpan(text: text.substring(last, m.start)));
    out.add(TextSpan(text: m.group(0), style: TextStyle(color: link)));
    last = m.end;
  }
  if (last < text.length) out.add(TextSpan(text: text.substring(last)));
  return out;
}

/// 底部弹出的评论输入框(≤1000 字)。返回写好的文字,取消返回 null。
Future<String?> showCommentInput(BuildContext context, {String hint = '发一条友善的评论', int maxLength = 1000}) {
  final c = TextEditingController();
  return szShowSheet<String>(
    context: context,
    builder: (ctx) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom),
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
          child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Expanded(
              child: TextField(
                controller: c,
                autofocus: true,
                minLines: 1,
                maxLines: 5,
                maxLength: maxLength,
                decoration: InputDecoration(hintText: hint, counterText: ''),
              ),
            ),
            TextButton(onPressed: () => Navigator.pop(ctx, c.text), child: const Text('发布')),
          ]),
        ),
      ),
    ),
  ).whenComplete(c.dispose);
}

/// 一楼的全部回复。
class _RepliesPage extends StatefulWidget {
  const _RepliesPage({required this.commentId, required this.vid, required this.uploaderId, required this.allowComments,
      this.focusId});

  final int commentId;
  final String vid;
  final int uploaderId;
  final bool allowComments;
  final int? focusId;

  @override
  State<_RepliesPage> createState() => _RepliesPageState();
}

class _RepliesPageState extends State<_RepliesPage> {
  VComment? _root;
  final List<VComment> _items = [];
  String? _cursor;
  bool _more = true;
  bool _loading = false;
  Object? _error;

  bool get _isUp => rootApi.userId == widget.uploaderId;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (_loading || !_more) return;
    setState(() => _loading = true);
    try {
      final r = await videoApi.replies(widget.commentId, cursor: _cursor);
      if (!mounted) return;
      setState(() {
        _root = VComment.fromJson(r['root']);
        _items.addAll([for (final x in vList(r['items'])) VComment.fromJson(x)]);
        _cursor = r['next_cursor'] as String?;
        _more = _cursor != null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _reply(VComment to) async {
    if (!widget.allowComments) return;
    if (!await ensureLoggedIn(context)) return;
    if (!mounted) return;
    final text = await showCommentInput(context, hint: '回复 @${to.user.name}');
    if (text == null || text.trim().isEmpty) return;
    try {
      final c = await videoApi.comment(widget.vid, text.trim(), parentId: to.id);
      if (mounted) setState(() => _items.add(c));
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _vote(VComment c, int v) async {
    if (!await ensureLoggedIn(context)) return;
    try {
      final r = await videoApi.voteComment(c.id, c.myVote == v ? 0 : v);
      if (mounted) {
        setState(() {
          c.likes = vInt(r['likes']);
          c.myVote = vInt(r['my_vote']);
        });
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  Future<void> _more2(VComment c) async {
    final mine = rootApi.userId == c.user.id;
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(leading: const Icon(Icons.copy), title: const Text('复制'), onTap: () => Navigator.pop(ctx, 'copy')),
          if (mine || _isUp)
            ListTile(leading: const Icon(Icons.delete_outline), title: const Text('删除'), onTap: () => Navigator.pop(ctx, 'delete')),
          if (!mine)
            ListTile(leading: const Icon(Icons.flag_outlined), title: const Text('举报'), onTap: () => Navigator.pop(ctx, 'report')),
        ]),
      ),
    );
    if (pick == null || !mounted) return;
    try {
      if (pick == 'copy') {
        await Clipboard.setData(ClipboardData(text: c.text));
      } else if (pick == 'delete') {
        await videoApi.deleteComment(c.id);
        if (c.id == _root?.id) {
          if (mounted) Navigator.pop(context);
          return;
        }
        setState(() => _items.removeWhere((x) => x.id == c.id));
      } else if (pick == 'report') {
        if (!await ensureLoggedIn(context)) return;
        if (mounted) await reportTarget(context, targetType: 'comment', targetId: c.id);
      }
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final root = _root;
    return SzPageScaffold(
      appBar: AppBar(title: Text(root == null ? '评论详情' : '${root.replyCount} 条回复')),
      body: root == null
          ? Center(child: _error != null ? SzError(error: _error, onRetry: _load) : const CircularProgressIndicator())
          : NotificationListener<ScrollNotification>(
              onNotification: (n) {
                if (n.metrics.pixels > n.metrics.maxScrollExtent - 200) _load();
                return false;
              },
              child: ListView(children: [
                CommentTile(
                  comment: root..replies = const [],
                  onVote: (v) => _vote(root, v),
                  onReply: () => _reply(root),
                  onMore: () => _more2(root),
                  highlight: widget.focusId == root.id,
                ),
                const Divider(height: 1),
                for (final r in _items)
                  CommentTile(
                    comment: r,
                    isReply: true,
                    highlight: widget.focusId == r.id,
                    onVote: (v) => _vote(r, v),
                    onReply: () => _reply(r),
                    onMore: () => _more2(r),
                  ),
                if (_loading) const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator())),
              ]),
            ),
    );
  }
}
