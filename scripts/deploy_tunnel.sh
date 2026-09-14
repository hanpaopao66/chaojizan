#!/bin/bash
# 部署机的 SSH 私密通道(frp stcp)。
#
# 部署机在家用宽带的局域网里,平时只能在那个网段里部署。这条通道让你在外面也能 ssh 过去,
# 而且**不在云服务器上多开任何公网端口**:stcp 只把流量转给持有同一把密钥的访问端
# (本机跑的 frpc),扫描器看不到这个服务。SSH 本身照旧只认密钥登录,部署机的主机密钥
# 照旧按局域网地址那一条核对(见 scripts/deploy_target.sh)。
#
#   bash scripts/deploy_tunnel.sh setup    一次性。**要在部署机所在的局域网里跑**
#   bash scripts/deploy_tunnel.sh up       起本机访问端(部署脚本连不上局域网时会自己调)
#   bash scripts/deploy_tunnel.sh down     停本机访问端
#   bash scripts/deploy_tunnel.sh status   看一眼
#
# 通道密钥只在两处:部署机的 deploy/tunnel/frpc.toml、本机的 deploy/tunnel/visitor.toml
# (都不入库,本机这份权限 600)。**脚本不打印任何密钥和令牌。**
# 要撤掉这条通道:删掉部署机 frpc.toml 里 superz-ssh 那一段,restart frpc;本机删 visitor.toml。
#
# macOS 自带 bash 3.2:别用关联数组。
set -eo pipefail
cd "$(dirname "$0")/.."

