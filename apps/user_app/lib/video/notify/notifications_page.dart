import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/store.dart';
import '../../session.dart';
import '../me/common.dart';
import '../models.dart';
import '../nav.dart';
import 'notify_format.dart';

export 'notify_format.dart' show notifyKinds;

/// 互动消息的总未读数:「消息」列表第三行「互动消息」上的角标听它。
final ValueNotifier<int> videoNotifyUnread = ValueNotifier<int>(0);

StreamSubscription<({String type, Map<String, dynamic> data})>? _watchSub;
int _watchSeq = 0;

/// 登录后调一次:先用 `GET /social/v1/notifications/unread` 对齐一次角标,之后听用户事件 `notify`
/// (每来一条互动消息、或者别的设备标了已读都会推,`data.unread.total` 直接覆盖角标,不用轮询)。
///
/// 可以重复调(换账号、回到前台都可以再调一次):订阅只挂一次,每次只是重新对齐数字。
void startVideoNotifyWatcher() {
  _watchSub ??= ChatStore.instance.userEvents.stream.listen((e) {
    if (e.type != 'notify') return;
    final u = e.data['unread'];
    if (u is Map && u['total'] != null) {
      _watchSeq++;
      videoNotifyUnread.value = vInt(u['total']);
    }
  });
  if (!rootApi.isLoggedIn) {
    videoNotifyUnread.value = 0;
    return;
  }
  unawaited(_initUnread(++_watchSeq));
}

Future<void> _initUnread(int seq) async {
  try {
    final u = await videoApi.notificationsUnread();
    // 接口在路上的时候来过事件的话,事件更新,以它为准
    if (seq == _watchSeq) videoNotifyUnread.value = vInt(u['total']);
  } catch (_) {
    // 拉不到就先不显示角标,下一个 notify 事件会带上最新的数
  }
}

/// 退出登录时调:停掉订阅、角标清零(换了人,上一个人的未读数不能挂在那儿)。
void stopVideoNotifyWatcher() {
  _watchSub?.cancel();
  _watchSub = null;
  _watchSeq++;
  videoNotifyUnread.value = 0;
}

/// 互动消息(#367):回复我的 / @我的 / 收到的赞 / 系统通知。
///
/// 进到哪个页签就把那一类标成已读(`POST /social/v1/notifications/read {kind}`),
/// 但这一次看到的列表里,新来的那几条仍然带着小红点 —— 标已读是为了角标,不是为了让人找不到哪几条是新的。
class VideoNotificationsPage extends StatefulWidget {
  const VideoNotificationsPage({super.key});

  @override
  State<VideoNotificationsPage> createState() => _VideoNotificationsPageState();
}

class _VideoNotificationsPageState extends State<VideoNotificationsPage> with SingleTickerProviderStateMixin {
  late final TabController _tc = TabController(length: notifyKinds.length, vsync: this)..addListener(_onTab);

  late final Map<String, CursorPager<NotifyItem>> _pagers = {
    for (final (kind, _) in notifyKinds)
      kind: CursorPager<NotifyItem>((cursor) async {
        final m = await videoApi.notifications(kind, cursor: cursor);
        _takeUnread(m['unread']);
        return (
          items: [for (final x in vList(m['items'])) NotifyItem.fromJson(x)],
          next: m['next_cursor'] as String?,
          extra: m,
        );
      }),
  };

  Map<String, int> _unread = {};

  /// 用户自己点过页签之后,就不再自动跳到有未读的那一页
  bool _touched = false;
  bool _auto = false;
  StreamSubscription<({String type, Map<String, dynamic> data})>? _events;

  String get _kind => notifyKinds[_tc.index].$1;

  @override
  void initState() {
    super.initState();
    _events = ChatStore.instance.userEvents.stream.listen((e) {
      if (e.type != 'notify') return;
      _takeUnread(e.data['unread']);
      // 正在看的这一类来了新的:拉一下再标已读;别的页签等点开时再拉
      final kind = e.data['kind'];
      if (kind == _kind && (_unread[_kind] ?? 0) > 0) unawaited(_openTab(_tc.index));
    });
    if (rootApi.isLoggedIn) _start();
  }

  void _start() {
    unawaited(_loadUnread());
    unawaited(_openTab(_tc.index));
  }

  @override
  void dispose() {
    _events?.cancel();
    _tc.dispose();
    for (final p in _pagers.values) {
      p.dispose();
    }
    super.dispose();
  }

  void _takeUnread(Object? u) {
    if (u is! Map) return;
    final m = u.cast<String, dynamic>();
    final next = {for (final (kind, _) in notifyKinds) kind: vInt(m[kind])};
    videoNotifyUnread.value = vInt(m['total']);
    if (mounted) setState(() => _unread = next);
  }

