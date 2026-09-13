# 社区治理:处罚、举报、申诉、管理员查看私聊留痕、透明中心「社区」栏

DEV-PROMPTS-40 #368(聊天部分)、#370、#371,不变量 **S6**(每个处罚都有原因、能申诉、换人复核)
和 **S8**(管理员看私聊要留痕)。视频的审核、下架、视频申诉、视频 / 评论 / 弹幕举报的接口在
[VIDEO-API.md](VIDEO-API.md) §11(同一个前缀 `/admin/social`),这里是对**人和会话**的那一半,
以及两半共用的数据页和透明中心栏。

本文、实现(`server/app/services/sanctions.py`、`chat_moderation.py`、`community_stats.py`、
`routers/social_admin.py`)、测试(`tests/e2e_social_moderation.py`、`tests/unit/test_sanctions.py`)逐字一致:
§1、§2 的表和 §3 的字段由单测对着代码比,改一处就要改三处。

---

## 1. 处罚种类

| 种类 `action` | 名字 | 对象 | 期限 | 效果 |
|---|---|---|---|---|
| `delete_messages` | 删除消息 | 被删消息的发送人(以会话名义发的记在群主头上) | 一次性 | 被举报的那几条正文、媒体清空,seq 占位,会话里发 `del` 事件;删了不能恢复 |
| `mute` | 禁言 | 人 | 1–720 小时,必须限时 | 不能发消息(含转发、改消息)、评论、弹幕 |
| `ban_chat` | 封禁群 / 频道 | 群、频道 | 1–3650 天或永久 | 成员不能发言、不能再加入;公开搜索、@链接、非成员预览里消失;成员照样能看历史 |
| `ban_account` | 封号 | 人 | 1–3650 天或永久 | 社交相关的写操作全拒;能登录、看自己的数据、注销、申诉 |
| `warn` | 警告 | 人 | 一次性 | 只记录和通知 |

- 原因代码用 DEV-PROMPTS-40 §5.11 同一张表(C101 … X999,`GET /admin/social/reason-codes`);**X999 必须写说明**(至少 5 个字);
- `note` 给当事人看(系统通知、处罚记录、被挡时的 403 里都有),`note_internal` 只在后台看;两者都不进透明中心;
- 「生效中」= 没撤销,并且没有到期时间或到期时间还没到;只有 mute / ban_chat / ban_account 会挡人;
- 当事人:对人的处罚是那个人;对会话的处罚是**当前的**群主 / 频道主(群主转让了,申诉权跟着走);
- 同时有几条生效时,提示用最重的那条:封号 > 封群 > 禁言;同种里永久的、到期晚的在前。

## 2. 执行点

每个执行点都落在真实的写路径上,判定只有 `services/sanctions.py` 一处(`check_user` / `check_chat`)。

| 执行点 `point` | 写路径 | 被哪些处罚挡住 |
|---|---|---|
| `message` | chat_store.send / forward / edit | ban_account、mute |
| `comment` | video_talk.post_comment | ban_account、mute |
| `danmaku` | video_talk.post_danmaku | ban_account、mute |
| `create_chat` | chat_store.create_chat、private_chat(新建时) | ban_account |
| `join` | chat_store.join_by_invite、join_public | ban_account |
| `video_submit` | video.submit | ban_account |
| `call` | calls._invite(WebSocket 信令) | ban_account |
| `social_write` | routers/social.social_user(其余全部社交写接口) | ban_account |

会话被 `ban_chat` 时挡两个执行点:

| 执行点 `point` | 写路径 |
|---|---|
| `speak` | chat_store.send、forward(目标会话)、edit、update_chat_info(改名、简介、公开链接) |
| `join` | chat_store.join_by_invite、join_public、add_members、decide_join_request(同意)、邀请链接预览 `GET /chat/v1/join/{code}` |

