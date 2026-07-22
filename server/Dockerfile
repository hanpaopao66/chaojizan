FROM python:3.11-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY static ./static
# 启动时 lifespan 自动跑 alembic upgrade,镜像里必须带迁移配置和脚本。
# app_version.txt 由发版脚本生成(透明中心版本公示);通配写法保证
# 本地开发没这个文件时构建也不失败
COPY alembic.ini app_version.txt* ./
COPY alembic ./alembic

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
