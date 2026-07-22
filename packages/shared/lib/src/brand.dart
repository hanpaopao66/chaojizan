/// Super-Z 品牌体系:颜色 token + 矢量 Logo。
///
/// 完整规范见 docs/BRAND.md。核心原则:
///  - 炉火橙是行动色(按钮/价格/选中),不是装饰色——大面积铺橙是禁忌
///  - 钱的正向语义(商家实收/骑手所得/余额)一律用账目绿,给踏实感
///  - 信任靠产品体验传达(账单可查/秒退款),不靠口号横幅
library;

import 'package:flutter/material.dart';

/// 炉火橙:外卖的烟火气。主行动色(按钮/价格/选中态种子色)
const Color kBrandOrange = Color(0xFFFF5A1F);

/// 账目绿:钱的颜色。只用于金额正向语义(实收/所得/余额/到账)
const Color kMoneyGreen = Color(0xFF0E8A5F);

/// 促销琥珀:满减/折扣标签专用(与主橙区分,避免促销淹没行动点)
const Color kPromoAmber = Color(0xFFB25E09);

// ---- v2 令牌(marketing/design/三端UI风格系统.html)----
const Color kInk = Color(0xFF1C1917);       // 墨色:标题与负向金额
const Color kGray = Color(0xFF8A8078);      // 暖灰:辅助说明
const Color kLine = Color(0xFFF0EBE7);      // 暖线:卡片描边
const Color kWarmBg = Color(0xFFF6F6F8);    // 页面底色
const Color kInputFill = Color(0xFFF0EFEA); // 输入框填充
const Color kGreenBg = Color(0xFFE7F4EE);   // 绿 chip 底
const Color kAmberBg = Color(0xFFFDF3E0);   // 琥珀 chip 底

/// 金额文本样式:等宽数字,账目绿。size 传比所在行说明文字大一级的值。
TextStyle kMoneyText(double size, {Color color = kMoneyGreen}) => TextStyle(
      fontSize: size,
      fontWeight: FontWeight.w800,
      color: color,
      fontFeatures: const [FontFeature.tabularFigures()],
    );

