# 开发提示词 #377–#383:金刚区新增「音乐」和「论坛」—— 音乐对标网易云音乐,论坛对标 X

2026-09-15 用户:「新增音乐和论坛功能,音乐对标网易云,论坛对标 X,都在金刚区展示,要标准化和可用,功能全面,
音乐有音乐人入口,账户还是统一用超级赞账户,打通其他板块。都不需要实名。」

- **音乐**:照网易云做 —— 发现页(每日推荐、推荐歌单、新歌、榜单、曲风)、播放器(进度、上一首 / 下一首、
  列表循环 / 单曲循环 / 随机、播放队列、滚动歌词、音质、定时关闭、后台播放)、我喜欢的音乐、最近播放、
  自建歌单和收藏歌单、专辑、歌手页、歌曲评论(热评、楼中楼)、搜索、分享;**音乐人中心**:开通音乐人、
  上传歌曲(歌词、词曲编制作署名、原创声明)、发单曲 / EP / 专辑、提交审核、数据;
- **论坛**:照 X 做 —— 推荐 / 关注两条时间线、发帖(文字、最多 4 张图、卡片、投票)、回复成串、转发、引用、
  点赞、书签、浏览数、编辑(30 分钟内、留历史)、谁能回复、#话题、@提及、热门话题、搜索、个人主页
  (帖子 / 回复 / 媒体 / 喜欢、置顶)、关注 / 粉丝、屏蔽词、举报;
- **打通**:同一个超级赞账号和社交资料;**关注关系全站一张**(关注一个人 = 看得到他的视频、帖子和歌);
  互动消息合并成一处;歌曲、歌单、帖子能分享进聊天(卡片)和论坛;个人主页有他的动态、视频、音乐;
  迷你播放器在整个 App 里跟着走。

## 怎么用这份文档

照 [DEV-PROMPTS-40.md](DEV-PROMPTS-40.md) 的写法:§1–§8 是设计与规范,§5 是规范性的(实现、文档、测试三处逐字一致);
§10 的每一条 `#3xx` 是一条可以单独交给编码 agent 的提示词。§4 的决定按推荐直接执行,另一个选项和代价照写。

---

## 1. 现状:能复用的东西(从代码里读出来的)

| 东西 | 位置 | 怎么用 |
|---|---|---|
| 统一账号与资料 | `users` + `social_profiles`(@超级赞号、签名、隐私)、`usernames` | 作者、音乐人一律挂 `users.id`,不另起账号体系 |
| 人物简卡 | `services/video.people(db, viewer_id, ids)` → `{id, name, username, avatar}` | **不含手机号**,头像按隐私和拉黑过滤;音乐、论坛直接用它 |
| 关注 | `follows`(`models_video.py`,全局 用户→用户),`video_interact.set_follow` | 现在只有视频用、接口挂在 `/video/v1`(视频关着就 503)、**不发通知** —— #377 抽成全站的 |
| 拉黑 / 处罚 | `social_blocks`、`social_sanctions`,写接口必须走 `routers/social.social_user` | 新模块的写接口一律走它(`test_sanctions` 有守卫) |
| 上传 | `/media/v1`(整块 ≤20MB、分片 4MB、24 小时)、`services/media.ingest`(按字节认类型) | 加用途 `music`;`sniff` 补认 FLAC |
| 转码队列 | Redis `media:jobs`、`workers/media.run_job`、`services/transcode.py` | 加任务类型 `music_track`(转 AAC) |
| 播放地址签名 | `services/video.py` 的 `vod_sig`(HMAC,绑定用户和到期) + `routers/media.file_response`(Range、X-Accel) | 音乐照抄一份,换命名空间 |
| 审核状态机 | `services/video_state.py`、`video_admin.py`、`video_decisions`、`REASON_CODES` | 音乐按「作品」审,照抄;原因代码共用 C1xx / X999 |
| 公开公式 | `services/video_rank.FORMULA` 和 DEV-PROMPTS-40 §5.9 逐字一致(单测钉住),每条推荐带中间量 | 音乐榜单、论坛推荐、热门话题照这个做 |
| 互动消息 | `social_notifications` + `services/social_notify.notify` + `/social/v1/notifications` | 加论坛、音乐的目标列和几个 kind,合并成一个互动消息 |
| 开关 | `services/flags.py`(`VIDEO_FLAGS`:开发缺省开、生产缺省关)、后台 `_KNOWN_FLAGS`、`/config.features` | 新增 `music_enabled`、`music_upload_enabled`、`forum_enabled`、`forum_post_enabled` |
| 金刚区 | `packages/shared/lib/src/channels.dart` `kChannels`、`GET /channels`、后台「平台开关」 | 加 `music`、`forum` 两格(颜色槽 4、6) |
| 注销 / 导出 | `auth.delete_me` → `video.purge_user`;`chat_export._build` | 都是手写清单,**新表不接进去不会报错**,各自补 |
| 播放库 | 用户端已经有 `audioplayers`(语音消息)、`video_player` | 音乐播放用 `audioplayers`,**不引新插件**(五端构建都已跑通) |

---

## 2. 对标:抄什么、不抄什么

### 2.1 音乐 vs 网易云

| 抄 | 不抄 / 不一样 | 理由 |
|---|---|---|
| 每日推荐、推荐歌单、新歌、榜单、曲风、搜索 | 不接商业曲库,**只收音乐人自己上传的原创或已获授权作品** | 没有版权采购,也不做搬运平台 |
| 播放器全套、滚动歌词、队列、播放模式、音质、定时关闭 | 不做下载离线、不做云盘 | 版权;只做边听边缓存 |
| 我喜欢、最近播放、自建 / 收藏歌单、收藏专辑 | 不做 VIP、付费单曲、数字专辑、打赏 | **平台没有钱**,也不向用户收钱 |
| 歌曲评论、热评、楼中楼 | 评论先发后审(和视频评论同口径) | |
| 音乐人入驻、上传、发布、数据 | **开通音乐人不要求实名**(用户拍板),不做收益结算 | |
| 榜单 | **公式公开**,每首歌带算分的中间量;推荐可关个性化 | 和视频推荐同一个立场 |

### 2.2 论坛 vs X

