// 音乐模块里到处都在用的小件:错误怎么摆、歌曲行、歌单 / 专辑 / 音乐人卡片、
// 算分中间量那一行。翻页器、确认框、登录引导直接用视频那边的 —— 全站一套。
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart';
import '../../video/models.dart';
import '../api.dart';
import '../models.dart';
import '../nav.dart';
import '../player/music_player.dart';
import 'add_to_playlist.dart';

/// 音乐接口的错误怎么摆:503 是开关关着(§5.2「音乐暂未开放」),
/// 给空状态、**不给重试按钮** —— 重试一百次也还是关着;其他错误给重试。
Widget musicErrorView(Object? error, VoidCallback onRetry) {
  if (error != null && MusicApi.isOff(error)) return SzEmpty(text: '$error');
  return SzError(error: error, onRetry: onRetry);
}

/// 给用户看的一句话:服务端的 detail 原样展示,网络问题 ApiClient 已经翻成人话。
String musicErrorText(Object e) => e is ApiException ? e.message : '$e';

void mToast(BuildContext context, Object message) => vToast(context, message);

/// 分享弹层:给哪几条路。抽出来是因为 nav.dart 不该直接堆界面。
///
/// [toForum] 是「发到动态」露不露 —— 论坛这一格在金刚区被关掉时,写完一条帖子
/// 才被 503 顶回来比没有这个入口更糟(ChannelConfig 是同步的,不发请求)。
Future<String?> szShowSheetForShare(BuildContext context, String title, {bool toForum = false}) =>
    szShowSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis)),
          const Divider(height: 1),
          ListTile(
              leading: const Icon(Icons.send_outlined),
              title: const Text('发到消息'),
              onTap: () => Navigator.pop(ctx, 'chat')),
          if (toForum)
            ListTile(
                leading: const Icon(Icons.forum_outlined),
                title: const Text('发到动态'),
                onTap: () => Navigator.pop(ctx, 'forum')),
          ListTile(leading: const Icon(Icons.link), title: const Text('复制链接'), onTap: () => Navigator.pop(ctx, 'link')),
          ListTile(leading: const Icon(Icons.ios_share), title: const Text('更多'), onTap: () => Navigator.pop(ctx, 'other')),
        ]),
      ),
    );

/// 「拉一次、画出来、失败能重试、能下拉刷新」这件事,音乐这边十几个页面都要做一遍。
///
/// 摊开写十几遍必然有几处漏掉其中一样 —— 最常漏的两样是:
/// 空着的时候下拉刷不动(RefreshIndicator 下面没有能滚的东西),
/// 以及拉成功了没把上一次的错误清掉,于是页面一直挂在出错页上。
///
/// [builder] 返回的必须是**能滚的东西**(ListView / CustomScrollView),
/// 下拉刷新靠它的越界通知工作。
class MLoader<T> extends StatefulWidget {
  const MLoader({super.key, required this.load, required this.builder});

  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, Future<void> Function() reload) builder;

  @override
  State<MLoader<T>> createState() => MLoaderState<T>();
}

class MLoaderState<T> extends State<MLoader<T>> {
  T? _data;
  Object? _error;

  @override
  void initState() {
    super.initState();
    unawaited(reload());
  }

  /// 重新拉一次。外面拿 GlobalKey 也能调(改完信息要刷新本页)。
  Future<void> reload() async {
    try {
      final d = await widget.load();
      if (!mounted) return;
      setState(() {
        _data = d;
        // 拉成功了就把上一次的错误清掉,不然点了重试、数据也回来了,页面还挂在出错页上
        _error = null;
      });
    } catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  /// 不重新请求,只是让界面跟着改过的数据重画(点了喜欢、改了歌单名)
  void refreshUi() {
    if (mounted) setState(() {});
  }

  T? get data => _data;

  @override
  Widget build(BuildContext context) {
    final d = _data;
    if (d == null) {
      // 出错页自己也要能下拉 —— 「重试」按钮和下拉是两条路,
      // 断一次网只剩一条路的话,手指先到的那一条往往是下拉
      if (_error != null) {
        return SzRefreshableEmpty(onRefresh: reload, child: musicErrorView(_error, reload));
      }
      return const Center(child: CircularProgressIndicator());
    }
    return RefreshIndicator(onRefresh: reload, child: widget.builder(context, d, reload));
  }
}

/// 封面。歌、专辑、歌单共用一套占位(没图时按名字取首字和底色)。
class MCover extends StatelessWidget {
  const MCover({super.key, required this.url, required this.name, this.size = 48, this.radius});

  final String url;
  final String name;
  final double size;
  final double? radius;

  @override
  Widget build(BuildContext context) =>
      SzImage(url: url.isEmpty ? '' : musicResolve(url), name: name, size: size, radius: radius);
}

/// 「不适宜未成年人」的小标(§8.1 track.explicit)。
class MExplicitTag extends StatelessWidget {
  const MExplicitTag({super.key});

  @override
  Widget build(BuildContext context) => VTag('不宜', color: Theme.of(context).sz.danger);
}

/// 算分的中间量那一行:一句「为什么」+「怎么算的」进公式页(§5.4 公式公开)。
class MRankLine extends StatelessWidget {
  const MRankLine(this.rank, {super.key, this.showFormulaLink = true});

