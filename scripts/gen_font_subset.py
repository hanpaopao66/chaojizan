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

## 两种用法

    python3 scripts/gen_font_subset.py           # 重新生成(要下载 24MB 源字体)
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
    return 0


def check() -> int:
    """校验两件事:源码文案全覆盖、GB2312 常用字全覆盖。

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
    raise SystemExit(check() if ap.parse_args().check else build())
