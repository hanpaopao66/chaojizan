# 开发提示词 #339–#376:底部「订单」换成「消息」和「视频」—— 消息对标 Telegram,视频对标 B 站(含抖音式竖屏)

用户端底部导航从「首页 / 订单 / 我的」改成「首页 / 消息 / 视频 / 我的」:

- **消息**:照 Telegram 的聊天做 —— 私聊、群组、频道、收藏夹(Saved Messages),
  文字 / 图片 / 相册 / 视频 / 文件 / 语音 / 位置 / 名片 / 投票 / 贴纸 / GIF / 骰子,
  回复、转发、编辑、双向删除、表情回应、置顶、已读、正在输入、在线状态、草稿、定时发送、
  搜索、会话分组、免打扰、归档、推送、1 对 1 语音 / 视频通话、机器人;
- **视频**:照 B 站做 —— 投稿(分 P、转码、审核)、播放器(清晰度 / 倍速 / 手势 / 进度预览)、
  弹幕、评论(楼中楼)、点赞 / 投币 / 收藏 / 分享(三连)、关注、UP 主空间、创作中心、
  推荐 / 热门 / 关注 / 分区 / 排行榜、搜索、历史 / 稍后再看 / 收藏夹;
  **竖屏**照抖音做:上下滑、自动播放、双击点赞、评论弹层、左滑进 UP 主空间。

「订单」不是删掉,是**搬家**:「我的」页的订单四格、首页的进行中订单条、推送和支付回跳都直达订单页。

## 怎么用这份文档

- §1–§8 是**设计与规范**,每条提示词都默认你读过它们。§5 是规范性的:实现、文档、测试三处逐字一致;
- §9 是里程碑与依赖顺序;§10 的每一条 `#3xx` 是**一条可以单独交给编码 agent 的提示词**:
  背景、要做什么、落在哪些文件、验收标准、测试、明确不做;
- §4 的「决定」:用户要求「先规划再开发、完全可以使用」,所以这里**直接按推荐执行**,
  另一个选项和代价照写,之后要改哪条再改;
- 和 Telegram / B 站**刻意不一样**的地方都写了理由(§2),不是漏做。

---

## 1. 现状与缺口(从代码里读出来的,不是印象)

