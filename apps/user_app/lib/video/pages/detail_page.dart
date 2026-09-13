import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/ui/avatar.dart';
import '../../session.dart';
import '../api.dart';
import '../comments/comments_view.dart';
import '../danmaku/sheets.dart';
import '../me/coins_page.dart';
import '../me/favorites_page.dart' show pickFavoriteFolders;
import '../models.dart';
import '../nav.dart';
import '../player/sz_video_controller.dart';
import '../player/sz_video_view.dart';
import '../widgets/cards.dart';
import '../widgets/feed.dart';
import '../widgets/follow_button.dart';
import '../widgets/report.dart';
import '../widgets/share.dart';
import '../widgets/shop_card.dart';
import '../widgets/triple_like_button.dart';

/// 视频详情页(#361,设计稿 E):播放器在上;下面「简介 / 评论」两个页签,页签那一行右边是「选集 N」和「⋯」。
/// 简介里从上往下:标题和播放 / 弹幕 / 发布时间、三连那一排(长按点赞 1.5 秒 = 三连)、UP 主和关注、
/// 硬币规则(原来藏在投币弹层里,只有已经想投币的人才看得到)、挂的店铺(D16,有合作标「合作」)、标签、相关视频。
/// 最底下一条「发个弹幕…」+「评论」,只在简介页签出现 —— 评论页签有它自己的输入条。
class VideoDetailPage extends StatefulWidget {
  const VideoDetailPage({super.key, required this.vid, this.commentId, this.rootCommentId, this.partIdx});

  final String vid;
  final int? commentId;
  final int? rootCommentId;
  final int? partIdx;

  @override
  State<VideoDetailPage> createState() => _VideoDetailPageState();
}

class _VideoDetailPageState extends State<VideoDetailPage> with SingleTickerProviderStateMixin {
  VideoDetail? _v;
  Object? _error;
  late final TabController _tabs = TabController(length: 2, vsync: this, initialIndex: widget.commentId != null ? 1 : 0);
  int _part = 0;
  List<VideoCard> _related = [];
  bool _descOpen = false;
  int _commentCount = 0;

  /// 播放器(#359):详情拉回来之后建一次;刷新详情(点赞失败回滚之类)不重建,不然会从头播
  SzVideoController? _player;

  @override
  void initState() {
    super.initState();
    _part = widget.partIdx ?? 0;
    // 底下那条「发个弹幕 / 评论」只在简介页签出现:换了页签要重画
    _tabs.addListener(_onTab);
    _load();
  }

  void _onTab() {
    if (!_tabs.indexIsChanging && mounted) setState(() {});
  }

  @override
  void dispose() {
    _player?.removeListener(_onPlayer);
    _player?.dispose();
    _tabs.dispose();
    super.dispose();
  }

