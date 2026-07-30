/// Super-Z 品牌体系:设计令牌 + 主题 + 矢量 Logo。
///
/// 数值规范见 docs/DEV-PROMPTS-8.md 的「设计基线」——那里是唯一来源,
/// 本文件是它的代码实现。核心原则:
///  - 底色是骨白(paper)不是纯白,卡片(surface)才浮得起来
///  - 黏土橘(clay)是行动色:一屏只有一个 clay 实底按钮,其余描边或纯文字
///  - 钱的语义色独立于强调色:到手的钱 earn、平台留存 hold,不得互相顶替
///  - 数字与拉丁字母走衬线(SzSerif),中文回落系统字
library;

import 'package:flutter/material.dart';

/// 三端设计令牌。取法:`Theme.of(context).sz`(见 [SzColorsX])。
///
/// 页面代码里不许再出现裸 `Color(0xFF...)`——加新颜色先往这里加令牌。
@immutable
class SzColors extends ThemeExtension<SzColors> {
  const SzColors({
    required this.paper,
    required this.surface,
    required this.surfaceAlt,
    required this.ink,
    required this.inkMuted,
    required this.inkFaint,
    required this.line,
    required this.clay,
    required this.claySoft,
    required this.earn,
    required this.hold,
    required this.danger,
    required this.channelTones,
  });

  /// 页面底色(骨白,不是纯白——纯白久看刺眼)
  final Color paper;

  /// 卡片底色
  final Color surface;

  /// 次级块:进度槽、缩略图占位、分类侧栏
  final Color surfaceAlt;

  /// 主文字
  final Color ink;

  /// 次要文字
  final Color inkMuted;

  /// 弱化文字:分段标题、占位符
  final Color inkFaint;

  /// 发丝线:卡片描边、列表分隔
  final Color line;

  /// 强调色:主按钮、选中态、可点链接。一屏只用一次实底
  final Color clay;

  /// 强调淡底:承诺条、头像底、当前节点光晕
  final Color claySoft;

  /// 语义色——到手的钱:商家实收 / 骑手所得 / 优惠减项
  final Color earn;

  /// 语义色——平台留存:佣金、服务费
  final Color hold;

  /// 语义色——错误。只给报错用,状态一律用 chip 表达
  final Color danger;

  /// 频道色槽(#132)。**受限色板,不许自由取色** ——
  /// 聚合平台变成彩虹糖,就是从"这个频道想要个亮蓝"开始的。
  /// 新频道按顺序领槽位;槽位用尽再讨论扩板,那时至少是一次有意识的决定。
  ///
  /// 与骨白+黏土同调:全部低饱和暖色,谁也不抢平台色的戏。
  /// **平台色 clay 不在此列** —— 它属于平台身份与主 CTA,不属于任何频道。
  final List<Color> channelTones;

  static const light = SzColors(
    paper: Color(0xFFF0EEE6),
    surface: Color(0xFFFBFAF6),
    surfaceAlt: Color(0xFFF5F3EC),
    ink: Color(0xFF141413),
    inkMuted: Color(0xFF6B6862),
    inkFaint: Color(0xFF9A968C),
    line: Color(0xFFE2DED2),
    clay: Color(0xFFC15F3C),
    claySoft: Color(0xFFEFDDD3),
    earn: Color(0xFF4E6B4F),
    hold: Color(0xFFA6763E),
    danger: Color(0xFFD03030),
    channelTones: [
      Color(0xFFB4553B),   // 0 赤陶 —— 外卖
      Color(0xFF4E6B4F),   // 1 苔绿 —— 住宿
      Color(0xFFA6763E),   // 2 琥珀 —— 团购
      Color(0xFF4A6670),   // 3 青灰 —— 出行(打车)
      Color(0xFF6B5B7B),   // 4 藕紫
      Color(0xFF7A6248),   // 5 胡桃
      Color(0xFF3F6B63),   // 6 松石
      Color(0xFF8A5A5A),   // 7 陶红
    ],
  );

