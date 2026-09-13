import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../models.dart';
import '../nav.dart';
import 'common.dart';

/// 粉丝 / 关注列表(#366):新的在前,每行一个关注按钮(关注的是**我**和这个人的关系),点人进 UP 主空间。
class FollowListPage extends StatefulWidget {
  const FollowListPage({super.key, required this.userId, required this.fans});

  final int userId;

  /// 真 = 粉丝列表,假 = 关注列表
  final bool fans;

  @override
  State<FollowListPage> createState() => _FollowListPageState();
}

class _FollowListPageState extends State<FollowListPage> {
  late final CursorPager<VPerson> _pager = CursorPager((cursor) async {
    final page = widget.fans
        ? await videoApi.fans(widget.userId, cursor: cursor)
        : await videoApi.followingOf(widget.userId, cursor: cursor);
    return (items: page.items, next: page.nextCursor, extra: page.extra);
  });

  final Set<int> _busy = {};

  bool get _isMe => rootApi.userId == widget.userId;

  @override
  void initState() {
    super.initState();
    unawaited(_pager.refresh());
  }

  @override
  void dispose() {
    _pager.dispose();
    super.dispose();
  }

  Future<void> _toggle(VPerson p) async {
    if (!await ensureLoggedIn(context) || !mounted) return;
    if (p.followed) {
      final ok = await vConfirm(context, title: '不再关注「${p.name}」?', ok: '不再关注');
      if (!ok || !mounted) return;
    }
    setState(() => _busy.add(p.id));
    try {
      final r = await videoApi.follow(p.id, !p.followed);
      _pager.upsert((x) => x.id == p.id, p.copyWith(followed: r['followed'] == true));
    } catch (e) {
      if (mounted) vToast(context, e);
    } finally {
      if (mounted) setState(() => _busy.remove(p.id));
    }
  }

  @override
  Widget build(BuildContext context) {
    final title = _isMe ? (widget.fans ? '我的粉丝' : '我的关注') : (widget.fans ? 'TA 的粉丝' : 'TA 的关注');
    return SzPageScaffold(
      appBar: AppBar(title: Text(title)),
      body: PagedListView<VPerson>(
        pager: _pager,
        emptyText: widget.fans
            ? (_isMe ? '还没有粉丝\n发视频、认真回评论,慢慢就有了' : '还没有粉丝')
            : (_isMe ? '还没有关注的人\n在视频页点 UP 主旁边的「关注」' : '还没有关注的人'),
        itemBuilder: (context, p, _) => _row(p),
      ),
    );
  }

  Widget _row(VPerson p) {
    final sz = Theme.of(context).sz;
    final me = rootApi.userId == p.id;
    final sub = p.bio.isNotEmpty ? p.bio : (p.username != null ? '@${p.username}' : '');
    return ListTile(
      leading: SzImage(url: p.avatar.isEmpty ? '' : videoResolve(p.avatar), name: p.name, size: 44, circle: true),
      title: Text(p.name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: sub.isEmpty
          ? null
          : Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      onTap: () => openUpSpace(context, p.id),
      trailing: me
          ? null
          : SizedBox(
              height: 32,
              child: OutlinedButton(
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size(72, 32),
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  foregroundColor: p.followed ? sz.inkMuted : sz.clay,
                  side: BorderSide(color: p.followed ? sz.line : sz.clay),
                ),
                onPressed: _busy.contains(p.id) ? null : () => _toggle(p),
                child: Text(p.followed ? '已关注' : '+ 关注'),
              ),
            ),
    );
  }
}
