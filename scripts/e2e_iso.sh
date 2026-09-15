#!/usr/bin/env bash
# 本地起一套一次性的隔离 e2e 环境:postgis / redis / minio 各一个容器,端口按「槽位」错开,
# 不碰开发库、开发 Redis、8010 / 8013 那两套服务。几个人(或几个 worktree)同时跑互不干扰。
#
#   bash scripts/e2e_iso.sh up   <槽位 0-9>   # 起容器、建桶、迁移、灌种子数据,写出环境变量文件
#   bash scripts/e2e_iso.sh env  <槽位>       # 打印环境变量文件的路径(. 它就能跑 e2e)
#   bash scripts/e2e_iso.sh down <槽位>       # 删容器和环境变量文件
#
# 端口:数据库 5550<槽位>、Redis 5650<槽位>、MinIO 5950<槽位>、api 81<槽位>0(api 自己起,见文末)。
# **server/.env 里没有 DATABASE_URL / REDIS_URL**,不显式给就连到开发库和 Redis 0 —— 环境文件把它们都指到这里;
# .env 里的腾讯地图 key 置空,跑测试不烧配额。JWT 密钥每次现造,只写进环境文件(0600),不打印。
set -euo pipefail
cmd=${1:?用法: e2e_iso.sh up|env|down <槽位>}
slot=${2:?缺槽位(0-9)}
case "$slot" in [0-9]) ;; *) echo "槽位只能是 0-9"; exit 2 ;; esac
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIR="${TMPDIR:-/tmp}/superz-e2e-iso"
ENVF="$DIR/slot$slot.env"
PG=5550$slot; RD=5650$slot; MN=5950$slot; API=81${slot}0
NAME=sz-e2e-iso-$slot

case "$cmd" in
  env) echo "$ENVF" ;;
  down)
    docker rm -f "$NAME-db" "$NAME-redis" "$NAME-minio" >/dev/null 2>&1 || true
    rm -f "$ENVF"; echo "槽位 $slot 已清理" ;;
  up)
    mkdir -p "$DIR"; chmod 700 "$DIR"
    docker rm -f "$NAME-db" "$NAME-redis" "$NAME-minio" >/dev/null 2>&1 || true
    PGIMG=$(docker image inspect imresamu/postgis:16-3.4 >/dev/null 2>&1 && echo imresamu/postgis:16-3.4 || echo postgis/postgis:16-3.4)
    MNIMG=$(docker image inspect quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z >/dev/null 2>&1 \
      && echo quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z || echo quay.io/minio/minio)
    docker run -d --name "$NAME-db" -e POSTGRES_USER=superz -e POSTGRES_PASSWORD=superz -e POSTGRES_DB=superz \
      -p "127.0.0.1:$PG:5432" "$PGIMG" >/dev/null
    docker run -d --name "$NAME-redis" -p "127.0.0.1:$RD:6379" redis:7-alpine >/dev/null
    docker run -d --name "$NAME-minio" -p "127.0.0.1:$MN:9000" -e MINIO_ROOT_USER=superz \
      -e MINIO_ROOT_PASSWORD=superz-e2e-local "$MNIMG" server /data >/dev/null
    for _ in $(seq 1 40); do
      docker exec "$NAME-db" pg_isready -U superz >/dev/null 2>&1 \
        && curl -sf "http://127.0.0.1:$MN/minio/health/live" >/dev/null 2>&1 && break
      sleep 2
    done
    umask 077
    cat > "$ENVF" <<EOF
export APP_ENV=dev
export DATABASE_URL=postgresql+asyncpg://superz:superz@127.0.0.1:$PG/superz
export REDIS_URL=redis://127.0.0.1:$RD/0
export STORAGE_BACKEND=minio
export MINIO_ENDPOINT=127.0.0.1:$MN
export MINIO_ACCESS_KEY=superz
export MINIO_SECRET_KEY=superz-e2e-local
export MINIO_SECURE=false
export AUTO_FLOW_ENABLED=false
export SUPERZ_API=http://127.0.0.1:$API
export E2E_ISO_API_PORT=$API
export SEED_DEMO_PASSWORD=e2e-local-demo
export SMS_DAILY_IP_LIMIT=100000
export RATE_LIMIT_REGISTER_PER_MINUTE=100000
export PUBLIC_CACHE_MAX_SECONDS=0
export QUEUE_CALL_GRACE_SECONDS=2
export SMS_RESEND_SECONDS=3
export CALL_RING_SECONDS=5
export CALL_DROP_GRACE_SECONDS=3
export TENCENT_MAP_KEY=
export RUN_MIGRATIONS_ON_STARTUP=false
EOF
    sec="e2e-iso-$(python3 -c 'import secrets;print(secrets.token_hex(24))')"
    echo "export JWT_SECRET=${sec}" >> "$ENVF"
    cd "$ROOT/server"
    PY=${PYTHON:-$ROOT/server/.venv/bin/python}
    [ -x "$PY" ] || PY=/Users/dujianye/PycharmProjects/super-z/server/.venv/bin/python
    # shellcheck disable=SC1090
    . "$ENVF"
    "$PY" - <<'PYEOF'
import os
from minio import Minio
c = Minio(os.environ["MINIO_ENDPOINT"], access_key="superz", secret_key="superz-e2e-local", secure=False)
for b in ("superz-public", "superz-private"):
    if not c.bucket_exists(b):
        c.make_bucket(b)
PYEOF
    "$PY" -m alembic upgrade head >/dev/null
    "$PY" -m scripts.seed >/dev/null
    "$PY" -m scripts.demo_seed >/dev/null
    echo "槽位 $slot 就绪:环境变量文件 $ENVF"
    echo "起 api:  . $ENVF && cd server && \$PY -m uvicorn app.main:app --host 127.0.0.1 --port $API"
    echo "跑用例:  . $ENVF && cd server && \$PY -m tests.e2e_xxx" ;;
  *) echo "未知命令 $cmd"; exit 2 ;;
esac
