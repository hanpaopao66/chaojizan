# 机器人 Bot API 参考

对应 DEV-PROMPTS-40 的 #355、§5.13。服务端实现在 `server/app/routers/bot_api.py`(Bot API)、
`routers/dev_bots.py`(开发者后台)、`routers/chat_bots.py`(客户端)、`services/bots.py`、
`services/bot_webhook.py`;测试 `server/tests/e2e_bots.py`、`server/tests/unit/test_bots.py`。
**本文和实现、测试逐字一致**,改接口时三处一起改(DEV-PROMPTS-40 §11)。

形状照 Telegram Bot API:方法名、参数名、Update / Message / User / Chat 的字段名都一样。
手上有 Telegram 机器人的,把框架的 base url 换成 `https://chaojizan.cc/bot/`(注意末尾的 `/`)就能跑起来;
支持的是一个**子集**,和 Telegram 不一样的地方集中写在第 11 节。

---

## 0. 通用约定

### 0.1 地址与鉴权

```
POST https://chaojizan.cc/bot/<token>/<method>
```

- `token` 形如 `123:AbCdEf…`(`<机器人的用户 id>:<35 位 [A-Za-z0-9_-]>`),在开发者后台建机器人时给出,
  **只显示这一次**;库里只存它的 sha256,平台也看不到原文。丢了只能在后台「重置 token」(旧的当场失效);
- 方法名大小写不敏感(`getMe` 和 `getme` 一样);
- GET 和 POST 都收。参数可以放在查询串、`application/json`、`application/x-www-form-urlencoded`、
  `multipart/form-data`(传文件用它)里,两处都有时以请求体为准;
- 表单和查询串里的复杂参数(`reply_markup`、`entities`、`caption_entities`、`commands`、`menu_button`、
  `reply_parameters`)传 **JSON 字符串**;JSON 请求体里直接传对象。

### 0.2 响应

```json
{"ok": true, "result": …}
{"ok": false, "error_code": 400, "description": "Bad Request: chat not found"}
{"ok": false, "error_code": 429, "description": "Too Many Requests: retry after 1", "parameters": {"retry_after": 1}}
```

HTTP 状态码 = `error_code`。`description` 照 Telegram 的写法以 `Bad Request:` / `Forbidden:` / `Conflict:` /
`Unauthorized` / `Too Many Requests:` 开头(框架按它抛异常),我们自己的规则在前缀后面用中文写明。

| error_code | 什么时候 |
|---|---|
| 400 | 参数不对、会话 / 消息找不到、键盘不合法、屏蔽词、改的内容没变 |
| 401 | `Unauthorized`:token 格式不对、对不上、机器人已删除(三种不区分) |
| 403 | `Forbidden`:机器人主动找没说过话的人、被用户拉黑、不在群里、没有发言权限 |
| 404 | `Not Found`:没有这个方法 |
| 409 | `Conflict`:设了 webhook 时调 getUpdates |
| 429 | 限流(见第 6 节),带 `parameters.retry_after`(秒) |
| 500 | `Internal Server Error`(日志里只记 token 前 6 位) |
| 503 | 平台开关 `bots_enabled` 关着:`{"ok":false,"error_code":503,"description":"机器人功能暂未开放"}`,**先于**认 token |

### 0.3 token 不进日志

路径里带 token(和 Telegram 一样),而路径是日志里最常出现的东西。服务端在进应用的第一层就把路径换成
`/bot/<token 前 6 位>***/<method>`,之后所有日志(包括 uvicorn 的访问日志、异常留痕)只看得到前 6 位;
开发者后台也只显示前 6 位(`token_prefix`)。

---

## 1. 标识

| 东西 | 取值 |
|---|---|
| 用户 `id` | 用户的 user id |
| 私聊的 `chat.id` | **对面那个用户的 id**(和 Telegram 一样,私聊 id 就是人的 id) |
| 群 / 频道的 `chat.id` | `-(1000000000000 + 会话 id)`,和 Telegram 超级群 / 频道的 `-100…` 一个样子,看正负就分得出私聊和群 |
| `chat_id` 参数 | 上面两种整数(可以是字符串形式),或者 `@用户名`(公开群 / 频道;也可以是用户的 @用户名,等于那个人的私聊) |
| `message_id` | 会话里的消息序号(客户端看到的 `seq`) |
| `update_id` | 每个机器人一条序列,从 1 开始递增;**提交顺序就是编号顺序** |
| `file_id` | `<媒体 id>-<签名>`,**按机器人签名**:别的机器人拿去用不了 |
| `file_unique_id` | 同一个文件对所有机器人都一样,只用来认「是不是同一个文件」 |