**封号在 `social_user` 统一挡**:社交写接口(`/chat/v1`、`/social/v1`、`/video/v1`、`/media/v1`、`/chat/v1/stickers`
下所有 POST / PUT / PATCH / DELETE;唯一的例外是不用登录的播放心跳 `POST /video/v1/videos/{vid}/view`)都挂着这个依赖,
被封号的人发来的写请求**默认全拒**,只放行下面这张表里的(新加的写接口忘了处理封号,也不会漏过去;
单测扫全部路由,没挂 `social_user` 的社交写接口会让它红):

| 方法 | 路径 | 为什么放行 |
|---|---|---|
| POST | /social/v1/sanctions/{sanction_id}/appeal | 申诉处罚 |
| POST | /video/v1/videos/{vid}/appeal | 申诉视频驳回 / 下架 |
| POST | /chat/v1/export | 导出自己的数据(S5,下载走 `GET /media/v1/files/{id}`,本来就是读) |
| POST | /chat/v1/sync | 读:断线补齐 |
| POST | /chat/v1/dialogs/{chat_id}/read | 读:已读位置 |
| POST | /social/v1/notifications/read | 读:通知已读 |
| POST | /media/v1/sign | 读:换媒体下载地址 |
| PATCH | /chat/v1/dialogs/{chat_id} | 只有自己看得见的会话设置(置顶、归档、免打扰、草稿) |
| PATCH | /social/v1/me | 隐私和通知设置(签名除外:改签名照样 403) |
| PATCH | /video/v1/me/settings | 个性化推荐开关(S9 任何时候都能关) |
| POST | /social/v1/blocks | 拉黑是自我保护 |
| DELETE | /social/v1/blocks/{user_id} | 解除拉黑 |
| POST | /chat/v1/chats/{chat_id}/leave | 退出群 / 频道 |
| POST | /chat/v1/reports | 举报(只给平台看) |
| POST | /video/v1/reports | 举报(只给平台看) |
| DELETE | /video/v1/me/history | 自己的观看历史 |
| DELETE | /video/v1/me/history/{vid} | 自己的观看历史 |

注销账号是 `DELETE /auth/me`,不挂 `social_user`,封号期间照样能注销(见 §8);
导出进度 `GET /chat/v1/export` 是读,不受影响。
定时消息到点由清扫任务发出时同样过 `chat_store.send`,发的人那时被禁言 / 封号就发不出去,
他收到一个 `scheduled_failed` 用户事件,`reason` 是下面 `message` 那句话。

## 3. 被挡时的 403

所有执行点被挡都回 **403**,`detail` 是同一个形状(客户端照着提示用户,不用自己拼话):

```json
{
  "error": "sanctioned",
  "message": "你被禁言到 2026 年 9 月 13 日 10:00,原因:骚扰、辱骂(多次辱骂他人)。期间不能发消息、评论和发弹幕。有异议可以申诉。",
  "sanction_id": 12,
  "scope": "user",
  "point": "message",
  "action": "mute",
  "action_label": "禁言",
  "reason_code": "C101",
  "reason_label": "骚扰、辱骂",
  "note": "多次辱骂他人",
  "until": "2026-09-13T02:00:00+00:00",
  "permanent": false,
  "can_appeal": true,
  "appeal_status": "",
  "appeal_path": "/social/v1/sanctions/12/appeal"
}
```

| 字段 | 说明 |
|---|---|
| `error` | 恒为 `sanctioned`(和别的 403 区分开) |
| `message` | 一句完整的话,直接给用户看(到期时间是北京时间) |
| `scope` | `user` 对人的处罚 / `chat` 会话被封 |
| `point` | 被挡的执行点(§2);封号在 `social_user` 统一挡时是 `social_write` |
| `until` / `permanent` | 到期时间(UTC ISO);永久时 `until` 为 null、`permanent` 为 true |
| `note` | 给当事人的说明。**会话被封时群里的普通成员不是当事人**:`note` 为空串、`can_appeal` 为 false、`appeal_path` 为 null,`message` 里写「群主可以申诉」 |
| `can_appeal` / `appeal_path` | 当事人、没撤销、还没申诉过时为真 / 给出申诉接口 |
| `appeal_status` | `""` 没申诉 / `open` 处理中 / `upheld` 维持 / `overturned` 撤销(非当事人恒为空串) |

