import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../session.dart';
import '../models.dart';
import '../nav.dart';

/// 关注 / 已关注按钮(空间、搜索、详情页的 UP 主卡共用)。
///
/// [outlined]:没关注时画 clay 描边、clay 字的「关注」,不画实底 —— 视频详情页那一屏的实底按钮
/// 留给挂的店铺卡上的「去点单」(一屏只有一个 clay 实底按钮,设计稿 E)。
class FollowButton extends StatefulWidget {
  const FollowButton({super.key, required this.person, required this.onChanged, this.dense = false, this.outlined = false});

  final VPerson person;
  final void Function(VPerson p) onChanged;
  final bool dense;
  final bool outlined;

  @override
  State<FollowButton> createState() => _FollowButtonState();
}

class _FollowButtonState extends State<FollowButton> {
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final p = widget.person;
    if (widget.outlined) {
      final sz = Theme.of(context).sz;
      final tone = p.followed ? sz.inkMuted : sz.clay;
      return OutlinedButton(
        style: OutlinedButton.styleFrom(
          foregroundColor: tone,
          side: BorderSide(color: p.followed ? sz.line : sz.clay),
          minimumSize: const Size(64, 32),
          padding: const EdgeInsets.symmetric(horizontal: 16),
          visualDensity: VisualDensity.compact,
          tapTargetSize: MaterialTapTargetSize.padded,
          textStyle: const TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600),
        ),
        onPressed: _busy ? null : () => _toggle(!p.followed),
        child: Text(p.followed ? '已关注' : '关注'),
      );
    }
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
