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
            // 露头条盖在列表顶上:不给底色和底边,它和底下的搜索框
            // 会叠成一层(安卓的拉伸回弹不挪列表,字直接压在字上)
            decoration: BoxDecoration(
              color: sz.paper,
              border: Border(bottom: BorderSide(color: sz.line)),
            ),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              for (final a in apps.take(4)) ...[
                // 和面板里同一套格子(surface 底 + 发丝描边),缩到 22。
                // 内容也和面板一致:图片地址画图,否则画运营配的 emoji ——
                // 露头条和面板画法不同的话,同一个小程序在一次手势里
                // 先后是两副样子
                Container(
                  width: 22,
                  height: 22,
                  alignment: Alignment.center,
                  clipBehavior: Clip.antiAlias,
                  decoration: BoxDecoration(
                    color: sz.surface,
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: sz.line),
                  ),
                  child: a.icon.startsWith('http')
                      ? SzImage(url: a.icon, name: a.name, size: 20, radius: 5)
                      : Text(a.icon,
                          style:
                              const TextStyle(fontSize: kFontNote, height: 1)),
                ),
                const SizedBox(width: 6),
              ],
              const SizedBox(width: 2),
              Text(armed ? '松手打开小程序' : '继续下拉',
                  style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
            ]),
          ),
        ),
      ),
    );
  }
}

/// 全屏面板:从顶部滑入,上滑或点空白收起。
///
/// 动效规范 02:整体 y −100%→0,320ms spring(带一点回弹);
/// 收起 220ms exit —— 消失比出现快,图标不单独动。
/// 图标跟在面板后面 80ms 开始,一个比一个晚 40ms 淡入上浮 8px(见 [_MiniAppsPanel])。
Future<void> showMiniAppsPanel(BuildContext context,
    {required ApiClient api, required List<MiniAppInfo> apps}) {
  return Navigator.of(context).push(PageRouteBuilder(
    opaque: false,
    transitionDuration: SzMotion.of(context, SzMotion.slow),
    reverseTransitionDuration: SzMotion.of(context, SzMotion.base),
    pageBuilder: (_, __, ___) => _MiniAppsPanel(api: api, apps: apps),
    transitionsBuilder: (context, anim, __, child) => SlideTransition(
      position: CurvedAnimation(
              parent: anim, curve: SzMotion.spring, reverseCurve: SzMotion.exit)
          .drive(Tween(begin: const Offset(0, -1), end: Offset.zero)),
      // 回弹那一下面板会往下多走几十像素,顶上垫一截纸色,
      // 不然会从缝里看见后面的首页
      child: Stack(clipBehavior: Clip.none, children: [
        Positioned(
          left: 0,
          right: 0,
          top: -120,
          height: 121,
          child: ColoredBox(color: Theme.of(context).sz.paper),
        ),
        Positioned.fill(child: child),
      ]),
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
                  return SzDelayedIn(
                    delay: const Duration(milliseconds: 80) + SzMotion.staggerAt(i),
                    curve: SzMotion.standard,
                    child: InkWell(
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
                    ),
                  );
                },
              ),
            ),
            // 顺序是运营在后台排的(mini_apps.sort),不是推荐算法,也不是
            // 登记顺序 —— 写「按登记顺序」就是一句查不实的话。
            // 「不卖位置」是 DEV-PROMPTS-31「明确不做」里那条
            Padding(
              padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 6),
              child: Text('顺序由平台人工排定 · 不做推荐,也不卖位置',
                  textAlign: TextAlign.center,
                  style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
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
