// 论坛各页共用的小件。翻页器、错误态、提示框这些地基直接用视频那份
// (`video/me/common.dart`)—— 同一批里已经跑过一遍的东西不重写第二遍。
import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import '../../video/me/common.dart' show videoErrorText;
import '../api.dart';

/// 论坛接口的错误怎么摆:503 是开关关着(「论坛暂未开放」「论坛发帖暂停中」),
/// 用服务端原话给空状态、**不给重试**(重试也还是关着);别的错误给重试。
Widget forumErrorView(Object? error, VoidCallback onRetry) {
  if (error != null && ForumApi.isOff(error)) return SzEmpty(text: '$error');
  return SzError(error: error, onRetry: onRetry);
}

/// 给用户看的一句话(网络问题 ApiClient 已经翻成人话)。
String forumErrorText(Object e) => videoErrorText(e);

void fToast(BuildContext context, Object message) {
  ScaffoldMessenger.maybeOf(context)
      ?.showSnackBar(SnackBar(content: Text(message is String ? message : forumErrorText(message))));
}

/// 一行小字的分隔点:`小王 · @xiaoming · 3 小时前 · 已编辑`。
class FDot extends StatelessWidget {
  const FDot({super.key});

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        child: Text('·', style: TextStyle(fontSize: kFontNote, color: Theme.of(context).sz.inkFaint)),
      );
}

/// 操作栏上的一个按钮:图标 + 数字。[active] 时用 [activeColor] 点亮。
class FActionButton extends StatelessWidget {
  const FActionButton({
    super.key,
    required this.icon,
    this.activeIcon,
    this.count = 0,
    this.active = false,
    this.activeColor,
    this.onTap,
    this.tooltip,
    this.showZero = false,
  });

  final IconData icon;
  final IconData? activeIcon;
  final int count;
  final bool active;
  final Color? activeColor;
  final VoidCallback? onTap;
  final String? tooltip;

  /// 浏览数是 0 也显示(「这条还没人看过」比空着好懂)
  final bool showZero;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    // onTap 为 null = 不能点(「谁能回复」限制到我了、没登录的只读态):画淡色,不画成消失
    final tone = onTap == null ? sz.inkFaint : (active ? (activeColor ?? sz.clay) : sz.inkMuted);
    final button = InkWell(
      borderRadius: BorderRadius.circular(kRadiusSm),
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 6),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(active && activeIcon != null ? activeIcon : icon, size: 17, color: tone),
          if (count > 0 || showZero) ...[
            const SizedBox(width: 4),
            Text(_short(count), style: szTabular(fontSize: kFontNote, color: tone)),
          ],
        ]),
      ),
    );
    return tooltip == null ? button : Tooltip(message: tooltip!, child: button);
  }

  static String _short(int n) {
    if (n < 10000) return '$n';
    final w = n / 10000;
    return '${w >= 100 ? w.toStringAsFixed(0) : w.toStringAsFixed(1)}万';
  }
}

/// 灰条:删了 / 下架了 / 看不到的那一条,在串里占位(§8.1)。
class FUnavailableTile extends StatelessWidget {
  const FUnavailableTile({super.key, required this.text, this.compact = false});

  final String text;

  /// 引用框里那种小一号的
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      margin: EdgeInsets.symmetric(horizontal: compact ? 0 : kPagePad, vertical: compact ? 0 : 6),
      padding: EdgeInsets.all(compact ? 10 : 14),
      decoration: BoxDecoration(
        border: Border.all(color: sz.line),
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      child: Row(children: [
        Icon(Icons.visibility_off_outlined, size: 16, color: sz.inkFaint),
        const SizedBox(width: 8),
        Expanded(child: Text(text, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted))),
      ]),
    );
  }
}

/// 小节标题(探索页、设置页用)。
class FSection extends StatelessWidget {
  const FSection(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 18, kPagePad, 8),
      child: Row(children: [
        Expanded(
          child: Text(text, style: TextStyle(fontSize: kFontBodyLg, color: sz.clay, fontWeight: FontWeight.w600)),
        ),
        if (trailing != null) trailing!,
      ]),
    );
  }
}
