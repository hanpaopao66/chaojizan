# 小程序开放平台上线手册(DEV-PROMPTS-39 #337)

按顺序做,每一步都能单独停下、单独回退。**改生产数据的步骤(标 ⚠)跑之前要先征得同意**;
部署一律走 `scripts/deploy_server.sh`,nginx 最后重启(见部署机的延迟 502 那条经验)。

## 0. 现状(2026-09-12)

- 代码:服务端、SDK 2.0.0、用户端容器 v2、开发者后台 `/dev/`、审核后台、官网 `/developers` `/miniapps` `/m/<appid>`、
  透明中心「小程序」栏都在仓库里,本地和开发库上验证过(见 [安全审计记录](MINIAPP-SECURITY-AUDIT.md));
- 生产:服务端和 App 从 v0.17.0 起带上开放平台的代码,但 `mini_apps` 表是空的 —— 用户端下拉抽屉没有条目,手势就退回成下拉刷新;签名密钥(`MINI_APP_SIGNING_KEY`)还没配;
- 托管域名(D1)2026-09-12 定为主站下专门的一级 `mp.chaojizan.cc`(不另买域名,见 2.1);解析、泛域名证书、签名密钥都还没做。

## 1. 先修现在的问题(不等托管域名)

目标:新老版本 App 下拉都能打开透明中心和公开账本(外部地址条目,桥 v1 兼容)。

1. 部署服务端:容器启动时自动跑迁移 `0124_miniapp_platform`。**这条迁移会写一行数据**:建一条「官方开发者」
   (没有账号,`is_official`,公司名陕西爱卡斯科技有限公司),并把存量 `mini_apps` 条目挂到它名下 —— 生产存量是 0 条。
   迁移有 downgrade(本地 up → down → up 验过);
2. **先配签名密钥,再插条目**:`.env.prod` 加 `MINI_APP_SIGNING_KEY`(生成和离线备份见 2.3),重建 api 容器。
   新版 App(0.17.0 起,容器 v2)打开**任何**条目都走 v2 启动、签 initData,外部地址条目也一样;
   没配密钥时新版 App 点开会报「小程序签名密钥未配置」(503),老版本 App 走 v1 不受影响。
   验:`curl https://chaojizan.cc/.well-known/superz-webapp-keys.json` 返回带 kid 的公钥,不是 503;
