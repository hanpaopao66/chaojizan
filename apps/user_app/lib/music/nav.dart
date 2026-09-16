import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';

import '../session.dart';
import 'api.dart';
import 'models.dart';
import 'pages/artist_page.dart';
import 'pages/charts_page.dart';
import 'pages/comments_page.dart';
import 'pages/daily_page.dart';
import 'pages/genre_page.dart';
import 'pages/home_page.dart';
import 'pages/my_music_page.dart';
import 'pages/playlist_page.dart';
import 'pages/release_page.dart';
import 'pages/search_page.dart';
import 'player/music_player.dart';
import 'player/player_page.dart';
import 'studio/studio_page.dart';
import 'widgets/common.dart';

/// 音乐模块的入口:接口单例、地址补全、各页面怎么打开、站内链接解析、分享。
///
/// 接口绑的是全局的 rootApi(登录后同一个对象带上 token)—— 听歌不要求登录(§4 M5),
/// 喜欢、评论、歌单这些写操作由各页自己 `ensureLoggedIn`。
MusicApi get musicApi => _api ??= MusicApi(rootApi);
MusicApi? _api;

/// 测试里换成 MockClient 支的假接口。
@visibleForTesting
set musicApi(MusicApi value) => _api = value;

/// `/img/…`、`/music/v1/stream/…` 这类相对地址补成完整的
String musicResolve(String path) => rootApi.resolveUrl(path);

// ---------------- 打开各页 ----------------

Future<void> openMusicHome(BuildContext context) => Navigator.of(context).push(MaterialPageRoute<void>(
      settings: const RouteSettings(name: '/music'),
      builder: (_) => const MusicHomePage(),
    ));

/// 打开一首歌:拉详情、开播、进播放页。
///
/// 站内链接 `/music/t/<tid>` 点进来走的就是这里 —— 分享出去的一条链接,
/// 别人点开应该**直接听到**,而不是落在一个还要再点一下的页面上。
Future<void> openTrack(BuildContext context, String tid) async {
  try {
    final t = await musicApi.track(tid);
    if (!context.mounted) return;
    await MusicPlayer.instance.playTrack(t, contextKey: 'link');
    if (context.mounted) await openMusicPlayer(context);
  } catch (e) {
    if (context.mounted) mToast(context, e);
  }
}

/// 播一首歌。[queue] 给了就把整份列表放进队列,从这一首开始。
Future<void> playTrack(BuildContext context, MTrack track,
    {List<MTrack>? queue, String contextKey = ''}) async {
  final list = queue ?? [track];
  final at = list.indexWhere((t) => t.tid == track.tid);
  await MusicPlayer.instance.playContext(list, start: at < 0 ? 0 : at, contextKey: contextKey);
}

Future<void> openMusicPlayer(BuildContext context) => Navigator.of(context).push(MaterialPageRoute<void>(
      settings: const RouteSettings(name: '/music/player'),
      builder: (_) => const MusicPlayerPage(),
    ));

Future<void> openPlaylist(BuildContext context, String pid) => Navigator.of(context).push(MaterialPageRoute<void>(
      settings: RouteSettings(name: '/music/p/$pid'),
      builder: (_) => MusicPlaylistPage(pid: pid),
    ));

Future<void> openRelease(BuildContext context, String rid) => Navigator.of(context).push(MaterialPageRoute<void>(
      settings: RouteSettings(name: '/music/r/$rid'),
      builder: (_) => MusicReleasePage(rid: rid),
    ));

Future<void> openArtist(BuildContext context, String aid) => Navigator.of(context).push(MaterialPageRoute<void>(
      settings: RouteSettings(name: '/music/a/$aid'),
      builder: (_) => MusicArtistPage(aid: aid),
    ));

Future<void> openMusicStudio(BuildContext context) => Navigator.of(context).push(MaterialPageRoute<void>(
      settings: const RouteSettings(name: '/music/studio'),
      builder: (_) => const MusicStudioPage(),
    ));

Future<void> openMusicComments(BuildContext context, MTrack track) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => MusicCommentsPage(track: track)));

Future<void> openMusicCharts(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const MusicChartsPage()));

Future<void> openMusicChart(BuildContext context, String key, String name) => Navigator.of(context)
    .push(MaterialPageRoute<void>(builder: (_) => MusicChartPage(chartKey: key, name: name)));

