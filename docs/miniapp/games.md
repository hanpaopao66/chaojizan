# 小游戏

建应用时选「小游戏」,`superz.json` 里 `"kind": "game"`。和应用的区别:

- 在 App 里**打开就是沉浸式全屏**,右上角是宿主的胶囊(`···` 和关闭);应用在弹层里打开,自己调 `requestFullscreen` 才全屏;
- 打开时按 `superz.json` 的 `orientation` 锁方向;
- 包上限 30 MB(应用是 10 MB)。

全屏(`requestFullscreen`)和锁方向(`lockOrientation`)这两项能力 2026-09-15 起**所有应用都有**,不再只给小游戏。

## 全屏与方向

```js
const app = SuperZ.WebApp
// 宿主打开小游戏时已经是全屏(再调会收到 fullscreenFailed: ALREADY_FULLSCREEN,不用管);
// 网页版上这一句会顺手试浏览器的全屏 API —— 放在用户第一次点击里调,浏览器才肯
app.requestFullscreen().catch(() => {})
```

横屏游戏在 `superz.json` 写 `"orientation": "landscape"`,宿主打开时就按它锁;玩到一半想固定住当前方向用
`lockOrientation()`(锁当前的横竖,和 Telegram 一样)。内容要让开 `contentSafeAreaInset`(胶囊和刘海)。
`exitFullscreen()` 会露出宿主的顶栏,游戏仍然铺满屏幕。

## 性能预算

- 中端安卓机上保持 60fps:16 个方块用 DOM + `transform` 就够(2048 就是),粒子多了再上 canvas / WebGL;
- 首屏 JS 尽量 < 200 KB(gzip),图片用 webp,音频用 ogg/m4a;
- WebAssembly 可以用(CSP 放行了 `wasm-unsafe-eval`),`eval` 不行。

## 存档

用[云存储](storage.md)存档,每步后防抖保存;本机再缓存一份让它秒开。2048 的做法:
`state`(棋盘、分数、随机种子、步数)每步后 500ms 存一次,`best` 存最高分;打开时本机缓存先画出来,
再看云端有没有更新的(换了设备接着玩)。随机数用**带种子的 PRNG**,状态里存种子 —— 可复现,也方便测试。

## 音频

浏览器不许未经用户操作自动播放声音:第一次点击或滑动之后再开始放。给一个静音开关。

## 为什么没有排行榜

前端游戏的分数没法由服务器验证,改一行 JS 就能刷到第一。**做不到公平的榜,不如不做**。
你想做排行榜,请自己的服务器做对局校验,并在描述里写清楚规则。

## 本期不允许内购和广告

小游戏只上**免费单机**:不能卖道具、不能放广告、不能诱导分享换奖励(R204、R402)。
带内购或广告的游戏涉及版号、防沉迷等资质,等平台准备好了再开放。
