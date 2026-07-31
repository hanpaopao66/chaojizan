FROM python:3.11-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
