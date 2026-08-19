# 拉丁字体子集(中文一律回落系统字)

三端只打包拉丁字母与数字，**不含任何 CJK**——中文由 `fontFamilyFallback`
交回 PingFang SC / 思源黑，既省体积也避免中文被带成宋体。
用法见 `lib/src/brand.dart` 的 `szFigure()` / `szMoney()` 与主题的 `fontFamily`。

## 为什么是这两款

claude.ai 实际用的是 **Galaxie Copernicus**（大标题）+ **Styrene B**（正文），
两个都是商用授权字体，不可能打进开源仓。所以按"同一血统 + OFL 授权"选替代：

| 用途 | Anthropic 用的 | 我们用的 | 依据 |
|---|---|---|---|
| 衬线 · 数字 | Galaxie Copernicus | **Literata** | Copernicus 是受 Plantin 影响的过渡期衬线；Literata 同属这一脉，且带 `onum`/`tnum` |
| 无衬线 · 拉丁词 | Styrene B | **Space Grotesk** | Styrene 的几何无衬线特征，Space Grotesk 是公认最接近的 OFL 替代 |

淘汰过程（实测，不是照搬相似度评分）：

- **DM Sans** — 没有 `tnum`，金额列对不齐，直接出局。
- **Newsreader** — 没有 `onum`，旧式数字没了，而旧式数字正是这套观感的来源。
- **Work Sans** — 特性齐全但太中性，和 PingFang 混排看不出性格，等于白加 25KB。
- **Source Serif 4**（第八辑 #101 用的）— 特性齐全，但它是 Fournier 血统，
  不是 Plantin 血统，和 Copernicus 隔了一层。

⚠️ **npm 上的 `anthropic-fonts` 包不能用**：发布者是第三方 `devchauhann`，
却把包标成 MIT——第三方无权把 Anthropic 的自有字体重新授权。
fontiko / onlinewebfonts 那类站点是盗版字体站。这些放进开源仓是法律风险。

## 授权与体积

- Literata：OFL 1.1，见 `OFL-Literata.txt`
- Space Grotesk：OFL 1.1，见 `OFL-SpaceGrotesk.txt`
- 子集后共 4 个文件 **116,632 字节 ≈ 113KB**（原始可变字体共 1.1MB）

保留的 OpenType 特性：`onum`（旧式数字，正文里的评分/月售/距离）、
`tnum`/`lnum`（等宽，金额列对齐）、`pnum`、`liga`、`kern`、`ccmp`、`zero`、`frac`。
**这三个特性是 `szFigure()` / `szMoney()` 的前提，换字体或重做子集时不能丢。**

## 怎么复现

```bash
python3 -m venv /tmp/fontenv && /tmp/fontenv/bin/pip install fonttools brotli
cd /tmp && curl -L -o Literata.ttf 'https://raw.githubusercontent.com/google/fonts/main/ofl/literata/Literata%5Bopsz,wght%5D.ttf'
curl -L -o SpaceGrotesk.ttf 'https://raw.githubusercontent.com/google/fonts/main/ofl/spacegrotesk/SpaceGrotesk%5Bwght%5D.ttf'

# 可变字体先定格成静态字重(Flutter 里用 fontVariations 麻烦,静态实例最省心)
/tmp/fontenv/bin/python - <<'EOF'
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
for src, dst, axes in [("Literata","SzSerif-Regular",{'wght':400,'opsz':14}),
                       ("Literata","SzSerif-Semibold",{'wght':600,'opsz':14}),
                       ("SpaceGrotesk","SzSans-Regular",{'wght':400}),
                       ("SpaceGrotesk","SzSans-Semibold",{'wght':600})]:
    instancer.instantiateVariableFont(TTFont(f"/tmp/{src}.ttf"), axes,
        inplace=False, updateFontNames=False).save(f"/tmp/{dst}-full.ttf")
EOF

for n in SzSerif-Regular SzSerif-Semibold SzSans-Regular SzSans-Semibold; do
  /tmp/fontenv/bin/pyftsubset "/tmp/$n-full.ttf" \
    --unicodes='U+0020-007E,U+00A5,U+00B0,U+00B7,U+00D7,U+2013,U+2014,U+2018,U+2019,U+201C,U+201D,U+2026,U+2212,U+2248,U+2264,U+2265,U+00A0,U+FFE5' \
    --layout-features='onum,tnum,lnum,pnum,liga,kern,ccmp,zero,frac' \
    --output-file="packages/shared/assets/fonts/$n.ttf" \
    --no-hinting --desubroutinize --name-IDs='*' --name-legacy --notdef-outline
done
```

