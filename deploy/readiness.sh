#!/usr/bin/env bash
# 生产就绪体检(#131):把"哪些外部依赖没配、降级成了什么、影响谁"打成一张表。
#
# 为什么需要它:这些集成早就写好且能优雅降级,问题是**降级了但没人知道**。
# 最典型的一次 —— 骑手新单推送做完验收全绿,而生产上 JPUSH 没配,
# 一条都发不出去:功能"存在"和功能"有效"完全脱节。
#
# 用法(在部署机上):
#     deploy/readiness.sh
# 建议每次发版后跑一眼。
set -uo pipefail
cd "$(dirname "$0")"

API="${API:-http://127.0.0.1:8010}"
ADMIN_PHONE="${ADMIN_PHONE:-}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"

if [ -z "$ADMIN_TOKEN" ]; then
  echo "需要管理员 token(体检包含配置状态,不对外开放)。两种给法:"
  echo "  ADMIN_TOKEN=xxx deploy/readiness.sh"
  echo "  或在管理后台登录后从浏览器里复制"
  exit 1
fi

resp=$(curl -s -m 20 -H "Authorization: Bearer $ADMIN_TOKEN" "$API/admin/readiness")
echo "$resp" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("拿不到体检结果(token 失效?):", sys.stdin.read()[:200]); raise SystemExit(1)

print(f"外部依赖 {d[\"total\"]} 项,已配置 {d[\"configured\"]},未配置 {d[\"missing\"]}\n")
for it in d["items"]:
    mark = "✓" if it["configured"] else "✗"
    print(f"{mark} {it[\"key\"]}")
    if not it["configured"]:
        print(f"    降级后:{it[\"degraded_behavior\"]}")
        print(f"    影响:  {it[\"affects\"]}")
    if it.get("note"):
        print(f"    备注:  {it[\"note\"]}")
print()
print("未配置的项不是错误 —— 但每一条都意味着某个功能在线上是残的。")
'