/// 三端统一的品牌主题 v2:组件级主题补全,全局去"原生 Flutter 味"。
///
/// 七条规则(设计依据 marketing/design/三端UI风格系统.html):
///  1. 一屏只有一个橙色主按钮(FilledButton),其余 Outlined/Text
///  2. 到手的钱一律账目绿 + 等宽数字(kMoneyText),比说明文字大一级
///  3. 状态用 chip 表达,红色只留给报错
///  4. 列表 = 白卡 + 间距,不用满屏 Divider
///  5. AppBar 与背景同色、无阴影、大标题
///  6. 品牌渐变只出现在 Logo 与承诺卡(PledgeCard)
///  7. 空态用 brand_art 插画,不用灰图标
ThemeData brandTheme(Brightness brightness) {
  final light = brightness == Brightness.light;
  // M3 的 tone 映射会把橙压暗成棕;主行动色直接钉死为炉火橙,
  // 其余层次(container/surface 等)仍由 seed 派生,保持体系和谐
  final seeded = ColorScheme.fromSeed(
    seedColor: kBrandOrange,
    brightness: brightness,
    dynamicSchemeVariant: DynamicSchemeVariant.vibrant,
  );
  final scheme = light
      ? seeded.copyWith(
          primary: kBrandOrange,
          onPrimary: Colors.white,
          surface: Colors.white,
          error: const Color(0xFFD03030),
        )
      : seeded;

  final baseText = Typography.material2021(platform: TargetPlatform.android)
      .black
      .apply(bodyColor: light ? kInk : null, displayColor: light ? kInk : null);

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: light ? kWarmBg : null,
    splashFactory: InkSparkle.splashFactory,

    // ---- 字阶:22/900 页标题、17/800 卡标题、15 正文、13 辅助 ----
    textTheme: baseText.copyWith(
      headlineSmall:
          const TextStyle(fontSize: 22, fontWeight: FontWeight.w900, height: 1.3),
      titleMedium:
          const TextStyle(fontSize: 17, fontWeight: FontWeight.w800, height: 1.35),
      titleSmall: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
      bodyMedium: const TextStyle(fontSize: 15, height: 1.6),
      bodySmall: TextStyle(fontSize: 13, color: light ? kGray : null, height: 1.5),
      labelSmall: TextStyle(fontSize: 11, color: light ? kGray : null),
    ),

    // ---- AppBar:与背景同色、无阴影、左对齐大标题 ----
    appBarTheme: AppBarTheme(
      backgroundColor: light ? kWarmBg : null,
      scrolledUnderElevation: 0,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
          fontSize: 22, fontWeight: FontWeight.w900, color: light ? kInk : null),
    ),

    // ---- 卡片:白底、圆角 14、1px 暖线描边、零阴影、零边距 ----
    cardTheme: CardThemeData(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: light ? kLine : Colors.transparent),
      ),
      color: light ? Colors.white : scheme.surfaceContainerHigh,
      margin: EdgeInsets.zero,
    ),

    // ---- 按钮:胶囊形;Filled=橙色主按钮(一屏一个),Outlined=次,Text=弱 ----
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: kBrandOrange,
        foregroundColor: Colors.white,
        minimumSize: const Size(64, 48),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        elevation: 0,
        backgroundColor: kBrandOrange,
        foregroundColor: Colors.white,
        minimumSize: const Size(64, 48),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: kBrandOrange,
        side: const BorderSide(color: kBrandOrange, width: 1.5),
        minimumSize: const Size(64, 44),
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: light ? const Color(0xFF666059) : null,
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
      ),
    ),

    // ---- 输入框:暖灰填充、圆角 12、无边框线 ----
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: light ? kInputFill : scheme.surfaceContainerHigh,
      hintStyle: const TextStyle(color: Color(0xFFA39B92), fontSize: 15),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide.none,
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: kBrandOrange, width: 1.5),
      ),
    ),

    // ---- chip:圆角胶囊,小号粗体;颜色语义在调用处给 ----
    chipTheme: ChipThemeData(
      shape: const StadiumBorder(),
      side: BorderSide.none,
      backgroundColor: light ? kGreenBg : scheme.surfaceContainerHigh,
      labelStyle: const TextStyle(
          fontSize: 12, fontWeight: FontWeight.w700, color: kMoneyGreen),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
    ),

    // ---- 底部导航:白底、无指示器底色、选中橙 ----
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: light ? Colors.white : null,
      elevation: 0,
      height: 64,
      indicatorColor: Colors.transparent,
      iconTheme: WidgetStateProperty.resolveWith((states) => IconThemeData(
          size: 24,
          color: states.contains(WidgetState.selected)
              ? kBrandOrange
              : (light ? const Color(0xFF9A9289) : null))),
      labelTextStyle: WidgetStateProperty.resolveWith((states) => TextStyle(
          fontSize: 11,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w800
              : FontWeight.w600,
          color: states.contains(WidgetState.selected)
              ? kBrandOrange
              : (light ? const Color(0xFF9A9289) : null))),
    ),

    // ---- TabBar 与分段控件 ----
    tabBarTheme: TabBarThemeData(
      labelColor: light ? kInk : null,
      unselectedLabelColor: const Color(0xFF877E75),
      indicatorColor: kBrandOrange,
      indicatorSize: TabBarIndicatorSize.label,
      labelStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800),
      dividerColor: Colors.transparent,
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        selectedBackgroundColor: Colors.white,
        selectedForegroundColor: kInk,
        backgroundColor: const Color(0xFFECE8E3),
        foregroundColor: const Color(0xFF877E75),
        side: BorderSide.none,
        shape: const StadiumBorder(),
        textStyle: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700),
      ),
    ),

    // ---- 弹层与反馈 ----
    dialogTheme: DialogThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      backgroundColor: light ? Colors.white : null,
      titleTextStyle: TextStyle(
          fontSize: 17, fontWeight: FontWeight.w800, color: light ? kInk : null),
    ),
    bottomSheetTheme: const BottomSheetThemeData(
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      showDragHandle: true,
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      backgroundColor: kInk,
      contentTextStyle: const TextStyle(fontSize: 14, color: Colors.white),
    ),

    // ---- 分割线:淡化为暖线——页面靠留白分组,卡内分行尽量用间距 ----
    dividerTheme: DividerThemeData(
        color: light ? kLine : null, thickness: 1, space: 1),
    listTileTheme: ListTileThemeData(
      contentPadding: const EdgeInsets.symmetric(horizontal: 16),
      titleTextStyle: TextStyle(
          fontSize: 15,
          fontWeight: FontWeight.w800,
          color: light ? kInk : null),
      subtitleTextStyle: TextStyle(fontSize: 13, color: light ? kGray : null),
    ),
  );
}