| 东西 | 位置 | 现状 |
|---|---|---|
| 底部导航 | `apps/user_app/lib/main.dart` `HomePage`(`SzNavScaffold` 三项:首页 / 订单 / 我的,`IndexedStack` 保活、只建访问过的 tab) | 订单是第 1 个 tab;宽屏自动换成左侧栏(#295) |
| 订单列表 | `main.dart` `OrdersTab`(频道条 + 筛选,`onCounts` 回报券包张数给顶栏「券包 · N」) | 只能作为 tab 出现,没有独立页面 |
| 「我的」订单四格 | `main.dart` `ProfileView` → `onOpenOrders(filter)` → `HomePage._openOrders` **切 tab** | 去掉订单 tab 后这条路断,要改成 push 独立订单页 |
| 消息中心 | `apps/user_app/lib/messages_page.dart` `MessageCenterPage`:平台公告 + 近 30 天订单状态流水;首页铃铛红点 | 不是聊天,没有会话概念 |
| 订单内聊天 | `packages/shared/lib/src/chat_page.dart` `OrderChatPage`(三端共用,**3 秒轮询兜底**)+ `routers/orders.py` `_chat_context` 等;未读计数放 Redis `chat:unread:{order}:{user}` | 只在订单里,和人没有长期关系;结单 2 小时后只读 |
| 实时推送 | `server/app/ws.py` `ConnectionManager`:**进程内**字典,两个主题(`order:` 无关用户、`merchant:`),token 放在 URL 查询串里 | 没有按用户的连接、没有 Redis 分发、没有断线补齐 |
| 上传 | `routers/uploads.py`:**只收图片**(jpg/png/webp/heic 转 jpg),单张 5MB,按用途分公开桶 `/img/` 和私密桶 `/files/` | 没有视频、文件、语音;没有分片续传 |
| 转码 | 镜像里**有 ffmpeg**(`server/Dockerfile`,明厨亮灶黑屏检测在用) | 没有转码队列;api 是单进程 uvicorn(`--workers 1`),重活不能放请求里 |
| 视频播放 | 用户端依赖里有 `video_player`(明厨亮灶 HLS) | 没有自带控件、弹幕、清晰度 |
| 推送 | `services/push.py` JPush,`push_to_user` / `fanout`,每次推送都记日志 | 没有聊天类推送 |
| 用户资料 | `users.name`、`users.avatar_url`(头像上传走图片审核队列) | 没有 @用户名、签名、隐私设置、拉黑、关注 |
| 实名 | `UserIdentity`(按需触发,酒类年龄核验在用) | 发视频、建公开群要用它 |
| 开关 | `PlatformFlag` + 管理后台「平台开关」页(`_KNOWN_FLAGS`) | 新功能照这个挂急停闸 |
| 搜索 | `routers/merchants.py` 用 `ILIKE`(注释写了为什么不用 pg_trgm:中文三元组要 3 个字才有选择性) | 视频搜索照这个口径 |
| 数据库扩展 | 只有 `plpgsql`、`postgis` | 不引新扩展 |

缺口:社交关系、会话、消息、实时同步、多媒体、音视频通话、机器人、视频平台 —— **全部是新的**。

---

## 2. 对标:抄什么、不抄什么

### 2.1 消息 vs Telegram

| Telegram | 我们 | 里程碑 / 理由 |
|---|---|---|
| 私聊、基础群 / 超级群、频道、Saved Messages | 私聊、群组(统一成一种,上限见 D7)、频道、收藏夹 | M1 / M2 |
| @username(5–32 位,大小写不敏感,和群 / 频道共用一个命名空间) | 同 | M0 |
| 按手机号找人、通讯录同步 | 只做**完整手机号精确匹配**(可在隐私里关),**不做通讯录上传**(D2) | 隐私 |
| 消息实体:粗体 / 斜体 / 下划线 / 删除线 / 剧透 / 行内代码 / 代码块 / 链接 / 提及 / 话题 | 同,偏移量用 UTF-16 码元(和 TG、Dart 字符串一致) | M1 |
| 链接预览 | 同,服务端取 OG 信息,**防 SSRF**(只许公网 http/https、限大小限时) | M2 |
| 图片、相册(≤10)、视频、文件、语音(波形、倍速、已听)、圆形视频消息 | 同;圆形视频消息 M5 | M1 / M5 |
| 贴纸(静态 / TGS 动画 / 视频)、GIF 搜索 | 静态贴纸包(用户自建 + 内置一套大表情),GIF 转无声 MP4 循环;**不做 TGS、不接境外 GIF 搜索**(D17、D18) | M2 |
| 位置、实时位置 | 位置;实时位置不做 | M1 |
| 名片、投票 / 测验、骰子 | 同 | M1 / M2 |
| 回复、转发(可隐藏来源)、编辑(48 小时内)、为双方删除、复制、多选 | 同 | M1 |
| 表情回应(每人最多 3 个,群管理员限定可用表情) | 同 | M2 |
| 置顶消息(多条)、已读(私聊双勾、≤100 人群的「已读名单」7 天内) | 同 | M1 / M2 |
| 正在输入 / 录音 / 上传中 | 同 | M1 |
| 在线状态、最后上线(隐私:所有人 / 联系人 / 没有人,隐藏时显示「最近 / 一周内 / 一月内」) | 同 | M1 |
| 草稿多端同步、定时发送、静音发送 | 同 | M2 |
| 会话置顶(5)、归档、免打扰(1 小时 / 8 小时 / 2 天 / 永久)、标记未读、清空记录、分组(10) | 同 | M1 / M2 |
| 全局搜索、会话内搜索、共享媒体 / 文件 / 链接 / 语音页 | 同 | M2 |
| 群:管理员细分权限、自定义头衔、邀请链接(过期 / 次数 / 需审批)、入群申请、禁言 / 封禁(限时)、慢速模式、成员列表 | 同 | M2 |
| 频道:广播、订阅者、浏览量、署名、静默发布、公开链接 | 同 | M2 |
| 频道评论(关联讨论组)、群话题(Topics)、快拍(Stories)、群语音 / 视频、直播 | **这一批不做**(D22) | 复杂度高、使用少 |
| 秘密聊天(端到端加密、阅后即焚) | **不做**(D3) | 合规 |
| 1 对 1 语音 / 视频通话 | 同,WebRTC + 自建 TURN | M5 |
| Bot API、BotFather、内联键盘、命令菜单、Mini App 按钮 | Bot API 子集;机器人在**开发者后台**创建(和小程序平台同一个开发者身份);机器人能打开小程序 | M5 |
| Premium、Stars、付费消息、商业账号 | **不做** | S4 |
| 多端同步(pts / getDifference) | 同一个思路:每会话事件序号 + 每用户事件序号 + 断线补齐接口 | M0 |

### 2.2 视频 vs B 站 / 抖音

| B 站 / 抖音 | 我们 | 里程碑 / 理由 |
|---|---|---|
| BV 号 | `sv` + 10 位 base58 随机(D19),不暴露投稿量,也不冒用 BV 号 | M3 |
| 投稿:标题 / 封面 / 分区 / 标签 / 简介 / 自制或转载 / 分 P / 定时发布 | 同(定时发布 = 审核通过后到点才公开) | M3 |
| 先审后发 | 同(D10) | M3 |
| DASH 自适应码率 | **MP4 多档位**(360 / 480 / 720 / 1080),渐进下载 + 手动 / 自动清晰度(D9) | M3 |
| 播放器:倍速、清晰度、全屏、双击暂停、横滑快进、左侧亮度右侧音量、长按 3 倍速、进度条缩略图、续播、自动连播 | 同 | M3 |
| 弹幕:滚动 / 顶部 / 底部、颜色、字号、发送、屏蔽词、不透明度 / 速度 / 显示区域、高能进度条 | 同 | M3 |
| 评论:楼中楼、点赞点踩、热度 / 时间排序、UP 主置顶和删除、@ | 同 | M3 |
| 点赞、投币(1–2 枚)、收藏(收藏夹)、分享、长按三连 | 同;**硬币是纯积分**:不能充值、不能提现、不能买东西(D13) | M3 |
| 充电、大会员、B 币、直播、番剧、专栏、动态 | **不做**(S4、D14、D15) | 付费 / 许可 |
| 关注、粉丝、UP 主空间、私信 | 同;私信直接进「消息」 | M4 |
| 推荐(个性化黑盒)、热门、每周必看、排行榜、分区 | 推荐 = **公开公式**(热度 × 时间衰减,可选关注 / 常看分区加权,**可一键关闭个性化**),热门 / 排行榜同一套公式(D12、S3、S9) | M4 |
| 搜索:综合 / 最多播放 / 最新 / 最多弹幕,时长筛选,热搜 | 同;热搜要求 24 小时内至少 5 个不同的人搜过才上榜(防刷) | M4 |
| 历史、稍后再看、收藏夹 | 同 | M4 |
| 创作中心:稿件管理、数据 | 同 | M3 / M4 |
| 消息中心:回复我的 / @我的 / 收到的赞 / 系统通知 | 进「消息」tab 的「互动消息」 | M4 |
| 抖音竖屏:上下滑、自动播放循环、双击点赞、右侧栏(头像关注 / 赞 / 评论 / 收藏 / 分享)、进度条拖动、长按菜单、左滑进主页 | 同 | M4 |
| 视频里挂商品 | 只许挂**本平台的店**(探店),要声明有无合作,有合作就标「合作」;平台不收推广费(D16) | M4 |

---

## 3. 不变量(先于功能定死;每条都要有守卫测试,守卫要先弄红一次)

- **S1 私密内容只给参与者。** 私聊、非公开群的消息和媒体只有成员能读;媒体每次下载都鉴权;
  离开 / 被移出后读不到离开之后的内容。守卫:e2e 用非成员拿消息、事件、媒体、已读名单,一律 403 / 404。
- **S2 手机号不外露。** 社交相关的任何响应里都没有**别人**的手机号;按手机号找人只返回那个人的资料,不回显号码。
  守卫:e2e 扫全部社交接口的响应,不含对方手机号(先拿自己的号喂给探测器,认得出来才算数)。
- **S3 不卖流量。** 推荐、热门、排行榜、搜索、频道 / 群的公开发现,排序全是**公开的纯函数**,输入只有公开字段;
  视频和社交相关的表里**不允许出现** `bid` / `boost` / `paid` / `promoted` / `rank_score` 这类列 —— 和小程序目录 I3 同一个做法。
  守卫:单测扫模型列名 + 排序函数的输入。
- **S4 不收钱。** 这一批没有打赏、充电、会员、付费消息、虚拟币充值;硬币不能充值、提现、兑换任何东西。
  守卫:单测扫模型、路由、SDK 方法名里没有付款相关的名字;硬币只有「每日登录、投稿过审」两个来源。
- **S5 用户的数据用户说了算。** 能导出自己的聊天记录(JSON + 媒体)和自己的投稿;注销账号级联删除消息正文、媒体、投稿、弹幕、评论;
  私聊里「为双方删除」就是两边都没了。守卫:e2e 注销后原来的消息、媒体、视频地址全部不可访问。
- **S6 每个处罚都有原因、能申诉、换人复核。** 视频驳回 / 下架、群 / 频道封禁、账号禁言都带原因代码和说明;
  申诉必须由另一名审核员处理(同小程序 I5)。
- **S7 拉黑立即生效、双向隔离。** 被拉黑的人不能给你发私信、不能拉你进群、看不到你的在线状态和头像更新、
  不能评论你的视频、他的弹幕和评论对你不显示。守卫:e2e 拉黑后逐项断言。
- **S8 管理员看私聊要留痕。** 平台技术上能读私聊(服务端存储,D3),规则只许在「被举报的那几条消息」范围内查看,
  每次查看写审计日志、次数在透明中心公示(D21)。守卫:查看接口不带举报单号就拒;e2e 断言审计日志多了一条。
- **S9 个性化推荐可以一键关闭。** 关掉之后「推荐」和未登录用户看到的完全一致(《互联网信息服务算法推荐管理规定》第十七条)。
  守卫:e2e 关掉后两份结果逐条相等。
- **S10 消息不丢、不重、有序。** 同一会话内 `seq` 严格递增、不留空洞(删除的消息保留占位);
  客户端带 `random_id` 重发不产生第二条;事件 `pts` 连续,断线后补齐。守卫:并发发送 + 重复 random_id + 断线补齐的 e2e。

---

## 4. 决定(按推荐执行)

| # | 问题 | 推荐(执行口径) | 另一个选项 / 代价 |
|---|---|---|---|
| D1 | 谁能用「消息」 | 用户端的顾客账号之间;**商家端、骑手端这一批不接入**,订单聊天保持现状,但在「消息」列表里有「订单消息」入口 | 全角色互通:同一个手机号的商家号、骑手号也能聊。身份混在一起,先不做 |
| D2 | 怎么找到人 | @用户名、二维码、**完整手机号精确匹配**(隐私里可以关);不上传通讯录 | 通讯录同步:找人方便,但要把用户整本通讯录传上来 |
| D3 | 端到端加密的秘密聊天 | **不做**。消息服务端存储;平台对违法内容有处置义务,端到端加密做不到;在「关于」里写明「平台技术上能读到消息,只在举报范围内查看并公示次数」(S8) | 做:要法务先确认,还要解决换设备丢记录 |
| D4 | 通话 | 1 对 1 语音、视频(WebRTC + 自建 coturn);群通话不做 | 不做通话:少一个 TURN 服务 |
| D5 | 机器人 | 做 Bot API 子集(收发消息、内联键盘、回调、命令菜单、编辑删除、getUpdates / webhook、打开小程序);机器人由开发者在 `/dev/` 创建 | 不做:少一块,但和小程序平台就接不上了 |
| D6 | 消息保存多久 | 永久,直到用户删除;删除即删正文和媒体,只留「谁、什么时候、在哪个会话、删了一条」的元数据 180 天 | 保存正文 6 个月:要法务确认是否必须 |
| D7 | 群 / 频道规模 | **群 ≤ 20 万人**(2026-09-16 从 1,000 提上来,和 Telegram 超级群同档);频道订阅者不设上限(事件按会话记,不按人扇出) | 原来的取舍是「群放到 20 万要换成大群那套分发,第一版不值」。现在换了:实时本来就按会话记、不按人扇出,真正按人扇出的只有离线推送 —— `chat_push.notify_message` 改成按 user_id 分批扫(每批 500),内存和单条 SQL 都与群大小无关;解散群时超过 1,000 人不再逐个写用户事件(靠会话事件 + 会话列表的 `deleted_at IS NULL` 兜底)。已读名单本来就只给 ≤100 人的群,和 Telegram 一样,不受影响 |
| D8 | 文件大小 | 聊天单个文件 ≤ 100MB、图片 ≤ 20MB;视频投稿单 P ≤ 1GB 且 ≤ 30 分钟,单个视频 ≤ 10 P;每人每天投稿 ≤ 10 个 | TG 的 2GB:部署机在家里,存储和上行都有限 |
| D9 | 视频格式 | H.264 + AAC 的 MP4 多档位(faststart),手动 / 自动清晰度;不做 HLS / DASH | 自适应码率:体验更好,切片和清单管理成本高,第二期再说 |
| D10 | 视频审核 | 全部先审后发;审核中 UP 主自己能看、能分享给审核员以外的人不能看 | 先发后审:不符合短视频审核细则 |
| D11 | 实名门槛 | 发视频、建公开群 / 频道要完成实名认证(已有 `UserIdentity`);聊天、评论、弹幕只需手机号账号(本来就是手机号注册) | 全部要实名:门槛太高 |
| D12 | 推荐算法 | 公开公式(§5.9);个性化只有两个加权:关注的 UP 主、近 30 天常看的分区;每条推荐都能看「为什么推荐」;可一键关闭 | 黑盒模型:和「账目为证」路线不合,还要算法备案说清楚 |
| D13 | 硬币 | 做,纯积分:每日首次登录 +1、投稿过审 +2(每天封顶);每个视频自制最多投 2 枚、转载 1 枚;投出的硬币归 UP 主;不能充值、提现、兑换 | 不做投币:少了「三连」 |
| D14 | 直播 | 不做 | 要网络表演经营许可和推流基础设施 |
| D15 | 动态 / 图文 | 不做;UP 主要发图文就开个频道 | — |
| D16 | 视频挂店铺 | 允许挂**一家平台商家**(探店);投稿时必须选「与商家有无合作」,有合作就在视频上标「合作」;平台不收推广费 | 不做:少了和外卖的连接 |
| D17 | 贴纸 | 用户自建贴纸包(上传 PNG / WebP,≤ 120 张一包)+ 内置一套「大表情」;不做 TGS / 视频贴纸 | — |
| D18 | GIF | 用户发的 GIF 转成无声 MP4 循环播放;不接第三方 GIF 搜索 | 境外服务、还要过内容审核 |
| D19 | 视频编号 | `sv` + 10 位 base58 随机 | 自增 id:暴露投稿量 |
| D20 | 推送预览 | 默认「发送人:内容」;隐私里可改成只显示「你有一条新消息」 | — |
| D21 | 管理员看私聊 | 只在举报范围内,每次留审计日志,透明中心公示次数(S8) | — |
| D22 | 不做的 TG 功能 | 频道评论区、群话题、快拍、群通话、实时位置、自定义表情、翻译、Premium | 以后按使用情况再加 |
| D23 | 订单入口 | 「我的」顶部订单四格 push 独立订单页;首页有进行中订单时顶部出一条可点的状态条;推送 / 支付回跳直达订单详情 | 订单挪进首页二级页:入口太深 |
| D24 | 通知和订单消息 | 「消息」列表顶部固定两行:「通知」(原消息中心)、「订单消息」(进行中订单的聊天);视频互动在第三行「互动消息」;首页右上角铃铛去掉 | 保留铃铛:两个地方都有未读,用户不知道看哪 |

---

## 5. 规范(规范性:实现、文档、测试逐字一致)

### 5.1 标识

- 会话 `chat_id`:整数;公开链接用 `public_id`(12 位 base58 随机)。
- 消息:`(chat_id, seq)`,`seq` 从 1 开始、会话内严格递增、不复用;对外引用消息一律用这一对,不暴露全局自增 id。
- 用户名:5–32 位 `[a-zA-Z0-9_]`,不能以数字或下划线开头、不能以下划线结尾、不能有连续两个下划线;
  大小写不敏感唯一(存小写键);用户、群、频道、机器人共用一个命名空间;机器人用户名必须以 `bot` 结尾;
  保留字(`admin`、`support`、`chaojizan`、`superz`、`official`、`system` …)不能注册。
- 链接(App Links 拉起,没装 App 落官网说明页):
  - 用户 / 公开群 / 频道:`https://chaojizan.cc/@<username>`
  - 邀请链接:`https://chaojizan.cc/join/<code>`(`code` 16 位 base58)
  - 公开会话里的消息:`https://chaojizan.cc/@<username>/<seq>`
  - 视频:`https://chaojizan.cc/v/<vid>`(`vid` = `sv` + 10 位 base58)
- 媒体:`media_id`(整数),下载地址只在响应里给相对路径 `/media/v1/files/<media_id>`,每次下载鉴权。

### 5.2 消息对象(接口和实时事件同一个形状)

```json
{
  "chat_id": 12, "seq": 345, "sender": {"id": 7, "name": "小王", "username": "xiaowang", "avatar": "/img/…"},
  "as_chat": false,
  "kind": "text",
  "text": "…", "entities": [{"type": "bold", "offset": 0, "length": 2}],
  "media": [{"id": 88, "kind": "photo", "w": 1280, "h": 960, "size": 231234, "mime": "image/jpeg",
             "url": "/media/v1/files/88", "thumb": "/media/v1/files/88?thumb=1", "name": "", "duration_ms": 0,
             "waveform": []}],
  "reply_to": {"seq": 340, "sender_name": "小李", "preview": "明天几点?", "kind": "text"},
  "forward": {"from_user": {"id": 9, "name": "…"}, "from_chat": null, "orig_seq": null, "date": "…", "hidden_name": ""},
  "grouped_id": null, "poll": null, "location": null, "contact": null, "dice": null, "service": null,
  "reactions": [{"emoji": "👍", "count": 3, "me": true}],
  "views": null, "silent": false, "edited_at": null, "created_at": "2026-09-13T10:00:00+08:00",
  "markup": null, "via_bot": null, "random_id": "1234567890123"
}
```

- `kind`:`text` `photo` `video` `file` `voice` `video_note` `sticker` `gif` `location` `contact` `poll` `dice` `service` `call`;
- 相册:同一次发送的多张图 / 视频是多条消息,共享 `grouped_id`,客户端合成一个气泡;
- 实体 `type`:`bold` `italic` `underline` `strike` `spoiler` `code` `pre`(带 `language`)`text_link`(带 `url`)
  `mention`(@用户名)`text_mention`(带 `user_id`)`hashtag` `url`;**offset / length 按 UTF-16 码元**;
  `url` / `mention` / `hashtag` 服务端自动识别补齐,客户端只需要发格式类实体;
- 文字 ≤ 4096 字、图片说明 ≤ 1024 字;超长由客户端拆条;
- `service.action`:`chat_create` `members_add` `member_join`(邀请链接)`member_leave` `member_kick`
  `title_change` `photo_change` `pin` `chat_migrate`(预留)`call`(通话记录)`screenshot`(预留);
- 被删除的消息不下发;删除事件只带 `seq`。

### 5.3 实时协议

**连接**:`GET /ws/v2`(WebSocket)。连上后 5 秒内客户端发第一帧 `{"t":"auth","token":"<JWT>","device":"<设备 id>","app":"user/1.2.3"}`,
服务端回 `{"t":"ready","user_pts":N,"server_time":"…"}`;超时或验证失败关闭码 `4401`。**token 不放 URL**(nginx 访问日志里会有)。

**客户端 → 服务端**

| 帧 | 说明 |
|---|---|
| `{"t":"ping"}` | 每 25 秒一次;60 秒收不到任何帧服务端断开 |
| `{"t":"state","foreground":true}` | 前后台切换;后台连接不算「在线」,新消息要走推送 |
| `{"t":"typing","chat_id":1,"action":"typing"}` | `typing` / `record_voice` / `upload_photo` / `upload_video` / `upload_file` / `choose_sticker` / `cancel`;每会话 3 秒最多一次;不落库,6 秒自动过期 |
| `{"t":"view","chat_id":1}` | 正在看这个会话(推送去重、在线人数用) |

**服务端 → 客户端**

| 帧 | 说明 |
|---|---|
| `{"t":"pong"}` | |
| `{"t":"ev","chat_id":1,"pts":88,"type":"…","data":{…}}` | 会话事件,见下表;同一会话 `pts` 连续 |
| `{"t":"uev","pts":12,"type":"…","data":{…}}` | 用户事件(和会话无关或只和「我」有关) |
| `{"t":"typing","chat_id":1,"user_id":7,"action":"typing"}` | 不带 pts |
| `{"t":"presence","user_id":7,"online":true,"last_seen":"…"}` | 按隐私过滤后才发 |
| `{"t":"call", …}` | 通话信令,见 §5.12 |

**会话事件 `ev.type`**:`msg`(新消息,data = 消息对象)`edit`(data = 消息对象)`del`(`{"seqs":[…]}`)
`react`(`{"seq":1,"reactions":[…]}`)`read`(`{"user_id":7,"seq":345}`:对方读到哪)`pin`(`{"seqs":[…],"pinned":true}`)
`poll`(`{"seq":…,"poll":{…}}`)`views`(`{"seq":…,"views":…}`,频道,批量合并)`chat`(会话资料变了,data = 会话对象)
`member`(`{"user_id":…,"role":…}`)`clear`(`{"upto":…}`,仅限清空对双方生效时)。

**用户事件 `uev.type`**:`chat_join` / `chat_leave`(我进 / 出了某个会话,data = 会话对象)`dialog`(我这边的会话状态:置顶 / 归档 / 免打扰 / 标记未读 / 草稿 / 已读位置)
`folders`(分组变了)`profile`(我的资料在另一台设备上改了)`block`(拉黑列表)`hide`(我「只为自己删除」了哪些消息)`sticker_sets`。

**断线补齐**:`POST /chat/v1/sync`,请求 `{"user_pts":12,"chats":{"1":88,"5":3}}`(客户端缓存过的会话和它们的 pts),
响应 `{"user_pts":20,"user_events":[…],"chats":{"1":{"events":[…],"pts":90},"5":{"reset":true,"pts":900}}}`;
单个会话落后超过 500 条事件或 7 天,回 `reset`,客户端丢掉缓存重拉这个会话。事件表保留 7 天。

**分发**:事件先落库、提交之后再发;进程内按「在线用户 → 连接」和「会话 → 在线成员」两张表分发;
同时发一份到 Redis 频道 `rt:c:<chat_id>` / `rt:u:<user_id>`,其他进程订阅后分给自己的连接(现在单进程,也要能多进程)。

### 5.4 发送与幂等

`POST /chat/v1/chats/{chat_id}/messages`,请求带 `random_id`(客户端生成的 63 位随机整数,字符串传输);
服务端对 `(chat_id, sender_id, random_id)` 唯一,重发返回同一条消息。客户端乐观显示「发送中」(时钟图标),
确认后换成单勾;失败显示红色感叹号,点一下重发(同一个 `random_id`)。

### 5.5 已读、送达、未读

- 每个成员记 `last_read_seq`;私聊里对方的 `last_read_seq ≥ 我的消息 seq` 就是双勾;
- ≤ 100 人的群:长按自己的消息看「已读」名单(7 天内读的人,按读的时间倒序);更大的群和频道不提供;
- 未读数 = 该会话里 `seq > last_read_seq`、不是我发的、没被删除、没被我隐藏的消息条数,封顶 999;
- 未读 @ 提及单独计数,聊天页右下角有「@」跳转按钮;
- 「标记为未读」是会话级别的一个标志,打开会话即清除;
- 已读回执受隐私控制吗:**不受**(TG 也不能关私聊已读)。

### 5.6 群 / 频道权限

角色:`owner` `admin` `member` `restricted` `left` `banned`。

管理员权限(布尔,owner 全有):`change_info` `delete_messages` `ban_users` `invite_users` `pin_messages`
`add_admins` `post_messages`(频道)`edit_messages`(频道,编辑别人的帖子)`anonymous`(群里匿名发言,显示为群)。
管理员可以有自定义头衔(≤ 16 字)。只有 `add_admins` 的人能任免管理员,且只能授予自己拥有的权限。

成员默认权限(群设置,可按人限制并设到期时间):`send_messages` `send_media` `send_stickers` `send_polls`
`embed_links` `invite_users` `pin_messages` `change_info`。

慢速模式:`0 / 10 / 30 / 60 / 300 / 900 / 3600` 秒,管理员不受限。
频道:只有 `post_messages` 的管理员能发;订阅者只能读和回应;`signatures` 打开时帖子显示发帖管理员名字。

### 5.7 限流与配额(公开写进文档,和派单算法同一个路子)

| 项 | 限制 |
|---|---|
| 发消息 | 每人每秒 5 条、每分钟 60 条;同一群每人每秒 1 条 |
| 新账号(注册 < 24 小时)主动发起新私聊 | 每天 20 个 |
| 建群 / 建频道 | 每人每天 10 个 |
| 转发 | 一次最多 100 条、最多转到 10 个会话 |
| 聊天上传 | 单文件见 D8;每人每天 2GB |
| 视频投稿 | 见 D8 |
| 弹幕 | 每人每 3 秒 1 条、每天 1,000 条;≤ 100 字 |
| 评论 | 每人每 5 秒 1 条、每天 500 条;≤ 1,000 字 |
| 点赞 / 投币 / 收藏 | 每人每秒 5 次 |
| 找人(按手机号) | 每人每天 20 次(防撞库) |
| 机器人发消息(Bot API 的 sendMessage / sendPhoto / sendDocument) | 每个机器人全局每秒 30 条;同一会话每秒 1 条(允许突发 3);同一群每分钟 20 条;超了 429 + `parameters.retry_after`(见 docs/BOT-API.md 第 6 节) |
| 点机器人消息上的回调按钮 | 每人每秒 3 次 |
| 机器人数量 | 每个开发者最多 20 个 |

### 5.8 视频状态机(服务端强制,非法迁移抛错,照 `state_machine.py` 的写法)

```
draft ──提交──▶ processing ──转码完成──▶ reviewing ──通过──▶ published ──下架──▶ removed
  ▲                │                          │                   │  └─UP 主设为私密─▶ (visibility=private)
  │                └─转码失败──▶ failed        └─驳回──▶ rejected   └─UP 主删除──▶ deleted(软删,30 天后清媒体)
  └──────────── rejected / failed 可以修改后重新提交 ─────────────┘
```

- 修改标题 / 简介 / 标签 / 封面 / 分区 / 分 P 之后要重新审核;审核期间**线上仍是上一版已审核的内容**;
- `scheduled_at`:审核通过后到点才变 `published`,由后台清扫任务推进;
- 每个分 P 单独转码,全部就绪才进 `reviewing`。

### 5.9 排序公式(公开,和 `services/video_rank.py` 逐字一致)

```
互动分 = 播放 × 1 + 点赞 × 5 + 投币 × 10 + 收藏 × 8 + 评论 × 6 + 弹幕 × 2 + 分享 × 10
         (只数最近 72 小时内的增量;同一个人对同一个视频每种互动只算一次)
热度   = 互动分 ÷ (发布后的小时数 + 2) ^ 1.5
推荐   = 热度 × (1 + 0.3 × 我关注了这个 UP 主 + 0.15 × 这是我近 30 天最常看的 3 个分区之一)
         关掉个性化:两个加权都是 0
去重   = 同一个 UP 主在一屏(20 条)里最多 2 个;看过的(播放进度 > 50%)7 天内不再推
排行榜 = 某分区(或全站)按「互动分」在 1 / 3 / 7 天窗口里排序
竖屏流 = 只取竖屏视频(宽 < 高),同「推荐」
```

- 输入只有公开计数、发布时间、关注关系和观看分区;**没有任何付费、商家、运营加权**(S3);
- 播放计数:同一个人(未登录按设备)同一个视频每天只算一次,且看满 5 秒或 30% 才算。

### 5.10 弹幕

字段:`time_ms`、`mode`(`1` 滚动 / `4` 底部 / `5` 顶部)、`color`(24 位 RGB 整数,默认白 `16777215`)、`size`(`18` 小 / `25` 标准)、
`text`(≤ 100 字,单行)、`user_hash`(发送人 id 的 8 位哈希,用于「屏蔽此人」,不暴露 id)。

- 拉取按 6 分钟一段:`GET /video/v1/parts/{part_id}/danmaku?segment=0`;客户端预取当前段和下一段;
- 渲染:滚动弹幕分轨道(行高 = 字号 × 1.4),同一轨道前一条的尾巴离开右边缘才放下一条,
  飞过屏幕固定 8 秒(速度 = (屏宽 + 文字宽) ÷ 8s,可调 0.5×–2×);顶部 / 底部停留 4 秒居中;放不下就丢弃;
- 设置:开关、不透明度 20–100%、字号 50–150%、速度、显示区域(1/4、半屏、3/4、全屏)、屏蔽顶部 / 底部 / 滚动 / 彩色、屏蔽词、屏蔽某人;
- 高能进度条:按 5 秒一桶统计弹幕数,在进度条上方画密度曲线;
- 自己发的弹幕立即上屏、带边框。

### 5.11 原因代码(审核、处罚共用,文档和后台一张表)

| 代码 | 含义 |
|---|---|
| C101 | 骚扰、辱骂 |
| C102 | 垃圾广告、引流 |
| C103 | 诈骗 |
| C104 | 色情、低俗 |
| C105 | 暴力、血腥 |
| C106 | 违法违规(赌博、毒品、枪支等) |
| C107 | 侵犯隐私(未经同意公开他人信息) |
| C108 | 冒充他人或官方 |
| C109 | 未成年人不宜 |
| V201 | 视频侵权(未经授权搬运) |
| V202 | 标题 / 封面与内容不符 |
| V203 | 画质或内容不完整(黑屏、无声、静止) |
| V204 | 分区选错 |
| V205 | 未声明合作(挂店铺却选了「无合作」) |
| V206 | 危险行为 |
| X999 | 其他(必须写说明) |

### 5.12 通话信令

在 `/ws/v2` 上走 `{"t":"call", …}`:`invite`(`call_id`、`video`、`sdp`)→ 对方 `ringing` → `accept`(`sdp`)/ `decline` / 超时 45 秒 `missed`;
双方交换 `ice`;任意一方 `hangup`;对方正在通话回 `busy`。通话结束写一条 `kind=call` 的服务消息(时长、类型、结果)。
TURN 凭据:`GET /chat/v1/calls/ice-servers` 返回 coturn 的临时用户名密码(REST 共享密钥方案,有效 1 小时)。
隐私「谁能给我打电话」对呼叫方生效;被拉黑直接 `busy`。

### 5.13 Bot API(子集,形状对齐 Telegram Bot API,方便迁移)

`POST /bot/<token>/<method>`,响应 `{"ok":true,"result":…}` / `{"ok":false,"error_code":…,"description":…}`。
方法:`getMe` `getUpdates`(长轮询 ≤ 50 秒)`setWebhook` `deleteWebhook` `sendMessage` `sendPhoto` `sendDocument`
`editMessageText` `editMessageReplyMarkup` `deleteMessage` `answerCallbackQuery` `setMyCommands` `getMyCommands`
`setChatMenuButton`(`web_app` 按钮 = 打开一个已上架的小程序)`getChat` `sendChatAction`。
更新类型:`message` `edited_message` `callback_query` `my_chat_member`。
机器人只能收到:私聊里用户发给它的消息、群里 `/命令`、@它的消息、回复它的消息(隐私模式默认开)。
webhook 调用带 `X-Superz-Bot-Api-Secret-Token`;失败按 1 / 2 / 4 … 分钟重试,24 小时后丢弃。
逐个方法的参数、对象、错误、限流和给客户端的接口见 [BOT-API.md](BOT-API.md)(和实现、测试逐字一致)。

---

## 6. 总体架构

```
          ┌──────── 用户端 App(Flutter,安卓 + 网页版)─────────┐
          │ 首页 │ 消息(chat/)│ 视频(video/)│ 我的            │
          └───┬─────────────┬───────────────┬──────────────────┘
      HTTPS   │   WebSocket /ws/v2            │ MP4 Range 请求
              ▼             ▼               ▼
┌──────────────── nginx(TLS)─────────────────────────────────────────┐
│ /           → api                                                     │
│ /ws/v2      → api(升级头,1 小时读超时,已有)                         │
│ /vod/…      → api 鉴权后 X-Accel-Redirect → MinIO(大文件不过 Python)│
│ /img/…      → MinIO 公开桶(封面、贴纸、头像,已有)                  │
└──────────────┬───────────────────────────────────────────────────────┘
               ▼
┌──────── api(FastAPI,单进程)────────┐   ┌──── media-worker ────┐
│ routers: social / chat / media /      │   │ ffmpeg:转码、封面、   │
│          video / bot / calls          │──▶│ 雪碧图、GIF→MP4、语音 │
│ realtime:连接表 + 分发 + Redis 订阅   │jobs│ 队列 Redis list       │
└──┬───────────────┬──────────────┬────┘   └──────────┬───────────┘
   ▼               ▼              ▼                    ▼
PostgreSQL       Redis          MinIO(私密桶:聊天媒体、视频原片与各档位;公开桶:封面、贴纸)
(消息、事件、    (在线、限流、
 视频、计数)      队列、pub/sub)          coturn(通话 TURN)   JPush(离线推送)
```

- **转码不在请求里做**:api 只收片、落对象存储、投任务;`media-worker` 是同一个镜像的另一个进程
  (`python -m app.workers.media`),并发 1,`nice 10`。开发 / CI 没有 worker 时 `MEDIA_WORKER=inline`
  在 api 进程里用后台任务跑同一段代码(默认值,保证什么环境都能跑通);生产 compose 设 `external`;
- **视频文件不过 Python**:生产上 `/vod/` 由 api 判权后回 `X-Accel-Redirect` 到 nginx 内部 location,
  nginx 带着预签名参数去 MinIO 取(支持 Range);开发环境没有 nginx,api 自己按 Range 流式返回(`MEDIA_ACCEL=off`,默认);
- **聊天媒体一律私密桶**,每次下载判「是不是这个媒体所在会话的成员」;
- **实时**:单进程也按多进程的方式写(Redis pub/sub),以后加 worker 不用改协议。

---

## 7. 数据模型(迁移从 0125 起;模型放 `models_social.py`、`models_video.py`,在 `models.py` 末尾导入)

**社交身份**

- `social_profiles`:`user_id`(PK)、`username`、`username_lc`(唯一)、`bio`(≤ 140)、`privacy`(JSONB:`last_seen` / `phone_search` / `group_invite` / `calls` / `forwards` / `avatar`,取值 `everyone|contacts|nobody`)、
  `notify`(JSONB:预览、私聊 / 群 / 频道默认)、`personalize_video`(布尔,默认真)、`coins`(整数)、`coin_day`(上次领币的北京日期)、
  `user_pts`(用户事件序号)、`last_seen_at`、`created_at`;
- `usernames`:`username_lc`(PK)、`owner_type`(`user|chat`)、`owner_id` —— 共用命名空间;
- `social_contacts`:`owner_id`、`contact_id`、`alias`、`created_at`(PK 前两列);
- `social_blocks`:`user_id`、`blocked_id`、`created_at`。

**会话与消息**

- `chats`:`id`、`type`(`private|group|channel|saved`)、`public_id`、`title`、`about`、`photo_url`、`owner_id`、
  `pair_key`(私聊 `小id:大id`,唯一;其他为空)、`last_seq`、`pts`、`member_count`、`settings`(JSONB:`slow_mode`、`join_by_request`、`default_perms`、`reactions`、`signatures`、`history_visible`、`protected`)、
  `last_message_at`、`created_at`、`deleted_at`;
- `chat_members`:`chat_id`、`user_id`(PK)、`role`、`rights`(JSONB)、`restrictions`(JSONB,含 `until`)、`title`、`joined_at`、`invited_by`、`left_at`、
  `last_read_seq`、`last_read_at`、`cleared_seq`、`muted_until`、`pinned_rank`、`archived`、`marked_unread`、`draft`(JSONB)、`join_seq`(入群时的 last_seq,`history_visible=false` 时看不到之前的);
  索引 `(user_id, role)`;
- `messages`:`id`(bigserial)、`chat_id`、`seq`(唯一 `(chat_id, seq)`)、`sender_id`、`as_chat`、`random_id`(唯一 `(chat_id, sender_id, random_id)`)、
  `kind`、`text`、`entities`、`media`(JSONB)、`reply_to_seq`、`forward`(JSONB)、`grouped_id`、`poll_id`、`extra`(JSONB:位置 / 名片 / 骰子 / 服务动作 / 通话)、
  `markup`(JSONB)、`via_bot_id`、`silent`、`views`、`edited_at`、`deleted_at`、`created_at`;索引 `(chat_id, seq)`、`(sender_id, created_at)`;
- `message_hides`:`chat_id`、`seq`、`user_id`(只为自己删除);
- `message_reactions`:`chat_id`、`seq`、`user_id`、`emoji`、`created_at`(PK 前四列);
- `message_mentions`:`chat_id`、`seq`、`user_id`(未读 @ 计数、「@我的」);
- `chat_events`:`chat_id`、`pts`(PK)、`type`、`data`、`created_at`;保留 7 天;
- `user_events`:`user_id`、`pts`(PK)、`type`、`data`、`created_at`;保留 7 天;
- `polls` / `poll_votes`;`invite_links`;`join_requests`;`scheduled_messages`;`chat_folders`;
- `sticker_sets` / `stickers` / `user_sticker_sets`;
- `calls`:`id`、`caller_id`、`callee_id`、`chat_id`、`video`、`state`、`started_at`、`answered_at`、`ended_at`、`reason`;
- `bots`:`user_id`(机器人自己的 users 行,`role=bot`)、`owner_id`、`token_hash`、`token_prefix`、`about`、`commands`、`webhook_url`、`webhook_secret`、`menu_app_id`、`privacy_mode`;
  `bot_updates`:`bot_id`、`update_id`、`payload`、`created_at`、`delivered_at`;
- `chat_reports`:举报(会话 / 消息),`admin_views`:管理员查看私聊的审计(S8)。

**媒体**

- `media_files`:`id`、`owner_id`、`bucket`(`private|public`)、`key`、`kind`(`photo|video|file|voice|video_note|sticker|gif|cover|avatar`)、`mime`、`size`、`w`、`h`、`duration_ms`、
  `thumb_key`、`waveform`(JSONB,64 个 0–31)、`sha256`、`name`、`status`(`ready|processing|failed`)、`error`、`created_at`;
- `uploads`:`id`(uuid)、`owner_id`、`purpose`、`size`、`received`、`chunk_size`、`mime`、`name`、`status`、`created_at`、`expires_at`(24 小时)。

**视频**

- `videos`:`id`、`vid`(唯一)、`uploader_id`、`title`、`description`、`cover_media_id`、`zone`、`tags`(text[])、`copyright`(`original|repost`)、`source_url`、
  `status`、`visibility`(`public|unlisted|private`)、`is_vertical`、`duration_ms`、`allow_danmaku`、`allow_comments`、`shop_id`、`shop_collab`、`scheduled_at`、`published_at`、
  `reject_code`、`reject_note`、`pending_changes`(JSONB,改了待审的内容)、计数列 `views` `likes` `coins` `favorites` `shares` `danmaku_count` `comment_count`、`created_at`、`updated_at`、`deleted_at`;
- `video_parts`:`id`、`video_id`、`idx`、`title`、`source_media_id`、`status`、`duration_ms`、`w`、`h`、`renditions`(JSONB:`[{"q":720,"key":…,"w":…,"h":…,"bitrate":…,"size":…}]`)、`sprite`(JSONB)、`created_at`;
- `video_likes`、`video_coins`(`video_id`、`user_id`、`amount`)、`coin_ledger`(`user_id`、`delta`、`reason`、`ref`、`created_at`)、`video_shares`;
- `fav_folders`、`fav_items`、`watch_later`、`watch_history`(`user_id`、`video_id`、`part_idx`、`position_ms`、`duration_ms`、`watched_at`,唯一前两列);
- `follows`:`follower_id`、`followee_id`、`created_at`;
- `video_comments`:`id`、`video_id`、`user_id`、`root_id`、`parent_id`、`reply_to_user_id`、`text`、`likes`、`dislikes`、`reply_count`、`pinned`、`deleted_at`、`created_at`;`comment_votes`;
- `danmaku`:`id`、`video_id`、`part_id`、`user_id`、`time_ms`、`mode`、`color`、`size`、`text`、`deleted_at`、`created_at`;索引 `(part_id, time_ms)`;
- `video_view_days`:`video_id`、`day`、`viewer_key`(唯一三列;播放去重);`video_stat_days`:按天增量(排行榜、创作中心曲线);
- `video_reports`、`video_decisions`(审核记录);`search_terms`:`day`、`term`、`users`(热搜,去重后的人数)。

守卫(S3):单测扫上面所有表,不许出现 `bid|boost|paid|promot|rank_score|weight_override` 这类列名。

---

## 8. 接口清单(前缀和小程序平台一致,`/v1` 起)

**社交** `/social/v1`:`GET/PATCH /me`(资料、隐私、通知)、`PUT /me/username`、`GET /users/{id}`、`GET /resolve/{username}`、
`POST /find-by-phone`、`GET/POST/DELETE /contacts`、`GET/POST/DELETE /blocks`、`GET /qr`(我的名片二维码内容)。

**聊天** `/chat/v1`:
- 会话:`GET /dialogs`(会话列表,带未读、最后一条、置顶 / 归档 / 免打扰状态,游标分页)、`POST /chats/private`(和某人的私聊,不存在就建)、
  `POST /chats`(建群 / 频道)、`GET/PATCH /chats/{id}`、`DELETE /chats/{id}`(解散 / 删除)、`POST /chats/{id}/leave`、
  `PATCH /dialogs/{id}`(置顶、归档、免打扰、标记未读、草稿)、`POST /dialogs/{id}/clear`(清空,可选对双方)、`POST /dialogs/{id}/read`;
- 消息:`GET /chats/{id}/messages?before=&after=&around=&limit=`、`POST /chats/{id}/messages`、`PATCH /chats/{id}/messages/{seq}`、
  `POST /chats/{id}/messages/delete`(批量,`revoke` 是否为双方)、`POST /chats/{id}/messages/forward`、`POST /chats/{id}/messages/{seq}/reactions`、
  `GET /chats/{id}/messages/{seq}/readers`、`POST /chats/{id}/pins`、`GET /chats/{id}/pins`、`POST /chats/{id}/polls/{seq}/vote`、`POST /chats/{id}/polls/{seq}/close`、
  `GET/POST/DELETE /chats/{id}/scheduled`;
- 成员与管理:`GET /chats/{id}/members`、`POST /chats/{id}/members`(拉人)、`PATCH /chats/{id}/members/{uid}`(任免管理员、限制、封禁)、
  `DELETE /chats/{id}/members/{uid}`(移出)、`GET/POST/PATCH /chats/{id}/invites`、`POST /join/{code}`、`GET /join/{code}`(预览)、
  `GET /chats/{id}/join-requests`、`POST /chats/{id}/join-requests/{uid}`;
- 搜索:`GET /search?q=`(会话、人、公开群 / 频道、消息)、`GET /chats/{id}/search?q=&kind=`、`GET /chats/{id}/media?kind=photo|file|link|voice`;
- 其他:`POST /sync`、`GET/PUT /folders`、`GET /stickers/sets`、`POST /stickers/sets`、`POST /stickers/sets/{id}/install`、
  `GET /link-preview?url=`、`POST /reports`、`GET /calls/ice-servers`、`GET /calls`(通话记录)、`POST /export`(导出)。

**媒体** `/media/v1`:`POST /upload`(≤ 10MB 一次传完)、`POST /uploads`(建分片上传)、`PUT /uploads/{id}/chunks/{n}`、`POST /uploads/{id}/complete`、
`GET /media/{id}`(状态)、`GET /files/{id}?thumb=1`(下载,Range)。

**视频** `/video/v1`:
- 浏览:`GET /feed/recommend`、`GET /feed/hot`、`GET /feed/following`、`GET /feed/vertical`、`GET /zones`、`GET /zones/{zone}`、`GET /rank?zone=&days=`、
  `GET /videos/{vid}`、`GET /videos/{vid}/related`、`GET /search?q=&order=&duration=&zone=`、`GET /search/hot`、`GET /users/{id}/space`、`GET /users/{id}/videos`;
- 互动:`POST /videos/{vid}/like`、`POST /videos/{vid}/coin`、`POST /videos/{vid}/favorite`、`POST /videos/{vid}/share`、`POST /videos/{vid}/triple`、
  `POST /videos/{vid}/view`(播放心跳)、`POST /videos/{vid}/not-interested`、`POST /users/{id}/follow`、`GET /me/following`、`GET /users/{id}/fans`;
- 弹幕与评论:`GET /parts/{id}/danmaku?segment=`、`POST /parts/{id}/danmaku`、`GET /videos/{vid}/comments?sort=&cursor=`、`POST /videos/{vid}/comments`、
  `GET /comments/{id}/replies`、`POST /comments/{id}/vote`、`POST /comments/{id}/pin`、`DELETE /comments/{id}`;
- 我的:`GET /me/history`、`DELETE /me/history`、`GET/POST/DELETE /me/watch-later`、`GET/POST/PATCH/DELETE /me/favorites`(收藏夹)、`GET /me/coins`、`GET/PATCH /me/settings`(个性化开关);
- 投稿:`POST /uploads/videos`(建稿件)、`PATCH /videos/{vid}`、`POST /videos/{vid}/parts`、`DELETE /videos/{vid}/parts/{id}`、`POST /videos/{vid}/submit`、`DELETE /videos/{vid}`、
  `GET /creator/videos`、`GET /creator/videos/{vid}/stats`、`GET /creator/overview`;
- 播放地址:`GET /vod/{vid}/{part_id}/{q}.mp4`(Range;判权)、`GET /vod/{vid}/{part_id}/sprite/{n}.jpg`。

**互动消息** `/social/v1/notifications?kind=reply|at|like|system`、`POST /social/v1/notifications/read`。

**管理** `/admin/social/…`:视频审核队列、决定、举报列表与处置、群 / 频道封禁、账号禁言、管理员查看被举报消息(S8)、统计。

**机器人** `/bot/<token>/<method>`;开发者后台 `/dev/v1/bots…`(建、改、重置 token、删除)。

---

## 9. 里程碑与顺序

| 里程碑 | 内容 | 提示词 |
|---|---|---|
| M0 地基 | 导航改版、社交身份、媒体上传与存储、转码队列、实时网关 | #339–#343 |
| M1 聊天核心 | 数据模型、私聊与消息基础、富文本、多媒体、会话列表、推送、客户端架构 | #344–#348、#353、#356 |
| M2 群 / 频道 / 互动 | 群组、频道、回应 / 投票 / 贴纸 / GIF / 定时 / 收藏夹、搜索与共享媒体 | #349–#352 |
| M3 视频核心 | 数据模型、投稿转码审核、播放器、弹幕、详情页、评论 | #357–#362 |
| M4 发现与个人 | 竖屏流、推荐 / 热门 / 排行榜 / 分区、搜索、空间 / 关注 / 收藏 / 历史 / 硬币、互动消息 | #363–#367 |
| M5 通话与机器人 | 1 对 1 通话、Bot API、圆形视频消息 | #354、#355 |
| M6 治理与横切 | 审核治理、内容安全、管理后台、透明中心、性能、安全审计、合规、上线手册 | #368–#375 |
| M7 验证 | 两台设备真聊、完整走查、全量回归 | #376 |

依赖:M0 → M1 → M2;M0 → M3 → M4;M1 + M0 → M5;M6 贯穿,每个里程碑结束前做对应部分。

---

## 10. 提示词

### #339 底部导航改版(首页 / 消息 / 视频 / 我的)

> 2026-09-13 按「超级赞用户端消息与视频」设计稿(A / D / F 三屏都是这个顺序)改成「首页 / 视频 / 消息 / 我的」,
> 消息角标改用 clay(数的是有未读的会话,不是待办)。下面是当时的原文。

**背景**:§1 第 1–3 行。订单是外卖的命脉,**入口不能变深**。

**要做**:
1. `HomePage` 的 `SzNavScaffold` 改成四项:首页(storefront)、消息(chat_bubble,带未读角标,免打扰会话不计)、视频(smart_display)、我的(person);
   宽屏左侧栏同样四项;`IndexedStack` + `_visited` 的懒建保留;
2. `OrdersTab` 抽成独立页面 `OrdersPage`(`apps/user_app/lib/orders_page.dart`),顶栏带「券包 · N」和原筛选;
   「我的」订单四格、「全部订单」改成 push `OrdersPage(filter)`;
3. 首页顶部(地址栏下面)有进行中的订单时出一条状态条(店名 + 状态 + 预计送达),点开订单详情;多单时显示「N 个订单进行中」进订单页;
4. 推送点击、支付回跳、深链原来切到订单 tab 的地方,全部改成 push 订单详情 / 订单页;全局搜 `_tab = 1`、`_openOrders`、`OrderFilter` 的调用点逐个改;
5. 首页右上角铃铛去掉(D24),通知入口在「消息」列表顶部;
6. 视频 tab 在「竖屏」子页时整个导航条换深色(和抖音一样),其他子页跟随主题。

**验收**:冷启动首页 → 点「我的」→ 订单四格每一格都能打开对应筛选的订单页,返回回到「我的」;
有进行中订单时首页出现状态条,点开是这单的详情;推送点击直达订单详情;宽屏侧栏四项正常。

**测试**:widget 测试:导航四项、订单四格 push 的是 `OrdersPage` 且筛选正确、没有 `_tab = 1` 的残留调用;
改动前后跑 `apps/user_app` 全部单测。

**不做**:订单页本身的改版。

### #340 社交身份:资料、@用户名、隐私、联系人、拉黑

**要做**:`models_social.py`(§7 社交身份四张表)+ 迁移;`routers/social.py`;`services/social.py`(用户名校验、隐私判定 `can_see(viewer, owner, field)`、拉黑判定 `blocked(a, b)`);
资料默认值:`display_name` 用 `users.name`,空的话「用户」+ 手机号后四位的哈希(**不用手机号本身**);
找人三种方式(§4 D2),按手机号每天 20 次;二维码内容就是 `https://chaojizan.cc/@<username>`,没用户名时是 `https://chaojizan.cc/u/<public_id>`;
客户端:「我的」→ 资料页加「用户名」「签名」;设置里加「隐私与安全」(最后上线、按手机号找到我、谁能拉我进群、谁能给我打电话、转发时附带我的链接、头像可见范围、已屏蔽的人)。

**验收**:改用户名实时检查可用(占用、保留字、格式各有一句明确的话);拉黑后 S7 各项生效;按手机号只精确匹配、不回显号码。

**测试**:单测(用户名规则、隐私判定真值表);e2e `e2e_social_profile`(改名冲突、找人、隐私、拉黑、S2 扫描)。

### #341 媒体服务:上传、存储、下载

**要做**:`models` 里 `media_files` / `uploads`;`routers/media.py`;`services/media.py`:
- 小文件一次传完(≤ 10MB),大文件分片(每片 4MB,`PUT` 原始字节,可断点续传:`GET /uploads/{id}` 返回已收到的片);
- 按魔数判类型(不信文件名和 mime):图片 jpg/png/webp/gif/heic、视频 mp4/mov/webm/mkv、音频 m4a/aac/mp3/ogg/opus/webm/wav、其他一律当文件;
- 图片:生成缩略图(长边 320,JPEG 质量 70)、读宽高、去掉 EXIF 里的定位;GIF 交给 worker 转 MP4;
- 视频 / 语音:`ffprobe` 读时长宽高;语音统一转 AAC 32kbps 单声道 m4a(同步做,1 分钟语音 < 1 秒);
- 聊天媒体进私密桶;下载 `GET /media/v1/files/{id}` 判权:上传者本人、或者这个媒体出现在我能读的某条消息里(查 `messages.media` 的 GIN 索引);
  支持 `Range`,`Content-Disposition` 对文件类给原文件名;
- 配额(§5.7、D8)按天累计,超了回 413 和明确的话。

**验收**:100MB 文件断网续传后完整(SHA-256 一致);非成员拿不到;伪装成 jpg 的 exe 被当文件处理且不预览。

**测试**:e2e `e2e_media`(小文件、分片、续传、魔数、Range、判权、配额)。

### #342 转码 worker

**要做**:`app/workers/media.py`(`python -m app.workers.media`)+ `services/transcode.py`(纯函数:给输入参数算 ffmpeg 命令,单测锁住);
队列 Redis list `media:jobs`,任务 `{"type":…,"id":…}`,失败重试 2 次,仍失败标 `failed` 写原因;
- 视频投稿:按 §4 D9 出档位(不超过原片高度 / 宽度;竖屏按宽算),`-preset veryfast -crf 23 -maxrate/bufsize`,关键帧 2 秒,`+faststart`;
  封面(没传封面时取 10% 处一帧)、雪碧图(每 N 秒一帧,160 宽,10×10 一张);
- 聊天视频:已经是 H.264/AAC、≤ 1080p、≤ 10Mbps 的只做 faststart 重封装,否则转 720p;取首帧缩略图;
- GIF → 无声 MP4;
- `MEDIA_WORKER=inline|external`(§6);
- 管理后台「平台开关」加 `media_transcode`(急停:关了新任务只排队不执行)。

**验收**:一段 2 分钟 1080p 竖屏视频 → 1080/720/480/360 四档 + 封面 + 雪碧图,档位宽高比例正确;worker 被杀掉重启后任务不丢。

**测试**:单测(命令生成、档位选择);e2e `e2e_transcode`(用 ffmpeg 现场生成测试片:横屏、竖屏、无声、奇数宽高)。

### #343 实时网关 v2

**要做**:`app/realtime/`:`hub.py`(连接表、会话在线成员表、分发)、`gateway.py`(`/ws/v2` 路由、第一帧鉴权、心跳、前后台)、`bus.py`(Redis pub/sub);
`services/events.py`:`append_chat_event(db, chat_id, type, data)` / `append_user_event(...)`,在同一个事务里分配 pts,**提交后**才分发;
`/chat/v1/sync`(§5.3);在线状态写 `social_profiles.last_seen_at`(断开时)+ Redis `online:<uid>`(TTL 90 秒);
presence 只发给「和他有私聊、且隐私允许」的在线用户;typing 按会话在线成员分发。

**验收**:两个连接同一用户都收到事件;断线期间发的 30 条消息,重连 sync 后一条不少、顺序正确;token 放 URL 连不上(必须第一帧)。

**测试**:e2e `e2e_realtime`(websocket 客户端直连:鉴权、心跳超时、事件顺序、断线补齐、reset、多设备)。

### #344 聊天数据模型与迁移

**要做**:§7「会话与消息」全部表 + 迁移(有 downgrade);`services/chat_perms.py`(权限判定全部集中在这,§5.6 的真值表);
`services/chat_store.py`(分配 seq、写消息、写事件的唯一入口 —— 其他代码不许直接 insert `messages`)。

**测试**:单测(权限真值表、seq 分配并发:两个事务同时发,seq 连续不重复 —— 用 `SELECT … FOR UPDATE` 锁会话行)。

### #345 私聊与消息基础

**要做**:私聊建立(`pair_key` 唯一,拉黑时拒绝)、收藏夹(`type=saved`,每人一个)、发 / 收文字、回复(引用预览)、转发(保留来源,可隐藏来源;`protected` 会话禁止转发)、
编辑(48 小时内,只能改自己的文字 / 说明;显示「已编辑」)、删除(只为自己 / 为双方;私聊随时可为双方删,群里自己的消息或有 `delete_messages` 的管理员)、
已读(§5.5)、正在输入、草稿(`PATCH /dialogs/{id}` 同步)、在线状态和最后上线(按隐私,隐藏时显示「最近 / 一周内 / 一月内」)。

**客户端**(`apps/user_app/lib/chat/`):
- `chat_page.dart`:倒序列表、按天分隔、「以下为新消息」分割线、气泡(自己的右侧品牌色、别人的左侧)、时间 + 已编辑 + 勾(时钟 / 单勾 / 双勾 / 红色感叹号)、
  回复条、转发头、滑动回复(气泡左滑)、长按菜单(回复、复制、转发、编辑、置顶、多选、删除、回应、已读名单、举报)、
  底部回到最新按钮(带未读数)、顶部置顶消息条、多选模式(批量转发 / 删除);
- 输入栏:多行、发送键、长按发送出「静音发送 / 定时发送」、没有文字时显示录音键、附件键、表情 / 贴纸键;回复 / 编辑状态条;
- 顶栏:头像、名字、副标题(在线 / 最后上线 / 正在输入… / N 位成员,M 人在线)、通话按钮、菜单(搜索、免打扰、清空、删除、拉黑、举报、共享媒体、资料)。

**验收**:两个账号(安卓 + 网页版)互发,1 秒内到达;对方打开后双勾;编辑、双向删除对方立即变;断网发 3 条,联网自动补发不重复。

**测试**:e2e `e2e_chat_private`;dart 单测(气泡分组、时间分隔、勾的状态机、乐观发送队列)。

### #346 富文本与消息实体

**要做**:`services/entities.py`:UTF-16 偏移换算、实体校验(不越界、不重叠冲突)、自动识别 url / mention / hashtag;
客户端:选中文字弹格式菜单(粗体、斜体、下划线、删除线、剧透、代码、链接);渲染用 `TextSpan`,剧透点开才显示,代码块等宽可复制,链接点开先确认外链;
@ 输入联想(群成员 / 联系人),`#话题` 点开会话内搜索。

**测试**:单测(UTF-16 换算含 emoji 和生僻字、实体校验);dart 单测(渲染快照)。

### #347 媒体消息

**要做**:图片(发送前可选「原图」,否则客户端压缩到长边 2560)、相册(≤ 10,九宫格布局)、视频(缩略图 + 时长,点开全屏播放,可保存)、
文件(图标、文件名、大小、下载进度,下载后用系统打开)、语音(按住录音、上滑锁定、左滑取消,波形,1× / 1.5× / 2×,未听的蓝点)、
位置(发当前位置或地图选点,气泡是静态地图,点开地图 / 导航)、名片(联系人的资料卡,点开发消息)、大表情(只有 1–3 个 emoji 的消息放大显示);
上传进度显示在气泡上,可取消;自动下载设置(Wi-Fi / 流量下各类媒体)。

**验收**:每种类型在安卓和网页版互发互看;网页版录的语音安卓能放,反之亦然。

**测试**:e2e `e2e_chat_media`;dart 单测(相册布局、波形绘制、录音手势状态机)。

### #348 会话列表与管理

**要做**:`chat_list_page.dart`:顶部固定「通知」「订单消息」「互动消息」三行(D24),归档行(有归档时),会话行(头像、标题、最后一条(群里带发送人)、时间、未读角标(免打扰为灰)、@ 角标、置顶图标、自己最后一条的勾、「草稿:」红字);
左滑:置顶 / 免打扰;右滑:归档 / 删除;长按多选;分组条(全部 / 私聊 / 群组 / 频道 / 未读 + 自定义分组,§5 限制 10 个);
新建按钮:新建群组、新建频道、添加联系人、扫一扫;顶部搜索。

**验收**:置顶 5 个上限、第 6 个给出明确提示;免打扰到期自动恢复;删除私聊可选「同时为对方删除」。

**测试**:e2e `e2e_chat_dialogs`;dart 单测(排序:置顶按 rank、其余按最后消息时间;分组过滤)。

### #349 群组

**要做**:建群(选成员,至少 1 人)、群资料(头像、名称、简介)、成员列表(角色、头衔、在线)、拉人(对方隐私「谁能拉我进群」不允许时改成发邀请链接)、
管理员任免与权限(§5.6)、默认权限与按人限制(可设到期)、封禁 / 移出、邀请链接(主链接 + 多条附加链接:名称、过期、次数、需审批)、入群申请审批、
慢速模式、置顶消息(多条,顶部条可切换)、服务消息(§5.2)、公开群(设用户名,可被搜到)、新成员看不看得到历史(`history_visible`)、转让群主(要本人确认)、退群 / 解散;
已读名单(≤ 100 人)。

**验收**:没权限的操作按钮不出现,接口也拒;被封禁的人通过邀请链接也进不来;慢速模式剩余秒数在输入栏显示。

**测试**:e2e `e2e_chat_groups`(权限矩阵逐项);单测(权限真值表)。

### #350 频道

**要做**:建频道(公开 / 私密)、发帖(只有管理员)、订阅 / 退订、订阅者列表(管理员可见)、浏览量(每人一次,批量合并事件)、署名、静默发布、帖子回应、
公开频道的链接与搜索、频道资料页(订阅数、链接、简介);频道消息在列表里显示为频道发出。

**测试**:e2e `e2e_chat_channels`。

### #351 互动:回应、投票、骰子、贴纸、GIF、定时 / 静音、收藏夹

**要做**:回应(每人每条最多 3 个,群可限定可用表情,长按看谁回应了);投票 / 测验(§2.1,题目 ≤ 255、选项 2–10、匿名 / 公开、多选、测验正确答案和解析、定时截止、手动截止);
骰子(🎲🎯🏀⚽🎳🎰,值服务端随机,动画客户端做);贴纸(贴纸包管理、上传建包、内置大表情包、最近使用);GIF(转 MP4、保存的 GIF 列表);
定时发送(会话内「定时消息」页,可改时间、立即发送、删除;到点由清扫任务发出,发出后照常通知);静音发送;收藏夹(转发到自己,支持加标签搜索)。

**测试**:e2e `e2e_chat_extras`。

### #352 搜索与共享媒体

**要做**:全局搜索(会话名、联系人、公开群 / 频道 / 用户名、消息正文 —— 只搜我能读的会话,`ILIKE` + `(chat_id, created_at)` 索引,结果按时间倒序分页);
会话内搜索(上下跳转、按人筛选、按日期跳转);共享媒体页(图片视频九宫格、文件、链接、语音四个页签);链接预览(`GET /chat/v1/link-preview`,SSRF 防护:DNS 解析后拒私网 / 回环 / 链路本地地址,重定向每一跳都查,≤ 1MB、5 秒)。

**测试**:e2e `e2e_chat_search`(含 SSRF 探针:`http://127.0.0.1`、`http://169.254.169.254`、跳转到内网)。

### #353 通知

**要做**:新消息事件 → 对每个接收者:没被免打扰(或 @ 了他 / 回复了他)、没有前台连接 → JPush(复用 `services/push.py` 的 `fanout`,带 `{"type":"chat","chat_id":…}`);
预览按 D20;群消息 3 秒内合并;推送点击直达会话;App 在前台时顶部横幅(可点、可上滑收起);桌面角标 = 未读会话数(不含免打扰);
通知设置:私聊 / 群 / 频道三类默认 + 每个会话单独。

**测试**:e2e `e2e_chat_push`(推送日志表断言:前台不推、免打扰不推、@ 穿透免打扰、预览关闭时正文不出现)。

### #354 语音 / 视频通话

**要做**:信令(§5.12)、`calls` 表、ICE 服务器接口、`deploy/docker-compose.prod.yml` 加 coturn(REST 共享密钥,端口写进上线手册);
客户端 `flutter_webrtc`:来电全屏页(接听 / 拒绝,振铃)、通话页(静音、免提、切摄像头、开关视频、挂断、计时)、小窗;
通话记录进聊天(服务消息)和「通话」列表。
**测试**:e2e `e2e_calls`(信令状态机:忙线、超时未接、拒接、隐私拒绝、拉黑);真机 / 模拟器 + 网页版实际通一次。

### #355 机器人平台

**要做**:`role=bot` 用户、`bots` 表、开发者后台「机器人」页(建机器人、改名、头像、简介、命令、菜单按钮选小程序、重置 token、webhook);
`/bot/<token>/…`(§5.13);消息里的内联键盘(`url` / `callback_data` / `web_app`)、回复键盘先不做;命令菜单(输入 `/` 联想);
机器人发的消息标「机器人」;用户可以拉黑机器人。
**测试**:e2e `e2e_bots`(getUpdates、webhook 重试、回调、隐私模式)。

### #356 聊天客户端架构

**要做**:`chat/store.dart`(单例 `ChangeNotifier`:会话列表、每个会话最近消息、在线状态、typing)、`chat/sync.dart`(连接、心跳、指数退避重连、pts 缺口补齐、reset)、
`chat/outbox.dart`(待发队列,落本地,重启继续发)、`chat/cache.dart`(会话列表 + 每会话最近 100 条落本地,离线可看);
API 客户端 `packages/shared/lib/src/social_api.dart`;网页版同一套代码(`web_socket_channel`、`shared_preferences`)。

**测试**:dart 单测(事件应用幂等、缺口检测、outbox 重试、缓存恢复)。

### #357 视频数据模型与迁移

§7「视频」全部表 + 迁移;`services/video_state.py`(§5.8 状态机);`services/video_rank.py`(§5.9 纯函数)。
**测试**:单测(状态机非法迁移、排序公式、S3 列名扫描)。

### #358 投稿与创作中心

**要做**:投稿页(选视频 → 分片上传带进度、可后台继续;标题 ≤ 80、简介 ≤ 2000、分区、标签 ≤ 10、封面(自动三帧可选或上传)、自制 / 转载(转载必填来源)、
分 P(加 / 删 / 排序 / 改标题)、可见性、弹幕 / 评论开关、挂店铺 + 合作声明(D16)、定时发布);提交 → 转码 → 审核;
创作中心:稿件列表(状态标签:转码中 / 审核中 / 已通过 / 未通过(原因 + 申诉)/ 已下架)、单稿数据(播放、点赞、硬币、收藏、弹幕、评论、分享,近 30 天曲线)、编辑、删除;
实名门槛(D11)。
**测试**:e2e `e2e_video_upload`(从上传到发布全流程、驳回重交、编辑后旧版继续在线)。

### #359 播放器

`apps/user_app/lib/video/player/`:基于 `video_player` 自绘控件:播放暂停、进度(拖动时显示雪碧图缩略图)、时间、清晰度(自动 / 1080 / 720 / 480 / 360;
自动 = Wi-Fi 720、流量 480)、倍速(0.5–2)、全屏(横屏视频转横屏、竖屏视频不转)、锁屏、手势(双击暂停、横滑快进、左侧上下亮度、右侧上下音量、长按 3 倍速)、
续播(从历史进度,提示「上次看到 xx:xx」)、连播下一 P / 相关视频、切清晰度保持进度、网络错误重试;播放心跳每 15 秒上报进度。
**测试**:dart 单测(手势判定、清晰度选择、雪碧图坐标计算)。

### #360 弹幕

服务端:存取接口、分段、限流、屏蔽词、UP 主可删自己视频的弹幕;客户端:`danmaku/engine.dart`(§5.10 轨道算法,纯 Dart,单测)+ `danmaku/layer.dart`(`CustomPainter` + `Ticker`,暂停 / 倍速 / 拖动同步)、
发送框(颜色、模式、字号)、设置面板、高能进度条。
**测试**:单测(轨道分配、碰撞、丢弃、seek 后重建);e2e `e2e_danmaku`。

### #361 视频详情页

播放器在上;下面:标题、播放数、弹幕数、发布时间、UP 主卡(头像、名字、粉丝数、关注)、三连按钮(长按点赞 1.5 秒触发三连动画)、分享(发到消息 / 复制链接)、
简介展开、标签、分 P 选择、「简介 / 评论」两个页签、相关视频(同 UP 主、同分区、同标签,排序同 §5.9)、挂的店铺卡(D16)、举报。

### #362 评论

楼中楼(一级评论 + 回复,回复里显示「回复 @某人」)、点赞点踩(点踩数不显示)、热度 / 时间排序、UP 主置顶一条、UP 主可删自己视频下的评论、作者标「UP 主」、@ 提及、
被回复 / 被 @ / 被赞进互动消息(#367);拉黑的人的评论对我不显示(S7)。
**测试**:e2e `e2e_video_comments`。

### #363 竖屏短视频流

`video/vertical_feed.dart`:纵向 `PageView`,当前页播放、前后各预加载一个(先建控制器、只缓冲不播放),离开页暂停并释放第三个以外的控制器;
自动循环;单击暂停 / 播放;双击点赞(点击位置出心形动画);右侧栏(头像 + 关注、赞、评论、收藏、分享);底部 @UP 主、标题(话题可点)、进度条(可拖,拖动时放大显示时间);
长按菜单(不感兴趣、举报、倍速、清屏);左滑进 UP 主空间;评论是底部弹层(同 #362);声音默认开。
**验收**:连续滑 30 个视频不卡、不重播、内存稳定(控制器始终 ≤ 3 个)。

### #364 首页与发现

视频 tab:顶部搜索框 + 投稿按钮;页签「关注 / 推荐 / 热门 / 竖屏」+ 分区入口;推荐 / 热门 / 关注是双列卡片流(封面、时长、播放数、弹幕数、标题两行、UP 主),下拉刷新、上拉加载;
分区页、排行榜页(全站 / 分区,1 / 3 / 7 天);每张推荐卡长按「为什么推荐」「不感兴趣」;设置里「个性化推荐」开关(S9)。
**测试**:e2e `e2e_video_feed`(公式逐条复算、关闭个性化与匿名一致、同 UP 主一屏 ≤ 2)。

### #365 搜索

视频搜索(标题、标签、简介、UP 主名 `ILIKE`,排序综合 / 最多播放 / 最新 / 最多弹幕,时长筛选 0–10 / 10–30 / 30–60 / 60+ 分钟,分区筛选)、用户搜索、搜索历史(本地)、热搜(§2.2 防刷)。

### #366 个人:空间、关注、收藏、稍后再看、历史、硬币

UP 主空间(头像、名字、签名、关注 / 粉丝 / 获赞、投稿列表(最新 / 最多播放)、公开收藏夹、「发消息」进私聊、关注按钮);关注 / 粉丝列表;
收藏夹(默认收藏夹 + 自建,公开 / 私密,移动 / 删除);稍后再看;历史(按天分组,带进度条,可删单条 / 清空 / 暂停记录);
硬币(余额、明细;每日首次打开视频 tab 领 1 枚,D13)。「我的」页加入口:收藏、历史、稍后再看、我的投稿、创作中心、硬币。

### #367 互动消息

「消息」列表第三行:回复我的 / @我的 / 收到的赞 / 系统通知(投稿审核结果、处罚通知)四个页签;点开跳到对应视频的评论位置;
赞按「这条评论 / 这个视频」合并(「小王等 12 人赞了你的视频」)。

### #368 审核与治理

视频审核队列(转码完成的稿件,按提交时间;审核员看预览、元数据、原因代码选择);举报(消息、群、频道、用户、视频、评论、弹幕)统一进一张表,
「7 天内 3 个不同的人举报」自动进复审;处置:删消息、禁言(限时)、封群 / 频道、封号(限时 / 永久)、下架视频;
申诉(S6);管理员查看被举报私聊消息(S8,只能看举报单里那几条和前后各 5 条上下文)。

**接口**(聊天这一半;视频那一半见 VIDEO-API.md §11):处罚种类与执行点、被挡时 403 的 `detail`、
`GET /social/v1/me/sanctions`、`POST /social/v1/sanctions/{id}/appeal`、`/admin/social/chat-reports…`、
`/admin/social/chat-messages?report_id=`(S8 唯一的查看口子)、`/admin/social/sanctions…`、`/admin/social/social-appeals…`
全部写在 [COMMUNITY-GOVERNANCE.md](COMMUNITY-GOVERNANCE.md) §1–§6(和实现、测试逐字一致,单测对着比)。

### #369 内容安全基础

`services/moderation.py`:屏蔽词(本地词表 + 管理后台维护,命中 → 拒绝发送并告知「包含不允许的内容」;弹幕 / 评论 / 用户名 / 群名 / 视频标题都过)、
新号限制(§5.7)、同一内容短时间群发多个会话判垃圾(24 小时内同样文字发给 20 个以上私聊 → 暂停发送 1 小时并提示)、
预留第三方内容审核接口(和 OCR 对接位一个做法,默认关)。

### #370 管理后台

admin-web 加「社区治理」菜单:视频审核、举报处理、处置记录、屏蔽词、数据(每日消息数、活跃会话、投稿量、审核中位时长)。

**接口**:`GET /admin/social/community-stats?days=30`,口径见 [COMMUNITY-GOVERNANCE.md](COMMUNITY-GOVERNANCE.md) §4.3、§7。

### #371 透明中心「社区」栏

公示:视频审核量、驳回率、中位审核时长;处置记录(对象类型 + 原因代码 + 申诉结果,不含个人信息);推荐 / 热门公式原文(链接到 `services/video_rank.py`);
管理员查看私聊的次数(按月,S8)。

**接口**:`GET /transparency/community`,字段和「不公开」清单见 [COMMUNITY-GOVERNANCE.md](COMMUNITY-GOVERNANCE.md) §4.4、§7。

### #372 性能与容量

目标(部署机 4 核):同时在线 2,000 连接;单会话发消息 p95 < 150ms;会话列表 p95 < 200ms;视频卡片流 p95 < 200ms;
消息分页走 `(chat_id, seq)` 索引、会话列表一条 SQL(不 N+1);计数用增量 + 每小时校正;压测脚本 `scripts/loadtest_chat.py`(独立进程发,旁路探针验证,见压测经验)。

### #373 安全审计(逐项验证,每项先证明守卫会响)

越权(别人的会话、消息、媒体、草稿、投稿、收藏夹、历史)、IDOR、非成员拿事件、媒体直链、XSS(消息、群名、视频标题、评论、弹幕在网页版和管理后台只当文字)、
SSRF(链接预览)、上传(魔数、zip 炸弹、超大分辨率图片)、限流、WebSocket 鉴权、Bot token 泄漏(日志里只有前 6 位)、S1–S10 每条的守卫。

### #374 合规清单(要法务确认,这里不下结论)

即时通信(《即时通信工具公众信息服务发展管理暂行规定》:后台实名、公众账号审核)、群组(《互联网群组信息服务管理规定》:群主责任、日志留存)、
频道(《互联网用户公众账号信息服务管理规定》)、跟帖评论 / 弹幕(《互联网跟帖评论服务管理规定》)、网络视听(**《信息网络传播视听节目许可证》—— 上线视频的前提**)、
短视频审核(《网络短视频内容审核标准细则》)、算法推荐(备案、可关闭个性化)、未成年人模式、个人信息(聊天记录的处理者角色、导出、删除)、通话(是否涉及电信业务许可)、机器人(第三方开发者责任)。
**上线视频之前卡在许可证上**,在合规清单里写明,生产开关默认关。

### #375 上线手册

开关(`social_chat`、`social_video`、`video_upload`、`calls`、`bots`、`media_transcode`,生产缺省:聊天开、视频关、上传关、通话关、机器人关,等合规结论)、
迁移、compose 加 `media-worker` 和 `coturn`、nginx 加 `/vod/` 内部 location 和 `/ws/v2`、对象存储容量预估、回退办法。

### #376 验证

1. 两个账号(安卓模拟器 + 网页版)完整走一遍「消息」:每种消息类型、回复转发编辑删除、回应、置顶、已读、正在输入、在线状态、群(建群、管理员、邀请链接、封禁、慢速)、
   频道(发帖、订阅、浏览量)、投票、贴纸、搜索、分组、免打扰、归档、推送、通话、机器人;
2. 「视频」:投稿(横屏 + 竖屏各一个)→ 转码 → 审核通过 → 推荐 / 竖屏流里出现 → 另一个账号播放、发弹幕、评论、三连、关注 → 互动消息收到 → 创作中心数据变化;
3. 订单入口:四格、状态条、推送直达;
4. 全量回归:单测、`make analyze`、全部 e2e、安全扫描、字号棘轮、显示字覆盖率。

---

## 11. 纪律

- 不说 push 就不 push,不部署生产,不碰生产数据;
- 每条提示词做完就提交一次(Conventional Commits,中文描述,不写 AI 字样),提交前跑安全扫描;
- 协议(§5)改了,文档、实现、测试一起改;
- 新增依赖:Python 走阿里云源,npm 走 npmmirror,Flutter 包写明用途;
- 注释和提交信息照仓库原有习惯(中文,讲为什么);
- 跑 e2e 必须看退出码。

## 12. 完成的标志

1. 底部导航是「首页 / 消息 / 视频 / 我的」,订单三个入口都能用;
2. §10 #376 的三段走查全部通过,并有截图 / 日志为证;
3. S1–S10 每条都有守卫测试,并且每个守卫都弄红过一次;
4. 单测、`make analyze`、全部 e2e(含新增的 `e2e_social_*`、`e2e_chat_*`、`e2e_media`、`e2e_transcode`、`e2e_realtime`、`e2e_video_*`、`e2e_danmaku`、`e2e_calls`、`e2e_bots`)全绿;
5. 合规清单、上线手册、安全审计记录三份文档齐全。