---

## 2. 对象

### 2.1 User

```json
{"id": 22, "is_bot": false, "first_name": "小王", "username": "xiaowang"}
```

`username` 没设就不带。`first_name` 是资料里的名字(没填名字的显示「用户」+ 4 位编码,不用手机号)。

### 2.2 Chat

```json
{"id": 22, "type": "private", "first_name": "小王", "username": "xiaowang"}
{"id": -1000000000031, "type": "group", "title": "机器人测试群"}
{"id": -1000000000040, "type": "channel", "title": "今日特价", "username": "tejia_cn"}
```

`type` 只有 `private` / `group` / `channel`(我们的群不分普通群和超级群)。`getChat` 另外带
`accent_color_id: 0`、`max_reaction_count: 3`,私聊带 `bio`(对方写了签名时),群 / 频道带 `description`(有简介时)。

### 2.3 Message

```json
{
  "message_id": 7,
  "from": {"id": 22, "is_bot": false, "first_name": "小王"},
  "chat": {"id": 22, "type": "private", "first_name": "小王"},
  "date": 1789279200,
  "text": "/start",
  "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
  "reply_to_message": {…},
  "edit_date": 1789279300,
  "reply_markup": {"inline_keyboard": [[{"text": "好的", "callback_data": "ok"}]]}
}
```

- 文字消息:`text` + `entities`;带说明的媒体:`caption` + `caption_entities`;
- 附件:`photo`(数组,一个元素)`document` `video` `animation`(GIF)`voice` `video_note` `sticker`,
  都带 `file_id`、`file_unique_id`、`file_size`,各自的宽高、时长、`mime_type`、`file_name`;
- `location {latitude, longitude}`、`contact {phone_number:"", first_name, user_id}`(**名片不带手机号**)、`dice {emoji, value}`;
  投票消息不带投票详情;
- 频道帖子和群里匿名管理员发的消息没有 `from`,有 `sender_chat`;
- `reply_to_message` 只带一层;被回复的那条删了就没有这个字段;
- `edit_date` 只在改过文字时有(只换键盘不算);`reply_markup` 只在有内联键盘时有。

**实体**:偏移、长度按 UTF-16 码元(和 Telegram 一样)。类型 `bold` `italic` `underline` `strikethrough` `spoiler`
`code` `pre`(带 `language`)`text_link`(带 `url`)`text_mention`(带 `user`)`mention` `hashtag` `url` `bot_command`。
`mention` / `hashtag` / `url` 服务端自己识别,`bot_command` 在以 `/` 开头的词上标(代码块、链接里的不算)。

### 2.4 Update

```json
{"update_id": 3, "message": {…}}
{"update_id": 4, "edited_message": {…}}
{"update_id": 5, "callback_query": {"id": "5170433928306125943", "from": {…}, "message": {…},
                                    "chat_instance": "840213938871726541", "data": "ok"}}
{"update_id": 6, "my_chat_member": {"chat": {…}, "from": {…}, "date": 1789279400,
                                    "old_chat_member": {"status": "left", "user": {…}},
                                    "new_chat_member": {"status": "member", "user": {…}}}}
```

`ChatMember.status`:`creator` / `administrator`(带 `can_*` 权限位)/ `member` / `restricted` / `left` / `kicked`。
`chat_instance`:同一个机器人、同一个会话永远一样。

### 2.5 InlineKeyboardMarkup

```json
{"inline_keyboard": [
  [{"text": "好的", "callback_data": "ok"}, {"text": "官网", "url": "https://chaojizan.cc/"}],
  [{"text": "打开小程序", "web_app": {"app_id": "sz0123456789abcdef"}}]
]}
```

规则(不合规 400):

- 每个按钮 `text` 1–64 个字(过屏蔽词),**恰好一个动作**:
  - `callback_data`:1–64 字节(UTF-8)—— 不合规是 `BUTTON_DATA_INVALID`;
  - `url`:只许 `http` / `https` —— 不合规是 `BUTTON_URL_INVALID`;
  - `web_app`:`{"app_id": "<已上架小程序的 appid>"}`,**不收任意网址**;
