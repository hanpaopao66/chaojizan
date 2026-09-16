// 我的音乐(§8.2 /me/*):我喜欢、最近播放、自己建的歌单、收藏的歌单、收藏的专辑,
// 外加「个性化推荐」开关(§5.4 推荐可关个性化)。
//
// 这一整页都要登录 —— 没登录时整页是一个登录引导,登录完了原地刷新,
// 不把人丢在登录页自己找回来。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../../video/me/common.dart';
import '../models.dart';
import '../nav.dart';
import '../player/music_player.dart';
import '../widgets/common.dart';

/// 独立的一页(从别处 push 进来)。
class MyMusicPage extends StatelessWidget {
  const MyMusicPage({super.key});

  @override
  Widget build(BuildContext context) => SzPageScaffold(
        contentMaxWidth: kFeedMaxWidth,
        appBar: AppBar(title: const Text('我的音乐')),
        body: const MyMusicView(),
      );
}

/// 音乐首页「我的」那一页签。
class MyMusicView extends StatefulWidget {
  const MyMusicView({super.key});

  @override
  State<MyMusicView> createState() => _MyMusicViewState();
}

class _MyMusicViewState extends State<MyMusicView> {
  final _key = GlobalKey<MLoaderState<_Mine>>();

  @override
  Widget build(BuildContext context) {
    if (!rootApi.isLoggedIn) {
      return SzRefreshableEmpty(
        onRefresh: () async => setState(() {}),
        child: VideoLoginGate(text: '登录后能看到我喜欢的音乐、最近播放和歌单', onLoggedIn: () => setState(() {})),
      );
    }
    return MLoader<_Mine>(
      key: _key,
      load: _load,
      builder: (context, mine, reload) => ListView(
        padding: const EdgeInsets.only(bottom: 24),
        children: [
          _Entry(
            icon: Icons.favorite,
            title: '我喜欢的音乐',
            count: mine.likes.length,
            tracks: mine.likes,
            contextKey: 'likes',
          ),
          _Entry(
            icon: Icons.history,
            title: '最近播放',
            count: mine.history.length,
            tracks: mine.history,
            contextKey: 'history',
            onClear: mine.history.isEmpty
                ? null
                : () async {
                    if (!await vConfirm(context, title: '清空最近播放?', ok: '清空', danger: true)) return;
                    try {
                      await musicApi.clearHistory();
                      await reload();
                    } catch (e) {
                      if (context.mounted) mToast(context, e);
                    }
                  },
          ),
          MSection('创建的歌单', onMore: () => _create(reload), moreLabel: '新建'),
          if (mine.playlists.created.isEmpty)
            const _Hint('还没有自己建的歌单')
          else
            for (final p in mine.playlists.created) _PlaylistRow(playlist: p, mine: true),
          if (mine.playlists.collected.isNotEmpty) ...[
            const MSection('收藏的歌单'),
            for (final p in mine.playlists.collected) _PlaylistRow(playlist: p),
          ],
          if (mine.playlists.collectedReleases.isNotEmpty) ...[
            const MSection('收藏的专辑'),
            for (final r in mine.playlists.collectedReleases)
              ListTile(
                leading: MCover(url: r.cover, name: r.title, size: 48),
                title: Text(r.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(
                    [mReleaseKindName(r.kind), if (r.artist != null) r.artist!.name].join(' · '),
                    style: TextStyle(fontSize: kFontNote, color: Theme.of(context).sz.inkMuted)),
                onTap: () => openRelease(context, r.rid),
              ),
          ],
          const MSection('设置'),
          SwitchListTile(
            title: const Text('个性化推荐'),
            subtitle: Text(
              // 关掉之后每日推荐只按热歌榜分数排(§5.4),说清楚关了会怎样,而不是只给个开关
              '关掉之后每日推荐只按热歌榜分数排,不再看你听过什么',
              style: TextStyle(fontSize: kFontNote, color: Theme.of(context).sz.inkMuted),
            ),
            value: mine.personalize,
            onChanged: (v) async {
              try {
                final on = await musicApi.setPersonalize(v);
                if (context.mounted) setState(() => mine.personalize = on);
              } catch (e) {
                if (context.mounted) mToast(context, e);
              }
            },
          ),
          ListTile(
            leading: const Icon(Icons.functions),
            title: const Text('榜单和推荐是怎么算的'),
            subtitle: Text('公式和全部参数都在这里',
                style: TextStyle(fontSize: kFontNote, color: Theme.of(context).sz.inkMuted)),
            onTap: () => openMusicFormula(context),
          ),
        ],
      ),
    );
  }

  Future<_Mine> _load() async {
    // 四个接口一起发:串起来要等四个来回,最慢的那一段是等出来的
    final r = await Future.wait<Object>([
      musicApi.myLikes(),
      musicApi.history(),
      musicApi.myPlaylists(),
      musicApi.personalize(),
    ]);
    return _Mine(
      likes: (r[0] as MPage<MTrack>).items,
      history: r[1] as List<MTrack>,
      playlists: r[2] as MMyPlaylists,
      personalize: r[3] as bool,
    );
  }

  Future<void> _create(Future<void> Function() reload) async {
    final title = await vPrompt(context,
        title: '新建歌单', hint: '歌单名', maxLength: 30, validate: (t) => t.trim().isEmpty ? '起个名字吧' : null);
    if (title == null || !mounted) return;
    try {
      final p = await musicApi.createPlaylist(title.trim());
      await reload();
      if (mounted) await openPlaylist(context, p.pid);
    } catch (e) {
      if (mounted) mToast(context, e);
    }
  }
}

class _Mine {
  _Mine({required this.likes, required this.history, required this.playlists, required this.personalize});

