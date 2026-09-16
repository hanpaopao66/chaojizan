// 歌曲评论(§8.2 /tracks/{tid}/comments):热评 + 最新两个页签、楼中楼、赞、删自己的、举报。
//
// 评论先发后审(§2.1),和视频评论同口径:违禁词当场拒(服务端),其余靠举报和巡查。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/ui/avatar.dart';
import '../../session.dart';
import '../../video/me/common.dart';
import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/common.dart';

class MusicCommentsPage extends StatefulWidget {
  const MusicCommentsPage({super.key, required this.track});

  final MTrack track;

  @override
  State<MusicCommentsPage> createState() => _MusicCommentsPageState();
}

class _MusicCommentsPageState extends State<MusicCommentsPage> with SingleTickerProviderStateMixin {
  late final TabController _tc = TabController(length: 2, vsync: this);
  final _input = TextEditingController();
  bool _sending = false;

  /// 回复谁(null = 发一条新评论)
  MComment? _replyTo;

  final _hotKey = GlobalKey<_CommentListState>();
  final _newKey = GlobalKey<_CommentListState>();

  @override
  void dispose() {
    _tc.dispose();
    _input.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: Column(children: [
          const Text('评论'),
          Text(widget.track.title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        ]),
        bottom: TabBar(controller: _tc, tabs: const [Tab(text: '热评'), Tab(text: '最新')]),
      ),
      body: TabBarView(controller: _tc, children: [
        _CommentList(key: _hotKey, tid: widget.track.tid, sort: 'hot', onReply: _startReply),
        _CommentList(key: _newKey, tid: widget.track.tid, sort: 'new', onReply: _startReply),
      ]),
      bottomNavigationBar: _composer(context),
    );
  }

  void _startReply(MComment c) {
    setState(() => _replyTo = c);
    FocusScope.of(context).requestFocus(FocusNode());
  }

  Widget _composer(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SafeArea(
      child: Padding(
        // 键盘弹起来时把输入框顶上去,不然打字看不见自己打的
        padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
        child: Container(
          decoration: BoxDecoration(color: sz.surface, border: Border(top: BorderSide(color: sz.line))),
          padding: const EdgeInsets.fromLTRB(kPagePad, 8, 8, 8),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (_replyTo != null)
              Row(children: [
                Expanded(
                  child: Text('回复 ${_replyTo!.user.name}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ),
                IconButton(
                  icon: const Icon(Icons.close, size: 16),
                  tooltip: '不回复了',
                  onPressed: () => setState(() => _replyTo = null),
                ),
              ]),
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  maxLength: 300,
                  minLines: 1,
                  maxLines: 4,
                  decoration: InputDecoration(
                    hintText: _replyTo == null ? '说点什么' : '回复 ${_replyTo!.user.name}',
                    counterText: '',
                    isDense: true,
                    border: const OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              _sending
                  ? const Padding(
                      padding: EdgeInsets.all(12),
                      child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)))
                  : IconButton(icon: const Icon(Icons.send), tooltip: '发送', onPressed: _send),
            ]),
          ]),
        ),
      ),
    );
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    if (!await ensureLoggedIn(context)) return;
    setState(() => _sending = true);
    try {
      await musicApi.comment(widget.track.tid, text, parentId: _replyTo?.id);
      if (!mounted) return;
      _input.clear();
      setState(() => _replyTo = null);
      widget.track.comments++;
      // 新评论在「最新」那一页,顺手把两页都拉一遍,免得切过去还是旧的
      await _newKey.currentState?.reload();
      await _hotKey.currentState?.reload();
      if (mounted) _tc.animateTo(1);
    } catch (e) {
      if (mounted) mToast(context, e);
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }
}

class _CommentList extends StatefulWidget {
  const _CommentList({super.key, required this.tid, required this.sort, required this.onReply});

  final String tid;
  final String sort;
  final void Function(MComment c) onReply;

  @override
  State<_CommentList> createState() => _CommentListState();
}

class _CommentListState extends State<_CommentList> with AutomaticKeepAliveClientMixin {
  late final CursorPager<MComment> _pager = CursorPager<MComment>((cursor) async {
    if (widget.sort == 'new') {
      final r = await musicApi.comments(widget.tid, sort: 'new', cursor: cursor);
      return (items: r.items, next: r.nextCursor, extra: r.extra);
    }
    final page = int.tryParse(cursor ?? '0') ?? 0;
    final r = await musicApi.comments(widget.tid, sort: 'hot', page: page);
    return (items: r.items, next: r.hasMore ? '${page + 1}' : null, extra: r.extra);
  });

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _pager.refresh();
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  Future<void> reload() => _pager.refresh();

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return PagedListView<MComment>(
      pager: _pager,
      divider: false,
      emptyText: '还没有人评论,来说第一句',
      itemBuilder: (context, c, i) => _CommentTile(
        comment: c,
        tid: widget.tid,
        onReply: widget.onReply,
        onChanged: _pager.touch,
        onDeleted: () => _pager.removeWhere((x) => x.id == c.id),
      ),
    );
  }
}

