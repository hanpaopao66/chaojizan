#!/usr/bin/env bash
# 迁移彩排(docs/STAGING.md):把生产备份恢复进一次性容器,用这次要上线的代码跑一遍迁移,查完就销毁。
# 在**预发机**的 deploy/ 下跑,由 scripts/deploy_staging.sh 调(备份从生产部署机直接流过来,不落开发机):
#
#   bash rehearse-migrations.sh <备份.dump>
#
# ## 为什么要有
#
# CI 的迁移只在空库和 e2e 自己造的数据上跑过。生产库里有 CI 造不出来的东西:历史脏数据、老版本写进去的空值、
# 某个值占了大半的列(Postgres 通用计划那次)。迁移在空库上两秒跑完,到了生产上可能违反约束失败、
# 或者跑十分钟锁表 —— 而那时候已经在部署了,api 等着它、用户也等着它。这些要先在生产数据上跑一遍才知道。
#
# ## 为什么一定要销毁
#
# 预发是开发配置(验证码直接回显,谁都能登录任何账号),生产数据绝不能进预发的库。
# 这里的一次性库不发布任何端口、不接 api,只有迁移进程连它;跑完连同备份文件一起删掉(trap,失败也删)。
set -euo pipefail
cd "$(dirname "$0")"

DUMP="${1:?用法: $0 <备份文件.dump>}"
[ -f "$DUMP" ] || { echo "✗ 备份文件不存在: $DUMP"; exit 1; }

NAME=superz-rehearsal-db
PASS=rehearsal
COMPOSE=(bash staging-compose.sh)
# 项目名在 staging-compose.sh 里写死成 superz-staging
NET=superz-staging_default
# 和预发 db 同一个镜像(docker-compose.staging.yml 里写的那个)
DB_IMAGE=$("${COMPOSE[@]}" config --images | grep -m1 postgis)

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -f "$DUMP"
}
trap cleanup EXIT
docker rm -f "$NAME" >/dev/null 2>&1 || true

# 迁移容器由 compose 起(镜像、环境变量和预发 migrate 服务一模一样),一次性库要和它在同一个网络里。
# 先让 compose 把项目网络建出来(第一次部署时还没有;自己 docker network create 的话 compose 认标签、会拒绝),
# 再把一次性库挂上去
"${COMPOSE[@]}" run --rm --no-deps --entrypoint true migrate >/dev/null
docker network inspect "$NET" >/dev/null 2>&1 || { echo "✗ 找不到 compose 项目网络 $NET"; exit 1; }

echo "→ 一次性库($DB_IMAGE,网络 $NET,不发布端口)"
docker run -d --name "$NAME" --network "$NET" -e POSTGRES_USER=superz -e POSTGRES_PASSWORD=$PASS \
  -e POSTGRES_DB=superz "$DB_IMAGE" >/dev/null
# 不用 pg_isready:initdb 阶段的临时服务器也会报 ready,但库还没建好(同 restore-drill.sh)
for _ in $(seq 1 120); do
  docker exec "$NAME" psql -U superz -d superz -tAc "SELECT 1" >/dev/null 2>&1 && break
  sleep 1
done

echo "→ 恢复生产备份 $(basename "$DUMP")($(du -h "$DUMP" | cut -f1))"
docker cp "$DUMP" "$NAME:/tmp/rehearsal.dump"
# 恢复清单剔除扩展条目(镜像里预装了),同 restore-drill.sh
docker exec "$NAME" bash -c "
  pg_restore -l /tmp/rehearsal.dump \
    | grep -vE ' EXTENSION | COMMENT - EXTENSION | SCHEMA - (tiger|tiger_data|topology) |spatial_ref_sys' \
    > /tmp/rehearsal.list &&
  pg_restore -U superz -d superz --no-owner -L /tmp/rehearsal.list /tmp/rehearsal.dump &&
  rm -f /tmp/rehearsal.dump"

q() { docker exec "$NAME" psql -U superz -d superz -tAc "$1"; }
BEFORE=$(q "SELECT version_num FROM alembic_version")
USERS_BEFORE=$(q "SELECT count(*) FROM users")
ORDERS_BEFORE=$(q "SELECT count(*) FROM orders")
[ "$USERS_BEFORE" != "0" ] || { echo "✗ 恢复出来一个用户都没有:备份不对,彩排不作数"; exit 1; }

echo "→ 用这次的代码跑迁移(生产现在是 $BEFORE)"
START=$(date +%s)
"${COMPOSE[@]}" run --rm --no-deps \
  -e "DATABASE_URL=postgresql+asyncpg://superz:$PASS@$NAME:5432/superz" \
  migrate
SECS=$(( $(date +%s) - START ))

AFTER=$(q "SELECT version_num FROM alembic_version")
HEAD=$("${COMPOSE[@]}" run --rm --no-deps --entrypoint python migrate -c \
  'from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config("alembic.ini")).get_current_head())' \
  | tail -1 | tr -d '\r')
USERS_AFTER=$(q "SELECT count(*) FROM users")
ORDERS_AFTER=$(q "SELECT count(*) FROM orders")
ORPHANS=$(q "SELECT count(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_events e WHERE e.order_id = o.id)")
INVALID=$(q "SELECT count(*) FROM pg_index WHERE NOT indisvalid")

fail=0
[ "$AFTER" = "$HEAD" ] || { echo "✗ 迁移后是 $AFTER,代码的 head 是 $HEAD"; fail=1; }
[ "$USERS_AFTER" = "$USERS_BEFORE" ] || { echo "✗ 用户数从 $USERS_BEFORE 变成了 $USERS_AFTER"; fail=1; }
[ "$ORDERS_AFTER" = "$ORDERS_BEFORE" ] || { echo "✗ 订单数从 $ORDERS_BEFORE 变成了 $ORDERS_AFTER"; fail=1; }
[ "$ORPHANS" = "0" ] || { echo "✗ $ORPHANS 个订单没有任何事件记录"; fail=1; }
# CREATE INDEX CONCURRENTLY 中途失败会留下 INVALID 索引(startup.py 里写过那次),重跑前得先删
[ "$INVALID" = "0" ] || { echo "✗ 迁移留下了 $INVALID 个 INVALID 索引"; fail=1; }
[ "$fail" = 0 ] || exit 1
if [ "$BEFORE" = "$AFTER" ]; then
  echo "✓ 迁移彩排通过:这次没有新迁移(仍是 $AFTER),用户 $USERS_AFTER / 订单 $ORDERS_AFTER 不变"
else
  echo "✓ 迁移彩排通过:$BEFORE → $AFTER,在生产数据上用了 ${SECS} 秒;用户 $USERS_AFTER / 订单 $ORDERS_AFTER 不变"
fi
echo "  一次性库和备份文件已删除"
