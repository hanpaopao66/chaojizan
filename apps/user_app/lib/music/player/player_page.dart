// 全屏播放页(§2.1 播放器全套):模糊封面打底、封面 / 歌词点一下互换、
// 喜欢 / 评论 / 分享 / 加到歌单、进度条、播放模式、上一首 / 播放 / 下一首、
// 队列、音质、定时关闭。
import 'dart:async';
import 'dart:ui';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/models.dart';
import '../models.dart';
import '../nav.dart';
import '../widgets/add_to_playlist.dart';
import '../widgets/common.dart';
import 'lyrics.dart';
import 'music_player.dart';
import 'queue_sheet.dart';

class MusicPlayerPage extends StatefulWidget {
  const MusicPlayerPage({super.key, this.player});

  final MusicPlayer? player;

  @override
  State<MusicPlayerPage> createState() => _MusicPlayerPageState();
}

class _MusicPlayerPageState extends State<MusicPlayerPage> {
  MusicPlayer get p => widget.player ?? MusicPlayer.instance;

  /// 点封面翻到歌词那一面
  bool _showLyrics = false;

  /// 拖进度条的时候不跟着播放进度跳 —— 手指还按着呢
  double? _dragging;

  /// 这首歌的歌词。换歌就重新拉
  String _lyricsFor = '';
  Lyrics _lyrics = Lyrics.none;
  bool _lyricsLoading = false;
  final ScrollController _lyricScroll = ScrollController();
  int _lastLine = -1;

  @override
  void initState() {
    super.initState();
    p.addListener(_onPlayer);
    _syncLyrics();
  }

  @override
  void dispose() {
    p.removeListener(_onPlayer);
    _lyricScroll.dispose();
    super.dispose();
  }

  void _onPlayer() {
    _syncLyrics();
    _followLyrics();
  }

  void _syncLyrics() {
    final t = p.current;
    if (t == null || t.tid == _lyricsFor || _lyricsLoading) return;
    _lyricsFor = t.tid;
    _lyrics = Lyrics.none;
    _lastLine = -1;
    _lyricsLoading = true;
    unawaited(() async {
      try {
        final r = await musicApi.lyrics(t.tid);
        if (mounted && _lyricsFor == t.tid) setState(() => _lyrics = parseLyrics(r.text, kind: r.kind));
      } catch (_) {
        // 歌词拉不到不影响听歌,那一面显示「暂无歌词」
      } finally {
        _lyricsLoading = false;
      }
    }());
  }

  /// 唱到哪一句就把哪一句滚到中间。用户自己在翻歌词的时候不抢(没做手动锁,
  /// 但只在「行号变了」时才滚一次,不是每帧都拽)
  void _followLyrics() {
    if (!_showLyrics || !_lyrics.synced || !_lyricScroll.hasClients) return;
    final i = _lyrics.indexAt(p.position.inMilliseconds);
    if (i < 0 || i == _lastLine) return;
    _lastLine = i;
    final target = (i * _lyricLineHeight - _lyricScroll.position.viewportDimension / 2 + _lyricLineHeight)
        .clamp(0.0, _lyricScroll.position.maxScrollExtent);
    _lyricScroll.animateTo(target, duration: const Duration(milliseconds: 260), curve: Curves.easeOut);
  }