class _CommentTile extends StatefulWidget {
  const _CommentTile({
    required this.comment,
    required this.tid,
    required this.onReply,
    required this.onChanged,
    required this.onDeleted,
  });

  final MComment comment;
  final String tid;
  final void Function(MComment c) onReply;
  final VoidCallback onChanged;
  final VoidCallback onDeleted;

  @override
  State<_CommentTile> createState() => _CommentTileState();
}

class _CommentTileState extends State<_CommentTile> {
  /// 楼中楼展开之后拉回来的回复
  List<MComment>? _replies;
  bool _loadingReplies = false;

  MComment get c => widget.comment;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final replies = _replies ?? c.replies;
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 10, kPagePad, 6),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        ChatAvatar(name: c.user.name, url: c.user.avatar, size: 34),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(c.user.name, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            const SizedBox(height: 2),
            Text.rich(TextSpan(children: [
              if (c.replyTo != null)
                TextSpan(text: '回复 @${c.replyTo!.name}:', style: TextStyle(color: sz.link)),
              TextSpan(text: c.text),
            ]), style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, height: 1.5)),
            const SizedBox(height: 4),
            Row(children: [
              Text(vAgo(c.createdAt), style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
              const SizedBox(width: 14),
              InkWell(
                onTap: () => widget.onReply(c),
                child: Text('回复', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ),
              const SizedBox(width: 14),
              InkWell(
                onTap: _like,
                child: Row(children: [
                  Icon(c.liked ? Icons.favorite : Icons.favorite_border,
                      size: 14, color: c.liked ? sz.clay : sz.inkMuted),
                  const SizedBox(width: 3),
                  Text(c.likes > 0 ? vCount(c.likes) : '赞',
                      style: TextStyle(fontSize: kFontMicro, color: c.liked ? sz.clay : sz.inkMuted)),
                ]),
              ),
              const Spacer(),
              InkWell(
                onTap: _menu,
                child: Icon(Icons.more_horiz, size: 16, color: sz.inkFaint),
              ),
            ]),
            if (replies.isNotEmpty)
              Container(
                margin: const EdgeInsets.only(top: 8),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(color: sz.surfaceAlt, borderRadius: BorderRadius.circular(kRadiusSm)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  for (final r in replies)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Text.rich(
                        TextSpan(children: [
                          TextSpan(text: '${r.user.name}:', style: TextStyle(color: sz.inkMuted)),
                          TextSpan(text: r.text),
                        ]),
                        style: TextStyle(fontSize: kFontBody, color: sz.ink, height: 1.5),
                      ),
                    ),
                ]),
              ),
            if (c.replyCount > replies.length)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: _loadingReplies
                    ? const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))
                    : InkWell(
                        onTap: _loadReplies,
                        child: Text('展开 ${c.replyCount} 条回复',
                            style: TextStyle(fontSize: kFontMicro, color: sz.link)),
                      ),
              ),
          ]),
        ),
      ]),
    );
  }

  Future<void> _loadReplies() async {
    setState(() => _loadingReplies = true);
    try {
      final r = await musicApi.commentReplies(c.id);
      if (mounted) setState(() => _replies = r.items);
    } catch (e) {
      if (mounted) mToast(context, e);
    } finally {
      if (mounted) setState(() => _loadingReplies = false);
    }
  }

  Future<void> _like() async {
    if (!await ensureLoggedIn(context)) return;
    try {
      final r = await musicApi.likeComment(c.id, !c.liked);
      if (!mounted) return;
      c
        ..liked = r.liked
        ..likes = r.likes;
      widget.onChanged();
      setState(() {});
    } catch (e) {
      if (mounted) mToast(context, e);
    }
  }

  Future<void> _menu() async {
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (c.mine)
            ListTile(
                leading: const Icon(Icons.delete_outline),
                title: const Text('删除'),
                onTap: () => Navigator.pop(ctx, 'delete'))
          else
            ListTile(
                leading: const Icon(Icons.flag_outlined),
                title: const Text('举报'),
                onTap: () => Navigator.pop(ctx, 'report')),
        ]),
      ),
    );
    if (pick == null || !mounted) return;
    if (pick == 'delete') {
      if (!await vConfirm(context, title: '删除这条评论?', ok: '删除', danger: true)) return;
      try {
        await musicApi.deleteComment(c.id);
        widget.onDeleted();
      } catch (e) {
        if (mounted) mToast(context, e);
      }
    } else {
      await reportSheet(context, targetType: 'comment', targetId: '${c.id}');
    }
  }
}
