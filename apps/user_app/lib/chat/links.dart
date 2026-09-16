import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../video/nav.dart';
import 'chat_page.dart';
import 'pages/pickers.dart';
import 'pages/user_profile_page.dart';
import 'store.dart';
import 'ui/avatar.dart';

/// 模块自己注册的站内链接处理函数(音乐、论坛在各自的 nav.dart 里注册)。
///
/// **方向是反的才对**:聊天不认识音乐和论坛的页面,它只负责把链接问一圈 ——
/// 谁认得谁处理。这样加一个新模块不用改这里,关掉一个模块也不会留下打不开的死链接。
typedef AppLinkHandler = Future<bool> Function(BuildContext context, Uri uri);

final List<AppLinkHandler> _moduleHandlers = [];

/// 注册一个站内链接处理函数(同一个函数重复注册只算一次,热重载时不会叠)。
void registerAppLinkHandler(AppLinkHandler handler) {
  if (!_moduleHandlers.contains(handler)) _moduleHandlers.add(handler);
}

@visibleForTesting
void clearAppLinkHandlers() => _moduleHandlers.clear();

/// 本站的域名。名片码、站内链接只认这两个
const _ownHosts = {'chaojizan.cc', 'www.chaojizan.cc'};

/// 这是不是本站的**名片链接**:`https://chaojizan.cc/@超级赞号`,或者 `https://chaojizan.cc/u/名片编号`
/// (没有超级赞号、或者关了「按超级赞号找到我」的人,名片码是后一种)。是就返回号或编号,不是返回 null。
///
/// **只认本站域名**:`chaojizan.cc.evil.example/@xxx`、`evil.example/@xxx` 这种长得一样的都不算 ——
/// 「扫一扫」扫到名片码会直接打开对方的资料页,别的链接得摆出来让人自己决定,不能扫一下就替人点了。
/// `/@频道名/123`(频道里的一条)、`/join/…`(邀请链接)不是名片,也返回 null。
({String? username, String? publicId})? cardRefOf(String raw) {
  final uri = Uri.tryParse(raw.trim());
  if (uri == null || (uri.scheme != 'https' && uri.scheme != 'http')) return null;
  if (!_ownHosts.contains(uri.host.toLowerCase())) return null;
  // `https://chaojizan.cc@evil.example/…` 的 host 是 evil.example,上面已经挡了;
  // 带用户名密码、带非默认端口的本站链接我们自己从来不发,也不认
  if (uri.userInfo.isNotEmpty || (uri.hasPort && uri.port != (uri.scheme == 'https' ? 443 : 80))) {
    return null;
  }
  final seg = uri.pathSegments.where((s) => s.isNotEmpty).toList();
  if (seg.length == 1 && seg[0].startsWith('@')) {
    final name = seg[0].substring(1);
    // 和服务端 validate_username 的格式一样:5–32 位,字母开头,字母数字下划线,不以下划线结尾
    return RegExp(r'^[A-Za-z](?:[A-Za-z0-9]|_(?!_)){3,30}[A-Za-z0-9]$').hasMatch(name)
        ? (username: name, publicId: null)
        : null;
  }
  if (seg.length == 2 && seg[0] == 'u' && RegExp(r'^[1-9A-HJ-NP-Za-km-z]{8,16}$').hasMatch(seg[1])) {
    return (username: null, publicId: seg[1]);
  }
  return null;
}

