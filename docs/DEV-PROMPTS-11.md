# 开发提示词 #124–#126:自建对象存储与真实图片

承接 docs/DEV-PROMPTS-10.md。

**这一批的起因不是"存储不够用",是一个隐私缺陷。** 实测:

```
匿名 GET /uploads/01160d64....png  → 200
带乱写的 token                     → 200
```

`/uploads/` 由 `StaticFiles` 直出、无任何鉴权,而同一个目录里同时躺着菜品图和
**骑手身份证 / 健康证 / 营业执照 / 送达留证**(`orders.delivery_photo_url` 的代码注释
写着"仅用户/平台可见",实际全网可见)。上传接口只有一个 `/upload`,通吃所有用途。

UUID4 不可枚举,所以不是"能被扫库"。但这是 security by obscurity ——
URL 一旦泄露(截图、日志、Referer、转发)就是**永久可访问且无法撤销**。
对身份证这个级别不够。更要紧的是:隐私政策对骑手写的是"只收提供服务所必需的最少信息",
实名材料挂在公网直取路径上,跟这句话对不上。

## 两个已拍板的决定(2026-07-30)

1. **public 桶对外路径用 `/img/`**,与老的 `/uploads/`(仅做兼容)分开。
   新路径干净、可单独设长缓存,也一眼看得出哪些是新链路。
2. **生产直接切 `STORAGE_BACKEND=minio`**,不走"先 local 跑一版"的过渡。
   理由:生产 uploads 只有 1.475MB,迁移窗口就是现在;两步切换要维护两套
   过渡状态,反而更容易出岔子。local 后端仍然保留 —— 那是本地开发用的,
   不是生产的过渡态。

## 部署机实测约束(2026-07-30)

| | |
|---|---|
| 磁盘 | 233G,已用 89G,**可用 133G** |
| 内存 | 7.6G,可用 4.4G(机器上还有 wanli-prod / new-api 等别的栈) |
| CPU | 4 核 |
| `deploy_uploads` 卷 | **1.475MB** |

两条推论:
1. **现在迁移几乎零成本** —— 生产上真实上传还没起量,越往后越贵,这是最好的时机;
2. 磁盘充裕(划 50G 绰绰有余),**内存是唯一要克制的**:MinIO 单节点单盘即可,
   别上分布式纠删码,别开一堆后台扫描。

---

### 124. 存储抽象层 + 按用途分桶 + 证照鉴权

```
先把隐私缺陷堵上,并且做成不依赖 MinIO 也能生效的形态。
先读 docs/DEV-PROMPTS-8.md 的「设计基线」。

现状:server/app/routers/uploads.py 是一个 30 行的 MVP —— 一个 /upload 接口,
落 server/uploads/,返回 /uploads/{uuid}.jpg,由 StaticFiles 公开直出。
文件头的注释写着"上量后换对象存储:改这一个文件,返回的 URL 结构不变",
这个判断是对的,现在就是那个时候。

业务规则(已拍板):
- 上传按**用途**分两类,这是硬边界:
  - 公开类 public:菜品图 / 门头照 / 门店相册 / 开屏运营图 / 分享卡素材;
  - 私密类 private:身份证 / 健康证 / 营业执照 / 送达拍照留证。
- 私密类**不得由任何静态托管直出**。只能通过服务端签发的短时效
  预签名/一次性 URL 访问,**且签发前服务端必须判权**:
  - 身份证/健康证:本人 + 管理员(审核要看);
  - 营业执照:店主/店员 + 管理员;
  - 送达留证:该订单的顾客 + 管理员(骑手拍完就不该再看得到);
  - 其他人一律 403,不是 404 —— 这里不用装作文件不存在,权限不足就说权限不足。
- 上传接口必须要求 `purpose` 参数,**没有默认值**。让调用方显式声明用途,
  比让它猜一个安全默认值更不容易出错(猜错的那次就是一张身份证进了公开桶)。
- 老 URL `/uploads/{name}` 必须继续可用。**不要批量改数据库里的 URL** ——
  库里存的全是相对路径,一旦要回滚就全乱套。

技术要点:
- 新建 server/app/services/storage.py,后端可切:
  `STORAGE_BACKEND=local|minio`(默认 local,本地开发不该被迫起一个 MinIO);
  接口:`put(data, ext, purpose) -> key` / `public_url(key)` / `signed_url(key, ttl)`。
- local 后端:public 落 uploads/,private 落 **uploads/private/**;
  `app.mount("/uploads", StaticFiles(...))` 必须挂在一个**不含 private 子目录**的
  目录上,或者干脆把 private 移到 uploads 之外 —— 光靠"路径没人猜得到"不算隔离。
- 新增 `GET /files/{key}`:私密文件唯一出口,走完整鉴权后再回读文件流。
- 迁移脚本 `scripts/migrate_private_uploads.py`:按 rider_profiles / merchants /
  orders 里那几列的 URL 反查出私密文件,从 uploads/ 挪到 private,
  **URL 字符串保持不变**,由 /uploads 路由做兼容跳转。
- 兼容路由:`/uploads/{name}` 命中私密清单时不再直出,转到鉴权逻辑。

验收:e2e_upload_privacy.py ——
- 公开类上传后匿名可取;
- 私密类上传后**匿名取 401/403**、他人取 403、本人可取、管理员可取;
- 存量身份证 URL 迁移后匿名不可取(这条要真的用旧 URL 去撞);
- 不传 purpose 的上传请求 422。
```

