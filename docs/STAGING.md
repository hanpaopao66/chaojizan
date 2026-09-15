# 预发环境

上线前的最后一站:**和生产同一套代码、同一套 compose、同一套 nginx 路由**,跑在局域网里的一台 Mac mini 上,
对外地址 `https://staging.chaojizan.cc:8443`。

它干两件事:

1. **上线前在真机和浏览器里点一遍新功能。** 预发是开发配置:验证码直接显示在界面上、付款是模拟的,
   顾客下单 → 商家接单 → 骑手送达整条流程都能走完;数据是演示数据(13 家演示店、订单、评价、团购券、酒店)。
2. **在生产数据上彩排迁移。** 每次部署预发时从生产库现导一份,恢复进一个一次性容器,用这次的代码跑一遍迁移,
   查完就销毁。CI 的迁移只在空库和测试自己造的数据上跑过,生产库里的历史数据才是会让迁移出事的东西。

## 和生产的差别

只有下面这些,其余(服务、构建、命令、资源限制、nginx location)全部照抄生产 ——
compose 用叠加(`docker-compose.prod.yml` + `docker-compose.staging.yml`),nginx 配置由
`scripts/gen_staging_nginx.py` 从生产 `superz.conf` 按标记生成。生产改了,预发下次部署自动跟着变。

| | 生产 | 预发 | 为什么 |
|---|---|---|---|
| 配置 | `APP_ENV=prod` | `APP_ENV=dev` | 要能随便登录、模拟付款,流程才点得通 |
| 数据 | 真实数据 | 演示数据(`seed.py` + `demo_seed.py`) | 开发配置下谁都能登录任何账号,**生产数据绝不进预发的库** |
| 入口 | 443 | 8443 + 门禁 | 云服务器的 443 整个转给了生产(frp 是 TCP 直通,分不了域名) |
| 数据库镜像 | `postgis/postgis:16-3.4` | `imresamu/postgis:16-3.4` | 生产那个只有 x86 版;这个是维护者发的多架构版,同版本 |
| MinIO 镜像 | `minio/minio:latest` | quay.io 上**同一个摘要**的版本标签 | Docker Hub 上已经没有了 |
| 短信、推送、地图、微信支付 | 真的 | 都不配 | 不给真人发短信和推送,不占生产的地图配额,不碰真钱 |
| 见证节点 | 有 | 没有 | 官方见证节点只该有一个 |

## 门禁

预发谁进来都能登录任何账号,所以 nginx 最外面有一道门:第一次打开会跳到 `/__gate`,浏览器弹框要用户名和密码;
通过后发一个 30 天的 HttpOnly cookie,之后这台设备不用再输。

- 用户名 `staging`,密码在预发机上:`ssh <预发机> cat ~/super-z-staging/deploy/staging-gate/access.txt`
- 换密码(换完所有人重新输一次):`bash scripts/deploy_staging.sh init --reset-gate`
- 不直接整站上 HTTP Basic 的原因:网页版调接口时自己带 `Authorization: Bearer …`,浏览器就不再补发 Basic 那个头,接口会全部 401。
- 手机 App 连不了预发:安装包里的接口地址是编译时写死的生产地址。在预发上测用浏览器(用户端网页版 `/web/`、各个后台)。

## 部署

```bash
bash scripts/deploy_staging.sh init        # 第一次(预发机上生成密钥、门禁、占位证书、frpc 配置)
bash scripts/deploy_staging.sh             # 部署 HEAD
bash scripts/deploy_staging.sh v0.21.0-b2064 --skip-web   # 部署某个提交;网页版没改就别重编
```

读 `deploy/.env.deploy`(不入库)里的 `STAGING=user@预发机`、`STAGING_BASE=https://staging.chaojizan.cc:8443`,
以及生产那两行(签证书、导生产库要连生产部署机,在外面时自动走私密通道)。

**只部署提交过的代码**:和生产一样从干净检出同步,工作区里没提交的改动不会带上预发。

一次部署依次做:

