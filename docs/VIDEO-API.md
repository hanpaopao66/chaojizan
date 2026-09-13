# 视频接口参考(客户端用)

对应 DEV-PROMPTS-40 的「视频」部分(#357–#368)。服务端实现在 `server/app/routers/video.py`、
`routers/video_admin.py`、`routers/notifications.py` 和 `services/video*.py`。
**本文的示例响应都是从真实接口抓的**(只删掉了列表里重复的条目、把长签名截短),字段名和类型以这里为准;
改接口时本文要一起改(DEV-PROMPTS-40 §11)。

---

## 0. 通用约定

### 0.1 鉴权

- `Authorization: Bearer <JWT>`,和其它接口同一个 token;
- 标 **公开** 的接口没登录也能调(只能看到公开稿件);登录了会多出和「我」有关的字段(`me`、个性化推荐);
- 标 **登录** 的接口要登录,而且只对用户端账号开放(D1),商家 / 骑手账号调回 `403「消息和视频只在用户端开放」`;
- 标 **管理员** 的是 `/admin/social/…`,要管理员账号;
- 投稿(建稿、挂分 P、提交)要先完成实名认证(D11,`POST /auth/verify-identity`),否则 `403「发视频要先完成实名认证…」`。

### 0.2 开关(#375)

| 开关 | 关着时 |
|---|---|
| `video_enabled` | `/video/v1/*` 全部回 `503 {"detail": "视频功能暂未开放"}`(生产缺省关,等许可证) |
| `video_upload_enabled` | 建稿、挂分 P、提交、用 `purpose=video` 上传原片 / 封面回 `503 {"detail": "视频投稿暂未开放"}` |

互动消息 `/social/v1/notifications` 不受开关影响(已经收到的审核结果、处罚通知关了也得能看)。
客户端见到 503 + 上面这句话时,视频 tab 显示「暂未开放」的空状态,不要重试。

### 0.3 错误

错误体统一是 `{"detail": "给用户看的中文"}`,直接展示 `detail` 即可。
**一个例外**:被禁言 / 封号时(发评论、发弹幕、提交投稿、以及封号期间的所有互动和投稿接口)是 403,
`detail` 是对象 `{"error": "sanctioned", "message": "给用户看的一句话", "reason_code", "reason_label", "until", "can_appeal", …}`,
展示 `detail.message`;字段见 [COMMUNITY-GOVERNANCE.md](COMMUNITY-GOVERNANCE.md) §3。

| 状态码 | 什么时候 |
|---|---|
| 401 | 没登录 / token 过期(要登录的接口) |
| 403 | 没权限:别人的稿件、UP 主关了弹幕 / 评论、有拉黑关系、没实名、原审核员处理自己结论的申诉、被禁言 / 封号 |
| 404 | 不存在、已删除、**或者你没权限看**(审核中、私密、下架的稿件对别人一律 404,不告诉你「有但你看不了」) |
| 409 | 状态不对:稿件在转码 / 审核中不能改、已经投满硬币、每个结论只能申诉一次、没有改动可提交 |
| 422 | 输入不合规:字段超长、弹幕换行、原因代码不对、屏蔽词(`「评论包含不允许发布的内容,请修改后重试」`) |
| 429 | 限流(见 0.6),`detail` 会说清楚是哪一条 |
| 503 | 开关关着(见 0.2) |

示例:

```json
{"detail": "发视频要先完成实名认证(我的 → 设置 → 实名认证)"}
{"detail": "弹幕发得太快了,3 秒一条"}
{"detail": "视频不存在或已删除"}
```

### 0.4 标识与时间

- 视频对外只用 `vid`:`sv` + 10 位 base58(`^sv[1-9A-HJ-NP-Za-km-z]{10}$`),分享链接 `https://chaojizan.cc/v/<vid>`;
- 分 P、评论、弹幕、收藏夹、互动消息用整数 `id`;
- 时间一律 ISO 8601 带时区(UTC),如 `"2026-09-13T02:09:39.575914+00:00"`;时长、播放位置一律**毫秒**(`*_ms`)。

### 0.5 分页

两种,别混:

| 方式 | 用在 | 怎么翻 |
|---|---|---|
| `page`(从 0 起) | 推荐、热门、竖屏流、分区、搜索、UP 主投稿 | 响应里 `has_more` 为真就 `page+1`。推荐类的「一页」就是「一屏 20 条」(§5.9 去重按屏算) |
| `cursor` | 关注流、评论、回复、历史、收藏夹内容、粉丝 / 关注列表、互动消息、硬币流水、创作中心列表 | 把上一页的 `next_cursor` 原样传回;`next_cursor` 为 `null` 表示没有了。**游标是不透明字符串,不要自己拼** |

推荐类的结果随时间变(热度每分钟都在衰减),翻页之间可能有一两条重复或跳过,客户端按 `vid` 去重即可。

### 0.6 限流与上限(§5.7、D8、D13)

| 项 | 限制 |
|---|---|
| 弹幕 | 每人每 3 秒 1 条、每天 1,000 条;≤ 100 字、单行 |
| 评论 | 每人每 5 秒 1 条、每天 500 条;≤ 1,000 字 |
| 点赞 / 投币 / 收藏 / 分享 / 三连 / 关注 / 评论赞踩 | 每人每秒 5 次(共用一个桶) |
| 搜索 | 每人(没登录按 IP)每分钟 60 次 |
| 播放心跳 | 每人 / 每设备每分钟 120 次 |
| 投稿 | 每人每天建 10 个稿件;每个稿件最多 10 P;单 P ≤ 1GB、≤ 30 分钟 |
| 标题 / 简介 / 标签 | 标题 ≤ 80 字;简介 ≤ 2,000 字;标签 ≤ 10 个、每个 ≤ 20 字 |
| 硬币 | 每天第一次打开视频 +1;投稿过审 +2(每天从过审拿到的最多 10 枚);自制视频每人最多投 2 枚、转载 1 枚;不能投自己;**不能充值、提现、兑换**(S4) |
| 收藏夹 | 自建最多 50 个,每个最多 1,000 个视频;稍后再看最多 100 个 |

### 0.7 分区

`GET /video/v1/zones` 返回全部分区(带公开视频数)。当前的 key:

`life` 生活 · `food` 美食 · `shop_visit` 探店 · `game` 游戏 · `knowledge` 知识 · `tech` 科技 · `music` 音乐 ·
`dance` 舞蹈 · `film` 影视 · `animal` 动物圈 · `sports` 运动 · `car` 汽车 · `fashion` 时尚 · `funny` 搞笑 · `travel` 旅行

### 0.8 原因代码(§5.11,审核、处罚、举报共用)

| 代码 | 含义 | 代码 | 含义 |
|---|---|---|---|
| C101 | 骚扰、辱骂 | V201 | 视频侵权(未经授权搬运) |
| C102 | 垃圾广告、引流 | V202 | 标题 / 封面与内容不符 |
| C103 | 诈骗 | V203 | 画质或内容不完整(黑屏、无声、静止) |
| C104 | 色情、低俗 | V204 | 分区选错 |
| C105 | 暴力、血腥 | V205 | 未声明合作(挂店铺却选了「无合作」) |
| C106 | 违法违规(赌博、毒品、枪支等) | V206 | 危险行为 |
| C107 | 侵犯隐私(未经同意公开他人信息) | X999 | 其他(必须写说明,≥ 5 个字) |
| C108 | 冒充他人或官方 | | |
| C109 | 未成年人不宜 | | |

---

## 1. 公共对象

### 1.1 人(简卡)`Person`

```json
{"id": 236, "name": "用户0934", "username": "Upzhu70527", "avatar": ""}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | 用户 id |
| name | string | 显示名;注销了的是「已注销用户」 |
| username | string \| null | @用户名(没设为 null) |
| avatar | string | 头像地址;对方头像隐私不许你看、或者对方拉黑了你,是空串 |

**任何视频接口都不含手机号**(S2)。

### 1.2 视频卡片 `VideoCard`

推荐 / 热门 / 搜索 / 空间 / 历史 / 收藏夹 / 稍后再看共用这个形状。

```json
{
  "vid": "svHbFUgZ3A32",
  "title": "示例视频:六秒测试片",
  "cover": "/img/video_cover/u236-0ec4f37a09eb4416b215313be6d98008.jpg",
  "duration_ms": 6000,
  "is_vertical": false,
  "zone": "tech",
  "zone_name": "科技",
  "tags": ["示例", "测试"],
  "views": 1, "likes": 1, "coins": 2, "favorites": 1, "shares": 1,
  "danmaku_count": 1, "comment_count": 3,
  "published_at": "2026-09-13T02:09:39.575914+00:00",
  "collab": false,
  "uploader": {"id": 236, "name": "用户0934", "username": "Upzhu70527", "avatar": ""}
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| cover | string | 公开封面(`/img/…`,可以直接缓存);没过审的稿件是空串 |
| is_vertical | bool | 竖屏 = 第一 P 宽 < 高 |
| views…comment_count | int | 累计数(展示用) |
| published_at | string \| null | 没发布过是 null |
| collab | bool | 挂了店铺且声明了「有合作」→ 视频上要标「合作」(D16) |

历史、收藏夹、稍后再看里**已经看不了的视频**(删了、下架、改私密)是 `{"vid": "...", "title": "视频已失效", "cover": "", "invalid": true}`。

### 1.3 排序中间量 `rank` / `why`(推荐、热门、竖屏、相关)

每条都带着算它的数,「为什么推荐」直接展示 `why`,谁都能按 §5.9 复算:

```json
"rank": {
  "counts": {"views": 6, "likes": 6, "coins": 3, "favorites": 2, "comments": 2, "danmaku": 2, "shares": 1},
  "interaction": 108,
  "hours": 1.0682802480555555,
  "hot": 20.094685755703022,
  "followed": false,
  "top_zone": true,
  "recommend": 23.108888619058472
},
"why": ["「科技」是你近 30 天最常看的分区之一(+0.15)", "近 72 小时互动分 108,发布 1.1 小时,热度 20.09"]
```

- `counts`:近 72 小时内的增量,每种互动同一个人只算一次;
- `interaction = views×1 + likes×5 + coins×10 + favorites×8 + comments×6 + danmaku×2 + shares×10`;
- `hours` = (响应里的 `ranked_at` − `published_at`) 小时数;`hot = interaction ÷ (hours + 2)^1.5`;
- `recommend = hot × (1 + 0.3×followed + 0.15×top_zone)`;关掉个性化 / 没登录时两个布尔都是 false;
- 公式原文和全部参数:`GET /video/v1/rank/formula`。

### 1.4 分 P `Part` 与播放地址

```json
{
  "id": 221, "idx": 0, "title": "第一 P", "status": "ready",
  "duration_ms": 6000, "w": 1280, "h": 720,
  "renditions": [
    {"q": 720, "w": 1280, "h": 720, "size": 192183, "bitrate": 256244,
     "url": "/video/v1/vod/svHbFUgZ3A32/221/720.mp4?u=237&e=1789948800&s=04f6d9cc…"},
    {"q": 480, "w": 852, "h": 480, "size": 151859, "bitrate": 202478, "url": "…/480.mp4?u=237&e=…&s=…"},
    {"q": 360, "w": 640, "h": 360, "size": 141659, "bitrate": 188878, "url": "…/360.mp4?u=237&e=…&s=…"}
  ],
  "sprite": {
    "interval_ms": 1000, "cols": 10, "rows": 10, "w": 160, "h": 90, "count": 6,
    "urls": ["/video/v1/vod/svHbFUgZ3A32/221/sprite/0.jpg?u=237&e=1789948800&s=04f6d9cc…"]
  }
}
```

- `renditions` 按清晰度从高到低,只有不超过原片的档位(360 永远有);竖屏按宽算档位(720×1280 是「720」档);
  自动清晰度建议:Wi-Fi 720、流量 480(#359);
- 播放地址支持 `Range`(`206 Partial Content`),H.264 + AAC 的 MP4、`faststart`,可以边下边播;
- **地址带签名**(`u` / `e` / `s`):网页版 `<video>` 带不了 Authorization 头,所以地址本身绑定了看的人;
  播放时服务端照样按这个人重新判权 —— 稿件删了、下架了、改私密了,旧地址立刻 404。签名不含清晰度,切清晰度不用重新拿;
  `e` 是到期时间(7–8 天后的零点),过期了重新调详情接口拿;
- 没登录的人拿到的是不带签名的地址,只对公开稿件有效;
- 雪碧图:每张 `cols × rows` 格、每格 `w × h`,第 `i` 格对应 `i × interval_ms` 那一刻。拖到位置 `t` 毫秒时:
  `i = min(floor(t / interval_ms), count − 1)`,`sheet = floor(i / (cols×rows))`,`row = floor((i mod (cols×rows)) / cols)`,`col = i mod cols`。

---

## 2. 浏览(公开)

### GET /video/v1/feed/recommend?page=0 — 推荐

登录且开着个性化时按 §5.9「推荐」排(关注的 UP 主 +0.3、常看分区 +0.15,看过 >50% 的 7 天内和「不感兴趣」的不出现);
没登录 / 关了个性化 = 所有人一样(S9:逐条相等)。一屏 20 条,同一个 UP 主一屏最多 2 个。

```json
{
  "items": [ {…VideoCard, "rank": {…}, "why": ["…"]} ],
  "page": 0,
  "has_more": true,
  "personalized": true,
  "ranked_at": "2026-09-13T02:09:00+00:00",
  "sort": "recommend"
}
```

`ranked_at` 是算分用的「现在」(取整到分钟):复算 `hours` 用它。一屏不满 20 条不代表没有下一屏(剩下的全是同几个 UP 主的),以 `has_more` 为准。

### GET /video/v1/feed/hot?page=0 — 热门

按热度排,**不个性化**,登录没登录一样;不做同 UP 主去重。响应同上,`"sort": "hot"`、`"personalized": false`。

### GET /video/v1/feed/vertical?page=0 — 竖屏流

只取竖屏视频,其余同「推荐」。

### GET /video/v1/feed/following?cursor= — 关注流(登录)

关注的 UP 主的新投稿,新发布的在前。

```json
{"items": [ {…VideoCard} ], "next_cursor": null}
```

### GET /video/v1/zones — 分区列表

```json
{"items": [{"zone": "life", "name": "生活", "count": 72}, {"zone": "food", "name": "美食", "count": 3}]}
```

### GET /video/v1/zones/{zone}?order=hot|new&page=0 — 分区页

`order=hot` 按热度(响应同热门,多 `zone` / `name` / `order`);`order=new` 按发布时间:

```json
{"items": [ {…VideoCard} ], "page": 0, "has_more": true, "zone": "tech", "name": "科技", "order": "new"}
```

不存在的分区 404。

### GET /video/v1/rank?zone=&days=1|3|7 — 排行榜

某分区(不传 = 全站)按「互动分」在 1 / 3 / 7 天窗口里排,前 100 名,只含互动分 > 0 的。`days` 只能是 1 / 3 / 7(否则 422)。

```json
{
  "items": [
    {…VideoCard,
     "rank": {"counts": {"views": 6, "likes": 6, "coins": 3, "favorites": 2, "comments": 2, "danmaku": 2, "shares": 1},
              "interaction": 108},
     "position": 1}
  ],
  "zone": null, "days": 1,
  "ranked_at": "2026-09-13T02:09:00+00:00",
  "window_start": "2026-09-12T02:09:00+00:00"
}
```

### GET /video/v1/rank/formula — 公式原文

```json
{
  "formula": "互动分 = 播放 × 1 + 点赞 × 5 + …(§5.9 原文,换行用 \\n)",
  "weights": {"views": 1, "likes": 5, "coins": 10, "favorites": 8, "comments": 6, "danmaku": 2, "shares": 10},
  "window_hours": 72, "decay_offset_hours": 2, "decay_power": 1.5,
  "follow_bonus": 0.3, "zone_bonus": 0.15, "top_zones": 3, "zone_lookback_days": 30,
  "screen_size": 20, "per_uploader_per_screen": 2,
  "watched_ratio": 0.5, "watched_skip_days": 7, "rank_windows_days": [1, 3, 7],
  "source": "server/app/services/video_rank.py"
}
```

### GET /video/v1/videos/{vid} — 视频详情

公开稿件谁都能看;审核中 / 私密 / 被驳回的只有 UP 主(和审核员)能看,别人 404。

```json
{
  …VideoCard(uploader 多两个字段),
  "uploader": {"id": 236, "name": "用户0934", "username": "Upzhu70527", "avatar": "", "fans": 0, "followed": false},
  "description": "接口文档用的示例稿件",
  "copyright": "original",
  "source_url": "",
  "status": "published",
  "status_label": "已发布",
  "visibility": "public",
  "allow_danmaku": true,
  "allow_comments": true,
  "shop": null,
  "shop_collab": null,
  "link": "https://chaojizan.cc/v/svHbFUgZ3A32",
  "parts": [ {…Part} ],
  "is_owner": false,
  "me": {
    "liked": false, "coins": 0, "coin_max": 2, "favorited": false, "folder_ids": [],
    "watch_later": false, "coin_balance": 0,
    "progress": null
  }
}
```

| 字段 | 说明 |
|---|---|
| copyright | `original` 自制 / `repost` 转载(转载带 `source_url`) |
| shop | 挂的店铺 `{"id", "name", "logo"}` 或 null;`shop_collab` 与商家有无合作(`true` 时标「合作」) |
| parts | 有线上版本的稿件只给**线上那几 P**(改动审核中新加的 P 不在这里,在创作中心);没发布过的只有 UP 主看得到全部 P |
| me | 没登录是 null。`coins` 我给这个视频投了几枚、`coin_max` 最多几枚(自制 2 / 转载 1)、`coin_balance` 我的硬币余额、`progress` 续播进度 `{"part_idx", "position_ms", "duration_ms", "watched_at"}` 或 null |

没登录时 `parts[].renditions[].url` 不带签名(`/video/v1/vod/svHbFUgZ3A32/221/720.mp4`)。

### GET /video/v1/videos/{vid}/related — 相关视频

同 UP 主、同分区或同标签的公开视频,按「推荐」排(登录且开着个性化时带个性化),最多 20 条。

```json
{"items": [ {…VideoCard, "rank": {…}, "why": [...]} ], "ranked_at": "2026-09-13T02:09:00+00:00"}
```

### GET /video/v1/search — 视频搜索

| 参数 | 说明 |
|---|---|
| q | 必填,1–64 字;在标题 / 标签 / 简介 / UP 主名(和 @用户名)里 ILIKE |
| order | `default` 综合(标题命中 3 分 + 标签 2 + UP 主名 2 + 简介 1,同分按播放、再按新)/ `views` 最多播放 / `new` 最新 / `danmaku` 最多弹幕 |
| duration | `0` 不限、`1` 0–10 分钟、`2` 10–30、`3` 30–60、`4` 60 以上 |
| zone | 分区 key |
| page | 从 0 起,一页 20 条 |

```json
{"items": [ {…VideoCard} ], "page": 0, "has_more": false, "order": "default"}
```

第一页的搜索词会记进热搜统计(只数登录用户)。搜索历史客户端本地存。

### GET /video/v1/search/users?q=&page=0 — 用户搜索

名字或 @用户名包含关键词的用户端账号,按粉丝数排。

```json
{"items": [{"id": 236, "name": "用户0934", "username": "Upzhu70527", "avatar": "", "fans": 1, "videos": 1, "followed": false}],
 "page": 0, "has_more": false}
```

### GET /video/v1/search/hot — 热搜

24 小时内至少 5 个**不同的登录用户**搜过的词,按人数排,最多 10 个;命中屏蔽词的不上榜。

```json
{"items": [{"term": "热词18374", "users": 5}], "min_users": 5}
```

### GET /video/v1/users/{id}/space — UP 主空间

```json
{
  "user": {"id": 236, "name": "用户0934", "username": "Upzhu70527", "avatar": "", "bio": ""},
  "is_self": false,
  "followed": true,
  "can_follow": true,
  "stats": {"following": 0, "fans": 1, "likes": 1, "videos": 1},
  "folders": [{"id": 46, "title": "学习", "is_default": false, "public": true, "count": 3, "cover": "/img/…", "updated_at": "…"}],
  "videos": {"items": [ {…VideoCard} ], "page": 0, "has_more": false, "order": "new"}
}
```

- `stats.likes`:公开视频收到的赞的总和;`folders`:别人看只有公开收藏夹,自己看是全部;
- `can_follow` 为 false:没登录、看自己、或者双方有拉黑关系;「发消息」直接用聊天的 `POST /chat/v1/chats/private`。

### GET /video/v1/users/{id}/videos?order=new|views&page=0 — UP 主的投稿

响应同分区页(`order` 回显)。

### GET /video/v1/users/{id}/fans?cursor= · GET /video/v1/users/{id}/following?cursor= — 粉丝 / 关注列表

```json
{"items": [{"id": 238, "name": "用户0036", "username": null, "avatar": "", "bio": "",
            "followed": false, "since": "2026-09-13T02:09:40.178390+00:00"}],
 "next_cursor": null}
```

`followed`:**我**有没有关注这个人;`since`:他关注 / 被关注的时间。新的在前。

### GET /video/v1/favorites/{folder_id}?cursor= — 看一个收藏夹

公开收藏夹谁都能看,私密的只有自己(别人 404)。响应同 `GET /video/v1/me/favorites/{id}`(见 5.3)。

---

## 3. 播放

### GET /video/v1/vod/{vid}/{part_id}/{q}.mp4 — 视频文件(公开 / 签名)

- 用详情接口给的 `url`,别自己拼;支持 `Range: bytes=a-b` → `206` + `Content-Range`;不带 Range → `200` 整份;
- 越界 Range → `416`;没权限 / 不存在 / 转码没完 → `404「没有这个视频」`;
- 生产上由 nginx 直出(`X-Accel-Redirect`),客户端无感。

### GET /video/v1/vod/{vid}/{part_id}/sprite/{n}.jpg — 进度条缩略图

第 `n` 张雪碧图(见 1.4 的坐标算法)。

### POST /video/v1/videos/{vid}/view — 播放心跳(公开)

客户端**每 15 秒**上报一次(暂停时不报),退出播放页时再报一次。

请求:

```json
{"part_id": 221, "position_ms": 5200, "played_ms": 5200, "device_id": "设备号(没登录时必传)"}
```

| 字段 | 说明 |
|---|---|
| position_ms | 当前播放位置(续播用,记进历史) |
| played_ms | **这次打开以来实际播放了多久**(不是位置;拖进度条不算);满 5 秒或满这一 P 时长的 30% 才算一次播放 |
| device_id | 没登录时按设备去重(服务端哈希后存);登录了按人 |

响应:

```json
{"counted": true, "views": 1}
```

同一个人(没登录按设备)同一个视频**每天只算一次**,之后都是 `counted: false`。
登录了且没暂停历史记录时,顺带把 `part_idx / position_ms` 记进历史(续播、「看过 >50% 不再推」都用它)。

---

## 4. 互动(登录)

没公开的稿件(审核中等)不能互动,回 `409「视频还没公开,不能互动」`。

### POST /video/v1/videos/{vid}/like — 点赞 / 取消

请求 `{"like": true}`(不传 body = 点赞),响应 `{"liked": true, "likes": 1}`。重复点赞幂等。

### POST /video/v1/videos/{vid}/coin — 投币

请求 `{"amount": 1, "like": false}`(`amount` 1 或 2;`like` 为 true 时顺手点赞)。

```json
{"coins_given": 1, "coin_max": 2, "coin_balance": 3, "coins": 1}
```

`coins_given`:我给这个视频累计投了几枚;`coin_balance`:我的余额;`coins`:视频收到的总数。
错误:`422「自制视频最多投 2 枚」/「转载视频最多投 1 枚」/「不能给自己的视频投币」/「硬币不够了(每天打开视频可以领 1 枚)」`、
`409「这个视频你已经投满 2 枚了」`。余额不够时整笔不生效。

### POST /video/v1/videos/{vid}/favorite — 收藏

请求 `{"folder_ids": [45, 46]}` = 这个视频要在的**全部**收藏夹;`[]` = 取消收藏;不传 body = 收进默认收藏夹。

```json
{"favorited": true, "folder_ids": [45], "favorites": 1}
```

收藏数按人算:放进三个收藏夹也只算一个人收藏。

### POST /video/v1/videos/{vid}/share — 分享

请求 `{"channel": "link|chat|qr|other"}`,响应 `{"shares": 1, "link": "https://chaojizan.cc/v/svHbFUgZ3A32"}`。
同一个人分享多次只算一次。「发到消息」由客户端调聊天接口发链接。

### POST /video/v1/videos/{vid}/triple — 三连

赞 + 投满(自制 2 / 转载 1,余额不够就投能投的)+ 收进默认收藏夹;做过的那一项跳过;自己的视频不投币。

```json
{
  "liked": true, "coins_given": 1, "coin_note": "", "favorited": true,
  "likes": 1, "coins": 2, "favorites": 1,
  "me": {"liked": true, "coins": 1, "coin_max": 2, "favorited": true, "folder_ids": [45],
         "watch_later": false, "coin_balance": 2, "progress": null}
}
```

`coins_given`:这次投了几枚;`coin_note`:「硬币不够,只投了一部分」/「硬币不够了」/「自己的视频不能投币」或空串。

### POST /video/v1/videos/{vid}/not-interested — 不感兴趣

响应 `{"ok": true}`。之后个性化推荐和竖屏流里不再出现它(关掉个性化时不生效 —— 那时推荐必须和没登录的人一样)。

### POST /video/v1/users/{id}/follow — 关注 / 取关

请求 `{"follow": true}`,响应 `{"followed": true, "fans": 1}`。不能关注自己(422);有拉黑关系(任意一方)不能关注(403)。

### GET /video/v1/me/following?cursor= — 我关注的人

响应同粉丝列表(2 节)。

---

## 5. 我的(登录)

### 5.1 历史

- `GET /video/v1/me/history?cursor=`:新看的在前,按天分组客户端做

```json
{
  "items": [{"video": {…VideoCard}, "part_idx": 0, "position_ms": 5200, "duration_ms": 6000,
             "watched_at": "2026-09-13T02:09:39.974617+00:00"}],
  "paused": false,
  "next_cursor": null
}
```

- `DELETE /video/v1/me/history/{vid}`:删一条,`{"ok": true}`;`DELETE /video/v1/me/history`:清空,`{"ok": true}`;
- 暂停记录用设置接口(5.5)。

### 5.2 稍后再看

- `GET /video/v1/me/watch-later`:`{"items": [{"video": {…VideoCard}, "added_at": "…"}], "count": 1, "max": 100}`;
- `POST /video/v1/me/watch-later` `{"vid": "svHbFUgZ3A32"}`:返回同 GET;满 100 个回 422;
- `DELETE /video/v1/me/watch-later/{vid}`:`{"ok": true}`。

### 5.3 收藏夹

收藏夹对象 `Folder`:

```json
{"id": 45, "title": "默认收藏夹", "is_default": true, "public": false, "count": 1,
 "cover": "/img/video_cover/…jpg", "updated_at": "2026-09-13T02:09:39.935846+00:00"}
```

| 接口 | 说明 |
|---|---|
| `GET /video/v1/me/favorites` | `{"items": [Folder…], "max": 50}`;第一次调会建好默认收藏夹(缺省私密) |
| `POST /video/v1/me/favorites` `{"title": "学习", "public": true}` | 建收藏夹(名字 1–20 字,过屏蔽词),返回 Folder |
| `GET /video/v1/me/favorites/{id}?cursor=` | `{"folder": Folder, "items": [{"video": {…VideoCard}, "added_at": "…"}], "next_cursor": null}`,新收的在前 |
| `PATCH /video/v1/me/favorites/{id}` `{"title"?, "public"?}` | 改名 / 公开私密,返回 Folder |
| `DELETE /video/v1/me/favorites/{id}` | 删自建收藏夹(默认的 422),`{"ok": true}` |
| `POST /video/v1/me/favorites/{id}/move` `{"vids": ["sv…"], "to": 46}` | 挪到另一个收藏夹;不传 `to` = 从这个收藏夹移除。`{"moved": 1}` |

公开收藏夹出现在 UP 主空间里;`cover` 是最近收进来的那个视频的封面。

### 5.4 硬币

- `GET /video/v1/me/coins?cursor=`:

```json
{
  "coins": 2,
  "today_claimed": true,
  "items": [
    {"id": 413, "delta": -1, "reason": "coin_give", "reason_label": "投币", "balance": 2,
     "video": {"vid": "svHbFUgZ3A32", "title": "示例视频:六秒测试片", "cover": "/img/…"},
     "created_at": "2026-09-13T02:09:39.958960+00:00"}
  ],
  "next_cursor": null
}
```

`reason`:`daily` 每日首次打开视频(+1)、`video_approved` 投稿过审(+2)、`coin_give` 投币(−n)、`coin_receive` 收到投币(+n)。
**没有别的来源**,也没有充值、提现、兑换(S4)。`balance` 是这一笔之后的余额。

- `POST /video/v1/me/coins/daily`:每天第一次打开视频 tab 时调,北京日期一天一次:`{"granted": true, "coins": 4}`
  (已经领过 `granted: false`,`coins` 是当前余额)。

### 5.5 设置

- `GET /video/v1/me/settings` → `{"personalize": true, "history_paused": false}`;
- `PATCH /video/v1/me/settings` `{"personalize"?: bool, "history_paused"?: bool}` → 同上。

`personalize` 就是 S9 的「个性化推荐」开关(和 `GET /social/v1/me` 里的 `personalize_video` 是同一个值):
关掉后推荐和没登录的人看到的完全一样,看过的、不感兴趣的也不再过滤。

---

## 6. 弹幕

弹幕对象 `Danmaku`:

```json
{"id": 154, "time_ms": 1200, "mode": 1, "color": 16777215, "size": 25, "text": "前排",
 "user_hash": "aad60552", "mine": true, "created_at": "2026-09-13T02:09:39.982770+00:00"}
```

| 字段 | 说明 |
|---|---|
| mode | `1` 滚动 / `4` 底部 / `5` 顶部 |
| color | 24 位 RGB 整数,缺省白 `16777215` |
| size | `18` 小 / `25` 标准 |
| user_hash | 发送人的 8 位哈希,「屏蔽此人」用;反推不出 id |
| mine | 是我发的(立即上屏、带边框) |

渲染规则见 DEV-PROMPTS-40 §5.10(轨道、8 秒飞过、顶部 / 底部停 4 秒、放不下丢弃)。

### GET /video/v1/parts/{part_id}/danmaku?segment=0 — 拉一段(公开)

6 分钟一段(`segment` 从 0 起:第 0 段是 `[0, 360000)` 毫秒);客户端预取当前段和下一段。

```json
{"part_id": 221, "segment": 0, "segment_ms": 360000, "segments": 1, "allow_danmaku": true,
 "items": [ {…Danmaku} ]}
```

按时间排,一段最多 3,000 条;和我有拉黑关系的人(任意一方)的弹幕不下发(S7)。

### GET /video/v1/parts/{part_id}/danmaku/density — 高能进度条(公开)

```json
{"part_id": 221, "bucket_ms": 5000, "counts": [1, 0]}
```

整个分 P 按 5 秒一桶的弹幕数(同样按拉黑过滤)。

### POST /video/v1/parts/{part_id}/danmaku — 发弹幕(登录)

请求 `{"time_ms": 1200, "text": "前排", "mode": 1, "color": 16777215, "size": 25}`,响应一个 `Danmaku`。

错误:`422`(空、超过 100 字、有换行 / 制表符 / U+2028 这类分行字符、模式 / 字号 / 颜色不对、时间超出这一 P 长度、屏蔽词)、
`403「UP 主关闭了这个视频的弹幕」/「你们之间有拉黑关系…」`、`429「弹幕发得太快了,3 秒一条」/「今天的弹幕发满 1000 条了…」`、
`409`(视频还没公开)。

### DELETE /video/v1/danmaku/{id} — 删弹幕(登录)

发的人删自己的;UP 主删自己视频下任何人的;别人 403。`{"ok": true}`。

---

## 7. 评论

评论对象 `Comment`:

```json
{
  "id": 232, "vid": "svHbFUgZ3A32", "root_id": null, "parent_id": null,
  "user": {"id": 237, "name": "用户7766", "username": "Kanke42488", "avatar": ""},
  "reply_to": null,
  "text": "拍得不错 @Upzhu70527",
  "mentions": [{"user_id": 236, "username": "upzhu70527"}],
  "likes": 1, "my_vote": 0, "reply_count": 2, "pinned": true, "is_up": false,
  "created_at": "2026-09-13T02:09:40.009463+00:00",
  "replies": [ {…Comment(回复,没有 replies 字段)} ]
}
```

| 字段 | 说明 |
|---|---|
| root_id / parent_id | 一级评论两个都是 null;回复的 `root_id` 是楼主那条、`parent_id` 是被回复的那条 |
| reply_to | 回复的是「回复」时是 `{"id", "name"}`(显示「回复 @某人」);直接回复一级评论时是 null |
| mentions | 文中 @ 到的人(用户名小写);没注册的用户名不在这里,原样当文字显示 |
| my_vote | 我的赞踩:1 / -1 / 0。**点踩数不对外**,响应里没有这个字段 |
| is_up | 作者是这个视频的 UP 主(标「UP 主」) |
| replies | 只在一级评论上:最早的 3 条回复;看全部用回复列表 |

### GET /video/v1/videos/{vid}/comments?sort=hot|new&cursor= — 评论列表(公开)

```json
{"items": [ {…Comment} ], "next_cursor": null, "sort": "hot", "count": 3, "allow_comments": true}
```

- `hot`:置顶的在最前,然后按(赞 + 回复数)从高到低;`new`:置顶的在最前,然后按时间倒序;
- 一页 20 条(含置顶);置顶那条只在第一页;`count` 是这个视频的评论总数(含回复);
- 和我有拉黑关系的人的评论和回复不下发(S7)。

### GET /video/v1/comments/{id}/replies?cursor= — 回复列表(公开)

```json
{"root": {…Comment}, "items": [ {…Comment} ], "next_cursor": null}
```

按时间正序。

### POST /video/v1/videos/{vid}/comments — 发评论 / 回复(登录)

请求 `{"text": "拍得不错 @Upzhu70527", "parent_id": null}`(`parent_id` 回复哪条,一级评论或回复都行),响应一个 `Comment`。

- 通知:评论视频 → UP 主「回复我的」;回复 → 被回复的人「回复我的」;@ → 被 @ 的人「@我的」;
- 错误:`422`(空、超过 1,000 字、屏蔽词)、`403「UP 主关闭了这个视频的评论」/「你们之间有拉黑关系,不能评论这个视频」/「…不能回复」`、
  `404`(回复的评论已删除)、`429「评论太快了,5 秒一条」/「今天的评论发满 500 条了…」`。

### POST /video/v1/comments/{id}/vote — 赞 / 踩(登录)

请求 `{"vote": 1}`(1 赞 / -1 踩 / 0 取消),响应 `{"id": 232, "likes": 1, "my_vote": 1}`。被赞的人收到「收到的赞」(按评论合并)。

### POST /video/v1/comments/{id}/pin — 置顶(登录,UP 主)

请求 `{"pinned": true}`,响应 `{"id": 232, "pinned": true}`。每个视频只能置顶一条一级评论,置顶新的自动取消旧的;
不是 UP 主 403,置顶回复 422。

### DELETE /video/v1/comments/{id} — 删评论(登录)

作者删自己的;UP 主删自己视频下的;别人 403。删一级评论,楼里的回复一起不再显示。`{"ok": true}`。

### POST /video/v1/reports — 举报视频 / 评论 / 弹幕(登录)

```json
{"target_type": "comment", "target_id": 232, "reason_code": "C102", "note": "引流"}
{"target_type": "video", "vid": "svHbFUgZ3A32", "reason_code": "V201", "note": "搬运的"}
{"target_type": "danmaku", "target_id": 154, "reason_code": "C101"}
```

响应 `{"id": 21, "status": "open"}`(7 天内第 3 个不同的人举报同一个对象时是 `"escalated"`,优先处理)。
原因代码见 0.8,选 X999 要写说明;同一个人对同一个对象 7 天内只记一次;举报人对被举报的一方永远匿名。

---

## 8. 投稿与创作中心(登录,投稿要实名)

### 8.1 流程

```
1. 传原片:POST /media/v1/upload(≤ 20MB,multipart:file、kind=video_source、purpose=video)
   或者分片:POST /media/v1/uploads {"size", "name", "kind": "video_source", "purpose": "video"}
            → PUT /media/v1/uploads/{id}/chunks/{n}(每片 4MB,原始字节,可乱序、可续传)
            → POST /media/v1/uploads/{id}/complete {"kind": "video_source"}
   得到媒体对象的 id(media_id)
2. 建稿件:POST /video/v1/uploads/videos {title, zone, tags, …}          → 草稿(vid)
3. 挂分 P:POST /video/v1/videos/{vid}/parts {"media_id": …, "title": "第一 P"} → 马上开始转码
   (要自己的封面:同样用媒体接口传 kind=cover、purpose=video 的图片,再 PATCH cover_media_id)
4. 提交:POST /video/v1/videos/{vid}/submit
   → processing(转码中)→ 全部分 P 就绪自动进 reviewing(审核中)→ 审核通过 published(或定时发布 scheduled)
5. 状态变化实时推用户事件 `video`(见第 10 节),创作中心据此刷新
```

原片转完就删了(各档位就是存档),原片的媒体 id 不能再挂第二次(409)。

### 8.2 稿件状态

| status | status_label | 说明 |
|---|---|---|
| draft | 草稿 | 可以改、加 / 删分 P、提交 |
| processing | 转码中 | 不能改内容 |
| reviewing | 审核中 | 不能改内容;UP 主和审核员能看,别人 404(D10) |
| scheduled | 已通过,等待定时发布 | 到 `scheduled_at` 由清扫任务公开 |
| published | 已发布 | 再改内容进待审,线上不变(见 8.4) |
| rejected | 未通过 | `reject_code` / `reject_label` / `reject_note` 是原因;改了重交,或申诉 |
| failed | 转码失败 | `fail_reason` 说哪一 P 为什么失败;删掉那一 P 重传后重交 |
| removed | 已下架 | 处罚;`reject_*` 是下架原因;只能申诉 |

### 8.3 创作中心对象 `CreatorVideo`

`POST /uploads/videos`、`PATCH /videos/{vid}`、`POST /videos/{vid}/parts`(多一个 `added_part_id`)、
`DELETE /videos/{vid}/parts/{id}`、`POST /videos/{vid}/submit`、`DELETE /videos/{vid}/changes`、
`GET /creator/videos/{vid}` 都返回它:

```json
{
  …VideoCard(没有 uploader),
  "status": "published", "status_label": "已发布", "visibility": "public",
  "reject_code": "", "reject_label": "", "reject_note": "", "fail_reason": "",
  "scheduled_at": null, "submitted_at": "2026-09-13T02:09:38.417831+00:00",
  "created_at": "2026-09-13T02:09:38.045802+00:00",
  "pending": null,
  "description": "接口文档用的示例稿件", "copyright": "original", "source_url": "",
  "allow_danmaku": true, "allow_comments": true,
  "shop": null, "shop_id": null, "shop_collab": null,
  "cover_media_id": 207,
  "cover_preview": "/img/video_cover/u236-0ec4f37a09eb4416b215313be6d98008.jpg",
  "link": "https://chaojizan.cc/v/svHbFUgZ3A32",
  "parts": [
    {…Part, "live": true, "error": "",
     "cover_candidates": [{"media_id": 208, "url": "/media/v1/files/208?u=236&e=…&s=…"}, …]}
  ],
  "version_part_ids": [221],
  "decisions": [
    {"id": 82, "action": "approve", "action_label": "审核通过", "reason_code": "", "reason_label": "",
     "note": "", "appeal_of": null, "created_at": "…", "can_appeal": false, "appeal_state": null}
  ]
}
```

| 字段 | 说明 |
|---|---|
| cover_preview | 封面预览:过审后是公开地址,没过审时是带签名的私密地址(只有你和审核员能看) |
| parts | **全部**分 P(含转码中、改动里新加的);`status` processing / ready / failed;`live` 是否在线上版本里;转码中的 `renditions` 是空的 |
| parts[].cover_candidates | 这一 P 自动截的三帧(10% / 50% / 90% 处),把 `media_id` 填进 `cover_media_id` 就是选它当封面;没选封面时用第一 P 的第一帧 |
| version_part_ids | 「下一版」的分 P 顺序(还没发布过 = 全部;已发布 = 待审清单) |
| decisions | 审核 / 下架 / 申诉记录;`can_appeal` 为真的可以申诉;`action` 取值:approve / reject / approve_changes / reject_changes / remove / appeal / appeal_upheld / appeal_overturned |

`pending`(已发布稿件有没审的改动时):

```json
"pending": {
  "state": "editing", "state_label": "改动未提交",
  "fields": {"title": "示例视频(改过的标题)"},
  "parts": null,
  "submitted_at": null,
  "reject_code": "", "reject_label": "", "reject_note": "", "fail_reason": ""
}
```

`state`:`editing` 改动未提交 / `processing` 改动转码中 / `reviewing` 改动审核中 / `rejected` 改动未通过 / `failed` 改动转码失败;
`fields` 只列改了的内容字段;`parts` 是下一版的分 P 清单 `[{"id", "title"}]`(没动分 P 时为 null)。

### 8.4 接口

#### POST /video/v1/uploads/videos — 建稿件

请求(都可选,提交时再校验必填):

```json
{"title": "示例视频", "description": "…", "zone": "tech", "tags": ["示例", "测试"],
 "copyright": "original", "source_url": "", "visibility": "public",
 "allow_danmaku": true, "allow_comments": true,
 "shop_id": null, "shop_collab": null, "scheduled_at": null, "cover_media_id": null}
```

| 字段 | 规则 |
|---|---|
| title | ≤ 80 字(提交时必填) |
| zone | 分区 key(提交时必填) |
| copyright | `original` / `repost`;转载必填 `source_url`(http/https) |
| visibility | `public` 公开 / `unlisted` 不公开(拿链接能看,不进推荐搜索空间)/ `private` 私密(只有自己) |
| shop_id / shop_collab | 挂一家本平台正常营业的店(D16);挂了就必须声明 `shop_collab`(有无合作) |
| scheduled_at | 定时发布(ISO 时间,5 分钟之后、30 天之内);过审后到点才公开 |
| cover_media_id | 自己上传的封面(媒体 kind=cover、purpose=video)或自动三帧之一 |

标题、简介、标签过屏蔽词。返回 `CreatorVideo`(`status: "draft"`)。

#### PATCH /video/v1/videos/{vid} — 改稿

请求同上(只传要改的),另可传 `"parts": [{"id": 221, "title": "第一 P"}, …]` 给出下一版全部分 P 的顺序和标题。

- 还没发布过的(草稿 / 未通过 / 转码失败)直接改;未通过 / 失败的改了回到草稿;
- **已发布的**:内容字段(标题、简介、分区、标签、自制 / 转载、来源、店铺、封面、分 P)进 `pending`,**线上一个字不动**,
  提交审核通过后才换;可见性、弹幕 / 评论开关立即生效;改回和线上一样的值 = 这一项不算改动;
- 转码 / 审核中改内容 409;已下架 409。

#### POST /video/v1/videos/{vid}/parts — 加一 P

请求 `{"media_id": 206, "title": "第一 P"}`,返回 `CreatorVideo` + `"added_part_id": 221`。原片必须是自己用 `purpose=video, kind=video_source` 传的。
已发布的稿件加 P = 改动(进 `pending.parts`),过审才上线。

#### DELETE /video/v1/videos/{vid}/parts/{part_id} — 删一 P

已发布的稿件删 P = 改动(线上还在,过审才删);至少留 1 P(422)。返回 `CreatorVideo`。

#### POST /video/v1/videos/{vid}/submit — 提交审核

草稿 / 未通过 / 失败的提交整稿;已发布的提交改动(没改动 409)。校验:标题、分区、转载来源、店铺合作声明、至少 1 P、没有转码失败的 P。
返回 `CreatorVideo`(`status` 变 processing,或者全部就绪直接 reviewing)。

#### DELETE /video/v1/videos/{vid}/changes — 放弃改动

已发布稿件还没过审的改动全部放弃(为改动新传的 P 一起删);审核中的不能撤回(409)。返回 `CreatorVideo`。

#### POST /video/v1/videos/{vid}/appeal — 申诉

对最近一次「驳回 / 改动被驳回 / 下架」申诉:请求 `{"text": "申诉理由(≥ 5 字)"}`,响应 `{"id": 84, "appeal_of": 83, "state": "open"}`。
每个结论只能申诉一次(409);稿件在驳回之后又改过了就不用申诉,直接重交(409)。
申诉**由另一名审核员处理**(S6),结果进系统通知。

#### DELETE /video/v1/videos/{vid} — 删除稿件

立即从所有地方消失、播放地址失效;媒体 30 天后清掉。`{"ok": true}`。

#### GET /video/v1/creator/videos?status=all&cursor= — 稿件管理列表

`status`:`all` / `processing`(草稿、转码中、失败)/ `reviewing` / `published`(含 scheduled)/ `rejected` / `removed`。

```json
{"items": [ {…VideoCard(没有 uploader), "status", "status_label", "visibility", "reject_code", "reject_label",
             "reject_note", "fail_reason", "scheduled_at", "submitted_at", "created_at", "pending"} ],
 "next_cursor": null}
```

#### GET /video/v1/creator/videos/{vid} — 单个稿件(完整)

返回 `CreatorVideo`。

#### GET /video/v1/creator/videos/{vid}/stats?days=30 — 单稿数据

```json
{
  "vid": "svHbFUgZ3A32",
  "totals": {"views": 1, "likes": 1, "coins": 2, "favorites": 1, "comments": 3, "danmaku": 1, "shares": 1},
  "days": [{"day": "2026-09-07", "views": 0, "likes": 0, "coins": 0, "favorites": 0, "comments": 0, "danmaku": 0, "shares": 0}, …]
}
```

`days` 按北京日期、从 N 天前到今天,没数据的天补 0(`days` 1–90)。每天的数是当天的增量(新增的赞、收到的硬币枚数……)。

#### GET /video/v1/creator/overview — 总览

```json
{
  "videos": {"draft": 0, "processing": 0, "reviewing": 0, "scheduled": 0, "published": 1, "rejected": 0, "failed": 0, "removed": 0},
  "totals": {"views": 1, "likes": 1, "coins": 2, "favorites": 1, "comments": 3, "danmaku": 1, "shares": 1},
  "today": {…同 totals 的七项}, "last_7_days": {…}, "last_30_days": {…},
  "fans": 1, "following": 0, "coins": 4
}
```

---

## 9. 互动消息 `/social/v1/notifications`(登录)

「消息」列表第三行「互动消息」:四个页签 `reply` 回复我的 / `at` @我的 / `like` 收到的赞 / `system` 系统通知。

### GET /social/v1/notifications?kind=reply&cursor=

```json
{
  "items": [
    {
      "id": 407, "kind": "reply",
      "title": "用户0036 回复了你的评论",
      "text": "+1",
      "actor": {"id": 238, "name": "用户0036", "username": null, "avatar": ""},
      "actors": [{"id": 238, "name": "用户0036", "username": null, "avatar": ""}],
      "count": 1,
      "video": {"vid": "svHbFUgZ3A32", "title": "示例视频:六秒测试片", "cover": "/img/…"},
      "comment": {"id": 234, "root_id": 232, "deleted": false},
      "data": {"target": "comment", "root_id": 232, "replied_text": "谢谢!"},
      "read": false,
      "created_at": "2026-09-13T02:09:40.060815+00:00",
      "updated_at": "2026-09-13T02:09:40.060815+00:00"
    }
  ],
  "next_cursor": null,
  "unread": {"reply": 2, "at": 0, "like": 1, "system": 1, "total": 4}
}
```

| 字段 | 说明 |
|---|---|
| title | 服务端拼好的一句话,直接显示:「X 评论了你的视频」「X 回复了你的评论」「X 在评论里 @ 了你」「X 赞了你的视频」「X等 12 人赞了你的评论」、系统通知的标题 |
| text | 评论内容片段(评论被删了是「该评论已删除」);系统通知是正文 |
| actor / actors | 最近那个人 / 最近几个人(赞合并时最多 3 个头像);系统通知是 null / [] |
| count | 赞的合并数(这个对象当前的赞数);其它类是 1 |
| video | 相关视频(已删除为 null) |
| comment | 跳转用:`id` 这条评论、`root_id` 所在的楼(打开视频评论区定位到它) |
| data | 按类型:reply / at 有 `target`(`video` 评论了视频 / `comment` 回复了评论)、`root_id`、`replied_text`;
         like 有 `target`、`text`;system 有 `title`、`action`(approve / reject / approve_changes / reject_changes / remove /
         appeal_overturned / appeal_upheld / published / failed)、`reason_code`、`reason_label`,过审的还有 `coins` |

赞按对象合并:同一个视频(或同一条评论)收到的赞只有一行,新的赞来了这一行 `count` / `actors` 更新、重新变未读并排到最前。
拉黑的人(任意一方)产生的互动不进消息。

### GET /social/v1/notifications/unread

```json
{"reply": 2, "at": 0, "like": 1, "system": 1, "total": 4}
```

### POST /social/v1/notifications/read

请求 `{"kind": "reply"}`(只标这一类)/ `{"ids": [407]}`(只标这几条)/ `{}`(全部),响应 `{"unread": {…同上}}`。
同时给我的所有设备推 `notify` 事件,角标一起变。

---

## 10. 实时事件(`/ws/v2` 的用户事件)

连接和鉴权见 DEV-PROMPTS-40 §5.3。视频模块发两种用户事件(`t: "uev"`,断线补齐走 `POST /chat/v1/sync` 的 `user_events`):

### `notify` — 互动消息角标

```json
{"t": "uev", "user_id": 236, "pts": 4, "type": "notify",
 "data": {"kind": "system", "unread": {"reply": 0, "at": 0, "like": 0, "system": 1, "total": 1}}}
```

每产生一条互动消息、或者已读状态变了都会推;`kind` 是哪一类变了(标已读 `{}` 全部时为 null),`unread` 是最新的未读数,直接覆盖角标。

### `video` — 我的稿件状态变了

```json
{"t": "uev", "user_id": 236, "pts": 2, "type": "video",
 "data": {"vid": "svHbFUgZ3A32", "status": "processing", "status_label": "转码中", "pending": null,
          "fail_reason": "", "reject_code": ""}}
```

提交、转码完成 / 失败、审核结果、下架、申诉结果、定时发布到点、UP 主自己在另一台设备上改稿都会推。
客户端收到后重新拉 `GET /video/v1/creator/videos/{vid}`。`pending` 是改动的状态(见 8.3)。

---

## 11. 管理 `/admin/social/…`(管理员)

每个写操作同时记 `video_decisions`(给 UP 主看)和管理员操作留痕。
对**人和会话**的处罚(禁言、封号、封群、聊天举报、社区申诉、数据页)在同一个前缀下,见 [COMMUNITY-GOVERNANCE.md](COMMUNITY-GOVERNANCE.md) §4.3;
评论 / 弹幕举报删掉内容之后要禁言发的人,用 `POST /admin/social/sanctions`(带 `video_report_id`)。
审核结论现在记下对应的那次提交时间(`video_decisions.submitted_at`),审核中位时长从它算。

| 接口 | 说明 |
|---|---|
| `GET /admin/social/reason-codes` | `{"items": [{"code": "C101", "label": "骚扰、辱骂"}, …]}` |
| `GET /admin/social/videos/review?limit=50` | 审核队列(新稿件 + 已发布稿件的改动),按提交时间先后:`{"items": [{…CreatorVideo 的列表字段, "review": "first|changes", "uploader": Person}], "count": 5}` |
| `GET /admin/social/videos/{vid}` | 完整稿件(`CreatorVideo`,播放地址按审核员签名)+ `review`、`uploader`、`reports_open` |
| `POST /admin/social/videos/{vid}/decide` | `{"approve": true}` 或 `{"approve": false, "reason_code": "V202", "note": "给 UP 主看的说明", "note_internal": "只在后台看"}`;驳回必须带原因代码,X999 要写说明。响应 `{"decision_id": 82, "action": "approve", "status": "published", "pending": null}`。改动审核时 `action` 是 approve_changes / reject_changes |
| `POST /admin/social/videos/{vid}/remove` | 下架:`{"reason_code": "V202", "note": "…", "note_internal": ""}` → `{"decision_id": 83, "status": "removed"}` |
| `GET /admin/social/appeals` | 没处理的申诉:`{"items": [{"appeal": {"id", "text", "created_at"}, "original": {"id", "action", "action_label", "reason_code", "reason_label", "note", "note_internal", "actor_id", "created_at"}, "video": {"vid", "title", "cover", "status"}, "you_decided_original": true}]}` |
| `POST /admin/social/appeals/{id}/resolve` | `{"overturn": true, "note": "复核结论(给 UP 主看)", "note_internal": ""}` → `{"appeal_id": 84, "decision_id": 85, "overturned": true, "status": "published"}`。**原结论是你作出的 → 403「原结论是你作出的,申诉必须由另一名审核员处理」**(S6) |
| `GET /admin/social/video-reports?status=open\|handled\|all` | 举报列表,escalated(7 天 3 人)排最前;每条带被举报对象的快照(`video` / `comment` / `danmaku`),不带举报人 |
| `POST /admin/social/video-reports/{id}/handle` | `{"action": "dismiss"}` 不成立 / `{"action": "delete", "reason_code", "note"}` 删评论或弹幕 / `{"action": "remove", "reason_code", "note"}` 下架视频;同一对象的举报一起结案 → `{"id": 21, "status": "dismissed", "resolution": "举报不成立"}` |
| `GET /admin/social/videos-stats` | `{"reviewing": 4, "approved_7d": 50, "rejected_7d": 7, "removed_7d": 12, "reject_rate_7d": 0.1228, "appeals_open": 0, "reports_open": 0}` |

平台开关:`POST /admin/flags/video_enabled {"value": "on|off", "reason": "…"}`、`POST /admin/flags/video_upload_enabled`(同上)。

---

## 12. 注销账号(S5)

`DELETE /auth/me` 注销时视频部分:投稿全部删除并**立即**清掉媒体(播放地址、雪碧图、公开封面当场 404),
弹幕删除,评论正文清空(楼里别人的回复保留),赞、踩、投币记录、收藏夹、稍后再看、历史、关注关系、不感兴趣、搜索记录、
硬币流水、互动消息一并删除;受影响视频的计数按明细重算。
