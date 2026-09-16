import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../nav.dart';
import 'common.dart';

/// 举报原因(§5.11:共用视频的 C1xx / X999,论坛另加 F4xx)。
/// 和审核后台同一张表 —— 这里改了那边也得改。
const forumReportReasons = <String, String>{
  'C101': '骚扰、辱骂',
  'C102': '垃圾广告、引流',
  'C103': '诈骗',
  'C104': '色情、低俗',
  'C105': '暴力、血腥',
  'C106': '违法违规(赌博、毒品、枪支等)',
  'C107': '侵犯隐私',
  'C108': '冒充他人或官方',
  'C109': '未成年人不宜',
  'F401': '刷屏、重复发帖',
  'F402': '蹭无关话题',
  'F403': '恶意引战、人身攻击',
  'X999': '其他(要写说明)',
};

/// 举报一条帖子:选原因(其他要写说明)→ 提交。举报人对被举报的一方永远匿名。
Future<void> reportForumPost(BuildContext context, String pid) async {
  if (!await ensureLoggedIn(context)) return;
  if (!context.mounted) return;
  final code = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: SizedBox(
        height: MediaQuery.of(ctx).size.height * .6,
        child: ListView(children: [
          const ListTile(title: Text('为什么举报?', style: TextStyle(fontWeight: FontWeight.w600))),
          for (final e in forumReportReasons.entries)
            ListTile(title: Text(e.value), onTap: () => Navigator.pop(ctx, e.key)),
        ]),
      ),
    ),
  );
  if (code == null || !context.mounted) return;
  var note = '';
  if (code == 'X999') {
    final c = TextEditingController();
    final r = await showDialog<String>(
      context: context,
      builder: (ctx) => SzDisposeWith(
        controllers: [c],
        child: SzDialog(
          title: const Text('说明一下'),
          content: TextField(controller: c, autofocus: true, maxLength: 200,
              decoration: const InputDecoration(hintText: '至少 5 个字')),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
            FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('提交')),
          ],
        ),
      ),
    );
    if (r == null || !context.mounted) return;
    note = r;
  }
  try {
    await forumApi.report(pid, code, note: note);
    if (context.mounted) fToast(context, '已举报,我们会尽快处理');
  } on ApiException catch (e) {
    if (context.mounted) fToast(context, e.message);
  }
}

/// 被下架了,申诉一次(换人复核,§2.2)。
Future<void> appealForumPost(BuildContext context, String pid) async {
  final c = TextEditingController();
  final text = await showDialog<String>(
    context: context,
    builder: (ctx) => SzDisposeWith(
      controllers: [c],
      child: SzDialog(
        title: const Text('申诉'),
        content: TextField(
          controller: c,
          autofocus: true,
          maxLength: 300,
          maxLines: 4,
          decoration: const InputDecoration(hintText: '说说为什么觉得判错了(换一个人复核,只能申诉一次)'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()), child: const Text('提交')),
        ],
      ),
    ),
  );
  if (text == null || text.isEmpty || !context.mounted) return;
  try {
    await forumApi.appeal(pid, text);
    if (context.mounted) fToast(context, '申诉已提交,会换一个人复核');
  } on ApiException catch (e) {
    if (context.mounted) fToast(context, e.message);
  }
}