  static const dark = SzColors(
    paper: Color(0xFF1B1A17),
    surface: Color(0xFF24231F),
    surfaceAlt: Color(0xFF2C2A25),
    ink: Color(0xFFF2F0E8),
    inkMuted: Color(0xFFA8A49A),
    inkFaint: Color(0xFF7A766D),
    line: Color(0xFF37342D),
    clay: Color(0xFFE08A6B),
    claySoft: Color(0xFF3A2C25),
    earn: Color(0xFF8FB08D),
    hold: Color(0xFFD2A86C),
    danger: Color(0xFFE06B6B),
    channelTones: [
      Color(0xFFD98567),   // 0 赤陶
      Color(0xFF8FB08D),   // 1 苔绿
      Color(0xFFD2A86C),   // 2 琥珀
      Color(0xFF8FAAB4),   // 3 青灰
      Color(0xFFAE9BBE),   // 4 藕紫
      Color(0xFFC0A684),   // 5 胡桃
      Color(0xFF7FB0A6),   // 6 松石
      Color(0xFFCC9494),   // 7 陶红
    ],
  );

  @override
  SzColors copyWith({
    Color? paper,
    Color? surface,
    Color? surfaceAlt,
    Color? ink,
    Color? inkMuted,
    Color? inkFaint,
    Color? line,
    Color? clay,
    Color? claySoft,
    Color? earn,
    Color? hold,
    Color? danger,
    List<Color>? channelTones,
  }) =>
      SzColors(
        paper: paper ?? this.paper,
        surface: surface ?? this.surface,
        surfaceAlt: surfaceAlt ?? this.surfaceAlt,
        ink: ink ?? this.ink,
        inkMuted: inkMuted ?? this.inkMuted,
        inkFaint: inkFaint ?? this.inkFaint,
        line: line ?? this.line,
        clay: clay ?? this.clay,
        claySoft: claySoft ?? this.claySoft,
        earn: earn ?? this.earn,
        hold: hold ?? this.hold,
        danger: danger ?? this.danger,
        channelTones: channelTones ?? this.channelTones,
      );

  @override
  SzColors lerp(covariant SzColors? other, double t) {
    if (other == null) return this;
    Color c(Color a, Color b) => Color.lerp(a, b, t)!;
    return SzColors(
      paper: c(paper, other.paper),
      surface: c(surface, other.surface),
      surfaceAlt: c(surfaceAlt, other.surfaceAlt),
      ink: c(ink, other.ink),
      inkMuted: c(inkMuted, other.inkMuted),
      inkFaint: c(inkFaint, other.inkFaint),
      line: c(line, other.line),
      clay: c(clay, other.clay),
      claySoft: c(claySoft, other.claySoft),
      earn: c(earn, other.earn),
      hold: c(hold, other.hold),
      danger: c(danger, other.danger),
      // 逐槽插值:深浅切换时频道色跟着一起过渡,不会闪一下
      channelTones: [
        for (var i = 0; i < channelTones.length; i++)
          c(channelTones[i],
            i < other.channelTones.length ? other.channelTones[i]
                                          : channelTones[i]),
      ],
    );
  }
}

/// `Theme.of(context).sz` 取令牌;主题里没挂扩展时回落浅色,不抛异常。
extension SzColorsX on ThemeData {
  SzColors get sz => extension<SzColors>() ?? SzColors.light;
}

/// 圆角:8 小(缩略图/chip 内、按钮)、12 卡片、18 大卡。
/// 按钮用 8 的圆角矩形而不是全胶囊——claude.ai 的按钮是圆角矩形,
/// 胶囊是上一版留下的,和这套观感对不上。chip 仍是胶囊(那是标签不是按钮)。
const double kRadiusSm = 8;
const double kRadiusMd = 12;
const double kRadiusLg = 18;

/// 页面左右留白与卡片内边距(间距一律取 4 的倍数)。
const double kPagePad = 18;
const double kCardPad = 14;

