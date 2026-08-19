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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
