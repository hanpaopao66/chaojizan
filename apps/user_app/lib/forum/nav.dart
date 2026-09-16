import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:share_plus/share_plus.dart';
import 'package:superz_shared/superz_shared.dart';

import '../session.dart';
import 'api.dart';
import 'models.dart';
import 'pages/bookmarks_page.dart';
import 'pages/compose_page.dart';
import 'pages/edits_page.dart';
import 'pages/explore_page.dart';
import 'pages/follow_list_page.dart';
import 'pages/home_page.dart';
import 'pages/mute_words_page.dart';
import 'pages/people_page.dart';
import 'pages/post_page.dart';
import 'pages/profile_page.dart';
import 'pages/search_page.dart';
import 'pages/settings_page.dart';
import 'pages/tag_page.dart';

/// 论坛模块的入口:接口单例、地址补全、几个 open*、站内链接、分享。
///
/// 接口绑全局的 rootApi(登录后同一个对象带上 token)—— 浏览类不登录也能看。
ForumApi get forumApi => _api ??= ForumApi(rootApi);
ForumApi? _api;

/// 测试里换掉接口单例(MockClient 造的 ApiClient)。传 null 还原。
@visibleForTesting
set forumApiOverride(ForumApi? api) => _api = api;

/// `/img/forum/…` 这类相对地址补成完整的
String forumResolve(String path) => path.isEmpty ? '' : rootApi.resolveUrl(path);

/// 帖子链接(§5.1)
String forumPostLink(String pid) => 'https://chaojizan.cc/forum/p/$pid';

/// 话题链接(§5.1,话题要 URL 编码)
String forumTagLink(String tag) => 'https://chaojizan.cc/forum/t/${Uri.encodeComponent(tag)}';

Future<void> openForumHome(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(
      settings: const RouteSettings(name: '/forum'),
      builder: (_) => const ForumHomePage(),
    ));

/// 打开帖子详情(上文串 + 本帖 + 回复)。
Future<void> openPost(BuildContext context, String pid) =>
    Navigator.of(context).push(MaterialPageRoute<void>(
      settings: RouteSettings(name: '/forum/p/$pid'),
      builder: (_) => PostPage(pid: pid),
    ));

/// 打开某人的论坛主页。
Future<void> openForumProfile(BuildContext context, int userId) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => ForumProfilePage(userId: userId)));

/// 打开话题页。[tag] 传规范化的小写 tag;[display] 只影响标题怎么写。
Future<void> openTag(BuildContext context, String tag, {String? display}) =>
    Navigator.of(context).push(MaterialPageRoute<void>(
      settings: RouteSettings(name: '/forum/t/$tag'),
      builder: (_) => TagPage(tag: tag, display: display ?? tag),
    ));

Future<void> openExplore(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ExplorePage()));

Future<void> openBookmarks(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const BookmarksPage()));

/// 发帖 / 回复 / 引用 / 改自己发过的。发出去了返回那条帖子,取消返回 null。
///
/// [card] 是 `{type, id}`(§5.9 的卡片引用):从歌曲页、视频页「分享到论坛」过来时预带,
/// 标题封面由服务端现查,客户端只报这两个字段(I3 —— 不信客户端报的快照)。
/// [origin] 是回复 / 引用时那条原帖,给发帖页显示用,不影响发什么。
/// [edit] 给了就是改正文(F3:30 分钟内、最多 5 次;图和投票不能改)。
Future<FPost?> openCompose(
  BuildContext context, {
  Map<String, dynamic>? card,
  String? quotePid,
  String? replyToPid,
  FPost? origin,
  FPost? edit,
}) async {
  if (!await ensureLoggedIn(context)) return null;
  if (!context.mounted) return null;
  return Navigator.of(context).push<FPost>(MaterialPageRoute<FPost>(
    fullscreenDialog: true,
    builder: (_) =>
        ComposePage(card: card, quotePid: quotePid, replyToPid: replyToPid, origin: origin, edit: edit),
  ));
}

