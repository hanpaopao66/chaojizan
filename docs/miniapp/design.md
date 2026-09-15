# 设计规范

小程序跑在超级赞里面,用户分不清哪块是平台、哪块是你 —— 所以有几条要一致,别的你自由发挥。

## 宿主那一圈归宿主

- **顶栏**(图标、名称、「由 XX 提供」和认证标记、`···`、关闭)是宿主原生画在网页外面的,页面盖不住。
  别在页面里再画一条长得像顶栏的东西,更别画「支付」「客服」这类平台界面 —— 那是 R501(仿冒);
- **全屏**(所有应用都能用)时顶栏收成右上角的胶囊(`···`、关闭),同样归宿主、画在页面上面。
  页面别往那块放东西(`contentSafeAreaInset` 已经把它让出来),也别画一个像它的 —— R501 的尺度不因全屏而变;
- **主按钮 / 次按钮**在底栏,由宿主原生画,页面只给文字和状态(`MainButton`);
- **返回键**用 `BackButton`:显示时安卓系统返回键交给页面,隐藏时关闭小程序。

## 主题

用 [CSS 变量](sdk-reference.md#css-变量),别写死颜色。宿主亮暗切换时 SDK 会更新变量并发 `themeChanged`。

```css
:root {
  --bg: var(--sz-theme-bg-color, #F0EEE6);
  --ink: var(--sz-theme-text-color, #141413);
  --accent: var(--sz-theme-accent-text-color, #C15F3C);
}
```

默认色板是超级赞的产品色:骨白 `#F0EEE6` / 墨 `#141413` / 黏土 `#C15F3C`,深色态骨白换成 `#1B1A17`。
你的品牌色可以用在强调处,但正文和底色建议跟随主题 —— 用户开了深色模式,整页亮白会很刺眼。

## 字体与字号

- 用系统字体栈(`system-ui, -apple-system, "PingFang SC", "Noto Sans CJK SC", sans-serif`),不要从外网加载字体(CSP 也会拦);
- 字号用 `rem`,跟随系统字号 —— 很多用户把系统字号调大了,长辈版会放大到 1.4 倍;
- 数字列用 `font-variant-numeric: tabular-nums`,对得齐。

## 安全区

全面屏和全屏时要让开刘海和底部横条:

```css
.page { padding-top: var(--sz-content-safe-area-inset-top, 0px); padding-bottom: var(--sz-safe-area-inset-bottom, 0px); }
```

全屏时(应用、小游戏都一样)右上角有宿主的胶囊(`···` 和关闭),`contentSafeAreaInset.top` 已经把它算进去了。
全屏时安卓的系统返回键仍然按 BackButton 的规则走;iOS 没有系统返回键,全屏页面要返回上一层请在页面里自己画返回按钮。

## 布局

- 手机宽度 360–430 为主;平板和网页版请限宽(`max-width: 42rem` 左右),别让一行字横跨整个屏幕;
- 可视高度会随键盘变化,用 `--sz-viewport-stable-height` 布局,不容易跟着键盘抖。

## 无障碍

- 按钮用 `<button>`,链接用 `<a>`,别拿 `<div>` 当按钮;
- 文字与底色对比度 ≥ 4.5:1(2048 的每一档方块色都按这个算过);
- 键盘能操作(Tab 可达、有 focus 样式);给图标按钮写 `aria-label`。

## 动效

和超级赞 App 同一套时长曲线:短 120ms、中 220ms、长 320ms;标准曲线 `cubic-bezier(0.2, 0.8, 0.2, 1)`、
回弹 `cubic-bezier(0.34, 1.3, 0.64, 1)`、退出 `cubic-bezier(0.4, 0, 1, 1)`。
**尊重「减少动态效果」**:

```css
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
```

品牌物料页的「动效」一栏有实例:[/brand](/brand)。
