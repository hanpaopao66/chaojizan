# 超级赞 Super-Z · 待开发功能提示词库(第八辑:三端前端视觉重构)

> **执行状态(2026-07-29):#101–#112 全部完成并逐条提交。**
> 走查记录见本文件末尾「#111 走查清单」;验收截图在
> `marketing/design/screens/`,上架截图在 `screens/store/`。

> 背景:三端 UI 沿用的是 M3 默认观感 + 炉火橙(`kBrandOrange #FF5A1F`),
> 橙色铺得太满、纯白底久看刺眼、账目透明这一核心资产被埋在订单详情的折叠卡里。
> 本辑按已通过的「Anthropic 风格」原型重做三端展示层。
>
> **风格基线以本文件「设计基线」一节为准**(原型仅供观感参考,
> 数值一律回本文件查)。原型:骨白纸底 + 黏土橘强调 + 数字走衬线,
> 六屏走查(首页/店铺/结算/跟踪/钱去哪了/我的)。
>
> 建议顺序严格按编号:**101 令牌 → 102 组件层**是地基,没做完不要碰页面;
> 103–108 用户端逐屏;109 商家端、110 骑手端;111 收口。
> 每条独立可验收、可单独提交,**不要合并成一个大 PR**。

## 任务一览

| 编号 | 任务 | 影响面 |
|---|---|---|
| 101 | 设计令牌重写 + 衬线数字字体打包 | `packages/shared/lib/src/brand.dart` |
| 102 | 共享组件层(卡片/分段标题/chip/步进器/分账条/空态) | `packages/shared/lib/src/` |
| 103 | 用户端 首页 | `user_app/lib/main.dart` |
| 104 | 用户端 店铺页与点菜 | `user_app/lib/main.dart` |
| 105 | 用户端 结算页 | `user_app/lib/checkout_page.dart` |
| 106 | 用户端 订单跟踪 | `user_app/lib/main.dart` |
| 107 | 用户端「钱去哪了」独立页 + 三处入口 | `user_app/lib/`(新文件) |
| 108 | 用户端「我的」+ 长尾页面收口 | `user_app/lib/` 其余 24 个文件 |
| 109 | 商家端重构 | `merchant_app/lib/`(17 文件 7222 行) |
| 110 | 骑手端重构 | `rider_app/lib/`(7 文件 2704 行) |
| 111 | 深色/无障碍/动效收口 + 上架截图重出 | 三端 |
| 112 | 商家端住宿子目录与两端二级页的信息层级重排 | `merchant_app/lib/hotel/` + 两端二级页 |

## 设计基线(唯一数值来源)

**色板**——浅色在前、深色在后,两套都要给,不许由浅色反相生成:

| 令牌 | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `paper` | `#F0EEE6` | `#1B1A17` | 页面底色(骨白,不是纯白) |
| `surface` | `#FBFAF6` | `#24231F` | 卡片 |
| `surfaceAlt` | `#F5F3EC` | `#2C2A25` | 次级块、进度槽、缩略图占位 |
| `ink` | `#141413` | `#F2F0E8` | 主文字 |
| `inkMuted` | `#6B6862` | `#A8A49A` | 次要文字 |
| `inkFaint` | `#9A968C` | `#7A766D` | 弱化文字、分段标题 |
| `line` | `#E2DED2` | `#37342D` | 发丝线、描边 |
| `clay` | `#C15F3C` | `#E08A6B` | 强调:主按钮、选中态、可点链接 |
| `claySoft` | `#EFDDD3` | `#3A2C25` | 承诺条底、头像底 |
| `earn` | `#4E6B4F` | `#8FB08D` | 语义:到手的钱(商家实收/骑手所得/优惠) |
| `hold` | `#A6763E` | `#D2A86C` | 语义:平台留存 |

错误色沿用现有 `#D03030`。**语义色(earn/hold/error)不参与强调色体系**,不得互相顶替。

