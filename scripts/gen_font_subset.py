#!/usr/bin/env python3
"""中文衬线显示字的子集化。

## 为什么加这个字体

`assets/fonts/README.md` 原本写着「**不含任何 CJK** —— 中文由 fontFamilyFallback
交回 PingFang SC / 思源黑,既省体积也避免中文被带成宋体」。

这一条现在**部分推翻**,原因和当时的顾虑并不冲突:

- 当时怕的是 `szFigure` / `szMoney` 把正文里的中文**顺带**变成宋体。
  那个顾虑是对的 —— 宋体在 11px 上发虚,而这个 App 有长辈版;
- 现在加的是一个**独立的显示体** [szDisplay],只用在大字位置
  (频道字块、页面大标题)。小字一行都不碰,`szFigure` / `szMoney` 的
  中文回落**保持不变**。

也就是说:宋体只在它擅长的尺寸出现。

## 为什么要子集

思源宋体全量 24MB(可变),定格成单字重也有 14MB —— 两个字重 28MB,
而用户端 APK 现在总共 51MB。不子集这件事就不用做了。

子集范围 = **源码固定文案 + GB2312 一级 + 二级**,共约 6800 字。

为什么给到 GB2312 全量而不是只要固定文案:只覆盖固定文案的话,
商家名、菜名、评价这些**用户产生的内容**一旦用显示体渲染,
生僻一点的字就掉回黑体 —— 一个标题里两种字形。
GB2312 一二级是简体中文的常用全集(6763 字),UGC 基本都在里面。

代价是 APK 大了约 11%。这是一次有意的取舍:宁可包大一点,
也不要用户在商家详情页的标题里看到半宋半黑。

⚠️ **繁体字和 GB2312 外的生僻字仍然会掉回系统黑体**。
商家起名用繁体(「老麵館」)是真实存在的情况 —— 这一档没覆盖,
要覆盖得再往上走一级(见 assets/fonts/README.md 里的体积表)。

## 三种用法

    python3 scripts/gen_font_subset.py           # 重新生成(要下载 24MB 源字体)
    python3 scripts/gen_font_subset.py --web     # 只重做官网那几份(不下载)
    python3 scripts/gen_font_subset.py --check   # 只校验覆盖率(CI 用,不下载)

`--check` 读已提交的子集里的 cmap,和源码里扫出来的汉字比对。
少一个字就报错 —— 否则新加的文案会**默默**掉回系统黑体,
同一个标题里一半宋体一半黑体,而没人会注意到。
"""
import argparse
import pathlib
import re
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "packages/shared/assets/fonts"
SRC_URL = ("https://github.com/google/fonts/raw/main/ofl/notoserifsc/"
           "NotoSerifSC%5Bwght%5D.ttf")
CACHE = pathlib.Path.home() / ".cache/superz-fonts/NotoSerifSC.ttf"

#: 扫这些目录的字符串字面量。**注释不算** —— 注释不会显示给用户。
SCAN = [
    (ROOT / "packages/shared/lib", "*.dart"),
    (ROOT / "apps/user_app/lib", "*.dart"),
    (ROOT / "apps/merchant_app/lib", "*.dart"),
    (ROOT / "apps/rider_app/lib", "*.dart"),
    # 服务端下发的状态名和错误提示也会显示在 App 里
    (ROOT / "server/app", "*.py"),
]

#: 中文标点。它们和汉字同行出现,掉回系统字会看出来
PUNCT = "，。、：；！？（）【】「」『』—…·《》〈〉￥％°×÷～“”‘’"