/// 衬线字族(Literata 子集):金额、评分、距离等数字。
/// 选它是因为 Literata 与 claude.ai 大标题用的 Galaxie Copernicus 同属
/// Plantin 一脉的过渡期衬线;Copernicus 本身是商用授权,打不进开源仓。
const String kSerifFamily = 'SzSerif';

/// 无衬线字族(Space Grotesk 子集):界面里的拉丁词与英文。
/// claude.ai 正文用的 Styrene B 是商用授权,Space Grotesk 是它公认最接近的
/// OFL 替代。中文一律回落系统字——这两款都不含 CJK。
const String kSansFamily = 'SzSans';

const List<String> _cjkFallback = ['PingFang SC', 'Noto Sans CJK SC', 'Heiti SC'];

/// 正文里的数字:评分、月售、距离、单量。旧式数字(onum),混排更贴合文字。
///
/// 中文不会被这个样式带成宋体——SzSerif 子集里没有 CJK 字形,
/// 系统会自动回落到 [_cjkFallback]。
TextStyle szFigure({
  double? fontSize,
  FontWeight? fontWeight,
  Color? color,
  double? height,
}) =>
    TextStyle(
      fontFamily: kSerifFamily,
      fontFamilyFallback: _cjkFallback,
      fontSize: fontSize,
      fontWeight: fontWeight,
      color: color,
      height: height,
      fontFeatures: const [FontFeature.oldstyleFigures()],
    );

/// 需要竖排对齐的金额:费用明细、对账列表。等宽 + 现代数字(tnum + lnum)。
TextStyle szMoney({
  double fontSize = 15,
  FontWeight fontWeight = FontWeight.w600,
  Color? color,
  double? height,
}) =>
    TextStyle(
      fontFamily: kSerifFamily,
      fontFamilyFallback: _cjkFallback,
      fontSize: fontSize,
      fontWeight: fontWeight,
      color: color,
      height: height,
      fontFeatures: const [
        FontFeature.tabularFigures(),
        FontFeature.liningFigures(),
      ],
    );

/// 缺图占位的底色/字色对。
///
/// 不是彩虹色板——六组都在骨白纸底的同一色域里(泥土色系低饱和),
/// 列表里十家店排下来是"有层次"而不是"花"。按名称哈希取,
/// 同一家店每次进都是同一个色,用户能靠颜色认店。
class SzTone {
  const SzTone(this.bg, this.fg);
  final Color bg;
  final Color fg;
}

const List<SzTone> _tonesLight = [
  SzTone(Color(0xFFE9DCD2), Color(0xFF8C5B41)), // 黏土
  SzTone(Color(0xFFDDE3DA), Color(0xFF4E6B4F)), // 苔绿
  SzTone(Color(0xFFEBE1CD), Color(0xFF8A6B34)), // 麦黄
  SzTone(Color(0xFFE4E1D9), Color(0xFF6B6862)), // 中性
  SzTone(Color(0xFFE9DDD9), Color(0xFF8A5A55)), // 陶土
  SzTone(Color(0xFFDCE1E3), Color(0xFF566368)), // 青灰
];

const List<SzTone> _tonesDark = [
  SzTone(Color(0xFF3A2C25), Color(0xFFD9A184)),
  SzTone(Color(0xFF2A322A), Color(0xFF8FB08D)),
  SzTone(Color(0xFF383026), Color(0xFFD2A86C)),
  SzTone(Color(0xFF302E29), Color(0xFFA8A49A)),
  SzTone(Color(0xFF362A28), Color(0xFFC79490)),
  SzTone(Color(0xFF2A3033), Color(0xFF93A3A9)),
];

/// 按 seed 取一组占位色。seed 用店名/菜名——同名同色,与数据库 id 无关,
/// 这样演示数据和生产数据的观感一致。
SzTone szToneOf(String seed, {bool dark = false}) {
  var h = 0;
  for (final c in seed.codeUnits) {
    h = (h * 31 + c) & 0x7fffffff;
  }
  final list = dark ? _tonesDark : _tonesLight;
  return list[h % list.length];
}