/// 承诺卡:品牌渐变在 App 内唯一允许出现的组件(除 Logo 外)。
/// 三端各放一张:用户端订单详情 / 商家端对账页尾 / 骑手端钱包页。
class PledgeCard extends StatelessWidget {
  const PledgeCard({super.key, required this.title, required this.body});
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 15, 16, 15),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(14),
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFFFF7A45), Color(0xFFE1251B)],
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: const TextStyle(
                  color: Colors.white,
                  fontSize: 14.5,
                  fontWeight: FontWeight.w900)),
          const SizedBox(height: 5),
          Text(body,
              style: TextStyle(
                  color: Colors.white.withValues(alpha: .95),
                  fontSize: 12,
                  height: 1.7)),
        ],
      ),
    );
  }
}

/// 绿色大数卡:今日实收 / 可提现余额 / 今日战报——三端最认的一屏。
class MoneyHeroCard extends StatelessWidget {
  const MoneyHeroCard({
    super.key,
    required this.label,
    required this.amountCents,
    this.subtitle,
    this.action,
  });
  final String label;
  final int amountCents;
  final String? subtitle;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final yuan = (amountCents / 100).toStringAsFixed(2);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: kMoneyGreen,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label,
              style: TextStyle(
                  color: Colors.white.withValues(alpha: .9), fontSize: 13)),
          const SizedBox(height: 4),
          Text('¥$yuan',
              style: const TextStyle(
                color: Colors.white,
                fontSize: 34,
                fontWeight: FontWeight.w900,
                fontFeatures: [FontFeature.tabularFigures()],
              )),
          if (subtitle != null || action != null) ...[
            const SizedBox(height: 10),
            Row(children: [
              if (subtitle != null)
                Expanded(
                    child: Text(subtitle!,
                        style: TextStyle(
                            color: Colors.white.withValues(alpha: .9),
                            fontSize: 11.5))),
              if (action != null) action!,
            ]),
          ],
        ],
      ),
    );
  }
}

/// 矢量 Logo(点赞大拇指,橙红渐变底),几何参数与
/// marketing/brand/icon_A.svg(viewBox 512)及 scripts/gen_brand_assets.py 一致。
class BrandLogo extends StatelessWidget {
  const BrandLogo({
    super.key,
    this.size = 64,
    this.radiusRatio = 116 / 512,
  });

  final double size;
  final double radiusRatio;

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      size: Size.square(size),
      painter: _LogoPainter(radiusRatio),
    );
  }
}

class _LogoPainter extends CustomPainter {
  _LogoPainter(this.radiusRatio);

  final double radiusRatio;

  static const _gradFrom = Color(0xFFFF7A45);
  static const _gradTo = Color(0xFFE1251B);
  static const _yellow = Color(0xFFFFD34D);

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width;
    double u(double v) => v / 512 * s; // SVG viewBox 512 坐标 → 画布

    // 渐变圆角底(左上→右下,与 SVG 同向)
    final rect = Offset.zero & size;
    canvas.drawRRect(
      RRect.fromRectAndRadius(rect, Radius.circular(s * radiusRatio)),
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [_gradFrom, _gradTo],
        ).createShader(rect),
    );

    RRect rr(double x, double y, double w, double h, double r) =>
        RRect.fromRectAndRadius(
            Rect.fromLTWH(u(x), u(y), u(w), u(h)), Radius.circular(u(r)));

    // 大拇指:圆头粗描边曲线(width 68)
    final thumb = Path()
      ..moveTo(u(244), u(300))
      ..cubicTo(u(239), u(258), u(237), u(234), u(233), u(212))
      ..cubicTo(u(229), u(190), u(224), u(174), u(215), u(154));
    canvas.drawPath(
      thumb,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = u(68)
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );

    canvas.drawRRect(rr(108, 246, 64, 168, 22),
        Paint()..color = _yellow); // 黄条(袖口)
    canvas.drawRRect(rr(190, 246, 204, 168, 36),
        Paint()..color = Colors.white); // 手掌
    // 三条纹(账本线):同一渐变色
    final barPaint = Paint()
      ..shader = const LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [_gradFrom, _gradTo],
      ).createShader(rect);
    for (final y in [288.0, 326.0, 364.0]) {
      canvas.drawRRect(rr(262, y, 106, 14, 7), barPaint);
    }
  }

  @override
  bool shouldRepaint(covariant _LogoPainter old) =>
      old.radiusRatio != radiusRatio;
}
