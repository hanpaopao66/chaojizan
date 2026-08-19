#!/usr/bin/env python3
"""频道色的可分辨性回归。

## 为什么要有它

频道色不是装饰,是**功能**:聚合平台首页一排图标,用户要一眼找到"打车"。
而"能不能一眼分开"是可以量的 —— 量不出来就会像旧色板那样,
配的时候觉得"低饱和暖色挺协调",实际两个频道 ΔE 23 谁也认不出谁。

更阴险的是**色觉缺陷**。旧色板在绿色盲下最差色差只有 4.0,
基本等于一排一模一样的方块;而这个数字肉眼永远看不出来,
只能靠算。第一版新色板拉高了正常视觉的色差,绿色盲下反而掉到 4.0 ——
优化了一个指标,把另一个做坏了还不自知。所以这道闸门必须是自动的。

## 这个脚本不管什么

它**不保证颜色好看**,也不该管。它只回答一个问题:
新加/改动一个频道色之后,有没有和已有的撞到分不开。

    python3 scripts/check_channel_tones.py
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKENS = ROOT / "design/tokens.json"

#: 已上线 + 明确要上的频道,取 channelTones 的前 N 个槽。
#: 预留槽不算在门槛里 —— 它们本来就分不开(见下面 MAX_USABLE)。
LIVE_SLOTS = 5

#: 正常视觉门槛。低于这个数,40px 图标上就要靠读字才能分辨。
MIN_DE_NORMAL = 28.0

#: 色觉缺陷下的门槛。定得比正常视觉低很多,是因为**物理上做不到更高** ——
#: 不是放水。旧色板这里是 4.0,新色板 12.9;要求 20 的话无解。
#: 颜色在这里本来就只是加速器,主标识是频道的汉字。
MIN_DE_CVD = 10.0

#: 超过这个数,颜色就分不动了(实测八槽在色觉缺陷下掉到 8.7)。
#: 到了这一步该换承载方式(分组、二级页),不是继续挤色板。
MAX_USABLE = 5

# Brettel/Viénot 线性 RGB 近似矩阵
CVD = {
    "红色盲": [[.152, 1.053, -.205], [.115, .786, .099], [-.004, -.048, 1.052]],
    "绿色盲": [[.367, .861, -.228], [.280, .673, .047], [-.012, .043, .969]],
    "蓝色盲": [[1.256, -.077, -.179], [-.078, .931, .148], [.005, .691, .304]],
}

NAMES = ["外卖", "住宿", "团购", "打车", "帮我送", "预留6", "预留7", "预留8"]


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def to_lin(h):
    return [_lin(int(h[i:i + 2], 16)) for i in (1, 3, 5)]


def lab_lin(r, g, b):
    x = r * .4124 + g * .3576 + b * .1805
    y = r * .2126 + g * .7152 + b * .0722
    z = r * .0193 + g * .1192 + b * .9505

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29

    fx, fy, fz = f(x / .95047), f(y), f(z / 1.08883)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def views(hex_):
    """一个色在正常 + 三种色觉缺陷下的 Lab。"""
    lin = to_lin(hex_)
    out = {"正常": lab_lin(*lin)}
    for name, m in CVD.items():
        out[name] = lab_lin(*[sum(m[r][c] * lin[c] for c in range(3))
                              for r in range(3)])
    return out


def contrast(fg, bg):
    def lum(h):
        r, g, b = to_lin(h)
        return .2126 * r + .7152 * g + .0722 * b
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + .05) / (lo + .05)


def blend(fg, bg, alpha):
    return "#" + "".join(
        "%02X" % round(int(fg[i:i + 2], 16) * alpha
                       + int(bg[i:i + 2], 16) * (1 - alpha))
        for i in (1, 3, 5))


def check(scheme_name, tones, surface, semantic):
    bad = []
    labs = [views(t) for t in tones[:LIVE_SLOTS]]

    for view in ("正常", "红色盲", "绿色盲", "蓝色盲"):
        floor = MIN_DE_NORMAL if view == "正常" else MIN_DE_CVD
        worst, pair = 999.0, None
        for i in range(LIVE_SLOTS):
            for j in range(i + 1, LIVE_SLOTS):
                d = math.dist(labs[i][view], labs[j][view])
                if d < worst:
                    worst, pair = d, (NAMES[i], NAMES[j])
        mark = "✓" if worst >= floor else "✗"
        print(f"  {mark} {scheme_name} {view:<4} 最差 ΔE {worst:5.1f} "
              f"(门槛 {floor:.0f}) —— {pair[0]}↔{pair[1]}")
        if worst < floor:
            bad.append(f"{scheme_name}/{view}:{pair[0]}↔{pair[1]} "
                       f"只差 ΔE {worst:.1f},门槛 {floor:.0f}")

    # 频道字画在自身 12% 淡底上 —— 见 user_app 的 glyphChip
    for i, t in enumerate(tones[:LIVE_SLOTS]):
        cr = contrast(t, blend(t, surface, 0.12))
        if cr < 4.5:
            bad.append(f"{scheme_name}:{NAMES[i]} 的字在自身淡底上"
                       f"对比度只有 {cr:.2f},不到 4.5")

    # 频道色不许和金额语义色撞 —— 撞了「住宿」标签看着就像一笔钱
    for i, t in enumerate(tones):
        for key in ("earn", "hold", "danger", "clay"):
            if t.upper() == semantic[key].upper():
                bad.append(f"{scheme_name}:{NAMES[i]} 的色 {t} 和语义色 "
                           f"{key} 是同一个值 —— 频道标签会被读成金额/状态")
    return bad


def main():
    d = json.loads(TOKENS.read_text())
    print(f"频道色可分辨性(前 {LIVE_SLOTS} 个槽):")
    bad = check("浅", d["light"]["channelTones"], d["light"]["surface"],
                d["light"])
    bad += check("深", d["dark"]["channelTones"], d["dark"]["surface"],
                 d["dark"])

    n = len(d["light"]["channelTones"])
    if n > MAX_USABLE:
        print(f"\n  提示:色板有 {n} 个槽,但只有前 {MAX_USABLE} 个能真正靠颜色分开。")
        print("       领用第 6 个之前,先想清楚是不是该换承载方式"
              "(分组 / 二级页),而不是继续挤色板。")

    if bad:
        print("\n✗ 频道色不合格:")
        for b in bad:
            print("   ", b)
        print("\n   重解一版:见 brand.dart 里 channelTones 的文档注释。")
        return 1
    print("\n✓ 频道色可分辨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
