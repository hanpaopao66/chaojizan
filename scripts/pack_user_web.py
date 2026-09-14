#!/usr/bin/env python3
"""把 `flutter build web` 的产物整理成官网 /web/ 要的样子,打成 chaojizan-web.tar.gz。

release.yml 的 web job 调它;本地想看发版那一份长什么样也可以跑(要能连 fonts.gstatic.com):

    python3 scripts/pack_user_web.py apps/user_app/build/web build/release-web/chaojizan-web.tar.gz \\
        [--font-cache ~/.cache/superz-web-fonts]

做五件事,任何一件不对就非零退出 —— CI 那一步跟着红,不会发一个半成品出去:

1. **核对构建参数真的生效了**:CanvasKit 从本地加载(--no-web-resources-cdn 写进了
   buildConfig 的 useLocalCanvasKit)、字体回落指向同源(flutter_bootstrap.js 里的
   SZ_FONT_FALLBACK_BASE 被 --web-define 换掉了)。少一样,国内打开就是白屏或满屏方块,
   而且开发机上看不出来(开发机能连 Google);
2. **删掉用不到的 CanvasKit 变体**:这是编译成 JS 的构建,只会加载 canvaskit/ 和
   canvaskit/chromium/ 两份。skwasm / wimp 只有 --wasm 构建用、experimental_webparagraph
   要显式开配置、.symbols 是调试符号 —— 加起来占产物一半;
3. **镜像字体回落**:从编译出来的 main.dart.js 里取出引擎会去 gstatic 下的全部字体路径
   (Noto 中日韩五套、emoji、各种符号,约 700 个文件、20MB 出头),原样下载到 fontfallback/ 下。
   按 main.dart.js 取而不是抄一份清单:升级 Flutter 换了字体版本,这里自动跟着换。
   只镜像中文那一套不够:浏览器语言不是 zh-CN 的人,引擎会挑日文、韩文那几套来显示汉字;
4. **预压缩**:文本和 wasm 各出一份 .gz,nginx 的 gzip_static 直接发 ——
   main.dart.js 6MB 压到不到 2MB,CanvasKit 的 wasm 同理,不用每个请求现压;
5. **打包**:条目排序、属主 0、权限 0644。每个文件的时间戳由**内容哈希**算出来
   (落在 2000~2019 年之间):nginx 的 ETag 是「修改时间 + 大小」,内容没变的文件
   (CanvasKit、字体)换版以后 ETag 不变,浏览器回源拿到 304、不用重下;内容变了的一定变。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import gzip
import hashlib
import io
import re
import shutil
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

FONT_CDN = "https://fonts.gstatic.com/s/"
FONT_DIR = "fontfallback"
#: main.dart.js 里字体回落的路径长这样:"notosanssc/v37/k3kXo8….0.woff2"、"roboto/v32/KFOm….woff2"
FONT_PATH = re.compile(rb'"([a-z0-9]+/v\d+/[A-Za-z0-9_-]+(?:\.\d+)?\.(?:woff2|ttf|otf))"')
#: 字体文件的魔数:下回来的得真是字体,不能是一张报错页
FONT_MAGIC = (b"wOF2", b"wOFF", b"\x00\x01\x00\x00", b"OTTO", b"true")

#: 预压缩哪些:文本类和 wasm。png / woff2 本身是压缩格式,再压只烧 CPU
GZIP_SUFFIX = {".js", ".mjs", ".wasm", ".json", ".html", ".css", ".svg",
               ".otf", ".ttf", ".frag", ".txt", ".map"}
GZIP_NAMES = {"NOTICES"}
GZIP_MIN = 1024

README = """这个目录里的字体原样来自 https://fonts.gstatic.com/s/(同样的路径),没有改动。

用户端网页版(Flutter)遇到打包字体里没有的字,会按引擎内置的清单去下 Noto 字体;
清单缺省指向 Google 的字体 CDN,国内访问不了,所以发版时由 scripts/pack_user_web.py
从 main.dart.js 里取出清单、镜像到这里,flutter_bootstrap.js 把 fontFallbackBaseUrl 指过来。