- 最多 100 个按钮、每行 ≤ 8 个、每行至少 1 个;
- 别的按钮类型(`login_url`、`switch_inline_query`、`callback_game`、`pay` …)400;
- **回复键盘不做**:`keyboard` / `remove_keyboard` / `force_reply` 一律 400;
- `{"inline_keyboard": []}` 等于不带键盘。

---

## 3. 方法

| 方法 | 参数 | 返回 |
|---|---|---|
| `getMe` | — | User,另带 `can_join_groups: true`、`can_read_all_group_messages`(= 隐私模式关)、`supports_inline_queries: false` |
| `getUpdates` | `offset`、`limit`(1–100,缺省 100)、`timeout`(0–50 秒,缺省 0) | Update 数组 |
| `setWebhook` | `url`(空串 = 删除)、`secret_token`、`drop_pending_updates` | `true` |
| `deleteWebhook` | `drop_pending_updates` | `true` |
| `getWebhookInfo` | — | `{url, has_custom_certificate: false, pending_update_count, max_connections?, last_error_date?, last_error_message?}` |
| `sendMessage` | `chat_id`、`text`(1–4096 字)、`entities`、`reply_markup`、`reply_to_message_id`(或 `reply_parameters.message_id`)、`disable_notification` | Message |
| `sendPhoto` | `chat_id`、`photo`(multipart 文件或自己的 `file_id`)、`caption`(≤ 1024 字)、`caption_entities`、`reply_markup`、`reply_to_message_id`、`disable_notification` | Message |
| `sendDocument` | 同上,文件字段叫 `document` | Message |
| `editMessageText` | `chat_id`、`message_id`、`text`、`entities`、`reply_markup` | Message |
| `editMessageReplyMarkup` | `chat_id`、`message_id`、`reply_markup` | Message |
| `deleteMessage` | `chat_id`、`message_id` | `true` |
| `answerCallbackQuery` | `callback_query_id`、`text`(≤ 200 字)、`show_alert`、`url`(http / https) | `true` |
| `setMyCommands` | `commands`(`[{command, description}]`) | `true` |
| `getMyCommands` | — | `[{command, description}]` |
| `setChatMenuButton` | `menu_button` | `true` |
| `getChatMenuButton` | — | MenuButton |
| `getChat` | `chat_id` | Chat(见 2.2) |
| `sendChatAction` | `chat_id`、`action` | `true` |

逐个说明:

- **getUpdates**:没有更新时挂着等(最多 `timeout` 秒),有了立刻回。`offset` 之前的更新**视为已确认、删掉**;
  `offset` 为负数时从最新往回数(`-1` = 只要最后一条)。设了 webhook 时 `409 Conflict: can't use getUpdates method
  while webhook is active; use deleteWebhook to delete the webhook first`。`allowed_updates` 暂不支持(传了也不过滤)。
- **setWebhook**:`url` 必须是 `https`,端口只能 80 / 88 / 443 / 8443,不能带账号密码;**解析出的 IP 必须是公网**
  (拒绝回环、内网、链路本地、运营商 NAT 等);开发环境(`APP_ENV=dev`)额外允许 `http(s)://127.0.0.1` / `localhost`。
  `secret_token` 1–256 位 `[A-Za-z0-9_-]`,加密落库。换了地址会清掉旧的「最近错误」。
- **sendMessage / sendPhoto / sendDocument**:发之前判「能不能往这个会话发」(第 5 节);`parse_mode` **不支持**
  (传了 400,格式请用 `entities`);`reply_to_message_id` 指向的消息不存在时照发、只是不带引用。
  `sendPhoto` 只收图片(按文件内容认 jpg / png / webp / heic,图片会去掉 EXIF 里的定位);两个方法都**不支持传 URL
  让服务端去拉**(防 SSRF),只能 multipart 上传,或者传**你自己以前上传过的** `file_id`(别的机器人的 400)。
  单个文件上限:图片 20MB、文件 100MB,每个机器人每天 2GB(和聊天上传同一套配额)。
- **editMessageText / editMessageReplyMarkup**:只能改自己发的消息(别人的 400 `message can't be edited`);
  **不受 48 小时限制**;`editMessageText` 只能改文字消息;**不带 `reply_markup` 等于去掉键盘**(和 Telegram 一样);
  内容和键盘都没变 400 `message is not modified…`。只换键盘不算「已编辑」。`inline_message_id` 不支持。
- **deleteMessage**:只能删自己发的(为所有人删除,对方那边当场消失),不限时间;别人的 400 `message can't be deleted`。
- **answerCallbackQuery**:每个查询只能回一次;15 分钟以后或回过一次再回:400 `query is too old and response timeout
  expired or query ID is invalid`。用户那边最多等 10 秒(第 10.2 节),晚了照样返回 `true`,只是用户看不到了。
