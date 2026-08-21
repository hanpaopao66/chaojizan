FROM python:3.11-slim

WORKDIR /srv

# ffmpeg 给明厨亮灶探测抽帧用(#156)。没有它只能验"连不连得上",
# 验不了**黑屏和镜头对着天花板** —— 而后者正是行业里最普遍的乱象,
# 也正是平台会被追连带责任的那一种(标着「有」实际啥也看不见)。
#
# 代码在没有 ffmpeg 时会照实降级并说明(kitchen_cam.capabilities()),
# 不会假装验过 —— 但生产上我们要的是完整检测。
#
# apt 走阿里云:官方源在国内服务器会超时
ARG APT_MIRROR=mirrors.aliyun.com
RUN sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" \
        /etc/apt/sources.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# pip 也走阿里云:服务器上 PyPI 官方源直接不通
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
COPY requirements.txt .
# --timeout / --retries 不是可有可无的。
#
# 2026-08-19 那次发版就死在这儿:阿里云源读超时,整个构建 exit 2,
# 部署脚本停在重建容器那一步 —— 生产没坏(旧容器还跑着),
# 但新版本上不去,而失败原因和代码一点关系都没有。
#
# 默认超时 15 秒对国内镜像站偏紧,包大一点(torch 那类没有,但 grpcio、
# pydantic-core 也不小)碰上网络抖动就断。retries 5 + timeout 60
# 是"多等一会儿"而不是"忽略错误":真的连不上还是会失败,
# 只是不会因为一次抖动就报废一次发版。
RUN pip install --no-cache-dir --retries 5 --timeout 60 \
      -i "${PIP_INDEX_URL}" -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY static ./static
# 演示用真实照片。**漏了这行的后果是静默的**:demo_seed 读不到图库时
# 会回退成纯色渐变块(category_photo 里的 `if not pool`),seed 照样跑通、
# 不报任何错,线上就一直是色块。生产曾因此挂了半年的渐变图
COPY seed_assets ./seed_assets
# 启动时 lifespan 自动跑 alembic upgrade,镜像里必须带迁移配置和脚本。
# app_version.txt 由发版脚本生成(透明中心版本公示);通配写法保证
# 本地开发没这个文件时构建也不失败
COPY alembic.ini app_version.txt* ./
COPY alembic ./alembic

EXPOSE 8000

# 反代信任范围。**不配这个,按 IP 限流就是错的**:
# uvicorn 默认只信 127.0.0.1,而 nginx 是另一个容器(172.x),
# 于是 X-Forwarded-For 被忽略、request.client.host 对所有请求都是
# nginx 的地址 —— /screen 和 /transparency 全站共用一个 120/分钟的桶。
#
# 值取 Docker 私有网段而不是 "*"。nginx 的容器 IP 会随重建漂移
# (nginx 配置里那段 resolver 注释就是为这事写的),所以只能按网段信,
# 不能钉死一个地址。写 "*" 则是连公网直连都信,没有理由。
#
# ⚠️ 已知局限,别以为配完就万事大吉:nginx 用的是
# `$proxy_add_x_forwarded_for`(**追加**而非覆盖),所以公网客户端
# 自带的 XFF 会被保留在链左侧。真正的来源 IP 还取决于 frp 隧道那一跳
# 有没有透传(仓库里看不到 frpc.toml)—— 如果没有,这里拿到的
# 仍然可能是同一个值。要根治得在 frps 开 proxyProtocolVersion,
# nginx 上配 set_real_ip_from / real_ip_header,然后把这里改成只信 nginx。
ENV FORWARDED_ALLOW_IPS=172.16.0.0/12

# --workers 1。**这不是"少用点资源",是四个 worker 会各跑一份不该跑四份的东西**:
#
#   连接池   4 × (10 + 20) = 120 > PG 默认 max_connections 100 → 随机 500
#   清扫循环 lifespan 里的 auto_flow_loop 每个 worker 各一份,同扫一批订单
#   WebSocket ConnectionManager 是进程内 dict,广播只到本进程 → 约 75% 收不到
#   迁移     四个进程同时 alembic upgrade,抢 alembic_version
#
# 这四件事有一个共同的形状:**它们都假设自己是独一份**。逐个改成多进程安全
# (Redis 选主 + pub/sub + 咨询锁)是另一条路,但这台机器 4 核还压着
# db/redis/minio/nginx/frpc,给一个 I/O 密集的异步 API 分四个进程本来就是
# 把核抢走给了最不需要的那个。清扫和迁移改成独立容器(见 compose),
# 剩下 WebSocket 天然正确 —— 单进程就是最简单的那把 Redis pub/sub。
#
# 什么时候该回到多进程:单进程 CPU 打满(不是内存、不是慢查询)。
# 那时要先把 ws.py 的广播换成 Redis pub/sub,不然横向扩一个丢一份消息。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers"]
