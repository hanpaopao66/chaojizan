"""生成品牌资产:App 图标(点赞大拇指,橙红渐变底)。

用法:cd server && source .venv/bin/activate && python ../scripts/gen_brand_assets.py
输出:assets/brand/icon.png(launcher 全图)与 icon_fg.png(自适应前景,
带安全区缩放)——flutter_launcher_icons 的输入。
几何参数与 marketing/brand/icon_A.svg(viewBox 512)一致;
App 内矢量版是 packages/shared/lib/src/brand.dart 的 CustomPaint,改造型两边同步。
"""
from pathlib import Path

from PIL import Image, ImageDraw

GRAD_FROM = (255, 122, 69)    # #FF7A45
GRAD_TO = (225, 37, 27)       # #E1251B
YELLOW = (255, 211, 77)       # #FFD34D
WHITE = (255, 255, 255)

OUT = Path(__file__).resolve().parent.parent / "assets" / "brand"
SIZE = 1024
SS = 4  # 超采样抗锯齿


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def diag_gradient(size: int) -> Image.Image:
    """对角线性渐变(左上 GRAD_FROM → 右下 GRAD_TO),与 SVG 同向。"""
    small = 256
    img = Image.new("RGB", (small, small))
    px = img.load()
    for y in range(small):
        for x in range(small):
            px[x, y] = _lerp(GRAD_FROM, GRAD_TO, (x + y) / (2 * (small - 1)))
    return img.resize((size, size), Image.BICUBIC)


def grad_at(x: float, y: float):
    """SVG 坐标(0~512)处的渐变色(手掌上三条纹用)。"""
    return _lerp(GRAD_FROM, GRAD_TO, (x + y) / 1024)


def _cubic(p0, p1, p2, p3, t):
    mt = 1 - t
    return (mt**3 * p0[0] + 3 * mt**2 * t * p1[0]
            + 3 * mt * t**2 * p2[0] + t**3 * p3[0],
            mt**3 * p0[1] + 3 * mt**2 * t * p1[1]
            + 3 * mt * t**2 * p2[1] + t**3 * p3[1])


def draw_mark(draw: ImageDraw.ImageDraw, scale: float, offset: float = 0.0):
    """点赞标(SVG viewBox 512 坐标系 × scale + offset)。"""
    def rrect(x, y, w, h, rad, fill):
        draw.rounded_rectangle(
            [offset + x * scale, offset + y * scale,
             offset + (x + w) * scale, offset + (y + h) * scale],
            radius=rad * scale, fill=fill)

    # 大拇指:两段三次贝塞尔密集采样,沿路径盖圆章(等效圆头粗描边 width 68,
    # 不用 draw.line 的粗线段——端头拼接会出摩尔纹)
    pts = []
    for seg in [((244, 300), (239, 258), (237, 234), (233, 212)),
                ((233, 212), (229, 190), (224, 174), (215, 154))]:
        for i in range(161):
            pts.append(_cubic(*seg, i / 160))
    r_ = 68 * scale / 2
    for p in pts:
        c = (offset + p[0] * scale, offset + p[1] * scale)
        draw.ellipse([c[0] - r_, c[1] - r_, c[0] + r_, c[1] + r_], fill=WHITE)

    rrect(108, 246, 64, 168, 22, YELLOW)      # 黄条(袖口)
    rrect(190, 246, 204, 168, 36, WHITE)      # 手掌
    for y in (288, 326, 364):                 # 三条纹(账本线,取渐变中段色)
        rrect(262, y, 106, 14, 7, grad_at(315, y))


def build_icon() -> Image.Image:
    """launcher 全图:渐变圆角方 + 点赞标。"""
    s = SIZE * SS
    bg = diag_gradient(s).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, s, s], radius=int(s * 116 / 512), fill=255)
    icon = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), mask)
    draw_mark(ImageDraw.Draw(icon), scale=s / 512)
    return icon.resize((SIZE, SIZE), Image.LANCZOS)


def build_foreground() -> Image.Image:
    """自适应图标前景:透明底,点赞标缩进中心安全区(约 60%)。"""
    s = SIZE * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    scale = s / 512 * 0.60
    offset = (s - 512 * scale) / 2
    draw_mark(ImageDraw.Draw(img), scale=scale, offset=offset)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    build_icon().save(OUT / "icon.png")
    build_foreground().save(OUT / "icon_fg.png")
    print(f"✓ 品牌图标已生成: {OUT}/icon.png, icon_fg.png")
    print("  下一步:各 App 目录里 dart run flutter_launcher_icons")


if __name__ == "__main__":
    main()