  /// 上面盖了一整页(点相关视频进了下一个详情、进了 UP 主空间)就暂停,回来接着播;
  /// 进全屏也是盖一整页,但那是同一个播放器换个地方放,不能停
  bool _onstage = true;
  bool _resumeOnReturn = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final on = TickerMode.valuesOf(context).enabled;
    if (on == _onstage) return;
    _onstage = on;
    final c = _player;
    if (c == null || c.fullscreen) return;
    if (!on) {
      _resumeOnReturn = c.playing;
      if (c.playing) unawaited(c.pause());
    } else if (_resumeOnReturn) {
      _resumeOnReturn = false;
      unawaited(c.play());
    }
  }

  void _onPlayer() {
    final c = _player;
    // 连播换到下一 P 时,下面的选集跟着走
    if (c != null && mounted && c.partIndex != _part) setState(() => _part = c.partIndex);
  }

  Future<void> _load({bool refresh = false}) async {
    try {
      final v = await videoApi.detail(widget.vid);
      if (!mounted) return;
      setState(() {
        _v = v;
        _commentCount = v.card.commentCount;
        if (!refresh) {
          if (widget.partIdx == null && v.me?.progress != null) _part = v.me!.progress!.partIdx;
          if (_part >= v.parts.length) _part = 0;
        }
      });
      if (refresh) return;
      if (v.parts.isNotEmpty) {
        final c = SzVideoController(video: v, partIndex: _part);
        // 一 P 播完:有下一 P 就接着放(B 站的「自动连播」),最后一 P 停在结束画面
        c.onPartEnded = (i) {
          if (i + 1 < v.parts.length) unawaited(c.switchPart(i + 1));
        };
        c.addListener(_onPlayer);
        _player = c;
        unawaited(c.initialize());
      }
      videoApi.related(widget.vid).then((r) {
        if (mounted) setState(() => _related = r);
      }).catchError((_) {});
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  void _switchPart(int i) {
    setState(() => _part = i);
    unawaited(_player?.switchPart(i));
  }

  void _toast(String s) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(s)));
  }

  // ---------------- 互动 ----------------

  Future<bool> _login() async => await ensureLoggedIn(context) && mounted;

  Future<void> _like() async {
    final v = _v;
    if (v == null || !await _login()) return;
    final me = v.me ??= VideoMe();
    final want = !me.liked;
    setState(() {
      me.liked = want;
      v.card.likes += want ? 1 : -1;
    });
    try {
      final r = await videoApi.like(v.vid, want);
      setState(() {
        me.liked = r['liked'] == true;
        v.card.likes = vInt(r['likes']);
      });
    } on ApiException catch (e) {
      _toast(e.message);
      await _load(refresh: true);
    }
  }

  Future<void> _coin() async {
    final v = _v;
    if (v == null || !await _login()) return;
    final me = v.me ??= VideoMe();
    if (v.isOwner) {
      _toast('不能给自己的视频投币');
      return;
    }
    final left = me.coinMax - me.coins;
    if (left <= 0) {
      _toast('这个视频你已经投满 ${me.coinMax} 枚了');
      return;
    }
    if (me.coinBalance <= 0) {
      _toast('硬币不够了(每天第一次打开视频可以领 1 枚)');
      return;
    }
    // 缺省投得起的最多那档:余额只有 1 枚就别预选 2 枚
    var amount = [left, me.coinBalance, 2].reduce((a, b) => a < b ? a : b);
    var alsoLike = !me.liked;
    if (!mounted) return;
    final ok = await szShowSheet<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(kPagePad),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text('给 UP 主投币(你有 ${me.coinBalance} 枚)', style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
              const SizedBox(height: 14),
              Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                for (final n in [1, 2])
                  if (n <= left)
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 8),
                      child: ChoiceChip(
                        label: Text('$n 枚'),
                        selected: amount == n,
                        onSelected: n > me.coinBalance ? null : (_) => set(() => amount = n),
                      ),
                    ),
              ]),
              CheckboxListTile(
                value: alsoLike,
                onChanged: (x) => set(() => alsoLike = x ?? false),
                title: const Text('同时点赞'),
                controlAffinity: ListTileControlAffinity.leading,
              ),
              Text('硬币只能投给视频:每天第一次打开视频领 1 枚、投稿过审得 2 枚;不能充值、提现、兑换。',
                  style: TextStyle(fontSize: kFontNote, color: Theme.of(ctx).sz.inkMuted)),
              const SizedBox(height: 12),
              SizedBox(width: double.infinity, child: FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('投币'))),
            ]),
          ),
        ),
      ),
    );
    if (ok != true) return;
    try {
      final r = await videoApi.coin(v.vid, amount, alsoLike: alsoLike);
      setState(() {
        me.coins = vInt(r['coins_given']);
        me.coinBalance = vInt(r['coin_balance']);
        v.card.coins = vInt(r['coins']);
        if (alsoLike && !me.liked) {
          me.liked = true;
          v.card.likes += 1;
        }
      });
      _toast('投了 $amount 枚硬币');
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  /// 点收藏:弹收藏夹选择(可以多选、可以新建;全不选 = 取消收藏),和 B 站一样
  Future<void> _favorite() async {
    final v = _v;
    if (v == null || !await _login()) return;
    final me = v.me ??= VideoMe();
    if (!mounted) return;
    final ids = await pickFavoriteFolders(context, current: me.folderIds);
    if (ids == null) return;
    try {
      final r = await videoApi.favorite(v.vid, folderIds: ids);
      setState(() {
        me.favorited = r['favorited'] == true;
        me.folderIds = [for (final x in vList(r['folder_ids'])) vInt(x)];
        v.card.favorites = vInt(r['favorites']);
      });
      _toast(me.favorited ? '已收藏' : '已取消收藏');
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _triple() async {
    final v = _v;
    if (v == null || !await _login()) return;
    try {
      final r = await videoApi.triple(v.vid);
      setState(() {
        v.me = VideoMe.fromJson(r['me']);
        v.card.likes = vInt(r['likes']);
        v.card.coins = vInt(r['coins']);
        v.card.favorites = vInt(r['favorites']);
      });
      final note = '${r['coin_note'] ?? ''}';
      _toast(note.isEmpty ? '三连成功!' : '三连成功($note)');
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _watchLater() async {
    final v = _v;
    if (v == null || !await _login()) return;
    try {
      if (v.me?.watchLater == true) {
        await videoApi.removeWatchLater(v.vid);
        setState(() => v.me?.watchLater = false);
        _toast('已从稍后再看移除');
      } else {
        await videoApi.addWatchLater(v.vid);
        setState(() => v.me?.watchLater = true);
        _toast('已加入稍后再看');
      }
    } on ApiException catch (e) {
      _toast(e.message);
    }
  }

  // ---------------- 界面 ----------------

  @override
  Widget build(BuildContext context) {
    final v = _v;
    if (v == null) {
      return SzPageScaffold(
        appBar: AppBar(),
        body: _error != null
            ? Center(
                child: VideoApi.isOff(_error!)
                    ? const SzEmpty(text: '视频功能暂未开放')
                    : SzError(error: _error, onRetry: _load),
              )
            : const Center(child: CircularProgressIndicator()),
      );
    }
    final player = _player;
    final sz = Theme.of(context).sz;
    return Scaffold(
      body: Column(children: [
        Container(
          color: Colors.black,
          child: SafeArea(
            bottom: false,
            child: AspectRatio(
              aspectRatio: 16 / 9,
              child: player == null
                  ? const Center(child: Text('这个视频还没有能播放的分 P', style: TextStyle(color: Colors.white70)))
                  : SzVideoView(
                      controller: player,
                      title: v.card.title,
                      onBack: () => Navigator.of(context).maybePop(),
                    ),
            ),
          ),
        ),
        Material(
          color: Theme.of(context).scaffoldBackgroundColor,
          child: DecoratedBox(
            decoration: BoxDecoration(border: Border(bottom: BorderSide(color: sz.line))),
            child: Row(children: [
              TabBar(
                controller: _tabs,
                isScrollable: true,
                tabAlignment: TabAlignment.start,
                padding: const EdgeInsets.only(left: kPagePad - 12),
                labelPadding: const EdgeInsets.symmetric(horizontal: 12),
                indicator: SzTabUnderline(color: sz.clay, width: 24),
                dividerColor: Colors.transparent,
                tabs: [const Tab(text: '简介', height: 42), Tab(text: '评论 ${vCount(_commentCount)}', height: 42)],
              ),
              const Spacer(),
              if (v.parts.length > 1)
                TextButton(
                  style: TextButton.styleFrom(
                    foregroundColor: sz.inkMuted,
                    minimumSize: const Size(44, 40),
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    textStyle: const TextStyle(fontSize: kFontNote),
                  ),
                  onPressed: () => _pickPart(v),
                  child: Text('选集 ${v.parts.length}'),
                ),
              // 稍后再看、弹幕设置、举报收进「⋯」;弹幕开关在播放器的控制条上
              PopupMenuButton<String>(
                icon: Icon(Icons.more_vert, color: sz.inkMuted),
                onSelected: (x) async {
                  if (x == 'later') {
                    await _watchLater();
                  } else if (x == 'danmaku') {
                    if (player != null) await showDanmakuSettings(context, player.danmaku);
                  } else if (x == 'report') {
                    if (!await _login()) return;
                    if (context.mounted) await reportTarget(context, targetType: 'video', vid: v.vid);
                  }
                },
                itemBuilder: (_) => [
                  PopupMenuItem(value: 'later', child: Text(v.me?.watchLater == true ? '从稍后再看移除' : '稍后再看')),
                  if (player != null && player.danmaku.allowDanmaku)
                    const PopupMenuItem(value: 'danmaku', child: Text('弹幕设置')),
                  const PopupMenuItem(value: 'report', child: Text('举报')),
                ],
              ),
            ]),
          ),
        ),
        Expanded(
          // 播放器那块已经让过状态栏;下面的评论列表别再按顶部安全区补一次(手机上「评论 N」上面会空一截)
          child: MediaQuery.removePadding(
            context: context,
            removeTop: true,
            child: TabBarView(controller: _tabs, children: [
              _intro(v),
              VideoComments(
                vid: v.vid,
                uploaderId: v.uploader?.id ?? 0,
                allowComments: v.allowComments,
                focusCommentId: widget.commentId,
                focusRootId: widget.rootCommentId,
                onCount: (n) {
                  if (mounted && n != _commentCount) setState(() => _commentCount = n);
                },
              ),
            ]),
          ),
        ),
        if (_tabs.index == 0) _bottomBar(player),
      ]),
    );
  }

  /// 简介页签最底下:「发个弹幕…」和「评论」(点了去评论页签,那里有写评论的输入条)
  Widget _bottomBar(SzVideoController? player) {
    final sz = Theme.of(context).sz;
    return Container(
      decoration: BoxDecoration(color: sz.paper, border: Border(top: BorderSide(color: sz.line))),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(14, 8, 14, 8),
          child: Row(children: [
            if (player != null) Expanded(child: DanmakuSendBar(controller: player)) else const Spacer(),
            const SizedBox(width: 8),
            OutlinedButton(
              style: OutlinedButton.styleFrom(
                foregroundColor: sz.inkMuted,
                minimumSize: const Size(0, 36),
                padding: const EdgeInsets.symmetric(horizontal: 15),
                textStyle: const TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w500),
              ),
              onPressed: () => _tabs.animateTo(1),
              child: const Text('评论'),
            ),
          ]),
        ),
      ),
    );
  }

  /// 「选集 N」:弹层里列出每一 P,正在放的那一 P 标出来
  Future<void> _pickPart(VideoDetail v) async {
    final pick = await szShowSheet<int>(
      context: context,
      builder: (ctx) {
        final sz = Theme.of(ctx).sz;
        return SafeArea(
          child: ListView(shrinkWrap: true, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 6),
              child: Text('选集(${v.parts.length})', style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
            ),
            for (var i = 0; i < v.parts.length; i++)
              ListTile(
                selected: _part == i,
                selectedColor: sz.clay,
                leading: Text('P${i + 1}', style: szTabular(fontSize: kFontBodyLg, fontWeight: FontWeight.w600)),
                title: Text(v.parts[i].title.isEmpty ? '第 ${i + 1} P' : v.parts[i].title,
                    maxLines: 1, overflow: TextOverflow.ellipsis),
                trailing: _part == i ? Icon(Icons.equalizer, color: sz.clay) : null,
                onTap: () => Navigator.pop(ctx, i),
              ),
          ]),
        );
      },
    );
    if (pick != null && pick != _part) _switchPart(pick);
  }

  Widget _intro(VideoDetail v) {
    final sz = Theme.of(context).sz;
    final up = v.uploader;
    final me = v.me;
    Widget pad(Widget w, {double top = 13}) =>
        Padding(padding: EdgeInsets.fromLTRB(kPagePad, top, kPagePad, 0), child: w);
    final ago = vAgo(v.card.publishedAt);
    final stats = [
      '${vCount(v.card.views)} 播放',
      '${vCount(v.card.danmakuCount)} 弹幕',
      // 「9-11 发布」日期后面空一格;「3 小时前发布」「昨天发布」不空
      if (ago.isNotEmpty) '$ago${RegExp(r'\d$').hasMatch(ago) ? ' ' : ''}发布',
    ].join(' · ');
    return ListView(padding: const EdgeInsets.only(bottom: 20), children: [
      pad(
        top: 14,
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => setState(() => _descOpen = !_descOpen),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Text(v.card.title,
                    maxLines: _descOpen ? 6 : 2,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, height: 1.35, color: sz.ink)),
              ),
              Padding(
                padding: const EdgeInsets.only(left: 6, top: 1),
                child: Icon(_descOpen ? Icons.expand_less : Icons.expand_more, size: 20, color: sz.inkFaint),
              ),
            ]),
            const SizedBox(height: 5),
            Text.rich(
              TextSpan(children: [
                TextSpan(text: stats),
                if (v.copyright == 'repost') TextSpan(text: ' · 转载', style: TextStyle(color: sz.hold)),
                if (v.status != 'published') TextSpan(text: ' · ${v.statusLabel}', style: TextStyle(color: sz.hold)),
              ]),
              style: szTabular(fontSize: kFontNote, color: sz.inkMuted),
            ),
            if (_descOpen) ...[
              const SizedBox(height: 8),
              SelectableText(v.description.isEmpty ? '(UP 主没写简介)' : v.description,
                  style: TextStyle(fontSize: kFontBody, color: sz.inkMuted, height: 1.5)),
              if (v.copyright == 'repost' && v.sourceUrl.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: SelectableText('转载自 ${v.sourceUrl}', style: TextStyle(fontSize: kFontNote, color: sz.link)),
                ),
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(v.vid, style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
              ),
            ],
          ]),
        ),
      ),
      // 三连那一排:上下两道发丝线夹着,下面一行小字说长按是三连
      pad(
        Container(
          padding: const EdgeInsets.symmetric(vertical: 9),
          decoration: BoxDecoration(border: Border.symmetric(horizontal: BorderSide(color: sz.line))),
          child: Row(children: [
            Expanded(
              child: Center(
                child: TripleLikeButton(liked: me?.liked ?? false, count: v.card.likes, onTap: _like, onTriple: _triple),
              ),
            ),
            Expanded(
              child: Center(
                child: VideoActionButton(
                    icon: Icons.monetization_on_outlined,
                    activeIcon: Icons.monetization_on,
                    active: (me?.coins ?? 0) > 0,
                    count: v.card.coins,
                    semantic: '投币',
                    onTap: _coin),
              ),
            ),
            Expanded(
              child: Center(
                child: VideoActionButton(
                    icon: Icons.star_border,
                    activeIcon: Icons.star,
                    active: me?.favorited ?? false,
                    count: v.card.favorites,
                    semantic: '收藏',
                    onTap: _favorite),
              ),
            ),
            Expanded(
              child: Center(
                child: VideoActionButton(
                    icon: Icons.reply,
                    activeIcon: Icons.reply,
                    flip: true,
                    active: false,
                    count: v.card.shares,
                    semantic: '分享',
                    onTap: () async {
                      await shareVideo(context, v.card);
                      if (mounted) setState(() {});
                    }),
              ),
            ),
          ]),
        ),
      ),
      Padding(
        padding: const EdgeInsets.only(top: 5),
        child: Center(
          child: Text('长按点赞 = 三连(赞 + 投币 + 收藏)', style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        ),
      ),
      if (up != null)
        pad(Row(children: [
          GestureDetector(
            onTap: () => openUpSpace(context, up.id),
            child: ChatAvatar(name: up.name, url: up.avatar, size: 40),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: () => openUpSpace(context, up.id),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(up.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
                Text('${vCount(up.fans)} 粉丝', style: szTabular(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
            ),
          ),
          if (!v.isOwner)
            FollowButton(person: up, outlined: true, onChanged: (p) => setState(() => v.card.uploader = p)),
        ])),
      pad(_coinRules(me)),
      if (v.shop != null) pad(VideoShopCard(shop: v.shop!, collab: v.shopCollab == true || v.card.collab)),
      if (v.card.tags.isNotEmpty)
        pad(Wrap(spacing: 8, runSpacing: 8, children: [
          for (final t in v.card.tags)
            Material(
              color: Colors.transparent,
              shape: StadiumBorder(side: BorderSide(color: sz.line)),
              clipBehavior: Clip.antiAlias,
              child: InkWell(
                onTap: () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => _TagPage(tag: t))),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  child: Text('#$t', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                ),
              ),
            ),
        ])),
      if (_related.isNotEmpty) ...[
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 18, kPagePad, 2),
          child: Text('相关推荐', style: TextStyle(fontWeight: FontWeight.w600, color: sz.ink)),
        ),
        for (final c in _related) VideoRowTile(card: c, onTap: () => openVideo(context, c.vid)),
      ],
    ]);
  }

  /// 硬币规则挪到明面上(设计稿 E):原来这段话只在投币弹层里,只有已经想投币的人才看得到。
  /// 规则照代码写:每天第一次打开视频 +1,投稿过审 +2(每天最多 10 枚);不能充值、提现、兑换。
  Widget _coinRules(VideoMe? me) {
    final sz = Theme.of(context).sz;
    return SzCard(
      padding: const EdgeInsets.fromLTRB(kCardPad, 13, kCardPad, 13),
      onTap: rootApi.isLoggedIn
          ? () => Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const CoinsPage()))
          : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
          Expanded(
            child: Text('硬币只能投给视频',
                style: TextStyle(fontSize: kFontBodyLg, fontWeight: FontWeight.w600, color: sz.ink)),
          ),
          if (me != null)
            Text('你有 ${me.coinBalance} 枚',
                style: szTabular(fontSize: kFigureSm, fontWeight: FontWeight.w600, color: sz.hold)),
        ]),
        const SizedBox(height: 5),
        Text.rich(
          TextSpan(children: [
            const TextSpan(text: '每天第一次打开视频领 1 枚,投稿过审得 2 枚(每天最多 10 枚)。'),
            TextSpan(text: '不能充值、不能提现、不能兑换', style: TextStyle(fontWeight: FontWeight.w600, color: sz.ink)),
            const TextSpan(text: ' —— 它不是钱,是一句「这条值得」。'),
          ]),
          style: TextStyle(fontSize: kFontNote, color: sz.inkMuted, height: 1.6),
        ),
      ]),
    );
  }
}

class _TagPage extends StatelessWidget {
  const _TagPage({required this.tag});

  final String tag;

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      appBar: AppBar(title: Text('#$tag')),
      body: VideoFeed(load: (page, _) => videoApi.search(tag, page: page), emptyText: '没有带这个标签的视频'),
    );
  }
}