1. 同步代码到预发机 `~/super-z-staging`;
2. 从生产 `superz.conf` 生成预发 nginx 配置;
3. 编用户端网页版:参数和发版一样,只有接口地址换成预发(GitHub Release 里那份编进去的是生产地址,不能用);
4. 取证书:在生产部署机上签 / 续 `staging.chaojizan.cc`,直接流到预发机;
5. 预发机缺的基础镜像由开发机拉 arm64 版灌过去(预发机自己拉 Docker Hub 时断时续);
6. 构建镜像,**迁移彩排**(见下);
7. 起服务、重启 nginx,空库时灌演示数据;
8. 在预发机本机过门禁查 `/health`(版本号要对得上)、确认不带 cookie 会被挡;
   冒烟(`deploy/staging-smoke.sh`):网页版和它编进去的接口地址、三个后台、配置下发、演示顾客验证码登录、首页有店;
   最后看 frpc 连上没有、从外网试一次。

## 迁移彩排

`deploy/rehearse-migrations.sh`,部署预发时自动跑(`--no-rehearsal` 跳过):

- 生产库**现导**一份(`pg_dump -Fc`),经管道直接流到预发机,不落开发机;
- 恢复进一次性容器(不发布端口、不接 api,只有迁移进程连它),用这次的代码 `python -m app.startup`;
- 查:迁移后到了代码的 head、用户数和订单数没变、没有孤儿订单、没有 INVALID 索引;打印在生产数据上用了几秒;
- 跑完(包括失败时)连同导出文件一起删掉。

彩排失败部署就停在那里,预发和生产都不动 —— 先把迁移修好。

## 上线前你要做的(一次)

1. **DNS**:阿里云解析里给 `chaojizan.cc` 加一条 A 记录,主机记录 `staging`,指向和 `chaojizan.cc` 相同的云服务器 IP;
2. **云服务器(跑 frps 的那台)放行 8443**,两处都要:
   - 安全组入方向放行 TCP 8443;
   - `frps.toml` 的 `allowPorts` 里加上 8443(比如 `{ single = 8443 }`),然后重启 frps。
     没加的话预发机的 frpc 日志里是 `start error: port not allowed`,部署脚本会指出来;
3. **预发机固定地址**:路由器里给 Mac mini 做 DHCP 保留(或者插网线后再保留),`deploy/.env.deploy` 里的 `STAGING` 跟着改;
4. (可选)Mac mini 装 Rosetta:`sudo softwareupdate --install-rosetta --agree-to-license`,之后 `colima restart`。
   现在 x86 镜像靠 qemu 模拟也能跑,只是慢;预发的镜像都是 arm64 版,暂时用不到。

1、2 做完后再跑一次部署,证书会自动换成正式的。

## 预发机上的东西

| 位置 | 是什么 |
|---|---|
| `~/super-z-staging/` | 同步过去的代码(rsync,排除清单见 `deploy_staging.sh`) |
| `deploy/.env.staging` | 运行配置和各项随机密钥(`staging-init.sh` 生成,只在这台上) |
| `deploy/staging-gate/` | 门禁密码、cookie 值、`access.txt`、演示数据的输出 `seed.log` |
| `deploy/certs/staging/` | 证书(部署机签好流过来;没有时是自签名占位) |
| `deploy/tunnel/frpc.staging.toml` | frpc 配置(服务端地址和 token 来自生产 frpc.toml,init 时直接流过来) |
| `deploy/nginx/staging.generated/` | 生成的 nginx 配置 |
| `webapp/current/` | 预发编的用户端网页版 |

在预发上跑某个 e2e 套件(测试代码临时拷进 api 容器、跑完删掉;用例会在预发库里造数据,不要紧):

```bash
ssh <预发机> bash ~/super-z-staging/deploy/staging-e2e.sh e2e_miniapp_catalog
```

官方小程序也可以发一份到预发(和生产同一个脚本 `server/scripts/publish_official_miniapp.py`,审核人写演示管理员 13800000000),
预发没有托管域名,开发配置下小程序走主站的 `/_mini-host/` 路径打开。

运维命令都走 `deploy/staging-compose.sh`(项目名、两份 compose、env 文件只写在这一处):

```bash
ssh <预发机>
bash ~/super-z-staging/deploy/staging-compose.sh ps
bash ~/super-z-staging/deploy/staging-compose.sh logs -f --tail 100 api
```

预发机的 Docker 是 colima(`brew services` 登录后自动起),配置在 `~/.colima/default/colima.yaml`。