  final MRank? rank;
  final bool showFormulaLink;

  @override
  Widget build(BuildContext context) {
    final r = rank;
    if (r == null || r.why.isEmpty) return const SizedBox.shrink();
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Row(children: [
        Flexible(
          child: Text(r.why,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
        ),
        if (showFormulaLink)
          GestureDetector(
            onTap: () => openMusicFormula(context),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 6),
              child: Text('怎么算的', style: TextStyle(fontSize: kFontMicro, color: sz.link)),
            ),
          ),
      ]),
    );
  }
}

/// 列表里的一首歌。
///
/// [leading] 给了就替掉封面(榜单用名次数字);[onTap] 不给就按这一行所在的
/// 整份列表开播 —— 点歌单里第 5 首,后面 6、7、8 跟着放,这是听歌的常识。
class MTrackTile extends StatelessWidget {
  const MTrackTile({
    super.key,
    required this.track,
    this.queue,
    this.contextKey = '',
    this.leading,
    this.subtitle,
    this.trailing,
    this.onTap,
    this.showRank = false,
    this.dense = false,
  });

  final MTrack track;

  /// 这一行所在的整份列表(点它就从这里开播)
  final List<MTrack>? queue;
  final String contextKey;
  final Widget? leading;
  final String? subtitle;
  final Widget? trailing;
  final VoidCallback? onTap;
  final bool showRank;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final player = MusicPlayer.instance;
    return AnimatedBuilder(
      animation: player,
      builder: (context, _) {
        final isCurrent = player.current?.tid == track.tid;
        final sub = subtitle ??
            [
              if (track.artistName.isNotEmpty) track.artistName,
              if ((track.release?.title ?? '').isNotEmpty) track.release!.title,
            ].join(' · ');
        return InkWell(
          onTap: onTap ?? () => _play(context),
          child: Padding(
            padding: EdgeInsets.symmetric(horizontal: kPagePad, vertical: dense ? 6 : 9),
            child: Row(children: [
              leading ?? MCover(url: track.cover, name: track.title, size: dense ? 40 : 48),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Flexible(
                      child: Text(track.title,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: kFontBodyLg,
                            color: isCurrent ? sz.clay : sz.ink,
                            fontWeight: isCurrent ? FontWeight.w600 : FontWeight.w400,
                          )),
                    ),
                    if (track.explicit) ...[const SizedBox(width: 6), const MExplicitTag()],
                  ]),
                  if (sub.isNotEmpty)
                    Text(sub,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
                  if (showRank) MRankLine(track.rank),
                ]),
              ),
              trailing ??
                  IconButton(
                    icon: const Icon(Icons.more_horiz),
                    tooltip: '更多',
                    onPressed: () => showTrackMenu(context, track),
                  ),
            ]),
          ),
        );
      },
    );
  }

  void _play(BuildContext context) {
    final list = queue ?? [track];
    final at = list.indexWhere((t) => t.tid == track.tid);
    MusicPlayer.instance.playContext(list, start: at < 0 ? 0 : at, contextKey: contextKey);
  }
}

/// 一首歌的「更多」:下一首播放、加到歌单、看专辑 / 音乐人、分享、举报。
Future<void> showTrackMenu(BuildContext context, MTrack track) async {
  final pick = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(
          leading: MCover(url: track.cover, name: track.title, size: 40),
          title: Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis),
          subtitle: track.artistName.isEmpty
              ? null
              : Text(track.artistName, maxLines: 1, overflow: TextOverflow.ellipsis),
        ),
        const Divider(height: 1),
        ListTile(
            leading: const Icon(Icons.playlist_play),
            title: const Text('下一首播放'),
            onTap: () => Navigator.pop(ctx, 'next')),
        ListTile(
            leading: const Icon(Icons.playlist_add),
            title: const Text('加到歌单'),
            onTap: () => Navigator.pop(ctx, 'playlist')),
        if ((track.release?.rid ?? '').isNotEmpty)
          ListTile(
              leading: const Icon(Icons.album_outlined),
              title: Text('查看${mReleaseKindName(track.release!.kind)}'),
              onTap: () => Navigator.pop(ctx, 'release')),
        if ((track.artist?.aid ?? '').isNotEmpty)
          ListTile(
              leading: const Icon(Icons.person_outline),
              title: const Text('查看音乐人'),
              onTap: () => Navigator.pop(ctx, 'artist')),
        ListTile(
            leading: const Icon(Icons.ios_share), title: const Text('分享'), onTap: () => Navigator.pop(ctx, 'share')),
        ListTile(
            leading: const Icon(Icons.flag_outlined), title: const Text('举报'), onTap: () => Navigator.pop(ctx, 'report')),
      ]),
    ),
  );
  if (pick == null || !context.mounted) return;
  switch (pick) {
    case 'next':
      MusicPlayer.instance.insertNext(track);
      mToast(context, '已插到下一首');
    case 'playlist':
      await addToPlaylistSheet(context, [track.tid]);
    case 'release':
      await openRelease(context, track.release!.rid);
    case 'artist':
      await openArtist(context, track.artist!.aid);
    case 'share':
      await shareMusic(context, 'track', track.tid, track.title);
    case 'report':
      await reportSheet(context, targetType: 'track', targetId: track.tid);
  }
}