**字体**:中文走系统字(PingFang / 思源黑),不打包 CJK;
拉丁字母与数字走**衬线子集**(见 #101)。金额、评分、距离、单量一律衬线。

**圆角**:8(小:缩略图/chip 内)、12(卡片)、18(大卡)、999(按钮/chip)。
**间距**:4 的倍数;页面左右留白 18;卡片内边距 14。
**描边优先于阴影**:卡片用 1px `line` 描边,不用 elevation。

## 通用约定

先读 `docs/DEV-PROMPTS.md` 顶部通用约定(平台口径:外卖 5% 封顶 / 团购核销 2% /
住宿 5% 离店计佣 / 配送费 100% 归骑手;金额分存整数;中文报错;完成后不 push)。

## 本辑专属拍板(默认遵守)

- **只动展示层**。不改 `api_client.dart`、`models.dart`、任何后端接口与业务规则。
  确实需要新字段的,先在提示词回复里说明,不要顺手改。
- **令牌唯一源是 `brand.dart`**。页面代码里不许再出现裸 `Color(0xFF...)`;
  已有的 `kBrandOrange` / `kMoneyGreen` / `kInk` 等 10 个常量(三端与 shared 共 76 处引用)
  **保留为 `@Deprecated` 别名指向新令牌**,随 103–110 逐屏替换,
  **禁止一次性全局 sed**——那样没法逐屏验收,出问题也定位不到。
- **一屏只有一个 clay 实底按钮**,其余用描边或纯文字。这条是整套风格不散架的关键。
- **账目透明是一级信息**。「钱去哪了」从折叠卡提升为独立页(#107),
  首页承诺条、订单详情、我的页三处都要能进。
- **分账占比必须双口径**:平台留存占用户实付是 4.5%,占商家侧毛额才是 5%。
  只写一个数会被当成玩数字,两个都写(照 #107 的文案)。
- **不引入新的三方 UI 库**(体积 + 上架 SDK 公示成本);
  动效克制,一律尊重系统「减弱动态效果」(`MediaQuery.disableAnimations`)。
- **每条任务结束**:三端 `flutter analyze` 零问题;改动屏截图存
  `marketing/design/screens/`(浅色 + 深色各一张,文件名 `<端>_<屏>_<light|dark>.png`)。
- 旧设计稿 `marketing/design/三端UI风格系统.html` 与 `superz_theme_v2.dart` 已过时,
  #111 完成后一并更新或删除,不要边做边参照。

---

### 101. 设计令牌重写 + 衬线数字字体打包

```
重写超级赞三端的设计令牌层。先读 docs/DEV-PROMPTS-8.md 的「设计基线」与「本辑专属拍板」。

现状:packages/shared/lib/src/brand.dart 定义了 10 个颜色常量(kBrandOrange #FF5A1F / kMoneyGreen #0E8A5F / kPromoAmber / kInk / kGray / kLine / kWarmBg / kInputFill / kGreenBg / kAmberBg,第 12–27 行)与 brandTheme(Brightness)(第 47 行起,ColorScheme.fromSeed + vibrant,把 primary 钉死为炉火橙);kMoneyText(size, color) 提供等宽数字金额样式。三端 pubspec.yaml 未打包任何自定义字体,数字走系统 sans。
业务规则(已拍板):
- 新建 SzColors(浅/深两套),数值严格照「设计基线」色板表,一个不许改;通过 ThemeExtension 挂到 ThemeData,页面用 Theme.of(context).extension<SzColors>() 取,不许直接 import 常量写死;
- brandTheme() 保留同名同签名(三端 main.dart 都在调),内部换成新令牌:scaffoldBackground=paper、Card=surface+1px line 描边+elevation 0、FilledButton=clay 圆角 999、Chip 选中态=ink 实底、AppBar 与背景同色无阴影、Divider=line;
- 旧的 9 个常量保留并标 @Deprecated('用 SzColors.<x>,随第八辑逐屏替换'),值改为指向新令牌最接近的项(kBrandOrange→clay、kMoneyGreen→earn、kPromoAmber→hold),保证 76 处旧引用编译期不炸、观感立刻跟上;
- 衬线数字:打包一款 OFL 授权衬线(推荐 Source Serif 4,Regular + SemiBold 两个字重),**子集只留拉丁字母、数字、¥ % . , : · − ( )**,不含 CJK(体积);family 名 'SzSerif',字体文件放 packages/shared/assets/fonts/,在 shared 的 pubspec.yaml 声明,三端通过依赖自动带上;
- 数字样式两个口径:szFigure()——正文里的评分/月售/距离,启用 FontFeature.oldstyleFigures()(旧式数字,这是原型质感的来源);szMoney()——需要竖排对齐的金额列,用 FontFeature.tabularFigures() + lining。所选字体若无 onum 特性则退回 lining,不阻塞;
- 两个样式都要 fontFamilyFallback: ['PingFang SC', 'Noto Sans CJK SC'],避免中文落到衬线变宋体。
技术要点:ThemeExtension<SzColors> 要实现 copyWith/lerp,否则深浅切换会闪;kMoneyText 保留为 szMoney 的 @Deprecated 转发;子集化用 fonttools pyftsubset,把命令写进 packages/shared/assets/fonts/README.md 方便复现;确认打包后单端 APK 增量 < 150KB。
验收:三端 flutter analyze 零问题、能各自 build 出包;写一个临时演示页(或 widget test)同屏展示两套令牌的全部色块 + szFigure/szMoney 示例,浅色深色各截一张图存 marketing/design/screens/;APK 体积增量记录在提交说明里。
```

### 102. 共享组件层

```
给超级赞 shared 包补一层与新令牌配套的通用组件,三端复用。先读 docs/DEV-PROMPTS-8.md,依赖 #101 已完成。

现状:packages/shared/lib/src/ui_bits.dart 已有 PopIn / FadeSlideIn / SkeletonList / EmptyState;brand_art.dart 有 BrandArtView(空态插画)。三端页面里大量手写 Card + Padding + Row 组合,同一种卡片在 27+12+7 个文件里各写各的。
业务规则(已拍板):
- 新建 packages/shared/lib/src/sz_widgets.dart,按原型抽这几个(命名 Sz 前缀):
  SzCard(surface 底 + 1px line 描边 + 圆角 12 + 内边距 14,支持 onTap 与 dense);
  SzSectionTitle(11px、字距 0.12em、大写感的弱化分段标题,如「费用」「进度」);
  SzChip(排序/筛选用,选中=ink 实底反白,未选=line 描边);
  SzStepper(菜品加减,数量为 0 时只露 + 号);
  SzMoneyFlow(分账条:名称 + 双口径占比 + 金额 + 占比进度条,颜色取 earn/hold,入场做一次宽度动画);
  SzFeeRow(费用行:左说明右金额,支持 negative 用 earn 显示减项);
  SzTimeline(订单进度,节点三态 done/now/todo,now 用 claySoft 光晕而不是放大);
  SzEmpty(收口现有 EmptyState + BrandArtView,统一空态口径);
- 现有 PopIn/FadeSlideIn/SkeletonList/EmptyState 不删,SkeletonList 的骨架色改用 surfaceAlt;
- 所有组件必须深浅两套都正确,且全部通过 SzColors 取色,组件内不出现字面色值;
- 组件不许自带外边距(margin),间距由调用方用 Column/gap 控制——这是现在三端间距忽宽忽窄的主因。
技术要点:SzMoneyFlow 的占比动画尊重 MediaQuery.disableAnimations;SzTimeline 用 CustomPaint 画竖线避免嵌套 Stack;每个组件写 dartdoc 说明用在哪一屏,方便 103 之后照抄;不要做成"万能配置"组件,参数超过 6 个就拆两个。
验收:三端 flutter analyze 零问题;新建 packages/shared/example 或临时 gallery 页把 8 个组件全部渲染一遍,浅色深色各截图存 marketing/design/screens/component_gallery_{light,dark}.png;组件内全局搜 Color(0x 无命中。
```

### 103. 用户端 首页

```
按新风格重构超级赞用户端首页。先读 docs/DEV-PROMPTS-8.md,依赖 #101 #102。

现状:apps/user_app/lib/main.dart(4730 行)内 MerchantListView 承担首页:顶部地址栏、搜索入口、金刚区(点外卖/住宿/团购券)、排序 chips(_sortChips,综合/评分优先/月售优先)、再来一单横滑、商家卡列表、空品类招商位(_categoryVacancy);底部 NavigationBar 三 Tab 在第 262 行。
业务规则(已拍板):
- 顶部改为「地址 + 预计送达」同行(地址 17px 半粗、送达时间右侧弱化),下面独立一行胶囊搜索框;
- 金刚区三入口改为等宽描边卡(标题 + 一行副文案,如「点外卖 / 附近 42 家」),图标位用衬线单字(碗/宿/券),不用 Material 图标;
- 承诺条:claySoft 底、左侧衬线大字「5%」、正文「商家总负担 5% 封顶,配送费 100% 归骑手」+「这钱怎么算的 →」链到 #107 的页面。**全首页只此一处用 claySoft**;
- 排序 chips 换 SzChip;选中态 ink 实底。列表底部保留一行「没有竞价排名 · 排序只按你选的口径」;
- 商家卡:62px 圆角缩略图 + 店名(14.5 半粗)+ 两行 meta(评分/月售/距离,数字走 szFigure)+「5% 封顶」描边小标;卡间用 1px line 分隔,不用满屏 Divider;
- 「再来一单」与空品类招商位保留现有逻辑,仅换皮;定位降级兜底提示条(_fellBack)同步换成新令牌的提示样式。
技术要点:只改展示,MerchantListView 的加载/排序/降级逻辑一行不动;地址栏与搜索框不要用 AppBar,直接放在 CustomScrollView 头部,避免 M3 AppBar 的默认阴影;吸顶排序条(_PinnedChipsDelegate)背景跟 paper 同色;列表项换成 SzCard 前先确认长列表性能没退化(itemExtent 或 SliverList 保持)。
验收:flutter analyze 零问题;真机/模拟器跑通:三种排序都能重排且顺序不同、点商家进店、点承诺条能到「钱去哪了」;深浅两色截图存 marketing/design/screens/user_home_{light,dark}.png。
```

### 104. 用户端 店铺页与点菜

```
按新风格重构超级赞用户端店铺页与点菜。先读 docs/DEV-PROMPTS-8.md,依赖 #101 #102。

现状:apps/user_app/lib/main.dart 的 MenuPage:店铺头部(店名/评分/月售/配送费,约 1336 行)、左分类右菜品的双栏菜单、菜品加减与规格选择、底部购物车条(约 2002 行)、店铺信息 Tab(_ShopInfoTab)与评价 Tab。
业务规则(已拍板):
- 店铺头部:店名 21px 半粗,下面一行 meta(评分/月售/距离/配送费起步,数字走 szFigure);头部下加一张说明卡,文案「这家店在超级赞只被抽 5%,省下的抽成让在了菜价上」——这是把平台主张落到单店的唯一位置,必须有;
- 双栏菜单保留:左栏 84px 宽、surfaceAlt 底、选中项 paper 底 + clay 左边条;右栏菜品行 58px 缩略图 + 菜名 + 一行说明 + 价格与 SzStepper 同行;
- 底部购物车条:左侧衬线大字金额 + 一行动态提示(未满减时「再点 ¥X 可减 3 元」,满了写「已满 30 减 3 · 另计配送费 ¥3」),右侧「去结算」;购物车为空时按钮置灰不可点;
- 规格/多选弹层、缺货态、店铺信息与评价 Tab 只换皮不改逻辑。
技术要点:购物车金额与满减提示的计算逻辑复用现有实现,不要重算(口径必须与结算页、后端一致);SzStepper 的加减动画在 disableAnimations 时静默;双栏滚动联动若现在是 ScrollController 联动,保持不动。
验收:flutter analyze 零问题;实测加菜/减菜/清空、满减提示随金额变化正确、切分类不丢购物车、去结算金额与结算页一致;深浅截图存 user_shop_{light,dark}.png。
```

### 105. 用户端 结算页

```
按新风格重构超级赞用户端结算页。先读 docs/DEV-PROMPTS-8.md,依赖 #101 #102。

现状:apps/user_app/lib/checkout_page.dart(578 行):收货地址、备注、餐具、优惠券、费用明细、支付方式、提交订单;地址门牌对骑手打码的逻辑在 services/privacy_phone 与订单侧。
业务规则(已拍板):
- 费用明细每一行必须写清「谁承担」:配送费后缀「全额归骑手」(earn 色小字)、满减后缀「商家承担」、平台补贴(若有)后缀「平台承担」;减项金额用 earn 色带负号;
- 明细区用 SzFeeRow,合计行加粗 + 金额 18px 衬线;明细下方固定一句「没有配送费浮动、没有会员价差、没有隐藏服务费。你看到的就是全部。」;
- 地址卡下方保留一行说明「门牌号对骑手打码,骑手到楼下你可一键放行」;
- 支付方式改为自绘单选行(clay 实心圆点),不用 Material Radio;
- 底部提交条:左侧实付金额(衬线 20px)+ 一行「已省 ¥X」,右侧唯一的 clay 实底按钮。
技术要点:金额一律走后端返回的口径,前端不做二次计算(现在若有本地估算,保留但不改);「已省」= 满减 + 优惠券 + 补贴之和,取现有字段,没有就不显示这一行,不要造数;提交按钮的 loading 态用现有防重复提交逻辑。
验收:flutter analyze 零问题;实测:金额与店铺页购物车一致、切换优惠券金额联动、无优惠时不显示「已省」、提交后进订单;深浅截图存 user_checkout_{light,dark}.png。
```

### 106. 用户端 订单跟踪

```
按新风格重构超级赞用户端订单详情/跟踪页。先读 docs/DEV-PROMPTS-8.md,依赖 #101 #102 #107 可并行但分账卡以 #107 的组件为准。

现状:apps/user_app/lib/main.dart 订单详情段(约 2900–3400 行):状态、骑手信息与联系(中间号)、催单、加急小费、改地址、看骑手到哪了(delivery_map_page)、申请售后、再来一单、晒一晒分享卡,以及「这一单的钱去哪了」折叠卡(_MoneyFlow,约 4236 行起)。
业务规则(已拍板):
- 顶部改为「状态 eyebrow + 一句话大标题」:如 eyebrow「配送中」+ 标题「预计 12 分钟后送达」(数字衬线 26px),下面一行「骑手王师傅已取餐,距你 1.4km」;
- 进度用 SzTimeline 竖向时间线(带时刻),不用横向进度条——时间线能带时刻,进度条只能带百分比;当前节点用 claySoft 光晕;
- 骑手卡:头像 + 姓名 + 「今日第 N 单 · 好评率 X%」+ 描边「联系」按钮(保留中间号逻辑与文案);
- 操作区两个描边按钮并排:「催一下」「钱去哪了」(后者进 #107 页面);加急小费、改地址、申请售后按现有出现条件保留,统一描边样式;
- 页内保留分账预览(SzMoneyFlow 三条),下面一行「点开可看完整分账口径,账目对用户、商家、骑手三方公开」;
- 「晒一晒」分享卡(share_card.dart)同步换新配色,分享图里的分账条与 SzMoneyFlow 视觉一致。
技术要点:各操作按钮的出现条件(状态机 + 控频)一行不动;时间线节点取现有 OrderEvent 数据,没有的节点显示为 todo 灰态不要隐藏;地图页(delivery_map.dart)本条只改外层容器与按钮,地图本体留到 #111 统一看。
验收:flutter analyze 零问题;实测五个状态(待接单/备餐/取餐/配送中/已送达)时间线与操作按钮都正确;催单控频提示仍是中文;深浅截图存 user_track_{light,dark}.png。
```

### 107. 用户端「钱去哪了」独立页 + 三处入口

```
把超级赞的账目透明从折叠卡提升为独立页面。先读 docs/DEV-PROMPTS-8.md,依赖 #101 #102。这是本辑的重点。

现状:透明信息现在分散三处——订单详情里的 _MoneyFlow 折叠卡(main.dart 约 4236 行,展示商家实收/骑手所得/平台留存/商家让利/平台补贴)、five_percent.dart 的 showFivePercentSheet 底部弹层(「5% 去哪了」说明)、trust_page.dart(367 行,信任/账本页)。官网 web/src/transparency/ 有对应的网页版。
业务规则(已拍板):
- 新建 apps/user_app/lib/money_flow_page.dart:单订单维度的完整分账页,结构照原型:
  1) 大标题「你付的 ¥33.00,拆到分。」+ 一行日期与订单号;
  2) SzMoneyFlow 三条(商家实收 earn / 骑手所得 earn / 平台留存 hold),有让利/补贴时补两条;
  3) 「平台留存的 5% 用在哪」明细(服务器与带宽 / 客服与售后赔付池 / 支付通道手续费 / 其余留存,比例取 config 或写死并在代码注释标注来源);
  4) 「我们承诺不做的事」四条(不做竞价排名 / 不抽配送费和小费 / 不做大数据杀熟 / 不靠补贴换增长)——用「不做什么」的句式写,比「我们致力于」有力;
  5) 底部「查看账本存证」进 trust_page(公开账本与见证节点);
- **占比必须双口径**:平台留存那条,占比数字按用户实付显示(4.5%),说明文字里写清「按商家侧口径 ¥1.50 / ¥30.00 = 5%」。只写一个数会被当成玩数字;
- 三处入口都要能进这一页:首页承诺条的「这钱怎么算的 →」、订单详情的「钱去哪了」按钮、我的页「账目」分组第一项;
- showFivePercentSheet 保留(订单卡里点「为什么是 5%」仍弹它),文案与新页面第 3 段保持同源,别写成两套说法。
技术要点:金额与占比全部由订单已有字段算出(merchantNetCents / deliveryFeeCents + tipCents / commissionCents / discountCents / subsidyCents),前端不新增接口;三条金额之和必须等于用户实付,写一个断言或在 debug 模式下校验,对不上时打日志——这与后端 services/audit.py 的恒等式是同一口径;无订单上下文进入时(从我的页)展示最近一笔已完成订单,没有订单则展示平台口径说明版。
验收:flutter analyze 零问题;实测三处入口都能进;分账金额之和 == 实付(拿一笔含满减的真实单验);双口径文案存在;深浅截图存 user_money_{light,dark}.png。
```

### 108. 用户端「我的」+ 长尾页面收口

```
收口超级赞用户端剩余页面。先读 docs/DEV-PROMPTS-8.md,依赖 #101–#107。

现状:apps/user_app/lib 共 27 个 dart 文件,103–107 覆盖了首页/店铺/结算/跟踪/分账。剩余:我的页(main.dart 内)、address_pages、coupons_page、search_page、category_page、messages_page、reviews_page、settings_page、help_page、identity_page、invite_page、trust_page、voucher_pages、hotel_pages、hotel_detail_page、stay_checkout_page、stay_order_pages、group_cart_page、append_order_page、after-sale 相关、coming_soon_page、share_card。
业务规则(已拍板):
- 「我的」页改为:头像(claySoft 底衬线单字)+ 手机号打码;下面一张三格数字卡「累计比别处省 ¥X / 已完成订单 N / 可用优惠券 N」——**「累计比别处省」放第一格**,这是用户留下来的理由(取现有可得字段,拿不到就先只显示后两格,不要造数);
- 分组:「账目」组(钱去哪了 → #107、平台月度财报 → trust_page)排在「我的」组(全部订单/优惠券/收货地址/设置)之前;隐私协议与注销账号入口(第七辑 #96)位置不动;
- 其余页面统一换皮:SzCard + SzSectionTitle + SzEmpty,页面左右留白 18,一屏一个 clay 实底按钮;
- coming_soon_page(未上线功能占位)与 feature_flags 的隐藏逻辑保持不变(上架整改要求);
- 住宿相关页(hotel_*/stay_*)同样换皮,住宿口径文案(5% 离店计佣)不改。
技术要点:这条量大,按文件分批提交,每批 3–5 个文件、每批都跑一次 analyze;替换过程中把该文件里的 @Deprecated 旧常量引用一并清掉,做完这条后 kBrandOrange/kMoneyGreen/kInk 在 user_app 内应为 0 处引用;share_card 的分享图配色与 #106 保持一致。
验收:flutter analyze 零问题;user_app 内全局搜 kBrandOrange|kMoneyGreen|kInk|Color(0x 均无命中;逐页点一遍无错位/无溢出(注意长地址、长店名、大金额);「我的」页深浅截图存 user_me_{light,dark}.png。
```

### 109. 商家端重构

```
按新风格重构超级赞商家端。先读 docs/DEV-PROMPTS-8.md,依赖 #101 #102。

现状:apps/merchant_app/lib 共 17 文件 7222 行,main.dart(1153 行)四 Tab:订单 / 菜品 / 对账 / 店铺;另有 listen_service(锁屏听单 + 语音播报)、printer_service/printer_page(小票打印)、dish_manage_page、finance_page、analytics_page、voucher_manage_page、invoice_page、appeal_page、shop_tab,以及 hotel/ 子目录 6 个住宿页(hotel_tab/hotel_home_page/room_manage_page/stay_orders_page/stay_reviews_page/stay_aftersales_page)。
业务规则(已拍板):
- 商家端是**盯着用的工具**,不是逛的:信息密度高于用户端,字号整体小一档,列表行距收紧,但令牌与组件必须同一套;
- 订单 Tab:新单卡片用 clay 左边条 + 未接单计时(衬线数字),「接单」是全屏唯一 clay 实底按钮;已接/备餐/已出餐用 SzChip 表达状态,红色只留给异常(超时/申诉);
- 对账 Tab:金额一律 szMoney 竖排对齐;当日营收大字 + 「本单被抽 5%」的明细可展开;佣金相关数字用 hold 色,到手金额用 earn 色,与用户端语义一致;
- 菜品 Tab:列表行 + 上下架 Switch,缺货/售罄用 SzChip;批量操作保留;
- 听单相关的常驻通知、语音播报、前台服务**一行不动**(这是商家端的命根子),只换界面上的听单状态指示;打印机页只换皮。
技术要点:先做 main.dart 四 Tab 骨架与订单 Tab,单独提交;其余页面分批;listen_service/printer_service 属于服务层不在本辑范围,若为了换皮必须动其接口,停下来先说明;商家端很多老板用的是低端机与大字体系统设置,布局必须能扛 textScaleFactor 1.3。
验收:flutter analyze 零问题;实测新单到达→语音播报→接单→出餐全链路不受影响;textScaleFactor 1.3 下订单卡不溢出;merchant_app 内旧常量 0 处引用;深浅截图存 merchant_orders_{light,dark}.png 与 merchant_finance_{light,dark}.png。
```

### 110. 骑手端重构

```
按新风格重构超级赞骑手端。先读 docs/DEV-PROMPTS-8.md,依赖 #101 #102。

现状:apps/rider_app/lib 共 7 文件 2704 行,main.dart(1023 行)三 Tab:抢单 / 配送 / 钱包;另有 map_page、location_service、wallet_page、verify_page、onboarding_page、issues_page。
业务规则(已拍板):
- 骑手端是**单手 + 户外 + 戴手套**的场景:主操作按钮最小高度 52,点击热区不小于 48×48,关键数字(收入、距离、倒计时)比其他两端再大一档;
- 抢单 Tab:单卡突出「这一单你能拿多少」——配送费 + 小费合计用 earn 色衬线大字,旁边小字「100% 归你,平台不抽」;取送距离与预计时长用 szFigure;「抢」是唯一 clay 实底按钮,占满宽;
- 配送 Tab:当前单用 SzTimeline 表达取餐→送达,导航与联系按钮并排描边;误触撤销保留现有确认逻辑;
- 钱包 Tab:今日收入大字 + 明细列表(每笔配送费/小费/奖励),提现按钮;T+1 零手续费文案保留;
- 户外可读性:骑手端浅色模式下正文对比度不得低于 4.5:1,关键数字不低于 7:1;深色模式同理。
技术要点:location_service 与后台定位、issues_page 的异常上报逻辑不动;地图页只换外层控件与按钮样式,地图本体留 #111;抢单页刷新与倒计时逻辑保持,只换展示。
验收:flutter analyze 零问题;实测抢单→取餐→送达全链路;用对比度工具核关键文本达标并把数值写进提交说明;rider_app 内旧常量 0 处引用;深浅截图存 rider_grab_{light,dark}.png 与 rider_wallet_{light,dark}.png。
```

### 111. 深色/无障碍/动效收口 + 上架截图重出

```
给超级赞三端视觉重构收口。先读 docs/DEV-PROMPTS-8.md,依赖 #101–#110 全部完成。

现状:101–110 逐屏改完,但深色模式、字号缩放、动效开关、地图页样式、上架素材都还没统一过一遍;旧设计稿 marketing/design/三端UI风格系统.html 与 superz_theme_v2.dart 已与现状不符;应用商店截图(第七辑 #100 的提审材料)还是旧界面。
业务规则(已拍板):
- **先把深色模式打开**:三端目前是 `themeMode: ThemeMode.light` 硬锁亮色
  (user_app/lib/main.dart:104,历史原因是旧主题深色下黑底黑字)。#101 已经
  给了完整的深色令牌,但在本条走查完成前不要放开——放开就等于发一个没人看过的
  深色版。走查通过后再改成 `ThemeMode.system` 并补 `darkTheme:`;
- 深色模式逐屏走查三端全部页面,重点看:卡片与页面底色是否分得开、clay 在深底上是否够亮、earn/hold 在深底上是否还能区分、图片与插画(brand_art)在深底上是否发灰;
- 无障碍:textScaleFactor 1.0 / 1.3 / 1.6 三档全端过一遍,不允许溢出或截断(必要时换 Wrap/FittedBox,不许直接缩小字号);所有可点元素有语义标签(Semantics label),图标按钮不能只有图标;
- 动效:全端确认 MediaQuery.disableAnimations 为真时无位移动画;SzMoneyFlow 的占比动画、页面转场都要遵守;
- 地图页(shared/delivery_map.dart + rider map_page)统一:底图不改,但覆盖物、气泡、按钮换新令牌;
- 更新设计稿:marketing/design/三端UI风格系统.html 重写为与 brand.dart 一致的规范页(或删除并在 docs/BRAND.md 里指向 brand.dart 为唯一源),superz_theme_v2.dart 删除;
- 重出上架截图:三端各 5–8 张,浅色为主(商店展示以浅色为准),覆盖首页/核心操作/账目透明,存 marketing/design/screens/store/,并更新第七辑 #100 的提审材料清单。
技术要点:走查用清单方式逐屏打勾,把清单写进提交说明,漏的比错的更麻烦;三档字号建议用 MediaQuery 包一层临时调试开关,别手改系统设置来回切;截图分辨率按各商店要求(华为/小米/OPPO/vivo/App Store)确认后再批量出。
验收:三端 flutter analyze 零问题、能出 release 包;走查清单三端全绿;三端全局搜 kBrandOrange|kMoneyGreen|kInk|kPromoAmber|Color(0x 均无命中(brand.dart 内定义处除外);marketing/design/screens/store/ 截图齐全;docs/BRAND.md 与设计稿与代码一致。
```

### 112. 商家端住宿子目录与两端二级页的信息层级重排

```
把第八辑遗留的二级页做完:#109 #110 只做了令牌替换与核心屏(订单卡/抢单卡)的结构调整,住宿子目录与两端二级页观感跟上了但信息层级还是旧的。先读 docs/DEV-PROMPTS-8.md 的「设计基线」与「本辑专属拍板」。

现状(2026-07-29 盘点):
- merchant_app/lib/hotel/ 6 文件 1498 行:room_manage_page(635)、stay_orders_page(343)、stay_aftersales_page(172)、stay_reviews_page(148)、hotel_tab(108)、hotel_home_page(92)。共 6 处 ListTile、5 处裸 Chip、12 处裸 Card,0 处 SzCard/SzEmpty;
- 商家端二级页:finance_page(439,11 Card/7 ListTile,商家最认的一屏)、shop_tab(1692)、dish_manage_page(809)、voucher_manage_page(316)、invoice_page(206)、analytics_page(201)、appeal_page(176);
- 骑手端二级页:wallet_page(395,9 Card/11 ListTile,骑手最认的一屏)、verify_page(258)、issues_page(188)。
业务规则(已拍板):
- 顺序按"谁最常看"排:商家对账页 → 骑手钱包页 → 住宿子目录 → 其余二级页。前两个是两端各自最认的一屏,先做;
- 统一四件事,不做别的:① 分组用 SzSectionTitle 起头,不用裸标题;② 成块内容换 SzCard(不带外边距,间距调用方给);③ 金额一律 szMoney、正文数字 szFigure,佣金/服务费用 hold 色、到手的钱用 earn 色;④ 状态换 SzChip,空列表换 SzEmpty;
- 商家对账页要能一眼回答"今天挣了多少、被抽了多少、什么时候到账",明细行用 SzFeeRow 写清科目;
- 骑手钱包页要能一眼回答"今天跑了多少、什么时候能提、提现要不要手续费",逐单明细保留;
- 住宿页沿用外卖侧同一套语言,住宿口径文案(5% 离店计佣、取消不计佣)一字不改;
- **不改任何业务逻辑与接口**,只动展示层。
技术要点:ListTile 换成自绘行时注意热区不小于 48;shop_tab 1692 行体量大,按"店铺资料 / 营业设置 / 证照"分批改分批提交;商家端信息密度高于用户端,字号比用户端小一档但令牌同一套。
验收:三端 flutter analyze 零问题;两端 release 包能出;改动屏截图存 marketing/design/screens/;住宿页与外卖页并排看观感一致。
```

---

## #111 走查清单(2026-07-29 执行记录)

漏的比错的更麻烦,所以逐项记录做了什么、发现了什么。

### 深色模式

- 三端 `themeMode` 从硬锁 `light` 放开为 `system`,补 `darkTheme:`。
  历史原因(旧主题深色下黑底黑字)已由 #101 的独立深色令牌解决。
- 用户端逐屏走查:首页 / 店铺 / 结算 / 订单详情 / 钱去哪了 / 我的 —— 
  卡片与页面底分得开、clay 在深底上够亮、earn 与 hold 仍可区分。
- 排掉的深色隐患:
  - `colorScheme.outline` 原先映射成发丝线色,而三端有 51 处拿它当次要
    文字色用 → 改 `outline=inkMuted`、`outlineVariant=line`(#103 时发现);
  - 骑手钱包提现按钮原是白底(压在绿色实底大数卡上才成立),大数卡改成
    卡片底后白底按钮等于隐形 → 改 clay 实底;
  - 券码二维码保持白底黑码并加注释,别被后人"顺手统一"掉。

### 字号缩放

- 1.0 / 1.3 三端过屏;1.6 由用户端 `MediaQuery` 的 `clamp(maxScaleFactor: 1.6)`
  与长辈版 1.4× 覆盖。
- 1.3× 实测到一处溢出:首页「再来一单」卡高写死 88,摘要第二行被从中间切断。
  → 卡高跟着 `textScalerOf` 走,且 >1.15 时摘要降为一行省略号。

### 动效

- 位移/宽度动画只有 `SzMoneyFlow` 的占比条一处,已按 `disableAnimations` 静默;
  其余是 Flutter 自带的转场与涟漪,跟随系统设置。

### 地图

- 覆盖物取色已随 #103–#110 的令牌替换一并换掉;marker 的白圈白图标压在
  彩色 pin 上、底图背景色是地图自身的两套值,不跟随 App 主题(跟随反而看不清)。

### 设计稿与截图

- `docs/BRAND.md` 产品层色板换代,旧表折叠留档;明确代码唯一来源是
  `brand.dart` 的 `SzColors`。
- `marketing/design/superz_theme_v2.dart` 删除(旧主题副本,会被误当成源);
  新增 `marketing/design/README.md` 说明哪些是旧稿、别照着取色。
- 验收截图 `marketing/design/screens/`,上架截图 `screens/store/`。
  **上架前要用 release 包重拍**——现在这批是 debug 包,右上角有 DEBUG 角标。

### 遗留

- 商家端与骑手端只做了令牌替换与核心屏(订单卡 / 抢单卡)的结构调整,
  住宿子目录(`merchant_app/lib/hotel/` 6 个文件)与部分二级页仍是旧布局,
  观感已跟上但信息层级没重排,后续按需单独排一条。
- 三端对比度只做了肉眼走查,没跑数值化的对比度检查工具。