3. ⚠ 插入两条自家条目(幂等,重复跑不会多插):

   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod exec api python -m scripts.seed_official_miniapps          # 先看会做什么
   docker compose -f docker-compose.prod.yml --env-file .env.prod exec api python -m scripts.seed_official_miniapps --apply  # 真做
   ```

4. 验:新老版本 App 下拉都出现「透明中心」「公开账本」两条,点开能用;`/mini-apps/catalog` 匿名能看到这两条。

回退:把两条条目下架(管理后台「小程序治理 → 应用与处罚」,或 `POST /mini-apps/admin/{id}/toggle`)。

## 2. 基础设施(托管第三方代码之前必须有)

### 2.1 托管域名(D1):`mp.chaojizan.cc`

2026-09-12 定:不另买域名,用主站下专门的一级。每个应用一个子域名 `<appid>.mp.chaojizan.cc`,
`.env.prod` 配 `MINI_APP_HOST_DOMAIN=mp.chaojizan.cc`。

- **不能配成 `chaojizan.cc` 本身**,也不能把小程序放在主站的路径下(`chaojizan.cc/xxx/`):
  那样第三方的代码和主站同一个 origin,能直接读写主站页面里的登录令牌。代码里有防护 ——
  配成主站本身或它的上级会被当成没配(托管小程序打不开,主站照常,日志里有一条 error),
  见 `services/miniapp_platform.host_domain` 和对应单测;
- 和单独买域名比,省了买域名和备案(chaojizan.cc 已备案,子域名不用再备;用途变化要不要报备见
  [合规清单](MINIAPP-COMPLIANCE.md) 第 2 条);**多出来的三个风险**写在
  [安全审计记录](MINIAPP-SECURITY-AUDIT.md)的「放在 chaojizan.cc 下面的代价」:cookie 塞满让主站在这个浏览器里打不开、
  地址看着像官方页面、审核预览和网页版宿主里的托管页可能和主站页面同一个进程;
- 泛域名解析:加一条 `*.mp.chaojizan.cc` 的 A 记录,指向和 `chaojizan.cc` 同一个云服务器 IP。
  frp 是 TCP 转发(`deploy/tunnel/frpc.toml.example`),不看域名,**云服务器那边不用改**;
- **证书(2026-09-15 起)**:先不签泛域名证书,用 `deploy/mp-cert.sh` 按库里的托管应用签一张**多域名证书**
  (`mp.chaojizan.cc` + 每个托管应用的 `<appid>.mp.chaojizan.cc`),走 HTTP-01 webroot —— 和 `renew-cert.sh`
  同一套 certbot 容器、同一个 `certbot-www` 目录。能这么签是因为泛解析已经指到云服务器、frp 是 TCP 直通、
  nginx 80 端口的 `server_name _` 会答任何子域名的验证请求(当天实测过)。好处是不用把阿里云的 DNS 密钥放到部署机上;
  - 新发布了托管应用(官方脚本或开发者后台)就在部署机上再跑一次 `bash ~/super-z/deploy/mp-cert.sh`:
    新 appid 进证书、nginx 热重载;没变化又没到期就什么都不做;
  - 续期交给 `renew-cert.sh`(`certbot renew` 一起续;脚本第一次签完会把 `mp.chaojizan.cc` 写进 `.domains.local`,
    续好的证书才会拷进 `certs/mp/`);
  - `conf.d/mp.conf` 引用的证书不存在时 nginx 起不来、整站都挂,所以 `deploy_server.sh` 在起容器之前先跑
    `mp-cert.sh --placeholder-if-missing`,没有证书就放一张 30 天的自签名占位;
  - **一张证书最多 100 个域名**。托管应用多到接近这个数(或者第三方应用发布频繁、等不了手动跑脚本),就换成
    **DNS-01 泛域名证书** `*.mp.chaojizan.cc` + `mp.chaojizan.cc`:用 acme.sh 或 certbot 的 DNS 插件接阿里云解析的 API
    (建一个只有 DNS 权限的 RAM 子账号,密钥由人自己配在部署机上),续期另排一条 cron,证书照样放 `deploy/certs/mp/`。
    **别把 `*.mp…` 加进 renew-cert.sh 的 DOMAINS**(那个脚本按域名首段起目录名,`*.mp…` 会得到 `*`)。

### 2.2 nginx

主域名 chaojizan.cc **不用改**:`/.well-known/assetlinks.json`(App Links)、`/.well-known/superz-webapp-keys.json`(平台公钥)
走现有的 `location /` 到 api;主域名上的 `/_mini-host/…` 由 api 自己在生产挡成 404。

托管域名加两个 server 块(证书到位之后再加进 `deploy/nginx/conf.d/`;证书路径不存在 nginx 起不来,整站都会挂):

```nginx
# 小程序托管域名:整站只做一件事 —— 原样交给 api,由 MiniHostMiddleware 按 Host 头认 appid
# (严格正则:大小写变体、带端口、多一级子域名一律 404)。
# **不在 nginx 缓存**:入口 HTML 要每次回源,紧急隔离才能立刻生效;其余文件地址带版本号、
# 返回头是 immutable,浏览器自己会长缓存。以后真要加 proxy_cache,键必须含 $host(appid 在子域名里)
server {
    listen 443 ssl;
    server_name *.mp.chaojizan.cc;
    ssl_certificate     /etc/nginx/certs/mp/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/mp/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 1k;              # 托管站点只读,不收请求体

    location / {
        limit_except GET HEAD { deny all; }
        resolver 127.0.0.11 valid=10s ipv6=off;
        set $api_upstream http://superz-api:8000;
        proxy_pass $api_upstream;
        proxy_set_header Host $host;      # 靠它认 appid,不能改成 $proxy_host
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_hide_header Set-Cookie;     # 托管站点永远不该种 cookie
    }
}

# 裸托管域名不出任何东西
server {
    listen 443 ssl;
    server_name mp.chaojizan.cc;
    ssl_certificate     /etc/nginx/certs/mp/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/mp/privkey.pem;
    return 404;
}
```

### 2.3 配置(`.env.prod`,不入库)

| 变量 | 值 | 说明 |
|---|---|---|
| `MINI_APP_HOST_DOMAIN` | `mp.chaojizan.cc`(不带 `*.`) | 不配时生产上托管应用启动不了、托管文件 404;配成 `chaojizan.cc` 会被忽略,效果同不配 |
| `MINI_APP_SIGNING_KEY` | 32 字节种子的 base64url | initData 的平台 Ed25519 私钥。生成见下;**离线备份两份**(纸 + 离线介质),丢了开发者后端用 signature 验签的全部失效 |
| `MINI_APP_PREVIOUS_PUBLIC_KEYS` | 空 | 轮换签名钥时把旧公钥写这里,继续发布一段时间 |
| `MINI_APP_FRAME_ANCESTORS` | App 网页版的 origin | 托管页 CSP 的 frame-ancestors 额外放行的 origin(逗号分隔);主站 `PUBLIC_BASE_URL` 总是放行 |
| `PUBLIC_BASE_URL` | `https://chaojizan.cc` | 已有;直达链接、CSP 报告地址用它 |

```bash
python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('='))"
```

对象存储:托管包放在**现有的私有桶**下 `miniapps/<appid>/<版本>/` 前缀(执行时没有另开 `superz-miniapps` 桶,
见 DEV-PROMPTS-39 执行记录);图标、截图走公开桶(和商家图片一样经 `/img/` 出)。

### 2.4 上生产后按这个清单验一遍

