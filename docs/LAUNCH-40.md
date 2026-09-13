# 消息与视频 · 上线手册(DEV-PROMPTS-40 #375)

这一批上线分两步:**先上消息**(聊天、群、频道、贴纸、导出、机器人框架默认关着),**视频、通话、机器人等合规结论**
(见 [COMPLIANCE-40.md](COMPLIANCE-40.md))。代码一次发完,生产靠开关控制开放范围 —— 开关缺省全部站在「关」这一边,
不经意的一次部署不会把没拿到许可的功能放出去。

## 1. 开关

后台「开关」页(`/admin/flags`)拨,**立即生效、不用发版**。没写过的开关按下表缺省:

| 开关 | 管什么 | 开发 / CI 缺省 | 生产缺省 | 什么时候开 |
|---|---|---|---|---|
| `chat_enabled` | 整个「消息」(`/chat/v1` 全部,含贴纸、通话记录) | 开 | **开** | 急停用:出事时关掉,通知和订单消息不受影响 |
| `calls_enabled` | 语音 / 视频通话(呼叫、ice-servers) | 开 | **关** | 电信业务许可有结论、coturn 部署好之后 |
| `video_enabled` | 整个「视频」(`/video/v1` 全部) | 开 | **关** | 拿到《信息网络传播视听节目许可证》之后 |
| `video_upload_enabled` | 视频投稿(建稿、加分 P、提交、传原片) | 开 | **关** | 同上,且审核人手到位 |
| `bots_enabled` | 机器人平台(Bot API、开发者后台建机器人、内联键盘回调) | 开 | **关** | 第三方开发者责任条款定稿之后 |
| `media_transcode` | 转码急停(关掉时任务只排队不执行) | 开 | 开 | 机器被转码压垮时临时关 |

- 判「开发」的依据是 `APP_ENV=dev`;拼错、留空、写成 staging 一律按生产算(`services/flags.video_flag_default`);
- `/config` 的 `features` 把 chat / calls / video / video_upload / bots 下发给客户端,关着的入口直接收起(电话按钮、「我的」页视频块);
  服务端照样兜底回 503,客户端只是不让人点进去才知道。

## 2. 迁移

`0125_social_identity` → `0126_chat` → `0127_media` → `0128_video` → `0129`(机器人)→ `0130`(社区治理)。
由 compose 里一次性的 `migrate` 容器跑(`python -m app.startup`,带 PostgreSQL 咨询锁),api / sweeper / media-worker 都等它成功再起。
全是新表和新列,不改老数据;回退代码时新表留着不碍事(见 §7)。

## 3. compose 变化(`deploy/docker-compose.prod.yml`)

- **新增 `media-worker`**:`python -m app.workers.media`,转码队列在 Redis(`media:jobs`,BLMOVE 到「进行中」,做完才删,重启先挪回),
  限 2 核 / 1.5G;api、sweeper 设 `MEDIA_WORKER=external` 只排队不转;
