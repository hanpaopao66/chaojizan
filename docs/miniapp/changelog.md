# 更新日志与兼容表

## SDK

| 版本 | 日期 | 变化 |
|---|---|---|
| 2.0.0 | 2026-09 | 首个开放版本:initData v2、MainButton / SecondaryButton / BackButton / SettingsButton、弹窗、触感、分享、打开外链、云存储(带 rev)、全屏与锁方向(小游戏)、requestProfile、CSS 变量、`?sz_mock=1`;保留 v1 的 `window.superz` |

`/_sdk/2.0.0/…` 永不改变;`/_sdk/2/…` 始终指向最新的 2.x。改了行为会升版本号并写在这里。

## 宿主 × 能力

| 能力 | 方法 | 宿主 2.0(App 与网页版) | 备注 |
|---|---|---|---|
| 基础 | ready / expand / close / 主题 / 视口 / 安全区 / 按钮 / 关闭确认 | ✓ | |
| haptics | HapticFeedback.* | ✓(网页版无振动,调用照常成功) | |
| popup | showPopup / showAlert / showConfirm | ✓ | 最多 3 个按钮 |
| openLink | openLink | ✓ | 先弹「即将离开超级赞」 |
| share | share | ✓(网页版不支持系统分享时复制到剪贴板) | |
| storage | CloudStorage.* | ✓ | |
| fullscreen / orientation | requestFullscreen / lockOrientation … | ✓(仅小游戏;网页版不锁方向) | |
| profile | requestProfile | ✓ | 要申请 |
| location / scanQr / clipboard / phone | — | 下一阶段 | 现在申请回「暂未开放」 |

## initData 协议

| 版本 | 状态 |
|---|---|
| v2(本文档) | 当前。一应用一密钥 + 平台 Ed25519 签名,测试向量见[服务端](server.md#测试向量) |
| v1 | **已废弃**。只剩外部地址的官方老条目在用(`POST /mini-apps/{id}/init-data`),不对第三方开放 |
