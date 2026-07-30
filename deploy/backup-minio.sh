#!/bin/bash
# MinIO 备份(#125):把两个桶镜像到宿主机目录。
#
# **自建的意思就是备份也归你。** 只上 MinIO 不上备份,跟原先那个裸 named volume
# 没有任何区别 —— 只是多了一层壳。所以这个脚本和 MinIO 同时上线,不留到"以后再说"。
#
# 用法(在部署机上):
#     deploy/backup-minio.sh                  # 备份到默认目录
#     BACKUP_DIR=/mnt/xxx deploy/backup-minio.sh
#
# 建议挂进 crontab(每天凌晨 4 点,避开出餐高峰):
#     0 4 * * * /home/dddd/super-z/deploy/backup-minio.sh >> /var/log/superz-minio-backup.log 2>&1
set -e
cd "$(dirname "$0")"

[ -f .env.prod ] && . .env.prod
: "${MINIO_ROOT_USER:?缺 MINIO_ROOT_USER(在 deploy/.env.prod)}"
: "${MINIO_ROOT_PASSWORD:?缺 MINIO_ROOT_PASSWORD(在 deploy/.env.prod)}"

BACKUP_DIR=${BACKUP_DIR:-$HOME/super-z-backup/minio}
mkdir -p "$BACKUP_DIR"

# 用 mc 容器接进本栈网络:MinIO 不对宿主机暴露端口,只能从 compose 网络里访问
NET=$(docker inspect superz-minio -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null)
[ -n "$NET" ] || { echo "✗ superz-minio 没在跑,先 docker compose up -d minio"; exit 1; }

echo "== 镜像两个桶到 $BACKUP_DIR =="
# --entrypoint sh:minio/mc 的默认 entrypoint 就是 mc,
# 不覆盖的话 `sh -c ...` 会被当成 mc 的参数(实测报 "sh is not a recognized command")
docker run --rm --network "$NET" \
  -v "$BACKUP_DIR:/backup" \
  -e MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@superz-minio:9000" \
  --entrypoint sh minio/mc:latest -c '
    set -e
    # --overwrite --remove:让备份目录与桶严格一致。
    # 不加 --remove 的话,桶里删掉的文件会在备份里永久留着,
    # 时间一长备份目录只增不减,恢复时会把删掉的东西又倒回去
    mc mirror --overwrite --remove local/superz-public  /backup/superz-public
    mc mirror --overwrite --remove local/superz-private /backup/superz-private
  '

echo "== 对账 =="
for b in superz-public superz-private; do
  remote=$(docker run --rm --network "$NET" \
    -e MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@superz-minio:9000" \
    minio/mc:latest ls --recursive "local/$b" 2>/dev/null | wc -l | tr -d ' ')
  local_n=$(find "$BACKUP_DIR/$b" -type f 2>/dev/null | wc -l | tr -d ' ')
  if [ "$remote" = "$local_n" ]; then
    echo "  ✓ $b: 桶内 $remote 个,备份 $local_n 个"
  else
    echo "  ✗ $b: 桶内 $remote 个,备份 $local_n 个 —— 不一致"
    exit 1
  fi
done

echo "备份完成 ✓ $(date '+%F %T')  →  $BACKUP_DIR"
echo "提醒:这只是同机备份,防的是误删和桶损坏,防不了整机故障。"
echo "     真要防机器挂掉,把 $BACKUP_DIR 再同步到另一台机器或移动硬盘。"