字符集里除 ASCII 外还留了 `¥ · × ≈ − ° – —` 和中英标点——这些会跟数字同行出现
（代码里 `·` 用了 153 处、`×` 14 处、`≈` 4 处）。加新符号时记得一并加进
`--unicodes` 重跑，否则该字符会掉回系统字，同一行里字形会打架。

---

# 追加：中文衬线显示字（2026-08-19）

上面那句"**不含任何 CJK**"现在**部分推翻**了，但推翻的范围要说清楚。

## 推翻了什么，没推翻什么

当时不打 CJK 的两个理由：省体积、避免中文被带成宋体。第二个理由针对的是
**正文**——宋体在 11px 上发虚，而这个 App 有长辈版 1.4×，老年用户不少。
**那个判断到今天仍然成立，没动它。**

新加的 `SzSerifCJK` 只接在 `szDisplay()` 上，用在大字位置：频道字块（19~21px）、
页面大标题。`szFigure()` / `szMoney()` 的中文回落**一行没改**，小字仍是系统黑体。

也就是说：宋体只在它撑得住的尺寸出现。

## 为什么值得加

频道字块（碗/宿/券/跑/车）本来是照衬线数字的样子设计的，
里面却坐着一个系统**黑**体字——字块和字不是一套。换成宋体之后才对上。

## 体积

| | |
|---|---|
| 思源宋体全量（可变） | 24MB |
| 定格成单字重 | 14MB |
| **子集后两字重** | **5.60MB（文件）/ 3.41MB（APK 内压缩后）** |
| 占用户端 APK | **+11.4%**（实测：29.82MB → 33.22MB） |

子集范围 = **GB2312 一级 + 二级 + 源码固定文案** = 6764 字。

GB2312 两级是简体中文的常用全集（6763 字），源码扫出来的 1339 字里
只有一个不在其中——`龥`，而它是 `addr_parse.py` 里正则 `[一-龥]` 的区间上界，
根本不显示。扫描器宁可多收不少收，无害。

## 为什么给到 GB2312 全集，而不是只要固定文案

只覆盖固定文案的话包能小 4.6MB（实测 +2.0% vs +11.4%），但**商家名、菜名、
地址、评价是用户产生的内容**——一旦用显示体渲染，生僻一点的字就掉回黑体，
一个标题里两种字形。

这是一次有意的取舍：宁可包大 3.4MB，也不要用户在商家详情页的标题里看到半宋半黑。

## ⚠️ 仍然盖不住的

**繁体字**和 GB2312 外的生僻字。商家起名用繁体（「老麵館」）是真实存在的情况。

各档实测体积，要往上走的话对着这张表算：

| 子集范围 | 字数 | 两字重文件 | APK 内压缩 | 占 APK |
|---|---|---|---|---|
| 只要频道字 5 个 | 37 | 25KB | ~15KB | +0.0% |
| 源码固定文案 | 1371 | 0.97MB | 635KB | +2.0% |
| + GB2312 一级 | 3802 | 2.97MB | ~1.8MB | +5.8% |
| **+ 一级 + 二级（现在这个）** | **6796** | **5.60MB** | **3.41MB** | **+11.4%** |

改 `scripts/gen_font_subset.py` 里的字符集然后重跑即可，但 APK 体积的账要单算。

## 怎么复现

```bash
python3 scripts/gen_font_subset.py          # 重新生成（首次会下载 24MB 源字体到 ~/.cache）
python3 scripts/gen_font_subset.py --check  # 只校验覆盖率（CI 跑这个，不下载）
```

`--check` 读已提交子集里的 cmap，和源码扫出来的汉字比对。少一个字就报错——
否则新加的文案会**默默**掉回系统黑体，不报错、不崩、没人会注意到。

授权：思源宋体 SC，OFL 1.1，见 `OFL-NotoSerifSC.txt`。
