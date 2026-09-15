# 从 Telegram Mini Apps 迁移

整套路线对标 Telegram Mini Apps:页面 + JS SDK + 签名的 initData。SDK 2.1.0 起同一份脚本还挂了
`window.Telegram.WebApp`,Telegram 的小程序搬过来,要改的只有三处:

1. **前端改一行 script 地址**;
2. **后端改验签那一处**;
3. **用户标识从 `id` 换成 `open_id`,老用户重新绑定一次**。

其余的 `Telegram.WebApp.*` 代码不用动。下面是完整的对照和步骤。

## 最小例子

前端(每个 HTML 页):

```diff
- <script src="https://telegram.org/js/telegram-web-app.js"></script>
+ <script src="/_sdk/2/sz-webapp.js"></script>
```

后端验签(Node.js,照 Telegram 文档写的那种实现;Python 等其他语言改法一样,完整代码见[服务端](server.md)):

```diff
  const params = new URLSearchParams(initData)
- const secret = createHmac('sha256', 'WebAppData').update(BOT_TOKEN).digest()
+ const secret = createHmac('sha256', 'SuperZWebAppData').update(APP_SECRET).digest()
  const checkString = [...params]
-   .filter(([k]) => k !== 'hash')
+   .filter(([k]) => k !== 'hash' && k !== 'signature')
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([k, v]) => `${k}=${v}`).join('\n')
  const ok = createHmac('sha256', secret).update(checkString).digest('hex') === params.get('hash')
+   && params.get('app_id') === MY_APP_ID
- const userKey = JSON.parse(params.get('user')).id
+ const userKey = JSON.parse(params.get('user')).open_id   // 字符串、按应用隔离,老用户要重新绑定
```

(真写的时候用常量时间比较、检查 `auth_date` 不超过 600 秒 —— 这两条 Telegram 和超级赞一样。)

## 为什么是改 script 地址,而不是平台替你注入

托管页的 CSP 只放行同源脚本,`https://telegram.org/js/telegram-web-app.js` 在超级赞里本来就加载不了;
平台也**不会**在托管层往你的 HTML 里注入脚本 —— 用户打开的、审核看过的、详情页公示 SHA-256 的,必须是同一份字节。
所以这一行得你自己改,改完的包照常上传、审核。

## 对照表

