#!/usr/bin/env python3
"""官网开城地图(web/src/films/OpenCityMapFilm.jsx)用的省界数据。

从大屏在用的 web/public/geo/china.json 投影、抽稀,写成
web/src/films/chinaGeo.js。一个点都不是手画的,重跑这个脚本就能复现。

    python3 scripts/gen_site_geo.py

## 为什么不用设计交接包里那份 sz-china-geo.js

那份是同一个源文件抽出来的,但少了**上海和澳门**两个省级行政区
(抽稀阈值把小面积的整个丢了),南海诸岛也不在里面(画幅裁到北纬 18°)。
公开的中国地图少一块,是事故不是瑕疵。所以这里的规矩是:

- 34 个省级行政区一个不少;抽稀抽没了的小块,退回原始轮廓;
- 北纬 17.5° 以南的岛礁(西沙、中沙、南沙)画在右下角的「南海诸岛」附图里,
  主图不裁掉任何一块陆地和岛屿;
- 投影同设计稿:等距圆柱,经度按北纬 36° 压缩(cos 36°),画幅宽 1000。

## 南海断续线

china.json 里没有断续线,单独放在 web/public/geo/china_dashline.json:从阿里云 DataV.GeoAtlas
全国边界(areas_v3/bound/100000_full.json)里 adcode 为 100000_JD 的要素原样取出,十段
(台湾以东那一段也在,和现行标准地图一致)。附图里十段全画;北纬 17.5° 以北的三段
(台湾以东、巴士海峡、东沙以东)在主图里也画,主图下沿放到把它们装下。
官网开城地图和 /screen 大屏读的是同一份生成结果,两边一起有。
按《地图管理条例》公开展示的中国地图还要送审(审图号),这件事不在这个脚本里解决。
"""
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "web/public/geo/china.json"
DASH_SRC = ROOT / "web/public/geo/china_dashline.json"
OUT = ROOT / "web/src/films/chinaGeo.js"

WIDTH = 1000
K = math.cos(math.radians(36))
#: 北纬这条线以南的多边形进附图(海南岛最南端在 18.1°,西沙在 16.5° 上下)
SOUTH_SEA_LAT = 17.5
#: 抽稀容差,单位是画幅像素(1000 宽下约 0.08°)
EPS = 1.6
#: 附图的经纬度窗口:左边带上北部湾,上边带上海南岛和广东沿海;
#: 右上角带上台湾以东那段断续线(东经 122.8°、北纬 24.6° 以内)
INSET_LON = (105.5, 123.1)
INSET_LAT = (3.0, 24.9)
#: 附图宽度(画幅像素)和离画幅边缘的距离
INSET_W = 150
INSET_PAD = 6


