# 论坛接口参考(客户端用)

对应 DEV-PROMPTS-41 的「论坛」部分(#380、#381)。服务端实现在 `server/app/routers/forum.py`、
`routers/forum_admin.py`、`services/forum.py`、`services/forum_feed.py`、`services/forum_rank.py`、
`services/cards.py`。字段名和类型以这里和 [DEV-PROMPTS-41.md](DEV-PROMPTS-41.md) §8.1 / §8.3 为准;
改接口时本文要一起改。

---

## 0. 通用约定

### 0.1 鉴权

- `Authorization: Bearer <JWT>`,和其它接口同一个 token;
- 标 **公开** 的接口没登录也能调;登录了会多出和「我」有关的字段(`viewer`、`can_reply`、个性化推荐);
- 标 **登录** 的接口要登录,而且只对用户端账号开放(D1),商家 / 骑手账号调回
  `403「消息和视频只在用户端开放」`;
- 标 **管理员** 的是 `/admin/forum/…`;
- **论坛不要求实名**(2026-09-15 用户拍板):发帖、回复、投票只要手机号账号。

### 0.2 开关

| 开关 | 关着时 |
|---|---|
| `forum_enabled` | `/forum/v1/*` 全部回 `503 {"detail": "论坛暂未开放"}`(生产缺省关,等合规结论) |
| `forum_post_enabled` | 发帖、回复、引用、编辑回 `503 {"detail": "论坛发帖暂停中"}`;**看还是能看** |

`GET /config` 的 `features.forum` / `features.forum_post` 是这两个开关的当前值 ——
客户端据此收起金刚区那一格、收起发帖按钮,别让人点进去才知道。
互动消息 `/social/v1/notifications` 不受开关影响(已经收到的下架通知关了也得能看)。

### 0.3 错误

错误体统一是 `{"detail": "给用户看的中文"}`,直接展示 `detail`。
**一个例外**:被禁言 / 封号时(发帖、回复、引用、编辑,以及封号期间的互动接口)是 403,
`detail` 是对象 `{"error": "sanctioned", "message", "reason_code", "reason_label", "until", "can_appeal", …}`,
展示 `detail.message`;字段见 [COMMUNITY-GOVERNANCE.md](COMMUNITY-GOVERNANCE.md) §3。

| 状态码 | 什么时候 |
|---|---|
| 401 | 没登录 / token 过期 |
| 403 | 没权限:改删别人的帖子、作者设了「谁能回复」、有拉黑关系、原审核人处理自己结论的申诉、被禁言 / 封号、看别人「喜欢」的页签 |
| 404 | 不存在、已删除、已下架、**或者你没权限看**(拉黑关系一律 404,不告诉你「有但你看不了」) |
| 409 | 状态不对:发出 30 分钟后编辑、编辑超过 5 次、投过票再投、同一个决定申诉两次、举报处理过了 |
| 422 | 输入不合规:正文超 500 字、图片不是自己传的、卡片查不到、投票选项数 / 时长不对、原因代码不存在、违禁词 |
| 429 | 限流(见 0.5) |
| 503 | 开关关着(见 0.2) |

### 0.4 分页

- 按分数排的(推荐、话题页 `sort=top`、搜索)用 `page`(0 起,最多 200),返回 `{items, page, has_more}`;
- 按时间排的用 `cursor`(`"{微秒}_{id}"`),返回 `{items, has_more, next_cursor}`;`next_cursor` 是
  `null` 就是到底了。

### 0.5 限流(§5.10)

| 动作 | 上限 | 超了 |
|---|---|---|
| 发帖(含回复、引用) | 每 10 秒 1 条、每小时 60 条、每天 300 条 | 429「发得太快了,歇一下再发」/「这一小时发得太多了」/「今天发的帖子太多了」 |
| 赞、转发、书签、投票 | 每人每秒 5 次 | 429「点得太快了,歇一下」 |
| 浏览上报 | 每人每分钟 120 次 | 429 |
| 搜索 | 每分钟 60 次 | 429 |
| 举报 | 每人每分钟 10 次 | 429 |

### 0.6 时间与编号

- 时间一律 ISO 8601 带时区;「日」按北京时间切;
- 帖子的公开编号是 `fp` + 10 位 base58(字母表 `[1-9A-HJ-NP-Za-km-z]`,不含 `0OIl`),
  链接 `https://chaojizan.cc/forum/p/<pid>`;话题的链接是 `/forum/t/<话题,URL 编码>`。

---

## 1. 帖子的形状(§8.1)

```jsonc
{
  "pid": "fpAbc123XyZ9",
  "author": {"id": 42, "name": "小王", "username": "xiaowang", "avatar": "…"},
  "text": "周末去 #成都# 玩 @xiaoming,看 https://…",
  // 实体**只由服务端解析**(§5.6),客户端报什么都不算数
  "entities": {
    "tags": [{"tag": "成都", "display": "成都"}],       // tag 是小写规范化的,display 是原样
    "mentions": [{"id": 7, "username": "xiaoming"}],    // 关了「按超级赞号找到我」的人不在里面
    "links": ["https://…"]
  },
  "media": [{"url": "/img/forum/u42-….jpg", "w": 1080, "h": 1440}],   // ≤ 4 张
  // 卡片每次现查,不存快照;查不到时是 {"type":…, "id":…, "unavailable": true}
  "card": {"type": "post", "id": "fp…", "title": "…", "subtitle": "…", "cover": "…",
           "url": "https://chaojizan.cc/forum/p/fp…"},
  "quote": null,                 // 引用:整条 post(不再嵌套 quote),或 {"pid","unavailable":true,"reason"}
  "reply_to": null,              // {"pid": "fp…", "author": {person}}
  "root_pid": null,              // 整串的第一条
  // 投票:**没投过、没结束、又不是作者时,每项的 votes 和 total 是 null**(投票前看不到结果)
  "poll": {"options": [{"text": "火锅", "votes": 3}], "total": 5,
           "ends_at": "…", "closed": false, "voted": null},
  "reply_policy": "all",         // all 所有人 / following 我关注的人 / mentioned 我提到的人
  "can_reply": true,             // 按 reply_policy 和拉黑算出来的,给客户端决定要不要摆输入框
  "counts": {"replies": 1, "reposts": 2, "quotes": 0, "likes": 9, "bookmarks": 1, "views": 120},
  "viewer": {"liked": false, "reposted": false, "bookmarked": false},
  "edited": false, "edited_at": null,
  "created_at": "2026-09-15T12:00:00+08:00",
  "pinned": false
}
```

看不见的帖子(删了、下架了、拉黑关系)在串里、引用里**占位**,不是消失:

```jsonc
{"pid": "fp…", "unavailable": true, "reason": "deleted|removed|blocked"}
```

时间线的条目有两种:

```jsonc
{"type": "post", "post": {…}, "rank": {…}?}
{"type": "repost", "by": {person}, "at": "2026-09-15T…", "post": {…}}
```

`rank`(只有推荐时间线有):

```jsonc
{"score": 0.2224,
 "parts": {"likes": 3, "reposts": 1, "quotes": 0, "repliers": 0,
           "hours": 7.0, "e": 5, "following": false, "topic": false},
 "why": "近 72 小时 3 人点赞、1 人转发、0 人引用、0 人回复(互动分 5),发帖 7.0 小时"}
```

---

## 2. 时间线

| 方法 路径 | 谁 | 说明 |
|---|---|---|
| GET `/forum/v1/timeline/foryou?page=` | 公开 | 推荐(§5.7)。`{items:[{type:"post", post, rank}], page, has_more, personalized, ranked_at}`。每屏 20 条,同一作者最多 2 条 |
| GET `/forum/v1/timeline/following?cursor=` | 登录 | 关注的人的帖子**和转发**,按事件时间倒序 |

推荐的候选是 72 小时内的原帖(不含回复);作者和我没有拉黑关系、不含我的屏蔽词。
关掉个性化(`PUT /me/settings {"personalize": false}`)之后,**结果和没登录的人逐条相等**。

## 3. 帖子

| 方法 路径 | 谁 | 说明 |
|---|---|---|
| POST `/forum/v1/posts` | 登录 + 发帖闸 | `{text, media?:[{url,w,h}], card?:{type,id}, quote_pid?, reply_to_pid?, poll?:{options:[…], minutes}, reply_policy?}` → post |
| GET `/forum/v1/posts/{pid}` | 公开 | `{post, ancestors:[post 或占位]}` |
| GET `/forum/v1/posts/{pid}/replies?sort=top\|new&cursor=` | 公开 | 回复。`top` 按赞数、`new` 按时间正序 |
| PATCH `/forum/v1/posts/{pid}` | 登录 + 发帖闸 | `{text}` → post。发出 30 分钟内、最多 5 次,旧正文进历史 |
| GET `/forum/v1/posts/{pid}/edits` | 公开 | `{items:[{text, created_at}]}` |
| DELETE `/forum/v1/posts/{pid}` | 登录 | 软删:下面的回复保留,这一条在串里占位 |
| POST / DELETE `/forum/v1/posts/{pid}/like` | 登录 | `{liked, likes}` |
| POST / DELETE `/forum/v1/posts/{pid}/repost` | 登录 | `{reposted, reposts}` |
| POST / DELETE `/forum/v1/posts/{pid}/bookmark` | 登录 | `{bookmarked}`。**书签只有自己看得见** |
| GET `/forum/v1/posts/{pid}/quotes?cursor=` | 公开 | 引用了这条的帖子 |
| GET `/forum/v1/posts/{pid}/likers?cursor=` | 公开 | 点赞的人(每项 person + `followed`) |
| POST `/forum/v1/posts/{pid}/vote` | 登录 | `{option}`(下标)→ poll。每人一票、不能改 |
| POST `/forum/v1/posts/views` | 登录 | `{pids:[≤50], device_id?}` → `{ok, counted}`。按人按天去重 |
| POST `/forum/v1/posts/{pid}/pin` / DELETE `/forum/v1/pin` | 登录 | 置顶到自己主页(每人一条)/ 取消 |
| POST `/forum/v1/posts/{pid}/appeal` | 登录 | `{text}`(5–500 字)。对最近一次下架,**每个决定只能申诉一次** |

发帖的几条规矩(§5.6):

- 正文 1–500 字(Unicode 字符数,去掉首尾空白);有图、卡片、引用或投票时正文可以为空;
- 图片最多 4 张,而且**必须是自己刚通过 `POST /upload?purpose=forum` 传上来的**
  (地址长 `/img/forum/u<我的 id>-…`),用别人的一律 422;
- 卡片只传 `{type, id}`,标题封面由服务端现查;查不到(删了、没过审、私密)拒发 422;
- 投票 2–4 项、每项 1–25 字、5 分钟–7 天;回复里不能带投票;违禁词管正文**也管选项**;
- 话题认 `#话题#` 和 `#话题` 两种写法(遇到空白、`#`、中英文标点截止),1–30 字、不分大小写,每帖最多 10 个;
- @ 认 `@超级赞号`(字母开头 5–32 位),查不到人的、对方关了「按超级赞号找到我」的不算,每帖最多 10 个;
- 链接最多 3 个。

## 4. 个人主页与「我的」

| 方法 路径 | 谁 | 说明 |
|---|---|---|
| GET `/forum/v1/users/{uid}/profile` | 公开 | `{user:{person}, bio, joined_at, posts, following, fans, followed, follows_you, pinned}` |
| GET `/forum/v1/users/{uid}/posts?tab=posts\|replies\|media\|likes&cursor=` | 公开 | `posts` 含转发(是 timeline item);`likes` **只有本人能看**(别人 403) |
| GET `/forum/v1/me/bookmarks?cursor=` | 登录 | 我的书签 |
| GET / POST `/forum/v1/me/mute-words` | 登录 | `{items:[word]}`;POST 体 `{word}`。每人最多 100 个 |
| DELETE `/forum/v1/me/mute-words?word=…` | 登录 | 删一个(词在 query 里,DELETE 不带请求体) |
| GET / PUT `/forum/v1/me/settings` | 登录 | `{personalize}` |

关注 / 粉丝走全站统一的 `/social/v1/users/{id}/follow`、`followers`、`following`、`follow-stats`
(§8.4,**不挂任何模块开关**)。

## 5. 话题、搜索、公式、举报

| 方法 路径 | 谁 | 说明 |
|---|---|---|
| GET `/forum/v1/tags/trending` | 公开 | `{items:[{tag, display, authors_24h, authors_3h, score}], updated_at}` |
| GET `/forum/v1/tags/{tag}/posts?sort=top\|new&cursor=&page=` | 公开 | 话题页,带 `{tag, display, posts, hidden}` |
| GET `/forum/v1/search?q=&type=posts\|users\|tags&page=` | 公开 | 搜索(ILIKE);`q` 为空返回空列表 |
| GET `/forum/v1/rank/formula` | 公开 | `{formula, params}` —— 公式原文和全部参数 |
| GET `/forum/v1/reason-codes` | 公开 | `{items:[{code, label}]}`,举报弹窗照它摆 |
| POST `/forum/v1/reports` | 登录 | `{pid, reason_code, note?}` → `{ok}`。举报人对被举报的一方永远匿名 |

**运营隐藏的话题不上热门榜,但话题页照样能打开、帖子照样在**(§2.2 不偷偷压话题),
话题页的 `hidden` 为真时客户端可以标一句「这个话题已从热门榜移除」。

## 6. 互动消息(§5.8)

`GET /social/v1/notifications?kind=…` 的 `kind` 在原来的 `reply` / `at` / `like` / `system` /
`follow` 之外加了 `repost`、`quote`。论坛产生的每一条在原字段之外带:

```jsonc
"post": {"pid": "fp…", "text": "帖子正文前 80 字", "unavailable": false}
```

客户端按有 `post` / `video` / `comment` 哪个字段决定点开去哪。合并规则:

| 事件 | kind | 合并 |
|---|---|---|
| 有人回复我的帖子 | `reply` | 不合并 |
| 帖子里 @ 我 | `at` | 不合并 |
| 有人赞我的帖子 | `like` | 按帖子合并(`like:post:<id>`),「小王等 12 人赞了你的帖子」 |
| 有人转发我的帖子 | `repost` | 按帖子合并(`repost:post:<id>`) |
| 有人引用我的帖子 | `quote` | 不合并 |
| 帖子被下架 / 恢复、申诉结果、投票结束 | `system` | 不合并 |

## 7. 公式(§5.7,和 `services/forum_rank.FORMULA` 逐字一致)

```text
互动分 E = 点赞人数 + 2 × 转发人数 + 2 × 引用人数 + 3 × 回复人数(都按人去重,只算发帖后 72 小时内)
推荐分 = (E + 1) ÷ (发帖后小时数 + 2)^1.5 × (1 + [我关注了作者]) × (1 + 0.5 × [帖子里有我近30天发过或点过赞的话题])
候选是 72 小时内的原帖(不含回复),作者没被我拉黑、也没拉黑我,不含我的屏蔽词;每屏 20 条,同一作者最多 2 条
关掉个性化后两个方括号都按 0 算
热门话题分数 = 近24小时用过这个话题的人数 + 2 × 近3小时用过的人数;近24小时至少 2 人用过才上榜,最多 20 个;运营隐藏的话题不上榜
```

`GET /forum/v1/rank/formula` 原样返回这段话和全部参数(`window_hours`、`like_weight`、
`repost_weight`、`quote_weight`、`reply_weight`、`e_offset`、`decay_offset_hours`、
`decay_power`、`follow_bonus`、`topic_bonus`、`topic_lookback_days`、`screen_size`、
`per_author_per_screen`、`trend_window_hours`、`trend_recent_hours`、`trend_recent_weight`、
`trend_min_authors`、`trend_max`)。每条推荐带 `rank.parts`,**拿计算器能复算**。

## 8. 原因代码(§5.11)

共用视频那张表的 `C101`–`C109` 和 `X999`,论坛另加:

| 代码 | 意思 |
|---|---|
| `F401` | 刷屏、重复发帖 |
| `F402` | 蹭无关话题 |
| `F403` | 恶意引战、人身攻击 |

选 `X999` 必须写至少 5 个字的说明。视频专有的 `V2xx` 在论坛不可用。

## 9. 后台(`/admin/forum`,管理员)

| 方法 路径 | 说明 |
|---|---|
| GET `/reports?status=open\|handled\|all` | 帖子举报(不含举报人) |
| POST `/reports/{id}/handle` | `{action: remove\|dismiss, reason_code?, note?, note_internal?}`;同一条帖子上没处理的举报一起结案 |
| GET `/posts?q=&author=&status=` | 按正文关键词 / 作者 / 状态找帖子(下架的、作者删的也找得到) |
| POST `/posts/{pid}/remove` | `{reason_code, note, note_internal?}`;作者收到 system,可申诉一次 |
| POST `/posts/{pid}/restore` | `{note?}` |
| GET `/appeals?status=open\|resolved\|all` | 申诉;`you_decided_original` 为真的**你不能处理** |
| POST `/appeals/{decision_id}/resolve` | `{result: upheld\|overturned, note}`;原审核人调回 403,改判自动恢复帖子 |
| GET `/tags?hidden=&q=` | 话题表 |
| POST `/tags/{tag}/hide` / `unhide` | `{reason_code, note}`;隐藏要写原因、进 `forum_decisions` 留痕 |
| GET `/stats` | `{posts_7d, removed_7d, visible_total, reports_open, appeals_open, tags_hidden, tags_total}` |
| GET `/reason-codes` | 原因代码表 |

## 10. 注销与导出(§3.7)

- `DELETE /auth/me` 会走 `services/forum.purge_user`:自己的帖子正文、实体、图片、卡片清空并标删除
  (**别人的回复留着**),赞 / 转发 / 书签 / 投票 / 置顶 / 屏蔽词 / 浏览记录全删,受影响的帖子按明细表重算计数;
- `POST /chat/v1/export` 导出的 zip 里有 `forum_posts.json`:自己发过的帖子(正文、图片地址、
  回复 / 引用指向谁、计数、链接)。
