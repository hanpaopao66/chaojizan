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
#
# ⚠️ 空白一律写 POSIX 的 [[:space:]],**不许写 `\s`**(下面有自检拦着)。
#    macOS 的 `git grep -E` 不认 `\s`,会把它当字面量 `s` —— 于是
#    `key\s*=` 在开发机上实际匹配的是 `key=`/`keyss=`,**带空格的
#    `key = "真密钥"` 静默漏过**,而 TOML/YAML 恰恰都这么写。
#    表现:开发机全绿、Linux CI 才报,本地这道闸形同虚设 ——
#    比没有这道闸更坏,因为大家以为它在守着(2026-08-18 由 CI 抓出)。
PATTERNS=(
  # 密钥与凭证
  'BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY'
  'api[_-]?key[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9]{16,}'
  'secret[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9]{16,}'
  'AKIA[0-9A-Z]{16}'                    # AWS
  'sk-[A-Za-z0-9]{20,}'                 # OpenAI 风格
  # 微信支付真实凭据(商户号只应存在于 .env,不入库)
  'mchid.{0,20}17[0-9]{8}'
  '1711302420'
  # 内网与隧道细节(10.0.2.2 是 Android 模拟器标准回环别名,不算)。
  # frp 本身是公开架构(deploy/ 随仓发布),要拦的是具体 IP 与隧道 token
  '192\.168\.[0-9]+\.[0-9]+'
  '8\.140\.31\.213'
  # 等号后必须有实质内容才算命中:样例文件里的空值(auth.token = "")
  # 是给自部署者照着填的,拦它只会逼人不写样例
  'auth\.token[[:space:]]*=[[:space:]]*["'"'"']?[A-Za-z0-9]'
  'wanli'
  'aikas'    # 历史域名:保留访问但不明文出现
  # 地图 key。腾讯地图是 5 组 5 位、连字符分隔的固定形态,拦得住;
  # 天地图/高德是 32 位十六进制,和一堆哈希撞形,所以按变量名拦
  '[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}'
  # 按变量名拦时**必须同时要求值长得像真 key**(16 位以上十六进制),
  # 否则 `--dart-define=AMAP_KEY=你的Key` 这种文档占位符全是误报,
  # 误报多了就没人看扫描结果,等于没有扫描
  'TENCENT_MAP_KEY[[:space:]]*[:=][[:space:]]*[A-Z0-9-]{20,}'
  'TIANDITU_[A-Z_]*KEY[[:space:]]*[:=][[:space:]]*[0-9a-fA-F]{16,}'
  'AMAP_[A-Z_]*KEY[[:space:]]*[:=][[:space:]]*[0-9a-fA-F]{16,}'
  # 生产环境痕迹
  'POSTGRES_PASSWORD[[:space:]]*[:=][[:space:]]*[^$?{[:space:]]'  # 写死的密码(引用变量的不算)
  'JWT_SECRET[[:space:]]*[:=][[:space:]]*[^$?{c[:space:]]'        # 同上(change-me 默认值放行)
)

# 自检一:模式里不许有 `\s`(理由见上面 PATTERNS 的注释)。
# 静默半瞎的扫描器比没有扫描器更坏,所以这里宁可整个脚本失败
for p in "${PATTERNS[@]}"; do
  case "$p" in
    *'\s'*)
      echo "✗ 模式含 \\s:$p"
      echo "  macOS 的 git grep -E 不认 \\s,会静默漏掉带空格的写法。"
      echo "  改用 POSIX 字符类 [[:space:]]。"
      exit 2
      ;;
  esac
done

# 自检二:确认当前引擎真的按预期匹配(引擎换了/环境变了立刻暴露,
# 而不是等某天真密钥漏出去才发现)
# (git grep --no-index 只认相对路径,所以要 cd 进临时目录跑)
_probe_dir=$(mktemp -d)
printf 'probe.token = "abc123"\n' > "$_probe_dir/probe.txt"
_probe_hit=$(cd "$_probe_dir" && git grep --no-index -IhE \
  'probe\.token[[:space:]]*=[[:space:]]*["'"'"']?[A-Za-z0-9]' -- probe.txt 2>/dev/null)
rm -rf "$_probe_dir"
if [ -z "$_probe_hit" ]; then
  echo "✗ 正则引擎自检失败:[[:space:]] 没能匹配到带空格的赋值"
  echo "  这台机器上的扫描结果不可信,先修引擎再提交。"
  exit 2
fi

# 已知的开发环境默认值(本地 docker 演示用,公开无害),从命中里过滤;
# ${VAR:?} 形式的环境变量引用(compose 占位,真值在 .env.prod)不是密钥,放行
DEV_DEFAULT_FILTER='(POSTGRES_PASSWORD[": =]+((superz)|(drill)))|(change-me-in-production)|(\$\{(POSTGRES_PASSWORD|JWT_SECRET)[:}?])'

# 排除:二进制/锁文件/构建产物/本脚本自身。
#
# e2e_printers.py 里有一串内网地址,那是 **SSRF 防护的测试用例** ——
# 它断言 validate_url 会拒掉 169.254 元数据服务、127.0.0.1、10.x、192.168.x。
# 那些地址必须写在那儿,删了这条防护就没人守了。
#
# ⚠️ 豁免的是**这一个文件**,不是整个 tests/ 目录:测试里照样可能不小心
# 粘进真的内网地址或密钥,那种必须拦。
EXCLUDES=(
  ':!*.png' ':!*.jpg' ':!*.m4a' ':!*.jar' ':!*.lock' ':!pubspec.lock'
  ':!scripts/security_scan.sh' ':!scripts/export_public_repo.sh'
  ':!server/tests/e2e_printers.py'
)

found=0
for pattern in "${PATTERNS[@]}"; do
  if git ls-files >/dev/null 2>&1; then
    # -I 跳过二进制;--untracked 把「还没 add 但也没被 ignore」的新文件一起扫。
    # 少了 --untracked 的话,新写的文件要等到 add 之后才进扫描范围 ——
    # 而 `git add -A && git commit` 是一步完成的,那时已经晚了
    hits=$(git grep -InE --untracked "$pattern" -- . "${EXCLUDES[@]}" 2>/dev/null \
           | grep -vE "$DEV_DEFAULT_FILTER")
  else
    hits=$(grep -rInE "$pattern" . \
      --exclude-dir=.git --exclude-dir=build --exclude-dir=.venv \
      --exclude-dir=__pycache__ --exclude-dir=.dart_tool \
      --exclude='*.png' --exclude='*.jpg' --exclude='*.m4a' \
      --exclude='*.jar' --exclude='*.lock' \
      --exclude='security_scan.sh' --exclude='export_public_repo.sh' \
      --exclude='e2e_printers.py' \
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
