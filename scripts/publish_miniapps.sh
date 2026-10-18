#!/usr/bin/env bash
# 批量发布官方小游戏到生产:本地 build_miniapp 产物 → 部署机 → api 容器 → publish 脚本。
#
#   scripts/publish_miniapps.sh tower                    # 只看计划(不写库、不传对象)
#   scripts/publish_miniapps.sh --apply tower cards      # 真发布(tower 第一次会自动建应用)
#
# 走 deploy/.env.deploy 里的部署机(局域网连不上时自动走 deploy_tunnel 私密通道),
# 在 api 容器里用 server/scripts/publish_official_miniapps_batch.py 发布:
# 同一个包校验器、同一个状态机、同一条审核记录(审核人 = 第一个管理员),不放后门。
# 真发布后自动跑 deploy/mp-cert.sh:新 appid 会签进托管证书(没变化就什么都不做)。
#
# ⚠ 改生产数据,跑 --apply 之前要先征得运营方同意。
set -eo pipefail
cd "$(dirname "$0")/.."

[ -f deploy/.env.deploy ] && . deploy/.env.deploy
DEPLOY=${DEPLOY:?缺部署机地址:在 deploy/.env.deploy 写 DEPLOY=user@host}
. scripts/deploy_target.sh
deploy_target || exit 1
echo "== 连部署机:$DEPLOY_VIA =="

apply=0
apps=()
for a in "$@"; do
  case "$a" in
    --apply) apply=1 ;;
    *) apps+=("$a") ;;
  esac
done
if [ ${#apps[@]} -eq 0 ]; then
  echo "用法:$0 [--apply] <app...>   (app 见 miniapps/ 下带 listing.json 的目录)"
  exit 2
fi

# ---- 1. 本地检查:每个应用都要有构建产物和元数据,并打印 SHA(和线上详情页公示的对得上) ----
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
for app in "${apps[@]}"; do
  zip="miniapps/$app/dist/$app.zip"
  listing="miniapps/$app/listing.json"
  [ -f "$zip" ] || { echo "✗ 缺 $zip,先跑 bash scripts/build_miniapp.sh $app"; exit 2; }
  [ -f "$listing" ] || { echo "✗ 缺 $listing"; exit 2; }
  cp "$zip" "$tmp/$app.zip"
  cp "$listing" "$tmp/$app-listing.json"
  sha="$(python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$zip")"
  size="$(wc -c < "$zip" | tr -d ' ')"
  echo "  $app  ${size} 字节  SHA-256 $sha"
done
echo "== 本地包检查通过 =="

# ---- 2. 传到部署机,再拷进 api 容器 ----
remote=/tmp/sz-publish
ssh $SSH_OPTS "$DEPLOY" "rm -rf $remote && mkdir -p $remote"
scp $SCP_OPTS "$tmp"/* "$DEPLOY:$remote/" >/dev/null
# 批量发布脚本本身也带过去(不用为了发布重新部署服务端;它只是调用容器里已有的发布函数)
scp $SCP_OPTS server/scripts/publish_official_miniapps_batch.py "$DEPLOY:$remote/publish_official_miniapps_batch.py" >/dev/null
echo "== 已传到部署机:$remote =="

ssh $SSH_OPTS "$DEPLOY" "cd ~/super-z/deploy && \
  docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T api sh -c 'rm -rf /tmp/sz-publish && mkdir -p /tmp/sz-publish' && \
  docker compose -f docker-compose.prod.yml --env-file .env.prod cp $remote/. api:/tmp/sz-publish/ >/dev/null && \
  docker cp $remote/publish_official_miniapps_batch.py superz-api:/tmp/publish_official_miniapps_batch.py >/dev/null && \
  echo '== 已拷进 api 容器 =='"

# ---- 3. 发布(不带 --apply 只看计划) ----
apply_arg=""
[ "$apply" = 1 ] && apply_arg="--apply"
ssh $SSH_OPTS "$DEPLOY" "cd ~/super-z/deploy && \
  docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T -w /srv -e PYTHONPATH=/srv api \
    python /tmp/publish_official_miniapps_batch.py --dir /tmp/sz-publish $apply_arg"

# ---- 4. 清理容器里的临时文件(不把包和 listing 留在生产容器 /tmp) ----
ssh $SSH_OPTS "$DEPLOY" "cd ~/super-z/deploy && \
  docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T api \
    sh -c 'rm -rf /tmp/sz-publish /tmp/publish_official_miniapps_batch.py' >/dev/null 2>&1 || true"

if [ "$apply" = 1 ]; then
  # ---- 5. 新 appid 进托管证书(没变化又没到期,脚本自己会跳过) ----
  echo "== 更新托管证书(新 appid 会签进去) =="
  ssh $SSH_OPTS "$DEPLOY" "bash ~/super-z/deploy/mp-cert.sh" | tail -5
  echo
  echo "== 发布完成。上线后复核:匿名目录 / 详情页 / 托管页 200+CSP / TLS / 无头 Chrome 打开 =="
  echo "   docs/MINIAPP-GAMES.md 里的 appid 与 SHA-256 记得同步更新。"
else
  echo
  echo "== 这只是计划。确认后加 --apply 真发布(改生产数据)。=="
fi