---

### 125. 自建 MinIO(单节点)+ nginx 反代 + 备份

```
把 storage.py 的 minio 后端接上,并把它部署起来。
先读 docs/DEV-PROMPTS-8.md 的「设计基线」与本文件开头的部署机约束。

业务规则(已拍板):
- 自建,不上云对象存储。
- **单节点单盘**。4 核 / 可用内存 4.4G 且有邻居栈,不做分布式纠删码,
  不开重扫描类后台任务。磁盘划 50G(可用 133G,留足余量)。
- **MinIO 的 9000/9001 一律不 publish 到宿主机**。对外只经 nginx:
  public 桶由 nginx 反代成一个稳定路径;private 桶只走预签名,不反代。
  控制台(9001)只在内网/隧道里开,不进 nginx 的公网 server 块。
- 凭据放 deploy/.env.prod(已 gitignore、已被 rsync --delete 排除),不入库。

docker-compose.prod.yml 加这一段(镜像走宿主 /etc/docker/daemon.json 的
registry-mirrors,与本项目其他服务同口径):

    minio:
      image: minio/minio:latest
      restart: unless-stopped
      command: server /data --console-address ":9001"
      environment:
        MINIO_ROOT_USER: ${MINIO_ROOT_USER}
        MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
        # 单节点单盘:关掉用不上的后台扫描,省内存
        MINIO_BROWSER_REDIRECT_URL: ""
      volumes:
        - minio_data:/data
      # 故意不写 ports:不暴露到宿主机,只在 compose 内网可达
      healthcheck:
        test: ["CMD", "mc", "ready", "local"]
        interval: 30s
        timeout: 5s
        retries: 3
      mem_limit: 1g          # 邻居栈还要用内存,给它设个上限

    # 一次性初始化:建桶 + 设策略。跑完就退出,不常驻
    minio-init:
      image: minio/mc:latest
      depends_on:
        minio:
          condition: service_healthy
      entrypoint: >
        /bin/sh -c "
        mc alias set local http://minio:9000 $$MINIO_ROOT_USER $$MINIO_ROOT_PASSWORD &&
        mc mb -p local/superz-public &&
        mc mb -p local/superz-private &&
        mc anonymous set download local/superz-public &&
        mc anonymous set none local/superz-private &&
        echo 'buckets ready'
        "
      environment:
        MINIO_ROOT_USER: ${MINIO_ROOT_USER}
        MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}

    volumes:
      minio_data:

注意 `mc anonymous set none local/superz-private` 这一句:
private 桶必须显式设成不可匿名读。默认值靠不住,写出来才敢说它是私密的。

技术要点:
- storage.py 的 minio 后端用官方 SDK,`STORAGE_BACKEND=minio` 时启用;
  连不上 MinIO 时**上传要明确失败**,不许静默退回本地磁盘 ——
  静默降级会让一半文件在桶里一半在磁盘上,后面根本对不齐。
- nginx 给 public 桶一个稳定前缀(如 `/img/`)反代到 `minio:9000/superz-public/`,
  设长缓存;private 桶不配任何反代。
- 存量迁移脚本 `scripts/migrate_uploads_to_minio.py`:
  按 #124 分好的公开/私密清单分别灌进两个桶,**幂等可重跑**,
  跑完打印两边文件数对账。生产上现在只有 1.475MB,几分钟的事。
- 过渡期双读:`/uploads/{name}` 先查 MinIO,没有再落回本地磁盘。
  跑稳一段时间再考虑收掉本地那条路 —— 别一步到位。
- **备份必须和 MinIO 一起上线**,不能留到"以后再说":
  deploy/backup-minio.sh 用 `mc mirror` 定时同步到宿主机另一目录,
  接进现有的运维脚本。自建的意思就是备份也归你 ——
  只上 MinIO 不上备份,跟现在的裸 named volume 没区别,只是多了一层壳。

验收:
- e2e_upload_privacy.py 在 STORAGE_BACKEND=minio 下同样全绿(同一套断言两种后端都跑);
- private 桶匿名直连(绕过服务端,直接打 MinIO)取不到文件 —— 这条要真的去撞;
- 迁移脚本重跑两次结果一致(幂等);
- 备份脚本跑一次后,镜像目录的文件数与桶内一致。
```

