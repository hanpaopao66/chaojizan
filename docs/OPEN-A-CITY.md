# 开城手册:把这套平台部署到你的城市

读者假设:你会用 Docker 和 Linux 命令行,没读过这个仓库的代码,
也联系不上我们。目标:照本文从零起一套自己的实例,并知道每一步花什么钱、
办什么证、错了怎么看出来。

诚实声明:本手册的命令与配置对照仓库代码和 CI 逐条核过;
CI(`.github/workflows/ci.yml`)每次提交都在干净机器上走一遍
「起库 → 迁移 → 灌数据 → 起服务 → 130 套 e2e」,那是被反复验证的黄金路径。
但「一个陌生人在全新 VPS 上照本文走通」这件事本身,截至 2026-08 还没有
第三方做过 —— 你就是第一个,卡在任何一步都请开
[部署求助 issue](https://github.com/hanpaopao66/chaojizan/issues/new/choose),
**卡住本身就是手册的 bug**。

## 0. 要花多少钱、办什么证(先看这节再动手)

### 钱(官方实例的真实数字,2026-08 口径)

| 项 | 金额 | 说明 |
|---|---|---|
| 服务器 | 一台 2C4G VPS 约 ¥60–100/月 | 全栈(PostGIS+Redis+API+MinIO+nginx)单机跑得动起步期;官方实例更省:业务跑在家用宽带的旧电脑上,云端只买了一台最便宜的机器做入口(见第 5 步的两种拓扑) |
| 域名 | ¥30–60/年 | 大陆机房必须 ICP 备案(免费,走云商流程 1–3 周) |
| 短信 | 约 ¥0.045/条 | 阿里云,充 ¥100 够起步期用很久 |
| 地图 | ¥0 | 腾讯位置服务个人开发者免费额度足够起步 |
| TLS 证书 | ¥0 | Let's Encrypt,脚本自动续期 |
| 微信支付 | ¥0 手续费另计 | 商户号免费,微信收单费率 0.6% 另算(不在平台 5% 里) |

**合计:每月一百多块钱跑一个城市。** 这个数字本身是「5% 能活」的证据之一。

### 证(按办理耗时倒序,先启动慢的)

| 资质 | 去哪办 | 耗时 | 没有它会怎样 |
|---|---|---|---|
| ICP 备案 | 域名所在云商的备案系统 | 1–3 周 | 大陆机房 80/443 被拦,站开不了 |
| 微信支付商户号 | pay.weixin.qq.com,需营业执照(个体户可) | 数天 | 收不了真钱;平台照常跑模拟支付,可以先开城后接支付 |
| 短信签名+模板 | 阿里云短信控制台,签名需资质证明 | 1–3 天 | 验证码发不出,用户登录不了(生产必须有) |
| 腾讯地图 Key | lbs.qq.com,个人可申请 | 当天 | 地址搜索是演示数据、地图无底图 |
| 极光推送 | jiguang.cn | 当天 | 离线推送没有;App 在前台仍能收单(可后补) |

平台业务合规(外卖平台本身的资质、入驻商家的食品经营许可审核义务等)
因城因规模而异,本手册不替你回答 —— 上线真实交易前请自行咨询当地市监。

## 1. 本地先跑通(半天,强烈建议不要跳)

在自己电脑上把全链路跑一遍,你会知道每个组件长什么样,
之后在服务器上出问题才分得清「配错了」和「本来就这样」。

```bash
git clone https://github.com/hanpaopao66/chaojizan.git && cd chaojizan
docker compose up -d          # PostGIS + Redis + MinIO + api 全容器
```

等一分钟(api 启动时自动跑数据库迁移),然后灌演示数据:

```bash
docker compose exec api python -m scripts.seed
```

验收:

- `http://localhost:8000/docs` 能打开接口文档;
- `http://localhost:8000/admin` 用 13800000000 / 123456 登录管理后台;
- 演示账号(用户 13800000001、商家 13800000002、骑手 13800000003,
  密码均 123456)在三端 App 里能登录 —— 装了 Flutter 的话
  `cd apps/user_app && flutter run` 直连本机。

注意:Python 版本 3.11(Dockerfile 与 CI 同款);源码方式跑后端见根
README「快速开始」。

## 2. 准备服务器与域名

1. 买 VPS(2C4G 起步),装 Docker 与 docker compose 插件;
2. 域名 A 记录指向服务器公网 IP,启动 ICP 备案(等备案期间可以做完
   下面所有步骤,用 IP + 自签证书先联调);
3. 检查 `/etc/docker/daemon.json` 配了国内 registry 镜像源
   (官方源在大陆服务器上经常超时;Dockerfile 内的 apt/pip 已默认阿里云源)。

## 3. 改掉「官方实例专属」的常量

这套代码开源,但有六处写着我们自己的名字,**照抄会把你的用户引到我们这来**:

| 位置 | 改什么 |
|---|---|
| `deploy/nginx/conf.d/superz.conf` | 所有 `chaojizan.cc` 换你的域名;证书目录 `certs/chaojizan/` 换 `certs/<你的域名首段>/`(renew-cert.sh 按域名首段命名) |
| `deploy/renew-cert.sh` 的 `DOMAINS=(...)` | 换你的域名 |
| `.env.prod` 的 `PUBLIC_BASE_URL` | 你的域名(短链/海报二维码全用它拼) |
| `.env.prod` 的 `SMS_SIGN_NAME` / `SMS_TEMPLATE_ID` | 你自己审核过的签名与模板(默认值是我们的,发不出你的短信) |
| `.env.prod` 的 `GITHUB_REPO` | 你 fork 后的仓库名(工程透明页展示用) |
| `deploy/docker-compose.prod.yml` 两处 `/home/dddd/super-z/...` 卷路径 | 换成你部署机上的实际路径(appdist 与 witness 两个挂载) |

品牌与 App 名称也请换成你自己的(CONTRIBUTING「把它带到你的城市」有说明)——
AGPL 给的是代码,不是「超级赞」这块牌子。

## 4. 填配置

```bash
cd deploy
cp .env.prod.example .env.prod && chmod 600 .env.prod
```

`.env.prod.example` 里每一项都有注释,这里只强调四件事:

1. **compose 层必填 4 项**(`POSTGRES_PASSWORD` / `JWT_SECRET` /
   `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`)—— 缺一个 `up` 直接报错,
   这是故意的,别绕;
2. **`JWT_SECRET` 首次上线后不可再换**:收款账户等密文默认由它派生加密,
   换了全解不开。想保留换的自由,首次部署就单独配 `CRYPTO_KEY`;
3. **MinIO 两组凭据要手动对齐**:`MINIO_ROOT_*` 给容器,
   `MINIO_ACCESS_KEY/SECRET_KEY` 给 api,值要一致;
4. **生产两开关**:`ADMIN_PASSWORD_LOGIN=false`、`MOCK_PAY_ENABLED=false`。
   忘了的话第 7 步的自检会红灯,但不会拦你启动 —— 责任在你。

微信支付可以先全空着(平台自动走模拟支付,收真钱前按
[WXPAY-SETUP.md](WXPAY-SETUP.md) 一步步来,那份文档含证书摆放和三个最常见的坑)。

## 5. 起栈

两种拓扑,先想清楚你是哪种:

**A. 服务器有公网 IP(多数人)**:不需要 frp。
`docker-compose.prod.yml` 里删掉(或注释掉)`frpc` 服务,
把 nginx 的端口发布 `8880:80`/`8443:443` 改成 `80:80`/`443:443`,完事。

**B. 业务机在内网、云端只做入口(官方实例的省钱拓扑)**:保留 frpc,
照 `deploy/tunnel/frpc.toml.example` 配隧道(注释里含云端 frps 侧的最小配置)。

然后:

```bash
cd deploy
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

首次签证书(备案通过后;命令是 renew-cert.sh 头注释那条,域名换成你的):

```bash
docker run --rm -v $PWD/letsencrypt:/etc/letsencrypt -v $PWD/certbot-www:/var/www/certbot \
  certbot/certbot certonly -n --webroot -w /var/www/certbot -d 你的域名 \
  --register-unsafely-without-email --agree-tos
./renew-cert.sh        # 把证书拷到 nginx 目录并 reload
```

数据库迁移**不用手动跑**:api 启动时自动执行(没有 alembic 状态的库会先打基线)。

商家网页工作台要单独构建一次(后端托管构建产物,没构建则 /merchant 返回提示):

```bash
cd ../merchant-web && npm ci --registry https://registry.npmmirror.com && npm run build
```

## 6. 灌基础数据

```bash
docker exec superz-api python -m scripts.seed
```

⚠️ 生产环境(`STORAGE_BACKEND=minio`)下,seed 会把演示账号的密码
**随机生成并只在输出里打印一次** —— 记下来。这是故意的:
宁可你登不进演示账号回来查文档,也不留一个人人可登的后门。

想要一批带图的演示店面撑门面(可选):`python -m scripts.demo_seed`;
之后清掉用 `python -m scripts.scrub_demo`(注意:清演示数据会清空账本锚点、
公开账本从头起链,开真实交易之后就别再跑它)。

## 7. 验收:跑通一单 + 自检全绿

1. **自检**:`ADMIN_TOKEN=<管理后台登录后的 token> ./readiness.sh` ——
   12 项外部依赖逐项报「配没配、没配会怎样」。起步期至少要绿:
   `mock_pay_disabled`、`sms`、`storage_minio`、`tencent_map`;
2. **走一单**:用户端下单(模拟支付关了的话,先在测试商户里走一分钱真实支付)
   → 商家端接单出餐 → 骑手端抢单送达 → 用户确认 → 打开「钱去哪了」
   看这一单的分账。这条链路通了,状态机、结算、账本就都通了;
3. **看账本**:次日检查 `https://你的域名/ledger/anchors` 出现了第一天的锚点 ——
   你的城市从这一刻起有了自己的公开账本链(和官方实例是两条独立的链);
4. **装监控**:crontab 加四条(部署机):

```
* * * * *  ~/super-z/deploy/healthcheck-alert.sh     # 探活告警(配 WEBHOOK_URL 才有用)
10 3 * * * ~/super-z/deploy/backup.sh                # 数据库每日备份
0 4 * * *  ~/super-z/deploy/backup-minio.sh          # 对象存储每日备份
30 4 * * 1 ~/super-z/deploy/renew-cert.sh >> ~/super-z/deploy/renew.log 2>&1
```

第一个月内跑一次 `restore-drill.sh`(恢复演练)——
没演练过恢复的备份等于没有备份。

## 8. 日常运维速查

| 事 | 命令 / 文件 |
|---|---|
| 更新代码后重建 | `docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`,**然后必须 `docker compose ... restart nginx`**(nginx 缓存旧容器 IP,不重启十几分钟后全站 502 —— 我们用一次生产事故换来的教训) |
| 看 api 日志 | `docker logs -f superz-api --tail 100` |
| 发 App 版本 | `scripts/release_apks.sh`(需要 Flutter 环境与签名钥匙,见脚本头注释) |
| 深入细节 | [deploy/README.md](../deploy/README.md)(官方实例的运维手册,frp 拓扑、备份、证书都在) |

## 9. 别照抄我们的部分(再强调一遍)

- **frp 内网穿透**是我们省钱的选择,有公网 IP 直接跑更简单(第 5 步 A);
- **佣金等承诺数字**:三原则(5% 封顶、配送费全归骑手、账目透明)是这套
  代码的立身之本,AGPL 不强制你保留它们 —— 但改掉它们之后,请别再说
  自己跑的是「那个不吸血的开源外卖平台」。账本哈希链会诚实地记录你收了多少。