- **api 开 `MEDIA_ACCEL=true`**:私密媒体和视频判完权回 `X-Accel-Redirect`,nginx 从 MinIO 直出(Range、拖进度条不经过 Python);
- 只能有一份的循环一律在 sweeper:视频定时发布、定时消息(5 秒一轮)、过期分片上传清理;
- **机器人 webhook 投递是例外,跟着 api 进程跑**(`services/bot_webhook.py`,#355):新更新提交之后当场推,不能等清扫的节奏,
  而且 CI / 本地 `AUTO_FLOW_ENABLED=false` 时也得能投。多个 api 进程时同一个机器人靠 Redis 锁只有一处在投、按 update_id 顺序;
  不想让某个进程投就给它设 `BOT_WEBHOOK_ENABLED=false`。

## 4. nginx(`deploy/nginx/conf.d/superz.conf`)

- `/ws/v2`:走现有 `location /` 的 WebSocket 升级(`Upgrade` / `Connection` 头、读超时 1 小时),不用另配;
  客户端每 25 秒一个 ping,服务端 60 秒收不到就断,1 小时的读超时只是上限;
- **新增 `/_minio_internal/`(internal)**:只认 api 发出来的内部跳转,浏览器直接请求一律 404;
  `Host` 必须和签名时的 endpoint 一字不差(`MINIO_ENDPOINT`,缺省 `minio:9000`),不然 MinIO 回 403 SignatureDoesNotMatch;
- `client_max_body_size 10m` 不用改:整块上传 ≤ 10MB,大文件走 4MB 一片的分片上传。

上线后验一下直出:登录后打开一个聊天视频,`curl -I` 它的签名地址应该是 200 / 206 且带 `Accept-Ranges: bytes`;
直接请求 `https://域名/_minio_internal/…` 应该是 404。

## 5. coturn(开通话时才需要)

**跑在有公网 IP 的云服务器(frps 那台)上,不在部署机的 compose 里** —— 部署机在内网、经 TCP 隧道对外,
而 TURN 要一段 UDP 端口直接暴露在公网。配置样例和启动命令见 `deploy/coturn/turnserver.conf.example`:

- 安全组放行 `3478/udp`、`3478/tcp`、`49160-49200/udp`(一通电话占两个中继端口);
- REST 共享密钥方案:部署机 `.env.prod` 写 `TURN_URLS` / `STUN_URLS` / `TURN_SECRET`,api 给客户端发 1 小时有效的临时凭据,密钥本身从不下发;
- 样例里 `denied-peer-ip` 拒掉了全部内网段:TURN 被当跳板打内网是这类服务最常见的事故,别删。

不配 TURN 时只有 STUN:同一个局域网能通,跨运营商、对称 NAT 多半打不通 —— 所以通话开关缺省关。

## 6. 容量预估(对象存储)

| 内容 | 估算 |
|---|---|
| 聊天图片 | 长边限 2560、JPEG 90,一张平均 400KB;1 万活跃用户 × 每天 5 张 ≈ 20GB / 天 |
| 聊天视频 / 文件 | 单个 ≤ 100MB,每人每天 2GB 配额封顶;按 1% 的人每天发一个 30MB 视频 ≈ 3GB / 天 |
| 视频投稿 | 原片留一份 + 360 / 480 / 720 / 1080 四档(不超过原片的档位);一分钟 1080p 投稿全档合计约 1.5 × 原片;按每天 50 个、平均 3 分钟 ≈ 15GB / 天 |
| 导出包 | 每人只留最新一份,24 小时一次,封顶 2GB |

部署机现在是单盘 MinIO:**视频开关打开前要先扩盘**,或把视频桶挪到云对象存储(`STORAGE_BACKEND` 相关配置,
存储层接口不变)。备份:`backup-minio.sh` 每天把两个桶整个镜像到宿主机目录 —— 视频打开后备份量会跟着陡增
(原片 + 各档转码产物),开之前先评估备份盘,或者约定转码产物不备份(丢了能从原片重转)。

## 7. 回退

1. 先拉开关:出问题的功能关掉(`chat_enabled` / `video_enabled` / `calls_enabled` / `bots_enabled` / `media_transcode`),立即生效;
2. 代码回退:`scripts/deploy_server.sh` 部署上一个版本;**迁移不回滚** —— 新表、新列对老代码是透明的
   (老代码不读它们),`alembic downgrade` 会删掉用户已经发出去的消息,不做;
3. media-worker 回退时队列里的任务不会丢(在 Redis 里),新版本起来接着转;
4. 回退后 `MEDIA_ACCEL=true` 仍然安全:老版本 api 不认这个变量,照旧自己流式返回。

## 8. 上线前核对

- [ ] `.env.prod`:`APP_ENV` 是 `prod`(或不写);`TURN_*` 只在开通话时才配
- [ ] 后台开关页确认:`calls_enabled`、`video_enabled`、`video_upload_enabled`、`bots_enabled` 显示「关」
- [ ] `docker compose ps`:migrate 退出码 0;api、sweeper、media-worker、minio、nginx 在跑
- [ ] 两个真实账号互发一条文字、一张图、一段语音;群里 @ 一下;频道发一条
- [ ] 签名地址直出 200 / 206;`/_minio_internal/` 直接访问 404
- [ ] 注销一个测试号,确认它发过的消息对对方消失、图片地址 404(S5)
- [ ] 透明中心「社区」栏能打开,数字是 0 也要能打开
