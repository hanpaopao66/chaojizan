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
    required this.ledger,
    required this.link,
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

  /// **只给装饰用**:图标、进度圈、淡底、分隔性元素。
  ///
  /// ⚠️ **不许拿它承载要读的信息。** 它在骨白底上对比度只有 2.54–2.83,
  /// 连 WCAG 大字门槛 3.0 都不到,更不用说正文的 4.5 ——
  /// 而这个 App 有长辈版大字模式,用户里老年人不少。
  ///
  /// 曾经有 146 处用它写正文:券包里"满50可用"的门槛、11.5px 的说明、
  /// 底部导航的标签、输入框占位符。看着"淡雅",实际是看不清。
  /// 现在这些一律改用 [inkMuted](骨白底上 5.32,过 AA)。
  ///
  /// 判断标准很简单:**这行字/这个元素,用户需要读懂它吗?**
  /// 需要 → inkMuted;只是让界面不空、或者旁边已有文字说明 → inkFaint。
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

  /// 账目表面(#133):「钱去哪了」「平台账本」这类**可查账**的地方专用。
  ///
  /// 账目透明是唯一抄不走的差异点,却和普通卡片长得一样 —— 用一张更"硬"的
  /// 深色台面把它从页面里托出来,让"这块是账"在视觉上先于文字被读到。
  ///
  /// **深浅两态用的是不同手法**:浅色页面上它是深色台面(反差);
  /// 深色页面上它比页底更深(下沉的井)。只做一种的话,深色模式下就糊没了。
  final Color ledger;

  /// **可跳转链接**专用蓝(#136)。整套里唯一的蓝,只给"点了会离开当前页"的字:
  /// 协议/政策入口、协议全文里的第三方隐私政策网址。
  ///
  /// 为什么破例引入一个蓝:`clay` 是**行动色**,用户读作"这是本产品的按钮";
  /// 而协议链接要传达的是"这是一条通向别处的链接",中文 App 里这个信号就是蓝色。
  /// 拿橘色标链接,用户只会当成一句被强调的话,不会想到能点 —— 应用商店审核
  /// 恰恰要求第三方协议**可点可达**。
  ///
  /// **不许**拿它当强调色、当第二主色、当按钮底色。出现范围仅限上述两处。
  /// 取值也不是随手挑的:常见的 `#1677FF` 在骨白底上对比度只有 3.53,过不了 AA;
  /// 这里的浅色态 5.84、深色态 7.68(实测)。
  final Color link;

  /// 频道色槽(#132)。**受限色板,不许自由取色** ——
  /// 聚合平台变成彩虹糖,就是从"这个频道想要个亮蓝"开始的。
  /// 新频道按顺序领槽位;槽位用尽再讨论扩板,那时至少是一次有意识的决定。
  ///
  /// **平台色 clay 不在此列** —— 它属于平台身份与主 CTA,不属于任何频道。
  ///
  /// ## 这组值是解出来的,不是挑出来的(#289)
  ///
  /// 旧的一组是照"低饱和暖色"的感觉配的,量出来才发现不成立:
  ///
  /// - 八个色挤在明度 41–53、平均彩度只有 25,已上线四个里
  ///   「住宿↔帮我送」ΔE 23.2、「外卖↔团购」ΔE 25.0 —— 40px 的图标上分不开;
  /// - 5 号槽(色相 72.6°)和团购(71.3°)基本同色,**下一个频道领到就撞**;
  /// - 更糟的是 [1] 和 [earn] 是同一个值、[2] 和 [hold] 是同一个值 ——
  ///   住宿的频道标跟"到账金额"一个颜色,团购的跟"被抽走"一个颜色。
  ///
  /// 新的一组在 CIE LCh 里按约束求解:字画在自身 12% 淡底上对比度 ≥4.5,
  /// 明度贴着 clay 上下浮动、彩度不超过它太多(风格闸门,不然会解出粉彩和亮青),
  /// 目标是**四种色觉下最差的那个色差最大化**。
  ///
  /// ## ⚠️ 颜色分不了八个频道 —— 这是硬事实,不是调参没调好
  ///
  /// 求解时把红/绿/蓝色盲当硬约束一起算,结果很清楚:
  ///
  /// | 频道数 | 正常视觉最差 ΔE | 色觉缺陷下最差 ΔE |
  /// |---|---|---|
  /// | 旧色板(4 个) | 23.2 | **4.0** |
  /// | 新色板(5 个) | 30.6 | 12.9 |
  /// | 新色板(8 个) | — | **8.7** |
  ///
  /// 五个频道能做到 12.9(旧的 4.0),八个就掉回 8.7。也就是说
  /// **频道一多,颜色这条路就走到头了**,再怎么配都没用。
  ///
  /// 所以频道的主标识是 [SzChannel.glyph] 那个汉字(碗/宿/券/跑/车),
  /// 颜色只是让人找得更快的加速器。**任何时候都不许把字符去掉只留颜色** ——
  /// 那等于对约 8% 的男性用户把频道入口做成了一排一样的方块。
  ///
  /// 复算脚本:`scripts/check_channel_tones.py`(CI 里跑)。
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
    ledger: Color(0xFF1F1E1B),      // 浅色页上的深台面
    link: Color(0xFF2C5F87),        // 链接蓝:骨白底上 5.84,过 AA
    channelTones: [
      // 前五个色相由语义定:食物暖、安睡绿、优惠金、出行蓝、跑腿紫。
      // 明度/彩度由求解器定 —— 见 channelTones 的文档注释。
      Color(0xFF943F2F),   // 0 砖红 —— 外卖  L38 C44 H38°
      Color(0xFF4E7054),   // 1 苔绿 —— 住宿  L44 C22 H148°
      Color(0xFF88611C),   // 2 赭金 —— 团购  L44 C44 H78°
      Color(0xFF2B5F7A),   // 3 靛青 —— 出行(打车) L38 C22 H248°
      Color(0xFF7A59A0),   // 4 藤紫 —— 帮我送 L44 C44 H310°
      // 以下三个是预留槽,色相由机器在色环上搜"离前面最远"的位置。
      // ⚠️ 领用第六个之前先读一遍上面那张表:六个往上,颜色已经分不动了
      Color(0xFF01756C),   // 5 松石
      Color(0xFF29763E),   // 6 竹青
      Color(0xFF944F8D),   // 7 木槿
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
    ledger: Color(0xFF100F0D),      // 比页底(#1B1A17)更深:下沉的井
    link: Color(0xFF7FB2D9),        // 深色态链接蓝:各底色上 6.9~8.5
    channelTones: [
      // 深色态单独解一遍,不是把浅色态提亮:深底上要保住对比度,
      // 明度得整体上移,而明度一变,能达到的色差组合就完全不同了
      Color(0xFFD98573),   // 0 砖红 —— 外卖
      Color(0xFFA2C4A7),   // 1 苔绿 —— 住宿
      Color(0xFFE1B473),   // 2 赭金 —— 团购
      Color(0xFF56C7FF),   // 3 靛青 —— 出行(打车)
      Color(0xFFAA91C4),   // 4 藤紫 —— 帮我送
      Color(0xFF28A79B),   // 5 松石
      Color(0xFFFAA0CC),   // 6 木槿
      Color(0xFFBE9455),   // 7 胡桃
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
    Color? ledger,
    Color? link,
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
        ledger: ledger ?? this.ledger,
        link: link ?? this.link,
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
      ledger: c(ledger, other.ledger),
      link: c(link, other.link),
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

/// 使用密度(#134):三端的使用姿势不一样,不该共用一套尺寸。
///
/// - [SzDensity.browse] 用户端:躺着刷,信息可以密一点、可逛;
/// - [SzDensity.operate] 商家端与骑手端:商家在忙碌的收银台前扫一眼,
///   骑手戴着手套单手操作 —— 点击区要更大、信息要更少。
///
/// **只在主题层生效**,不去改各页面写死的 padding:Flutter 的主题会自动
/// 传播到所有按钮、列表行、输入框,改一处覆盖全部;逐个页面改 44 处
/// 调用点,代价大而且下次新写的页面又会漏。
enum SzDensity {
  browse,
  operate;

  /// 主按钮最小高度。48 是 Material 的基线,戴手套按不准 —— 提到 56
  double get buttonHeight => this == SzDensity.operate ? 56 : 48;

  /// 次按钮最小高度
  double get secondaryHeight => this == SzDensity.operate ? 50 : 44;

  /// 列表行的竖直内边距:操作态松一档,一屏少放两行但不容易点错
  double get listVerticalPad => this == SzDensity.operate ? 10 : 4;

  /// 输入框的竖直内边距**增量**。写成增量而不是绝对值,是为了让浏览态严格等于
  /// 分化之前的老口径 —— 用户端不该因为"给商家端加大"而跟着变样
  double get inputPadBump => this == SzDensity.operate ? 3 : 0;

  /// 正文字号增量:商家端在油烟和光线不好的后厨看,骑手在阳光下看
  double get fontBump => this == SzDensity.operate ? 1.0 : 0;

  /// 图标按钮的点击区
  double get iconButtonSize => this == SzDensity.operate ? 52 : 44;

  /// Material 的全局密度。ListTile / Chip 这类**高度是算出来的**组件
  /// 只认这个,给 minVerticalPadding 撑不开它们的默认行高(实测两态都是 72)
  VisualDensity get visual => this == SzDensity.operate
      ? const VisualDensity(vertical: 1)
      : VisualDensity.standard;
}

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
ThemeData brandTheme(Brightness brightness,
    {SzDensity density = SzDensity.browse}) {
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
      labelSmall: TextStyle(fontSize: 11, color: sz.inkMuted),
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
        minimumSize: Size(64, density.buttonHeight),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(kRadiusSm)),
        textStyle: TextStyle(
            fontSize: 15 + density.fontBump, fontWeight: FontWeight.w600),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        elevation: 0,
        backgroundColor: sz.clay,
        foregroundColor: scheme.onPrimary,
        minimumSize: Size(64, density.buttonHeight),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(kRadiusSm)),
        textStyle: TextStyle(
            fontSize: 15 + density.fontBump, fontWeight: FontWeight.w600),
      ),
    ),
    // 次按钮是墨字 + 发丝描边,不再是橙字橙框——一屏只让主按钮抢眼
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: sz.ink,
        side: BorderSide(color: sz.line),
        minimumSize: Size(64, density.secondaryHeight),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(kRadiusSm)),
        textStyle: TextStyle(
            fontSize: 14 + density.fontBump, fontWeight: FontWeight.w500),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: sz.clay,
        minimumSize: Size(48, density.secondaryHeight),
        textStyle: TextStyle(
            fontSize: 14 + density.fontBump, fontWeight: FontWeight.w500),
      ),
    ),

    visualDensity: density.visual,

    // ---- 图标按钮:默认命中区只有 40,操作态提到 52 ----
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        minimumSize: Size.square(density.iconButtonSize),
      ),
    ),

    // ---- 输入框:次级块填充、圆角 12、无边框线 ----
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: sz.surfaceAlt,
      hintStyle: TextStyle(
          color: sz.inkMuted, fontSize: 14.5 + density.fontBump),
      contentPadding: EdgeInsets.symmetric(
          horizontal: 16, vertical: 13 + density.inputPadBump),
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
    //
    // ⚠️ 文字颜色**必须按状态给**。这里踩过一个真实的坑:
    // `selectedColor: sz.ink` 是选中时的底色,而 labelStyle 写死 `sz.ink`,
    // 于是选中那一刻底色和字色变成同一个颜色 —— 字直接消失。
    // 浅色态是近黑底配近黑字,深色态是近白底配近白字,**两套主题都看不见**。
    //
    // 表现出来就是"点了之后那个选项不见了",而它其实还在,只是隐身了。
    // 三端一共 30 处 Material Chip 走这份主题,全都受影响
    // (自绘的 SzChip 没事,它本来就是 selected ? paper : ink)。
    //
    // WidgetStateColor 能直接塞进 TextStyle.color,按状态解析,
    // 口径与 SzChip 保持一致:选中 = 墨底纸字。
    chipTheme: ChipThemeData(
      shape: const StadiumBorder(),
      side: BorderSide(color: sz.line),
      backgroundColor: sz.surface,
      selectedColor: sz.ink,
      // 勾选标记同理:FilterChip 选中会画一个勾,
      // 墨底上再画墨色的勾一样是隐身
      checkmarkColor: sz.paper,
      labelStyle: TextStyle(
          fontSize: 12.5,
          fontWeight: FontWeight.w500,
          color: WidgetStateColor.resolveWith((states) =>
              states.contains(WidgetState.selected) ? sz.paper : sz.ink)),
      secondaryLabelStyle: TextStyle(
          fontSize: 12.5,
          fontWeight: FontWeight.w500,
          color: WidgetStateColor.resolveWith((states) =>
              states.contains(WidgetState.selected) ? sz.paper : sz.ink)),
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
          color: states.contains(WidgetState.selected) ? sz.clay : sz.inkMuted)),
      labelTextStyle: WidgetStateProperty.resolveWith((states) => TextStyle(
          fontSize: 10.5,
          fontWeight: states.contains(WidgetState.selected)
              ? FontWeight.w600
              : FontWeight.w500,
          color: states.contains(WidgetState.selected) ? sz.clay : sz.inkMuted)),
    ),

    // ---- TabBar 与分段控件 ----
    tabBarTheme: TabBarThemeData(
      labelColor: sz.ink,
      unselectedLabelColor: sz.inkMuted,
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
      minVerticalPadding: density.listVerticalPad,
      titleTextStyle: TextStyle(
          fontSize: 14.5 + density.fontBump,
          fontWeight: FontWeight.w500,
          color: sz.ink),
      subtitleTextStyle:
          TextStyle(fontSize: 12.5 + density.fontBump, color: sz.inkMuted),
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