---

### 126. 演示数据换成真实照片

```
把演示商家的图从纯色渐变块换成真实照片,顺着 #125 的存储链路走。

现状:server/uploads/demo/ 下 202 张所谓"演示图"全部是 400x300 的橙色渐变块;
195 家演示商家里只有 9 家挂了这种"图",648 道菜里 199 道。
应用商店截图、审核员、给商家做演示时,平台看起来像个没做完的壳子。

已完成的部分:scripts/fetch_demo_photos.py 已从 Wikimedia Commons 抓下
23 个品类共约 90 张真实照片,存 server/seed_assets/demo_photos/,
**只收 Public domain / CC0**(无署名义务),每张都在 manifest.json 里
记了来源页 / 许可 / 作者。人工筛掉过一轮古画、铜版画、细密画、活体小龙虾、
矢量插画、店铺门脸、包装食品和带可识别人物的,并落成 blocklist.txt。

业务规则(已拍板):
- **这些图只用于演示数据**。真实商家没传图时**绝不能**套用一张不属于他的照片 ——
  那是平台替商家做虚假宣传,和"不杀熟、不虚标"的立场直接冲突,
  出了"图文不符"的差评责任还在平台。真实商家缺图继续走占位方案。
- 演示数据在库里要能被识别(便于将来一键清演示数据),
  不要和真实商家的图混在一个命名空间里。
- seed_assets 进仓库、随部署同步;uploads 既被 gitignore 也被 rsync 排除,
  图放那儿等于既不进仓库也上不了生产。

技术要点:
- seed/demo_seed 脚本把 seed_assets/demo_photos 灌进 **public 桶**
  (或 local 后端的 uploads/),按品类给演示商家分配 logo 与菜品图;
- 同品类的店之间要错开取图,别整屏一模一样;
- 删掉 server/uploads/demo/ 下的 202 张渐变块与我早期跑测试时的残留;
- fetch_demo_photos.py 保留:将来补品类或换图直接重跑,blocklist 会跳过已否掉的。

验收:演示城市首页整屏不再出现纯色块;manifest.json 覆盖所有落库的演示图;
清演示数据的路径仍然可用。
```

---

## 与 #123 的待办合并

docs/DEV-PROMPTS-10.md 末尾那条「上架前必须拆 productFlavors 摘掉
REQUEST_INSTALL_PACKAGES」依然有效,和这一批无关,别忘了。

---

## 执行记录(#124 / #125 / #126)

2026-07-30 一轮做完,全量回归 **402 项通过(跑在 minio 后端上)**。

### #124 存储抽象层 + 分桶 + 证照鉴权 — 已完成

- 新建 `app/services/storage.py`:`PURPOSES` 表把用途硬分公开/私密两类,
  `LocalBackend`(本地开发)与 `MinioBackend`(生产)可切。
- **`/upload` 的 `purpose` 必填、无默认值**。写代码时最想偷的懒就是给个
  "安全默认",但猜错的那一次就是一张身份证进了公开桶。
- **`main.py` 里的 `app.mount("/uploads", StaticFiles(...))` 已删除**。
  这一条比任何判权代码都重要 —— 静态挂载是绕过鉴权的一条路,
  只要它还在,判权就是摆设。`/uploads/{name}` 现由 `legacy_file` 接管。
- 判权看**归属**不看角色:身份证只有本人+管理员;营业执照只有店主+管理员
  (店员不给 —— 资质材料不是接单要用的);送达留证只有该单顾客+管理员
  (骑手拍完就不该再看得到,那是别人家门口)。权限不足给 403 不给 404。
