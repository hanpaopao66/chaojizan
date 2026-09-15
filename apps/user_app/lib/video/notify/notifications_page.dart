import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/links.dart' show openAppLink;
import '../../chat/pages/user_profile_page.dart' show openUserProfile;
import '../../chat/store.dart';
import '../../chat/ui/conv_row.dart';
import '../../chat/ui/format.dart' show dayLabel, hm, sameDay;
import '../../session.dart';
import '../me/common.dart';
import '../models.dart';
import '../nav.dart';
import 'notify_format.dart';
import 'notify_prefs.dart';

export 'notify_format.dart' show notifyKinds;

/// 互动消息的总未读数(服务端的 total,各类加起来)。
final ValueNotifier<int> videoNotifyUnread = ValueNotifier<int>(0);

/// 每一类各有几条没读(`reply / at / like / follow / repost / quote / system`)。「提醒设置」只数勾上的几类,所以要分开记;
/// 每次都换一个新的 Map,听它的地方(会话列表、底栏)哪一类变了都能收到。
final ValueNotifier<Map<String, int>> videoNotifyUnreadKinds = ValueNotifier<Map<String, int>>(const {});

/// 「互动消息」那一行此刻该挂几:按「提醒设置」过滤过的未读数。
int videoNotifyBadge() => notifyBadgeCount(videoNotifyUnreadKinds.value, VideoNotifyPrefs.instance.kinds);

void _takeUnreadMap(Object? u) {
  if (u is! Map) return;
  final m = u.cast<String, dynamic>();
  // 先换分类的,再换总数:听总数的地方拿到的分类已经是新的
  videoNotifyUnreadKinds.value = {for (final (k, _) in notifyKinds) k: vInt(m[k])};
  videoNotifyUnread.value = vInt(m['total']);
}

StreamSubscription<({String type, Map<String, dynamic> data})>? _watchSub;
int _watchSeq = 0;

/// 登录后调一次:先用 `GET /social/v1/notifications/unread` 对齐一次角标,之后听用户事件 `notify`
/// (每来一条互动消息、或者别的设备标了已读都会推,`data.unread` 直接覆盖角标,不用轮询)。
///
/// 可以重复调(换账号、回到前台都可以再调一次):订阅只挂一次,每次只是重新对齐数字。
void startVideoNotifyWatcher() {
  unawaited(VideoNotifyPrefs.instance.load());
  _watchSub ??= ChatStore.instance.userEvents.stream.listen((e) {
    // 我在别的设备上改了「静音 / 提醒设置」:服务端推 settings,这里当场跟着变
    if (e.type == 'settings') {
      VideoNotifyPrefs.instance.applyServer(e.data['notify']);
      return;
    }
    if (e.type != 'notify') return;
    final u = e.data['unread'];
    if (u is Map && u['total'] != null) {
      _watchSeq++;
      _takeUnreadMap(u);
    }
  });
  if (!rootApi.isLoggedIn) {
    _takeUnreadMap(const {'total': 0});
    return;
  }
  unawaited(_initUnread(++_watchSeq));
}

Future<void> _initUnread(int seq) async {
  try {
    final u = await videoApi.notificationsUnread();
    // 接口在路上的时候来过事件的话,事件更新,以它为准
    if (seq == _watchSeq) _takeUnreadMap(u);
  } catch (_) {
    // 拉不到就先不显示角标,下一个 notify 事件会带上最新的数
  }
}

/// 退出登录时调:停掉订阅、角标清零(换了人,上一个人的未读数不能挂在那儿)。
void stopVideoNotifyWatcher() {
  _watchSub?.cancel();
  _watchSub = null;
  _watchSeq++;
  _takeUnreadMap(const {'total': 0});
}

/// 「互动消息」(#367 设计稿 C;DEV-PROMPTS-41 起视频、动态、音乐合在这一处):**一个机器人会话**,
/// 不是一个带页签的页面。
///
/// 一条互动 = 一条消息,按时间往下排,最新的在最底下;赞、关注、转发是服务端合并好的一条
/// (「小王等 8 人赞了你的评论」「张三等 3 人关注了你」),不一条条炸;回复的气泡里用引用块放**我的原话**
/// (隔两天谁记得在回复谁),下面挂「回复 / 看视频 / 看动态 / 看评论」这些按钮。
/// 打开时没读的那几条上面画「以下为新消息」,然后整个会话标成已读 —— 没有「全部已读」按钮,也没有页签。
/// 机器人不收消息,所以没有输入框,底下只有「静音」和「提醒设置」(存在服务端、各设备同步,见 [VideoNotifyPrefs])。
class VideoNotificationsPage extends StatefulWidget {
  const VideoNotificationsPage({super.key});

