# SzSerif — 三端数字与拉丁字母的衬线子集

金额、评分、距离、单量这类数字走衬线，中文仍走系统字（PingFang / 思源黑）。
详见 `docs/DEV-PROMPTS-8.md` 的「设计基线」与 `lib/src/brand.dart` 的
`szFigure()` / `szMoney()`。

## 是什么

- 字体：[Source Serif 4](https://github.com/adobe-fonts/source-serif) 4.005R，
  Regular + Semibold 两个字重。
- 授权：SIL Open Font License 1.1（见同目录 `OFL.txt`），可随本仓库开源分发。
- 子集：只保留拉丁字母、数字与金额相关符号，**不含任何 CJK**——中文由
  `fontFamilyFallback` 交回系统字，既省体积也避免中文变成宋体。
- 体积：Regular 34KB + Semibold 35KB ≈ 69KB（原始 TTF 共 534KB）。

保留的 OpenType 特性：`onum`（旧式数字，正文里的评分/月售/距离用）、
`tnum`/`lnum`（等宽衬线数字，金额列对齐用）、`pnum`、`liga`、`kern`、
`ccmp`、`zero`、`frac`。这三个特性是 `szFigure()` / `szMoney()` 的前提，
换字体或重做子集时不能丢。

## 怎么复现

```bash
python3 -m venv /tmp/fontenv && /tmp/fontenv/bin/pip install fonttools brotli
curl -L -o /tmp/ss4.zip https://github.com/adobe-fonts/source-serif/releases/download/4.005R/source-serif-4.005_Desktop.zip
unzip -o /tmp/ss4.zip -d /tmp/ss4
for w in Regular Semibold; do
  /tmp/fontenv/bin/pyftsubset "/tmp/ss4/source-serif-4.005_Desktop/TTF/SourceSerif4-$w.ttf" \
    --unicodes='U+0020-007E,U+00A5,U+00B0,U+00B7,U+00D7,U+2013,U+2014,U+2018,U+2019,U+201C,U+201D,U+2026,U+2212,U+2248,U+2264,U+2265,U+00A0,U+FFE5' \
    --layout-features='onum,tnum,lnum,pnum,liga,kern,ccmp,zero,frac' \
    --output-file="packages/shared/assets/fonts/SzSerif-$w.ttf" \
    --no-hinting --desubroutinize --name-IDs='*' --name-legacy --notdef-outline
done
```

字符集里除了 ASCII，还留了 `¥ · × ≈ − ° − – —` 和中英标点——这些会跟数字
同行出现（代码里 `·` 用了 153 处、`×` 14 处、`≈` 4 处）。加新符号时记得
一并加进 `--unicodes` 重跑，否则该字符会掉回系统字，同一行里字形会打架。
