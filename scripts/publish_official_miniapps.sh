#!/bin/bash
# 把官方小程序 / 小游戏的包发到生产(DEV-PROMPTS-39 #337):开发机上构建好的 zip + listing.json
# 传到部署机、放进 api 容器,跑 server/scripts/publish_official_miniapp.py(和开发者后台同一套校验、审核、状态机)。
#
#   bash scripts/publish_official_miniapps.sh critters                 # 只看计划:不写库、不传对象
#   bash scripts/publish_official_miniapps.sh --apply critters gomoku  # 真发
#
# 先 bash scripts/build_miniapp.sh <名字> 构建(可复现的 zip,SHA-256 打印出来要和线上公示的对得上)。
# **改生产数据:跑 --apply 之前要先征得同意**;上架新游戏前先查 docs/MINIAPP-COMPLIANCE.md 第 7 条。
# 新应用第一次发布后,托管域名证书要把新 appid 签进去:脚本最后会提示在部署机上跑 deploy/mp-cert.sh。
#
# 部署机怎么连:同 deploy_server.sh(scripts/deploy_target.sh,局域网连不上时自动走 SSH 私密通道)。
set -eo pipefail
cd "$(dirname "$0")/.."
[ -f deploy/.env.deploy ] && . deploy/.env.deploy
DEPLOY=${DEPLOY:?缺部署机地址:在 deploy/.env.deploy 写 DEPLOY=user@host(不入库)}

APPLY=""
if [ "${1:-}" = "--apply" ]; then APPLY="--apply"; shift; fi
[ $# -gt 0 ] || { echo "用法: $0 [--apply] <名字>..."; exit 2; }
for a in "$@"; do
  case "$a" in *[!a-z0-9_-]*) echo "✗ 名字只能是小写字母、数字、- _:$a"; exit 2 ;; esac
  [ -f "miniapps/$a/dist/$a.zip" ] || { echo "✗ 没有 miniapps/$a/dist/$a.zip,先 bash scripts/build_miniapp.sh $a"; exit 1; }
  [ -f "miniapps/$a/listing.json" ] || { echo "✗ 没有 miniapps/$a/listing.json"; exit 1; }
done

. scripts/deploy_target.sh
deploy_target || exit 1
echo "== 连部署机:$DEPLOY_VIA =="
R=/tmp/mpub-$$
# shellcheck disable=SC2086
ssh -n $SSH_OPTS -o BatchMode=yes "$DEPLOY" "mkdir -p $R"
for a in "$@"; do
  # shellcheck disable=SC2086
  scp -q $SCP_OPTS -o BatchMode=yes "miniapps/$a/dist/$a.zip" "$DEPLOY:$R/$a.zip"
  # shellcheck disable=SC2086
  scp -q $SCP_OPTS -o BatchMode=yes "miniapps/$a/listing.json" "$DEPLOY:$R/$a-listing.json"
done
NAMES="$*"
# 审核人记平台管理员(和开发者后台里人工审核一样落审核记录)。按角色取、不写死手机号:手机号不进仓库也不打到终端
# shellcheck disable=SC2086
ssh -n $SSH_OPTS -o BatchMode=yes "$DEPLOY" "set -e
for a in $NAMES; do
  docker cp $R/\$a.zip superz-api:/tmp/\$a.zip
  docker cp $R/\$a-listing.json superz-api:/tmp/\$a-listing.json
done
rm -rf $R
REV=\$(docker exec deploy-db-1 psql -U superz -d superz -Atc \"select phone from users where role = 'admin' order by id limit 1\")
for a in $NAMES; do
  echo \"=== \$a\"
  docker exec superz-api python -m scripts.publish_official_miniapp /tmp/\$a.zip \
    --listing /tmp/\$a-listing.json --reviewer \"\$REV\" $APPLY 2>&1 | tail -5
  docker exec superz-api rm -f /tmp/\$a.zip /tmp/\$a-listing.json
done"
if [ -n "$APPLY" ]; then
  echo "发完了。新应用(第一次发布)还要把 appid 签进托管域名证书:"
  echo "  部署机上 bash ~/super-z/deploy/mp-cert.sh(见 docs/MINIAPP-ROLLOUT.md 2.1)"
fi
