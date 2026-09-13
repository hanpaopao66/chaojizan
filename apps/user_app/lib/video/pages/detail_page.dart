import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../chat/ui/avatar.dart';
import '../../session.dart';
import '../api.dart';
import '../comments/comments_view.dart';
import '../danmaku/sheets.dart';
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

/// 视频详情页(#361):播放器在上;下面「简介 / 评论」两个页签。
/// 简介里:UP 主卡(关注)、标题、播放数、弹幕数、发布时间、三连(长按点赞 1.5 秒 = 三连)、分享、
/// 简介展开、标签、分 P、挂的店铺(D16,有合作标「合作」)、相关视频;右上角举报、稍后再看。
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
    _load();
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
      _toast('硬币不够了(每天第一次看视频可以领 1 枚)');
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
              Text('硬币只能投给视频:每天第一次看视频领 1 枚、投稿过审得 2 枚;不能充值、提现、兑换。',
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
          child: Row(children: [
            TabBar(
              controller: _tabs,
              isScrollable: true,
              tabAlignment: TabAlignment.start,
              dividerColor: Colors.transparent,
              tabs: [const Tab(text: '简介'), Tab(text: '评论 ${vCount(_commentCount)}')],
            ),
            // 「点我发弹幕」和弹幕开关放在页签这一行(B 站的位置),稍后再看、举报收进「⋯」
            Expanded(child: player == null ? const SizedBox.shrink() : DanmakuSendBar(controller: player)),
            PopupMenuButton<String>(
              onSelected: (x) async {
                if (x == 'later') {
                  await _watchLater();
                } else if (x == 'report') {
                  if (!await _login()) return;
                  if (context.mounted) await reportTarget(context, targetType: 'video', vid: v.vid);
                }
              },
              itemBuilder: (_) => [
                PopupMenuItem(value: 'later', child: Text(v.me?.watchLater == true ? '从稍后再看移除' : '稍后再看')),
                const PopupMenuItem(value: 'report', child: Text('举报')),
              ],
            ),
          ]),
        ),
        const Divider(height: 1),
        Expanded(
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
      ]),
    );
  }

  Widget _intro(VideoDetail v) {
    final sz = Theme.of(context).sz;
    final up = v.uploader;
    final me = v.me;
    return ListView(padding: const EdgeInsets.only(bottom: 24), children: [
      if (up != null)
        ListTile(
          leading: GestureDetector(
            onTap: () => openUpSpace(context, up.id),
            child: ChatAvatar(name: up.name, url: up.avatar, size: 42),
          ),
          title: Text(up.name, style: const TextStyle(fontWeight: FontWeight.w600)),
          subtitle: Text('${vCount(up.fans)} 粉丝', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
          onTap: () => openUpSpace(context, up.id),
          trailing: v.isOwner
              ? null
              : FollowButton(
                  person: up,
                  dense: true,
                  onChanged: (p) => setState(() => v.card.uploader = p),
                ),
        ),
      Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 0),
        child: GestureDetector(
          onTap: () => setState(() => _descOpen = !_descOpen),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Text(v.card.title,
                    maxLines: _descOpen ? 6 : 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, height: 1.35)),
              ),
              Icon(_descOpen ? Icons.expand_less : Icons.expand_more, color: sz.inkFaint),
            ]),
            const SizedBox(height: 6),
            Wrap(spacing: 12, children: [
              _Stat(icon: Icons.play_circle_outline, text: vCount(v.card.views)),
              _Stat(icon: Icons.subtitles_outlined, text: vCount(v.card.danmakuCount)),
              Text(vAgo(v.card.publishedAt), style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              if (v.copyright == 'repost')
                Text('转载', style: TextStyle(fontSize: kFontNote, color: sz.hold)),
              if (v.status != 'published')
                Text(v.statusLabel, style: TextStyle(fontSize: kFontNote, color: sz.hold)),
            ]),
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
                child: Text(v.vid, style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
              ),
            ],
          ]),
        ),
      ),
      if (v.card.tags.isNotEmpty)
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 10, kPagePad, 0),
          child: Wrap(spacing: 8, runSpacing: 6, children: [
            for (final t in v.card.tags)
              ActionChip(
                label: Text(t, style: const TextStyle(fontSize: kFontNote)),
                visualDensity: VisualDensity.compact,
                onPressed: () => Navigator.of(context).push(MaterialPageRoute<void>(
                    builder: (_) => _TagPage(tag: t))),
              ),
          ]),
        ),
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
          _LikeButton(liked: me?.liked ?? false, count: v.card.likes, onTap: _like, onTriple: _triple),
          _ActionButton(
              icon: Icons.monetization_on_outlined,
              activeIcon: Icons.monetization_on,
              active: (me?.coins ?? 0) > 0,
              label: vCount(v.card.coins),
              semantic: '投币',
              onTap: _coin),
          _ActionButton(
              icon: Icons.star_border,
              activeIcon: Icons.star,
              active: me?.favorited ?? false,
              label: vCount(v.card.favorites),
              semantic: '收藏',
              onTap: _favorite),
          _ActionButton(
              icon: Icons.share_outlined,
              activeIcon: Icons.share,
              active: false,
              label: vCount(v.card.shares),
              semantic: '分享',
              onTap: () async {
                await shareVideo(context, v.card);
                if (mounted) setState(() {});
              }),
        ]),
      ),
      if (v.parts.length > 1) ...[
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 6),
          child: Text('选集(${v.parts.length})', style: const TextStyle(fontWeight: FontWeight.w600)),
        ),
        SizedBox(
          height: 44,
          child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 12), children: [
            for (var i = 0; i < v.parts.length; i++)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: ChoiceChip(
                  label: Text('P${i + 1} ${v.parts[i].title}'),
                  selected: _part == i,
                  onSelected: (_) => _switchPart(i),
                ),
              ),
          ]),
        ),
      ],
      if (v.shop != null) _ShopCard(shop: v.shop!, collab: v.shopCollab == true),
      if (_related.isNotEmpty) ...[
        Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 14, kPagePad, 2),
          child: Text('相关推荐', style: TextStyle(fontWeight: FontWeight.w600, color: sz.ink)),
        ),
        for (final c in _related) VideoRowTile(card: c, onTap: () => openVideo(context, c.vid)),
      ],
    ]);
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 14, color: sz.inkMuted),
      const SizedBox(width: 3),
      Text(text, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
    ]);
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({required this.icon, required this.activeIcon, required this.active, required this.label,
      required this.onTap, required this.semantic});

  final IconData icon;
  final IconData activeIcon;
  final bool active;
  final String label;
  final VoidCallback onTap;
  final String semantic;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Semantics(
      button: true,
      label: semantic,
      child: InkResponse(
        onTap: onTap,
        radius: 32,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(active ? activeIcon : icon, size: 28, color: active ? sz.clay : sz.inkMuted),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(fontSize: kFontNote, color: active ? sz.clay : sz.inkMuted)),
        ]),
      ),
    );
  }
}