  @override
  State<VideoNotificationsPage> createState() => _VideoNotificationsPageState();
}

class _VideoNotificationsPageState extends State<VideoNotificationsPage> {
  NotifyMerge _merge = NotifyMerge();
  bool _loadingOlder = false;
  bool _firstDone = false;
  Object? _error;

  /// 打开时最旧的那条没读的:「以下为新消息」画在它上面。只在第一次拉完时定一次,
  /// 之后标了已读、来了新的也不挪 —— 分隔线是「这次打开时从哪开始是新的」
  int? _dividerAbove;

  StreamSubscription<({String type, Map<String, dynamic> data})>? _events;
  Timer? _debounce;
  VideoNotifyPrefs get _prefs => VideoNotifyPrefs.instance;

  @override
  void initState() {
    super.initState();
    _prefs.addListener(_onPrefs);
    unawaited(_prefs.load());
    _events = ChatStore.instance.userEvents.stream.listen((e) {
      if (e.type != 'notify' || !_firstDone) return;
      final kind = e.data['kind'];
      // 标已读也会推 notify(kind 为空):那一次不用重拉
      if (kind is! String || kind.isEmpty) return;
      _debounce?.cancel();
      _debounce = Timer(const Duration(milliseconds: 300), () => _refresh(kind));
    });
    if (rootApi.isLoggedIn) unawaited(_loadFirst());
  }

  @override
  void dispose() {
    _prefs.removeListener(_onPrefs);
    _events?.cancel();
    _debounce?.cancel();
    super.dispose();
  }

  void _onPrefs() {
    if (mounted) setState(() {});
  }

  Future<void> _loadFirst() async {
    setState(() => _error = null);
    try {
      // 先问服务端认识哪几类(未读表的键):老服务端不认 follow / repost / quote,拉它们会 422。
      // 拿不到未读表就按最早的四类拉,和老版本一样
      Map<String, dynamic>? unread;
      try {
        unread = await videoApi.notificationsUnread();
        _takeUnreadMap(unread);
      } catch (_) {
        unread = null;
      }
      final kinds = activeNotifyKinds(unread);
      _merge = NotifyMerge(kinds: kinds);
      final pages = await Future.wait([for (final k in kinds) videoApi.notifications(k)]);
      for (var i = 0; i < kinds.length; i++) {
        final m = pages[i];
        _merge.put(kinds[i], [for (final x in vList(m['items'])) NotifyItem.fromJson(x)],
            next: m['next_cursor'] as String?);
        _takeUnreadMap(m['unread']);
      }
      final stillUnread = _merge.visible().where((n) => !n.read);
      _dividerAbove = stillUnread.isEmpty ? null : stillUnread.last.id;
      _firstDone = true;
      _error = null;
    } catch (e) {
      _error = e;
    }
    if (!mounted) return;
    setState(() {});
    if (_firstDone) await _markRead();
  }

  /// 开着的时候来了新的:只重拉那一类的第一页,合进来,再标已读
  Future<void> _refresh(String kind) async {
    if (!_merge.kinds.contains(kind)) return;   // 这次没在拉的类(服务端比客户端新)
    try {
      final m = await videoApi.notifications(kind);
      if (!mounted) return;
      setState(() => _merge.put(kind, [for (final x in vList(m['items'])) NotifyItem.fromJson(x)],
          next: m['next_cursor'] as String?));
      _takeUnreadMap(m['unread']);
      await _markRead();
    } catch (_) {
      // 拉不到就等下一次;手里的照样能看
    }
  }

  Future<void> _loadOlder() async {
    final k = _merge.nextKind();
    if (k == null || _loadingOlder || !_firstDone) return;
    setState(() => _loadingOlder = true);
    try {
      final m = await videoApi.notifications(k, cursor: _merge.cursorOf(k));
      _merge.put(k, [for (final x in vList(m['items'])) NotifyItem.fromJson(x)],
          next: m['next_cursor'] as String?, older: true);
    } catch (e) {
      if (mounted) vToast(context, e);
    } finally {
      if (mounted) setState(() => _loadingOlder = false);
    }
  }

