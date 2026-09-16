#!/bin/bash
# 把某个 GitHub Release 的产物原样同步到部署机，并更新 versions.json:
#   - 三端 APK、Windows / macOS / Ubuntu 桌面包 → appdist(官网下载页、App 内更新读它);
#   - 用户端网页版 → 解压到 ~/super-z/webapp/releases/<tag>/,切 current 软链(nginx 的 /web/)。
#
# 用法: scripts/sync_release_to_appdist.sh v0.12.1-b2052 "更新说明一句话"
#
# 版本门禁(环境变量,默认与从前一致):
#   FORCE=1        这一版强制更新(versions.json 的 force=true)
#   MIN_BUILD=<n>  低于这个 build 的客户端视为过旧
#
# 和 release_apks.sh 是同一套参数 —— 这两个脚本都会写 versions.json,
# 只有一个支持门禁的话,用哪条路发版决定了门禁生不生效,那是最坏的一种不一致。
#
# ## 为什么要有这个脚本
#
# #274 把发版的信任根从开发机换成了公开 CI：APK 由 release.yml 在公开 runner
# 上从 tag 构建，SHA-256 写进 Release 附件，Release 正文里写着
# 「官网下载页与应用内更新走 appdist 通道，由运维把**本页同一批产物**同步过去
#   —— 两边哈希应当一致，不一致请立刻开 issue」。
#
# 但当时只做到「CI 出包发 Release」，没人把那一批产物送到 appdist ——
# 而 release_apks.sh **永远本地重打**。用它去同步的话，appdist 上是开发机
# 编出来的另一份包，哈希和 Release 页对不上，等于自己打脸自己写的那句话。
#
# 所以这个脚本只做搬运，不碰编译器：
#   下载 Release 附件 → 用附件里的 SHA256SUMS.txt 核一遍 → scp 到部署机(先落 .part)
#   → 落地再核一遍 → 全部核过才改名上线 → 写 versions.json。
# 网页版和桌面包是同一个 Release 里的同一批产物,走同一套核对,不另开口子。
#
# 老版本的 Release(还没有网页版和桌面包的)照样能同步:只搬 APK,
# versions.json 里桌面版、网页版的条目保持上一次的,不会被抹掉。
#
# ## 前提
#
#   - release.yml 已经跑完并发布了该 tag 的 Release（gh release view 能看到）；
#   - 本机在部署机同一网段（LAN-only，见 deploy/.env.deploy）。
set -eo pipefail
cd "$(dirname "$0")/.."

TAG=${1:?用法: sync_release_to_appdist.sh <tag，如 v0.12.1-b2052> <更新说明>}
NOTES=${2:?缺更新说明（会写进 versions.json，旧版 App 的更新弹窗里显示）}

[ -f deploy/.env.deploy ] && . deploy/.env.deploy
API=${PUBLIC_BASE:?缺 PUBLIC_BASE：写在 deploy/.env.deploy（不入库）}
DEPLOY=${DEPLOY:?缺 DEPLOY=user@host：写在 deploy/.env.deploy（不入库）}
# ⚠️ 先去 .git 后缀再截 owner/repo,不能靠 (\.git)? 可选组 ——
# [^/]+ 是贪婪的,会把 .git 一起吞进捕获组,解析成 owner/repo.git,
# 然后 gh release download 报 "release not found"(第一次跑就踩到了)
REPO=$(git remote get-url origin | sed -E 's#\.git$##; s#.*[:/]([^/]+/[^/]+)$#\1#')

# tag 形如 v0.12.1-b2052 —— 版本号和 build 号都从它解析，
# 不另外传参：两处各写一遍迟早会写岔，而写岔的后果是
# versions.json 说 build 2052、APK 里其实是 2051，已装用户永远收不到更新
VERSION="${TAG#v}"; VERSION="${VERSION%-b*}"
BUILD="${TAG##*-b}"
echo "$BUILD" | grep -qE '^[0-9]+$' || { echo "✗ tag 里解析不出 build 号：$TAG"; exit 1; }
# 版本号会拼进路径和 Python 字面量,只收 x.y.z
echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$' || { echo "✗ tag 里解析不出版本号：$TAG"; exit 1; }

