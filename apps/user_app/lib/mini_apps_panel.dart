/// 小程序抽屉(#278 → DEV-PROMPTS-39 #326):首页下拉呼出的那一屏。
///
/// 交互对标微信:列表到顶继续下拉 → 面板跟手露头 → 过阈值松手全屏展开。
/// 手势本体在 main.dart 的 MerchantListView 里(要跟 RefreshIndicator 共存,见那边的注释);
/// 这里只管两个纯 UI:
/// - [MiniAppsPeek]:下拉过程中跟手下移的预览条;
/// - [showMiniAppsPanel]:松手后从顶部滑入的全屏面板。
///
/// 面板自上而下四段:最近使用、常用(各一行)、我的小程序(**默认折叠**)、全部小程序 ›。
/// **只要目录不空就能下拉**。
/// 顺序全听服务端:最近使用按打开时间,常用按自己打开的次数,我的小程序按名字,全部小程序是目录的纯函数排序
/// (精选在前、其余按首次上架时间)—— 客户端一个都不重排,也不做推荐。客户端只做一件事:
/// 「常用」里去掉上一行「最近使用」已经摆出来的,同一个图标不在两行里各占一格。
///
/// 要紧凑(2026-09-15 用户):抽屉是随手一拉的地方,一眼要扫完。所以格子只画图标和名字 ——
/// 小程序自己有图标和名字,一句话介绍留给详情页;列数按可用宽度排,常见手机一行 5 个;
/// 最近使用、常用各只摆一行,更多的在「我的小程序」和「全部小程序」里。
library;

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:superz_shared/superz_shared.dart';

import 'miniapp/container.dart';
import 'miniapp/pages.dart';

/// 下拉超过这个逻辑像素数,松手即展开面板(微信手感约 90–120)
const kMiniAppsPullThreshold = 120.0;

/// 拉过这么多、但没到 [kMiniAppsPullThreshold] 就松手 = 刷新(DEV-PROMPTS-39 #338 真机验出来的):
/// RefreshIndicator 自己要拉到视口高度的 1/6 才上膛,常见手机上约 130,比面板阈值还深 ——
/// 靠它自己的话,「浅拉刷新」根本拉不出来,一拉就是面板。首页在松手时替它扣扳机
const kMiniAppsRefreshPull = 56.0;

/// 露头条的高度。首页下拉时底下的内容跟着让出这么多(设计稿 2a 的「下拉中」)
const kMiniAppsPeekHeight = 56.0;

/// 格子里画哪个字(设计稿 2a:和频道字块同一套,一个衬线汉字)。见 [miniAppGlyphOf]
String miniAppGlyph(MiniAppCard a) => miniAppGlyphOf(a);

/// 下拉过程中的预览条:跟手下移,过阈值换文案。
/// 放在首页 Stack 顶层,由外面用拉距驱动,自身无状态。
class MiniAppsPeek extends StatelessWidget {
  const MiniAppsPeek({super.key, required this.pull, required this.apps, required this.api});

