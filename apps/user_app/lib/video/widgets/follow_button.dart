import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../models.dart';
import '../nav.dart';

/// 关注 / 已关注按钮(空间、搜索、详情页的 UP 主卡共用)。
class FollowButton extends StatefulWidget {
  const FollowButton({super.key, required this.person, required this.onChanged, this.dense = false});

  final VPerson person;
  final void Function(VPerson p) onChanged;
  final bool dense;

  @override
  State<FollowButton> createState() => _FollowButtonState();
}

class _FollowButtonState extends State<FollowButton> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final p = widget.person;
    final style = widget.dense
        ? const ButtonStyle(visualDensity: VisualDensity.compact, padding: WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 12)))
        : null;
    return p.followed
        ? OutlinedButton(style: style, onPressed: _busy ? null : () => _toggle(false), child: const Text('已关注'))
        : FilledButton(style: style, onPressed: _busy ? null : () => _toggle(true), child: const Text('+ 关注'));
  }

  Future<void> _toggle(bool follow) async {
    if (!await ensureLoggedIn(context)) return;
    setState(() => _busy = true);
    try {
      final r = await videoApi.follow(widget.person.id, follow);
      widget.onChanged(widget.person.copyWith(followed: r['followed'] == true, fans: vInt(r['fans'])));
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}