打电话走 WebSocket,没有 HTTP 403:`{"t": "call", "a": "error", "call_id": …, "reason": "sanctioned", "message": …, "sanction": {同上}}`。

会话卡片(`GET /chat/v1/chats/{id}`、会话列表 `GET /chat/v1/dialogs` 的每一项)多一个 `platform_ban`:
群 / 频道此刻被封时是 `{"sanction_id", "reason_code", "reason_label", "until", "permanent", "message"}`,
否则为 null;封禁、解封时会话里各发一个 `chat` 事件 `{"platform_ban": {…} | null}`。

## 4. 接口

### 4.1 我的处罚与申诉(登录,用户端账号)

**`GET /social/v1/me/sanctions`** —— 对我这个人的处罚 + 对我当群主 / 频道主的会话的处罚,新的在前,最多 200 条:

```json
{"active": [SanctionOut, …], "history": [SanctionOut, …]}
```

`SanctionOut`:

```json
{
  "id": 12, "target_type": "user", "chat_id": 7,
  "action": "mute", "action_label": "禁言",
  "reason_code": "C101", "reason_label": "骚扰、辱骂", "note": "多次辱骂他人",
  "until": "2026-09-13T02:00:00+00:00", "permanent": false, "duration": "24 小时",
  "seqs": [],
  "status": "active", "status_label": "生效中",
  "created_at": "…", "revoked_at": null, "revoke_note": "",
  "appeal": {"status": "", "status_label": "未申诉", "text": "", "appealed_at": null,
             "note": "", "resolved_at": null},
  "can_appeal": true
}
```

- `status`:`active` 生效中 / `expired` 已到期 / `revoked` 已撤销 / `done` 一次性处罚已执行;
- `chat_id`:对人的处罚来自某个会话的举报时是那个会话,对会话的处罚是那个会话;`seqs`:删消息删的是哪几条;
- 不带内部备注、不带处理人是谁。

**`POST /social/v1/sanctions/{id}/appeal`** `{"text": "申诉理由,5–500 字"}` →
`{"id": 12, "appeal": {"status": "open", "status_label": "申诉处理中", "text": "…", "appealed_at": "…", "note": "", "resolved_at": null}}`。
一次处罚只能申诉一次(再申诉 409「每个处罚只能申诉一次」);不是你的处罚 404;已撤销的 409;理由长度不对 422。
封号期间也能用。处罚、申诉结果都会进「互动消息 → 系统通知」(`data.sanction_id`、`data.sanction_action`)。

### 4.2 举报(用户端,改动)

`POST /chat/v1/reports` 的请求不变(`target_type` chat / message / user,`chat_id`、`seqs`、`user_id`、`reason_code`、`note`),
响应 `{"id": 3, "status": "open" | "escalated"}`。服务端这次加了三件事:

- 只收举报人**当时看得到**的消息(清空过的、入群前的不收,已删除的不收);举报用户时只收他在这个会话里发的;
  举报整个会话、没指定消息时,带上举报人当时能看到的最近 10 条;
- 记下举报人当时的可见下限,管理员按 S8 看上下文时不越过它;
- 记下「被举报的是谁」:消息的发送人、被举报的用户,或者会话本身(整个会话、频道帖子、匿名发言);
  **7 天内 3 个不同的人举报同一个对象**,这些举报单变成 `escalated`,排在队列最前。

### 4.3 后台 `/admin/social/…`(管理员;非管理员一律 403)

