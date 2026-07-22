#!/usr/bin/env bash
# 恢复演练:把指定备份恢复到一个一次性容器里,做完整性抽查后销毁。
# 建议每月跑一次 —— 没演练过恢复的备份等于没有备份。
#
# 用法:./restore-drill.sh <备份文件.dump>
set -euo pipefail

DUMP="${1:?用法: $0 <备份文件.dump>}"
[ -f "$DUMP" ] || { echo "✗ 备份文件不存在: $DUMP"; exit 1; }

NAME="superz-restore-drill"
PORT="${DRILL_PORT:-55432}"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

echo "→ 启动一次性 PostGIS 容器 ($NAME, 端口 $PORT)…"
docker run -d --name "$NAME" -e POSTGRES_USER=superz -e POSTGRES_PASSWORD=drill \
  -e POSTGRES_DB=superz -p "127.0.0.1:$PORT:5432" postgis/postgis:16-3.4 >/dev/null
# 不用 pg_isready:initdb 阶段的临时服务器也会报 ready,但库还没建好
until docker exec "$NAME" psql -U superz -d superz -tAc "SELECT 1" >/dev/null 2>&1; do
  sleep 1
done

echo "→ 恢复备份…"
# postgis 扩展目标库里已有(镜像预装),恢复清单里剔除扩展条目避免冲突
docker cp "$DUMP" "$NAME:/tmp/drill.dump"
docker exec "$NAME" bash -c "
  pg_restore -l /tmp/drill.dump \
    | grep -vE ' EXTENSION | COMMENT - EXTENSION | SCHEMA - (tiger|tiger_data|topology) |spatial_ref_sys' \
    > /tmp/drill.list &&
  pg_restore -U superz -d superz --no-owner -L /tmp/drill.list /tmp/drill.dump"

echo "→ 完整性抽查:"
check() {
  docker exec "$NAME" psql -U superz -d superz -tAc "$1"
}
TABLES=$(check "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
USERS=$(check "SELECT count(*) FROM users")
ORDERS=$(check "SELECT count(*) FROM orders")
EVENTS=$(check "SELECT count(*) FROM order_events")
ALEMBIC=$(check "SELECT version_num FROM alembic_version" || echo "无")
echo "   表 $TABLES 张 / 用户 $USERS / 订单 $ORDERS / 订单事件 $EVENTS / 迁移版本 $ALEMBIC"

# 账目一致性:每笔已结算订单都应有对应事件流水(抽查逻辑完好性,不只是行数)
ORPHANS=$(check "SELECT count(*) FROM orders o WHERE NOT EXISTS
                 (SELECT 1 FROM order_events e WHERE e.order_id=o.id)")
if [ "$ORPHANS" != "0" ]; then
  echo "✗ 发现 $ORPHANS 个没有任何事件记录的订单,备份可能不完整!"
  exit 1
fi
if [ "$TABLES" -lt 16 ] || [ "$USERS" = "0" ]; then
  echo "✗ 数据量异常(表<16 或用户为 0),请人工核查!"
  exit 1
fi
echo "✓ 恢复演练通过,一次性容器已销毁"