| 抄 | 不抄 / 不一样 | 理由 |
|---|---|---|
| 推荐 / 关注时间线、发帖、回复成串、转发、引用、点赞、书签、浏览数 | 推荐**公式公开**、可关个性化 | |
| 编辑(发出 30 分钟内,留历史) | 不收费,人人都能编辑 | |
| 谁能回复、@、#话题、热门话题、搜索、屏蔽词、置顶 | 热门话题**运营能隐藏但要写原因、留痕** | 不偷偷压话题 |
| 个人主页、关注 / 粉丝 | 私信直接用聊天,不另做 | 聊天已经对标 Telegram |
| 投票 | 不做 Spaces、社群、订阅、广告、蓝 V 售卖 | 平台不卖东西 |
| 举报、下架 | 下架带原因代码,作者能申诉一次、换人复核 | 和视频、社区治理同一套 |

---

## 3. 不变量(每条都要有守卫测试)

1. **不收钱**:音乐和论坛没有任何付费、打赏、会员、推广位。`/music/v1`、`/forum/v1`、`/admin/music`、`/admin/forum`
   的路由名、请求字段里不许出现支付字样(照 `test_video_invariants` 的支付词扫描);模型里不许有可售字段
   (`sponsored` / `boost` / `promot` / `paid` / `price` 之类,照 `test_video_rank` 的检查)。
2. **不要求实名**:开通音乐人、上传、发帖、评论只要手机号账号。守卫:`music*.py`、`forum*.py` 里不许引用
   `UserIdentity` / `require_realname`。
3. **音乐先审后发**:没过审的作品,除了作者本人和管理员,谁也拿不到播放地址、详情、封面(一律 404,不告诉你「有但看不了」)。
4. **统一账号**:作者、音乐人、歌单主人都挂 `users.id`;人物简卡一律走 `video.people`(不含手机号)。
5. **公开公式**:`services/music_rank.FORMULA`、`services/forum_rank.FORMULA` 和本文 §5.4、§5.7 的代码块**逐字一致**(单测钉住);
   榜单、推荐的每一项都带算分的中间量;`GET /music/v1/rank/formula`、`GET /forum/v1/rank/formula` 返回全部参数。
6. **处罚管得到、拉黑管得到**:写接口一律走 `social_user`;被拉黑的人不能回复、@、引用、评论你,也看不到你的头像。
7. **注销清干净、导出拿得全**:`purge_user` 覆盖全部新表;导出里有自己的帖子、歌单、作品。
8. **开关是急停闸**:`music_enabled` / `forum_enabled` 关着时对应前缀全部 503;`music_upload_enabled` 管上传和提交审核,
   `forum_post_enabled` 管发帖和回复;路由级依赖,单测列举全部路由检查。

---

## 4. 决定(按推荐执行)

| # | 决定 | 另一个选项和代价 |
|---|---|---|
| M1 | 曲库只收音乐人上传的原创 / 已获授权作品,上传时勾选声明;侵权走举报(版权投诉要留联系方式),下架有记录 | 接商业曲库:要版权采购,做不了 |
| M2 | 任何用户端账号都能开通音乐人:艺名(唯一、2–30 字、套用保留词)+ 简介 + 曲风;不实名、不审核主页,冒充走举报 | 审核主页:慢,且没有实名也审不出真假 |
| M3 | 审核的单位是「作品」(单曲 / EP / 专辑,含全部歌曲);过审后歌曲不能改,要改就下架重交 | 按歌审:一张专辑一半上架一半卡着,体验怪 |
| M4 | 上传 mp3 / m4a / aac / flac / wav / ogg,单首 ≤ 200MB、5 秒–20 分钟;转 AAC 128k(标准)和 256k(高品质,源码率低于 192k 不出);统一响度 −14 LUFS;转完删源文件 | 保留无损:存储翻十倍,也没有播放无损的需求 |
| M5 | 播放地址签名 6 小时,**不登录也能听**;喜欢、评论、歌单、推荐要登录 | 必须登录才能听:门槛太高 |
| M6 | 听满 `min(30 秒, 时长一半)` 算一次收听;同一个人同一首 30 分钟内只算一次;榜单一律按人去重 | |
| M7 | 榜单三个:热歌、新歌、飙升;每日推荐 20 首;推荐歌单按收藏 | |
| M8 | 歌词支持 LRC(带时间轴)和纯文本;播放页滚动高亮 | |
| M9 | 后台播放:iOS 开 `UIBackgroundModes: audio`、安卓加 `WAKE_LOCK`,用 `audioplayers` 的 stayAwake;**这一批不做锁屏控制条** | 接 audio_service:要安卓前台服务和通知,五端构建风险大,下一批 |
| F1 | 帖子 500 字;图片 ≤ 4 张(公开图片用途 `forum`,只能用自己上传的);可带一张站内卡片;投票 2–4 项、5 分钟–7 天 | |
| F2 | 回复成串:`reply_to` + `root`;转发不带字、引用带字;书签只有自己看得见 | |
| F3 | 编辑:发出后 30 分钟内、最多 5 次,留历史,显示「已编辑」;投票和图片不能改 | |
| F4 | 谁能回复:所有人 / 我关注的人 / 我提到的人 | |
| F5 | 浏览数:客户端批量上报展示过的帖子,按人按天去重 | 按请求算:刷新一次涨一次,虚 |
| F6 | #话题 认两种写法:`#话题`(空格、标点或结尾截止)和 `#话题#`;话题 1–30 字、不分大小写 | |
| F7 | 发帖、评论先发后审:违禁词当场拒发(`moderation.guard_text`),其余靠举报和巡查;下架带原因代码 | 先审后发:论坛就不是论坛了 |
| I1 | 关注全站一张表(`follows`),新接口 `/social/v1/users/{id}/follow`,**关注发通知**;视频的老接口保留、改调同一个函数 | |
| I2 | 互动消息合并:`social_notifications` 加论坛、音乐的目标列;kind 加 `follow`、`repost`、`quote`;「视频互动」那一行改叫「互动消息」 | 各模块各一行:聊天列表被挤满 |
| I3 | 分享进聊天:新消息类型 `card`,客户端只传 `{type, id}`,**标题、封面由服务端查出来存快照**,不信客户端 | 发纯文本链接(视频现在的做法):没有卡片样子 |
| I4 | 金刚区加「音乐」「论坛」,默认名就叫这两个,后台能改名、能显示 / 隐藏 | |
| I5 | 迷你播放器:有歌在放时,App 底部导航上方常驻一条;点开进播放页 | |