[ -f deploy/.env.deploy ] && . deploy/.env.deploy
DEPLOY=${DEPLOY:?缺部署机地址:在 deploy/.env.deploy 写 DEPLOY=user@host(不入库)}
HOST=${DEPLOY#*@}
PORT=${DEPLOY_TUNNEL_PORT:-6022}
CONF=deploy/tunnel/visitor.toml
PIDF=deploy/tunnel/.visitor.pid
LOGF=deploy/tunnel/.visitor.log
DEST='~/super-z'
PROXY_NAME=superz-ssh

running_pid() {
  [ -f "$PIDF" ] || return 1
  local pid
  pid=$(cat "$PIDF")
  # 只认自己起的那个 frpc:pid 被系统复用给了别的进程时不能当成「在跑」,更不能去杀它
  [ -n "$pid" ] && ps -p "$pid" -o comm= 2>/dev/null | grep -q frpc && echo "$pid"
}

cmd_up() {
  [ -f "$CONF" ] || { echo "✗ 本机没配私密通道($CONF)。先回到部署机所在局域网跑一次:bash scripts/deploy_tunnel.sh setup"; exit 1; }
  if running_pid >/dev/null; then
    echo "✓ 访问端已经在跑:127.0.0.1:$PORT"
    return 0
  fi
  local frpc
  frpc=$(command -v frpc) || { echo "✗ 本机没有 frpc(macOS:brew install frpc)"; exit 1; }
  nohup "$frpc" -c "$CONF" > "$LOGF" 2>&1 &
  echo $! > "$PIDF"
  for _ in $(seq 1 20); do
    if nc -z -G 1 127.0.0.1 "$PORT" 2>/dev/null; then
      echo "✓ 访问端起来了:127.0.0.1:$PORT(日志 $LOGF)"
      return 0
    fi
    sleep 0.5
  done
  echo "✗ 访问端 10 秒没起来,看 $LOGF"
  exit 1
}

cmd_down() {
  local pid
  if pid=$(running_pid); then
    kill "$pid" && echo "✓ 访问端已停"
  else
    echo "访问端没在跑"
  fi
  rm -f "$PIDF"
}

cmd_status() {
  if pid=$(running_pid); then
    echo "访问端在跑(pid $pid),本机 127.0.0.1:$PORT → 部署机 SSH"
  else
    echo "访问端没在跑"
  fi
  [ -f "$CONF" ] && echo "本机配置:$CONF" || echo "本机还没配(先在局域网里 setup)"
}

cmd_setup() {
  if ! nc -z -G 5 "$HOST" 22 2>/dev/null; then
    echo "✗ setup 要在部署机所在的局域网里跑(连不上 $HOST:22)。"
    echo "  它要改部署机上的 frpc 配置 —— 这一步只能在能直连部署机的时候做一次。"
    exit 1
  fi
  local remote_conf="$DEST/deploy/tunnel/frpc.toml"
  ssh "$DEPLOY" "test -f $remote_conf" || { echo "✗ 部署机上没有 deploy/tunnel/frpc.toml"; exit 1; }
  ssh "$DEPLOY" "test -w $remote_conf" || {
    echo "✗ 部署机上的 frpc.toml 当前用户写不了,先在部署机上把它的属主改成部署用户再来"; exit 1; }

  # frps 的地址、端口、令牌、用户名从部署机那份配置里读 —— 直接写进本机文件,不经过屏幕
  local lines addr sport token fuser
  lines=$(ssh "$DEPLOY" "grep -E '^[[:space:]]*(serverAddr|serverPort|user|auth\\.token)[[:space:]]*=' $remote_conf" || true)
  addr=$(printf '%s\n' "$lines" | sed -n 's/^[[:space:]]*serverAddr[[:space:]]*=[[:space:]]*//p' | head -1)
  sport=$(printf '%s\n' "$lines" | sed -n 's/^[[:space:]]*serverPort[[:space:]]*=[[:space:]]*//p' | head -1)
  token=$(printf '%s\n' "$lines" | sed -n 's/^[[:space:]]*auth\.token[[:space:]]*=[[:space:]]*//p' | head -1)
  fuser=$(printf '%s\n' "$lines" | sed -n 's/^[[:space:]]*user[[:space:]]*=[[:space:]]*//p' | head -1)
  [ -n "$addr" ] && [ -n "$sport" ] || { echo "✗ 部署机的 frpc.toml 里没找到 serverAddr / serverPort"; exit 1; }

  # 通道密钥:部署机上已经有这一段就沿用它的(重跑 setup 不换钥匙),没有就新生成
  local secret
  secret=$(ssh "$DEPLOY" "awk '/^\\[\\[proxies\\]\\]/{inblk=0} /name[[:space:]]*=[[:space:]]*\"$PROXY_NAME\"/{inblk=1} inblk && /secretKey/{print; exit}' $remote_conf" \
    | sed -n 's/.*secretKey[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p')
  if [ -z "$secret" ]; then
    secret=$(openssl rand -hex 24)
    echo "== 给部署机的 frpc 加上 SSH 私密通道(先备份原配置) =="
    ssh "$DEPLOY" "cp $remote_conf $remote_conf.bak-\$(date +%Y%m%d%H%M%S)"
    # 密钥走标准输入,不出现在任何一台机器的命令行参数里
    ssh "$DEPLOY" "cat >> $remote_conf" <<EOF

# 部署机 SSH 的私密通道(scripts/deploy_tunnel.sh setup 加的)。stcp 不在 frps 上开公网端口,
# 只转给持有同一把 secretKey 的访问端。要撤掉:删掉这一段,restart frpc。
[[proxies]]
name = "$PROXY_NAME"
type = "stcp"
secretKey = "$secret"
localIP = "127.0.0.1"
localPort = 22
EOF
    echo "== 重启 frpc(网站经隧道的访问会断一两秒) =="
    ssh "$DEPLOY" "cd $DEST/deploy && docker compose -f docker-compose.prod.yml --env-file .env.prod restart frpc"
  else
    echo "== 部署机上已经有这条通道,沿用原来的密钥 =="
  fi

  echo "== 写本机访问端配置 $CONF(权限 600,不入库) =="
  (umask 077; {
    echo "# 本机的 frp 访问端:把部署机的 SSH 私密通道接到本机 127.0.0.1:$PORT。不入库、不要外传。"
    echo "serverAddr = $addr"
    echo "serverPort = $sport"
    [ -n "$token" ] && echo "auth.token = $token"
    echo ""
    echo "[[visitors]]"
    echo "name = \"superz-ssh-visitor\""
    echo "type = \"stcp\""
    echo "serverName = \"$PROXY_NAME\""
    [ -n "$fuser" ] && echo "serverUser = $fuser"
    echo "secretKey = \"$secret\""
    echo "bindAddr = \"127.0.0.1\""
    echo "bindPort = $PORT"
  } > "$CONF")
  chmod 600 "$CONF"

  cmd_down >/dev/null 2>&1 || true
  cmd_up
  echo "== 从通道 ssh 一次试试(主机密钥按 $HOST 那一条核对) =="
  local ok=0
  for _ in 1 2 3 4 5; do
    if ssh -p "$PORT" -o HostKeyAlias="$HOST" -o BatchMode=yes -o ConnectTimeout=10 \
        "${DEPLOY%@*}@127.0.0.1" true 2>/dev/null; then ok=1; break; fi
    sleep 2
  done
  [ "$ok" = 1 ] || { echo "✗ 通道起来了但 ssh 过不去,看 $LOGF 和部署机的 frpc 日志(docker logs deploy-frpc-1)"; exit 1; }
  echo "✓ 私密通道通了。以后在外面直接跑 scripts/deploy_server.sh,连不上局域网时会自动走通道。"

  # 顺手看一眼部署机 SSH 是否还允许密码登录 —— 只报告不改(改错了会把自己锁在外面)
  local pw
  pw=$(ssh "$DEPLOY" "grep -hEi '^[[:space:]]*PasswordAuthentication' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null | tail -1" || true)
  case "$pw" in
    *[Nn][Oo]*) echo "✓ 部署机 SSH 已关掉密码登录" ;;
    *) echo "⚠ 部署机 SSH 可能还允许密码登录(${pw:-没写,按系统默认})。建议在部署机上把 PasswordAuthentication 设成 no,只留密钥" ;;
  esac
}

case "${1:-}" in
  setup) cmd_setup ;;
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  *) sed -n '2,17p' "$0"; exit 1 ;;
esac