- **setMyCommands**:`command` 1–32 位 `[a-z0-9_]`(前面的 `/` 可带可不带),`description` 1–256 字(过屏蔽词),
  最多 100 条,不许重复;只支持默认范围(`scope` 不传或 `{"type":"default"}`,`language_code` 不传)。
- **setChatMenuButton**:只设默认按钮(传 `chat_id` 400)。`menu_button` 三种:
  `{"type":"commands"}`(列命令)、`{"type":"default"}`(= 没有按钮)、
  `{"type":"web_app","text":"点餐","web_app":{"app_id":"<appid>"}}` —— 只能是**机器人主人自己名下已上架**的小程序,
  文字 1–64 字;不收任意网址。小程序之后下架了,客户端就不显示这个按钮。
- **getChat**:私聊只要会话存在就行(用户打开过和机器人的私聊),群 / 频道要机器人是成员。
- **sendChatAction**:`action` 取 `typing` `upload_photo` `record_video` `upload_video` `record_voice` `upload_voice`
  `upload_document` `choose_sticker` `find_location` `record_video_note` `upload_video_note`,对方看到「正在输入 / 上传中」,
  6 秒后自己消失;同一会话 3 秒最多一次(多的静默忽略、照样返回 `true`);频道里什么都不做。

---

## 4. 机器人能收到什么

| 场景 | 收到 |
|---|---|
| 私聊 | 用户发给它的每一条(`message`),改过的(`edited_message`) |
| 群,隐私模式开(**缺省**) | 以 `/命令` 开头的(没 @ 谁时群里每个机器人都收)、`/命令@它的用户名`、@它的、回复它的消息;`/命令@别的机器人` **不收** |
| 群,隐私模式关 | 群里所有消息 |
| 频道 | 什么都不收(机器人在频道里只能发帖:被任命为有「发帖」权限的管理员) |
| 按它消息上的回调按钮 | `callback_query` |
| 被拉进群 / 移出 / 封禁 / 任免管理员 | `my_chat_member`;群解散时收到 `left` |
| 用户拉黑 / 解除拉黑它 | 私聊里的 `my_chat_member`(`kicked` / `member`) |

- 服务消息(谁进群了、改群名了)不投;**别的机器人发的消息不投**,自己发的也不回给自己;
- 隐私模式在开发者后台切换;`getMe` 的 `can_read_all_group_messages` 反映当前状态;
- 客户端在群资料里能看到每个机器人的隐私模式(`bot-info` 的 `privacy_mode`)。

---

## 5. 机器人不能主动找人

- 私聊:只能发给**和它说过话**的用户 —— 私聊存在,而且对方在里面发过消息。没说过话、没打开过私聊的:
  `403 Forbidden: bot can't initiate conversation with a user`(不区分「没这个人」和「他没理你」);
- 用户拉黑了机器人:`403 Forbidden: bot was blocked by the user`(发消息、正在输入、改、删都是);
- 用户注销了:`403 Forbidden: user is deactivated`;
- 群 / 频道:机器人得是成员,否则 `403 Forbidden: bot is not a member of the group chat`(频道是 `channel chat`);
  群里被限制发言、频道里不是有发帖权限的管理员:403;
- 机器人不需要实名。用户通过 @用户名 找到机器人、打开私聊,和找人一样(对方是机器人时不要求实名)。

---

## 6. 限流

| 项 | 限制 |
|---|---|
| 每个机器人发消息(sendMessage / sendPhoto / sendDocument) | 全局每秒 30 条 |
| 同一会话 | 每秒 1 条,允许突发 3 条 |
| 同一群 | 每分钟 20 条 |
| 用户点回调按钮 | 每人每秒 3 次 |

三道一起判、全过才扣额度;参数不合法(键盘、文件)在扣额度之前就拒掉,不白吃额度。超了 `429`,
`parameters.retry_after` 是要等的秒数(至少 1)。改消息、删消息、取更新不计入。

---

## 7. webhook

- 设了 webhook 之后,更新由平台 `POST` 到你的地址:`Content-Type: application/json`,正文就是一个 Update 对象;
  设了 `secret_token` 的带请求头 **`X-Superz-Bot-Api-Secret-Token: <secret_token>`**,用它认出是平台发的;