/// 从名称取占位用的字:中文取第一个字,拉丁取前两个字母。
/// 「运营测试店-1784465885」这种带编号的名字只取「运」,不带数字。
String szInitialOf(String name) {
  final t = name.trim();
  if (t.isEmpty) return '·';
  final first = t.characters.first;
  // 拉丁开头的名字给两个字母更容易区分(如 KFC / MC)
  if (first.codeUnitAt(0) < 128 && RegExp(r'[A-Za-z]').hasMatch(first)) {
    final letters = t.replaceAll(RegExp(r'[^A-Za-z]'), '');
    return letters.substring(0, letters.length >= 2 ? 2 : 1).toUpperCase();
  }
  return first;
}

// ---- 旧令牌:@Deprecated 别名,随第八辑 103–110 逐屏清理 ----
// 值已指向新令牌最接近项,所以旧引用的观感立刻跟上;不要全局 sed 替换,
// 那样没法逐屏验收(见 docs/DEV-PROMPTS-8.md 拍板)。

@Deprecated('用 Theme.of(context).sz.clay')
const Color kBrandOrange = Color(0xFFC15F3C);

@Deprecated('用 Theme.of(context).sz.earn')
const Color kMoneyGreen = Color(0xFF4E6B4F);

@Deprecated('用 Theme.of(context).sz.hold')
const Color kPromoAmber = Color(0xFFA6763E);

@Deprecated('用 Theme.of(context).sz.ink')
const Color kInk = Color(0xFF141413);

@Deprecated('用 Theme.of(context).sz.inkMuted')
const Color kGray = Color(0xFF6B6862);

@Deprecated('用 Theme.of(context).sz.line')
const Color kLine = Color(0xFFE2DED2);

@Deprecated('用 Theme.of(context).sz.paper')
const Color kWarmBg = Color(0xFFF0EEE6);

@Deprecated('用 Theme.of(context).sz.surfaceAlt')
const Color kInputFill = Color(0xFFF5F3EC);

@Deprecated('用 Theme.of(context).sz.claySoft 或 surfaceAlt')
const Color kGreenBg = Color(0xFFEAEDE8);

@Deprecated('用 Theme.of(context).sz.claySoft')
const Color kAmberBg = Color(0xFFEFDDD3);

/// 金额文本样式(旧)。新代码用 [szMoney]。
///
/// 默认色保持"到手的钱"语义,与旧版行为一致——迁移时改成
/// `szMoney(color: Theme.of(context).sz.earn)`,深色模式才跟得上。
@Deprecated('用 szMoney(fontSize: ..., color: Theme.of(context).sz.earn)')
TextStyle kMoneyText(double size, {Color color = _kEarnFallback}) =>
    szMoney(fontSize: size, fontWeight: FontWeight.w700, color: color);

/// 仅供 [kMoneyText] 的默认值使用(默认值必须是编译期常量)。
const Color _kEarnFallback = Color(0xFF4E6B4F);