def gb2312_hanzi() -> set[str]:
    """GB2312 一级(3755 字)+ 二级(3008 字)。

    **本地按编码区位算出来,不下字表** —— 外部字表链接会失效
    (第一版用的那个 GitHub 原始链接就是 404),而 GB2312 的区位是标准,
    永远算得出同一组字。

    - 一级 0xB0A1–0xD7F9:最常用,按拼音排序;
    - 二级 0xD8A0–0xF7FE:次常用,按部首排序。

    两级合起来 6763 字,是简体中文的常用全集 —— 菜名、商家名、
    地址、评价里的字基本都在这个范围内。
    """
    out = set()
    for hi in range(0xB0, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                out.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    return {c for c in out if CJK.match(c)}

WEIGHTS = {400: "Regular", 600: "Semibold"}

CJK = re.compile(r"[㐀-鿿豈-﫿]")
LITERAL = re.compile(r"""'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)\"""")


def source_chars() -> set[str]:
    """源码字符串字面量里出现过的汉字。"""
    found = set()
    for base, glob in SCAN:
        if not base.exists():
            continue
        for path in base.rglob(glob):
            lines = path.read_text(errors="ignore").splitlines()
            # 整行注释去掉。行内注释留着无所谓 —— 多收几个字不影响正确性,
            # 漏收才会出问题,所以这里宁可宽松
            body = "\n".join(
                ln for ln in lines
                if not ln.lstrip().startswith(("//", "///", "#")))
            for m in LITERAL.finditer(body):
                found.update(CJK.findall(m.group(1) or m.group(2) or ""))
    return found


def covered() -> set[str]:
    """已提交的子集里真正有字形的汉字。"""
    from fontTools.ttLib import TTFont
    path = FONT_DIR / f"SzSerifCJK-{WEIGHTS[400]}.ttf"
    if not path.exists():
        raise SystemExit(f"✗ 找不到 {path.relative_to(ROOT)},先跑一次生成")
    cmap = TTFont(path).getBestCmap()
    return {chr(c) for c in cmap if CJK.match(chr(c))}


def fetch_source() -> pathlib.Path:
    if CACHE.exists():
        return CACHE
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    print(f"  下载思源宋体(24MB,只下这一次,存到 {CACHE})…")
    urllib.request.urlretrieve(SRC_URL, CACHE)
    return CACHE


def build() -> int:
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    src = fetch_source()
    fixed = source_chars()
    common = gb2312_hanzi()
    chars = fixed | common
    text = "".join(sorted(chars | set(PUNCT)))
    print(f"  源码固定文案 {len(fixed)} 字 + GB2312 常用 {len(common)} 字")
    print(f"  去重后 {len(chars)} 字,加标点共 {len(text)} 字")

    total = 0
    for wght, name in WEIGHTS.items():
        static = ROOT / f".fontcache-{wght}.ttf"
        instancer.instantiateVariableFont(
            TTFont(src), {"wght": wght}, inplace=False,
            updateFontNames=False).save(static)
        out = FONT_DIR / f"SzSerifCJK-{name}.ttf"
        subprocess.run([
            sys.executable.replace("python", "pyftsubset")
            if pathlib.Path(sys.executable.replace("python", "pyftsubset")).exists()
            else "pyftsubset",
            str(static), f"--text={text}", f"--output-file={out}",
            # CJK 用不上 onum/tnum(那是给数字的,数字走 Literata),
            # 但 kern/ccmp/locl 要留:locl 管地区字形,丢了会出日文字形
            "--layout-features=kern,ccmp,locl,liga",
            "--no-hinting", "--desubroutinize",
            "--name-IDs=*", "--name-legacy",
        ], check=True)
        static.unlink()
        size = out.stat().st_size
        total += size
        print(f"  {out.name:<28} {size/1024:6.0f} KB")
    print(f"  合计 {total/1048576:.2f} MB")
    # 官网那份是从 App 子集里再切出来的,App 子集变了它要跟着重做
    return build_web()


# ---------- 官网(web/src/**,外加独立的下载页) ----------
#
# 官网的中文衬线只用在大字上 —— 各页 h1 / h2、频道字块、首页流程动画的字幕,
# 文案全是写死的,用不着 App 那份 GB2312 全集(2.9MB,手机上开官网要白下这么多)。
# 所以按这些地方实际出现的字,从已提交的 App 子集里再切一份。
#
# 拉丁字母和数字走 SzSerif(常规、半粗两个字重,各 33KB),这里只换成 WOFF。
# 用 WOFF 不用 WOFF2:WOFF2 要 brotli,CI 的覆盖率检查只装了 fonttools;
# 字这么少,两者差不到 10KB。

WEB_SRC = ROOT / "web/src"
WEB_DOWNLOAD = ROOT / "server/static/download.html"
WEB_FONT_DIR = ROOT / "web/public/fonts"
WEB_CJK = WEB_FONT_DIR / "SzSerifCJK-Semibold.site.woff"
WEB_LATIN = WEB_FONT_DIR / "SzSerif-Semibold.woff"
#: 数字的常规字重:表格里逐行的金额、时间用它(设计稿里只有大字是 600)
WEB_LATIN_REGULAR = WEB_FONT_DIR / "SzSerif-Regular.woff"

#: 源码里用衬线显示、但不在 <h1>/<h2> 里写死的字(频道页标题表、流程动画字幕),
#: 用这一对注释圈起来;圈里的**字符串字面量**都算
SERIF_BLOCK = re.compile(r"@serif-cjk-begin(.*?)@serif-cjk-end", re.S)


def web_chars() -> set[str]:
    """官网上会用中文衬线(SzSerifCJK)显示的汉字。

    **判据要和挂 SzSerifCJK 的样式对上**:
    - site.css 的 `.h3 h1, .h3 h2` → web/src 里所有 .jsx 的 <h1>…</h1>、<h2>…</h2>;
    - `.glyph`、频道页的 `.cp-pill .g` → 频道注册表里的 `glyph: '碗'`;
    - 频道页规矩左边那一格 `.cp-rules .v` → ChannelPage.jsx 标题表同一个圈里的 V;
    - FlowFilm.jsx 的字幕 / 收尾卡、ChannelPage.jsx 的标题表 → @serif-cjk-begin/end 圈住的字面量;
    - server/static/download.html 的 <h1> 和 class="g" 的字块(那页自己挂的字体)。
    那边多挂一处,这里就要多扫一处。标题写成变量传进去的话这里扫不到 ——
    所以标题要么写死在 <h1>/<h2> 里,要么放进 serif-cjk 圈里。
    """
    found = set()
    for path in sorted(WEB_SRC.rglob("*.js*")):
        if path.suffix not in (".jsx", ".js"):
            continue
        src = path.read_text()
        for m in re.finditer(r"<h([12])[^>]*>(.*?)</h\1>", src, re.S):
            found.update(CJK.findall(m.group(2)))
        for m in re.finditer(r"glyph: '(.)'", src):
            found.update(CJK.findall(m.group(1)))
        for block in SERIF_BLOCK.findall(src):
            for m in LITERAL.finditer(block):
                found.update(CJK.findall(m.group(1) or m.group(2) or ""))
    if WEB_DOWNLOAD.exists():
        html = WEB_DOWNLOAD.read_text()
        for m in re.finditer(r"<h1[^>]*>(.*?)</h1>", html, re.S):
            found.update(CJK.findall(m.group(1)))
        for m in re.finditer(r'class="g"[^>]*>([^<]*)<', html):
            found.update(CJK.findall(m.group(1)))
    return found


def build_web() -> int:
    from fontTools import subset
    from fontTools.ttLib import TTFont

    chars = web_chars()
    if not chars:
        raise SystemExit(f"✗ 在 {WEB_SRC.relative_to(ROOT)} 里一个标题字都没扫到,"
                         "扫描规则和页面对不上了")
    WEB_FONT_DIR.mkdir(parents=True, exist_ok=True)

    opts = subset.Options()
    opts.flavor = "woff"
    opts.layout_features = ["kern", "ccmp", "locl", "liga"]
    opts.hinting = False
    opts.desubroutinize = True
    opts.name_IDs = ["*"]
    opts.name_legacy = True
    font = subset.load_font(str(FONT_DIR / "SzSerifCJK-Semibold.ttf"), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text="".join(sorted(chars)) + PUNCT)
    sub.subset(font)
    subset.save_font(font, str(WEB_CJK), opts)

    for name, out in (("Semibold", WEB_LATIN), ("Regular", WEB_LATIN_REGULAR)):
        latin = TTFont(FONT_DIR / f"SzSerif-{name}.ttf")
        latin.flavor = "woff"
        latin.save(out)

    missing = sorted(chars - {chr(c) for c in font.getBestCmap()})
    if missing:
        # App 子集(GB2312 一二级 + App 源码)里本来就没有的字,官网子集也切不出来
        print("  ⚠ App 子集里没有这些字,官网上会掉回系统字体:" + "".join(missing))
    print(f"  官网衬线显示字 {len(chars)} 个")
    for out in (WEB_CJK, WEB_LATIN, WEB_LATIN_REGULAR):
        print(f"  {out.relative_to(ROOT)!s:<48} {out.stat().st_size/1024:6.1f} KB")
    return 0


def check_web() -> bool:
    """官网的衬线显示字是否都在官网子集里。改了标题没重跑,这里拦。"""
    from fontTools.ttLib import TTFont

    if not WEB_CJK.exists():
        print(f"  ✗ 找不到 {WEB_CJK.relative_to(ROOT)},"
              "跑 `python3 scripts/gen_font_subset.py --web`")
        return False
    cmap = TTFont(WEB_CJK).getBestCmap()
    have = {chr(c) for c in cmap if CJK.match(chr(c))}
    need = web_chars()
    missing = sorted(need - have)
    mark = "✗" if missing else "✓"
    print(f"  {mark} 官网衬线显示字:需要 {len(need)} 字,缺 {len(missing)} 字")
    if missing:
        print("     " + "".join(missing))
        print("   跑 `python3 scripts/gen_font_subset.py --web` 重新切官网子集。")
    return not missing


def check() -> int:
    """校验三件事:源码文案全覆盖、GB2312 常用字全覆盖、官网衬线显示字全覆盖。

    第二条看着多余(子集就是照它生成的),但它挡的是**手改字体文件**
    这种事 —— 有人为了省体积单独重新子集了一次,包变小了、
    测试全绿、直到有个菜名里的字掉回黑体才被发现。
    """
    have = covered()
    fixed, common = source_chars(), gb2312_hanzi()
    bad = False
    for label, need in (("源码固定文案", fixed), ("GB2312 常用字", common)):
        missing = sorted(need - have)
        mark = "✗" if missing else "✓"
        print(f"  {mark} {label}:需要 {len(need)} 字,缺 {len(missing)} 字")
        if missing:
            bad = True
            print("     " + "".join(missing[:60])
                  + ("…" if len(missing) > 60 else ""))
    print(f"  子集共覆盖 {len(have)} 个汉字")
    if not check_web():
        bad = True
    if bad:
        print("\n✗ 缺的字会**默默**掉回系统黑体 —— 不报错、不崩、"
              "同一行里字形打架。")
        print("   跑一次 `python3 scripts/gen_font_subset.py` 重新生成。")
        return 1
    print("✓ 显示字覆盖完整")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="只校验覆盖率,不重新生成(CI 用)")
    ap.add_argument("--web", action="store_true",
                    help="只重做官网那几份字体(从已提交的 App 子集切,不下载)")
    args = ap.parse_args()
    raise SystemExit(check() if args.check else build_web() if args.web else build())
