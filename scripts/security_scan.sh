#!/usr/bin/env bash
# 开源发布前安全扫描(M6):扫密钥/密码/内网 IP/隧道细节。
#
# 用法:
#   ./scripts/security_scan.sh [目标目录]     # 默认扫当前仓库的 git 跟踪文件
#
# 公开仓导出脚本(export_public_repo.sh)会自动调用本脚本把关,
# 有任何发现直接失败退出——安全扫描不过,仓库不出门。
set -uo pipefail

TARGET="${1:-.}"
cd "$TARGET"

# 允许的例外(演示数据/文档中的假值),按行号精确豁免太脆,用内容模式豁免:
#  - 1380000000x / 139/137/136+时间戳:演示与测试专用号段
#  - change-me-in-production:默认值本身就是提醒
#  - example/示例/演示 上下文中的占位
PATTERNS=(
  # 密钥与凭证
  'BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY'
  'api[_-]?key\s*[:=]\s*["'"'"'][A-Za-z0-9]{16,}'
  'secret\s*[:=]\s*["'"'"'][A-Za-z0-9]{16,}'
  'AKIA[0-9A-Z]{16}'                    # AWS
  'sk-[A-Za-z0-9]{20,}'                 # OpenAI 风格
  # 微信支付真实凭据(商户号只应存在于 .env,不入库)
  'mchid.{0,20}17[0-9]{8}'
  '1711302420'
  # 内网与隧道细节(10.0.2.2 是 Android 模拟器标准回环别名,不算)。
  # frp 本身是公开架构(deploy/ 随仓发布),要拦的是具体 IP 与隧道 token
  '192\.168\.[0-9]+\.[0-9]+'
  '8\.140\.31\.213'
  'auth\.token\s*='
  'wanli'
  # 生产环境痕迹
  'POSTGRES_PASSWORD\s*[:=]\s*[^$?{]'   # 写死的密码(引用变量的不算)
  'JWT_SECRET\s*[:=]\s*[^$?{c]'         # 同上(change-me 默认值放行)
)

# 已知的开发环境默认值(本地 docker 演示用,公开无害),从命中里过滤;
# ${VAR:?} 形式的环境变量引用(compose 占位,真值在 .env.prod)不是密钥,放行
DEV_DEFAULT_FILTER='(POSTGRES_PASSWORD[": =]+((superz)|(drill)))|(change-me-in-production)|(\$\{(POSTGRES_PASSWORD|JWT_SECRET)[:}?])'

# 排除:二进制/锁文件/构建产物/本脚本自身
EXCLUDES=(
  ':!*.png' ':!*.jpg' ':!*.m4a' ':!*.jar' ':!*.lock' ':!pubspec.lock'
  ':!scripts/security_scan.sh' ':!scripts/export_public_repo.sh'
)

found=0
for pattern in "${PATTERNS[@]}"; do
  if git ls-files >/dev/null 2>&1; then
    hits=$(git grep -InE "$pattern" -- . "${EXCLUDES[@]}" 2>/dev/null \
           | grep -vE "$DEV_DEFAULT_FILTER")
  else
    hits=$(grep -rInE "$pattern" . \
      --exclude-dir=.git --exclude-dir=build --exclude-dir=.venv \
      --exclude-dir=__pycache__ --exclude-dir=.dart_tool \
      --exclude='*.png' --exclude='*.jpg' --exclude='*.m4a' \
      --exclude='*.jar' --exclude='*.lock' \
      --exclude='security_scan.sh' --exclude='export_public_repo.sh' \
      2>/dev/null | grep -vE "$DEV_DEFAULT_FILTER")
  fi
  if [ -n "$hits" ]; then
    echo "✗ 命中模式: $pattern"
    echo "$hits" | head -10
    echo
    found=1
  fi
done

if [ "$found" -eq 1 ]; then
  echo "===== 安全扫描发现问题,处理后重跑 ====="
  exit 1
fi
echo "✓ 安全扫描通过:无密钥/内网 IP/隧道细节/真实凭据"