- 私密响应带 `Cache-Control: no-store, private`:被 CDN/代理缓存一次,撤权就形同虚设。
- 迁移 `scripts/migrate_uploads.py`:幂等(复跑 433 个全跳过),
  **数据库里的 URL 一个字没改**,是否私密由「文件在哪」决定而不是维护一份清单 ——
  清单会和现实脱节,文件位置不会。

**用途表在实现过程中扩了一倍**,因为逐个核对 12 处调用点时发现了漏网的敏感项:
`incident`(骑手事故现场照)、`after_sale`(售后凭证)、
以及 `food_safety` —— 食安投诉可附**医疗凭证**,医疗健康信息在个保法下
属于敏感个人信息,这一类比身份证更不能公开直出。

### #125 自建 MinIO — 已完成

- 生产 compose 加 `minio` + `minio-init`(一次性建桶设策略,幂等,
  每次部署都重新确认一遍「私密桶不可匿名读」)。
- **实测确认没有 ports 暴露**(`docker compose config` 里 minio 段 ports 出现 0 次)。
- **nginx 的 `/img/` 用变量 + resolver 在请求时解析 upstream**:
  写死主机名的话 MinIO 没起来 nginx 就直接起不来 —— 图片挂了是小事,
  整站连不上是大事。另配 `error_page ... = @img_fallback` 回落到 api。
- **private 桶在 nginx 里没有任何 location**,少写那一条正是隐私改造的意义。
- `deploy/backup-minio.sh` 与 MinIO 同时上线,`mc mirror --overwrite --remove`
  保证备份与桶严格一致,跑完对账文件数(本地演练 5=5 通过)。

**踩到并修掉的两个坑**:
1. `minio/mc` 镜像的 entrypoint 就是 `mc`,`docker run ... mc:latest sh -c '...'`
   会把 `sh` 当成 mc 子命令(实测报 "sh is not a recognized command"),
   必须 `--entrypoint sh`。compose 里用 `entrypoint:` 覆盖则没这个问题。
2. 私密桶匿名直连实测 403、公开桶 200 —— 桶策略是真的生效,不是靠服务端挡着。

### #126 演示图换真照片 — 已完成

- `scripts/fetch_demo_photos.py` 从 Wikimedia Commons 抓 23 品类约 90 张,
  **只收 PD/CC0**(无署名义务),manifest 记来源/许可/作者,blocklist 记人工否决项。
- 人工筛过两轮,否掉的典型样本:铜版画建筑、波斯细密画、古籍手稿、水里的活小龙虾、
  矢量插画、店铺门脸、包装香肠、带可识别人物的照片。据此给脚本加了
  `ART_WORDS`/`NOT_A_DISH` 标题过滤 —— 公有领域里古画最多,
  许可最干净所以恰恰最容易被搜出来。
- `demo_seed.py` 的取图改为**走 storage 层**而不是直接写 uploads/:
  生产后端是 MinIO,往本地目录写文件在那边根本读不到 ——
  seed 正是「本地跑得通、线上一片灰」最容易发生的地方。
- 演示证照也进私密桶:演示数据和真实数据在**存储策略**上必须一致,
  否则 e2e 和迁移对账会得到一个"看起来没问题"的假象。
- 实测:商家 logo 走 `/img/` 19 家(色块 0 家)、菜品图 223 道,匿名 GET 200。

---

## ⚠️ 上线前必须知道的两件事

1. **这是破坏性接口变更**。`/upload` 的 `purpose` 必填,
   **v0.5.0 及更早的客户端上传会 422**。必须与三端新版本一起发,
   考虑给这一版设 `force: true`。
   (生产 uploads 目前只有 1.475MB,真实用户上传量近乎为零,现在破是最便宜的。)
2. `deploy/.env.prod` 要新增四项,**不入库**:
   ```
   STORAGE_BACKEND=minio
   MINIO_ENDPOINT=minio:9000
   MINIO_ACCESS_KEY=<与 MINIO_ROOT_USER 一致>
   MINIO_SECRET_KEY=<与 MINIO_ROOT_PASSWORD 一致>
   MINIO_ROOT_USER=<自拟>
   MINIO_ROOT_PASSWORD=<自拟,足够长>
   ```
   部署后先跑一次 `python -m scripts.migrate_uploads` 把存量灌进桶,
   再把 `deploy/backup-minio.sh` 挂进 crontab。
