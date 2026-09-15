#!/usr/bin/env python3
"""萌兽三路的美术和音效:从 Kenney 的 CC0 素材包里挑图、拼图集、转 webp / m4a。

素材包**不进仓库**(见 ../ASSETS.md:每个包的官网地址、zip 地址、许可证)。要重新生成:

    # 1. 从 kenney.nl 各包页面下载 zip,解压到同一个目录,子目录名 = 页面地址里的名字:
    #    <素材目录>/animal-pack-remastered/  rpg-base/  ui-pack-adventure/  game-icons/  board-game-icons/  particle-pack/
    #    smoke-particles/  interface-sounds/  impact-sounds/  rpg-audio/  music-jingles/  casino-audio/  sci-fi-sounds/
    # 2. 生成(要 Pillow 和 ffmpeg):
    python3 miniapps/critters/tools/build_assets.py <素材目录>

产物:public/art/*.webp(三张图集 + 界面用的几张)、public/art/icon/*.webp(图标,当遮罩用)、
public/sfx/*.m4a、src/art.ts(图集里每一帧的坐标,自动生成)。产物都进仓库,构建时不再跑这个脚本。
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else None
HERE = Path(__file__).resolve().parent.parent  # miniapps/critters
ART = HERE / "public/art"
SFX = HERE / "public/sfx"
T = 128  # RPG Base 2 倍表格一格的像素;战场上一格在 3 倍屏上约 130 像素
QUALITY = 88


def pack(name: str) -> Path:
    p = SRC / name
    if not p.is_dir():
        sys.exit(f"缺素材包目录 {p}(见 ASSETS.md)")
    return p


# ---------------------------------------------------------------- 小工具


def trim(im: Image.Image, pad: int = 2) -> Image.Image:
    """裁掉四周全透明的边,留 pad 像素"""
    box = im.getchannel("A").getbbox()
    if not box:
        return im
    l, t, r, b = box
    return im.crop((max(0, l - pad), max(0, t - pad), min(im.width, r + pad), min(im.height, b + pad)))


def fit(im: Image.Image, w: int, h: int) -> Image.Image:
    """等比缩到放得进 w×h(只缩不放)"""
    s = min(w / im.width, h / im.height, 1.0)
    if s >= 1:
        return im
    return im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)


def scale(im: Image.Image, s: float) -> Image.Image:
    return im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)


def hsv(im: Image.Image, dh: int = 0, ks: float = 1.0, kv: float = 1.0, add_v: int = 0) -> Image.Image:
    """整体调色:色相平移 dh(0–255 一圈)、饱和度 ×ks、明度 ×kv 再加 add_v。透明度不动"""
    rgba = im.convert("RGBA")
    a = rgba.getchannel("A")
    h, s, v = rgba.convert("RGB").convert("HSV").split()
    h = h.point(lambda x: (x + dh) % 256)
    s = s.point(lambda x: max(0, min(255, round(x * ks))))
    v = v.point(lambda x: max(0, min(255, round(x * kv + add_v))))
    out = Image.merge("HSV", (h, s, v)).convert("RGB").convert("RGBA")
    out.putalpha(a)
    return out


def snowy(im: Image.Image, k: float = 0.7) -> Image.Image:
    """把偏绿的像素往雪白里掺(树冠盖雪),树干这类不绿的不动"""
    rgba = im.convert("RGBA")
    px = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = px[x, y]
            if a and g > r + 8 and g >= b:
                lum = (r * 3 + g * 6 + b) / 10 / 255
                tr, tg, tb = 228 + 22 * lum, 236 + 16 * lum, 244 + 10 * lum
                px[x, y] = (round(r + (tr - r) * k), round(g + (tg - g) * k), round(b + (tb - b) * k), a)
    return rgba


def tint(im: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """白色的粒子图染色:颜色乘上去,透明度用原图的亮度"""
    g = im.convert("RGBA")
    a = ImageChops.multiply(g.getchannel("A"), g.convert("L"))
    out = Image.new("RGBA", g.size, color + (255,))
    out.putalpha(a)
    return out


def white_alpha(im: Image.Image) -> Image.Image:
    """黑底 / 调色板的白粒子 → 白色 + 透明度"""
    g = im.convert("RGBA")
    a = ImageChops.multiply(g.getchannel("A"), g.convert("L"))
    out = Image.new("RGBA", g.size, (255, 255, 255, 255))
    out.putalpha(a)
    return out


def save_webp(im: Image.Image, path: Path, quality: int = QUALITY, lossless: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "WEBP", quality=quality, method=6, lossless=lossless, exact=False)


class Atlas:
    """货架式装箱:按高度从高到低一排排摆,每张图四周留 2 像素透明边,防止缩放时串色"""

    def __init__(self, name: str, width: int):
        self.name = name
        self.width = width
        self.items: list[tuple[str, Image.Image, tuple[float, float]]] = []

    def add(self, key: str, im: Image.Image, anchor: tuple[float, float] = (0.5, 0.5)) -> None:
        if any(k == key for k, _, _ in self.items):
            raise SystemExit(f"{self.name} 里 {key} 重复")
        self.items.append((key, im.convert("RGBA"), anchor))

    def build(self) -> dict:
        pad = 2
        order = sorted(self.items, key=lambda it: (-it[1].height, it[0]))
        x = y = row_h = 0
        placed = {}
        for key, im, anchor in order:
            w, h = im.width + pad * 2, im.height + pad * 2
            if x + w > self.width:
                x, y, row_h = 0, y + row_h, 0
            placed[key] = (x + pad, y + pad, im, anchor)
            x += w
            row_h = max(row_h, h)
        height = y + row_h
        height = (height + 3) // 4 * 4
        sheet = Image.new("RGBA", (self.width, height), (0, 0, 0, 0))
        frames = {}
        for key, (px, py, im, anchor) in sorted(placed.items()):
            sheet.alpha_composite(im, (px, py))
            frames[key] = [px, py, im.width, im.height, anchor[0], anchor[1]]
        save_webp(sheet, ART / f"{self.name}.webp")
        return {"src": f"art/{self.name}.webp", "w": self.width, "h": height, "frames": frames}


# ---------------------------------------------------------------- 动物(单位)和卡面

ANIMALS = ["bear", "buffalo", "chick", "chicken", "cow", "crocodile", "dog", "duck", "elephant", "frog", "giraffe",
           "goat", "gorilla", "hippo", "horse", "monkey", "moose", "narwhal", "owl", "panda", "parrot", "penguin",
           "pig", "rabbit", "rhino", "sloth", "snake", "walrus", "whale", "zebra"]


def rpg_sheet() -> Image.Image:
    return Image.open(pack("rpg-base") / "Spritesheet/RPGpack_sheet_2X.png").convert("RGBA")


def cell(sheet: Image.Image, c: int, r: int, w: int = 1, h: int = 1) -> Image.Image:
    return sheet.crop((c * T, r * T, (c + w) * T, (r + h) * T))


def orb(color: tuple[int, int, int], rim: tuple[int, int, int], layers: list[tuple[Image.Image, float]],
        inner: tuple[int, int, int] | None = None) -> Image.Image:
    """法术卡面:一个带深色描边的圆球(中间亮、边上暗的径向渐变),里面叠几层粒子。先画 4 倍再缩小,边缘不锯齿"""
    S = 4
    size = 150
    big = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    d.ellipse([6 * S, 6 * S, (size - 6) * S, (size - 6) * S], fill=rim + (255,))
    # 径向渐变:中心 inner → 边上 color
    c0 = inner or tuple(min(255, round(v * 1.35 + 30)) for v in color)
    grad = Image.new("RGBA", big.size, (0, 0, 0, 0))
    gp = grad.load()
    cx = cy = size * S / 2
    rad = (size / 2 - 13) * S
    for y in range(big.height):
        for x in range(0, big.width):
            t = ((x - cx) ** 2 + (y - cy * 0.92) ** 2) ** 0.5 / rad
            if t <= 1.08:
                k = min(1.0, t) ** 1.6
                gp[x, y] = (round(c0[0] + (color[0] - c0[0]) * k), round(c0[1] + (color[1] - c0[1]) * k),
                            round(c0[2] + (color[2] - c0[2]) * k), 255)
    inner_mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(inner_mask).ellipse([13 * S, 13 * S, (size - 13) * S, (size - 13) * S], fill=255)
    grad.putalpha(ImageChops.multiply(grad.getchannel("A"), inner_mask))
    big.alpha_composite(grad)
    # 左上一块高光
    hi = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(hi).ellipse([30 * S, 22 * S, 88 * S, 64 * S], fill=(255, 255, 255, 80))
    big.alpha_composite(hi.filter(ImageFilter.GaussianBlur(6 * S)))
    out = big.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([13, 13, size - 13, size - 13], fill=255)
    for im, k in layers:
        lay = fit(im, round(size * k), round(size * k))
        tmp = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tmp.alpha_composite(lay, ((size - lay.width) // 2, (size - lay.height) // 2))
        tmp.putalpha(ImageChops.multiply(tmp.getchannel("A"), mask))
        out.alpha_composite(tmp)
    return out


def tower(sheet: Image.Image, enemy: bool, window: bool = True) -> Image.Image:
    """哨塔:尖顶(6,6)压在一段墙上;墙用左边沿(0,4)的左半 + 右边沿(3,4)的右半拼,两边都有边。
    电脑一方用灰石墙、深色屋顶(同一行往右 9 格)"""
    o = 9 if enemy else 0
    wall = Image.new("RGBA", (T, T))
    wall.alpha_composite(cell(sheet, 0 + o, 4).crop((0, 0, T // 2, T)), (0, 0))
    wall.alpha_composite(cell(sheet, 3 + o, 4).crop((T // 2, 0, T, T)), (T // 2, 0))
    im = Image.new("RGBA", (T, T * 2 - 24))
    im.alpha_composite(wall, (0, T - 24))
    im.alpha_composite(cell(sheet, 6 + o, 6), (0, 0))
    if window:
        win = scale(cell(sheet, 17 if enemy else 12, 9), 0.72)
        im.alpha_composite(win, ((T - win.width) // 2, T - 24 + 18))
    return trim(im)


def base(sheet: Image.Image, enemy: bool) -> Image.Image:
    """大本营:两格宽的山墙屋顶(2,6)(3,6) + 两格墙 + 拱门"""
    o = 9 if enemy else 0
    im = Image.new("RGBA", (T * 2, T * 2 - 16))
    im.alpha_composite(cell(sheet, 0 + o, 4), (0, T - 16))
    im.alpha_composite(cell(sheet, 3 + o, 4), (T, T - 16))
    im.alpha_composite(cell(sheet, 2 + o, 6), (0, 0))
    im.alpha_composite(cell(sheet, 3 + o, 6), (T, 0))
    door = cell(sheet, 19 if enemy else 14, 10)
    im.alpha_composite(door, (T // 2, T - 16))
    for wx in (6, T * 2 - 6 - 44):
        win = scale(cell(sheet, 18 if enemy else 13, 9), 0.7)
        im.alpha_composite(win, (wx, T - 16 + 22))
    return trim(im)


def ruin(src: Image.Image, keep: float) -> Image.Image:
    """倒了的塔:只留底下 keep 那一截,上沿咬成锯齿,整体压暗一点"""
    w, h = src.size
    top = round(h * (1 - keep))
    part = src.crop((0, top, w, h))
    mask = Image.new("L", part.size, 255)
    d = ImageDraw.Draw(mask)
    pts = [(0, 0)]
    x = 0
    k = 0
    while x < w:
        x = min(w, x + w // 7)
        pts.append((x, (k % 2) * (part.height * 0.28) + (k % 3) * 3))
        k += 1
    pts += [(w, 0)]
    d.polygon(pts + [(w, 0), (0, 0)], fill=0)
    part.putalpha(ImageChops.multiply(part.getchannel("A"), mask))
    return trim(hsv(part, 0, 0.8, 0.82))


def build_units(sheet: Image.Image, fx: dict[str, Image.Image]) -> dict:
    at = Atlas("units", 1024)
    src = pack("animal-pack-remastered") / "PNG/Round (outline)"
    for a in ANIMALS:
        im = trim(Image.open(src / f"{a}.png").convert("RGBA"), 1)
        at.add(a, im, (0.5, 0.5))
    # 法术的卡面(也用在对局里的法术图标上)
    at.add("spell-fire", orb((210, 58, 30), (120, 30, 16), [(tint(fx["glow"], (255, 214, 120)), 1.0),
                                                            (tint(fx["flame"], (255, 246, 210)), 0.62)], inner=(255, 176, 60)))
    at.add("spell-freeze", orb((52, 124, 196), (26, 70, 128), [(tint(fx["glow"], (200, 240, 255)), 0.9),
                                                               (tint(fx["star"], (255, 255, 255)), 0.9)], inner=(150, 214, 255)))
    at.add("spell-heal", orb((52, 150, 78), (28, 96, 48), [(tint(fx["glow"], (220, 255, 210)), 0.9),
                                                           (tint(fx["heart"], (255, 255, 255)), 0.52)], inner=(150, 230, 140)))
    at.add("spell-rage", orb((214, 96, 24), (130, 52, 14), [(tint(fx["twirl"], (255, 244, 200)), 1.0),
                                                            (tint(fx["spark"], (255, 255, 235)), 0.6)], inner=(255, 196, 80)))
    # 建筑卡:栅栏、鸡窝(木箱上蹲一只母鸡)、瞭望台(木色小塔)
    fence = trim(cell(sheet, 6, 10, 2, 1))
    at.add("fence", fence, (0.5, 0.78))
    coop = Image.new("RGBA", (T, T + 40))
    crate = trim(cell(sheet, 8, 9))
    crate = scale(crate, 1.25)
    coop.alpha_composite(crate, ((T - crate.width) // 2, T + 40 - crate.height))
    hen = scale(trim(Image.open(src / "chicken.png").convert("RGBA"), 1), 0.62)
    coop.alpha_composite(hen, ((T - hen.width) // 2, T + 40 - crate.height - hen.height + 26))
    at.add("coop", trim(coop), (0.5, 0.82))
    at.add("lookout", scale(tower(sheet, False, True), 0.78), (0.5, 0.86))
    return at.build()


# ---------------------------------------------------------------- 战场

THEMES = {
    # 草地(色相平移、饱和度、明度)、土路、树
    "meadow": {"grass": (0, 1.0, 1.0, 0), "dirt": (0, 1.0, 1.0, 0), "trees": "green"},
    "swamp": {"grass": (-6, 0.72, 0.74, 0), "dirt": (0, 0.85, 0.66, 0), "trees": "dark"},
    "snow": {"grass": (48, 0.16, 0.5, 132), "dirt": (100, 0.22, 0.6, 96), "trees": "snow"},
    "jungle": {"grass": (10, 1.0, 0.7, 0), "dirt": (-4, 1.1, 0.78, 0), "trees": "dark"},
    "highland": {"grass": (-18, 0.72, 0.98, 0), "dirt": (6, 0.72, 1.08, 0), "trees": "orange"},
}


def build_world(sheet: Image.Image) -> dict:
    at = Atlas("world", 1536)
    grass = [cell(sheet, 3, 2), cell(sheet, 4, 2)]
    dirt = cell(sheet, 6, 1)  # 土坑 3×3 的正中那格:四边没有草
    trees = {"green": (0, 1), "orange": (2, 3), "dark": (4, 5)}
    for name, th in THEMES.items():
        for i, g in enumerate(grass):
            at.add(f"grass-{name}-{i}", hsv(g, *th["grass"]), (0, 0))
        at.add(f"dirt-{name}", hsv(dirt, *th["dirt"]), (0, 0))
    for kind, (big, small) in trees.items():
        at.add(f"tree-{kind}-0", trim(cell(sheet, big, 10, 1, 2)), (0.5, 0.94))
        at.add(f"tree-{kind}-1", trim(cell(sheet, small, 10, 1, 2)), (0.5, 0.94))
    at.add("tree-snow-0", snowy(trim(cell(sheet, 4, 10, 1, 2))), (0.5, 0.94))
    at.add("tree-snow-1", snowy(trim(cell(sheet, 5, 10, 1, 2))), (0.5, 0.94))
    for i in range(6):
        b = trim(cell(sheet, i, 9))
        at.add(f"bush-{i}", b, (0.5, 0.8))
    at.add("bush-snow-0", snowy(trim(cell(sheet, 4, 9)), 0.6), (0.5, 0.8))
    at.add("bush-snow-1", snowy(trim(cell(sheet, 5, 9)), 0.6), (0.5, 0.8))
    pond = trim(cell(sheet, 10, 0, 3, 3))
    at.add("pond", pond, (0.5, 0.5))
    at.add("pond-ice", hsv(pond, 12, 0.35, 1.05, 30), (0.5, 0.5))
    at.add("barrel", trim(cell(sheet, 8, 10)), (0.5, 0.85))
    at.add("crate", trim(cell(sheet, 8, 9)), (0.5, 0.85))
    at.add("fence-post", trim(cell(sheet, 7, 11)), (0.5, 0.8))
    at.add("tower-0", tower(sheet, False), (0.5, 0.88))
    at.add("tower-1", tower(sheet, True), (0.5, 0.88))
    at.add("base-0", base(sheet, False), (0.5, 0.86))
    at.add("base-1", base(sheet, True), (0.5, 0.86))
    # 废墟用不带窗、不带门的墙,免得断墙上还挂着半扇窗
    for side, o in ((0, 0), (1, 9)):
        wall1 = Image.new("RGBA", (T, T))
        wall1.alpha_composite(cell(sheet, 0 + o, 4).crop((0, 0, T // 2, T)), (0, 0))
        wall1.alpha_composite(cell(sheet, 3 + o, 4).crop((T // 2, 0, T, T)), (T // 2, 0))
        wall2 = Image.new("RGBA", (T * 2, T))
        wall2.alpha_composite(cell(sheet, 0 + o, 4), (0, 0))
        wall2.alpha_composite(cell(sheet, 3 + o, 4), (T, 0))
        at.add(f"ruin-tower-{side}", ruin(wall1, 0.5), (0.5, 0.72))
        at.add(f"ruin-base-{side}", ruin(wall2, 0.45), (0.5, 0.72))
    return at.build()


# ---------------------------------------------------------------- 粒子

def load_fx() -> dict[str, Image.Image]:
    pp = pack("particle-pack") / "PNG (Transparent)"
    sp = pack("smoke-particles") / "PNG"
    raw = {
        "dot": pp / "circle_05.png", "ring": pp / "circle_02.png", "glow": pp / "light_01.png",
        "star": pp / "star_06.png", "twinkle": pp / "star_07.png", "spark": pp / "spark_01.png",
        "slash": pp / "slash_02.png", "smoke": pp / "smoke_07.png", "dirt": pp / "dirt_02.png",
        "flame": pp / "flame_05.png", "heart": pp / "symbol_01.png", "twirl": pp / "twirl_02.png",
        "scorch": pp / "scorch_02.png", "magic": pp / "magic_05.png", "trace": pp / "trace_04.png",
        "puff0": sp / "White puff/whitePuff00.png", "puff1": sp / "White puff/whitePuff05.png",
        "puff2": sp / "White puff/whitePuff10.png",
    }
    out = {k: trim(white_alpha(Image.open(v)), 2) for k, v in raw.items()}
    for i, n in enumerate(["explosion01", "explosion04", "explosion06"]):
        out[f"boom{i}"] = trim(Image.open(sp / f"Explosion/{n}.png").convert("RGBA"), 2)
    out["boom"] = out["boom1"]
    return out


def build_fx(fx: dict[str, Image.Image]) -> dict:
    at = Atlas("fx", 1024)
    sizes = {"dot": 48, "ring": 128, "glow": 96, "star": 64, "twinkle": 64, "spark": 96, "slash": 112, "smoke": 96,
             "dirt": 96, "flame": 64, "heart": 48, "twirl": 96, "scorch": 112, "magic": 96, "trace": 64,
             "puff0": 96, "puff1": 96, "puff2": 96, "boom0": 144, "boom1": 144, "boom2": 144}
    for k, s in sizes.items():
        at.add(k, fit(fx[k], s, s))
    return at.build()


# ---------------------------------------------------------------- 界面图(CSS 用)和图标(遮罩)

def build_ui() -> None:
    up = pack("ui-pack-adventure") / "PNG/Double"
    for old in (ART / "ui").glob("*.webp"):
        old.unlink()
    # 结算页标题的红色横幅(面板、按钮都是 CSS 画的,颜色要跟亮暗主题走)
    save_webp(Image.open(up / "banner_hanging.png").convert("RGBA"), ART / "ui/banner.webp", 92)
    gi = pack("game-icons") / "PNG/White/2x"
    bg = pack("board-game-icons") / "PNG/Double (128px)"
    # 只留界面上真用到的(金币是 CSS 画的圆片,不用图)
    icons = {
        "pause": gi / "pause.png", "sound-on": gi / "audioOn.png", "sound-off": gi / "audioOff.png",
        "info": gi / "information.png", "star": gi / "star.png", "lock": gi / "locked.png", "trophy": gi / "trophy.png",
        "check": gi / "checkmark.png", "close": gi / "cross.png", "back": gi / "arrowLeft.png", "cards": gi / "menuGrid.png",
        "medal": gi / "medal1.png", "target": gi / "target.png", "calendar": bg / "notepad.png",
    }
    for old in (ART / "icon").glob("*.webp"):
        old.unlink()
    for name, path in icons.items():
        im = white_alpha(Image.open(path)) if "board-game" in str(path) else Image.open(path).convert("RGBA")
        im = trim(im, 4)
        side = max(im.width, im.height)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.alpha_composite(im, ((side - im.width) // 2, (side - im.height) // 2))
        save_webp(fit(sq, 96, 96), ART / f"icon/{name}.webp", 92)


# ---------------------------------------------------------------- 音效

SOUNDS = {
    "tap": ("interface-sounds", "click_002.ogg"),
    "pick": ("casino-audio", "card-slide-3.ogg"),
    "place": ("casino-audio", "card-place-2.ogg"),
    "shuffle": ("casino-audio", "card-shuffle.ogg"),
    "pop": ("interface-sounds", "drop_002.ogg"),
    "poof": ("interface-sounds", "drop_004.ogg"),
    "hit0": ("impact-sounds", "impactPunch_medium_000.ogg"),
    "hit1": ("impact-sounds", "impactPunch_medium_002.ogg"),
    "hit2": ("impact-sounds", "impactSoft_medium_001.ogg"),
    "heavy": ("impact-sounds", "impactPunch_heavy_001.ogg"),
    "throw": ("interface-sounds", "pluck_001.ogg"),
    "arrow": ("impact-sounds", "impactGeneric_light_002.ogg"),
    "tower": ("impact-sounds", "impactWood_medium_001.ogg"),
    "crash": ("impact-sounds", "impactWood_heavy_002.ogg"),
    "boom": ("sci-fi-sounds", "explosionCrunch_000.ogg"),
    "freeze": ("interface-sounds", "glass_002.ogg"),
    "heal": ("interface-sounds", "confirmation_002.ogg"),
    "rage": ("interface-sounds", "maximize_006.ogg"),
    "refund": ("interface-sounds", "tick_002.ogg"),
    "error": ("interface-sounds", "error_004.ogg"),
    "star": ("interface-sounds", "confirmation_001.ogg"),
    "coins": ("rpg-audio", "handleCoins.ogg"),
    "upgrade": ("interface-sounds", "maximize_008.ogg"),
    "count": ("interface-sounds", "tick_001.ogg"),
    "go": ("interface-sounds", "bong_001.ogg"),
    "win": ("music-jingles", "jingles_PIZZI02.ogg"),
    "lose": ("music-jingles", "jingles_PIZZI01.ogg"),
    "unlock": ("music-jingles", "jingles_PIZZI16.ogg"),
}


def build_sfx() -> list[str]:
    SFX.mkdir(parents=True, exist_ok=True)
    for f in SFX.glob("*.m4a"):
        f.unlink()
    for name, (pk, fn) in SOUNDS.items():
        hits = sorted(pack(pk).rglob(fn))
        if not hits:
            sys.exit(f"{pk} 里找不到 {fn}")
        # 单声道 44.1 kHz AAC 64 kbps;去掉元数据,同样的输入得到同样的文件
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(hits[0]), "-ac", "1", "-ar", "44100",
                        "-c:a", "aac", "-b:a", "64k", "-map_metadata", "-1", "-fflags", "+bitexact",
                        "-flags:a", "+bitexact", "-movflags", "+faststart", str(SFX / f"{name}.m4a")], check=True)
    return list(SOUNDS)


# ---------------------------------------------------------------- 生成 art.ts

def main() -> None:
    if not SRC:
        sys.exit(__doc__)
    ART.mkdir(parents=True, exist_ok=True)
    sheet = rpg_sheet()
    fx = load_fx()
    units = build_units(sheet, fx)
    world = build_world(sheet)
    fxa = build_fx(fx)
    build_ui()
    sounds = build_sfx()
    ts = [
        "// 由 tools/build_assets.py 生成,不要手改。图集里每一帧:[x, y, 宽, 高, 锚点 x, 锚点 y](锚点按宽高的比例)",
        "export interface Sheet { src: string; w: number; h: number; frames: Record<string, number[]> }",
        f"export const UNITS: Sheet = {json.dumps(units, ensure_ascii=False, separators=(',', ':'))}",
        f"export const WORLD: Sheet = {json.dumps(world, ensure_ascii=False, separators=(',', ':'))}",
        f"export const FX: Sheet = {json.dumps(fxa, ensure_ascii=False, separators=(',', ':'))}",
        f"export const SOUNDS = {json.dumps(sounds, ensure_ascii=False)} as const",
        "export type SoundName = typeof SOUNDS[number]",
        "",
    ]
    (HERE / "src/art.ts").write_text("\n".join(ts), encoding="utf-8")
    total = sum(f.stat().st_size for f in list(ART.rglob("*.webp")) + list(SFX.glob("*.m4a")))
    print(f"图集 units {units['w']}×{units['h']}、world {world['w']}×{world['h']}、fx {fxa['w']}×{fxa['h']};"
          f"音效 {len(sounds)} 个;美术和音效一共 {total // 1024} KB")


if __name__ == "__main__":
    main()