# 门禁参数。默认 false / 0 = 与改造前完全一致的行为
FORCE_JSON=false
[ "${FORCE:-0}" = "1" ] && FORCE_JSON=true
# ⚠️ Python 的布尔字面量首字母大写。直接把 shell 的 `false` 插进下面那段
# python3 里会是个**未定义的名字**,而它炸的位置正是本脚本注释里点过名的
# 那个最坏时机:**包已经传上去、versions.json 还没改**
# (2026-08-23 发 v0.13.0 时踩到)。显示仍用小写,写进代码的用这个
FORCE_PY=False
[ "$FORCE_JSON" = true ] && FORCE_PY=True
MIN_BUILD=${MIN_BUILD:-0}
echo "$MIN_BUILD" | grep -qE '^[0-9]+$' || {
  echo "✗ MIN_BUILD 必须是数字，收到：$MIN_BUILD"; exit 1; }
# min_build 大于本次 build 的话，新包自己都过不了门禁
[ "$MIN_BUILD" -le "$BUILD" ] || {
  echo "✗ MIN_BUILD($MIN_BUILD) 大于本次 build($BUILD)，这会把新版自己也挡在门外"
  exit 1; }

echo "== 同步 $TAG（版本 $VERSION，build $BUILD，force=$FORCE_JSON，min_build=$MIN_BUILD）=="

# 先探部署机通不通，别烧满 SSH 超时再死在 scp 中途（deploy_server.sh 同款预检）。
# 局域网不通时改走 SSH 私密通道（配过的话，见 scripts/deploy_target.sh）
. scripts/deploy_target.sh
deploy_target || exit 1
echo "== 连部署机：$DEPLOY_VIA =="

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

echo "== 下载 Release 附件 =="
# chaojizan-* 一把全拿:APK、网页版、桌面包。SHA256SUMS.txt 里列的每一个都得在,
# 下面 shasum -c 才核得过 —— 只挑一部分下载的话,没下的那几个会被报成缺文件
# **重试三次。** 一把拿 9 个附件(最大的 57MB)时 gh 是并发下的,网络抖一下就是
# 一句 `unexpected EOF`,整条发版流程停在这儿。2026-09-16 连着撞了两次,
# 而单个文件重下都是好的 —— 所以是并发 + 网络,不是文件坏了。
# 下载失败不改线上任何东西,重试是安全的(真坏了下面 shasum -c 那道闸会拦)。
for try in 1 2 3; do
  rm -rf "$WORK"/chaojizan-* "$WORK"/SHA256SUMS.txt
  if gh release download "$TAG" -R "$REPO" -D "$WORK" \
      -p 'chaojizan-*' -p 'SHA256SUMS.txt'; then
    break
  fi
  [ "$try" = 3 ] && { echo "✗ 附件下了三次都没下全,先看网络"; exit 1; }
  echo "  第 $try 次没下全,5 秒后重来"
  sleep 5
done

echo "== 核对 CI 写下的 SHA-256（下载途中坏了在这里拦）=="
( cd "$WORK" && shasum -a 256 -c SHA256SUMS.txt ) || {
  echo "✗ 附件哈希和 SHA256SUMS.txt 对不上，中止"; exit 1; }

# 要搬的每个文件都必须**列在** SHA256SUMS.txt 里。shasum -c 只核清单上的文件 ——
# 有人往 Release 里手工补传一个清单外的包,上面那一步照样是绿的
listed() { awk '{print $2}' "$WORK/SHA256SUMS.txt" | sed 's/^\*//' | grep -qx "$1"; }

for app in user merchant rider; do
  [ -f "$WORK/chaojizan-${app}-arm64.apk" ] || {
    echo "✗ Release 里没有 chaojizan-${app}-arm64.apk"; exit 1; }
  listed "chaojizan-${app}-arm64.apk" || {
    echo "✗ chaojizan-${app}-arm64.apk 不在 SHA256SUMS.txt 里，来路不明，中止"; exit 1; }
done

# 网页版 + 桌面包:要么一个都没有(老版本的 Release、急修时关了桌面构建),要么五个都齐。
# 缺一半说明 Release 被动过手脚或 CI 出了岔子,宁可停下来
EXTRA_FILES="chaojizan-web.tar.gz chaojizan-windows-x64.zip chaojizan-macos.dmg chaojizan-linux-x64.tar.gz chaojizan-linux-x64.deb"
have=0; total=0
for f in $EXTRA_FILES; do
  total=$((total + 1))
  if [ -f "$WORK/$f" ]; then have=$((have + 1)); fi
