#!/usr/bin/env python3
"""设计令牌单一来源:从 brand.dart 生成其余四端的令牌文件。

## 为什么需要它

查过一次:品牌主色在仓库里有**三个不同的值** —— Flutter 的 `#C15F3C`、
鸿蒙抄过去的 `#C04026`、商家后台和公开站硬编码的 `#FF5A1F`。
而 `docs/BRAND.md` 里 `#FF5A1F` 标着「v2 旧产品层色板,已废弃」。

不是谁改错了,是**规范改了而抄过去的那几份不会自己跟着改**。
一份份手工同步的东西,迟早分叉。

## 为什么事实来源是 brand.dart

它是被验证得最严的那一份:对比度算过(修 chip 字色撞底色、
inkFaint 收回只做装饰那两批)、`ledger_surface_test` 盯着深色台面。
web 侧和鸿蒙侧一行测试都没有。**事实来源要放在验证最严的一侧。**

## 为什么直接解析而不是跑 Dart

跑 Dart 要 Flutter SDK,而这个脚本要在 CI 的私密信息扫描那一档跑
(那一档只有 Python)。`SzColors.light/dark` 是纯 `const` 字面量,
正则解析足够稳 —— 而且解析不到会**报错退出**,不会悄悄生成半份。

    python3 scripts/gen_tokens.py          # 生成
    python3 scripts/gen_tokens.py --check  # 只校验是否与源一致(CI 用)
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BRAND = ROOT / "packages/shared/lib/src/brand.dart"
TOKENS = ROOT / "design/tokens.json"

#: 从 brand.dart 里取这些标量颜色。channelTones 是列表,单独处理。
COLOR_KEYS = [
    "paper", "surface", "surfaceAlt", "ink", "inkMuted", "inkFaint",
    "line", "clay", "claySoft", "earn", "hold", "danger", "ledger", "link",
]

#: 尺寸常量。**这些也要导出** —— 后台的圆角现在是 antd 默认的 6,
#: 而 App 是 8/12/18,同一个产品两种圆角。
SIZE_KEYS = ["kRadiusSm", "kRadiusMd", "kRadiusLg", "kPagePad", "kCardPad"]

#: 语义说明。生成的文件里带上,免得下一个人对着 `--sz-hold` 猜它是什么。
MEANING = {
    "paper": "页面底色",
    "surface": "卡片/浮层底",
    "surfaceAlt": "次级底(输入框、弱化区块)",
    "ink": "正文",
    "inkMuted": "次要文字。**要读懂的字用它,不要用 inkFaint**",
    "inkFaint": "只给装饰:图标、进度圈、分隔性元素。对比度不到 3.0",
    "line": "发丝线:卡片描边、列表分隔",
    "clay": "平台行动色:主 CTA、选中态",
    "claySoft": "clay 的淡底",
    "earn": "钱的正向:实收、到账、余额",
    "hold": "被抽走/待处理:佣金、超时、警示",
    "danger": "错误与不可逆操作",
    "ledger": "账目专属深台面",
    "link": "站外可跳转链接",
}


def _hex(dart_color: str) -> str:
    """`Color(0xFFC15F3C)` → `#C15F3C`(丢掉 alpha,web 侧一律不透明)。"""
    m = re.fullmatch(r"0x([0-9A-Fa-f]{2})([0-9A-Fa-f]{6})", dart_color)
    if m is None:
        raise SystemExit(f"✗ 认不出的颜色字面量:{dart_color}")
    if m.group(1).upper() != "FF":
        raise SystemExit(
            f"✗ {dart_color} 带透明度。令牌层不接受半透明 —— "
            "半透明在不同底色上是不同的颜色,而令牌要能被直接引用")
    return "#" + m.group(2).upper()


def parse_scheme(src: str, name: str) -> dict:
    """抠出 `static const light = SzColors( ... );` 那一段。"""
    m = re.search(
        r"static const " + name + r" = SzColors\((.*?)\n  \);", src, re.S)
    if m is None:
        raise SystemExit(f"✗ brand.dart 里找不到 SzColors.{name} —— "
                         "结构变了,这个脚本要跟着改")
    body = m.group(1)
    out = {}
    for key in COLOR_KEYS:
        km = re.search(key + r":\s*Color\((0x[0-9A-Fa-f]{8})\)", body)
        if km is None:
            raise SystemExit(f"✗ SzColors.{name} 里没找到 {key}")
        out[key] = _hex(km.group(1))
    tones = re.search(r"channelTones:\s*\[(.*?)\]", body, re.S)
    if tones is None:
        raise SystemExit(f"✗ SzColors.{name} 里没找到 channelTones")
    out["channelTones"] = [
        _hex(c) for c in re.findall(r"Color\((0x[0-9A-Fa-f]{8})\)",
                                    tones.group(1))]
    return out


def parse_sizes(src: str) -> dict:
    out = {}
    for key in SIZE_KEYS:
        m = re.search(r"const double " + key + r" = ([0-9.]+);", src)
        if m is None:
            raise SystemExit(f"✗ brand.dart 里没找到 {key}")
        out[key] = float(m.group(1))
    return out


def build() -> dict:
    src = BRAND.read_text()
    return {
        "_": "由 scripts/gen_tokens.py 从 packages/shared/lib/src/brand.dart "
             "生成。**不要手改这个文件**,改 brand.dart 再重新生成。",
        "meaning": MEANING,
        "light": parse_scheme(src, "light"),
        "dark": parse_scheme(src, "dark"),
        "size": parse_sizes(src),
    }


def _kebab(name: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1-\2", name).lower()


def css(tokens: dict) -> str:
    """CSS 变量。深色态走 prefers-color-scheme,和 App 的口径一致。"""
    def block(scheme: dict, indent: str = "  ") -> str:
        lines = []
        for k in COLOR_KEYS:
            lines.append(f"{indent}--sz-{_kebab(k)}: {scheme[k]};"
                         f"  /* {MEANING[k]} */")
        for i, c in enumerate(scheme["channelTones"]):
            lines.append(f"{indent}--sz-channel-{i}: {c};")
        return "\n".join(lines)

    size = "\n".join(f"  --sz-{_kebab(k)}: {int(v) if v == int(v) else v}px;"
                     for k, v in tokens["size"].items())

    # 派生淡底:语义色按 12% 混进卡片底。
    #
    # **不是新令牌**,是同一个色的淡化用法 —— Flutter 那边写作
    # `c.withValues(alpha: 0.12)`,CSS 这边没有运行时,所以在生成时算好。
    # 后台的日历有「今天 / 关房 / 拖选」几种格子底,原先是三个手挑的浅色
    # (#fff3ed / #fff1f0 / #ffd9c9),和主色没有任何关系 —— 换主色它们不跟。
    def soft(scheme, key, pct=12):
        fg = [int(scheme[key][i:i + 2], 16) for i in (1, 3, 5)]
        bg = [int(scheme["surface"][i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(
            "%02X" % round(f * pct / 100 + b * (1 - pct / 100))
            for f, b in zip(fg, bg))

    def softs(scheme, indent="  "):
        return "\n".join(
            f"{indent}--sz-{_kebab(k)}-soft: {soft(scheme, k)};"
            for k in ("danger", "hold", "earn"))
    return f"""/* 由 scripts/gen_tokens.py 生成,**不要手改**。
 * 改 packages/shared/lib/src/brand.dart 再跑 `python3 scripts/gen_tokens.py`。
 *
 * 为什么这份文件是生成的:品牌主色一度在仓库里有三个不同的值,
 * 而其中一个是 BRAND.md 里标着「已废弃」的旧色板 —— 手工同步一定会分叉。
 */
