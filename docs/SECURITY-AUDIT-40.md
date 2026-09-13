# 消息与视频 · 安全审计记录(DEV-PROMPTS-40 #373)

逐项验证,不是逐项声称:每一条写**守卫在哪**、**怎么弄红过一次**。守卫弄不红的不算守卫。
跑法:单测 `cd server && python -m pytest tests/unit -q`;e2e 对着开发实例
`SUPERZ_API=http://127.0.0.1:8013 DATABASE_URL=… python -m tests.<名字>`,看退出码。

> 弄红的方法都是「把被守的那一行临时改坏 → 跑守卫 → 确认它红了、红在那句断言上 → 改回 → 再跑绿」。
> 同尺寸改动(比如 `all` 换 `any`)要先删 `__pycache__` 或 `touch` 一下源文件:改动在同一秒内、文件大小不变时
> Python 会拿旧的字节码,守卫看起来「弄不红」—— 这次审计就撞上过一回。

## 1. 越权 / IDOR

| 对象 | 守卫 | 弄红 |
|---|---|---|
| 别人的会话、消息、补齐事件、搜索、实时事件、已读名单(S1) | `e2e_chat_private`「S1:C 读、发、补齐、搜索、实时事件,一样都拿不到」;群的已读名单在 `e2e_chat_groups` | #345 开发时 |
| 媒体:发出前只有本人、签名绑人、外人拿不到、删了签名地址一起失效、不能把别人的文件发出去 | `e2e_media` 的 S1 段 | #341 开发时 |
| 别人会话里的「我的会话设置」(草稿、置顶、免打扰) | `e2e_social_idor` 草稿段 | 本次 |
| 别人的分片上传(查进度、传片、完成) | `e2e_social_idor` 分片段 | 本次 |
| 别人还没发出去的媒体状态 | `e2e_social_idor` 媒体状态段 | 本次 |
| 别人的投稿:改、提交、加分 P、创作中心详情、删除;审核中的稿件别人看不到(D10) | `e2e_social_idor` 投稿段;`e2e_video_upload` D10 段 | 本次(投稿段);#358(D10) |
| 私密收藏夹:别人和没登录的看不到、别人改不了 | `e2e_social_idor` 收藏夹段 | **本次**:把 `routers/video.py` `folder_view` 的私密判断改成只判存在 → 断言「私密收藏夹被看到了:200」红;改回绿 |
| 历史、稍后再看、硬币流水、视频设置 | 接口都在 `/video/v1/me/*`,**不收对象编号**,只按当前登录人查 —— 没有可以换的号 | 结构上不存在 |

## 2. 非成员拿事件

`/ws/v2` 只推给会话成员;`POST /chat/v1/sync` 带上不在的会话一律不给。守卫:`e2e_chat_private` S1 段(C 用补齐和实时两条路都拿不到 A、B 的私聊)。

## 3. 媒体直链

- 聊天媒体全在**私密桶**,对象存储不给匿名读;下载只走 `/media/v1/files/{id}`:要么带登录,要么带绑定用户的 HMAC 签名(`services/media.url_sig`),下载时**照样按那个用户判权** —— 签名地址被转出去也没用,人不在会话里就是 404;
- 视频播放地址 `/video/v1/vod/…` 同理,签名绑人;稿件转私密后旧签名地址立刻 404;
- 守卫:`e2e_media`「签名绑人不能改」「把签名地址里的用户换成别人:签名对不上」;`e2e_video_upload`「私密:别人的旧签名地址立刻 404」。

## 4. XSS

- App 和网页版(Flutter)只把消息、群名、视频标题、评论、弹幕当文字画(`Text` / `TextSpan`,实体只改样式),没有任何 HTML 渲染路径;
- 管理后台、开发者后台是 React,默认转义。全仓只有一处 `dangerouslySetInnerHTML`:官网开发者文档页(`web/src/developers/DevelopersPage.jsx`),内容是仓库里平台自己写的 Markdown,不是用户输入;
- 文件类媒体下载一律 `application/octet-stream` + 文件名(`routers/media.get_file`):上传一个改名成 .jpg 的 HTML,也不会在我们的域名下被浏览器当网页执行。守卫:`e2e_media`「改名成 .jpg 的可执行文件按『文件』处理:不预览、强制下载」。

## 5. SSRF(链接预览)