/// 引用这条帖子的人。
Future<void> openQuotes(BuildContext context, String pid) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => QuotesPage(pid: pid)));

/// 点赞这条帖子的人。
Future<void> openLikers(BuildContext context, String pid) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => LikersPage(pid: pid)));

/// 编辑历史(F3:每次把旧正文留下来)。
Future<void> openEdits(BuildContext context, String pid) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => EditsPage(pid: pid)));

/// 关注 / 粉丝列表。[tab] 是 `following` 或 `followers`。
Future<void> openFollowList(BuildContext context, int userId, {String tab = 'followers'}) =>
    Navigator.of(context).push(MaterialPageRoute<void>(
        builder: (_) => FollowListPage(userId: userId, tab: tab)));

Future<void> openForumSearch(BuildContext context, {String q = ''}) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => ForumSearchPage(initial: q)));

Future<void> openMuteWords(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const MuteWordsPage()));

Future<void> openForumSettings(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ForumSettingsPage()));

/// 推荐公式(§5.7,参数原样摊开)。
Future<void> openForumFormula(BuildContext context) =>
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => const ForumFormulaPage()));

/// 站内链接里论坛认的两种(§5.1):`/forum/p/<pid>`、`/forum/t/<话题>`。
///
/// 认得就自己打开并返回 true,不认得返回 false 交回给调用方。
/// #382 合并时把它注册进 `registerAppLinkHandler`,论坛不反向依赖 chat。
bool handleForumLink(BuildContext context, Uri uri) {
  final seg = uri.pathSegments.where((s) => s.isNotEmpty).toList();
  if (seg.length < 3 || seg[0] != 'forum') return false;
  if (seg[1] == 'p' && RegExp(r'^fp[1-9A-HJ-NP-Za-km-z]{10}$').hasMatch(seg[2])) {
    unawaitedOpen(openPost(context, seg[2]));
    return true;
  }
  if (seg[1] == 't') {
    // pathSegments 已经解过一次码,话题原样用
    final tag = seg[2];
    if (tag.isEmpty || tag.length > 30) return false;
    unawaitedOpen(openTag(context, tag.toLowerCase(), display: tag));
    return true;
  }
  return false;
}

/// 链接处理是同步判定「认不认」、异步打开页面 —— 这里把那个 Future 明确丢掉。
void unawaitedOpen(Future<void> f) {
  f.ignore();
}

/// 分享一条帖子。
///
/// 现在是「复制链接 / 系统分享」两条;#382 合并后把「发到消息」接上聊天的
/// `shareCardToChat`(消息类型 `card`,§5.9)—— 那半边在主会话的 724904f 里,
/// 这个 worktree 还没有,所以先只发链接,不假装有卡片。
Future<void> shareForumPost(BuildContext context, FPost post) async {
  if (post.unavailable) return;
  final link = forumPostLink(post.pid);
  final title = _shareTitle(post);
  final pick = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        ListTile(title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis)),
        const Divider(height: 1),
        ListTile(leading: const Icon(Icons.link), title: const Text('复制链接'), onTap: () => Navigator.pop(ctx, 'link')),
        ListTile(leading: const Icon(Icons.ios_share), title: const Text('更多'), onTap: () => Navigator.pop(ctx, 'other')),
      ]),
    ),
  );
  if (pick == null || !context.mounted) return;
  switch (pick) {
    case 'link':
      await Clipboard.setData(ClipboardData(text: link));
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('链接已复制')));
      }
    case 'other':
      await SharePlus.instance.share(ShareParams(text: '$title $link'));
  }
}

/// 分享时用的一句话:正文前 30 字;没正文(纯图 / 卡片 / 投票)就写作者。
String _shareTitle(FPost post) {
  final t = post.text.trim().replaceAll('\n', ' ');
  if (t.isNotEmpty) {
    final runes = t.runes.toList();
    return runes.length <= 30 ? t : '${String.fromCharCodes(runes.take(30))}…';
  }
  final name = post.author?.name ?? '';
  return name.isEmpty ? '一条帖子' : '$name 的帖子';
}
