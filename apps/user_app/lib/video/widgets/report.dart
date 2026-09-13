import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../nav.dart';

/// 举报原因(§5.11,和审核后台同一张表)。视频专有的 V2xx 只在举报视频时给。
const reportReasons = <String, String>{
  'C101': '骚扰、辱骂',
  'C102': '垃圾广告、引流',
  'C103': '诈骗',
  'C104': '色情、低俗',
  'C105': '暴力、血腥',
  'C106': '违法违规(赌博、毒品、枪支等)',
  'C107': '侵犯隐私',
  'C108': '冒充他人或官方',
  'C109': '未成年人不宜',
  'V201': '视频侵权(未经授权搬运)',
  'V202': '标题 / 封面与内容不符',
  'V203': '画质或内容不完整',
  'V204': '分区选错',
  'V205': '挂了店铺却说「无合作」',
  'V206': '危险行为',
  'X999': '其他(要写说明)',
};

/// 举报视频 / 评论 / 弹幕:选原因(其他要写 ≥5 个字的说明)→ 提交。举报人对被举报的一方永远匿名。
Future<void> reportTarget(BuildContext context, {required String targetType, int? targetId, String? vid}) async {
  final reasons = {
    for (final e in reportReasons.entries)
      if (targetType == 'video' || !e.key.startsWith('V')) e.key: e.value,
  };
  final code = await szShowSheet<String>(
    context: context,
    builder: (ctx) => SafeArea(
      child: SizedBox(
        height: MediaQuery.of(ctx).size.height * .6,
        child: ListView(children: [
          const ListTile(title: Text('为什么举报?', style: TextStyle(fontWeight: FontWeight.w600))),
          for (final e in reasons.entries)
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
          content: TextField(controller: c, autofocus: true, maxLength: 200, decoration: const InputDecoration(hintText: '至少 5 个字')),
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
    final r = await videoApi.report(targetType: targetType, targetId: targetId, vid: vid, reasonCode: code, note: note);
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(r['status'] == 'escalated' ? '已举报,好几个人都举报了它,会优先处理' : '已举报,我们会尽快处理')));
    }
  } on ApiException catch (e) {
    if (context.mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
  }
}