def rings(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    return [poly[0] for poly in geom["coordinates"]]


def centroid(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def rdp(pts, eps):
    """Ramer–Douglas–Peucker,迭代版(省界一圈几千个点,递归会爆栈)。"""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            x0, y0 = pts[i]
            if norm == 0:
                d = math.hypot(x0 - x1, y0 - y1)
            else:
                d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
            if d > best:
                best, idx = d, i
        if best > eps and idx > 0:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(pts, keep) if k]


def main():
    data = json.loads(SRC.read_text())
    feats = data["features"]

    dash_rings = [poly[0] for f in json.loads(DASH_SRC.read_text())["features"]
                  for poly in f["geometry"]["coordinates"]]
    # 主图范围:北纬 17.5° 以北的全部多边形
    lons, lats = [], []
    for f in feats:
        for r in rings(f["geometry"]):
            if centroid(r)[1] < SOUTH_SEA_LAT:
                continue
            lons += [p[0] for p in r]
            lats += [p[1] for p in r]
    lon0, lon1 = min(lons), max(lons)
    lat1 = max(lats)
    # 下沿:主图里要画的那几段断续线也得装下(东沙以东那段比海南岛南端还往南一点)
    main_dash = [i for i, r in enumerate(dash_rings) if centroid(r)[1] >= SOUTH_SEA_LAT]
    lat0 = min(lats + [p[1] for i in main_dash for p in dash_rings[i]])
    scale = WIDTH / ((lon1 - lon0) * K)
    height = round((lat1 - lat0) * scale)

    def proj(lon, lat):
        return ((lon - lon0) * K * scale, (lat1 - lat) * scale)

    def path(ring):
        pts = [proj(*p) for p in ring]
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        simple = rdp(pts + [pts[0]], EPS)[:-1]
        # 抽稀抽成一条线或一个点的小块(澳门、近岸小岛)退回原始轮廓 —— 不许丢
        if len(simple) < 3:
            simple = pts
        return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in simple) + "Z"

    provinces = []
    islands = []
    for f in feats:
        name = f["properties"]["name"]
        parts = []
        for r in rings(f["geometry"]):
            if centroid(r)[1] < SOUTH_SEA_LAT:
                cx, cy = proj(*centroid(r))
                islands.append([round(cx, 1), round(cy, 1)])
                continue
            parts.append(path(r))
        cp = proj(*f["properties"]["cp"])
        provinces.append({"n": name, "cp": [round(cp[0], 1), round(cp[1], 1)],
                          "d": "".join(parts)})

    # 断续线:一段是一个细长的多边形,点不多,不抽稀;主图和附图用同一套坐标
    def dash_path(ring):
        pts = [proj(*p) for p in ring]
        if pts[0] == pts[-1]:
            pts = pts[:-1]
        return "M" + "L".join(f"{x:.2f} {y:.2f}" for x, y in pts) + "Z"

    dashes = [dash_path(r) for r in dash_rings]
    for i in main_dash:
        for p in dash_rings[i]:
            x, y = proj(*p)
            assert 0 <= x <= WIDTH and 0 <= y <= height + 0.5, f"主图里第 {i} 段断续线出了画幅"
    for i, r in enumerate(dash_rings):
        for lon, lat in r:
            assert INSET_LON[0] <= lon <= INSET_LON[1] and INSET_LAT[0] <= lat <= INSET_LAT[1], \
                f"第 {i} 段断续线出了附图窗口"

    # 附图:同一个投影,整体缩放到 INSET_W 宽,贴右下角
    ix0, iy0 = proj(INSET_LON[0], INSET_LAT[1])
    ix1, iy1 = proj(INSET_LON[1], INSET_LAT[0])
    k = INSET_W / (ix1 - ix0)
    inset_h = (iy1 - iy0) * k
    inset = {
        # 附图框在画幅里的位置
        "x": round(WIDTH - INSET_W - INSET_PAD, 1),
        "y": round(height - inset_h - INSET_PAD, 1),
        "w": INSET_W, "h": round(inset_h, 1),
        # 主图坐标 → 附图坐标:translate(x, y) scale(k) translate(-ox, -oy)
        "k": round(k, 4), "ox": round(ix0, 1), "oy": round(iy0, 1),
    }

    names = [p["n"] for p in provinces]
    assert len(names) == 34, f"省级行政区应是 34 个,现在 {len(names)} 个"
    for must in ("上海市", "澳门特别行政区", "香港特别行政区", "台湾省", "海南省"):
        assert must in names, f"少了 {must}"
    assert islands, "南海诸岛一个都没进附图"
    assert len(dashes) == 10, f"断续线应是 10 段,现在 {len(dashes)} 段"

    geo = {"viewBox": f"0 0 {WIDTH} {height}", "w": WIDTH, "h": height,
           "provinces": provinces, "inset": inset, "islands": islands,
           # 南海断续线:dashes 十段全在附图里画;dashMain 是主图里也要画的那几段的下标
           "dashes": dashes, "dashMain": main_dash}
    body = json.dumps(geo, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(
        "/* 由 scripts/gen_site_geo.py 从 web/public/geo/china.json 和 china_dashline.json 生成,别手改。\n"
        "   34 个省级行政区;北纬 17.5° 以南的岛礁在 islands 里,画进「南海诸岛」附图;\n"
        "   南海断续线十段在 dashes 里,附图全画,dashMain 那几段主图也画。 */\n"
        f"export default {body}\n")
    print(f"  {OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.1f} KB"
          f"  · 画幅 1000×{height} · 省级 {len(provinces)} · 岛礁 {len(islands)}"
          f" · 断续线 {len(dashes)} 段(主图 {len(main_dash)} 段)")


if __name__ == "__main__":
    main()
