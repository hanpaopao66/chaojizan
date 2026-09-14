# 部署机怎么连:给 deploy_server.sh、sync_release_to_appdist.sh source 进去,调 deploy_target。
#
# 先试局域网(和从前一样);够不着、而本机配过 SSH 私密通道(scripts/deploy_tunnel.sh setup
# 写的 deploy/tunnel/visitor.toml)时,起本机访问端、改走通道。两条路都不通就明说,
# 别烧满 SSH 超时再死在 rsync / scp 中途(那时版本号已经写进 server/app_version.txt 了)。
#
# 调完之后可用:
#   DEPLOY      ssh 的目标(走通道时是 user@127.0.0.1)
#   SSH_OPTS    给 ssh 的额外参数(走通道时:端口、HostKeyAlias)—— 用的时候**不加引号**,要按空格拆
#   SCP_OPTS    给 scp 的
#   RSYNC_RSH   给 rsync -e 的
#   DEPLOY_VIA  这次走的哪条路(打印给人看)
#
# 走通道时,部署机的主机密钥**照旧按局域网地址那一条核对**(HostKeyAlias):通道那头要是换成了
# 别的机器,ssh 当场拒绝,而不是把代码和 APK 悄悄推给它。
# macOS 自带 bash 3.2:别用关联数组。

deploy_target() {
  local host=${DEPLOY#*@} user=${DEPLOY%@*}
  local port=${DEPLOY_TUNNEL_PORT:-6022}
  SSH_OPTS=""
  SCP_OPTS=""
  RSYNC_RSH="ssh"
  if nc -z -G 5 "$host" 22 2>/dev/null; then
    DEPLOY_VIA="局域网 $host"
    return 0
  fi
  if [ ! -f deploy/tunnel/visitor.toml ]; then
    echo "✗ 连不上部署机 $host:22,本机也没配私密通道。"
    echo "  本机地址:$(ipconfig getifaddr en0 2>/dev/null || echo 未知)"
    echo "  回到部署机所在局域网,或者在局域网里先跑一次 bash scripts/deploy_tunnel.sh setup,"
    echo "  以后在外面也能部署。线上服务不受影响,还是原来那版。"
    return 1
  fi
  echo "== 局域网连不上,改走 SSH 私密通道 =="
  bash scripts/deploy_tunnel.sh up || return 1
  SSH_OPTS="-p $port -o HostKeyAlias=$host -o ConnectTimeout=15 -o ServerAliveInterval=15"
  SCP_OPTS="-P $port -o HostKeyAlias=$host -o ConnectTimeout=15 -o ServerAliveInterval=15"
  RSYNC_RSH="ssh $SSH_OPTS"
  DEPLOY="$user@127.0.0.1"
  local ok=0
  for _ in 1 2 3 4 5; do
    # shellcheck disable=SC2086
    if ssh $SSH_OPTS -o BatchMode=yes "$DEPLOY" true 2>/dev/null; then ok=1; break; fi
    sleep 2
  done
  if [ "$ok" != 1 ]; then
    echo "✗ 私密通道起来了,但 ssh 过不去(看 deploy/tunnel/.visitor.log)。"
    echo "  可能是部署机那头的 frpc 没在跑,或者通道密钥两边对不上。线上不受影响。"
    return 1
  fi
  DEPLOY_VIA="私密通道(本机 127.0.0.1:$port → 部署机,主机密钥按 $host 核对)"
}