/// 站内链接(和 Telegram 的 t.me 一样):在 App 里直接打开,不跳浏览器。
///
/// - `chaojizan.cc/@超级赞号` → 这个人的资料 / 公开群、频道;
/// - `chaojizan.cc/@频道名/123` → 打开频道并跳到第 123 条;
/// - `chaojizan.cc/join/邀请码` → 邀请链接预览,可以加入;
/// - `chaojizan.cc/u/名片编号` → 这个人的资料(没有超级赞号、或者关了按号找到的人的名片链接);
/// - `chaojizan.cc/v/视频号` → 视频详情(`?p=2` 从第 2 P 开始)。
///
/// - `chaojizan.cc/music/…`、`chaojizan.cc/forum/…` → 由音乐、论坛模块**自己注册**的处理函数认
///   ([registerAppLinkHandler]);聊天不反向依赖那两个模块。
///
/// 返回 true 表示认得、已经处理;false 交给调用方(一般是问一句再用浏览器打开)。
Future<bool> openAppLink(BuildContext context, Uri uri) async {
  if (!_ownHosts.contains(uri.host.toLowerCase())) return false;
  final seg = uri.pathSegments.where((s) => s.isNotEmpty).toList();
  if (seg.isEmpty) return false;
  // 模块注册的先问一遍:音乐、论坛的链接不需要登录就能看,和视频一样放在「消息没启动」前面
  for (final h in _moduleHandlers) {
    if (await h(context, uri)) return true;
    if (!context.mounted) return true;
  }
  // 视频不需要登录也能看,放在「消息没启动」的判断前面
  if (seg[0] == 'v' && seg.length > 1 && RegExp(r'^sv[1-9A-HJ-NP-Za-km-z]{10}$').hasMatch(seg[1])) {
    final p = int.tryParse(uri.queryParameters['p'] ?? '');
    await openVideo(context, seg[1], partIdx: p != null && p > 0 ? p - 1 : null);
    return true;
  }
  final store = ChatStore.instance;
  if (!store.started) return false;
  try {
    if (seg[0].startsWith('@') && seg[0].length > 1) {
      final name = seg[0].substring(1);
      final post = seg.length > 1 ? int.tryParse(seg[1]) : null;
      if (post == null) {
        await openUsername(context, name);
        return true;
      }
      final r = await store.api.resolve(name);
      if (!context.mounted) return true;
      if (r['type'] == 'chat') {
        final id = ((r['chat'] as Map)['id'] as num).toInt();
        await openChat(context, id, jumpTo: post);
      } else {
        await openUsername(context, name);
      }
      return true;
    }
    if (seg[0] == 'join' && seg.length > 1) {
      await openInvite(context, seg[1]);
      return true;
    }
    if (seg[0] == 'u' && seg.length > 1) {
      final u = await store.api.resolvePublicId(seg[1]);
      if (context.mounted) await openUserProfile(context, u.id);
      return true;
    }
  } on ApiException catch (e) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    return true;
  }
  return false;
}

/// 邀请链接:先给看群名、人数、简介,确认了再加入(要审批的群发申请)。
Future<void> openInvite(BuildContext context, String code) async {
  final store = ChatStore.instance;
  final p = await store.api.invitePreview(code);
  if (!context.mounted) return;
  final chat = (p['chat'] as Map).cast<String, dynamic>();
  final id = (chat['id'] as num).toInt();
  if (p['is_member'] == true) {
    await openChat(context, id);
    return;
  }
  final channel = chat['type'] == 'channel';
  final approval = p['requires_approval'] == true;
  final go = await szShowSheet<bool>(
    context: context,
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(kPagePad),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ChatAvatar(name: '${chat['title'] ?? ''}', url: '${chat['photo'] ?? ''}', size: 72),
          const SizedBox(height: 10),
          Text('${chat['title'] ?? ''}', style: const TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600)),
          Text(channel ? '${chat['member_count']} 位订阅者' : '${chat['member_count']} 位成员'),
          if ('${chat['about'] ?? ''}'.isNotEmpty)
            Padding(padding: const EdgeInsets.only(top: 8), child: Text('${chat['about']}', textAlign: TextAlign.center)),
          if (approval)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text('管理员同意之后才能进', style: TextStyle(fontSize: kFontNote, color: Theme.of(ctx).sz.inkMuted)),
            ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(approval ? '申请加入' : (channel ? '订阅' : '加入')),
            ),
          ),
        ]),
      ),
    ),
  );
  if (go != true || !context.mounted) return;
  final r = await store.api.join(code);
  if (!context.mounted) return;
  if (r['status'] == 'requested') {
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('申请已发出,管理员同意后会通知你')));
    return;
  }
  await store.refresh();
  if (context.mounted) await openChat(context, id);
}