  Future<void> _loadUnread() async {
    try {
      final u = await videoApi.notificationsUnread();
      _takeUnread(u);
      if (!mounted || _touched || (_unread[_kind] ?? 0) > 0) return;
      // 一进来默认是「回复我的」;它没有新的而别的页签有,就直接跳过去
      final i = notifyKinds.indexWhere((k) => (_unread[k.$1] ?? 0) > 0);
      if (i >= 0 && i != _tc.index) {
        _auto = true;
        _tc.animateTo(i);
      }
    } catch (_) {
      // 角标拉不到不影响看列表
    }
  }

  void _onTab() {
    if (_tc.indexIsChanging) return;
    if (_auto) {
      _auto = false;
    } else {
      _touched = true;
    }
    unawaited(_openTab(_tc.index));
    setState(() {});
  }

  /// 打开一个页签:没拉过就拉;有未读说明来了新的,重新拉第一页;然后把这一类标成已读。
  Future<void> _openTab(int i) async {
    final kind = notifyKinds[i].$1;
    final p = _pagers[kind]!;
    if (p.loading) return;
    if (!p.loaded || (_unread[kind] ?? 0) > 0) await p.refresh();
    if ((_unread[kind] ?? 0) == 0) return;
    try {
      final r = await videoApi.markNotificationsRead(kind: kind);
      _takeUnread(r['unread']);
    } catch (_) {
      // 标已读失败:角标晚一点对齐而已,下次进来再标
    }
  }