  static const double _lyricLineHeight = 34;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: p,
      builder: (context, _) {
        final t = p.current;
        if (t == null) {
          return SzPageScaffold(
            appBar: AppBar(title: const Text('播放')),
            body: SzEmpty(text: '还没有在放的歌', actionLabel: '去听点什么', onAction: () => openMusicHome(context)),
          );
        }
        final sz = Theme.of(context).sz;
        return SzPageScaffold(
          contentMaxWidth: kContentMaxWidth,
          appBar: AppBar(
            backgroundColor: Colors.transparent,
            elevation: 0,
            title: Column(children: [
              Text(t.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: kFontTitle)),
              if (t.artistName.isNotEmpty)
                Text(t.artistName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
            ]),
            actions: [
              IconButton(
                icon: const Icon(Icons.more_horiz),
                tooltip: '更多',
                onPressed: () => showTrackMenu(context, t),
              ),
            ],
          ),
          body: Stack(children: [
            _BlurCover(url: t.cover, name: t.title),
            SafeArea(
              child: Column(children: [
                Expanded(child: _face(context, t)),
                _actions(context, t),
                _progress(context),
                _controls(),
                const SizedBox(height: 8),
                _bottomRow(context),
                const SizedBox(height: 10),
              ]),
            ),
          ]),
        );
      },
    );
  }

  /// 封面那一面 / 歌词那一面,点一下互换
  Widget _face(BuildContext context, MTrack t) {
    return GestureDetector(
      onTap: () {
        setState(() => _showLyrics = !_showLyrics);
        _lastLine = -1;
        // 翻到歌词面时先对一次位置,不然要等下一次进度事件才滚过去
        WidgetsBinding.instance.addPostFrameCallback((_) => _followLyrics());
      },
      child: _showLyrics ? _lyricsFace(context) : _coverFace(context, t),
    );
  }

  Widget _coverFace(BuildContext context, MTrack t) {
    final sz = Theme.of(context).sz;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
          LayoutBuilder(
            builder: (context, box) {
              final side = [box.maxWidth, box.maxHeight - 40, 320.0].reduce((a, b) => a < b ? a : b);
              return MCover(url: t.cover, name: t.title, size: side <= 0 ? 120 : side, radius: kRadiusLg);
            },
          ),
          const SizedBox(height: 14),
          Text('点封面看歌词', style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
        ]),
      ),
    );
  }

  Widget _lyricsFace(BuildContext context) {
    final sz = Theme.of(context).sz;
    if (_lyrics.isEmpty) {
      return Center(child: Text('暂无歌词', style: TextStyle(color: sz.inkMuted)));
    }
    final now = _lyrics.indexAt(p.position.inMilliseconds);
    return ListView.builder(
      controller: _lyricScroll,
      padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
      itemCount: _lyrics.lines.length,
      itemBuilder: (context, i) {
        final line = _lyrics.lines[i];
        final on = _lyrics.synced && i == now;
        return SizedBox(
          height: line.text.isEmpty ? _lyricLineHeight / 2 : _lyricLineHeight,
          child: Align(
            alignment: Alignment.center,
            child: Text(
              line.text,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: on ? kFontTitle : kFontBodyLg,
                height: 1.4,
                color: on ? sz.clay : sz.inkMuted,
                fontWeight: on ? FontWeight.w600 : FontWeight.w400,
              ),
            ),
          ),
        );
      },
    );
  }

  /// 喜欢、评论、分享、加到歌单
  Widget _actions(BuildContext context, MTrack t) {
    final sz = Theme.of(context).sz;
    return Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
      _IconText(
        icon: t.liked ? Icons.favorite : Icons.favorite_border,
        color: t.liked ? sz.clay : null,
        label: vCount(t.likes),
        tooltip: t.liked ? '取消喜欢' : '喜欢',
        onTap: () => _like(t),
      ),
      _IconText(
        icon: Icons.mode_comment_outlined,
        label: vCount(t.comments),
        tooltip: '评论',
        onTap: () => openMusicComments(context, t),
      ),
      _IconText(
        icon: Icons.playlist_add,
        label: '歌单',
        tooltip: '加到歌单',
        onTap: () => addToPlaylistSheet(context, [t.tid]),
      ),
      _IconText(
        icon: Icons.ios_share,
        label: '分享',
        tooltip: '分享',
        onTap: () => shareMusic(context, 'track', t.tid, t.title),
      ),
    ]);
  }

  Future<void> _like(MTrack t) async {
    if (!await ensureLoggedIn(context)) return;
    try {
      final r = await musicApi.likeTrack(t.tid, !t.liked);
      if (!mounted) return;
      setState(() {
        t.liked = r.liked;
        t.likes = r.likes;
      });
    } catch (e) {
      if (mounted) mToast(context, e);
    }
  }

  Widget _progress(BuildContext context) {
    final sz = Theme.of(context).sz;
    final total = p.duration.inMilliseconds;
    final at = _dragging ?? p.progress;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 18),
      child: Row(children: [
        SizedBox(
          width: 44,
          child: Text(vDuration(((_dragging ?? p.progress) * total).round()),
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        ),
        Expanded(
          child: Slider(
            value: at.clamp(0.0, 1.0),
            onChanged: total <= 0 ? null : (v) => setState(() => _dragging = v),
            onChangeEnd: total <= 0
                ? null
                : (v) {
                    setState(() => _dragging = null);
                    p.seekTo(Duration(milliseconds: (v * total).round()));
                  },
          ),
        ),
        SizedBox(
          width: 44,
          child: Text(vDuration(total),
              textAlign: TextAlign.right, style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        ),
      ]),
    );
  }

  // context 不从参数进来:这几个回调里要在 await 之后用它,
  // 用 State 自己的 context 才好拿 mounted 把关
  Widget _controls() {
    final sz = Theme.of(context).sz;
    return Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
      IconButton(
        icon: Icon(musicModeIcon(p.mode)),
        tooltip: p.mode.label,
        onPressed: () async {
          await p.cycleMode();
          if (mounted) mToast(context, p.mode.label);
        },
      ),
      IconButton(iconSize: 34, icon: const Icon(Icons.skip_previous), tooltip: '上一首', onPressed: p.prev),
      // 正在取地址 / 缓冲时把播放键换成转圈,不然点下去半天没反应像是卡了
      SizedBox(
        width: 62,
        height: 62,
        child: p.buffering
            ? const Padding(padding: EdgeInsets.all(14), child: CircularProgressIndicator(strokeWidth: 2))
            : IconButton.filled(
                iconSize: 34,
                style: IconButton.styleFrom(backgroundColor: sz.clay, foregroundColor: sz.paper),
                icon: Icon(p.playing ? Icons.pause : Icons.play_arrow),
                tooltip: p.playing ? '暂停' : '播放',
                onPressed: p.toggle,
              ),
      ),
      IconButton(iconSize: 34, icon: const Icon(Icons.skip_next), tooltip: '下一首', onPressed: () => p.next()),
      IconButton(icon: const Icon(Icons.queue_music), tooltip: '播放队列', onPressed: () => showMusicQueue(context, player: p)),
    ]);
  }

  /// 音质、定时关闭
  Widget _bottomRow(BuildContext context) {
    final sz = Theme.of(context).sz;
    final sleep = p.sleepRemaining;
    final sleeping = sleep != null || p.sleepAfterTrack;
    return Row(mainAxisAlignment: MainAxisAlignment.center, children: [
      TextButton.icon(
        onPressed: _pickQuality,
        icon: const Icon(Icons.graphic_eq, size: 18),
        label: Text(mQualityName(p.quality), style: const TextStyle(fontSize: kFontNote)),
      ),
      const SizedBox(width: 12),
      TextButton.icon(
        onPressed: _pickSleep,
        icon: Icon(Icons.bedtime_outlined, size: 18, color: sleeping ? sz.clay : null),
        label: Text(
          p.sleepAfterTrack ? '播完这首' : (sleep == null ? '定时关闭' : '还有 ${sleep.inMinutes + 1} 分钟'),
          style: TextStyle(fontSize: kFontNote, color: sleeping ? sz.clay : null),
        ),
      ),
    ]);
  }

  Future<void> _pickQuality() async {
    final q = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const ListTile(title: Text('音质')),
          const Divider(height: 1),
          for (final q in [kQualityStd, kQualityHq])
            ListTile(
              title: Text(mQualityName(q)),
              subtitle: Text(q == kQualityStd ? 'AAC 128k,省流量' : 'AAC 256k;这首没有高品质档时自动用标准',
                  style: const TextStyle(fontSize: kFontNote)),
              trailing: p.quality == q ? const Icon(Icons.check) : null,
              onTap: () => Navigator.pop(ctx, q),
            ),
        ]),
      ),
    );
    if (q != null) await p.setQuality(q);
  }

  Future<void> _pickSleep() async {
    final pick = await szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            title: const Text('定时关闭'),
            subtitle: p.sleepRemaining == null
                ? null
                : Text('还有 ${p.sleepRemaining!.inMinutes + 1} 分钟', style: const TextStyle(fontSize: kFontNote)),
          ),
          const Divider(height: 1),
          for (final m in [15, 30, 60]) ListTile(title: Text('$m 分钟后'), onTap: () => Navigator.pop(ctx, '$m')),
          ListTile(
            title: const Text('播完这首再停'),
            trailing: p.sleepAfterTrack ? const Icon(Icons.check) : null,
            onTap: () => Navigator.pop(ctx, 'track'),
          ),
          ListTile(title: const Text('不定时'), onTap: () => Navigator.pop(ctx, 'off')),
        ]),
      ),
    );
    if (pick == null || !mounted) return;
    switch (pick) {
      case 'off':
        p.setSleepTimer(null);
        mToast(context, '已取消定时');
      case 'track':
        p.setSleepAfterTrack(true);
        mToast(context, '这首播完就停');
      default:
        final m = int.tryParse(pick) ?? 30;
        p.setSleepTimer(Duration(minutes: m));
        mToast(context, '$m 分钟后停');
    }
  }
}