  Future<void> _markRead() async {
    if (videoNotifyUnread.value == 0) return;
    try {
      final r = await videoApi.markNotificationsRead();
      _takeUnreadMap(r['unread']);
    } catch (_) {
      // 标已读失败:角标晚一点对齐而已,下次进来再标
    }
  }

  bool _nearTop(ScrollMetrics m) {
    // 列表是倒着排的(最新的在最底下):往上翻 = 往 maxScrollExtent 走
    if (m.axis == Axis.vertical && m.extentAfter < 400) unawaited(_loadOlder());
    return false;
  }

  void _openVideo(NotifyItem n, {bool atComment = false}) {
    if (n.video == null || n.vid.isEmpty) {
      vToast(context, '视频已经删除了');
      return;
    }
    final cid = atComment ? n.commentId : null;
    final root = vInt(n.comment?['root_id']);
    openVideo(context, n.vid, commentId: cid, rootCommentId: cid != null && root > 0 && root != cid ? root : null);
  }

  /// 点开这一条说的东西。视频直接走视频那条路;论坛的帖子、音乐的歌和作品走**站内链接**
  /// (chat/links.dart 的 openAppLink)—— 互动消息不直接依赖论坛、音乐两个模块,
  /// 少一层耦合,链接那边认得出就跳得过去。
  Future<void> _openTarget(NotifyItem n, {bool atComment = false}) async {
    switch (n.target) {
      case 'video':
        _openVideo(n, atComment: atComment);
      case 'post':
        await _openLink('/forum/p/${n.pid}');
      case 'track':
        final cid = n.commentId;
        await _openLink('/music/t/${n.tid}${cid != null ? '?c=$cid' : ''}');
      case 'release':
        await _openLink('/music/r/${n.rid}');
      default:
        final who = n.actor;
        if (who != null) await openUserProfile(context, who.id);
    }
  }

  Future<void> _openLink(String path) async {
    final ok = await openAppLink(context, Uri.parse('https://chaojizan.cc$path'));
    if (!ok && mounted) vToast(context, '打不开,升级到最新版再试');
  }

  /// 这一条下面挂哪几个按钮
  List<(String, VoidCallback)> _buttons(NotifyItem n) => switch (n.target) {
        'video' => n.video == null
            ? const []
            : [
                if (n.kind == 'reply' || n.kind == 'at') ('回复', () => _openVideo(n, atComment: true)),
                ('看视频', () => _openVideo(n)),
              ],
        'post' => [('看动态', () => unawaited(_openTarget(n)))],
        'track' => [('看评论', () => unawaited(_openTarget(n, atComment: true)))],
        'release' => [('看作品', () => unawaited(_openTarget(n)))],
        _ => n.kind == 'follow' && n.actor != null
            ? [('看看 TA', () => unawaited(openUserProfile(context, n.actor!.id)))]
            : const [],
      };

  Future<void> _toggleMute() async {
    final next = !_prefs.muted;
    try {
      await _prefs.setMuted(next);
    } catch (e) {
      if (mounted) vToast(context, '没改成:${videoErrorText(e)}');
      return;
    }
    if (mounted) vToast(context, next ? '已静音:这个会话的未读不再算进底栏' : '已取消静音');
  }