| 接口 | 请求 → 响应 |
|---|---|
| `GET /admin/social/chat-reports?status=open\|handled\|all&limit=100` | 队列:`{"items": [ReportItem], "count": N}`。待处理的 escalated 在前、其余按时间先后;处理过的新的在前。**不含消息内容、不含举报人** |
| `GET /admin/social/chat-reports/{id}` | `{"report": ReportItem, "subject_sanctions": [对象身上的处罚], "related_open": [同一对象的其他待处理举报单号], "views": [{"id", "admin": {"id", "name", …}, "chat_id", "seqs", "at"}], "can_view_messages": true, "messages_path": "/admin/social/chat-messages?report_id=3", "candidates": {"users": [能处罚的人], "chat": 能封的群 \| null}}`。**不含消息内容** |
| `GET /admin/social/chat-messages?report_id=3` | S8 查看(§6):`{"report_id", "chat": {"id", "type", "title", "username", "member_count", "owner_id", "deleted"}, "reported_seqs": [10], "seqs": [5, …, 15], "messages": [{"seq", "sender": {"id", "name", "username", …} \| null, "as_chat", "kind", "text", "media": [{"id", "kind", "name", "size", "w", "h", "duration_ms", "mime", "url", "thumb"}], "extra", "reply_to_seq", "created_at", "edited_at", "deleted", "reported"}], "audit": {"id", "at", "notice": "本次查看已记录…"}}`。**不带 report_id → 403** |
| `POST /admin/social/chat-reports/{id}/handle` | `{"action": "dismiss\|delete_messages\|mute\|ban_chat\|ban_account\|warn", "reason_code": "C101", "note": "给当事人看", "note_internal": "", "hours": 24, "days": 7, "permanent": false, "user_id": null, "also_delete": false}` → `{"id": 3, "status": "actioned\|dismissed", "resolution": "已禁言 24 小时:骚扰、辱骂", "sanction_ids": [12, 13]}`。`hours` 只给禁言(1–720);`days` / `permanent` 给封号、封群;`user_id` 默认是被举报的人,**必须是这张单涉及的人**(被举报的人、被举报消息的发送人、群主),否则 422;`also_delete` 同时删掉被举报的消息(按发送人各记一条 `delete_messages`);已处理 409 |
| `GET /admin/social/sanctions?status=all\|active\|expired\|revoked\|done&action=&target_type=&reason_code=&appeal=none\|open\|upheld\|overturned&target_id=&before=&limit=50` | 处置记录(新到旧,`next_before` 翻页):`{"items": [SanctionAdmin], "next_before": 41 \| null}` |
| `POST /admin/social/sanctions` | 直接处置(比如评论、弹幕被举报,删掉之后再禁言发的人):`{"target_type": "user\|chat", "target_id", "action": "mute\|ban_chat\|ban_account\|warn", "reason_code", "note", "note_internal", "hours", "days", "permanent", "video_report_id": 21}` → `SanctionAdmin`。删消息不走这里(S8 的范围由聊天举报单定) |
| `POST /admin/social/sanctions/{id}/revoke` | `{"note": "撤销理由(会告诉当事人)"}` → `SanctionAdmin`。已撤销 409;**当事人已经申诉的 409**(必须在申诉里换人处理) |
| `GET /admin/social/social-appeals?status=open\|resolved\|all` | `{"items": [{"appeal": {"id", "status", "text", "appealed_at"}, "sanction": SanctionAdmin, "you_decided_original": true}]}`。申诉单号就是处罚编号 |
| `POST /admin/social/social-appeals/{id}/resolve` | `{"overturn": true, "note": "复核结论(给当事人看)", "note_internal": ""}` → `{"id": 12, "appeal_status": "overturned", "sanction": SanctionAdmin}`。**处理人等于原处罚人 → 403「原处罚是你作出的,申诉必须由另一名审核员处理」**;撤销 = 立即解除限制 + 通知当事人;不是待处理 409 |
| `GET /admin/social/community-stats?days=30` | 数据页(§7):`{"days", "since", "items": [{"day", "messages", "active_chats", "video_submissions", "review_decisions", "review_median_hours", "reports", "sanctions"}], "totals": {…}, "open": {"chat_reports", "video_reports", "social_appeals", "review_queue"}, "notes": {…}}` |