  /// 当前累计拉距(逻辑像素,>= 0)
  final double pull;
  final List<MiniAppCard> apps;
  final ApiClient api;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    final t = (pull / kMiniAppsPullThreshold).clamp(0.0, 1.0);
    final armed = t >= 1.0;
    // 两段手势,文案跟着说清楚:浅拉松手刷新,拉过阈值松手开面板
    final label = armed
        ? '松手打开小程序'
        : pull >= kMiniAppsRefreshPull
            ? '松手刷新 · 继续下拉打开小程序'
            : '继续下拉';
    return IgnorePointer(
      child: Opacity(
        opacity: t,
        child: Transform.translate(
          // 从视口上方滑入:拉多少露多少
          offset: Offset(0, (t - 1) * kMiniAppsPeekHeight),
          // 底边是虚线(设计稿 2a):它和底下的内容是两层,实线会读成「页面到这儿结束了」
          child: CustomPaint(
            foregroundPainter: _DashedBottom(sz.line),
            child: Container(
              height: kMiniAppsPeekHeight,
              alignment: Alignment.center,
              // 露头条自己有纸色底:iOS 回弹时底下是空的,安卓那边首页会跟着往下让
              color: sz.paper,
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                for (final a in apps.take(4)) ...[
                  MiniAppIcon(card: a, api: api, size: 22),
                  const SizedBox(width: 6),
                ],
                const SizedBox(width: 2),
                Text(label, style: TextStyle(fontSize: kFontNote, color: sz.inkMuted)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// 露头条底下那条虚线:4px 实、3px 空,1px 高。
class _DashedBottom extends CustomPainter {
  _DashedBottom(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1;
    final y = size.height - .5;
    for (double x = 0; x < size.width; x += 7) {
      canvas.drawLine(Offset(x, y), Offset(math.min(x + 4, size.width), y), paint);
    }
  }

  @override
  bool shouldRepaint(_DashedBottom old) => old.color != color;
}

/// 全屏面板:从顶部滑入,上滑或点空白收起。
///
/// 动效规范 02:整体 y −100%→0,320ms spring(带一点回弹);收起 220ms exit ——
/// 消失比出现快,图标不单独动。图标跟在面板后面 80ms 开始,一个比一个晚 40ms 淡入上浮。
Future<void> showMiniAppsPanel(BuildContext context,
    {required ApiClient api, required List<MiniAppCard> apps}) {
  return Navigator.of(context).push(PageRouteBuilder(
    opaque: false,
    transitionDuration: SzMotion.of(context, SzMotion.slow),
    reverseTransitionDuration: SzMotion.of(context, SzMotion.base),
    pageBuilder: (_, __, ___) => _MiniAppsPanel(api: api, catalog: apps),
    transitionsBuilder: (context, anim, __, child) => SlideTransition(
      position: CurvedAnimation(parent: anim, curve: SzMotion.spring, reverseCurve: SzMotion.exit)
          .drive(Tween(begin: const Offset(0, -1), end: Offset.zero)),
      // 回弹那一下面板会往下多走几十像素,顶上垫一截纸色,不然会从缝里看见后面的首页
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

class _MiniAppsPanel extends StatefulWidget {
  const _MiniAppsPanel({required this.api, required this.catalog});

  final ApiClient api;
  final List<MiniAppCard> catalog;

  @override
  State<_MiniAppsPanel> createState() => _MiniAppsPanelState();
}

/// 一格的目标宽度:360–414 宽的手机上正好一行 5 个,宽屏按宽度多排;名字 5 个字以内放得下
const double _kCellWidth = 64;
const int _kMinCols = 4;
const int _kMaxCols = 8;
const double _kIconSize = 44;

/// 可用宽度下一行排几个
int miniAppPanelColumns(double width) =>
    ((width - 2 * kPagePad) / _kCellWidth).floor().clamp(_kMinCols, _kMaxCols);

class _MiniAppsPanelState extends State<_MiniAppsPanel> {
  List<MiniAppCard> _recent = const [];
  List<MiniAppCard> _frequent = const [];
  List<MiniAppCard> _starred = const [];
  // 我的小程序默认折叠:常点的已经在最上面两行了,收藏的全摊开会把「全部小程序」挤到屏幕外
  bool _starredOpen = false;
  double _upPull = 0;
  bool _closing = false;

  @override
  void initState() {
    super.initState();
    _loadMine();
  }

  Future<void> _loadMine() async {
    if (!widget.api.isLoggedIn) return;
    try {
      final m = await widget.api.miniAppMine();
      if (mounted) setState(() => (_recent = m.recent, _frequent = m.frequent, _starred = m.starred));
    } catch (_) {}
  }

  Future<void> _open(MiniAppCard a) async {
    await openMiniApp(context, widget.api, appid: a.appid, card: a);
    // 关掉回到抽屉:刚用过的要排到「最近使用」第一个,在详情里收藏的也要出现
    await _loadMine();
  }

  void _close() {
    if (_closing) return;
    _closing = true;
    Navigator.of(context).maybePop();
  }

  /// 在列表上往上推也要能收起:列表是 primary 的,默认物理是「总能滚」,会把竖向拖动抢走,
  /// 外层 GestureDetector 的上滑就收不到(原先只有标题和底下那一截能上滑收起)。
  /// 所以看列表自己的越界:推到底还往上推(内容不满一屏时一推就是到底)超过一小段,就收起
  bool _onScroll(ScrollNotification n) {
    if (n is OverscrollNotification && n.dragDetails != null && n.overscroll > 0) {
      _upPull += n.overscroll;
      if (_upPull > 48) _close();
    } else if (n is ScrollStartNotification || n is ScrollEndNotification) {
      _upPull = 0;
    }
    return false;
  }

  /// 格子:宽度按列数分,**高度由内容撑**(Wrap 而不是定高的 GridView)。
  /// 定高要猜名字那一行多高,主题行高、系统字号一变就溢出 —— 第一版按「字号 × 1.4」猜,实际高出 2 像素,测试当场红了
  Widget _grid(List<MiniAppCard> apps, int cols, double width, {int offset = 0}) {
    final sz = Theme.of(context).sz;
    const gap = 4.0;
    // 向下取整:几个格子宽度加起来不能超过一行,差一点浮点误差最后一个就会被挤到下一行
    final cell = ((width - 2 * kPagePad - (cols - 1) * gap) / cols).floorToDouble();
    return Padding(
      padding: const EdgeInsets.fromLTRB(kPagePad, 4, kPagePad, 2),
      child: Wrap(spacing: gap, runSpacing: 6, children: [
        for (var i = 0; i < apps.length; i++)
          SizedBox(
            width: cell,
            child: SzDelayedIn(
              delay: const Duration(milliseconds: 80) + SzMotion.staggerAt(offset + i),
              curve: SzMotion.standard,
              child: InkWell(
                borderRadius: BorderRadius.circular(kRadiusMd),
                onTap: () => _open(apps[i]),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    MiniAppIcon(card: apps[i], api: widget.api, size: _kIconSize),
                    const SizedBox(height: 4),
                    Text(apps[i].name,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: kFontNote, color: sz.ink)),
                  ]),
                ),
              ),
            ),
          ),
      ]),
    );
  }

  TextStyle _titleStyle() =>
      TextStyle(fontSize: kFontBody, fontWeight: FontWeight.w600, color: Theme.of(context).sz.inkMuted);

  Widget _title(String text) => Padding(
        padding: const EdgeInsets.fromLTRB(kPagePad, 10, kPagePad, 0),
        child: Text(text, style: _titleStyle()),
      );

  /// 「全部小程序 · 查看全部 ›」:整行可点。原来右边是个 TextButton,自带 48 高的点击区,
  /// 这一行的上下留白比别的标题多出一截(截图里一眼就看得出来)
  Widget _catalogTitle() {
    final sz = Theme.of(context).sz;
    return Semantics(
      button: true,
      child: InkWell(
        onTap: () => Navigator.of(context)
            .push(MaterialPageRoute(builder: (_) => MiniAppCatalogPage(api: widget.api))),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 10, kPagePad, 4),
          child: Row(children: [
            Text('全部小程序', style: _titleStyle()),
            const Spacer(),
            Text('查看全部 ›', style: TextStyle(fontSize: kFontNote, color: sz.link)),
          ]),
        ),
      ),
    );
  }

  /// 「我的小程序」的标题行:点一下展开 / 收起,标着有几个
  Widget _starredHeader() {
    final sz = Theme.of(context).sz;
    return Semantics(
      button: true,
      expanded: _starredOpen,
      child: InkWell(
        onTap: () => setState(() => _starredOpen = !_starredOpen),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(kPagePad, 10, kPagePad, 4),
          child: Row(children: [
            Text('我的小程序', style: _titleStyle()),
            const SizedBox(width: 6),
            Text('${_starred.length}', style: TextStyle(fontSize: kFontNote, color: sz.inkFaint)),
            const Spacer(),
            AnimatedRotation(
              turns: _starredOpen ? .5 : 0,
              duration: SzMotion.of(context, SzMotion.base),
              curve: SzMotion.standard,
              child: Icon(Icons.expand_more, size: 20, color: sz.inkFaint),
            ),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return GestureDetector(
      // 上滑收起(面板从上面来,回上面去);点空白也收
      onVerticalDragEnd: (d) {
        if ((d.primaryVelocity ?? 0) < -300) _close();
      },
      onTap: _close,
      child: Scaffold(
        backgroundColor: sz.paper,
        body: SafeArea(
          // 宽屏(平板、电脑)限宽居中:一行摆十几个图标,眼睛从左扫到右太远(见 SzContentWidth)
          child: SzContentWidth(
            child: LayoutBuilder(builder: (context, box) {
              final cols = miniAppPanelColumns(box.maxWidth);
              final recent = _recent.take(cols).toList();
              final inRecent = {for (final a in recent) a.appid};
              final frequent = _frequent.where((a) => !inRecent.contains(a.appid)).take(cols).toList();
              final all = widget.catalog.take(cols * 2).toList();
              final shownAbove = recent.length + frequent.length;
              return Column(children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(kPagePad, 12, kPagePad, 0),
                  child: Row(children: [
                    Text('小程序',
                        style: TextStyle(fontSize: kFontTitle, fontWeight: FontWeight.w600, color: sz.ink)),
                    const Spacer(),
                    Text('网页应用 · 不装包', style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
                  ]),
                ),
                Expanded(
                  child: NotificationListener<ScrollNotification>(
                    onNotification: _onScroll,
                    child: ListView(padding: const EdgeInsets.only(bottom: 8), children: [
                      if (recent.isNotEmpty) ...[_title('最近使用'), _grid(recent, cols, box.maxWidth)],
                      if (frequent.isNotEmpty) ...[
                        _title('常用'),
                        _grid(frequent, cols, box.maxWidth, offset: recent.length),
                      ],
                      if (_starred.isNotEmpty) ...[
                        _starredHeader(),
                        AnimatedSize(
                          duration: SzMotion.of(context, SzMotion.base),
                          curve: SzMotion.standard,
                          alignment: Alignment.topCenter,
                          child: _starredOpen
                              ? _grid(_starred, cols, box.maxWidth, offset: shownAbove)
                              : const SizedBox(width: double.infinity),
                        ),
                      ],
                      _catalogTitle(),
                      _grid(all, cols, box.maxWidth, offset: shownAbove + (_starredOpen ? _starred.length : 0)),
                    ]),
                  ),
                ),
                // 顺序说明是一句对外承诺:精选是人工的(理由公示),其余按上架时间 —— 没有可以买的位置
                Padding(
                  padding: const EdgeInsets.fromLTRB(kPagePad, 0, kPagePad, 4),
                  child: Text('精选由平台人工挑选、理由公示;其余按上架时间 · 不做推荐,也不卖位置',
                      textAlign: TextAlign.center, style: TextStyle(fontSize: kFontMicro, color: sz.inkFaint)),
                ),
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: Icon(Icons.keyboard_arrow_up, color: sz.inkFaint),
                ),
              ]);
            }),
          ),
        ),
      ),
    );
  }
}
