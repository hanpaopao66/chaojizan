# SDK 参考

```html
<script src="/_sdk/2/sz-webapp.js"></script>
<script>const app = SuperZ.WebApp</script>
```

也可以打进自己的包:把开源仓 `packages/miniapp-sdk/src/index.ts` 拷进来 `import WebApp from './sz-webapp'`
(官方的记事本和 2048 就是这么做的)。当前版本 **2.0.0**,gzip 后约 7 KB。
固定版本的地址 `/_sdk/2.0.0/sz-webapp.js` 永不改变,`/_sdk/2/…` 始终是最新的 2.x;SRI 见 `/sdk/versions.json`。

约定:

- **所有方法返回 Promise**;同时接受 Telegram 风格的回调作为最后一个参数;
- 失败时 reject 一个 `SzError`,按 `error.code` 判断(见[错误码](#错误码)),不要按文案判断;
- 不在超级赞里打开时 `inHost` 为 `false`,调用回 `4008`;
- 「能力」一栏写的是需要的能力(见[核心概念 · 能力与授权](concepts.md#能力与授权)),「宿主」写最低宿主版本。

## 启动信息

### initData
`string`。平台签名的原串,**原样交给你的后端验签**([服务端](server.md))。能力:initData。宿主 2.0。

### initDataUnsafe
解析好的对象:`{ app_id, auth_date, launch_id, user: { open_id, language_code, nickname?, avatar_url? }, start_param?, env?, sig_kid, hash, signature }`。
**只用来展示**,不要拿它判断身份 —— 页面里的东西用户都能改。

### startParam()
直达链接 `?startapp=` 带来的参数(`[A-Za-z0-9_-]{1,64}`),没有返回空串。

### version
宿主实现的协议版本,如 `"2.0"`。

### sdkVersion
这份 SDK 的版本,如 `"2.0.0"`。

### isVersionAtLeast(v)
宿主版本是否 ≥ `v`。用新方法前先判断:`if (app.isVersionAtLeast('2.1')) …`。

### platform
`'android' | 'ios' | 'web' | 'unknown'`。

### inHost
是否在超级赞里打开。直接用浏览器打开时为 `false`(`?sz_mock=1` 时为 `true`)。

### isMock
是否在 `?sz_mock=1` 本地调试模式。

### capabilities
这个应用**此刻**有的能力名数组。

## 生命周期与外观

### ready()
告诉宿主页面画好了,宿主撤掉启动页。不调的话宿主 8 秒后照常展示。

### expand()
应用在半屏弹层里打开时,拉到全屏。

### close()
关闭小程序。

### isExpanded
弹层是否已经全屏。

### isActive
小程序是否在前台(切到后台时为 `false`,见 `activated` / `deactivated` 事件)。

### colorScheme
`'light' | 'dark'`,跟随宿主。

### themeParams
主题色(见 [CSS 变量](#css-变量)):`bg_color`、`secondary_bg_color`、`text_color`、`hint_color`、`link_color`、
`button_color`、`button_text_color`、`accent_text_color`、`destructive_text_color`、`line_color`。

### setHeaderColor(color)
设置宿主顶栏的底色(`#RRGGBB`)。**顶栏的内容(图标、名称、「由 XX 提供」、关闭)归宿主,页面改不了。**

### headerColor
最近一次设置的顶栏色。

### setBackgroundColor(color)
设置容器底色(`#RRGGBB`)。

### backgroundColor
最近一次设置的容器底色。

### enableClosingConfirmation()
用户点关闭 / 系统返回时先问一句「确定关闭?」。有没保存的改动时打开。

### disableClosingConfirmation()
关掉关闭确认。

### isClosingConfirmationEnabled
当前是否开着关闭确认。

### viewportHeight
可视区域高度(px),键盘弹出、弹层拖动时会变。

### viewportStableHeight
稳定后的可视高度(拖动结束才更新)。布局用它,不容易抖。

### safeAreaInset
设备安全区 `{ top, bottom, left, right }`(px)。

### contentSafeAreaInset
内容安全区:小游戏全屏时右上角有宿主的胶囊(`···` 和关闭),内容要让开它。

### isFullscreen
是否全屏(小游戏)。

### requestFullscreen()
进入全屏。能力:fullscreen(仅小游戏)。

### exitFullscreen()
退出全屏。能力:fullscreen。

### lockOrientation()
按 `superz.json` 的 `orientation` 锁屏幕方向。能力:orientation(仅小游戏)。

### unlockOrientation()
解除方向锁定。能力:orientation。

## 事件

### onEvent(name, handler)
订阅事件。

### offEvent(name, handler)
取消订阅。

事件名:`themeChanged`、`viewportChanged`、`safeAreaChanged`、`contentSafeAreaChanged`、`mainButtonClicked`、
`secondaryButtonClicked`、`backButtonClicked`、`settingsButtonClicked`、`popupClosed`、`activated`、`deactivated`、
`fullscreenChanged`、`fullscreenFailed`。

## 按钮(宿主原生画)

### MainButton
底栏主按钮。页面只管文字和状态,按钮本身宿主画 —— 页面盖不住、也仿冒不了。属性:`text`、`color`、`textColor`、
`isVisible`、`isActive`、`isProgressVisible`、`position`。同一轮里连着改几个属性只发一次。

### MainButton.setText(text)
设置文字(最多 64 个字符)。返回按钮本身,可以链式调用。

### MainButton.show()
显示。

### MainButton.hide()
隐藏。

### MainButton.enable()
可点。

### MainButton.disable()
不可点。

### MainButton.showProgress()
显示加载中(期间点击不触发)。

### MainButton.hideProgress()
取消加载中。

### MainButton.setParams(params)
一次设置多项:`{ text, color, text_color, is_visible, is_active, is_progress_visible }`。

### MainButton.onClick(handler)
点击回调(也会触发 `mainButtonClicked` 事件)。

### MainButton.offClick(handler)
取消点击回调。

### SecondaryButton
次按钮,API 和 MainButton 相同;`setParams` 多一个 `position`:`left` / `right` / `top` / `bottom`(相对主按钮)。

### BackButton
宿主顶栏左侧的返回箭头。**显示时,安卓系统返回键也交给页面**(触发 `backButtonClicked`);隐藏时系统返回键关闭小程序。

### BackButton.show()
显示返回箭头。

### BackButton.hide()
隐藏。

### BackButton.onClick(handler)
点击回调。

### BackButton.offClick(handler)
取消回调。

### SettingsButton
宿主 `···` 菜单里的「设置」一项,API 和 BackButton 相同。

## 弹窗与交互

### showPopup(params)
原生弹窗。`{ title?, message, buttons?: [{ id?, type?: 'default'|'ok'|'close'|'cancel'|'destructive', text? }] }`,
最多 3 个按钮,返回被按下的按钮 `id`(点空白关闭返回 `null`)。能力:popup。

```js
const id = await app.showPopup({
  title: '删除笔记',
  message: '删了能在回收站里找回 30 天',
  buttons: [{ id: 'del', type: 'destructive', text: '删除' }, { type: 'cancel' }],
})
```

### showAlert(message)
只有一个关闭按钮的弹窗。能力:popup。

### showConfirm(message)
确定 / 取消,返回 `boolean`。能力:popup。

### openLink(url)
用系统浏览器打开外链。宿主先弹「即将离开超级赞」,用户取消回 `4002`。只收 http(s)。能力:openLink。

### share(params)
系统分享面板:`{ text, url? }`,不给 `url` 默认带上这个小程序的直达链接。返回是否分享成功。能力:share。

### HapticFeedback
触感反馈。能力:haptics。

### HapticFeedback.impactOccurred(style)
`'light' | 'medium' | 'heavy' | 'rigid' | 'soft'`。

### HapticFeedback.notificationOccurred(type)
`'success' | 'warning' | 'error'`。

### HapticFeedback.selectionChanged()
选择变化的轻触感。

### requestProfile()
请求昵称和头像。能力:profile(要申请)。首次调用宿主弹确认,同意后**当场返回一份新签发的 initData**
(`{ initData, user }`)—— 把它交给你的后端验签;页面自己报上来的昵称不可信。用户拒绝回 `4002`。

## 云存储

(应用, 用户)隔离的键值存储,详见[云存储](storage.md)。能力:storage。

### CloudStorage
键 `^[A-Za-z0-9_.:-]{1,128}$`,值是字符串(对象请先 `JSON.stringify`),UTF-8 ≤ 65,536 字节。

### CloudStorage.setItem(key, value, opts?)
写一个键。`opts.ifRev`:只有当前版本号等于它才写(`0` 表示「必须还不存在」),不符回 `4007`。返回 `{ key, rev }`。

### CloudStorage.getItem(key)
读一个键,没有返回 `null`。

### CloudStorage.getItems(keys)
一次读多个(≤ 100),返回 `{ key: value | null }`。

### CloudStorage.getItemsWithRev(keys)
带版本号读,返回 `{ key: { value, rev } | null }`。做并发控制时用。

### CloudStorage.removeItem(key)
删一个键。

### CloudStorage.removeItems(keys)
删多个(≤ 100)。

### CloudStorage.getKeys(opts?)
列出全部键(自动翻页);`opts.prefix` 按前缀过滤。

### CloudStorage.getKeysPage(opts?)
分页列键:`{ prefix?, cursor?, limit? }`,返回 `{ keys, next_cursor }`。

## 错误

### SzError
失败时 reject 的错误类型,带 `code`。

### ERRORS
错误码常量表(下面这张表)。

## 错误码

| 码 | 名称 | 含义 | 该怎么办 |
|---|---|---|---|
| 4001 | CAPABILITY_NOT_GRANTED | 应用没申请到这个能力 | 去后台申请;或者降级处理 |
| 4002 | USER_DENIED | 用户点了拒绝 | 尊重用户,别连着再弹 |
| 4003 | NOT_SUPPORTED | 宿主太老或平台没有 | 用 `isVersionAtLeast` 先判断 |
| 4004 | INVALID_PARAMS | 参数不合法 | 看 message |
| 4005 | RATE_LIMITED | 调用太频繁 | 退避重试 |
| 4006 | QUOTA_EXCEEDED | 云存储满了 | 提示用户清理 |
| 4007 | REV_CONFLICT | 云存储版本号不符 | 取回服务器版本合并,见[云存储 · 并发](storage.md#并发) |
| 4008 | NOT_IN_HOST | 不在超级赞里打开 | 提示用户去 App 里打开 |
| 4009 | APP_SUSPENDED | 应用已被暂停 | 宿主随后会关闭它 |
| 5000 | INTERNAL | 宿主或平台内部错误 | 重试;持续出现请反馈 |
| 5001 | NETWORK | 网络失败 | 可重试 |

## CSS 变量

SDK 把主题和视口写在 `:root` 上,颜色取超级赞的产品色(骨白 / 墨 / 黏土),亮暗两套:

| 变量 | 对应 |
|---|---|
| `--sz-theme-bg-color` | 页面底色 |
| `--sz-theme-secondary-bg-color` | 卡片底色 |
| `--sz-theme-text-color` | 正文 |
| `--sz-theme-hint-color` | 次要文字 |
| `--sz-theme-link-color` | 链接 |
| `--sz-theme-button-color` / `--sz-theme-button-text-color` | 按钮 |
| `--sz-theme-accent-text-color` | 强调色 |
| `--sz-theme-destructive-text-color` | 危险操作 |
| `--sz-theme-line-color` | 分隔线 |
| `--sz-viewport-height` / `--sz-viewport-stable-height` | 可视高度 |
| `--sz-safe-area-inset-{top,bottom,left,right}` | 安全区 |
| `--sz-content-safe-area-inset-{top,bottom,left,right}` | 内容安全区 |

```css
body { background: var(--sz-theme-bg-color, #F0EEE6); color: var(--sz-theme-text-color, #141413); }
```

## 兼容 v1

老页面用的 `window.superz`(v1 桥)继续可用,SDK 会把它映射到 v2。新代码请直接用 `SuperZ.WebApp`。

## 线上协议(给想自己实现宿主或调试的人)

页面和宿主之间是 `{v:2, type, id, method, params, token}` 的消息:页面先发 `hello`,宿主回 `init`(带会话令牌),
之后每条 `call` 都要带令牌,宿主回 `reply`、主动发 `event`。原生 App 走注入的 `SuperzBridge` 通道,
网页版走 iframe `postMessage`。宿主只把令牌发给主框架 —— 页面里嵌的第三方 iframe 冒充不了。
