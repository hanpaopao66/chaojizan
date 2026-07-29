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