Future<void> openMusicDaily(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const MusicDailyPage()));

Future<void> openMusicGenre(BuildContext context, String key, String name) => Navigator.of(context)
    .push(MaterialPageRoute<void>(builder: (_) => MusicGenrePage(genreKey: key, name: name)));

Future<void> openMusicSearch(BuildContext context, {String? initial}) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => MusicSearchPage(initial: initial)));

Future<void> openMyMusic(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const MyMusicPage()));

Future<void> openMusicFormula(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const MusicFormulaPage()));

/// 一份现成的歌曲列表(我喜欢、最近播放)。
Future<void> openTrackList(BuildContext context,
        {required String title, required List<MTrack> tracks, String contextKey = ''}) =>
    Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => MusicTrackListPage(title: title, tracks: tracks, contextKey: contextKey)));

// ---------------- 站内链接 ----------------

/// 本站域名。站内链接只认这两个 —— 和 chat/links.dart 同一个口径,
/// `chaojizan.cc.evil.example/music/t/…` 这种长得一样的不算。
const _ownHosts = {'chaojizan.cc', 'www.chaojizan.cc'};

/// 公开编号:前缀 + 10 位 base58(§5.1,字母表同视频,防止按数字遍历)。
final _idPattern = RegExp(r'^(mt|mr|mp|ma)[1-9A-HJ-NP-Za-km-z]{10}$');

/// 音乐的站内链接(§5.1):`/music/t|r|p|a/<编号>` →(类型, 编号)。
/// 不是音乐链接、编号形状不对都返回 null。
///
/// 类型用**路径那一段**,不是编号前缀:两者对不上(`/music/t/mp…`)一律不认,
/// 免得一条拼错的链接把人送去一个不相干的页面。
({String type, String id})? musicLinkOf(Uri uri) {
  if (!_ownHosts.contains(uri.host.toLowerCase())) return null;
  final seg = uri.pathSegments.where((s) => s.isNotEmpty).toList();
  if (seg.length != 3 || seg[0] != 'music') return null;
  const kinds = {'t': 'track', 'r': 'release', 'p': 'playlist', 'a': 'artist'};
  const prefixes = {'t': 'mt', 'r': 'mr', 'p': 'mp', 'a': 'ma'};
  final kind = kinds[seg[1]];
  if (kind == null) return null;
  final id = seg[2];
  if (!_idPattern.hasMatch(id) || !id.startsWith(prefixes[seg[1]]!)) return null;
  return (type: kind, id: id);
}

/// 分享用的站内链接。
String musicLinkFor(String type, String id) {
  const path = {'track': 't', 'release': 'r', 'playlist': 'p', 'artist': 'a'};
  return 'https://chaojizan.cc/music/${path[type] ?? 't'}/$id';
}

/// 在 App 里打开一条音乐链接。认得就打开并返回 true,不认得返回 false ——
/// 交给调用方(主会话会把它接进 `openAppLink`,和视频的 `/v/…` 并排)。
bool handleMusicLink(BuildContext context, Uri uri) {
  final ref = musicLinkOf(uri);
  if (ref == null) return false;
  switch (ref.type) {
    case 'track':
      openTrack(context, ref.id);
    case 'release':
      openRelease(context, ref.id);
    case 'playlist':
      openPlaylist(context, ref.id);
    case 'artist':
      openArtist(context, ref.id);
  }
  return true;
}

// ---------------- 分享 ----------------

/// 分享一首歌 / 一个作品 / 一个歌单 / 一位音乐人。
///
/// 现在是「复制链接」和系统分享两条路。**主会话之后会加上「发到聊天」** ——
/// 那一条要走 §5.9 的 `card` 消息(客户端只传 `{type, id}`,标题封面由服务端
/// 查出来存快照),这一批服务端还没有,所以先发链接。
Future<void> shareMusic(BuildContext context, String type, String id, String title) async {
  final link = musicLinkFor(type, id);
  final pick = await szShowSheetForShare(context, title);
  if (pick == null || !context.mounted) return;
  switch (pick) {
    case 'link':
      await Clipboard.setData(ClipboardData(text: link));
      if (context.mounted) mToast(context, '链接已复制');
    case 'other':
      await SharePlus.instance.share(ShareParams(text: '$title $link'));
  }
}