done
if [ "$have" -eq 0 ]; then
  HAS_EXTRA=0
  echo "  这一版没有网页版和桌面包:只同步 APK,versions.json 里桌面版和网页版的条目保持上一次的"
elif [ "$have" -eq "$total" ]; then
  HAS_EXTRA=1
  for f in $EXTRA_FILES; do
    listed "$f" || { echo "✗ $f 不在 SHA256SUMS.txt 里，来路不明，中止"; exit 1; }
  done
  echo "  网页版 + 三个桌面包 ✓"
else
  echo "✗ 网页版和桌面包只有 $have / $total 个 —— Release 不完整，中止（线上还是原来那版）"
  exit 1
fi

# versionCode 必须和 tag 里的 build 平码。CI 已经验过一道，
# 这里再验一道是因为**搬运的是文件不是信任**：万一 tag 和附件对不上
# （手工传过附件、Release 被编辑过），错的包一旦进了 appdist，
# 已装用户就再也收不到更新提示了
if command -v aapt2 >/dev/null 2>&1 || [ -n "${ANDROID_HOME:-}" ]; then
  AAPT=$(command -v aapt2 || ls "$ANDROID_HOME"/build-tools/*/aapt2 2>/dev/null | tail -1)
  if [ -n "$AAPT" ]; then
    for app in user merchant rider; do
      CODE=$("$AAPT" dump badging "$WORK/chaojizan-${app}-arm64.apk" \
             | head -1 | sed -n "s/.*versionCode='\([0-9]*\)'.*/\1/p")
      [ "$CODE" = "$BUILD" ] || {
        echo "✗ ${app} 包里 versionCode=$CODE，而 tag 说 build=$BUILD"; exit 1; }
    done
    echo "  versionCode 平码 ✓"
  fi
else
  echo "  (本机没有 aapt2，跳过 versionCode 复核 —— CI 那道闸已经验过)"
fi

# 要上传的文件:<Release 里的文件名>:<部署机上的目标路径(相对 ~/super-z)>:<变量名后缀>
# ⚠️ 不用关联数组（declare -A）—— macOS 自带的是 bash 3.2，没有这东西。
# 踩过一次：它会在**包已经传上去、versions.json 还没改**的那一刻炸，
# 是最坏的时机。release_apks.sh 用 SHA_<端> 这套写法也是这个原因
UPLOADS="chaojizan-user-arm64.apk:appdist/chaojizan-user-arm64.apk:user
chaojizan-merchant-arm64.apk:appdist/chaojizan-merchant-arm64.apk:merchant
chaojizan-rider-arm64.apk:appdist/chaojizan-rider-arm64.apk:rider"
if [ "$HAS_EXTRA" = 1 ]; then
  UPLOADS="$UPLOADS
chaojizan-windows-x64.zip:appdist/chaojizan-windows-x64.zip:windows
chaojizan-macos.dmg:appdist/chaojizan-macos.dmg:macos
chaojizan-linux-x64.tar.gz:appdist/chaojizan-linux-x64.tar.gz:linux
chaojizan-linux-x64.deb:appdist/chaojizan-linux-x64.deb:deb
chaojizan-web.tar.gz:webapp/releases/$TAG.tar.gz:web"
fi

for line in $UPLOADS; do
  f=${line%%:*}; key=${line##*:}
  eval "SHA_${key}=\$(shasum -a 256 \"\$WORK/\$f\" | awk '{print \$1}')"
  eval "SIZE_${key}=\$(wc -c < \"\$WORK/\$f\" | tr -d ' ')"
done

echo "== 上传到部署机(先落 .part,核过哈希再改名上线) =="
# 以前是直接覆盖线上文件再核:传到一半有人点下载,拿到的是半截包;
# 核出来不对的时候,错的包已经在线上了。现在全部 .part 核过之后才一起改名
# shellcheck disable=SC2086
ssh $SSH_OPTS "$DEPLOY" 'mkdir -p ~/super-z/appdist ~/super-z/webapp/releases' || {
  echo "✗ 部署机上建不了 ~/super-z/webapp/releases —— 多半是 docker 抢先把 webapp 建成了 root 的目录"
  echo "  (compose 挂载一个不存在的目录时会替你建,属主是 root)。在部署机上执行一次:"
  echo "    sudo chown -R \$(id -un):\$(id -gn) ~/super-z/webapp"
  exit 1; }
for line in $UPLOADS; do
  f=${line%%:*}; rest=${line#*:}; dest=${rest%:*}
  # shellcheck disable=SC2086
  scp -q $SCP_OPTS "$WORK/$f" "$DEPLOY:~/super-z/$dest.part"
  echo "  $f ✓"
done

echo "== 复核落地哈希（传输途中出错在这里拦）=="
for line in $UPLOADS; do
  f=${line%%:*}; rest=${line#*:}; dest=${rest%:*}; key=${line##*:}
  eval "LOCAL=\$SHA_${key}"
  REMOTE=$(ssh $SSH_OPTS "$DEPLOY" "shasum -a 256 ~/super-z/$dest.part | awk '{print \$1}'")
  [ "$REMOTE" = "$LOCAL" ] || {
    echo "✗ $f 上传后哈希不符，中止（还没有任何文件上线，线上仍是原来那版）"; exit 1; }
done
echo "  全部哈希一致 ✓（且与 Release 页同值）"

if [ "$HAS_EXTRA" = 1 ]; then
  echo "== 网页版:解压到 releases/$TAG,切 current 软链 =="
  # 在部署机上跑,排在 APK 改名之前:这一步出岔子的话 APK、桌面包都还没动,线上整体还是上一版。
  # 先把 .part 改成正式名、按刚才核过的哈希再对一次;解到 .tmp 再改名,
  # 切软链用 mv -T 原子替换 —— nginx 那边要么看到旧版、要么看到新版。
  # 旧版本只留最近 3 个(外加当前那个)。回滚:ln -sfn releases/<旧tag> current
  # shellcheck disable=SC2086
  ssh $SSH_OPTS "$DEPLOY" bash -s -- "$TAG" "$SHA_web" <<'REMOTE'
set -eo pipefail
TAG=$1; SHA=$2
cd ~/super-z/webapp
mv -f "releases/$TAG.tar.gz.part" "releases/$TAG.tar.gz"
[ "$(shasum -a 256 "releases/$TAG.tar.gz" | awk '{print $1}')" = "$SHA" ] || {
  echo "✗ 网页版包的哈希和刚才核过的不一样,中止(current 没动)"; exit 1; }
rm -rf "releases/$TAG.tmp"
mkdir -p "releases/$TAG.tmp"
tar -xzf "releases/$TAG.tar.gz" -C "releases/$TAG.tmp"
for f in index.html main.dart.js flutter_bootstrap.js canvaskit/canvaskit.wasm; do
  [ -f "releases/$TAG.tmp/$f" ] || { echo "✗ 网页版包里缺 $f,中止(current 没动)"; exit 1; }
done
# 同一个 tag 重新同步时,旧目录先挪开再换进来(两次 mv 之间只有一瞬)
if [ -d "releases/$TAG" ]; then mv "releases/$TAG" "releases/$TAG.old"; fi
mv "releases/$TAG.tmp" "releases/$TAG"
rm -rf "releases/$TAG.old"
ln -sfn "releases/$TAG" current.tmp
mv -Tf current.tmp current
echo "  current -> $(readlink current)"
cur=$(readlink current)
n=0
for d in $(ls -1dt releases/*/ 2>/dev/null); do
  d=${d%/}
  n=$((n + 1))
  if [ "$d" = "$cur" ] || [ "$n" -le 3 ]; then continue; fi
  rm -rf "$d" "$d.tar.gz"
  echo "  清掉旧版本 $d"
done
REMOTE
fi

echo "== 改名上线 =="
for line in $UPLOADS; do
  rest=${line#*:}; dest=${rest%:*}
  # 网页版的包上一步已经改过名了
  if [ "${line##*:}" = web ]; then continue; fi
  # shellcheck disable=SC2086
  ssh $SSH_OPTS "$DEPLOY" "mv -f ~/super-z/$dest.part ~/super-z/$dest"
done
echo "  APK$( [ "$HAS_EXTRA" = 1 ] && echo '、桌面包' ) ✓"

echo "== 更新 versions.json =="
# 更新说明走 base64:原来是直接插进 Python 的三引号字符串,说明里带个 ''' 或反斜杠就炸
NOTES_B64=$(printf '%s' "$NOTES" | base64 | tr -d '\n')
# shellcheck disable=SC2086
ssh $SSH_OPTS "$DEPLOY" "python3 - << 'PYEOF'
import base64, json, os
path = os.path.expanduser('~/super-z/appdist/versions.json')
try:
    with open(path) as f:
        old = json.load(f)
except Exception:
    old = {}
notes = base64.b64decode('$NOTES_B64').decode('utf-8')
shas = {'user': '$SHA_user', 'merchant': '$SHA_merchant',
        'rider': '$SHA_rider'}
data = {}
for app in ['user', 'merchant', 'rider']:
    data[app] = {
        'version': '$VERSION',
        'build': $BUILD,
        'url': '$API/appdist/chaojizan-' + app + '-arm64.apk',
        'notes': notes,
        # force:这一版是否强制更新(发版当时的一次性决定)
        'force': $FORCE_PY,
        # min_build:低于它的客户端视为过旧(**持续有效**的下限,与 force 不同)。
        # 服务端 /app/latest 原样透出,当前只用于观测,不拦截
        'min_build': $MIN_BUILD,
        # 应用内安装前用它校验；缺这个字段客户端会退回浏览器下载（#123）
        'sha256': shas[app],
    }
# 桌面版、网页版放在单独的键下,**不动上面三个键的结构**:
# 老版本 App 和 /app/latest 只认 user / merchant / rider,新键它们看不见。
# 这一版没出桌面包(老 Release、急修时关了)就沿用上一次的条目,不抹掉
if $HAS_EXTRA:
    def pkg(name, sha_size):
        return {'url': '$API/appdist/' + name, 'sha256': sha_size[0], 'size': sha_size[1]}
    data['desktop'] = {'user': {
        'version': '$VERSION',
        'build': $BUILD,
        'notes': notes,
        'force': $FORCE_PY,
        'min_build': $MIN_BUILD,
        # 桌面版不在 App 里下载安装,只提示有新版、打开这一页(见 shared/update_checker.dart)
        'page': '$API/download#desktop',
        'files': {
            'windows': pkg('chaojizan-windows-x64.zip', ('${SHA_windows:-}', ${SIZE_windows:-0})),
            'macos': pkg('chaojizan-macos.dmg', ('${SHA_macos:-}', ${SIZE_macos:-0})),
            'linux': pkg('chaojizan-linux-x64.tar.gz', ('${SHA_linux:-}', ${SIZE_linux:-0})),
            'linux_deb': pkg('chaojizan-linux-x64.deb', ('${SHA_deb:-}', ${SIZE_deb:-0})),
        },
    }}
    data['web'] = {'user': {
        'version': '$VERSION',
        'build': $BUILD,
        'url': '$API/web/',
        'tag': '$TAG',
        # Release 附件 chaojizan-web.tar.gz 的哈希:部署机上 releases/<tag>.tar.gz 就是它
        'sha256': '${SHA_web:-}',
    }}
else:
    for k in ('desktop', 'web'):
        if isinstance(old.get(k), dict):
            data[k] = old[k]
tmp = path + '.tmp'
with open(tmp, 'w') as f:
    f.write(json.dumps(data, ensure_ascii=False, indent=2))
os.replace(tmp, path)
print('versions.json -> v$VERSION build $BUILD' + (' (含桌面版、网页版)' if $HAS_EXTRA else ''))
PYEOF"

echo "== 验证 =="
curl -s -m 10 --noproxy '*' "$API/app/latest?app=user" | head -c 240; echo
if [ "$HAS_EXTRA" = 1 ]; then
  # 网页版:nginx 直接出,不经过 api。版本号看 Flutter 自己生成的 version.json
  WEBV=$(curl -s -m 10 --noproxy '*' "$API/web/version.json" || true)
  echo "  /web/version.json: $WEBV"
  echo "$WEBV" | grep -q "\"build_number\":\"$BUILD\"" || {
    echo "✗ 线上 /web/ 不是这一版(build $BUILD)—— 看看 nginx 的 /web/ 和 ~/super-z/webapp/current"
    exit 1; }
  for f in chaojizan-windows-x64.zip chaojizan-macos.dmg chaojizan-linux-x64.tar.gz chaojizan-linux-x64.deb; do
    code=$(curl -s -o /dev/null -I -w '%{http_code}' -m 10 --noproxy '*' "$API/appdist/$f")
    [ "$code" = "200" ] || { echo "✗ $API/appdist/$f 返回 $code"; exit 1; }
  done
  echo "  网页版 build $BUILD ✓  桌面包 ×4 可下载 ✓"
fi
echo
echo "同步完成 ✓ 旧版用户打开 App 即会收到更新提示"
echo "  appdist / 网页版上的文件 = Release $TAG 的同一批产物，两边 SHA-256 一致。"