:root {{
{block(tokens['light'])}

{softs(tokens['light'])}

{size}
}}

/* 深色态。**只重定义颜色**,尺寸不随主题变 */
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
{block(tokens['dark'], '    ')}

{softs(tokens['dark'], '    ')}
  }}
}}

:root[data-theme="dark"] {{
{block(tokens['dark'])}

{softs(tokens['dark'])}
}}
"""


def antd_theme(tokens: dict) -> str:
    """Ant Design 的 theme.token。

    只映射 antd 认识的那几个键 —— 其余令牌走 CSS 变量。
    硬要把 14 个语义色都塞进 antd 的 token 体系会拧巴:
    它的 colorSuccess/colorWarning 和我们的 earn/hold 语义不完全重合
    (earn 是"钱到手",不是"操作成功")。
    """
    lt, dk, size = tokens["light"], tokens["dark"], tokens["size"]
    return f"""// 由 scripts/gen_tokens.py 生成,**不要手改**。
// 改 packages/shared/lib/src/brand.dart 再跑 `python3 scripts/gen_tokens.py`。
import type {{ ThemeConfig }} from 'antd'

/** 浅色态。语义与 App 对齐:clay=行动色,earn=钱的正向,hold=被抽走 */
export const szLight: ThemeConfig = {{
  token: {{
    colorPrimary: '{lt["clay"]}',
    colorSuccess: '{lt["earn"]}',
    colorWarning: '{lt["hold"]}',
    colorError: '{lt["danger"]}',
    colorLink: '{lt["link"]}',
    colorText: '{lt["ink"]}',
    colorTextSecondary: '{lt["inkMuted"]}',
    // ⚠️ 不要把 inkFaint 映射成 colorTextTertiary 之类会承载正文的角色:
    // 它对比度不到 3.0,只能做装饰(见 brand.dart 里那段说明)
    colorBorder: '{lt["line"]}',
    colorBgLayout: '{lt["paper"]}',
    colorBgContainer: '{lt["surface"]}',
    borderRadius: {int(size["kRadiusSm"])},
  }},
}}

