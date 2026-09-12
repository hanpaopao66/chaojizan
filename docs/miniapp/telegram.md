# 从 Telegram Mini Apps 迁移

整套路线对标 Telegram Mini Apps:页面 + JS SDK + 签名的 initData。大部分代码改个命名空间就能跑。

## 对照表

| Telegram | 超级赞 | 说明 |
|---|---|---|
| `Telegram.WebApp` | `SuperZ.WebApp` | |
| `telegram-web-app.js` | `/_sdk/2/sz-webapp.js` | 每个托管 origin 下同源引 |
| `initData` / `initDataUnsafe` | 同名 | 字段见下 |
| `user.id` | `user.open_id` | **按应用隔离**,不是全局用户 id |
| `user.first_name` / `username` | 无;`requestProfile()` 后有 `nickname`、`avatar_url` | 默认不给昵称 |
| `start_param`(`startapp`) | 同名;链接是 `https://chaojizan.cc/m/<AppID>?startapp=…` | |
| `hash`(bot token 派生) | `hash`(AppSecret 派生)| 常量换成 `SuperZWebAppData` |
| 第三方验证(Ed25519 `signature`) | `signature` | 签名内容 `"<app_id>:SuperZWebAppData\n" + data_check_string` |
| `ready()` / `expand()` / `close()` | 同名 | |
| `MainButton` / `SecondaryButton` / `BackButton` / `SettingsButton` | 同名 | 方法名一致;事件名 `mainButtonClicked` 等 |
| `HapticFeedback` | 同名 | |
| `showPopup` / `showAlert` / `showConfirm` | 同名 | 返回 Promise |
| `CloudStorage` | 同名 | 多了 `ifRev` 乐观并发和 `getItemsWithRev`;配额是 1024 键 / 5 MB |
| `openLink` | 同名 | 先弹「即将离开超级赞」 |
| `openTelegramLink` / `switchInlineQuery` / `sendData` | 无 | 超级赞没有聊天和机器人 |
| `requestFullscreen` / `lockOrientation` | 同名 | 只给小游戏 |
| `themeParams` / CSS 变量 `--tg-theme-*` | `--sz-theme-*` | 键名相同 |
| `onEvent('themeChanged')` 等 | 同名 | |
| 支付(Stars / invoice) | **没有** | 本期不允许收款、内购、广告 |
| Bot 服务器 | 你自己的后端 | 靠 initData 识别用户 |
| 部署在你自己的域名 | **平台托管** | 上传 zip,平台存成不可变版本,审核后发布 |

## 迁移步骤

1. 把 `Telegram.WebApp` 全部换成 `SuperZ.WebApp`,脚本地址换成 `/_sdk/2/sz-webapp.js`;
2. 后端验签:常量 `WebAppData` 换成 `SuperZWebAppData`,密钥从 bot token 换成你的 AppSecret
   (或者直接用平台公钥验 `signature`),**并检查 `app_id` 是你自己的**;
3. 用户标识从 `user.id` 换成 `user.open_id`(注意它按应用隔离,老用户要重新绑定);
4. 声明你后端的域名(后台「开发设置 → 服务器域名」);
5. 把静态文件打成 zip(根目录放 `superz.json`),上传、模拟器调通、提交审核。

## 故意不一样的地方

- **open_id 按应用隔离**:同一个人在两个应用里是两个 id —— 平台不帮任何开发者画像;
- **托管而不是外链**:审核看的就是上线的那一份,用户能核对 SHA-256;
- **没有支付和广告**:这一阶段只做工具和免费游戏;
- **敏感能力走桥、逐次确认**:相机、定位在托管页里被 Permissions-Policy 堵住,以后开放时只能经桥申请。