- 你的服务 **10 秒内回 2xx** 算投成;非 2xx、超时、连不上都算失败,记进 `getWebhookInfo` 的
  `last_error_date` / `last_error_message`(如 `Wrong response from the webhook: 500 Internal Server Error`);
- 失败按 **1 / 2 / 4 / 8 / … 分钟**退避重试;**同一个机器人按 `update_id` 顺序投**:队头那条在退避时,后面的都等着,
  不会先收到新的、后收到旧的;
- 创建满 **24 小时**还没投成的更新丢掉(`getUpdates` 也不会再给);
- 每次投之前重新解析地址、判一次内网;不跟随重定向;
- 平台开关关着时暂停投递,更新留着(24 小时内开回来照样送到)。

---

## 8. 开发者后台 `/dev/v1/bots…`

开发者账号(和小程序同一个身份)登录后调用,`Authorization: Bearer <JWT>`。**只能管自己的机器人,别人的一律 404。**
错误体是 `{"detail": "中文"}`。

| 接口 | 说明 |
|---|---|
| `GET /dev/v1/bots` | `{"items": [机器人…], "max": 20, "enabled": true}` |
| `POST /dev/v1/bots` | `{"name": "点餐助手", "username": "diancan_bot"}` → `{"bot": 机器人, "token": "…", "notice": "token 只显示这一次…"}`。名字 1–32 字;用户名规则同 @用户名(5–32 位、字母开头…)**且必须以 bot 结尾**,和用户 / 群 / 频道共用命名空间;每个开发者最多 20 个(409);开关关着 503 |
| `GET /dev/v1/bots/{id}` | 机器人详情,**不含 token**,只有 `token_prefix` |
| `PUT /dev/v1/bots/{id}` | 改 `name`、`about`(资料卡上的一句话,≤ 120)、`description`(空会话中间那段,≤ 512)、`avatar`(先 `POST /upload` `purpose=avatar` 上传,只认自己传的那张;进图片审核队列)、`privacy_mode` |
| `PUT /dev/v1/bots/{id}/commands` | `{"commands": [{command, description}]}`,规则同 setMyCommands |
| `PUT /dev/v1/bots/{id}/menu-button` | `{"type": "commands" \| "default" \| "web_app", "text": "…", "app_id": "…"}`,规则同 setChatMenuButton |
| `PUT /dev/v1/bots/{id}/webhook` | `{"url", "secret_token", "drop_pending_updates"}`,规则同 setWebhook |
| `DELETE /dev/v1/bots/{id}/webhook?drop_pending_updates=` | 删 webhook |
| `POST /dev/v1/bots/{id}/token` | 重置 token:旧的当场失效,新的只在这次响应里出现一次 |
| `DELETE /dev/v1/bots/{id}` | 删机器人,不可恢复(见下) |

机器人对象:

```json
{"id": 25, "name": "点餐助手", "username": "diancan_bot", "link": "https://chaojizan.cc/@diancan_bot",
 "avatar": "", "about": "", "description": "", "commands": [],
 "menu_button": {"type": "default"}, "privacy_mode": true, "token_prefix": "25:ZY1",
 "created_at": "2026-09-13T04:00:00+00:00",
 "webhook": {"url": "", "has_secret": false, "pending_update_count": 0,
             "last_error_date": null, "last_error_message": ""}}
```

`menu_button` 是 web_app 时是 `{"type":"web_app","text","app_id","app":{"name","icon","status"},"available"}`
(`available=false` 表示小程序下架了、用户那边不显示)。

**删机器人**:和注销账号同一套级联(`services/chat_purge.py`,S5)—— 它发过的消息正文、图片、按钮清空
(占位留着、对方当场看到消失)、它上传的文件删掉、退出所有群和频道、@用户名释放;token 当场失效、没取走的更新删掉;
它的账号行和注销账号一样留一行墓碑(名字显示「已删除的机器人」)。

开关 `bots_enabled` 关着时只是**不能建新机器人**,已有的照样能看、能改、能删。

---

## 9. 开关

`bots_enabled`(管理后台「平台开关」,名字「机器人」)。**缺省:开发 / CI 开,生产关**(和视频同一个判据,
等合规结论)。每次现查、不缓存,拉闸立刻生效。关着时:

- Bot API 一律 `503 {"ok":false,"error_code":503,"description":"机器人功能暂未开放"}`(token 对不对都是);
- 开发者后台建机器人 `503 {"detail":"机器人功能暂未开放"}`;
- 客户端的回调和 bot-info `503 {"detail":"机器人功能暂未开放"}`;
- 不再给机器人生成新的更新,webhook 暂停投递。