`ReportItem`:`{"id", "target_type", "status": "open|escalated|actioned|dismissed", "status_label", "escalated", "reason_code", "reason_label", "note"(举报人写的说明), "chat": {"id", "type", "title"(私聊显示「私聊」), …}, "subject": {"type": "user|chat", "id", …}, "seq_count", "reporters_7d"(近 7 天举报同一对象的不同人数), "created_at", "handled_at", "handled_by", "decision"}`。

`SanctionAdmin`:`SanctionOut` 的全部字段 + `target`(人或会话的简卡)、`note_internal`、`admin`(谁处罚的)、`report`(`{"kind": "chat|video", "id"}`)、
`revoked_by`、`appeal.note_internal`、`appeal.admin`、`carried_from`、`you_decided`(是不是你处罚的)。

### 4.4 透明中心 `GET /transparency/community`(公开,无鉴权,按 IP 限流,缓存 5 分钟)

```json
{
  "window_days": 30,
  "video_review": {
    "last_30d": {"reviewed": 120, "approved": 105, "rejected": 15, "reject_rate": 0.125, "median_review_hours": 3.5},
    "monthly": [{"month": "2026-09", "reviewed": 40, "approved": 35, "rejected": 5, "reject_rate": 0.125, "median_review_hours": 2.8}]
  },
  "sanctions": {
    "last_30d": {"total": 9, "by_action": [{"action": "mute", "label": "禁言", "count": 3}, …, {"action": "remove_video", "label": "下架视频", "count": 1}]},
    "monthly": [{"month": "2026-09", "total": 9, "by_action": {"mute": 3, "remove_video": 1}}],
    "records": [{"date": "2026-09-12", "target_type": "user", "action": "mute", "action_label": "禁言",
                 "reason_code": "C101", "reason_label": "骚扰、辱骂", "duration": "24 小时",
                 "appeal": "upheld", "appeal_label": "维持原处罚", "revoked": false}]
  },
  "appeals": {"last_30d": {"filed": 2, "upheld": 1, "overturned": 1}, "open": 0, "rule": "…"},
  "admin_chat_views": {"last_30d": 3, "total": 3, "monthly": [{"month": "2026-09", "views": 3}], "rule": "…"},
  "formula": {"text": "互动分 = …", "source": "server/app/services/video_rank.py",
              "source_url": "https://github.com/hanpaopao66/chaojizan/blob/main/server/app/services/video_rank.py"},
  "not_public": ["被处罚的是谁(账号、昵称、用户名、手机号)", …]
}
```

字段口径见 §7。

## 5. S6:每个处罚都有原因、能申诉、换人复核

- 处罚必须带原因代码,X999 必须写说明;当事人收到系统通知(标题:你被禁言了 / 账号被封禁 / 你的群被封禁 / 消息被删除 / 收到一次警告);
- 一次处罚申诉一次;**处理申诉的人不能是作出处罚的人**(403),和视频申诉、小程序申诉同一条规矩;
- 申诉成立 = 撤销:限制立即解除(执行点按查询判,不用等缓存),封群的会话发解封事件;当事人收到「申诉结果」;
  删消息申诉成立只撤销这条处罚记录,**删掉的内容不恢复**(通知里写明);
- 有待处理的申诉时管理员不能绕过申诉直接撤销(409),免得「原处罚人自己把申诉结了」;没有申诉的处罚,任何管理员都能撤销(写理由,通知当事人)。

## 6. S8:管理员看私聊要留痕

平台技术上能读消息(服务端存储,D3)。规则:

1. 后台看会话消息**只有一个口子** `GET /admin/social/chat-messages?report_id=…`,不带举报单号 403;
   只收 `report_id` 一个参数,会话和 seq 都从举报单里取,调用方传的 `chat_id` / `seqs` 一律不理;
2. 范围 = 举报单里那几条和前后各 5 条(按 seq),不越过举报人提交时的可见下限(清空记录、入群前的历史)——
   举报人自己都看不到的消息,不能借举报单被管理员看到;**公开群 / 频道也按同一个口径**;