安全审计里 Host 头、frame-ancestors、主域名挡内部路径这几条,本地是按生产配置跑的单测,上线后在生产上再验
(`<版本 id>` 是版本记录的 id,不是版本号,启动应答里的 `url` 就是这个形状):

```bash
curl -s -D - -o /dev/null https://<appid>.mp.chaojizan.cc/v/<版本 id>/index.html | grep -iE 'content-security|permissions-policy|cache-control|set-cookie'  # 没有 set-cookie(托管路由只接 GET,HEAD 回 405,别用 -I)
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: x.<appid>.mp.chaojizan.cc' https://<appid>.mp.chaojizan.cc/v/<版本 id>/index.html   # 404:多一级子域名
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<appid>.mp.chaojizan.cc/v/<版本 id>/index.html   # 403 或 404
curl -s -o /dev/null -w '%{http_code}\n' https://mp.chaojizan.cc/                                     # 404
curl -s -o /dev/null -w '%{http_code}\n' https://chaojizan.cc/mini-apps/catalog                        # 200:主站没被托管吞掉
curl -s -o /dev/null -w '%{http_code}\n' https://chaojizan.cc/_mini-host/<appid>/v/<版本 id>/index.html # 404
curl -s https://chaojizan.cc/.well-known/assetlinks.json          # 指纹和正式签名证书一致
curl -s https://chaojizan.cc/.well-known/superz-webapp-keys.json  # 有 kid,和 MINI_APP_SIGNING_KEY 对应
```

CSP 头里的 `frame-ancestors` 不能有 `*`。

大写的 appid(`SZ…`)在生产上是 200 而不是 404:nginx 转给 api 的是 `$host`,它总是转成小写,大写变体到不了
MiniHostMiddleware;浏览器也把大小写不同的主机名当同一个 origin,所以这不是隔离上的漏洞。中间件那条严格正则由单测守着。
(2026-09-15 第一次上生产时照这个清单验过:其余几条都和预期一致。)

## 3. 上线顺序

1. **服务端**(迁移 + 新接口;老接口行为不变,老版本 App 只看得到外部地址条目);
2. **新版 App**(容器 v2)走正常的发版流程;
3. ⚠ **上传官方小程序**(托管域名、签名密钥都到位之后;发布完在部署机上跑 `bash ~/super-z/deploy/mp-cert.sh`,
   把新 appid 签进证书 —— 签之前那几分钟,目录里已经有它但打不开):

   ```bash
   bash scripts/build_miniapp.sh notepad     # 打印的 SHA-256 要和上线后详情页公示的一致
   bash scripts/build_miniapp.sh 2048
   # 把两个 zip 和 listing.json 拷进 api 容器(docker cp),在容器里先不带 --apply 看一遍,再真做
   python -m scripts.publish_official_miniapp /tmp/notepad.zip --listing /tmp/notepad-listing.json --reviewer <管理员手机号> --apply
   python -m scripts.publish_official_miniapp /tmp/2048.zip --listing /tmp/2048-listing.json --reviewer <管理员手机号> --apply
   ```

   脚本走和开发者后台同一套校验器、状态机、审核记录(审核人 = 指定的管理员,内部备注「官方应用,脚本发布」),不开后门。
   **官方小程序把 SDK 打进了自己的包里**:SDK 一改,两个包和它们的 SHA-256 都要重打重发;
4. **开发者注册对所有人开放**:`developer_signup` 缺省就是 `open`,小程序、小游戏谁都可以注册,不用邀请;
5. 盯着审核队列(积压、中位时长)。上架前本来就要过审核,注册开放不等于上架开放;
   审核真的扛不住或者有人批量注册捣乱,再到「小程序治理 → 开发者注册」临时切成「仅限邀请」或「暂停注册」。

## 4. 开关(出问题先关开关,再查原因)

前三个在管理后台「平台开关」页,改动带原因进透明中心的治理时间线;开发者注册在「小程序治理」页:

| 开关 | 缺省 | 关了会怎样 |
|---|---|---|
| `miniapp_hosted` 托管小程序 | 开 | 托管应用启动回 4009、开着的一分钟内被宿主关掉、托管文件 404、从目录和最近使用消失;外部地址条目不受影响 |
| `miniapp_catalog` 小程序目录 | 开 | 目录只列官方小程序;第三方应用只能从直达链接和用户自己的最近使用进 |
| `miniapp_profile` 读取昵称头像 | 开 | profile 能力对所有应用当场收回,requestProfile 回 4001 |
| `developer_signup` 开发者注册 | 开放注册 | 在「小程序治理 → 开发者注册」改:开放 / 仅限邀请 / 暂停(已有开发者照常登录) |

## 5. 回滚

- 应用级:开发者后台或审核后台「回滚到这个版本」,一键回到任一发布过的版本;单个版本有问题用「紧急隔离」,立即 404;
- 平台级:关上面的开关;
- 代码级:回滚部署;迁移 0124 有 downgrade(会删掉新表和新列,**小程序开发者、版本、云存储数据一并删除**,
  非不得已不要 downgrade,先关开关)。
