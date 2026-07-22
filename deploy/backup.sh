#!/usr/bin/env bash
# 每日数据库备份(M2 保命线)。在部署机 crontab 里跑:
#   10 3 * * * /home/dddd/super-z/deploy/backup.sh >> /home/dddd/super-z/backups/backup.log 2>&1
#
# 异地容灾:设置 OFFSITE_DEST(rsync 目标,如 user@host:/path 或挂载的网盘目录),
# 本机磁盘挂了备份还在。没有异地目标的备份只算半个备份。
#
# 恢复演练用 restore-drill.sh —— 没演练过恢复的备份等于没有备份。
set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-deploy-db-1}"   # 生产 compose 的 db 容器名
BACKUP_DIR="${BACKUP_DIR:-$HOME/super-z/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
OFFSITE_DEST="${OFFSITE_DEST:-}"

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
FILE="$BACKUP_DIR/superz-$STAMP.dump"

# -Fc 自定义格式:压缩、可用 pg_restore 选表恢复
# -N 排除 postgis 扩展自带的 schema(恢复目标的镜像里本来就有,带上反而冲突)
docker exec "$DB_CONTAINER" pg_dump -U superz -Fc \
  -N tiger -N tiger_data -N topology superz > "$FILE"
SIZE=$(du -h "$FILE" | cut -f1)
echo "$(date '+%F %T') 备份完成 $FILE ($SIZE)"

# 轮转:只留最近 KEEP_DAYS 天
find "$BACKUP_DIR" -name 'superz-*.dump' -mtime +"$KEEP_DAYS" -delete

# 异地同步(强烈建议配置)
if [ -n "$OFFSITE_DEST" ]; then
  rsync -az "$FILE" "$OFFSITE_DEST/" && echo "$(date '+%F %T') 已同步到异地 $OFFSITE_DEST"
else
  echo "警告:未配置 OFFSITE_DEST,备份只存在本机(本机磁盘故障=备份一起没)"
fi
