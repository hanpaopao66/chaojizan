# 更新日志与兼容表

## SDK

| 版本 | 日期 | 变化 |
|---|---|---|
| 2.1.0 | 2026-09-15 | Telegram 兼容层:同时挂 `window.Telegram.WebApp`,CSS 变量多一套 `--tg-*` 名字,主题色补齐 Telegram 的 15 个键(`line_color` 保留),Telegram 有、超级赞没有的接口给「不支持」的桩(见 [SDK 参考 · Telegram 兼容层](sdk-reference.md#telegram-兼容层));新增 `setBottomBarColor` / `bottomBarColor` / `isOrientationLocked`;颜色收主题色键和 `#RGB`、`rgb()`;底栏按钮的属性可以直接赋值,`showProgress(leaveActive)` 和 Telegram 一致 |
| 2.0.0 | 2026-09 | 首个开放版本:initData v2、MainButton / SecondaryButton / BackButton / SettingsButton、弹窗、触感、分享、打开外链、云存储(带 rev)、全屏与锁方向(小游戏)、requestProfile、CSS 变量、`?sz_mock=1`;保留 v1 的 `window.superz` |

`/_sdk/2.1.0/…`、`/_sdk/2.0.0/…` 永不改变;`/_sdk/2/…` 始终指向最新的 2.x。改了行为会升版本号并写在这里。

## 宿主 × 能力

宿主 2.1 是 2026-09-15 起的 App(和网页版);更早的 App 是宿主 2.0。页面用 `isVersionAtLeast('2.1')` 区分。

| 能力 | 方法 | 宿主 2.0 | 宿主 2.1 | 备注 |
|---|---|---|---|---|
| 基础 | ready / expand / close / 主题 / 视口 / 安全区 / 按钮 / 关闭确认 | ✓ | ✓ | 2.1 的主题色是 16 个键,2.0 是 10 个(SDK 补齐) |
| 基础 | setBottomBarColor | — | ✓ | |
| haptics | HapticFeedback.* | ✓ | ✓ | 网页版无振动,调用照常成功 |
| popup | showPopup / showAlert / showConfirm | ✓ | ✓ | 最多 3 个按钮 |
| openLink | openLink | ✓ | ✓ | 先弹「即将离开超级赞」 |
| share | share | ✓ | ✓ | 网页版不支持系统分享时复制到剪贴板 |
| storage | CloudStorage.* | ✓ | ✓ | |
| fullscreen / orientation | requestFullscreen / lockOrientation … | 仅小游戏 | ✓ 所有应用 | 网页版不锁方向;全屏时试浏览器的全屏 API |
| profile | requestProfile | ✓ | ✓ | 要申请 |
| location / scanQr / clipboard / phone | — | 下一阶段 | 下一阶段 | 现在申请回「暂未开放」 |

## initData 协议

| 版本 | 状态 |
|---|---|
| v2(本文档) | 当前。一应用一密钥 + 平台 Ed25519 签名,测试向量见[服务端](server.md#测试向量) |
| v1 | **已废弃**。只剩外部地址的官方老条目在用(`POST /mini-apps/{id}/init-data`),不对第三方开放 |
