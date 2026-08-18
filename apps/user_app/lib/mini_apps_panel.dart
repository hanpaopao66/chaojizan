/// 小程序面板(#278):首页下拉呼出的那一屏。
///
/// 交互对标微信:列表到顶继续下拉 → 面板跟手露头 → 过阈值松手全屏展开。
/// 手势本体在 main.dart 的 MerchantListView 里(要跟 RefreshIndicator
/// 共存,见那边的注释);这里只管两个纯 UI:
/// - [MiniAppsPeek]:下拉过程中跟手下移的预览条;
/// - [showMiniAppsPanel]:松手后从顶部滑入的全屏面板。
///
/// 面板里不做推荐、不做排序算法 —— 顺序就是服务端 sort 的顺序,
/// 这条写在 DEV-PROMPTS-31 的「明确不做」里。
library;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'mini_app_sheet.dart';

/// 下拉超过这个逻辑像素数,松手即展开面板(微信手感约 90–120)
const kMiniAppsPullThreshold = 120.0;

/// 下拉过程中的预览条:跟手下移,过阈值换文案。
/// 放在首页 Stack 顶层,由外面用拉距驱动,自身无状态。
class MiniAppsPeek extends StatelessWidget {
  const MiniAppsPeek({super.key, required this.pull, required this.apps});

  /// 当前累计拉距(逻辑像素,>= 0)
  final double pull;
  final List<MiniAppInfo> apps;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final t = (pull / kMiniAppsPullThreshold).clamp(0.0, 1.0);
    final armed = t >= 1.0;
    return IgnorePointer(
      child: Opacity(
        opacity: t,
        child: Transform.translate(
          // 从视口上方滑入:拉多少露多少
          offset: Offset(0, (t - 1) * 56),
          child: Container(
            height: 56,
            alignment: Alignment.center,
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              for (final a in apps.take(4)) ...[
                Text(a.icon.startsWith('http') ? '🧩' : a.icon,
                    style: const TextStyle(fontSize: 16)),
                const SizedBox(width: 6),
              ],
              const SizedBox(width: 2),
              Text(armed ? '松手打开小程序' : '继续下拉',
                  style: TextStyle(fontSize: 12, color: sz.inkMuted)),
            ]),
          ),
        ),
      ),
    );
  }
}

/// 全屏面板:从顶部滑入,上滑或点空白收起。
Future<void> showMiniAppsPanel(BuildContext context,
    {required ApiClient api, required List<MiniAppInfo> apps}) {
  return Navigator.of(context).push(PageRouteBuilder(
    opaque: false,
    transitionDuration: const Duration(milliseconds: 240),
    reverseTransitionDuration: const Duration(milliseconds: 200),
    pageBuilder: (_, __, ___) => _MiniAppsPanel(api: api, apps: apps),
    transitionsBuilder: (_, anim, __, child) => SlideTransition(
      position: anim.drive(Tween(begin: const Offset(0, -1), end: Offset.zero)
          .chain(CurveTween(curve: Curves.easeOutCubic))),
      child: child,
    ),
  ));
}

class _MiniAppsPanel extends StatelessWidget {
  const _MiniAppsPanel({required this.api, required this.apps});

  final ApiClient api;
  final List<MiniAppInfo> apps;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return GestureDetector(
      // 上滑收起(面板从上面来,回上面去);点空白也收
      onVerticalDragEnd: (d) {
        if ((d.primaryVelocity ?? 0) < -300) Navigator.of(context).pop();
      },
      onTap: () => Navigator.of(context).pop(),
      child: Scaffold(
        backgroundColor: sz.paper,
        body: SafeArea(
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 18, kPagePad, 6),
              child: Row(children: [
                Text('小程序',
                    style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w600,
                        color: sz.ink)),
                const Spacer(),
                Text('网页应用 · 不装包',
                    style: TextStyle(fontSize: 11.5, color: sz.inkFaint)),
              ]),
            ),
            Expanded(
              child: GridView.builder(
                padding: const EdgeInsets.fromLTRB(
                    kPagePad, 10, kPagePad, kPagePad),
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 4,
                    mainAxisSpacing: 18,
                    crossAxisSpacing: 10,
                    childAspectRatio: 0.82),
                itemCount: apps.length,
                itemBuilder: (context, i) {
                  final a = apps[i];
                  return InkWell(
                    borderRadius: BorderRadius.circular(kRadiusMd),
                    onTap: () => showMiniAppSheet(context, api: api, app: a),
                    child: Column(children: [
                      Container(
                        width: 52,
                        height: 52,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: sz.surface,
                          borderRadius: BorderRadius.circular(kRadiusMd),
                          border: Border.all(color: sz.line),
                        ),
                        child: a.icon.startsWith('http')
                            ? SzImage(
                                url: a.icon,
                                name: a.name,
                                size: 52,
                                radius: kRadiusMd)
                            : Text(a.icon,
                                style: const TextStyle(fontSize: 26)),
                      ),
                      const SizedBox(height: 6),
                      Text(a.name,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(fontSize: 12, color: sz.ink)),
                      if (a.tagline.isNotEmpty)
                        Text(a.tagline,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style:
                                TextStyle(fontSize: 9.5, color: sz.inkFaint)),
                    ]),
                  );
                },
              ),
            ),
            // 收起提示:面板怎么来的就怎么走
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Icon(Icons.keyboard_arrow_up, color: sz.inkFaint),
            ),
          ]),
        ),
      ),
    );
  }
}