  final List<MTrack> likes;
  final List<MTrack> history;
  final MMyPlaylists playlists;
  bool personalize;
}

/// 「我喜欢」「最近播放」两个入口:一行,点开是这一整份列表。
class _Entry extends StatelessWidget {
  const _Entry({
    required this.icon,
    required this.title,
    required this.count,
    required this.tracks,
    required this.contextKey,
    this.onClear,
  });

  final IconData icon;
  final String title;
  final int count;
  final List<MTrack> tracks;
  final String contextKey;
  final VoidCallback? onClear;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ListTile(
      leading: CircleAvatar(backgroundColor: sz.claySoft, child: Icon(icon, color: sz.clay)),
      title: Text(title),
      subtitle: Text('$count 首', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      trailing: Row(mainAxisSize: MainAxisSize.min, children: [
        if (onClear != null)
          IconButton(icon: const Icon(Icons.delete_outline), tooltip: '清空', onPressed: onClear),
        IconButton(
          icon: const Icon(Icons.play_circle_outline),
          tooltip: '播放全部',
          onPressed: tracks.isEmpty ? null : () => MusicPlayer.instance.playContext(tracks, contextKey: contextKey),
        ),
      ]),
      onTap: () => openTrackList(context, title: title, tracks: tracks, contextKey: contextKey),
    );
  }
}

class _PlaylistRow extends StatelessWidget {
  const _PlaylistRow({required this.playlist, this.mine = false});

  final MPlaylist playlist;
  final bool mine;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return ListTile(
      leading: MCover(url: playlist.cover, name: playlist.title, size: 48),
      title: Row(children: [
        Flexible(child: Text(playlist.title, maxLines: 1, overflow: TextOverflow.ellipsis)),
        if (mine && !playlist.isPublic) ...[const SizedBox(width: 6), const VTag('私密')],
      ]),
      subtitle: Text(
          mine
              ? '${playlist.trackCount} 首'
              : '${playlist.trackCount} 首 · ${playlist.owner?.name ?? ''}',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      onTap: () => openPlaylist(context, playlist.pid),
    );
  }
}

class _Hint extends StatelessWidget {
  const _Hint(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 8),
        child: Text(text, style: TextStyle(fontSize: kFontNote, color: Theme.of(context).sz.inkFaint)),
      );
}

/// 一份现成的歌单列表(我喜欢、最近播放、曲风页的「全部」)。不再请求,直接画。
class MusicTrackListPage extends StatelessWidget {
  const MusicTrackListPage({super.key, required this.title, required this.tracks, this.contextKey = ''});

  final String title;
  final List<MTrack> tracks;
  final String contextKey;

  @override
  Widget build(BuildContext context) {
    return SzPageScaffold(
      contentMaxWidth: kFeedMaxWidth,
      appBar: AppBar(
        title: Text(title),
        actions: [
          IconButton(
            icon: const Icon(Icons.play_circle_outline),
            tooltip: '播放全部',
            onPressed: tracks.isEmpty ? null : () => MusicPlayer.instance.playContext(tracks, contextKey: contextKey),
          ),
        ],
      ),
      body: tracks.isEmpty
          ? SzEmpty(text: '$title里还没有歌')
          : ListView.builder(
              itemCount: tracks.length,
              itemBuilder: (context, i) => MTrackTile(track: tracks[i], queue: tracks, contextKey: contextKey),
            ),
    );
  }
}
