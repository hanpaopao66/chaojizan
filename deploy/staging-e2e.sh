#!/usr/bin/env bash
# 在预发上跑 e2e 套件(docs/STAGING.md)。在**预发机**上跑:
#
#   bash ~/super-z-staging/deploy/staging-e2e.sh e2e_miniapp_catalog [e2e_xxx ...]
#
# 测试代码临时拷进 api 容器(镜像里本来不带 tests),在容器里直连 api(不过门禁),跑完删掉。
# 用例会在预发库里造数据(新号、测试小程序、订单)—— 预发本来就是开发配置 + 演示数据,不要紧;
# 目录里会多出测试用的小程序,要清的话在后台下架。
#
# 演示账号口令:预发播种时随机生成、写在 staging-gate/seed.log,这里就地读出来交给用例
# (和 CI 用 SEED_DEMO_PASSWORD 同一个办法),不打印。
set -uo pipefail
cd "$(dirname "$0")"
[ -d /opt/homebrew/bin ] && export PATH="/opt/homebrew/bin:$PATH"
[ $# -gt 0 ] || { echo "用法: $0 <套件名>..."; exit 2; }
PW=$(grep -oE '随机生成:[A-Za-z0-9_-]+' staging-gate/seed.log 2>/dev/null | head -1 | cut -d: -f2)
[ -n "$PW" ] || { echo "✗ staging-gate/seed.log 里没有演示口令(预发是不是还没灌过演示数据?)"; exit 2; }
docker cp ../server/tests superz-api:/srv/tests >/dev/null
trap 'docker exec superz-api rm -rf /srv/tests' EXIT
fail=0
for s in "$@"; do
  case "$s" in *[!a-z0-9_]*) echo "✗ 套件名不对: $s"; fail=1; continue ;; esac
  echo "== $s"
  # 先落文件再看:判定用退出码,不能拿 tail 看尾行(前面报错、后面的 ✓ 照样打印)
  if docker exec -w /srv -e SUPERZ_API=http://127.0.0.1:8000 -e SEED_DEMO_PASSWORD="$PW" superz-api \
      python -m "tests.$s" > "/tmp/staging-e2e-$s.log" 2>&1; then
    grep -E "✓" "/tmp/staging-e2e-$s.log" | tail -30
    echo "   通过"
  else
    tail -30 "/tmp/staging-e2e-$s.log"
    echo "   ✗ 失败,完整输出在 /tmp/staging-e2e-$s.log"
    fail=1
  fi
done
exit $fail