---

## 5. 规范(规范性)

### 5.1 标识

公开编号都是「前缀 + 10 位 base58」(字母表同视频 `sv…`:`[1-9A-HJ-NP-Za-km-z]`),防止按数字遍历:

| 对象 | 前缀 | 链接 |
|---|---|---|
| 歌曲 | `mt` | `https://chaojizan.cc/music/t/<tid>` |
| 作品(单曲 / EP / 专辑) | `mr` | `/music/r/<rid>` |
| 歌单 | `mp` | `/music/p/<pid>` |
| 音乐人 | `ma` | `/music/a/<aid>` |
| 帖子 | `fp` | `/forum/p/<pid>` |
| 话题 | —— | `/forum/t/<话题,URL 编码>` |

### 5.2 通用约定

- **人物简卡** `person`:`{id, name, username, avatar}`,由 `video.people` 生成;
- **分页**:按分数排的(推荐、榜单外的热门、搜索)用 `page`(0 起,最多 50)返回 `{items, has_more}`;
  按时间排的用 `cursor`(`"{微秒}_{id}"`,和视频一样)返回 `{items, has_more, next_cursor}`;
- **错误**:开关关着 503(「音乐暂未开放」「论坛暂未开放」「音乐投稿暂未开放」「论坛发帖暂停中」);参数不对 422;
  没权限 403;不存在或看不了 404;限流 429(带 `Retry-After`);
- **时间**一律 ISO 8601 带时区;**日**按北京时间切(`video.bj_day`);
- **计数**字段叫 `plays` / `likes` / `comments` / `collects` / `fans`,整数;
- **登录**:读接口可不登录(`get_current_user_optional`),写接口必须登录且走 `social_user`。

### 5.3 音乐作品状态机(服务端强制,非法迁移 409)

```
draft ──提交(音乐人)──▶ reviewing ──通过(管理员)──▶ published ──下架(音乐人)──▶ withdrawn
  ▲                       │                              │                           │
  │                       └──驳回(管理员)──▶ rejected    └──下架(管理员,带原因)──▶ removed
  │                                            │                                     │
  └────────── 撤回提交(音乐人) ◀── reviewing   └──再提交(音乐人)──▶ reviewing      恢复 / 申诉改判(管理员)──▶ published
withdrawn ──再提交(音乐人)──▶ reviewing        rejected 申诉改判(管理员,换人)──▶ published
```

- 提交的前提:至少 1 首歌、每首都转码完成、有封面、每首都勾了原创 / 授权声明;
- 只有 `draft`、`rejected`、`withdrawn` 能改信息、增删歌曲、删除(软删);
- 申诉:每个驳回或下架决定只能申诉一次,**原审核人不能复核自己的决定**(和视频一样 403);
- 每个决定一行 `music_decisions`,并给音乐人发一条 `system` 互动消息。

歌曲转码状态:`pending → processing → ready | failed`(失败自动重试 3 次,还失败写 `fail_reason`,音乐人可删了重传)。

### 5.4 音乐榜单与每日推荐公式(`services/music_rank.FORMULA` 与下面逐字一致)

```text
收听人数:听满 min(30 秒, 时长一半) 算一次收听,按人去重(登录用户按账号,没登录按设备)
热歌榜分数 = 近7天收听人数 + 3 × 近7天新增喜欢人数 + 5 × 近7天加入歌单人数
新歌榜:只收发布 14 天内的歌,分数 = 近7天收听人数 + 3 × 近7天新增喜欢人数
飙升榜:近24小时收听人数 L 至少 5 人才上榜,分数 = (L − 前24小时收听人数 P) ÷ max(P, 5)
同分按发布时间新的在前,再按歌曲编号;每个榜最多 100 首,同一位音乐人在一个榜里最多 10 首
每日推荐分数 = 热歌榜分数 + 20 × min(我近30天喜欢或听过的同曲风歌数, 10) + 200 × [我关注了这位音乐人] + 20 × min(我喜欢过这位音乐人的歌数, 5)
每日推荐取前 20 首,近7天听过的不推,同一位音乐人最多 3 首;关掉个性化后只按热歌榜分数
推荐歌单分数 = 5 × 近30天新增收藏人数 + 总收藏人数;至少 5 首歌的公开歌单才推荐
```

每一项都下发 `rank: {score, parts: {…每个中间量…}, why: "近7天 35 人收听、4 人加入歌单"}`。
公式参数(7、14、24、30、5、100、10、20、200、3)全部在 `music_rank.PARAMS`,`/music/v1/rank/formula` 原样返回。

### 5.5 收听计数与播放地址

- 客户端在一首歌切走或播完时上报 `POST /music/v1/tracks/{tid}/play {ms_listened, device_id?, context?}`;
  服务端把 `ms_listened` 截到时长以内,满足 §5.4 的门槛且 30 分钟内这个人没算过这首,才写一行 `music_plays`
  并给 `tracks.plays` 加一;同时写「最近播放」(登录用户,留最近 300 首);
- 播放地址 `/music/v1/stream/{tid}/{q}.m4a?u=<用户号,没登录是0>&e=<到期>&s=<签名>`,`q ∈ {std, hq}`;
  签名 `HMAC-SHA256(key=sha256("superz-music-url:" + jwt_secret), "{tid}:{u}:{e}")` 取前 32 位十六进制;
  有效 6 小时;**每次请求重新判权**(作品不是 published 且不是作者本人 / 管理员 → 404);走 `media.file_response`(Range、X-Accel)。

### 5.6 论坛帖子规则

- 正文 1–500 字(按 Unicode 字符数,去掉首尾空白;有图、卡片或投票时正文可以为空);
- **实体**由服务端解析,存进 `entities`,客户端不许自己报:
  - 话题:`#([^\s#…]{1,30})#` 或 `#([^\s#…]{1,30})`(遇到空白、`#`、中英文标点截止),统一小写存 `tag`,原样存 `display`,每帖最多 10 个;
  - 提及:`@([A-Za-z][A-Za-z0-9_]{4,31})`,按 @超级赞号 查人,查不到的不算;每帖最多 10 个;
  - 链接:`https?://…`,最多 3 个;