  Future<void> _settings() => szShowSheet<void>(
        context: context,
        builder: (ctx) => AnimatedBuilder(
          animation: _prefs,
          builder: (ctx, _) {
            final sz = Theme.of(ctx).sz;
            return SafeArea(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(0, 0, 0, 12),
                child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Padding(
                    padding: EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 4),
                    child: Text('提醒设置', style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 4),
                    child: Text('哪几类算进「互动消息」的未读', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  ),
                  for (final (kind, label) in notifyKinds)
                    SwitchListTile(
                      value: _prefs.kinds.contains(kind),
                      onChanged: (v) => _prefs.setKind(kind, v).catchError((Object e) {
                        if (ctx.mounted) vToast(ctx, '没改成:${videoErrorText(e)}');
                      }),
                      title: Text(label),
                      subtitle: Text(switch (kind) {
                        'reply' => '评论、回复了你的视频、动态或歌',
                        'at' => '在评论或动态里 @ 了你',
                        'like' => '视频、动态、评论收到的赞,同一条合并成一条',
                        'follow' => '有人关注了你,同一天的合并成一条',
                        'repost' => '转发了你的动态',
                        'quote' => '引用了你的动态',
                        _ => '审核结果、下架、处罚和申诉结果',
                      }),
                    ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(kPagePad, 6, kPagePad, 0),
                    child: Text('互动提醒只在 App 里提示,不发系统推送;这里的设置跟着账号走,换手机也一样。',
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5)),
                  ),
                ]),
              ),
            );
          },
        ),
      );

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final appBar = AppBar(
      titleSpacing: 0,
      title: ConvHeaderTitle(
        avatar: const IconAvatar(icon: Icons.smart_toy_outlined, size: 34),
        title: '互动消息',
        suffix: [
          const BotTag(),
          if (_prefs.muted) Icon(Icons.notifications_off, size: 14, color: sz.inkFaint),
        ],
        // 视频、动态、音乐的互动都在这一处(DEV-PROMPTS-41 §5.8)
        subtitle: '回复、@、赞、关注、转发和审核结果',
      ),
    );
    if (!rootApi.isLoggedIn) {
      return SzPageScaffold(
        appBar: appBar,
        body: VideoLoginGate(text: '登录后能看到谁回复了你、赞了你、关注了你', onLoggedIn: () => unawaited(_loadFirst())),
      );
    }
    return SzPageScaffold(
      appBar: appBar,
      body: _body(),
      bottomNavigationBar: _bottomBar(),
    );
  }

  Widget _body() {
    if (!_firstDone) {
      if (_error != null) return Center(child: videoErrorView(_error, () => unawaited(_loadFirst())));
      return const Center(child: CircularProgressIndicator());
    }
    final vis = _merge.visible();
    if (vis.isEmpty) {
      return const SzEmpty(text: '还没有互动\n有人回复、@ 你、赞你或者关注你,会在这里告诉你');
    }
    return LayoutBuilder(builder: (context, box) {
      final cardW = math.min(300.0, box.maxWidth - 28);
      final entries = <Widget>[_footNote()];
      for (var i = 0; i < vis.length; i++) {
        final n = vis[i];
        entries.add(Padding(
          padding: const EdgeInsets.fromLTRB(14, 5, 14, 5),
          child: Align(alignment: Alignment.centerLeft, child: SizedBox(width: cardW, child: _card(n))),
        ));
        if (n.id == _dividerAbove) entries.add(const UnreadDivider());
        final older = i + 1 < vis.length ? vis[i + 1] : null;
        if (older == null || !sameDay(notifyTime(older), notifyTime(n))) entries.add(_DayLabel(notifyTime(n)));
      }
      if (_loadingOlder || _merge.hasMore) {
        entries.add(Padding(
          padding: const EdgeInsets.all(12),
          child: Center(
            child: _loadingOlder
                ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                : const SizedBox(height: 18),
          ),
        ));
      }
      return NotificationListener<ScrollMetricsNotification>(
        // 一屏没铺满时滑不动,也要能把更早的拉出来
        onNotification: (n) => _nearTop(n.metrics),
        child: NotificationListener<ScrollNotification>(
          onNotification: (n) => _nearTop(n.metrics),
          child: ListView.builder(
            reverse: true,
            padding: const EdgeInsets.only(top: 4),
            itemCount: entries.length,
            itemBuilder: (_, i) => entries[i],
          ),
        ),
      );
    });
  }

  /// 会话最底下的一句话:这个机器人只推什么。
  Widget _footNote() {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 10, 14, 12),
      child: Text('这个会话只收别人对你的互动 —— 视频、动态、音乐的回复、@、赞、关注、转发,还有审核和处罚结果,不会往这儿塞推荐和活动。平台公告在「超级赞」里。',
          style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted, height: 1.7)),
    );
  }

  Widget _bottomBar() {
    final sz = Theme.of(context).sz;
    final muted = _prefs.muted;
    ButtonStyle style() => OutlinedButton.styleFrom(
          backgroundColor: sz.surface,
          foregroundColor: sz.inkMuted,
          minimumSize: const Size.fromHeight(40),
          textStyle: const TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w500),
        );
    return Container(
      decoration: BoxDecoration(color: sz.paper, border: Border(top: BorderSide(color: sz.line))),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 10, 14, 10),
          child: Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                style: style(),
                onPressed: _toggleMute,
                icon: Icon(muted ? Icons.notifications_active_outlined : Icons.notifications_off_outlined, size: 16),
                label: Text(muted ? '取消静音' : '静音'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(child: OutlinedButton(style: style(), onPressed: _settings, child: const Text('提醒设置'))),
          ]),
        ),
      ),
    );
  }

  // ---------------- 一条互动 ----------------

  Widget _card(NotifyItem n) => switch (n.kind) {
        // 赞、关注、转发都是「一堆人对同一个东西做了同一件事」,服务端合并成一条,画法也一样
        'like' || 'follow' || 'repost' => _mergedCard(n),
        'system' => _systemCard(n),
        _ => _replyCard(n),   // reply / at / quote
      };

  /// 机器人发来的一条:发丝描边的卡片,左下角是小尾巴;[buttons] 是挂在下面的 inline 按钮。
  Widget _bubble({required Widget child, List<(String, VoidCallback)> buttons = const [], bool tail = true, VoidCallback? onTap}) {
    final sz = Theme.of(context).sz;
    final radius = BorderRadius.only(
      topLeft: const Radius.circular(kRadiusMd),
      topRight: const Radius.circular(kRadiusMd),
      bottomRight: const Radius.circular(kRadiusMd),
      bottomLeft: Radius.circular(tail ? 4 : kRadiusMd),
    );
    return Container(
      decoration: BoxDecoration(color: sz.surface, borderRadius: radius, border: Border.all(color: sz.line)),
      child: ClipRRect(
        borderRadius: radius,
        child: Material(
          type: MaterialType.transparency,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
            InkWell(
              onTap: onTap,
              child: Padding(padding: const EdgeInsets.fromLTRB(12, 9, 12, 10), child: child),
            ),
            if (buttons.isNotEmpty)
              DecoratedBox(
                decoration: BoxDecoration(border: Border(top: BorderSide(color: sz.line))),
                child: IntrinsicHeight(
                  child: Row(children: [
                    for (var i = 0; i < buttons.length; i++) ...[
                      if (i > 0) VerticalDivider(width: 1, thickness: 1, color: sz.line),
                      Expanded(
                        child: InkWell(
                          onTap: buttons[i].$2,
                          child: Padding(
                            padding: const EdgeInsets.symmetric(vertical: 9),
                            child: Center(
                              child: Text(buttons[i].$1,
                                  style: TextStyle(fontSize: kFontBody, color: sz.link, fontWeight: FontWeight.w500)),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ]),
                ),
              ),
          ]),
        ),
      ),
    );
  }

  /// 第一行:「**名字** 回复了你的评论」+ 右边的时刻
  Widget _headline(NotifyItem n, {List<InlineSpan>? spans}) {
    final sz = Theme.of(context).sz;
    final line = notifyHeadline(n);
    final name = n.actor?.name ?? '';
    final text = spans ??
        (name.isNotEmpty && line.startsWith(name)
            ? [
                TextSpan(text: name, style: const TextStyle(fontWeight: FontWeight.w600)),
                TextSpan(text: line.substring(name.length)),
              ]
            : [TextSpan(text: line, style: const TextStyle(fontWeight: FontWeight.w600))]);
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(
        child: Text.rich(TextSpan(children: text), style: TextStyle(fontSize: kFontBody, color: sz.ink, height: 1.45)),
      ),
      const SizedBox(width: 8),
      Padding(
        padding: const EdgeInsets.only(top: 2),
        child: Text(hm(notifyTime(n)), style: szTabular(fontSize: kFontMicro, color: sz.inkMuted)),
      ),
    ]);
  }

  /// 引用块:左边一道竖线,里面是「你:我的原话」
  Widget _quote(String text) {
    final sz = Theme.of(context).sz;
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.only(left: 9),
      decoration: BoxDecoration(
        border: Border(left: BorderSide(color: sz.inkFaint.withValues(alpha: .5), width: 2)),
      ),
      child: Text(text,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.5)),
    );
  }

  /// 这一条说的那个东西:视频、动态、歌、作品各一行。没有目标(比如关注)就不画
  Widget? _targetLine(NotifyItem n) => switch (n.target) {
        'video' => _videoLine(n),
        'post' => _iconLine(Icons.forum_outlined, '${n.post?['text'] ?? ''}', empty: '这条动态已经不在了'),
        'track' => _coverLine('${n.track?['cover'] ?? ''}', '${n.track?['title'] ?? ''}',
            icon: Icons.music_note_outlined, empty: '这首歌已经不在了'),
        'release' => _iconLine(Icons.album_outlined, '${n.release?['title'] ?? ''}', empty: '这个作品已经不在了'),
        _ => null,
      };

  /// 一个小图标 + 一行字(动态、作品)
  Widget _iconLine(IconData icon, String text, {required String empty}) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(padding: const EdgeInsets.only(top: 2), child: Icon(icon, size: 15, color: sz.inkFaint)),
        const SizedBox(width: 7),
        Expanded(
          child: Text(text.trim().isEmpty ? empty : text,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.4)),
        ),
      ]),
    );
  }

  /// 方封面 + 一行字(歌)
  Widget _coverLine(String cover, String title, {required IconData icon, required String empty}) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: SizedBox(
            width: 34,
            height: 34,
            child: cover.isEmpty
                ? ColoredBox(color: sz.line, child: Icon(icon, size: 16, color: sz.inkFaint))
                : Image(
                    image: szNetImage(videoResolve(cover)),
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => ColoredBox(color: sz.line),
                  ),
          ),
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Text(title.trim().isEmpty ? empty : title,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.4)),
        ),
      ]),
    );
  }

  /// 视频那一小条:缩略图 + 标题。视频删了就说一声
  Widget _videoLine(NotifyItem n) {
    final sz = Theme.of(context).sz;
    final v = n.video;
    final cover = '${v?['cover'] ?? ''}';
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Row(children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: SizedBox(
            width: 52,
            height: 34,
            child: v == null || cover.isEmpty
                ? ColoredBox(color: sz.line, child: Icon(Icons.smart_display_outlined, size: 16, color: sz.inkFaint))
                : Image(
                    image: szNetImage(videoResolve(cover)),
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => ColoredBox(color: sz.line),
                  ),
          ),
        ),
        const SizedBox(width: 9),
        Expanded(
          child: Text(v == null ? '视频已经删除了' : '${v['title'] ?? ''}',
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.4)),
        ),
      ]),
    );
  }

  /// 我的原话:回复、赞、转发时引在上面 —— 隔两天谁记得对方在回复哪一条
  String _mine(NotifyItem n) {
    final replied = '${n.data['replied_text'] ?? ''}';
    final videoTitle = '${n.video?['title'] ?? ''}';
    final trackTitle = '${n.track?['title'] ?? ''}';
    final postText = '${n.post?['text'] ?? ''}';
    if (replied.isNotEmpty) return '你:$replied';          // 我的那条评论
    if (n.target == 'video' && n.data['target'] == 'video') return videoTitle.isEmpty ? '' : '你的视频《$videoTitle》';
    if (n.target == 'track' && n.data['target'] == 'track') return trackTitle.isEmpty ? '' : '你的歌《$trackTitle》';
    if (n.target == 'post') return postText.trim().isEmpty ? '' : '你的动态:$postText';
    if (n.text.isNotEmpty && n.kind == 'like') return '你:${n.text}';
    return '';
  }

  /// 回复我的、@ 我的、引用我的:对方说了什么是主体,我的原话引在上面
  Widget _replyCard(NotifyItem n) {
    final sz = Theme.of(context).sz;
    final quote = n.kind == 'at' ? '' : _mine(n);
    final deleted = n.text == '该评论已删除';
    final line = _targetLine(n);
    return _bubble(
      onTap: () => unawaited(_openTarget(n, atComment: true)),
      buttons: _buttons(n),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _headline(n),
        if (quote.isNotEmpty) _quote(quote),
        if (n.text.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(n.text,
                maxLines: 4,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: kFontBodyLg, height: 1.5, color: deleted ? sz.inkMuted : sz.ink)),
          ),
        if (line != null) line,
      ]),
    );
  }

  /// 赞、关注、转发:服务端把一堆人合成一条,这里是几张脸 + 一句话 + 我的原话
  Widget _mergedCard(NotifyItem n) {
    final sz = Theme.of(context).sz;
    final a = notifyAvatars(n);
    final name = a.shown.isEmpty ? '有人' : a.shown.first.name;
    final suffix = switch (n.kind) {
      'follow' => '关注了你',
      'repost' => '转发了你的动态',
      _ => '赞了你的${notifyTargetWord(n)}',
    };
    final quote = n.kind == 'follow' ? '' : _mine(n);
    return _bubble(
      tail: false,
      onTap: () => unawaited(_openTarget(n, atComment: notifyTargetWord(n) == '评论')),
      buttons: _buttons(n),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          if (a.shown.isNotEmpty) Padding(padding: const EdgeInsets.only(right: 8), child: _faces(a.shown)),
          Expanded(
            child: _headline(n, spans: [
              TextSpan(text: name, style: const TextStyle(fontWeight: FontWeight.w600)),
              if (n.count > 1) ...[
                const TextSpan(text: ' 等 '),
                TextSpan(text: '${n.count}', style: szTabular(fontWeight: FontWeight.w600, color: sz.ink)),
                TextSpan(text: ' 人$suffix'),
              ] else
                TextSpan(text: ' $suffix'),
            ]),
          ),
        ]),
        if (quote.isNotEmpty) _quote(quote),
      ]),
    );
  }

  /// 赞合并时叠在一起的几张脸(最多 3 张)
  Widget _faces(List<VPerson> people) {
    final sz = Theme.of(context).sz;
    const size = 22.0, step = 15.0;
    return SizedBox(
      width: size + step * (people.length - 1),
      height: size,
      child: Stack(children: [
        for (var i = people.length - 1; i >= 0; i--)
          Positioned(
            left: step * i,
            child: Container(
              decoration: BoxDecoration(shape: BoxShape.circle, border: Border.all(color: sz.surface, width: 1.5)),
              child: SzImage(
                url: people[i].avatar.isEmpty ? '' : videoResolve(people[i].avatar),
                name: people[i].name,
                size: size - 3,
                circle: true,
              ),
            ),
          ),
      ]),
    );
  }

  Widget _systemCard(NotifyItem n) {
    final sz = Theme.of(context).sz;
    final action = '${n.data['action'] ?? ''}';
    final label = systemActionLabel(action);
    final bad = systemActionBad(action);
    final reason = '${n.data['reason_label'] ?? ''}';
    final code = '${n.data['reason_code'] ?? ''}';
    final coins = vInt(n.data['coins']);
    final color = bad ? sz.danger : (label.isEmpty ? sz.clay : sz.earn);
    final line = _targetLine(n);
    return _bubble(
      onTap: n.target.isEmpty ? null : () => unawaited(_openTarget(n)),
      buttons: _buttons(n),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _headline(n, spans: [TextSpan(text: notifyHeadline(n), style: const TextStyle(fontWeight: FontWeight.w600))]),
        if (label.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: VTag(label, color: color)),
        if (n.text.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(n.text, style: TextStyle(fontSize: kFontBodyLg, color: sz.ink, height: 1.5)),
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
            child: Text('+$coins 硬币', style: szTabular(fontSize: kFontNote, fontWeight: FontWeight.w600, color: sz.earn)),
          ),
        if (bad && action != 'failed' && action != 'appeal_upheld')
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
                n.target == 'release'
                    ? '觉得判错了可以在「音乐人中心」里申诉,会由另一名审核员复核'
                    : '觉得判错了可以在「创作中心」里申诉,会由另一名审核员复核',
                style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted, height: 1.5)),
          ),
        if (line != null) line,
      ]),
    );
  }
}

/// 按天分开的那一行小字(今天 / 昨天 / 9月11日 周四)
class _DayLabel extends StatelessWidget {
  const _DayLabel(this.day);

  final DateTime day;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 10, bottom: 4),
      child: Center(
        child: Text(dayLabel(day),
            style: TextStyle(fontSize: kFontMicro, color: Theme.of(context).sz.inkMuted)),
      ),
    );
  }
}
