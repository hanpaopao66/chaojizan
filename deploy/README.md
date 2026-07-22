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
5. `.env.prod` 按 `server/.env.example` 补齐运行配置