| Telegram | 超级赞 | 说明 |
|---|---|---|
| `telegram-web-app.js` | `/_sdk/2/sz-webapp.js` | 每个托管 origin 下同源引;同一份脚本同时挂 `Telegram.WebApp` 和 `SuperZ.WebApp` |
| `Telegram.WebApp` | `Telegram.WebApp`(兼容层),或者 `SuperZ.WebApp` | 兼容层按 Telegram 的约定:方法不返回 Promise、失败不 reject、回调写法;`SuperZ.WebApp` 返回 Promise,见 [SDK 参考](sdk-reference.md) |
| `version` / `isVersionAtLeast` | 同名 | 兼容层报 Bot API 版本:2026-09-15 起的 App 报 `8.0`,更早的报 `7.10`,按版本号探测能力的代码能走对分支。为什么是这两个数见 [SDK 参考 · Telegram 兼容层](sdk-reference.md#telegram-兼容层) |
| `initData` | 同名 | 原样交给后端验签;字段不一样(有 `app_id`、`launch_id`、`sig_kid`,没有 `query_id`、`chat`),见[核心概念](concepts.md#initdata) |
| `initDataUnsafe.user.id` | 同名,就是 `open_id` | **字符串**(`o_` 开头)、**按应用隔离**,和 Telegram 的全局数字 id 不是一回事 |
| `user.first_name` / `user.photo_url` | 同名,就是昵称 / 头像 | 要 `requestProfile()` 且用户同意后才有(之前 `first_name` 是空串);`last_name`、`username`、`is_premium` 没有 |
| `start_param`(`startapp`) | 同名;链接是 `https://chaojizan.cc/m/<AppID>?startapp=…` | |
| `hash`(bot token 派生) | `hash`(AppSecret 派生) | 算法同构;常量换成 `SuperZWebAppData`,data_check_string **也去掉 `signature`**(Telegram 的 hash 只去掉 `hash` 本身) |
| 第三方验证(Ed25519 `signature`) | `signature` | 签名内容 `"<app_id>:SuperZWebAppData\n" + data_check_string`,公钥在 `/.well-known/superz-webapp-keys.json`(按 `sig_kid` 挑) |
| `ready()` / `expand()` / `close()` | 同名 | |
| `MainButton` / `SecondaryButton` / `BackButton` / `SettingsButton` | 同名 | 通栏按钮、底栏底色;属性直接赋值、`showProgress(leaveActive)` 和 Telegram 一致;事件名 `mainButtonClicked` 等相同 |
| `setHeaderColor` / `setBackgroundColor` / `setBottomBarColor` | 同名 | 收颜色键(`'bg_color'` 等)、`#RGB`、`rgb(…)`;顶栏的内容归宿主,见下 |
| `HapticFeedback` | 同名 | |
| `showPopup` / `showAlert` / `showConfirm` | 同名 | |
| `CloudStorage` | 同名 | 兼容层照 Telegram:只有回调、读不到的键给空串;`SuperZ.WebApp.CloudStorage` 多了 `ifRev` 乐观并发和 `getItemsWithRev`。配额 1024 键 / 5 MB,单个值 64 KB(Telegram 是 4096 字符),键多收 `.` 和 `:` |
| `openLink` | 同名 | 先弹「即将离开超级赞」;`try_instant_view` 等选项收下不用 |
| `requestFullscreen` / `exitFullscreen` / `isFullscreen` | 同名 | **所有应用都能用**(和 Telegram 一样,不只小游戏);全屏时右上角是宿主的胶囊(`···`、关闭) |
| `lockOrientation` / `unlockOrientation` / `isOrientationLocked` | 同名 | 锁当前的横竖;网页版不锁 |
| `safeAreaInset` / `contentSafeAreaInset` | 同名 | 兼容层照 Telegram 的口径:content 是安全区里面再让出的那一截,两者相加是总边距 |
| `themeParams`(15 个键) | 同名,15 个都有,多一个 `line_color` | 值是超级赞的产品色,亮暗两套 |
| CSS `--tg-theme-*`、`--tg-viewport-*`、`--tg-safe-area-inset-*`、`--tg-content-safe-area-inset-*` | 同名 | 另有一套 `--sz-*` 名字,见 [SDK 参考 · CSS 变量](sdk-reference.md#css-变量) |
| `onEvent('themeChanged')` 等 | 同名 | 处理函数里 `this` 是 `Telegram.WebApp`;`fullscreenFailed` 带 `error` |
| `isActive`、`activated` / `deactivated` | 同名 | |
| `disableVerticalSwipes` | 同名 | 只记开关:超级赞的内容区本来就不会被竖着滑走 |
| `hideKeyboard` | 同名 | |
| `openTelegramLink` / `switchInlineQuery` / `sendData` | 有桩,调用什么也不做 | 超级赞有消息和机器人:机器人的内联键盘 `web_app` 按钮和菜单按钮能打开小程序,和 Telegram 一样;但**小程序这边回不到会话** —— 没有「打开一个会话链接」「内联模式」「把数据交给机器人」的对应物,initData 里也没有 `query_id`、`chat` |
| `shareToStory` / `shareMessage` / `setEmojiStatus` / `requestEmojiStatusAccess` / `downloadFile` / `addToHomeScreen` / `checkHomeScreenStatus` | 有桩,按 Telegram 的约定回「不支持」 | 回调给 `false` / `'unsupported'`,并发对应的失败事件 |
| `requestWriteAccess` / `requestContact` | 有桩,按「用户取消」回 | 小程序拿不到用户的手机号,这是故意的 |
| `showScanQrPopup` / `readTextFromClipboard` / `LocationManager` / `BiometricManager` / `Accelerometer` / `DeviceOrientation` / `Gyroscope` | 有桩,回「不可用」 | 扫码、剪贴板、定位这类敏感能力以后开放时,每次都要用户确认 |
| `DeviceStorage` / `SecureStorage`(Bot API 9.0) | 有桩,回调给错误 `'UNSUPPORTED'` | 兼容层报 8.0,按版本号探测的代码本来就不会调 |
| 支付(Stars / `openInvoice`) | **没有**;`openInvoice` 的桩回 `'failed'` | 本期不允许收款、内购、广告 |
| Bot 服务器 | 你自己的后端 | 靠 initData 识别用户 |
| 部署在你自己的域名 | **平台托管** | 上传 zip,平台存成不可变版本,审核后发布 |

所有桩的逐项说明见 [SDK 参考 · Telegram 兼容层](sdk-reference.md#telegram-兼容层)。桩不走桥、不抛异常,控制台对每一项提示一次,
做了功能探测的代码会照 Telegram 的「不支持 / 用户取消」分支走下去。

## 迁移步骤

1. **前端改一行**:每个 HTML 页里的 `telegram-web-app.js` 换成 `<script src="/_sdk/2/sz-webapp.js"></script>`。
   其余 `Telegram.WebApp.*` 代码不用改。(打包进自己 JS 里的,用 `import { TelegramWebApp } from '@superz/miniapp-sdk'`;
   `@twa-dev/sdk` 这类把 telegram-web-app.js 整份打进包里的,把那份去掉换成这一行。)
2. **后端改验签那一处**(见上面的最小例子):常量 `WebAppData` 换成 `SuperZWebAppData`;密钥从 bot token 换成你的 AppSecret;
   hash 的 data_check_string 除了 `hash` 也去掉 `signature`;**并检查 `app_id` 是你自己的**。
   或者直接用平台公钥验 `signature`(签名内容里是你的 `app_id`,不是 bot id)。完整实现和测试向量见[服务端](server.md)。
3. **open_id 重新绑定**:后端从验签过的 `user` 里读 `open_id`(不是 `id`)。它和用户的 Telegram id 没有任何对应关系,
   在别的超级赞小程序里也不一样 —— 你原来按 Telegram id 存的用户数据,要让用户在你的系统里重新绑定一次(比如登录你自己的账号)。
4. 声明你后端的域名(后台「开发设置 → 服务器域名」);
5. 把静态文件打成 zip(根目录放 `superz.json`),上传、模拟器调通、提交审核。

`@telegram-apps/sdk`(tma.js)这类不经 `window.Telegram.WebApp`、自己实现 Telegram 私有协议的库,换 script 没用,
要把调用改成 `Telegram.WebApp` 或 `SuperZ.WebApp`。

## 故意不一样的地方

- **open_id 按应用隔离**:同一个人在两个应用里是两个 id —— 平台不帮任何开发者画像;
- **托管而不是外链**:审核看的就是上线的那一份,用户能核对 SHA-256;平台也因此不往你的页面里注入任何东西;
- **签名常量和密钥是自己的**:`SuperZWebAppData` 故意和 Telegram 的 `WebAppData` 分开,一边的签名串拿到另一边用不了;
- **顶栏归宿主,「由 XX 提供」保留**:外框的排法向 Telegram 靠(左关闭 / 返回、中间名称、右 `···`),但名称下面一定有一行
  「由 XX 提供」和认证标记,页面画不掉;全屏时收成右上角的胶囊,页面盖不住、也不许仿冒(审核按 R501 查);
- **没有支付和广告**:这一阶段只做工具和免费游戏;
- **敏感能力走桥、逐次确认**:相机、定位在托管页里被 Permissions-Policy 堵住,以后开放时只能经桥申请。

## 和消息、机器人的关系

超级赞的消息和机器人已经上线。机器人那一侧和 Telegram 一样能打开小程序:内联键盘的 `web_app` 按钮、会话里的菜单按钮
(只能是已上架的小程序,不收任意网址,见开源仓的 `docs/BOT-API.md`)。反方向还没有:小程序里没有 `openTelegramLink`
(打开一个会话链接)、`switchInlineQuery`(机器人本来就没有内联模式)、`sendData`(把数据交给打开它的机器人)的对应物,
initData 里也不带会话信息(没有 `query_id`、`chat`、`chat_type`),`answerWebAppQuery` 这一路用不了。
兼容层对这三个方法给的是什么也不做的桩。还要注意:机器人看到的是用户的平台 id,小程序拿到的是按应用隔离的 `open_id`,
平台不提供两者的对应关系 —— 想把小程序里的结果交回会话,目前只能让用户在两边各自登录你自己的账号,在你的后端对上。

## 几处容易踩的细节

- `platform` 是 `'android'` / `'ios'` / `'web'`,没有 Telegram 的 `'tdesktop'`、`'weba'` 这些值;
- `secondary_bg_color` 在超级赞是**卡片色**(比页面底 `bg_color` 浅);Telegram 里它是分组列表后面那层灰。
  照 Telegram 的推荐拿 `secondary_bg_color` 当页面底、`section_bg_color` 当分组卡片的,在超级赞里两者同色,
  只靠 `section_separator_color` 的分隔线分组 —— 想要层次,页面底换成 `bg_color`;
- 内容安全区两套口径:`--tg-content-safe-area-inset-*` 是 Telegram 的写法(和安全区相加),`--sz-content-safe-area-inset-*`
  已经是总数,别把两套混着加;
- `CloudStorage.getItem` 读不到时,`Telegram.WebApp` 给空串、`SuperZ.WebApp` 给 `null`。