---

## 10. 给客户端的接口

### 10.1 消息里的内联键盘

机器人发的带键盘的消息,消息对象(§5.2)里:

```json
"markup": {"inline_keyboard": [[{"text": "…", "callback_data": "…"},
                                {"text": "…", "url": "https://…"},
                                {"text": "…", "web_app": {"app_id": "…"}}], …]}
```

没有键盘是 `null`。每个按钮恰好一个动作(见 2.5 的规则,服务端保证)。机器人换键盘、去掉键盘时照常发 `edit` 事件
(消息对象里的 `markup` 变了;只换键盘时 `edited_at` 不变)。发送人 `sender.is_bot` 为 `true`。

### 10.2 点回调按钮

```
POST /chat/v1/chats/{chat_id}/messages/{seq}/callback
{"data": "ok"}
```

- 调用者必须是会话成员(否则 403);那条消息必须是机器人发的、`markup` 里真有这个 `callback_data`(否则 400,
  机器人收不到);消息删了 / 看不到 404;每人每秒最多 3 次(429);
- 服务端给机器人一条 `callback_query`,然后**最多等 10 秒**它的 answerCallbackQuery(等的时候不占数据库连接);
- 等到了:`{"answered": true, "text": "已为你下单", "show_alert": false, "url": null}`
  (机器人没给文字时 `text` 是 `""`);`show_alert` 为真时弹窗,否则轻提示;`url` 非空时打开它;
- 10 秒没等到:`{"answered": false}`,什么都不提示。

### 10.3 会话里的机器人

```
GET /chat/v1/chats/{chat_id}/bot-info
```

成员可调(否则 403)。私聊里是对面那个机器人(一个),群 / 频道里是所有机器人成员,没有机器人是空列表:

```json
{"bots": [{"id": 25, "name": "点餐助手", "username": "diancan_bot", "avatar": "",
           "about": "帮你点外卖", "description": "发 /menu 看今天的菜",
           "commands": [{"command": "start", "description": "开始"}],
           "menu_button": {"type": "commands"},
           "privacy_mode": true}]}
```

`menu_button`:`{"type":"commands"}` | `{"type":"web_app","text":"点餐","app_id":"sz…","app":{"name":"…","icon":"…"}}` | `null`
(没设、设成 default、或者小程序下架了)。

### 10.4 找到机器人、打开私聊、拉进群、拉黑

- `GET /social/v1/resolve/{username}` 对机器人照常返回 `{"type":"user","user":{…,"is_bot":true}}`;
  用户资料卡 `GET /social/v1/users/{id}`、会话卡片里的 `peer` 都带 `is_bot`;
- `POST /chat/v1/chats/private {"user_id": <机器人 id>}` 打开私聊(对方是机器人时不要求实名);
- `POST /chat/v1/chats/{id}/members {"user_ids": [<机器人 id>]}` 拉进群:普通成员能加人就能加机器人;
  机器人不能当群主(转让给机器人 422);
- 拉黑走现有的 `POST /social/v1/blocks`,解除 `DELETE /social/v1/blocks/{id}`;
- 机器人不收推送(它没有设备),它发的消息照常推给用户。

---

## 11. 和 Telegram 不一样的地方

- 支持的方法只有第 3 节那些;没有内联模式(`inline_query`、`inline_message_id`)、支付、游戏、贴纸管理、
  `getFile`(机器人拿到用户发的图片 / 文件只有 `file_id`,下载不了);
- 回复键盘(`ReplyKeyboardMarkup` / `ReplyKeyboardRemove` / `ForceReply`)不做;`parse_mode` 不做,格式用 entities;
- `web_app` 按钮和菜单按钮打开的是**平台上已上架的小程序**(`app_id`),不是任意网址;菜单按钮只能是自己名下的;
- 发文件不支持传 URL 让服务端去拉;
- 私聊和群 / 频道的 `chat.id` 取法见第 1 节;群没有普通群 / 超级群之分,`type` 就是 `group`;
- 命令只有默认范围,不分语言;菜单按钮只有默认一个(不能按会话设);
- `allowed_updates` 不支持;`getUpdates` 同时被两个请求调用时不报 409;
- 机器人改 / 删自己的消息不限时间(Telegram 删除限 48 小时);
- 群里的慢速模式对机器人不生效(它有第 6 节的限流)。