/// 点赞按钮:点一下是赞 / 取消;按住 1.5 秒转一圈 = 三连(赞 + 投币 + 收藏),和 B 站一样。
class _LikeButton extends StatefulWidget {
  const _LikeButton({required this.liked, required this.count, required this.onTap, required this.onTriple});

  final bool liked;
  final int count;
  final VoidCallback onTap;
  final VoidCallback onTriple;

  @override
  State<_LikeButton> createState() => _LikeButtonState();
}

class _LikeButtonState extends State<_LikeButton> with SingleTickerProviderStateMixin {
  late final AnimationController _hold = AnimationController(vsync: this, duration: const Duration(milliseconds: 1500))
    ..addStatusListener((s) {
      if (s == AnimationStatus.completed) {
        widget.onTriple();
        _hold.reset();
      }
    });

  @override
  void dispose() {
    _hold.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Semantics(
      button: true,
      label: '点赞,长按三连',
      child: GestureDetector(
        onTap: widget.onTap,
        onLongPressStart: (_) => _hold.forward(from: 0),
        onLongPressEnd: (_) {
          if (_hold.isAnimating) _hold.reset();
        },
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          SizedBox(
            width: 40,
            height: 32,
            child: Stack(alignment: Alignment.center, children: [
              AnimatedBuilder(
                animation: _hold,
                builder: (_, __) => _hold.value == 0
                    ? const SizedBox.shrink()
                    : SizedBox(
                        width: 36,
                        height: 36,
                        child: CircularProgressIndicator(value: _hold.value, strokeWidth: 2.5, color: sz.clay),
                      ),
              ),
              Icon(widget.liked ? Icons.thumb_up : Icons.thumb_up_outlined, size: 26,
                  color: widget.liked ? sz.clay : sz.inkMuted),
            ]),
          ),
          const SizedBox(height: 2),
          Text(vCount(widget.count), style: TextStyle(fontSize: kFontNote, color: widget.liked ? sz.clay : sz.inkMuted)),
        ]),
      ),
    );
  }
}

/// 挂的店铺(D16):只能挂本平台的店;UP 主声明了「有合作」就标「合作」。平台不收推广费。
class _ShopCard extends StatelessWidget {
  const _ShopCard({required this.shop, required this.collab});

  final Map<String, dynamic> shop;
  final bool collab;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final logo = '${shop['logo'] ?? ''}';
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 8, kPagePad, 0),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: sz.surfaceAlt, borderRadius: BorderRadius.circular(kRadiusMd)),
        child: Row(children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(kRadiusSm),
            child: SizedBox(
              width: 44,
              height: 44,
              child: logo.isEmpty
                  ? Icon(Icons.storefront_outlined, color: sz.clay)
                  : Image(image: szNetImage(videoResolve(logo)), fit: BoxFit.cover),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text('${shop['name'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w600))),
                if (collab)
                  Container(
                    margin: const EdgeInsets.only(left: 6),
                    padding: const EdgeInsets.symmetric(horizontal: 5),
                    decoration: BoxDecoration(color: sz.hold, borderRadius: BorderRadius.circular(4)),
                    child: const Text('合作', style: TextStyle(color: Colors.white, fontSize: kFontMicro)),
                  ),
              ]),
              Text(collab ? 'UP 主和这家店有合作' : 'UP 主声明和这家店没有合作',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ]),
          ),
        ]),
      ),
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