`services/link_preview.safe_fetch`:只许 http / https;DNS 解析出来的**每一个** IP 都必须是公网地址(回环、私网、链路本地含 169.254.169.254、CGNAT、组播、保留段、IPv4 映射的 IPv6 全拒);
**钉住解析出来的 IP 去连**(Host 头、SNI 用原域名,防 DNS 重绑定);不自动跟随跳转,每一跳重判,最多 3 跳;网页 ≤ 1MB、图片 ≤ 2MB 且 ≤ 4000 万像素;整次预览另封 15 秒总时长(本次补:单次读 5 秒超时挡不住每 4 秒吐一个字节的站)。

守卫:`tests/unit/test_link_preview_ssrf.py`(31 条:地址分类、非 http 协议一个请求都不发、解析出内网一个请求都不发、钉 IP、跳到内网那一跳不发、跳转环、截断、类型不对)。
**本次弄红**:把「每个 IP 都得是公网」改成「有一个是公网就行」(`all` → `any`)→「一个公网一个回环」那条红;改回绿。

## 6. 上传

| 风险 | 做法 | 守卫 |
|---|---|---|
| 伪装类型 | 按文件头魔数定类型(`services/media.sniff`),不信扩展名和客户端声明 | `e2e_media` 伪装段 |
| 超大分辨率图片(小文件、解开几百 MB) | **本次修**:分辨率上限(8000 万像素)挪到解码之前 —— 原来 `exif_transpose` 先把整张图解开才判尺寸 | `tests/unit/test_media_decode_guard.py`;**弄红**:改回原顺序,「超限的图在判尺寸之前就被解码了」红 |
| 超大分辨率视频 / GIF | **本次补**:ffprobe 只读头,长边 > 8192 或总像素 > 3600 万直接 422,不进转码 | 同上文件 `test_video_resolution_cap` |
| 压缩炸弹 | 服务端**从不解压**用户上传的压缩包(文件原样存、原样给);会被解码的只有图片和音视频,各有上限 | 结构上不存在 |
| 超大文件、刷存储 | D8 单文件上限;每人每天 2GB 配额;分片上传 24 小时不完成就清 | `e2e_media` 配额段、分片段 |
| EXIF 定位泄露 | 图片一律重新编码,EXIF 丢掉 | `e2e_media`「EXIF 定位去掉了」 |

## 7. 限流

§5.7 那张表逐项落在代码里(`ratelimit.check_*`);守卫分散在各自的 e2e:发消息频率与慢速模式(`e2e_chat_groups`)、同样文字群发 20 个私聊暂停 1 小时(#369,`e2e_chat_groups`)、评论与弹幕频率(`e2e_video_comments`、`e2e_danmaku`)、按手机号找人每天 20 次(`e2e_social_profile`)。

## 8. WebSocket 鉴权

token 不许放 URL(会进访问日志);连上 5 秒内没有 auth 帧就 4401 断开;错 token 4401。守卫:`e2e_chat_private` 第一段。

## 9. Bot token 泄漏

见机器人平台合并时补的这一节(库里只存 sha256,日志和后台只出现前 6 位,有守卫断言日志里没有完整 token)。

## 10. S1–S10 的守卫

| 不变量 | 守卫 |
|---|---|
| S1 私密内容只给参与者 | `e2e_chat_private`、`e2e_media`、`e2e_social_idor` |
| S2 手机号不外露 | `e2e_social_profile`、`e2e_video_me`(探测器先对自己的号验过能认出来) |
| S3 不卖流量 | `tests/unit/test_video_rank.py`(模型列名、排序函数的输入) |
| S4 不收钱 | `tests/unit/test_video_invariants.py` 的 `test_s4_*`、硬币来源两条 |
| S5 用户的数据用户说了算 | `e2e_chat_export`(导出只本人能下、注销后消息和媒体对别人消失;**本次弄红**:去掉注销时的清理那一步,「消息对方还看得见」红)、`e2e_video_upload` S5 段、`e2e_account_delete` |
| S6 处罚有原因、能申诉、换人复核 | 视频:`e2e_video_upload` S6 段;消息侧处罚与申诉见社区治理合并时补的 `e2e_social_moderation` |
| S7 拉黑立即生效、双向隔离 | `e2e_social_profile`、`e2e_video_comments`、`e2e_danmaku`、`e2e_calls` |
| S8 管理员看私聊要留痕 | 见社区治理合并时补的 `e2e_social_moderation` |
| S9 个性化可以一键关闭 | `e2e_video_feed` |
| S10 消息不丢、不重、有序 | `e2e_chat_private`(并发发送、重复 random_id、断线补齐与 reset) |