/// 歌单卡(发现页、我的音乐的横向卡片)。
class MPlaylistCard extends StatelessWidget {
  const MPlaylistCard({super.key, required this.playlist, this.width = 128, this.showRank = false});

  final MPlaylist playlist;
  final double width;
  final bool showRank;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: () => openPlaylist(context, playlist.pid),
      child: SizedBox(
        width: width,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          MCover(url: playlist.cover, name: playlist.title, size: width, radius: kRadiusMd),
          const SizedBox(height: 6),
          Text(playlist.title,
              maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: kFontBody, height: 1.3)),
          Text('${playlist.trackCount} 首 · ${vCount(playlist.collects)} 收藏',
              maxLines: 1, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
          if (showRank) MRankLine(playlist.rank),
        ]),
      ),
    );
  }
}

/// 作品卡(音乐人主页、我的收藏)。
class MReleaseCard extends StatelessWidget {
  const MReleaseCard({super.key, required this.release, this.width = 118});

  final MRelease release;
  final double width;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return InkWell(
      onTap: () => openRelease(context, release.rid),
      child: SizedBox(
        width: width,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          MCover(url: release.cover, name: release.title, size: width, radius: kRadiusMd),
          const SizedBox(height: 6),
          Text(release.title,
              maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: kFontBody, height: 1.3)),
          Text(
              [
                mReleaseKindName(release.kind),
                if (release.releaseDate.isNotEmpty) release.releaseDate,
              ].join(' · '),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: kFontMicro, color: sz.inkMuted)),
        ]),
      ),
    );
  }
}

/// 音乐人一行(搜索结果、主页顶上)。
class MArtistTile extends StatelessWidget {
  const MArtistTile({super.key, required this.aid, required this.name, this.avatar = '', this.subtitle,
      this.trailing, this.onTap});

  final String aid;
  final String name;
  final String avatar;
  final String? subtitle;
  final Widget? trailing;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ListTile(
      leading: SzImage(url: avatar.isEmpty ? '' : musicResolve(avatar), name: name, size: 44, circle: true),
      title: Text(name, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: subtitle == null
          ? null
          : Text(subtitle!, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      trailing: trailing,
      onTap: onTap ?? () => openArtist(context, aid),
    );
  }
}

/// 一小节的标题 +「更多」。
class MSection extends StatelessWidget {
  const MSection(this.title, {super.key, this.note, this.onMore, this.moreLabel = '更多'});

  final String title;
  final String? note;
  final VoidCallback? onMore;
  final String moreLabel;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 18, kPagePad, 8),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: TextStyle(fontSize: kFontTitle, color: sz.ink, fontWeight: FontWeight.w600)),
            if (note != null && note!.isNotEmpty)
              Text(note!, style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
          ]),
        ),
        if (onMore != null)
          TextButton(onPressed: onMore, child: Text(moreLabel, style: const TextStyle(fontSize: kFontNote))),
      ]),
    );
  }
}

/// 举报弹层。版权投诉(M301)要留联系方式 —— 没有联系方式没法核实授权。
Future<void> reportSheet(BuildContext context, {required String targetType, required String targetId}) async {
  // 共用视频的 C101–C109、X999,音乐另加 M301–M305(§5.11)
  const reasons = {
    'M301': '非原创且没有授权(侵权)',
    'M302': '音频不完整(无声、截断、严重失真)',
    'M303': '歌名 / 封面 / 署名与内容不符',
    'M304': '歌词违规',
    'M305': '冒充其他音乐人',
    'C101': '违法违规',
    'C104': '色情低俗',
    'C107': '人身攻击',
    'X999': '其他',
  };
  final code = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const ListTile(title: Text('举报理由')),
        const Divider(height: 1),
        for (final e in reasons.entries)
          ListTile(dense: true, title: Text(e.value), onTap: () => Navigator.pop(ctx, e.key)),
      ]),
    ),
  );
  if (code == null || !context.mounted) return;
  final copyright = code == 'M301';
  final note = await vPrompt(context,
      title: copyright ? '版权投诉' : '补充说明',
      hint: copyright ? '说明作品出处,并留下联系方式(邮箱或手机号),便于核实' : '可以不填',
      maxLength: 200,
      maxLines: 3,
      validate: (t) => copyright && t.trim().length < 6 ? '版权投诉要留下出处和联系方式' : null);
  if (note == null || !context.mounted) return;
  try {
    await musicApi.report(
      targetType: targetType,
      targetId: targetId,
      reasonCode: code,
      note: note.trim(),
      // 版权投诉把联系方式和说明写在一处:服务端那边 contact 必填
      contact: copyright ? note.trim() : '',
    );
    if (context.mounted) mToast(context, '已收到,我们会尽快处理');
  } catch (e) {
    if (context.mounted) mToast(context, e);
  }
}