/// 三端统一的品牌主题 v3(第八辑视觉重构)。
///
/// 数值来源:docs/DEV-PROMPTS-8.md「设计基线」。七条规则:
///  1. 一屏只有一个 clay 实底按钮(FilledButton),其余 Outlined/Text
///  2. 钱的语义色独立:到手的钱 earn、平台留存 hold,不与 clay 混用
///  3. 状态用 chip 表达,红色(danger)只留给报错
///  4. 卡片靠 1px 描边分层,不用阴影;列表靠留白分组,不用满屏 Divider
///  5. AppBar 与背景同色、无阴影、左对齐,标题不再是超大号
///  6. 页面底色是骨白(paper),卡片(surface)比它亮一档才浮得起来
///  7. 数字与拉丁字母走 SzSerif,中文回落系统字(见 szFigure/szMoney)
ThemeData brandTheme(Brightness brightness) {
  final light = brightness == Brightness.light;
  final sz = light ? SzColors.light : SzColors.dark;

  // M3 的 tone 映射会把黏土橘压暗;主行动色钉死为 clay,
  // 其余层次仍由 seed 派生,保持体系和谐
  final seeded = ColorScheme.fromSeed(
    seedColor: sz.clay,
    brightness: brightness,
  );
  final scheme = seeded.copyWith(
    primary: sz.clay,
    onPrimary: light ? const Color(0xFFFBFAF6) : const Color(0xFF1B1A17),
    surface: sz.surface,
    onSurface: sz.ink,
    surfaceContainerHighest: sz.surfaceAlt,
    // 存量代码里 colorScheme.outline 有 51 处当"次要文字色"在用,
    // 映射成发丝线色会让那些文字直接看不见 —— 所以 outline 给 inkMuted,
    // 真正的线走 outlineVariant / dividerTheme / sz.line
    outline: sz.inkMuted,
    outlineVariant: sz.line,
    error: sz.danger,
  );

  final baseText = Typography.material2021(platform: TargetPlatform.android)
      .black
      .apply(bodyColor: sz.ink, displayColor: sz.ink);

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    // 拉丁走 SzSans,中文回落系统字。只影响 km / CSV / T+1 这类词,
    // 中文观感不变(子集里没有 CJK,渲染时系统自动接管)
    fontFamily: kSansFamily,
    fontFamilyFallback: _cjkFallback,
    scaffoldBackgroundColor: sz.paper,
    canvasColor: sz.paper,
    // 涟漪比 InkSparkle 安静,和这套克制的观感匹配
    splashFactory: InkRipple.splashFactory,
    extensions: <ThemeExtension<dynamic>>[sz],

    // ---- 字阶:26 页面大标题、21 卡标题、15 正文、13 辅助、11 分段标题 ----
    // 中文不做字距,字重比旧版整体轻一档(w900 在中文里糊成一团)
    textTheme: baseText.copyWith(
      headlineSmall: TextStyle(
          fontSize: 26, fontWeight: FontWeight.w600, height: 1.3, color: sz.ink),
      titleLarge: TextStyle(
          fontSize: 21, fontWeight: FontWeight.w600, height: 1.35, color: sz.ink),
      titleMedium: TextStyle(
          fontSize: 17, fontWeight: FontWeight.w600, height: 1.35, color: sz.ink),
      titleSmall: TextStyle(
          fontSize: 14.5, fontWeight: FontWeight.w600, color: sz.ink),
      bodyMedium: TextStyle(fontSize: 15, height: 1.6, color: sz.ink),
      bodySmall: TextStyle(fontSize: 12.5, color: sz.inkMuted, height: 1.55),
      labelSmall: TextStyle(fontSize: 11, color: sz.inkFaint),
    ),

    // ---- AppBar:与背景同色、无阴影、左对齐 ----
    appBarTheme: AppBarTheme(
      backgroundColor: sz.paper,
      foregroundColor: sz.ink,
      surfaceTintColor: Colors.transparent,
      scrolledUnderElevation: 0,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
          fontSize: 16.5, fontWeight: FontWeight.w600, color: sz.ink),
    ),

    // ---- 卡片:surface 底、圆角 12、1px 描边、零阴影、零边距 ----
    cardTheme: CardThemeData(
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        side: BorderSide(color: sz.line),
      ),
      color: sz.surface,
      margin: EdgeInsets.zero,
    ),

    // ---- 按钮:胶囊形;Filled=clay 主按钮(一屏一个),Outlined=次,Text=弱 ----
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: sz.clay,
        foregroundColor: scheme.onPrimary,
        minimumSize: const Size(64, 48),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(kRadiusSm)),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        elevation: 0,
        backgroundColor: sz.clay,
        foregroundColor: scheme.onPrimary,
        minimumSize: const Size(64, 48),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(kRadiusSm)),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
    ),
    // 次按钮是墨字 + 发丝描边,不再是橙字橙框——一屏只让主按钮抢眼
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: sz.ink,
        side: BorderSide(color: sz.line),
        minimumSize: const Size(64, 44),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(kRadiusSm)),
        textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: sz.clay,
        textStyle: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
      ),
    ),

    // ---- 输入框:次级块填充、圆角 12、无边框线 ----
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: sz.surfaceAlt,
      hintStyle: TextStyle(color: sz.inkFaint, fontSize: 14.5),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 13),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        borderSide: BorderSide.none,
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        borderSide: BorderSide(color: sz.line),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(kRadiusMd),
        borderSide: BorderSide(color: sz.clay, width: 1.5),
      ),
    ),

    // ---- chip:描边胶囊、墨字;语义色在调用处给(见 SzChip) ----
    chipTheme: ChipThemeData(
      shape: const StadiumBorder(),
      side: BorderSide(color: sz.line),
      backgroundColor: sz.surface,
      selectedColor: sz.ink,
      labelStyle: TextStyle(
          fontSize: 12.5, fontWeight: FontWeight.w500, color: sz.ink),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
    ),

    // ---- 底部导航:卡片底、无指示器底色、选中 clay ----
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: sz.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      height: 62,
      indicatorColor: Colors.transparent,
      iconTheme: WidgetStateProperty.resolveWith((states) => IconThemeData(
          size: 23,
          color: states.contains(WidgetState.selected) ? sz.clay : sz.inkFaint)),
      labelTextStyle: WidgetStateProperty.resolveWith((states) => TextStyle(
          fontSize: 10.5,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w600
              : FontWeight.w500,
          color: states.contains(WidgetState.selected) ? sz.clay : sz.inkFaint)),
    ),

    // ---- TabBar 与分段控件 ----
    tabBarTheme: TabBarThemeData(
      labelColor: sz.ink,
      unselectedLabelColor: sz.inkFaint,
      indicatorColor: sz.clay,
      indicatorSize: TabBarIndicatorSize.label,
      labelStyle: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w600),
      unselectedLabelStyle:
          const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w500),
      dividerColor: Colors.transparent,
    ),
    segmentedButtonTheme: SegmentedButtonThemeData(
      style: SegmentedButton.styleFrom(
        selectedBackgroundColor: sz.surface,
        selectedForegroundColor: sz.ink,
        backgroundColor: sz.surfaceAlt,
        foregroundColor: sz.inkMuted,
        side: BorderSide(color: sz.line),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(kRadiusSm)),
        textStyle: const TextStyle(fontSize: 13, fontWeight: FontWeight.w500),
      ),
    ),

    // ---- 弹层与反馈 ----
    dialogTheme: DialogThemeData(
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(kRadiusLg)),
      backgroundColor: sz.surface,
      surfaceTintColor: Colors.transparent,
      titleTextStyle: TextStyle(
          fontSize: 16.5, fontWeight: FontWeight.w600, color: sz.ink),
      contentTextStyle:
          TextStyle(fontSize: 14, height: 1.6, color: sz.inkMuted),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: sz.surface,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(kRadiusLg))),
      showDragHandle: true,
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape:
          RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      backgroundColor: sz.ink,
      contentTextStyle: TextStyle(fontSize: 13.5, color: sz.paper),
    ),

    // ---- 分割线与列表 ----
    dividerTheme:
        DividerThemeData(color: sz.line, thickness: 1, space: 1),
    listTileTheme: ListTileThemeData(
      contentPadding: const EdgeInsets.symmetric(horizontal: kPagePad),
      titleTextStyle: TextStyle(
          fontSize: 14.5, fontWeight: FontWeight.w500, color: sz.ink),
      subtitleTextStyle: TextStyle(fontSize: 12.5, color: sz.inkMuted),
      iconColor: sz.inkFaint,
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith((s) =>
          s.contains(WidgetState.selected) ? scheme.onPrimary : sz.surface),
      trackColor: WidgetStateProperty.resolveWith(
          (s) => s.contains(WidgetState.selected) ? sz.clay : sz.surfaceAlt),
      trackOutlineColor: WidgetStatePropertyAll(sz.line),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: sz.clay,
      linearTrackColor: sz.surfaceAlt,
      circularTrackColor: sz.surfaceAlt,
    ),
    iconTheme: IconThemeData(color: sz.inkMuted, size: 20),
  );
}

