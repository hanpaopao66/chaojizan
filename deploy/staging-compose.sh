#!/usr/bin/env bash
# 预发 compose 的唯一入口(docs/STAGING.md):项目名、两份 compose 文件、env 文件只在这一处写。
# 在预发机上:
#   bash ~/super-z-staging/deploy/staging-compose.sh ps
#   bash ~/super-z-staging/deploy/staging-compose.sh logs -f --tail 100 api
set -euo pipefail
cd "$(dirname "$0")"
# 预发机是 Mac(docker、colima 由 Homebrew 装),非交互 ssh 的 PATH 里没有 /opt/homebrew/bin
[ -d /opt/homebrew/bin ] && export PATH="/opt/homebrew/bin:$PATH"
# 项目名写死:网络名(superz-staging_default)要让 rehearse-migrations.sh 认得出来,
# 也免得目录一改名就起出第二套栈、旧的那套还占着端口
exec docker compose -p superz-staging -f docker-compose.prod.yml -f docker-compose.staging.yml \
  --env-file .env.staging "$@"