- 回复:`reply_to_pid` 指向被回复的帖子,`root` 记整串的第一条;被回复帖的 `reply_policy` 不允许、或作者拉黑了我 → 403;
- 引用:`quote_pid`;被引用的帖子删了或下架了,引用照样在,只显示「这条帖子已不可见」;
- 编辑:作者本人、发出 30 分钟内、最多 5 次;每次把旧正文存进 `forum_post_edits`;
- 删除:作者软删;下面的回复保留,被删的那条显示「这条帖子已删除」;
- 投票:2–4 项、每项 1–25 字、时长 5 分钟–7 天;每人一票、不能改;结束后作者和投过票的人收到 `system` 互动消息。

### 5.7 论坛推荐与热门话题公式(`services/forum_rank.FORMULA` 与下面逐字一致)

```text
互动分 E = 点赞人数 + 2 × 转发人数 + 2 × 引用人数 + 3 × 回复人数(都按人去重,只算发帖后 72 小时内)
推荐分 = (E + 1) ÷ (发帖后小时数 + 2)^1.5 × (1 + [我关注了作者]) × (1 + 0.5 × [帖子里有我近30天发过或点过赞的话题])
候选是 72 小时内的原帖(不含回复),作者没被我拉黑、也没拉黑我,不含我的屏蔽词;每屏 20 条,同一作者最多 2 条
关掉个性化后两个方括号都按 0 算
热门话题分数 = 近24小时用过这个话题的人数 + 2 × 近3小时用过的人数;近24小时至少 2 人用过才上榜,最多 20 个;运营隐藏的话题不上榜
```

每条推荐下发 `rank: {score, parts: {likes, reposts, quotes, repliers, hours, following, topic}, why}`。
参数(72、1.5、2、0.5、30、20、24、3)在 `forum_rank.PARAMS`。

### 5.8 互动消息(全站一处)

`social_notifications` 新增目标列:`forum_post_id`、`music_track_id`、`music_comment_id`、`music_release_id`(都可空,删除级联);
`kind` 在原来的 `reply` / `at` / `like` / `system` 之外加 `follow`、`repost`、`quote`。

| 事件 | kind | 目标 | 合并 |
|---|---|---|---|
| 有人回复我的帖子 / 回复里 @ 我 | `reply` / `at` | `forum_post_id` = 那条回复 | 不合并 |
| 有人赞我的帖子 | `like` | `forum_post_id` | `group_key = like:post:<id>` |
| 有人转发 / 引用我的帖子 | `repost` / `quote` | `forum_post_id`(引用时是那条引用帖) | 转发按 `repost:post:<id>` 合并 |
| 有人关注我 | `follow` | —— | `follow:<我>` 按天合并 |
| 有人评论我的歌 / 回复我的歌曲评论 | `reply` | `music_track_id` + `music_comment_id` | 不合并 |
| 有人赞我的歌曲评论 | `like` | `music_comment_id` | `like:mcomment:<id>` |
| 作品过审 / 驳回 / 下架、投票结束、帖子被下架 | `system` | `music_release_id` / `forum_post_id` | 不合并 |

`GET /social/v1/notifications` 的每一条在原字段之外带 `post: {pid, text}`、`track: {tid, title, cover}`、
`release: {rid, title}` 中相应的一个,客户端按有哪个字段决定点开去哪。

### 5.9 分享卡片(聊天消息类型 `card`)

- 发送:`{"kind": "card", "card": {"type": "track|release|playlist|artist|post|video", "id": "<公开编号>"}}`;
- 服务端按 `type` 查出对象,**只有公开可见的才能发**(没过审的作品、私密歌单、已删帖子 → 422),
  存快照 `extra.card = {type, id, title, subtitle, cover, url}`;转发原样带过去;
- 会话列表预览:`[歌曲] 标题`、`[歌单] 标题`、`[专辑] 标题`、`[音乐人] 名字`、`[帖子] 正文前 30 字`、`[视频] 标题`;
- 客户端点卡片按 `url` 走站内链接(`openAppLink`)。

### 5.10 限流(和视频同一套 `ratelimit` 工具,写进 MUSIC-API.md / FORUM-API.md)

| 动作 | 上限 |
|---|---|
| 音乐:喜欢、收藏、加歌单、关注 | 每人每秒 5 次 |
| 音乐:收听上报 | 每人每分钟 120 次 |
| 音乐:评论 | 每 5 秒 1 条、每天 500 条 |
| 音乐:建作品 / 加歌 | 每分钟 20 次、每天 50 首歌 |
| 音乐:搜索 | 每分钟 60 次 |
| 论坛:发帖(含回复、引用) | 每 10 秒 1 条、每小时 60 条、每天 300 条 |
| 论坛:赞、转发、书签 | 每人每秒 5 次 |
| 论坛:浏览上报 | 每人每分钟 120 次 |
| 论坛:搜索 | 每分钟 60 次 |
| 举报 | 每人每分钟 10 次 |

### 5.11 原因代码

共用视频的 `C101`–`C109` 和 `X999`(`services/video.REASON_CODES`),各模块另加:

| 代码 | 意思 |
|---|---|
| `M301` | 非原创且没有授权(侵权) |
| `M302` | 音频不完整(无声、截断、严重失真) |
| `M303` | 歌名 / 封面 / 署名与内容不符 |
| `M304` | 歌词违规 |
| `M305` | 冒充其他音乐人 |
| `F401` | 刷屏、重复发帖 |
| `F402` | 蹭无关话题 |
| `F403` | 恶意引战、人身攻击 |

---

## 6. 架构

```
用户端 lib/music/**   lib/forum/**         后台 admin-web/src/pages/music|forum/**
        │                    │                        │
   /music/v1/**        /forum/v1/**          /admin/music/**  /admin/forum/**
        │                    │                        │
 services/music*.py   services/forum*.py      共用:video.people、follows、social_blocks、
        │                                           social_sanctions、social_notify、moderation
 /media/v1(用途 music)─▶ media:jobs ─▶ workers/media(music_track)─▶ 私密桶 music/t<id>/…/std|hq.m4a
```

模型放 `models_music.py`、`models_forum.py`,在 `models.py` 末尾导入(照 `models_video.py`),各自一个 `MUSIC_MODELS` / `FORUM_MODELS` 清单。

---

## 7. 数据模型(迁移 0143 音乐、0144 论坛)