/// 承诺卡:平台主张(5% 封顶 / 配送费全归骑手)。
/// 三端各放一张:用户端订单详情 / 商家端对账页尾 / 骑手端钱包页。
///
/// v3 起改为 claySoft 淡底——渐变实底在骨白页面上过于抢眼,
/// 而承诺是背景信息不是行动点。全屏的 claySoft 只允许出现这一处。
class PledgeCard extends StatelessWidget {
  const PledgeCard({super.key, required this.title, required this.body});
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final sz = Theme.of(context).sz;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(kCardPad, 13, kCardPad, 13),
      decoration: BoxDecoration(
        color: sz.claySoft,
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: TextStyle(
                  color: sz.ink,
                  fontSize: 14,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 4),
          Text(body,
              style: TextStyle(color: sz.inkMuted, fontSize: 12, height: 1.65)),
        ],
      ),
    );
  }
}

/// 大数卡:今日实收 / 可提现余额 / 今日战报——三端最认的一屏。
///
/// v3 起改为卡片底 + earn 色衬线大数:绿色实底会把整屏的视觉重心
/// 从"这是多少钱"移到"这是一块绿色",数字本身才是主角。
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
    final sz = Theme.of(context).sz;
    final yuan = (amountCents / 100).toStringAsFixed(2);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: sz.surface,
        border: Border.all(color: sz.line),
        borderRadius: BorderRadius.circular(kRadiusMd),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: TextStyle(color: sz.inkMuted, fontSize: 12.5)),
          const SizedBox(height: 4),
          Text('¥$yuan',
              style: szMoney(
                  fontSize: 32, fontWeight: FontWeight.w600, color: sz.earn)),
          if (subtitle != null || action != null) ...[
            const SizedBox(height: 10),
            Row(children: [
              if (subtitle != null)
                Expanded(
                    child: Text(subtitle!,
                        style: TextStyle(color: sz.inkMuted, fontSize: 11.5))),
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

/// 相对时间:近的说"多久前",远的给日期。
///
/// 订单列表原先全是 `7/27 17:21` 这种绝对时间——"这是刚下的单还是昨天的"
/// 要用户自己在脑子里算。外卖是分钟级的生意,几分钟前和几小时前的语义完全不同。
///
/// 分档:1 分钟内「刚刚」、1 小时内「N 分钟前」、当天「N 小时前」、
/// 昨天「昨天 HH:MM」、今年「M/D HH:MM」、跨年带上年份。
/// [iso] 是服务端的 UTC 时间戳,内部转本地时区再比。
String szTimeAgo(String iso) {
  final t = DateTime.tryParse(iso)?.toLocal();
  if (t == null) return '';
  final now = DateTime.now();
  final diff = now.difference(t);
  String two(int n) => n.toString().padLeft(2, '0');

  // 未来时间(预约单/时钟不准):不说"负 N 分钟前",直接给时刻
  if (diff.isNegative) return '${t.month}/${t.day} ${two(t.hour)}:${two(t.minute)}';
  if (diff.inMinutes < 1) return '刚刚';
  if (diff.inMinutes < 60) return '${diff.inMinutes} 分钟前';

  final today = DateTime(now.year, now.month, now.day);
  final that = DateTime(t.year, t.month, t.day);
  if (that == today) return '${diff.inHours} 小时前';
  if (that == today.subtract(const Duration(days: 1))) {
    return '昨天 ${two(t.hour)}:${two(t.minute)}';
  }
  if (t.year == now.year) {
    return '${t.month}/${t.day} ${two(t.hour)}:${two(t.minute)}';
  }
  return '${t.year}/${t.month}/${t.day}';
}