Noto 系列字体按 SIL Open Font License 1.1 发布(https://openfontlicense.org);
Roboto 的许可见 https://fonts.google.com/specimen/Roboto/license 。
"""


def die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def check_build(web: Path) -> str:
    boot = web / "flutter_bootstrap.js"
    if not boot.is_file() or not (web / "main.dart.js").is_file():
        die(f"{web} 里没有 flutter_bootstrap.js / main.dart.js —— 先 flutter build web")
    text = boot.read_text(encoding="utf-8")
    if '"useLocalCanvasKit":true' not in text:
        die("buildConfig 里没有 useLocalCanvasKit —— 构建没带 --no-web-resources-cdn,"
            "CanvasKit 会去 www.gstatic.com 下,国内打不开")
    if "{{SZ_FONT_FALLBACK_BASE}}" in text:
        die("flutter_bootstrap.js 里的 SZ_FONT_FALLBACK_BASE 没被替换 —— 构建没带 "
            f"--web-define=SZ_FONT_FALLBACK_BASE={FONT_DIR}/,字体回落会去 fonts.gstatic.com")
    if f"'{FONT_DIR}/'" not in text:
        die(f"flutter_bootstrap.js 里的字体回落地址不是 {FONT_DIR}/,和这里镜像的目录对不上")
    # 认的是我们自己那份启动脚本的最后一行。Flutter 缺省的那份会注册 service worker、
    # 也不带字体回落的配置(内联进来的 flutter.js 本身就含 serviceWorkerSettings 这个词,
    # 不能拿它当判据)
    if "_flutter.loader.load({ config: szConfig });" not in text:
        die("flutter_bootstrap.js 不是 apps/user_app/web/flutter_bootstrap.js 那一份 ——"
            "是不是用回了 Flutter 缺省的启动脚本?")
    return text


def prune(web: Path, bootstrap: str) -> int:
    ck = web / "canvaskit"
    victims: list[Path] = list(ck.rglob("*.symbols"))
    victims += [p for p in (ck / "experimental_webparagraph",) if p.exists()]
    if '"compileTarget":"dart2wasm"' not in bootstrap:
        victims += [p for p in ck.iterdir() if p.name.startswith(("skwasm", "wimp"))]
    # service worker 不注册(见 flutter_bootstrap.js),留着这个文件只会让人以为它在工作
    victims += [p for p in (web / "flutter_service_worker.js",) if p.exists()]
    freed = 0
    for p in victims:
        if p.is_dir():
            freed += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            shutil.rmtree(p)
        elif p.exists():
            freed += p.stat().st_size
            p.unlink()
    for need in ("canvaskit.js", "canvaskit.wasm", "chromium/canvaskit.js", "chromium/canvaskit.wasm"):
        if not (ck / need).is_file():
            die(f"canvaskit/{need} 不见了 —— 加载器要用它,Flutter 的产物结构可能变了")
    return freed


def _fetch(path: str, dest: Path, cache: Path | None) -> int:
    cached = cache / path if cache else None
    if cached and cached.is_file():
        data = cached.read_bytes()
    else:
        err: Exception | None = None
        data = b""
        for attempt in range(4):
            try:
                with urllib.request.urlopen(FONT_CDN + path, timeout=60) as r:
                    data = r.read()
                break
            except Exception as e:  # noqa: BLE001 —— 网络抖动都重试,最后一次再报
                err = e
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"{path}: {err}")
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
    if not data.startswith(FONT_MAGIC):
        raise RuntimeError(f"{path}: 下回来的不是字体文件(开头 {data[:8]!r})")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


def mirror_fonts(web: Path, cache: Path | None) -> tuple[int, int]:
    js = (web / "main.dart.js").read_bytes()
    if FONT_CDN.encode() not in js:
        die(f"main.dart.js 里没有 {FONT_CDN} —— Flutter 可能改了字体回落的做法,核对以后再改这个脚本")
    paths = sorted({m.group(1).decode() for m in FONT_PATH.finditer(js)})
    if len(paths) < 100:
        die(f"只从 main.dart.js 里认出 {len(paths)} 个字体路径(以前是 700 多个)——"
            "Flutter 可能改了字体清单的写法,核对以后再改这个脚本")
    if not any(p.startswith("notosanssc/") for p in paths):
        die("字体清单里没有 Noto Sans SC —— 中文会没有字形,核对 Flutter 的字体回落清单")
    out = web / FONT_DIR
    if out.exists():
        shutil.rmtree(out)
    total = 0
    with cf.ThreadPoolExecutor(16) as ex:
        futs = {ex.submit(_fetch, p, out / p, cache): p for p in paths}
        for f in cf.as_completed(futs):
            try:
                total += f.result()
            except Exception as e:  # noqa: BLE001
                die(f"字体镜像失败:{e}")
    (out / "README.txt").write_text(README, encoding="utf-8")
    return len(paths), total


def precompress(web: Path) -> tuple[int, int, int]:
    # Flutter 的产物里本来没有 .gz;有的话是上次跑剩下的(本地对同一个目录跑第二遍),先清掉,
    # 不然删掉的 CanvasKit 变体会留下一个没有原文件的 .gz
    for p in list(web.rglob("*.gz")):
        p.unlink()
    n = before = after = 0
    for p in sorted(web.rglob("*")):
        if not p.is_file() or p.suffix == ".gz":
            continue
        if p.suffix not in GZIP_SUFFIX and p.name not in GZIP_NAMES:
            continue
        data = p.read_bytes()
        if len(data) < GZIP_MIN:
            continue
        z = gzip.compress(data, compresslevel=9, mtime=0)
        if len(z) > len(data) * 0.9:
            continue
        p.with_name(p.name + ".gz").write_bytes(z)
        n, before, after = n + 1, before + len(data), after + len(z)
    return n, before, after


def _stamp(data: bytes) -> int:
    """内容决定时间戳:2000-01-01 起往后 19 年以内。见文件头第 5 条。"""
    return 946_684_800 + int.from_bytes(hashlib.sha256(data).digest()[:4], "big") % 600_000_000


def pack(web: Path, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in web.rglob("*") if p.is_file())
    stamps: dict[Path, int] = {}
    for p in files:
        if p.suffix != ".gz":
            stamps[p] = _stamp(p.read_bytes())
    with open(out, "wb") as raw, \
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz, \
            tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for p in files:
            data = p.read_bytes()
            info = tarfile.TarInfo(p.relative_to(web).as_posix())
            info.size = len(data)
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            # .gz 跟原文件同一个时间戳:原文件内容变了,它的也跟着变
            src = p.with_name(p.name[:-3]) if p.suffix == ".gz" else p
            info.mtime = stamps[src] if src in stamps else _stamp(data)
            tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(out.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("web", type=Path, help="flutter build web 的输出目录(会被就地整理)")
    ap.add_argument("out", type=Path, help="输出的 tar.gz")
    ap.add_argument("--font-cache", type=Path, default=None,
                    help="字体下载缓存目录(本地反复跑时省流量;CI 不用)")
    a = ap.parse_args()

    boot = check_build(a.web)
    print("  构建参数 ✓(CanvasKit 本地加载、字体回落同源、不注册 service worker)")
    freed = prune(a.web, boot)
    print(f"  删掉用不到的 CanvasKit 变体和调试符号:{freed / 1048576:.1f} MB")
    n, size = mirror_fonts(a.web, a.font_cache)
    print(f"  字体回落镜像:{n} 个文件,{size / 1048576:.1f} MB → {FONT_DIR}/")
    n, before, after = precompress(a.web)
    print(f"  预压缩 {n} 个文件:{before / 1048576:.1f} MB → {after / 1048576:.1f} MB(.gz)")
    sha = pack(a.web, a.out)
    print(f"  {a.out}  {a.out.stat().st_size / 1048576:.1f} MB")
    print(f"  sha256 {sha}")


if __name__ == "__main__":
    main()
