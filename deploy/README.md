# 部署(内网穿透,全栈自持)

```
用户/App → 域名(云服务器 frps :80/:443)
         → TCP 隧道(frpc,token 认证,本目录 compose 拉起)
         → 部署机 nginx(8880/8443,本目录 compose,TLS 终结)
         → superz-api:8000
```

一台有公网 IP 的云服务器跑 frps 做入口,真正的服务跑在任意一台内网机器上——
家用宽带也能扛住起步期流量,省下云主机钱(这也是"5% 能活"的一部分)。

## 组成

| 文件 | 作用 |
|---|---|
| `docker-compose.prod.yml` | 生产栈:PostGIS + Redis + API + nginx + frpc |
| `.env.prod`(不入库) | `POSTGRES_PASSWORD` / `JWT_SECRET`(`openssl rand -hex 32` 生成)+ 短信/地图等运行配置,经 env_file 全量注入 api |
| `.env.deploy`(不入库) | 开发机侧:`DEPLOY=user@部署机地址`,deploy_server.sh / release_apks.sh 读取 |
| `nginx/conf.d/superz.conf` | 域名分发 + TLS + WebSocket 升级;新域名备案后按注释启用 |
| `tunnel/frpc.toml`(仅部署机) | 隧道配置,含 token,rsync 排除 |
| `certs/`、`letsencrypt/`、`certbot-www/`(仅部署机) | 证书与签发挑战目录,rsync 排除 |
| `renew-cert.sh` | 证书续期(webroot 零停机),crontab 每周一 04:30 |
| `backup.sh` / `restore-drill.sh` | 数据库每日备份 / 恢复演练 |
| `healthcheck-alert.sh` | 探活告警(crontab 每分钟) |

## 日常操作(部署机)

```bash
cd ~/super-z/deploy

# 更新代码后重建(代码由开发机 scripts/deploy_server.sh rsync 推送并自动执行)
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# 看日志
docker logs -f superz-api --tail 100

# 证书续期(cron 自动;手动跑也安全,30 天内到期才真续)
./renew-cert.sh
```

## 首次搭建备忘

1. 云服务器装 frps(:7000 控制口,80/443 转发),token 与 `tunnel/frpc.toml` 一致
2. 域名 A 记录指向云服务器;域名需 ICP 备案(大陆云商未备案会拦 80/443)
3. 首签证书:见 `renew-cert.sh` 头部注释(webroot 模式,经隧道完成挑战)
4. crontab 加续期与探活(示例见各脚本头部注释)
5. `.env.prod` 按 `server/.env.example` 补齐运行配置;
   生产必须设 `ADMIN_PASSWORD_LOGIN=false`、`MOCK_PAY_ENABLED=false`
6. 微信支付密钥手动上传一次(rsync 排除,部署机本地仅存):

```bash
ssh <部署机> "mkdir -p ~/super-z/deploy/wxpay-certs && chmod 700 ~/super-z/deploy/wxpay-certs"
scp server/certs/apiclient_key.pem server/certs/pub_key.pem <部署机>:~/super-z/deploy/wxpay-certs/
```

   compose 把它挂到 api 容器 `/srv/certs:ro`(容器 WORKDIR=/srv),
   所以 `.env.prod` 里写相对路径 `certs/apiclient_key.pem`、`certs/pub_key.pem`。
   密钥缺失时 `get_client()` 记日志返回 None、支付接口 503,不会 500。

## 发版失败的两种"看着成功"

两次都是**退出码骗人**,而不是部署真的成功。都已经修掉,记在这里防止再犯。

### 一、管道吞掉失败(2026-08-19)

```bash
bash scripts/deploy_server.sh | tail -40    # ← 别这么跑
```

管道的退出码取的是**最后一个命令**(`tail`)的。那次 docker build 在
`pip install` 就 exit 2 了(阿里云源读超时),终端显示的却是 `exit 0`。
表现是"部署成功"四个字,线上还是上一版。

现在 `deploy_server.sh` 开头是 `set -eo pipefail`,脚本自身在管道里
不会再被吞掉。但**调用方也别随手接 `| tail`** —— 想看尾部就
`> /tmp/deploy.log 2>&1` 完了再 `tail`,退出码才是真的。

### 二、`timeout` 命令不存在(更早一次)

```bash
timeout 900 bash deploy_server.sh || bash deploy_server.sh    # ← 别这么跑
```

macOS 默认没有 `timeout`(那是 GNU coreutils 的)。`command not found`
返回 127,`||` 接住之后又跑了一遍……也是 127。整条命令 exit 0,
**部署压根没跑**,输出看着还挺正常。

### 构建失败不会弄坏生产

这是唯一的好消息:`docker compose up -d --build` 构建失败时不会替换
正在跑的容器。上面那次失败之后线上仍是上一版、健康检查全绿 ——
只是新版本没上去。所以发现"部署成功但功能没有"时,先查的是
**版本号**(`/health` 里的 `version` 和 `deployed_at`),不是查代码。

pip 那步现在带 `--retries 5 --timeout 60`(见 `server/Dockerfile`),
一次网络抖动不至于报废一次发版。
