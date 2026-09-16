# 音乐接口参考(客户端用)

对应 [DEV-PROMPTS-41](DEV-PROMPTS-41.md) 的「音乐」部分(#378,§5.1–§5.5、§5.10、§5.11、§8.2)。
服务端实现在 `server/app/routers/music.py`、`routers/music_admin.py` 和 `services/music*.py`。
字段名和类型以本文为准;改接口时本文要一起改。

---

## 0. 通用约定

### 0.1 鉴权

- `Authorization: Bearer <JWT>`,和其它接口同一个 token;
- 标 **公开** 的接口没登录也能调 —— **包括听歌**(M5:不登录也能听,只能听已发布的作品);
- 标 **登录** 的接口要登录,而且只对用户端账号开放(D1),商家 / 骑手账号调回
  `403「消息和视频只在用户端开放」`;
- 标 **管理员** 的是 `/admin/music/…`,要管理员账号;
- **开通音乐人、上传、发歌都不要求实名**(M2、§3.2),只要手机号账号。冒充走举报(`M305`)。

### 0.2 开关(§3.8)

| 开关 | 关着时 |
|---|---|
| `music_enabled` | `/music/v1/*` 全部回 `503 {"detail": "音乐暂未开放"}`(生产缺省关) |
| `music_upload_enabled` | 开通音乐人、建作品、加歌、提交审核,以及用 `purpose=music` 上传音频 / 封面,回 `503 {"detail": "音乐投稿暂未开放"}` |

`GET /config` 的 `features.music` / `features.music_upload` 就是这两个开关,客户端据此收起入口。
互动消息 `/social/v1/notifications` 不受开关影响(已经收到的审核结果关了也得能看)。

### 0.3 错误

错误体统一是 `{"detail": "给用户看的中文"}`,直接展示 `detail`。
**一个例外**:被禁言 / 封号时是 403,`detail` 是对象
`{"error": "sanctioned", "message": …, "reason_code", "reason_label", "until", "can_appeal", …}`,
展示 `detail.message`;字段见 [COMMUNITY-GOVERNANCE.md](COMMUNITY-GOVERNANCE.md) §3。

| 状态码 | 什么时候 |
|---|---|
| 401 | 没登录 / token 过期(要登录的接口) |
| 403 | 没权限:别人的作品、音乐人被停用、有拉黑关系、原审核员处理自己结论的申诉、被禁言 / 封号 |
| 404 | 不存在、已删除、**或者你没权限看**(没过审、下架的作品对别人一律 404,不告诉你「有但你看不了」) |
| 409 | 状态不对:审核中不能改、已发布的作品要先下架才能改、每个结论只能申诉一次、艺名已被占用 |
| 422 | 输入不合规:字段超长、曲风 / 语种不认识、没勾声明、原因代码不对、违禁词、版权投诉没留联系方式 |
| 429 | 限流(见 0.6) |
| 503 | 开关关着(见 0.2) |

### 0.4 标识与时间(§5.1)

对外只用公开编号,**不暴露自增 id**(歌曲评论除外,评论用整数 `id`):

| 对象 | 前缀 | 正则 | 链接 |
|---|---|---|---|
| 歌曲 | `mt` | `^mt[1-9A-HJ-NP-Za-km-z]{10}$` | `https://chaojizan.cc/music/t/<tid>` |
| 作品 | `mr` | `^mr[…]{10}$` | `/music/r/<rid>` |
| 歌单 | `mp` | `^mp[…]{10}$` | `/music/p/<pid>` |
| 音乐人 | `ma` | `^ma[…]{10}$` | `/music/a/<aid>` |

时间一律 ISO 8601 带时区(UTC);时长、播放位置一律**毫秒**(`*_ms`);「日」按北京时间切。

### 0.5 分页

| 方式 | 用在 | 怎么翻 |
|---|---|---|
| `page`(从 0 起) | 曲风页、推荐歌单、音乐人全部歌曲、搜索 | 响应里 `has_more` 为真就 `page+1` |
| `cursor` | 我喜欢的音乐、评论、回复 | 把上一页的 `next_cursor` 原样传回;为 `null` 表示没有了。**游标是不透明字符串,不要自己拼** |

榜单、每日推荐、发现页一次给全(榜最多 100 首、每日推荐 20 首),不分页。

### 0.6 限流(§5.10)

| 动作 | 上限 | 超了 |
|---|---|---|
| 喜欢、收藏、加歌单 | 每人每秒 5 次 | `429「点得太快了,歇一下」` |
| 收听上报 | 每人每分钟 120 次 | `429` |
| 评论 | 每 5 秒 1 条、每天 500 条 | `429「评论太快了,5 秒一条」` |
| 建作品 / 加歌 | 每分钟 20 次、每天 50 首歌 | `429` |
| 搜索 | 每分钟 60 次 | `429` |
| 举报 | 每人每分钟 10 次 | `429` |

### 0.7 曲风与语种

`GET /music/v1/genres` 返回 `[{key, name}]`,**客户端不要自己写一份**。现在有:
`pop` 流行、`rock` 摇滚、`folk` 民谣、`electronic` 电子、`rap` 说唱、`rnb` R&B、`jazz` 爵士、
`classical` 古典、`country` 乡村、`metal` 金属、`punk` 朋克、`ancient` 古风、`acg` 动漫、
`soundtrack` 影视原声、`world` 世界音乐、`kids` 儿童、`instrumental` 纯音乐、`other` 其他。

语种(作品上填一个):`mandarin` 华语、`cantonese` 粤语、`english` 英语、`japanese` 日语、
`korean` 韩语、`none` 无人声、`other` 其他。

---

## 1. 公共对象(§8.1)

```jsonc
// 歌曲卡片 track
{"tid":"mt…","title":"…","duration_ms":215000,"cover":"/img/music_cover/….jpg","explicit":false,
 "genre":"pop","genre_name":"流行","plays":1234,"likes":56,"comments":7,"liked":false,
 "artist":{"aid":"ma…","name":"…","avatar":"…","user_id":42},
 "release":{"rid":"mr…","title":"…","kind":"single"},
 "published_at":"2026-09-15T12:00:00+00:00"}

// 作品卡片 release
{"rid":"mr…","title":"…","kind":"album","cover":"…","artist":{…简版音乐人…},
 "track_count":8,"release_date":"2026-09-15","collects":3,"published_at":"…"}

// 歌单卡片 playlist
{"pid":"mp…","title":"…","cover":"…","track_count":20,"collects":5,"is_public":true,
 "owner":{"id":7,"name":"…","username":"…","avatar":"…"},"tags":["华语"]}

// 音乐人 artist(列表里的简版只有 aid / name / avatar / user_id)
{"aid":"ma…","name":"…","bio":"…","avatar":"…","cover":"…","genres":["pop"],"user_id":42,
 "fans":10,"followed":false,"track_count":12}

// 排序中间量 rank(榜单、每日推荐、曲风页、推荐歌单的每一项都带)
{"score":57.0,"parts":{"listeners_7d":35,"likers_7d":4,"playlisters_7d":2},
 "why":"近 7 天 35 人收听、4 人喜欢、2 人加入歌单"}
```

`artist.user_id` 是这位音乐人的超级赞账号 —— **关注走 `/social/v1/users/{user_id}/follow`**
(#377 关注全站一张表),不是音乐人自己的关注接口。

---

## 2. 发现与榜单(公开)

| 方法 路径 | 说明 |
|---|---|
| GET `/music/v1/home` | 发现页:`{daily:[track≤6], daily_personalized, playlists:[playlist+rank≤6], new_tracks:[track+rank≤6], charts:[{key,name,top:[track+rank≤3]}], genres:[{key,name}]}` |
| GET `/music/v1/genres` | `[{key, name}]` |
| GET `/music/v1/genres/{key}/tracks?page=` | 这个曲风下的歌,按热歌榜分数:`{items:[track+rank], has_more}` |
| GET `/music/v1/charts` | 三个榜的摘要:`[{key, name, updated_at, top:[track+rank≤3]}]` |
| GET `/music/v1/charts/{key}` | 榜单全表,`key ∈ hot / new / rising`:`{key, name, updated_at, items:[{rank_no, track, rank}]}` |
| GET `/music/v1/daily` | 每日推荐:`{date, personalized, items:[track+rank]}` |
| GET `/music/v1/playlists/recommended?page=` | 推荐歌单:`{items:[playlist+rank], has_more}` |
| GET `/music/v1/rank/formula` | 公式原文和全部参数:`{formula, params, charts, source}` |
| GET `/music/v1/search?q=&type=&page=` | `type ∈ track / artist / release / playlist`:`{items, has_more}` |

公式(§5.4)原样公开,`/rank/formula` 的 `formula` 就是它:

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

个性化开关在 `GET / PUT /music/v1/me/settings`(`{personalize}`)。关掉之后每日推荐只按热歌榜分数,
和没登录的人看到的一样。

---

## 3. 歌曲、作品、音乐人(公开)

| 方法 路径 | 说明 |
|---|---|
| GET `/music/v1/tracks/{tid}` | track + `lyrics_kind`、`credits`、`declaration`、`track_no`、`stream` |
| GET `/music/v1/tracks/{tid}/lyrics` | `{kind: "none"\|"plain"\|"lrc", text}` |
| GET `/music/v1/tracks/{tid}/stream` | 重新签地址:`{std, hq, expires_at}` |
| GET `/music/v1/releases/{rid}` | release + `description`、`genre_name`、`language_name`、`collected`、`tracks:[track]` |
| GET `/music/v1/artists/{aid}` | artist + `hot_tracks:[track≤10]`、`releases:[release]` |
| GET `/music/v1/artists/{aid}/tracks?page=` | 全部歌曲(按收听):`{items, has_more}` |

没过审、被下架、作者被停用的作品,对**别人**一律 404;作者本人和管理员看得到。

---

## 4. 播放(§5.5)

```jsonc
// GET /music/v1/tracks/{tid} 里的 stream
{"std": "/music/v1/stream/mt…/std.m4a?u=42&e=1789000000&s=3f5a…",
 "hq":  "/music/v1/stream/mt…/hq.m4a?u=42&e=1789000000&s=3f5a…",
 "expires_at": "2026-09-15T18:00:00+00:00"}
```

- `q ∈ {std, hq}`。**源码率低于 192kbps 的歌不出 hq**,那一档是 `null`;
- 签名 `HMAC-SHA256(key = sha256("superz-music-url:" + jwt_secret), "{tid}:{u}:{e}")` 取前 32 位十六进制,
  `u` 是用户号(没登录是 `0`),有效 **6 小时**;
- **每次请求重新判权**:作品下架、删除、作者被停用,旧地址立刻 404;
- 支持 `Range`(206 + `Content-Range`),生产由 nginx 直出(`X-Accel-Redirect`);
- 地址过期就调 `GET /music/v1/tracks/{tid}/stream` 重新签,不用重新进详情页。

### 收听上报

`POST /music/v1/tracks/{tid}/play` — **公开**(不登录也能报,按 `device_id` 去重)

```jsonc
// 请求
{"ms_listened": 32000, "device_id": "…没登录时给…", "context": "daily"}
// 响应
{"counted": true, "plays": 1235}
{"counted": false, "plays": 1234, "threshold_ms": 30000}   // 没听够
{"counted": false, "plays": 1234, "deduped": true}          // 30 分钟内算过了
```

- 服务端把 `ms_listened` 截到歌的时长以内;
- 听满 `min(30 秒, 时长一半)` 才算一次收听,**同一个人同一首歌 30 分钟内只算一次**;
- 登录用户不管算不算,都会写「最近播放」(那是「我放过什么」,不是「算不算收听」);
- 客户端在一首歌切走或播完时报一次就行,不用每 15 秒一次。

---

## 5. 我的(登录)

| 方法 路径 | 说明 |
|---|---|
| POST / DELETE `/music/v1/tracks/{tid}/like` | 喜欢 / 取消:`{liked, likes}` |
| GET `/music/v1/me/likes?cursor=` | 我喜欢的音乐:`{items:[track], has_more, next_cursor}` |
| GET / DELETE `/music/v1/me/history` | 最近播放(≤300)/ 清空:`{items:[track], max}` / `{ok}` |
| GET `/music/v1/me/playlists` | `{created:[playlist], collected:[playlist], collected_releases:[release]}` |
| GET / PUT `/music/v1/me/settings` | `{personalize}` |

下架、删掉的歌会从「我喜欢的」「最近播放」「歌单」里消失(恢复上架之后还在),
不是把喜欢记录删了。

### 歌单

| 方法 路径 | 说明 |
|---|---|
| POST `/music/v1/playlists` | `{title, description?, is_public?, tags?, cover_url?}` → 歌单详情 |
| GET `/music/v1/playlists/{pid}` | playlist + `description, created_at, updated_at, collected, mine, tracks:[track]` |
| PATCH / DELETE `/music/v1/playlists/{pid}` | 改 / 删(主人) |
| POST `/music/v1/playlists/{pid}/tracks` | `{tids:[…]}`,去重、≤1000 首 → `{added, track_count}` |
| DELETE `/music/v1/playlists/{pid}/tracks/{tid}` | `{ok, track_count}` |
| PUT `/music/v1/playlists/{pid}/order` | `{tids:[…]}` 全量新顺序 → `{ok}` |
| POST / DELETE `/music/v1/playlists/{pid}/collect` | 收藏别人的公开歌单:`{collected, collects}` |
| POST / DELETE `/music/v1/releases/{rid}/collect` | 收藏专辑:`{collected, collects}` |

歌单名 ≤ 40 字、简介 ≤ 500 字、标签最多 5 个;封面只收站内公开图(`/img/…`,走
`POST /uploads` 的 `purpose=music_cover`),不收外链。私密歌单对别人是 404。

---

## 6. 评论

| 方法 路径 | 说明 |
|---|---|
| GET `/music/v1/tracks/{tid}/comments?sort=hot\|new&cursor=` | 公开。第一页带 `hot:[≤3]`(至少有 1 个赞的才算热评) |
| POST `/music/v1/tracks/{tid}/comments` | 登录。`{text, parent_id?}` |
| GET `/music/v1/comments/{id}/replies?cursor=` | 公开。楼中楼 |
| POST / DELETE `/music/v1/comments/{id}/like` | 登录。`{liked, likes}` |
| DELETE `/music/v1/comments/{id}` | 登录。删自己的,**或者这首歌的音乐人删自己歌下面的** |

```jsonc
// comment
{"id":12,"user":{"id":7,"name":"…","username":"…","avatar":"…"},"text":"这首好听",
 "mentions":[{"user_id":9,"username":"xiaoming"}],"likes":3,"liked":false,"reply_count":1,
 "root_id":null,"reply_to":{…person…}|null,"created_at":"…","mine":true,
 "by_artist":false,"can_delete":true,
 "replies":[…前 3 条回复…]}                    // 只有一级评论的列表里有
```

- 正文 1–1000 字;违禁词当场 422;
- `@超级赞号` 由服务端解析(对方关了「按超级赞号找到我」的当普通文字,不出链接也不通知);
- 有拉黑关系时不能评论 / 回复(403)。

---

## 7. 互动消息里的音乐(§5.8)

`GET /social/v1/notifications?kind=…` 的每一条在原字段之外可能带:

```jsonc
{"track":   {"tid":"mt…","title":"…","cover":"/img/…"} | null,
 "release": {"rid":"mr…","title":"…"} | null,
 "music_comment": {"id":12,"root_id":12,"deleted":false} | null}
```

| 事件 | kind | 带什么 |
|---|---|---|
| 有人评论我的歌 | `reply` | `track` + `music_comment` |
| 有人回复我的歌曲评论 | `reply` | `track` + `music_comment` |
| 有人在歌曲评论里 @ 我 | `at` | `track` + `music_comment` |
| 有人赞我的歌曲评论 | `like` | `track` + `music_comment`(按 `like:mcomment:<id>` 合并) |
| 作品过审 / 驳回 / 下架 / 恢复 / 申诉结果 | `system` | `release` |

客户端按有哪个字段决定点开去哪:有 `music_comment` 就进歌曲详情的评论区,
只有 `release` 就进音乐人中心的作品页。

---

## 8. 音乐人中心 `/music/v1/studio`(登录)

| 方法 路径 | 说明 |
|---|---|
| GET `/studio/me` | `{artist: {…, status} \| null}` |
| POST `/studio/artist` | 开通 `{name, bio?, genres?}`(投稿开关) |
| PATCH `/studio/artist` | 改 `{name?, bio?, genres?, avatar_url?, cover_url?}` |
| GET `/studio/releases` | 我的作品(见下面的形状) |
| POST `/studio/releases` | 建草稿 `{title, kind, genre, language, description?, release_date?, cover_media_id?}`(投稿开关) |
| PATCH / DELETE `/studio/releases/{rid}` | 改 / 删(只在 draft / rejected / withdrawn) |
| POST `/studio/releases/{rid}/tracks` | 加歌 `{title, media_id, lyrics?, credits?, explicit?, declaration}`(投稿开关) |
| PATCH / DELETE `/studio/tracks/{tid}` | 改 / 删歌(只在可编辑状态) |
| PUT `/studio/releases/{rid}/order` | `{tids}` 全量新曲序 |
| POST `/studio/releases/{rid}/submit` | 提交审核(投稿开关) |
| POST `/studio/releases/{rid}/cancel` | 撤回提交(回草稿) |
| POST `/studio/releases/{rid}/withdraw` | 已发布的自己下架 |
| POST `/studio/releases/{rid}/appeal` | `{text}`(对最近一次驳回或下架,每个结论一次) |
| GET `/studio/stats?days=30` | `{plays, listeners, likes, fans, per_day:[{day, plays, listeners}], top_tracks:[track]}` |

```jsonc
// /studio/releases 里的一个作品
{"rid":"mr…","title":"…","kind":"ep","cover":"/img/…","artist":{…},"track_count":2,
 "release_date":"2026-09-15","collects":0,"published_at":"…",
 "status":"rejected","status_label":"未通过","description":"…","genre":"pop","language":"mandarin",
 "submitted_at":"…","reject_code":"M301","reject_note":"查到是别人的歌","reject_label":"非原创且没有授权(侵权)",
 "editable":true,"can_appeal":true,"cover_media_id":123,
 "tracks":[{"tid":"mt…","title":"…","track_no":1,"duration_ms":215000,
            "transcode_status":"ready","fail_reason":"","lyrics_kind":"lrc","credits":{…},
            "explicit":false,"declaration":"original","plays":0,"likes":0}]}
```

### 8.1 艺名(M2)

2–30 个字;**全站唯一**(判据是小写去空白,「周杰伦」和「周 杰 伦」算同一个);
不能带「超级赞 / 官方 / 客服 / 管理员 / 系统 / admin / official / superz」这类保留词;过违禁词。
重名回 `409「这个艺名已经有人用了,换一个」`。一个账号只能开一个音乐人身份。

### 8.2 上传音频和封面

走 `/media/v1`,`purpose=music`:

| 类型 `kind` | 上限 | 格式 | 存哪 |
|---|---|---|---|
| `audio_source` | 200MB | mp3 / m4a / aac / flac / wav / ogg(按内容认,不看扩展名) | 私密桶,**只有作者和审核员能下** |
| `cover` | 10MB | 图片 | 私密桶;**过审时复制到公开桶** |

- ≤20MB 走 `POST /media/v1/upload`(整块),更大的走 `POST /media/v1/uploads` + 分片 4MB;
- 拿到 `media_id` 之后 `POST /studio/releases/{rid}/tracks {media_id, …}`,服务端**立刻开始转码**;
- 音乐人自己的头像、横幅和歌单封面是**公开图**,走 `POST /uploads` 的 `purpose=music_cover`,
  拿到 `/img/…` 地址后 PATCH 进去。

### 8.3 转码(M4)

`transcode_status`:`pending → processing → ready | failed`。

- 出两档 m4a:`std` 128kbps、`hq` 256kbps(源码率低于 192kbps 不出 hq);
  AAC-LC / 44.1kHz / 立体声,响度统一 −14 LUFS,`+faststart`;
- 时长必须在 **5 秒–20 分钟**,超出范围 `failed`,`fail_reason` 写明白;
- 失败自动重试 3 次(内容本身的问题不重试);`ready` 之后**原文件删掉**;
- 失败的歌删了重传就行。客户端轮询 `GET /studio/releases` 看 `transcode_status`。

### 8.4 状态机(§5.3)

```
draft ──提交──▶ reviewing ──通过──▶ published ──音乐人下架──▶ withdrawn ──再提交──▶ reviewing
                    │                   │
                    ├──驳回──▶ rejected ─┴──平台下架──▶ removed
                    └──撤回提交──▶ draft
rejected ──改完再提交──▶ reviewing;rejected / removed 申诉改判(换人)──▶ published
```

- **提交的前提**:至少 1 首歌、每首都转码完成、有封面、每首都勾了原创 / 授权声明;
- 只有 `draft` / `rejected` / `withdrawn` 能改信息、增删歌曲、改曲序、删除;
  已发布的要改 → 先 `withdraw`,改完再 `submit`(M3);
- 申诉:每个驳回 / 下架**只能申诉一次**,而且**原审核人不能复核自己的决定**(403)。
  作品在决定之后又改过了就不用申诉了(409,改完重交更快)。

---

## 9. 举报

`POST /music/v1/reports`(登录)

```jsonc
{"target_type": "track|release|comment|playlist|artist",
 "target_id": "mt…",          // 评论传评论 id 的字符串
 "reason_code": "M301",
 "note": "…",
 "contact": "copyright@example.com"}   // 版权投诉(M301)必填,别的可选
```

举报人对被举报的一方**永远匿名**;同一个人同一个对象 7 天内只记一次;
7 天内 3 个不同的人举报同一个对象自动进复审(`escalated`,后台排最前)。

原因代码(§5.11,和视频共用 `C1xx` / `X999`):

| 代码 | 意思 |
|---|---|
| `C101`–`C109` | 骚扰辱骂、垃圾广告、诈骗、色情低俗、暴力血腥、违法违规、侵犯隐私、冒充他人或官方、未成年人不宜 |
| `M301` | 非原创且没有授权(侵权)—— **必须留联系方式** |
| `M302` | 音频不完整(无声、截断、严重失真) |
| `M303` | 歌名 / 封面 / 署名与内容不符 |
| `M304` | 歌词违规 |
| `M305` | 冒充其他音乐人 |
| `X999` | 其他(必须写说明,至少 5 个字) |

---

## 10. 管理 `/admin/music/…`(管理员)

| 方法 路径 | 说明 |
|---|---|
| GET `/review?limit=` | 待审作品,按提交时间先后;每首歌带**能直接播的地址**(签名绑这位管理员,6 小时),封面也给签名地址 |
| GET `/releases/{rid}` | 单个作品 + `decisions`(全部审核记录和申诉) |
| POST `/releases/{rid}/decide` | `{action: "approve"\|"reject", reason_code?, note?}` |
| POST `/releases/{rid}/remove` | `{reason_code, note}` 下架 |
| POST `/releases/{rid}/restore` | `{note?}` 恢复 |
| GET `/appeals` | 待处理的申诉;`you_decided_original` 为真的你不能处理 |
| POST `/appeals/{decision_id}/resolve` | `{result: "upheld"\|"overturned", note}` |
| GET `/reports?status=open\|handled\|all` | 举报(带 `contact`、`is_copyright`,不含举报人) |
| POST `/reports/{id}/handle` | `{action: "dismiss"\|"remove_target", reason_code?, note?}` |
| GET `/artists?q=` | 音乐人列表 |
| POST `/artists/{aid}/suspend` / `restore` | 停用 / 恢复 |
| GET `/stats` | 近 7 天审核量、驳回率、下架数、待办数 |
| GET `/reason-codes` | 原因代码表 + `copyright_code` |

`remove_target` 按对象类型分别处置:歌 / 作品 → 下架所在的**作品**(审核单位是作品);
评论 → 删除;歌单 → 改成私密(是用户自己的东西,不删);音乐人 → 停用。

---

## 11. 注销账号(§3.7)

`DELETE /auth/me` 之后音乐这边:

- 音乐人身份、作品、歌曲连同全部音频、封面**立即**清掉,播放地址和公开桶里的封面当场失效;
- 他的歌单删掉;喜欢、收藏、最近播放、收听明细、个人设置删掉;
- 他写的评论清空正文、标成已删除(别人的回复不跟着消失);
- 举报记录留着(那是平台的处置依据),但说明和联系方式清空;
- 受影响的歌按明细表重算计数。

导出(`POST /chat/v1/export`)里的 `music.json` 有:音乐人资料、作品和每首歌的元数据(含歌词、署名)、
歌单及歌名、喜欢的歌、我写过的评论、最近播放。**音频文件不放进包里** —— 歌是自己上传的,母带在自己手里。
