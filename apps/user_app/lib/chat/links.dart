import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../video/nav.dart';
import 'chat_page.dart';
import 'pages/pickers.dart';
import 'pages/user_profile_page.dart';
import 'store.dart';
import 'ui/avatar.dart';

/// 站内链接(和 Telegram 的 t.me 一样):在 App 里直接打开,不跳浏览器。
///
/// - `chaojizan.cc/@用户名` → 这个人的资料 / 公开群、频道;
/// - `chaojizan.cc/@频道名/123` → 打开频道并跳到第 123 条;
/// - `chaojizan.cc/join/邀请码` → 邀请链接预览,可以加入;
/// - `chaojizan.cc/u/名片编号` → 这个人的资料(没有用户名的人的名片链接);
/// - `chaojizan.cc/v/视频号` → 视频详情(`?p=2` 从第 2 P 开始)。
///
/// 返回 true 表示认得、已经处理;false 交给调用方(一般是问一句再用浏览器打开)。
Future<bool> openAppLink(BuildContext context, Uri uri) async {
  final host = uri.host.toLowerCase();
  if (host != 'chaojizan.cc' && host != 'www.chaojizan.cc') return false;
  final seg = uri.pathSegments.where((s) => s.isNotEmpty).toList();
  if (seg.isEmpty) return false;
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
