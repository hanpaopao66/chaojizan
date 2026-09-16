import 'package:flutter/foundation.dart';

import '../session.dart';
import 'api.dart';

/// 音乐模块的入口:接口单例、地址补全、站内链接解析。
///
/// 绑的是全局的 rootApi(登录后同一个对象带上 token)—— 听歌不要求登录(§4 M5),
/// 喜欢、评论、歌单这些写操作由各页自己 `ensureLoggedIn`。
MusicApi get musicApi => _api ??= MusicApi(rootApi);
MusicApi? _api;

/// 测试里换成 MockClient 支的假接口。
@visibleForTesting
set musicApi(MusicApi value) => _api = value;

/// `/img/…`、`/music/v1/stream/…` 这类相对地址补成完整的
String musicResolve(String path) => rootApi.resolveUrl(path);

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
