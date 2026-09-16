// 帖子里的投票(F1、§5.6:2–4 项、每人一票、不能改)。
//
// 三态:
//   1. 还能投 —— 每项是一个能点的描边按钮,**看不到票数**(§8.1:votes 和 total 是 null);
//   2. 投过了 / 已结束 —— 每项画成横条,底下是占比和票数,我投的那项打勾;
//   3. 没登录 —— 和第一态长一样,点下去先引导登录。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../models.dart';

class PollView extends StatelessWidget {
  const PollView(this.poll, {super.key, this.onVote, this.busy = false});

  final FPoll poll;

  /// 点某一项(0 起)。为 null = 只读(别人的详情页里已经结束的投票)
  final void Function(int option)? onVote;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final results = poll.showResults;
    final left = fPollLeft(poll);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (var i = 0; i < poll.options.length; i++) ...[
        if (i > 0) const SizedBox(height: 8),
        results ? _ResultBar(poll: poll, index: i) : _VoteButton(
          text: poll.options[i].text,
          onTap: busy || onVote == null || !poll.canVote ? null : () => onVote!(i),
        ),
      ],
      const SizedBox(height: 8),
      Row(children: [
        if (poll.total != null)
          Text('${poll.total} 人投票', style: szTabular(fontSize: kFontNote, color: sz.inkMuted)),
        if (poll.total != null && left.isNotEmpty)
          Text(' · ', style: TextStyle(fontSize: kFontNote, color: sz.inkFaint)),
        if (left.isNotEmpty) Text(left, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
        if (poll.total == null && left.isEmpty)
          Text('投票后才能看到结果', style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
      ]),
    ]);
  }
}

class _VoteButton extends StatelessWidget {
  const _VoteButton({required this.text, required this.onTap});

  final String text;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return SizedBox(
      width: double.infinity,
      child: OutlinedButton(
        style: OutlinedButton.styleFrom(
          foregroundColor: sz.clay,
          side: BorderSide(color: onTap == null ? sz.line : sz.clay),
          padding: const EdgeInsets.symmetric(vertical: 10),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(kRadiusLg)),
        ),
        onPressed: onTap,
        child: Text(text, maxLines: 2, overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600)),
      ),
    );
  }
}

class _ResultBar extends StatelessWidget {
  const _ResultBar({required this.poll, required this.index});

  final FPoll poll;
  final int index;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final o = poll.options[index];
    final share = poll.share(index);
    final mine = poll.voted == index;
    return Semantics(
      label: '${o.text},${(share * 100).round()}%${mine ? ',我投的' : ''}',
      child: Stack(children: [
        // 横条本身:占比那一段用 claySoft 填,剩下的是底色 —— 不用进度条组件,
        // 因为这里要在条上叠文字
        Container(
          height: 34,
          decoration: BoxDecoration(color: sz.surfaceAlt, borderRadius: BorderRadius.circular(kRadiusSm)),
        ),
        Positioned.fill(
          child: FractionallySizedBox(
            alignment: Alignment.centerLeft,
            widthFactor: share.clamp(0.0, 1.0),
            child: Container(
              decoration: BoxDecoration(color: sz.claySoft, borderRadius: BorderRadius.circular(kRadiusSm)),
            ),
          ),
        ),
        Positioned.fill(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            child: Row(children: [
              if (mine) ...[
                Icon(Icons.check, size: 15, color: sz.clay),
                const SizedBox(width: 4),
              ],
              Expanded(
                child: Text(o.text,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: kFontBody, color: sz.ink,
                        fontWeight: mine ? FontWeight.w600 : FontWeight.w400)),
              ),
              const SizedBox(width: 8),
              Text('${(share * 100).round()}%', style: szTabular(fontSize: kFontNote, color: sz.ink)),
              if (o.votes != null) ...[
                const SizedBox(width: 6),
                Text('${o.votes}', style: szTabular(fontSize: kFontMicro, color: sz.inkMuted)),
              ],
            ]),
          ),
        ),
      ]),
    );
  }
}