### 7.1 音乐(`models_music.py`)

| 表 | 关键列 |
|---|---|
| `music_artists` | `id`、`aid`(唯一)、`user_id`(唯一,FK users)、`name`、`name_lc`(唯一)、`bio`、`avatar_url`、`cover_url`、`genres` JSONB、`status`(active / suspended / closed)、`created_at`、`updated_at` |
| `music_releases` | `id`、`rid`、`artist_id`、`title`、`kind`(single / ep / album)、`cover_media_id`(审核前私密)、`cover_url`(过审后公开)、`description`、`genre`、`language`、`release_date`、`status`、`submitted_at`、`published_at`、`reject_code`、`reject_note`、`collects`、`created_at`、`updated_at`、`deleted_at` |
| `music_tracks` | `id`、`tid`、`release_id`、`artist_id`、`title`、`track_no`、`duration_ms`、`source_media_id`、`renditions` JSONB `[{q,key,bitrate,size}]`、`transcode_status`、`fail_reason`、`lyrics`、`lyrics_kind`(none / plain / lrc)、`credits` JSONB `{lyricist:[],composer:[],arranger:[],producer:[]}`、`explicit`、`declaration`(original / authorized)、`plays`、`likes`、`comments`、`created_at`、`updated_at` |
| `music_playlists` | `id`、`pid`、`owner_id`、`title`、`description`、`cover_url`、`tags` JSONB、`is_public`、`track_count`、`collects`、`created_at`、`updated_at`、`deleted_at` |
| `music_playlist_tracks` | PK(`playlist_id`,`track_id`)、`position`、`added_at`、`added_by` |
| `music_track_likes` / `music_playlist_collects` / `music_release_collects` | PK(`user_id`,目标)、`created_at` |
| `music_plays` | `id`、`track_id`、`listener_key`、`user_id`(可空)、`ms_listened`、`created_at`、`day`(北京日);留 60 天 |
| `music_history` | PK(`user_id`,`track_id`)、`played_at`;每人留最近 300 首 |
| `music_comments` | `id`、`track_id`、`user_id`、`root_id`、`parent_id`、`reply_to_user_id`、`text`、`mentions` JSONB、`likes`、`reply_count`、`status`、`created_at` |
| `music_comment_likes` | PK(`user_id`,`comment_id`) |
| `music_reports` | `id`、`reporter_id`、`target_type`(track / release / comment / playlist / artist)、`target_id`、`reason_code`、`note`、`contact`(版权投诉必填)、`status`、`handled_by`、`handled_at`、`created_at` |
| `music_decisions` | `id`、`release_id`、`admin_id`、`action`、`reason_code`、`note`、`appeal_text`、`appeal_at`、`appeal_result`、`appeal_by`、`created_at` |
| `music_user_settings` | PK `user_id`、`personalize`(缺省 true) |

### 7.2 论坛(`models_forum.py`)

| 表 | 关键列 |
|---|---|
| `forum_posts` | `id`、`pid`(唯一)、`author_id`、`text`、`entities` JSONB、`media` JSONB `[{url,w,h}]`、`card` JSONB `{type,id}`、`reply_to_id`、`reply_to_user_id`、`root_id`、`quote_of_id`、`reply_policy`(all / following / mentioned)、`status`(visible / deleted / removed)、`removed_code`、`edited_at`、`edit_count`、`replies`、`reposts`、`quotes`、`likes`、`bookmarks`、`views`、`created_at`、`deleted_at` |
| `forum_post_edits` | `id`、`post_id`、`text`、`entities`、`created_at` |
| `forum_reposts` | `id`、`user_id`、`post_id`、`created_at`,唯一(`user_id`,`post_id`) |
| `forum_likes` / `forum_bookmarks` | PK(`user_id`,`post_id`)、`created_at` |
| `forum_tags` | `id`、`tag`(唯一,小写)、`display`、`posts`、`hidden`(运营隐藏)、`hidden_code`、`last_used_at` |
| `forum_post_tags` | PK(`post_id`,`tag_id`)、`author_id`、`created_at` |
| `forum_mentions` | PK(`post_id`,`user_id`) |
| `forum_polls` | PK `post_id`、`options` JSONB `[{text,votes}]`、`ends_at`、`total`、`closed_notified` |
| `forum_poll_votes` | PK(`post_id`,`user_id`)、`option`、`created_at` |
| `forum_pins` | PK `user_id`、`post_id` |
| `forum_mute_words` | PK(`user_id`,`word`)、`created_at`;每人最多 100 个 |
| `forum_view_days` | PK(`post_id`,`day`,`viewer_key`);留 8 天 |
| `forum_reports` | `id`、`reporter_id`、`post_id`、`reason_code`、`note`、`status`、`handled_by`、`handled_at`、`created_at` |
| `forum_decisions` | `id`、`post_id`、`admin_id`、`action`、`reason_code`、`note`、`appeal_text`、`appeal_at`、`appeal_result`、`appeal_by`、`created_at` |
| `forum_user_settings` | PK `user_id`、`personalize`(缺省 true) |

---

## 8. 接口清单(返回形状规范性:客户端按这里写,服务端按这里实现)

### 8.1 共用对象