/** 深色态 */
export const szDark: ThemeConfig = {{
  token: {{
    colorPrimary: '{dk["clay"]}',
    colorSuccess: '{dk["earn"]}',
    colorWarning: '{dk["hold"]}',
    colorError: '{dk["danger"]}',
    colorLink: '{dk["link"]}',
    colorText: '{dk["ink"]}',
    colorTextSecondary: '{dk["inkMuted"]}',
    colorBorder: '{dk["line"]}',
    colorBgLayout: '{dk["paper"]}',
    colorBgContainer: '{dk["surface"]}',
    borderRadius: {int(size["kRadiusSm"])},
  }},
}}
"""


def harmony_color_json(scheme: dict, dark: bool) -> str:
    """鸿蒙的 color.json。

    鸿蒙那两个工程原本是**手抄**的一份色板,主色抄成了 #C04026 ——
    和 Flutter 的 #C15F3C 差着一截。现在改成生成。
    """
    items = [{"name": "start_window_background",
              "value": scheme["paper"]}]
    for k in COLOR_KEYS:
        items.append({"name": _kebab(k).replace("-", "_"), "value": scheme[k]})
    # 鸿蒙侧页面里用到的别名(历史命名,保持不动免得改一堆页面)
    items.append({"name": "brand", "value": scheme["clay"]})
    items.append({"name": "brand_soft", "value": scheme["claySoft"]})
    items.append({"name": "page", "value": scheme["paper"]})
    items.append({"name": "surface_alt", "value": scheme["surfaceAlt"]})
    items.append({"name": "ink_muted", "value": scheme["inkMuted"]})
    items.append({"name": "ink_faint", "value": scheme["inkFaint"]})
    items.append({"name": "earn_soft",
                  "value": scheme["claySoft"] if dark else "#EAF5EF"})
    items.append({"name": "scrim", "value": "#66000000"})
    seen, uniq = set(), []
    for it in items:
        if it["name"] in seen:
            continue
        seen.add(it["name"])
        uniq.append(it)
    return json.dumps({"color": uniq}, ensure_ascii=False, indent=2) + "\n"


TARGETS = {}


def render_all(tokens: dict) -> dict:
    # ⚠️ 官网 `web/` **不在这里面**,这是故意的。
    #
    # `docs/BRAND.md` 是双层体系:传播层(海报 / 官网 hero / Logo)用品牌渐变
    # `#FF7A45 → #E1251B` 和超级红 `#E1251B`;产品层(三端 App 内)才用
    # `SzColors`。原话是「传播层(海报/官网/Logo)不变」。
    #
    # 把产品层令牌推到官网上会把这个分层推平 —— 那是把规范改掉,不是执行规范。
    # (官网现在的 `--orange: #FF5A1F` 两边都不是,既不是产品层新色也不是
    #  传播层的超级红。那是笔独立的账,要改得先有人拍板,不能顺手带过。)
    out = {
        "design/tokens.json":
            json.dumps(tokens, ensure_ascii=False, indent=2) + "\n",
        "merchant-web/src/tokens.css": css(tokens),
        "merchant-web/src/theme.ts": antd_theme(tokens),
    }
    for app in ("user_app_harmony", "merchant_app_harmony"):
        base = f"apps/{app}/entry/src/main/resources"
        out[f"{base}/base/element/color.json"] = harmony_color_json(
            tokens["light"], dark=False)
        out[f"{base}/dark/element/color.json"] = harmony_color_json(
            tokens["dark"], dark=True)
    return out


def main() -> int:
    check = "--check" in sys.argv
    tokens = build()
    files = render_all(tokens)
    stale = []
    for rel, content in files.items():
        path = ROOT / rel
        if not path.parent.exists():
            if check:
                stale.append(f"{rel}(目录不存在)")
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_text() if path.exists() else None
        if old == content:
            continue
        if check:
            stale.append(rel)
        else:
            path.write_text(content)
            print(f"  写入 {rel}")
    if check:
        if stale:
            print("✗ 这些生成文件与 brand.dart 不一致,跑一次 "
                  "`python3 scripts/gen_tokens.py`:")
            for s in stale:
                print("   ", s)
            return 1
        print(f"✓ 令牌一致(主色 {tokens['light']['clay']})")
        return 0
    print(f"✓ 令牌已生成,主色 {tokens['light']['clay']} / "
          f"深色 {tokens['dark']['clay']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