/// 模糊封面打底:一张放大糊掉的封面,上面压一层半透明的纸色,
/// 好让歌词和按钮在任何封面上都读得清。
class _BlurCover extends StatelessWidget {
  const _BlurCover({required this.url, required this.name});

  final String url;
  final String name;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    if (url.isEmpty) return Positioned.fill(child: ColoredBox(color: sz.paper));
    return Positioned.fill(
      child: Stack(fit: StackFit.expand, children: [
        Image(image: szNetImage(musicResolve(url)), fit: BoxFit.cover, errorBuilder: (_, __, ___) => ColoredBox(color: sz.paper)),
        BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 40, sigmaY: 40),
          child: ColoredBox(color: sz.paper.withValues(alpha: .86)),
        ),
      ]),
    );
  }
}

class _IconText extends StatelessWidget {
  const _IconText({required this.icon, required this.label, required this.onTap, this.color, this.tooltip});

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Color? color;
  final String? tooltip;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    // 图标下面就是那行字,不再套 Tooltip —— 重复一遍同样的话没用,
    // 触屏上还会把长按吃掉
    return Semantics(
      button: true,
      label: tooltip ?? label,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(kRadiusMd),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 24, color: color ?? sz.ink),
            const SizedBox(height: 2),
            Text(label, style: TextStyle(fontSize: kFontMicro, color: color ?? sz.inkMuted)),
          ]),
        ),
      ),
    );
  }
}