```jsonc
// 歌曲卡片 track
{"tid":"mt…","title":"…","duration_ms":215000,"cover":"https://…/img/music_cover/…jpg","explicit":false,
 "genre":"pop","genre_name":"流行","plays":1234,"likes":56,"comments":7,"liked":false,
 "artist":{"aid":"ma…","name":"…","user_id":42},"release":{"rid":"mr…","title":"…","kind":"single"},
 "published_at":"2026-09-15T12:00:00+08:00"}
// 作品卡片 release
{"rid":"mr…","title":"…","kind":"album","cover":"…","artist":{"aid":"ma…","name":"…","user_id":42},
 "track_count":8,"release_date":"2026-09-15","collects":3,"published_at":"…"}
// 歌单卡片 playlist
{"pid":"mp…","title":"…","cover":"…","track_count":20,"collects":5,"plays":100,"is_public":true,
 "owner":{person},"tags":["华语"]}
// 音乐人 artist(列表里的简版只有 aid/name/avatar/user_id/fans)
{"aid":"ma…","name":"…","bio":"…","avatar":"…","cover":"…","genres":["pop"],"user_id":42,
 "fans":10,"followed":false,"track_count":12}
// 帖子 post
{"pid":"fp…","author":{person},"text":"…","entities":{"tags":[{"tag":"周末","display":"周末"}],
  "mentions":[{"id":7,"username":"xiaoming"}],"links":["https://…"]},
 "media":[{"url":"/img/forum/u42-….jpg","w":1080,"h":1440}],
 "card":{"type":"track","id":"mt…","title":"…","subtitle":"…","cover":"…","url":"https://chaojizan.cc/music/t/mt…"}|null,
 "quote":{post,不再嵌套 quote}|{"pid":"fp…","unavailable":true}|null,
 "reply_to":{"pid":"fp…","author":{person}}|null,"root_pid":"fp…",
 "poll":{"options":[{"text":"…","votes":3}],"total":5,"ends_at":"…","closed":false,"voted":null}|null,
 "reply_policy":"all","can_reply":true,
 "counts":{"replies":1,"reposts":2,"quotes":0,"likes":9,"bookmarks":1,"views":120},
 "viewer":{"liked":false,"reposted":false,"bookmarked":false},
 "edited":false,"edited_at":null,"created_at":"…","pinned":false}
// 投票:没投过、没结束、又不是作者时,每项的 votes 和 total 是 null(投票前看不到结果,和 X 一样)
// 卡片:服务端按 {type,id} 现查,查不到(删了、没过审、私密)时 card 是 {"type":…,"id":…,"unavailable":true}
// 不可见的帖子(删了、下架了、拉黑关系)在串里占位:
{"pid":"fp…","unavailable":true,"reason":"deleted|removed|blocked"}
// 时间线条目
{"type":"post","post":{post},"rank":{…}?}  |  {"type":"repost","by":{person},"at":"…","post":{post}}
```

### 8.2 音乐(前缀 `/music/v1`,路由级依赖 `music_on`)

| 方法 路径 | 说明 | 返回 |
|---|---|---|
| GET `/home` | 发现页 | `{daily:[track≤6], daily_personalized, playlists:[playlist≤6], new_tracks:[track≤6], charts:[{key,name,top:[track≤3]}], genres:[{key,name}]}` |
| GET `/genres` | 曲风表 | `[{key,name}]` |
| GET `/genres/{key}/tracks?page=` | 这个曲风下的歌,按热歌榜分数 | `{items:[track+rank], has_more}` |
| GET `/tracks/{tid}` | 歌曲详情 | track + `lyrics_kind`、`credits`、`declaration`、`stream:{std,hq\|null,expires_at}` |
| GET `/tracks/{tid}/lyrics` | 歌词 | `{kind, text}` |
| GET `/tracks/{tid}/stream` | 重新签地址 | `{std, hq, expires_at}` |
| GET `/stream/{tid}/{q}.m4a` | 音频文件(签名见 §5.5) | 音频,支持 Range |
| POST `/tracks/{tid}/play` | 收听上报 `{ms_listened, device_id?, context?}` | `{counted}` |
| POST / DELETE `/tracks/{tid}/like` | 喜欢 / 取消 | `{liked, likes}` |
| GET `/tracks/{tid}/comments?sort=hot\|new&page=\|cursor=` | 评论(第一页带 `hot:[≤3]`) | `{items:[comment], has_more, next_cursor?, total, hot?}` |
| GET `/comments/{id}/replies?cursor=` | 楼中楼 | page |
| POST `/tracks/{tid}/comments` | `{text, parent_id?}` | comment `{id, user:{person}, text, likes, liked, reply_count, reply_to:{person}?, created_at, mine}` |
| DELETE `/comments/{id}` | 删自己的(或歌的作者删) | `{ok}` |
| POST / DELETE `/comments/{id}/like` | | `{liked, likes}` |
| GET `/me/likes?cursor=` | 我喜欢的音乐 | page of track |
| GET `/me/history` / DELETE `/me/history` | 最近播放(≤300) / 清空 | `{items:[track]}` |
| GET `/me/playlists` | 我的歌单 | `{created:[playlist], collected:[playlist], collected_releases:[release]}` |
| GET / PUT `/me/settings` | `{personalize}` | 同 |
| POST `/playlists` | `{title, description?, is_public?, tags?, cover_url?}` | 歌单详情 |
| GET `/playlists/{pid}` | 歌单详情 | playlist + `description, created_at, updated_at, collected, tracks:[track]` |
| PATCH / DELETE `/playlists/{pid}` | 改 / 删(主人) | 歌单详情 / `{ok}` |
| POST `/playlists/{pid}/tracks` | `{tids:[…]}`(去重,≤1000 首) | `{added, track_count}` |
| DELETE `/playlists/{pid}/tracks/{tid}` | | `{ok, track_count}` |
| PUT `/playlists/{pid}/order` | `{tids:[…]}` 全量新顺序 | `{ok}` |
| POST / DELETE `/playlists/{pid}/collect` | 收藏别人的公开歌单 | `{collected, collects}` |
| GET `/playlists/recommended?page=` | 推荐歌单(§5.4) | `{items:[playlist+rank], has_more}` |
| GET `/releases/{rid}` | 作品详情 | release + `description, genre, language, tracks:[track], collected` |
| POST / DELETE `/releases/{rid}/collect` | 收藏专辑 | `{collected, collects}` |
| GET `/artists/{aid}` | 音乐人主页 | artist + `hot_tracks:[track≤10], releases:[release]` |
| GET `/artists/{aid}/tracks?page=` | 全部歌曲(按收听) | page |
| GET `/charts` | 三个榜的摘要 | `[{key, name, updated_at, top:[track≤3]}]` |
| GET `/charts/{key}` | 榜单全表,`key ∈ hot/new/rising` | `{key, name, updated_at, items:[{rank_no, track, rank}]}` |
| GET `/daily` | 每日推荐 | `{date, personalized, items:[track+rank]}` |
| GET `/rank/formula` | 公式和参数 | `{formula, params}` |
| GET `/search?q=&type=track\|artist\|release\|playlist&page=` | 搜索(`ILIKE`,同视频口径) | page |
| POST `/reports` | `{target_type, target_id, reason_code, note?, contact?}` | `{ok}` |

**音乐人中心**(`/music/v1/studio`,登录;上传类还要 `music_upload_on`):