  void _open(NotifyItem n) {
    if (n.video == null || n.vid.isEmpty) {
      vToast(context, '视频已经删除了');
      return;
    }
    final cid = n.commentId;
    if (cid != null) {
      openVideo(context, n.vid, commentId: cid);
    } else {
      openVideo(context, n.vid);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: AppBar(title: const Text('互动消息')),
        body: VideoLoginGate(text: '登录后能看到谁回复了你、赞了你', onLoggedIn: () => setState(_start)),
      );
    }
    return SzPageScaffold(
      appBar: AppBar(
        title: const Text('互动消息'),
        bottom: TabBar(
          controller: _tc,
          isScrollable: true,
          tabAlignment: TabAlignment.start,
          tabs: [
            for (final (kind, label) in notifyKinds)
              Tab(
                child: Badge(
                  isLabelVisible: (_unread[kind] ?? 0) > 0,
                  label: Text(unreadBadge(_unread[kind] ?? 0)),
                  offset: const Offset(14, -6),
                  child: Text(label),
                ),
              ),
          ],
        ),
      ),
      body: TabBarView(controller: _tc, children: [
        for (final (kind, _) in notifyKinds)
          PagedListView<NotifyItem>(
            pager: _pagers[kind]!,
            emptyText: switch (kind) {
              'reply' => '还没有人回复你\n评论了你的视频、回复了你的评论都会出现在这里',
              'at' => '还没有人 @ 你',
              'like' => '还没有收到赞',
              _ => '没有系统通知\n投稿的审核结果、处罚和申诉结果会在这里告诉你',
            },
            itemBuilder: (context, n, _) => kind == 'system' ? _systemRow(n) : _row(n),
          ),
      ]),
    );
  }

  Widget _dot() {
    final sz = Theme.of(context).sz;
    return Container(
      width: 7,
      height: 7,
      margin: const EdgeInsets.only(left: 6, top: 6),
      decoration: BoxDecoration(color: sz.danger, shape: BoxShape.circle),
    );
  }

  Widget _avatar(VPerson p, double size) => GestureDetector(
        onTap: () => openUpSpace(context, p.id),
        child: SzImage(url: p.avatar.isEmpty ? '' : videoResolve(p.avatar), name: p.name, size: size, circle: true),
      );

  /// 赞合并时几个头像叠着放,后面跟一个「+N」
  Widget _avatars(NotifyItem n) {
    final sz = Theme.of(context).sz;
    final a = notifyAvatars(n);
    if (a.shown.isEmpty) {
      return CircleAvatar(radius: 20, backgroundColor: sz.surfaceAlt, child: Icon(Icons.person_outline, color: sz.inkFaint));
    }
    if (a.shown.length == 1 && a.more == 0) return _avatar(a.shown.first, 40);
    const size = 30.0, step = 18.0;
    final extra = a.more > 0 ? 1 : 0;
    return SizedBox(
      width: size + step * (a.shown.length - 1 + extra),
      height: size,
      child: Stack(children: [
        for (var i = a.shown.length - 1; i >= 0; i--)
          Positioned(
            left: step * i,
            child: Container(
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                border: Border.all(color: Theme.of(context).scaffoldBackgroundColor, width: 1.5),
              ),
              child: _avatar(a.shown[i], size - 3),
            ),
          ),
        if (a.more > 0)
          Positioned(
            left: step * a.shown.length,
            child: Container(
              width: size,
              height: size,
              alignment: Alignment.center,
              decoration: BoxDecoration(color: sz.surfaceAlt, shape: BoxShape.circle),
              child: FittedBox(
                child: Padding(
                  padding: const EdgeInsets.all(3),
                  child: Text('+${vCount(a.more)}', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
                ),
              ),
            ),
          ),
      ]),
    );
  }

  Widget _thumb(NotifyItem n) {
    final sz = Theme.of(context).sz;
    final v = n.video;
    return ClipRRect(
      borderRadius: BorderRadius.circular(kRadiusSm),
      child: SizedBox(
        width: 72,
        height: 45,
        child: v == null
            ? ColoredBox(
                color: sz.surfaceAlt,
                child: Center(child: Text('已删除', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted))),
              )
            : '${v['cover'] ?? ''}'.isEmpty
                ? ColoredBox(color: sz.surfaceAlt, child: Icon(Icons.smart_display_outlined, color: sz.inkFaint))
                : Image(
                    image: szNetImage(videoResolve('${v['cover']}')),
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => ColoredBox(color: sz.surfaceAlt),
                  ),
      ),
    );
  }

  String _when(NotifyItem n) {
    final t = n.updatedAt ?? n.createdAt;
    return t == null ? '' : szTimeAgo(t.toUtc().toIso8601String());
  }

  Widget _row(NotifyItem n) {
    final sz = Theme.of(context).sz;
    final replied = '${n.data['replied_text'] ?? ''}';
    final quote = n.kind == 'like' ? '' : replied;
    return InkWell(
      onTap: () => _open(n),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 12),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _avatars(n),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                  child: Text(notifyHeadline(n),
                      style: TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600, color: sz.ink, height: 1.4)),
                ),
                if (!n.read) _dot(),
              ]),
              if (n.text.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(n.text,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: kFontBody, color: n.text == '该评论已删除' ? sz.inkMuted : sz.ink, height: 1.5)),
                ),
              if (quote.isNotEmpty)
                Container(
                  margin: const EdgeInsets.only(top: 6),
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
                  decoration: BoxDecoration(color: sz.surfaceAlt, borderRadius: BorderRadius.circular(kRadiusSm)),
                  child: Text('我的评论:$quote',
                      maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ),
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(_when(n), style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ),
            ]),
          ),
          const SizedBox(width: 10),
          _thumb(n),
        ]),
      ),
    );
  }

  Widget _systemRow(NotifyItem n) {
    final sz = Theme.of(context).sz;
    final action = '${n.data['action'] ?? ''}';
    final label = systemActionLabel(action);
    final bad = systemActionBad(action);
    final reason = '${n.data['reason_label'] ?? ''}';
    final code = '${n.data['reason_code'] ?? ''}';
    final coins = vInt(n.data['coins']);
    final color = bad ? sz.danger : (label.isEmpty ? sz.clay : sz.earn);
    return InkWell(
      onTap: n.video == null ? null : () => _open(n),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 12),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          CircleAvatar(
            radius: 20,
            backgroundColor: color.withValues(alpha: .12),
            child: Icon(
              bad ? Icons.error_outline : (label.isEmpty ? Icons.campaign_outlined : Icons.check_circle_outline),
              color: color,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                  child: Text(notifyHeadline(n),
                      style: TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600, color: sz.ink, height: 1.4)),
                ),
                if (label.isNotEmpty) Padding(padding: const EdgeInsets.only(left: 6), child: VTag(label, color: color)),
                if (!n.read) _dot(),
              ]),
              if (n.text.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(n.text, style: TextStyle(fontSize: kFontBody, color: sz.ink, height: 1.5)),
                ),
              if (reason.isNotEmpty || code.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('原因:${[code, reason].where((s) => s.isNotEmpty).join(' ')}',
                      style: TextStyle(fontSize: kFontNote, color: bad ? sz.danger : sz.inkMuted)),
                ),
              if (coins > 0)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('+$coins 硬币', style: TextStyle(fontSize: kFontNote, color: sz.earn)),
                ),
              if (bad && action != 'failed' && action != 'appeal_upheld')
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text('觉得判错了可以在「创作中心」里申诉,会由另一名审核员复核',
                      style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
                ),
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(_when(n), style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ),
            ]),
          ),
          if (n.video != null) ...[const SizedBox(width: 10), _thumb(n)],
        ]),
      ),
    );
  }
}