3. 每次查看在同一个事务里写一行 `admin_chat_views`(谁、哪张举报单、哪个会话、哪些 seq、什么时候)和一条管理员操作留痕
   (`chat_report.view_messages`,「操作留痕」页能查);举报单被删时这行的举报单号置空,**行不删**;
4. 被举报的是图片、视频时,媒体地址**绑定这张举报单**(`/media/v1/files/{id}?u=…&r=…&e=…&s=…`,1 小时有效),
   下载时再按那张单的范围判一次,地址被转出去也看不到范围外的东西;
5. 查看次数按月公示在透明中心(只有次数,没有会话、没有内容);
6. 举报单详情、队列都不含消息内容;后台页面在查看结果上方写明「本次查看已记录并公示次数」。

## 7. 数据页与透明中心的口径

时间一律按北京时间分天、分月。

| 数 | 口径 |
|---|---|
| 消息数 | 当天发出的消息(不含服务消息;之后被删的也算) |
| 活跃会话数 | 当天有人发过消息的会话数 |
| 投稿量 | 按稿件最近一次提交审核的时间计;同一个稿件改了重交,只算最后那一次 |
| 审核量 / 驳回率 | 审核结论(通过、驳回、改动通过、改动驳回)的条数 / 驳回占比 |
| 审核中位时长 | 结论时间 − 这次结论对应的那次提交(含转码);从 `video_decisions.submitted_at` 有记录起算,之前的结论不参与 |
| 举报量 | 聊天举报 + 视频 / 评论 / 弹幕举报 |
| 处置量 | 对人和会话的处罚(删消息、禁言、封群、封号、警告)+ 视频下架 |
| 管理员查看私聊次数 | `admin_chat_views` 的行数 |

透明中心的处置记录只有这几个字段:

| 字段 | 说明 |
|---|---|
| `date` | 处置日期(北京时间) |
| `target_type` | `user` 人 / `chat` 群或频道 / `video` 视频 |
| `action` | §1 的种类,视频下架是 `remove_video` |
| `action_label` | 中文名 |
| `reason_code` | §5.11 原因代码 |
| `reason_label` | 原因代码的中文 |
| `duration` | 「24 小时」「7 天」「永久」;一次性的处罚和视频下架为空 |
| `appeal` | `""` 未申诉 / `open` 处理中 / `upheld` 维持 / `overturned` 撤销 |
| `appeal_label` | 中文 |
| `revoked` | 是否已撤销 |

**不公开**:被处罚的是谁(账号、昵称、用户名、手机号)、会话名称和成员、消息 / 评论 / 弹幕的内容、举报人是谁、
处罚说明和内部备注、处理人是谁 —— 取数的 SQL 根本不读这些列(`community_stats.public_section`,单测扫它的 SQL)。
推荐 / 热门公式原文直接取 `services/video_rank.FORMULA`(和 DEV-PROMPTS-40 §5.9 逐字一致),附开源仓库里这个文件的链接。

## 8. 注销再注册

注销时还在生效的禁言 / 封号,按 HMAC(手机号 + 角色) 记下(不存手机号明文);同一个号再注册(密码或验证码)时,
**原样挪到新账号上**(同一条处罚改对象,不复制:透明中心的条数不会因此多出来,申诉状态也跟着走,不能借注销再申诉一次)。
和 `risk_carryovers`(风控标记跟随)同一个理由:注销不是洗白按钮。

## 9. 测试与守卫

- `tests/e2e_social_moderation.py`(在 `make test` 的 e2e 链尾部):§4 的每个接口、§2 每个执行点、S6、S8、透明中心不含个人信息、注销再注册;
- `tests/unit/test_sanctions.py`:期限与状态的纯函数、S8 的范围函数、403 detail 的字段、本文 §1–§3、§7 的表和代码对得上、
  封号放行表里每一条都是真实存在的写接口、社交写接口都挂着 `social_user`(封号统一挡得住)、新表没有和钱 / 排序有关的列、
  透明中心取数的 SQL 不碰个人信息的列。