| 方法 路径 | 说明 |
|---|---|
| GET `/studio/me` | `{artist:{…}\|null}` |
| POST `/studio/artist` | 开通 `{name, bio?, genres?}` |
| PATCH `/studio/artist` | 改 `{name?, bio?, genres?, avatar_url?, cover_url?}`(头像、横幅走公开图片用途 `music_cover`) |
| GET `/studio/releases` | 我的作品(含 `status`、`reject_code/note`、`tracks:[带 transcode_status]`、`can_appeal`) |
| POST `/studio/releases` | 建草稿 `{title, kind, genre, language, description?, release_date?, cover_media_id?}` |
| PATCH / DELETE `/studio/releases/{rid}` | 改 / 删(只在 draft / rejected / withdrawn) |
| POST `/studio/releases/{rid}/tracks` | 加歌 `{title, media_id, lyrics?, credits?, explicit?, declaration}`(`media_id` 是 `/media/v1` 用途 `music`、类型 `audio_source` 传上来的) |
| PATCH / DELETE `/studio/tracks/{tid}` | 改 / 删歌(只在可编辑状态) |
| PUT `/studio/releases/{rid}/order` | `{tids}` |
| POST `/studio/releases/{rid}/submit` / `cancel` / `withdraw` | 提交审核 / 撤回提交 / 已发布的下架 |
| POST `/studio/releases/{rid}/appeal` | `{text}`(对最近一次驳回或下架) |
| GET `/studio/stats?days=30` | `{plays, listeners, likes, fans, per_day:[{day, plays, listeners}], top_tracks:[track]}` |

**后台**(`/admin/music`,`require_role("admin")`):`GET /review`(待审作品,带能播的地址)、`POST /releases/{rid}/decide {action: approve|reject, reason_code?, note?}`、
`POST /releases/{rid}/remove {reason_code, note}`、`POST /releases/{rid}/restore`、`GET /reports?status=`、`POST /reports/{id}/handle {action: remove_target|dismiss, reason_code?, note?}`、
`GET /artists?q=`、`POST /artists/{aid}/suspend|restore`、`GET /appeals`、`POST /appeals/{decision_id}/resolve {result: upheld|overturned, note}`(不能是原审核人)、`GET /stats`、`GET /reason-codes`。

上传:`/media/v1` 的 `PURPOSES` 加 `"music": {"audio_source", "cover"}`,受 `music_upload_enabled` 管;`audio_source` 上限 200MB。
公开图片:`storage.PURPOSES` 加 `"music_cover": False`(歌单封面、音乐人头像 / 横幅)。

### 8.3 论坛(前缀 `/forum/v1`,路由级依赖 `forum_on`;发帖类另加 `forum_post_on`)

| 方法 路径 | 说明 | 返回 |
|---|---|---|
| GET `/timeline/foryou?page=` | 推荐(§5.7) | `{items:[{type:"post", post, rank}], has_more}` |
| GET `/timeline/following?cursor=` | 关注的人的帖子和转发,倒序 | `{items:[timeline item], has_more, next_cursor}` |
| POST `/posts` | `{text, media?:[url], card?:{type,id}, quote_pid?, reply_to_pid?, poll?:{options:[…], minutes}, reply_policy?}` | post |
| GET `/posts/{pid}` | 详情 + 上文 | `{post, ancestors:[post\|占位]}` |
| GET `/posts/{pid}/replies?sort=top\|new&cursor=` | 回复 | page of post |
| PATCH `/posts/{pid}` | `{text}`(§5.6 编辑规则) | post |
| GET `/posts/{pid}/edits` | 编辑历史 | `[{text, created_at}]` |
| DELETE `/posts/{pid}` | 删自己的 | `{ok}` |
| POST / DELETE `/posts/{pid}/like` | | `{liked, likes}` |
| POST / DELETE `/posts/{pid}/repost` | | `{reposted, reposts}` |
| POST / DELETE `/posts/{pid}/bookmark` | | `{bookmarked}` |
| GET `/posts/{pid}/quotes?cursor=` / `/likers?cursor=` | 引用 / 点赞的人 | page |
| POST `/posts/{pid}/vote` | `{option}` | poll |
| POST `/posts/views` | `{pids:[≤50], device_id?}` | `{ok}` |
| POST `/posts/{pid}/pin` / DELETE `/pin` | 置顶到主页 / 取消 | `{ok}` |
| POST `/posts/{pid}/appeal` | `{text}` | `{ok}` |
| GET `/users/{uid}/profile` | 主页 | `{user:{person}, bio, joined_at, posts, following, fans, followed, follows_you, pinned:post\|null}` |
| GET `/users/{uid}/posts?tab=posts\|replies\|media\|likes&cursor=` | 主页各页签 | page(`posts` 页签含转发,是 timeline item) |
| GET `/me/bookmarks?cursor=` | 书签 | page of post |
| GET / POST / DELETE `/me/mute-words` | `{word}` | `[word]` |
| GET / PUT `/me/settings` | `{personalize}` | 同 |
| GET `/tags/trending` | 热门话题 | `{items:[{tag, display, authors_24h, authors_3h, score}], updated_at}` |
| GET `/tags/{tag}/posts?sort=top\|new&cursor=\|page=` | 话题下的帖子 | page |
| GET `/search?q=&type=posts\|users\|tags&page=` | 搜索 | page |
| GET `/rank/formula` | 公式和参数 | `{formula, params}` |
| POST `/reports` | `{pid, reason_code, note?}` | `{ok}` |

**后台**(`/admin/forum`):`GET /reports?status=`、`POST /reports/{id}/handle {action: remove|dismiss, reason_code?, note?}`、`GET /posts?q=&author=`、
`POST /posts/{pid}/remove {reason_code, note}`、`POST /posts/{pid}/restore`、`GET /appeals`、`POST /appeals/{decision_id}/resolve`、
`GET /tags?hidden=`、`POST /tags/{tag}/hide {reason_code, note}` / `unhide`、`GET /stats`、`GET /reason-codes`。

图片:`storage.PURPOSES` 加 `"forum": False`(公开),走现有的 `POST /uploads`(`purpose=forum`);发帖时 `media` 里的每个地址必须是
`/img/forum/u<我>-…`(本人上传的)。

**卡片解析**:新文件 `services/cards.py`(论坛后端建)—— `register(type, resolver)` + `async resolve(db, type, id, viewer_id) -> dict | None`,
返回 `{type, id, title, subtitle, cover, url}`;先注册 `video`、`post`,音乐的 `track` / `release` / `playlist` / `artist`
由音乐后端在 `services/music.py` 里提供 `async card_of(db, type, public_id, viewer_id)`,合并时接进来;聊天的 `card` 消息(§5.9)也用它。

### 8.4 全站共用(#377)

| 方法 路径 | 说明 |
|---|---|
| POST / DELETE `/social/v1/users/{id}/follow` | 关注 / 取消(不挂任何模块开关),返回 `{followed, fans}`;关注发 `follow` 互动消息 |
| GET `/social/v1/users/{id}/followers?cursor=` / `following?cursor=` | 粉丝 / 关注列表,每项 `person + followed` |
| GET `/social/v1/users/{id}/follow-stats` | `{fans, following, followed, follows_you}` |

---

## 9. 客户端(用户端)

- **音乐** `lib/music/`:`api.dart`(照 `video/api.dart`)、`models.dart`、`player/`(`MusicPlayer` 单例:队列、模式、音质、
  歌词同步、收听上报、签名过期自动重签、定时关闭;`MusicMiniBar`、`PlayerPage`、`QueueSheet`)、`pages/`
  (发现、榜单、每日推荐、歌单、作品、音乐人、搜索、评论、我的音乐、歌单编辑、加到歌单)、`studio/`(开通音乐人、作品编辑、
  上传歌曲(分片)、歌词和署名、提交审核、申诉、数据)、`nav.dart`(`openMusicHome`、`openTrack`、`openPlaylist`…);
- **论坛** `lib/forum/`:`api.dart`、`models.dart`、`widgets/`(`PostTile`:头像、名字、@号、时间、正文实体可点、九宫格图、
  卡片、引用、投票、操作栏)、`pages/`(首页两条时间线、发帖、帖子详情(串)、个人主页、探索(热门话题 + 搜索)、话题页、
  书签、关注 / 粉丝、编辑历史、点赞的人、引用、屏蔽词、设置)、`nav.dart`(`openForumHome`、`openPost`、`openForumProfile`、`openTag`);
- 宽屏照 [三端响应式](DEV-PROMPTS-33.md) 的判据:内容限宽、双栏;所有页面用 `SzPageScaffold` / 设计令牌,不许裸颜色;
- 用户看得到的界面文字按 [可配置文案](../server/app/services/copy_registry.py) 的原则:入口名字走登记表。

## 10. 里程碑与分工

1. #377 统一关注(先做,两边都要用)—— 主会话;
2. 并行:#378 音乐后端、#379 音乐客户端、#380 论坛后端、#381 论坛客户端 —— 各一个编码 agent,各自一个 git worktree;
3. #382 合并与打通(金刚区、分享卡片、互动消息合并、个人主页、迷你播放器、站内链接、注销导出、合规、文档)—— 主会话;
4. 全量回归(单测两遍、全部 e2e、三端检查)→ push → 发版 → 部署 → 生产开开关。

## 11. 提示词

### #377 统一关注与关注通知

`POST/DELETE /social/v1/users/{id}/follow`、`GET followers / following / follow-stats`(§8.4),写 `follows` 表,调 `video_interact.set_follow`
(视频老接口改调同一个函数);关注发 `follow` 互动消息(按天合并);不挂模块开关;不能关注自己、被对方拉黑不能关注;
e2e `e2e_social_follow`。

### #378 音乐后端

按 §3、§5.3–§5.5、§5.10、§5.11、§7.1、§8.2 实现:模型与迁移 0143(含 `social_notifications` 的 `music_*` 目标列)、上传用途、
`workers/media` 的 `music_track` 任务(ffprobe 时长、loudnorm、AAC 128k/256k、失败重试、删源)、状态机、审核与申诉、
签名播放、收听计数、喜欢、歌单、收藏、评论、榜单与每日推荐(公式公开、带中间量)、搜索、举报、音乐人中心、后台接口、
注销清理(`purge_user`)、导出、开关(`MUSIC_FLAGS` 进 `flags.py`、`_KNOWN_FLAGS`、`/config.features.music / music_upload`)、
`docs/MUSIC-API.md`;后台页面(`admin-web` 社区治理下「音乐审核」「音乐举报」「音乐人」);
单测(状态机、公式与文档逐字一致、不变量)+ e2e(`e2e_music_studio`、`e2e_music_listen`、`e2e_music_social`、`e2e_music_review`)。

### #379 音乐客户端

按 §2.1、§8.1–§8.2、§9 实现 `lib/music/**` 全部页面和播放器;iOS `UIBackgroundModes: audio`、安卓 `WAKE_LOCK`;
widget 测试(播放器队列与模式、LRC 解析与高亮、发现页、音乐人中心表单)。

### #380 论坛后端

按 §3、§5.6–§5.8、§5.10、§5.11、§7.2、§8.3 实现:模型与迁移 0144(含 `social_notifications.forum_post_id`、kind `repost` / `quote`)、
发帖与实体解析、回复串、转发、引用、点赞、书签、浏览、编辑、删除、投票、置顶、谁能回复、拉黑与屏蔽词、两条时间线、
热门话题、搜索、举报、下架与申诉、后台接口、注销清理、导出、开关(`FORUM_FLAGS`)、`docs/FORUM-API.md`;
后台页面(「论坛举报」「帖子管理」「热门话题」);单测(实体解析、公式、不变量)+ e2e(`e2e_forum_posts`、`e2e_forum_timeline`、`e2e_forum_moderation`)。

### #381 论坛客户端

按 §2.2、§8.1、§8.3、§9 实现 `lib/forum/**`;widget 测试(帖子正文实体渲染、发帖字数与图片上限、时间线分页、投票)。

### #382 合并与打通

金刚区两格(`kChannels`、首页点击、`CHANNELS_FALLBACK`、后台开关页和 `known` 集合、文案登记表、官网)、聊天 `card` 消息(§5.9)、
互动消息合并(§5.8,客户端「互动消息」一处)、个人主页(关注按钮、他的动态 / 视频 / 音乐)、迷你播放器常驻、站内链接
(`/music/…`、`/forum/…`)、合规清单第 17、18 条、文档索引。
