"""为演示数据抓取真实菜品/门店照片(Wikimedia Commons)。

为什么只用 Commons 且只收 PD/CC0:
- Commons 无需 API key,内容来源可公开追溯,适合一个开源项目;
- **只收 Public domain 与 CC0** —— 这两类没有署名义务。CC BY 要署名、
  CC BY-SA 还要求衍生作品同样方式共享,对一个商用 App 是长期负担,
  为了几张演示图背这个包袱不划算。
- 每张图都写进 manifest.json(来源页 / 许可 / 作者),
  即使没有署名义务也留痕 —— 用了别人的东西就该说得清出处。

**这些图只用于演示数据**。真实商家没传图时绝不能套用:
给一家店配一张不属于它的诱人照片,是平台替商家做虚假宣传,
和「不杀熟、不虚标」的立场直接冲突。真实商家缺图走品类插画。

用法:
    python scripts/fetch_demo_photos.py                 # 全部品类
    python scripts/fetch_demo_photos.py malatang noodles # 指定品类
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
# 落在 seed_assets 而不是 uploads:uploads 既被 gitignore 也被部署脚本
# rsync 排除,图放那儿等于既不进仓库也上不了生产。seed 时再复制过去
OUT_DIR = ROOT / "server" / "seed_assets" / "demo_photos"
MANIFEST = OUT_DIR / "manifest.json"

API = "https://commons.wikimedia.org/w/api.php"
UA = "superz-demo-assets/0.1 (https://chaojizan.cc; winlere233@gmail.com)"

# 无署名义务的许可白名单。字符串取自 extmetadata.LicenseShortName,
# 大小写与写法都可能变,所以用「包含」匹配而不是相等
FREE_LICENSES = ("public domain", "cc0", "pd-")

# 标题里出现这些词的一律不要:公有领域里有大量古画、铜版画、细密画、
# 手稿和矢量插画,它们许可最干净,所以恰恰最容易被搜出来。
# 实测翻车样本:「铜版画建筑」进了卤味、「波斯细密画」进了品质正餐、
# 「古籍手稿」进了干锅 —— 都是因为搜中文单字命中了书画题名
ART_WORDS = (
    "painting", "engraving", "drawing", "illustration", "miniature",
    "manuscript", "woodcut", "lithograph", "etching", "print",
    "poster", "logo", "icon", "map", "diagram", "sketch", "svg",
    "portrait", "statue", "sculpture", "coin", "stamp", "banknote",
    "书", "画", "图鉴", "手稿", "卷", "碑",
)

# 这些词出现在标题里,多半是活体/原料/店招而不是「一份能点的菜」
NOT_A_DISH = (
    "live ", "aquarium", "wild", "habitat", "species", "specimen",
    "storefront", "shopfront", "signboard", "restaurant exterior",
    "menu", "packaging", "package", "supermarket",
    "招牌", "门店", "门面", "店面", "包装",
    # 第二轮实测又抓到的:空餐具、宴会厅内景、军舰、牙签
    "tableware", "porcelain", "cutlery", "glassware", "place setting",
    "dinner service", "plate setting", "interior", "hall", "lobby",
    "ship", "warship", "boat", "building", "church", "palace", "castle",
    "museum", "toothpick", "empty plate", "餐具", "空盘", "大厅",
)

# 每个品类的搜索词:中英各给几个,中文能命中本土菜,英文命中面更广。
# 词写得具体一点 —— 搜「火锅」会混进一堆餐厅内景,搜「火锅 食物」才是菜
CATEGORY_TERMS: dict[str, list[str]] = {
    "premium_dining": ["steamed fish chinese dish", "东坡肉",
                       "chinese seafood banquet dish", "红烧肉 摆盘",
                       "peking duck served"],
    "drinks_dessert": ["milk tea cup drink", "奶茶 饮品",
                       "fruit tea glass", "boba tea served"],
    "fast_food": ["盖浇饭", "chinese rice plate meal", "bento box lunch",
                  "快餐 便当"],
    "light_salad": ["vegetable salad bowl", "沙拉"],
    "burger_pizza": ["hamburger served plate", "pizza served",
                     "cheeseburger meal"],
    "noodles": ["chinese noodle soup", "牛肉面", "米粉"],
    "bbq_fried": ["chinese barbecue skewers", "烤串", "fried chicken"],
    "braised_duck": ["卤煮", "chinese braised pork dish",
                     "红烧肉", "soy braised meat", "酱肘子"],
    "baozi_congee": ["baozi steamed bun", "包子", "congee porridge"],
    "dumplings": ["dumplings jiaozi", "饺子", "wonton soup"],
    "malatang": ["麻辣烫", "malatang"],
    "sichuan_hunan": ["sichuan cuisine dish", "川菜", "mapo tofu"],
    "regional": ["chinese regional cuisine", "中华料理"],
    "snacks": ["臭豆腐", "煎饼果子", "糖葫芦", "凉皮"],
    "western": ["spaghetti bolognese", "grilled steak plate",
                "risotto dish", "roast chicken plate"],
    "wraps": ["肉夹馍", "chinese flatbread sandwich", "春卷",
              "煎饼 果子"],
    "japan_korea": ["sushi plate served", "bibimbap bowl", "ramen bowl"],
    "dry_pot": ["麻辣香锅", "chinese stir fried dish wok",
                "spicy chicken stir fry", "辣子鸡", "爆炒"],
    "hotpot_skewers": ["火锅", "chinese hot pot food", "串串香"],
    "crayfish_bbq": ["麻辣小龙虾", "crawfish boil plate",
                     "烧烤 拼盘", "grilled skewers platter", "烤肉 拼盘"],
    "beef_lamb_soup": ["羊肉汤", "beef soup chinese", "牛杂汤"],
    "southeast_asia": ["thai curry dish", "pad thai", "vietnamese pho"],
    "pastry": ["月饼", "蛋糕 甜点", "chinese pastry plate", "蛋挞"],
    # 住宿频道用(酒店门头/大堂/客房)。词要写「room interior」这类具体的,
    # 只搜 hotel 会抓到一堆外立面航拍和历史建筑
    "stay_room": ["hotel room interior", "hotel bedroom bed",
                  "guest room interior", "hostel dormitory room",
                  "宾馆 客房", "旅馆 房间"],
    "stay_lobby": ["hotel lobby interior", "hotel reception desk",
                   "guesthouse interior", "hotel entrance facade",
                   "酒店 大堂"],
}

TARGET = (800, 600)   # 4:3,与现有 demo 图一致(旧的是 400x300,这里给 2x)
# 演示店每家 5-7 道菜 + 1 张门头 + 3 张相册。留 4 张的话同一家店的菜单里
# 就会出现重复图片,比纯色块还假。留 8 张够一家店不重样
PER_CATEGORY = int(os.environ.get("PER_CATEGORY", "8"))


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read()


def search(term: str, limit: int = 40) -> list[dict]:
    q = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": f"filetype:bitmap {term}", "gsrnamespace": "6",
        "gsrlimit": str(limit), "prop": "imageinfo",
        "iiprop": "url|extmetadata|size", "iiurlwidth": "1200",
    }
    data = json.loads(_get(API + "?" + urllib.parse.urlencode(q)))
    return list((data.get("query") or {}).get("pages", {}).values())


def is_free(meta: dict) -> bool:
    """只放行没有署名义务的许可。"""
    lic = (meta.get("LicenseShortName", {}).get("value") or "").lower()
    return any(k in lic for k in FREE_LICENSES)


# 住宿品类:要的恰恰是 NOT_A_DISH 里被拉黑的 interior / lobby / building。
# 对这几个品类只过画作,不过"这不是一道菜"
STAY_CATEGORIES = ("stay_room", "stay_lobby")


def looks_like_a_dish(title: str, category: str = "") -> bool:
    """按标题粗筛掉画作/活体/店招。粗但便宜,剩下的靠人眼过。"""
    t = title.lower()
    words = ART_WORDS if category in STAY_CATEGORIES else ART_WORDS + NOT_A_DISH
    return not any(w in t for w in words)


def load_blocklist() -> set[str]:
    """人工筛掉的 Commons 条目(按标题记,文件名会变标题不会)。"""
    f = OUT_DIR / "blocklist.txt"
    if not f.exists():
        return set()
    return {ln.strip() for ln in f.read_text().splitlines()
            if ln.strip() and not ln.startswith("#")}


def usable(page: dict, category: str = "") -> dict | None:
    info = (page.get("imageinfo") or [None])[0]
    if not info:
        return None
    meta = info.get("extmetadata", {})
    if not is_free(meta):
        return None
    if not looks_like_a_dish(page["title"], category):
        return None
    if page["title"] in _BLOCKED:
        return None
    w, h = info.get("width") or 0, info.get("height") or 0
    if w < 640 or h < 480:
        return None                      # 太小的放大就糊
    if not 0.6 <= (w / h) <= 2.2:
        return None                      # 过于狭长的裁不出 4:3
    return {
        "title": page["title"],
        "thumb": info.get("thumburl") or info.get("url"),
        "descriptionurl": info.get("descriptionurl", ""),
        "license": meta.get("LicenseShortName", {}).get("value", ""),
        "artist": _strip_html(meta.get("Artist", {}).get("value", "")),
    }


def _strip_html(s: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", s).strip()[:120]


def crop_to(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """居中裁切到目标比例再缩放 —— 直接 resize 会把菜压扁。"""
    tw, th = size
    tr, sr = tw / th, img.width / img.height
    if sr > tr:                                    # 太宽:裁两边
        nw = int(img.height * tr)
        box = ((img.width - nw) // 2, 0, (img.width - nw) // 2 + nw, img.height)
    else:                                          # 太高:裁上下
        nh = int(img.width / tr)
        box = (0, (img.height - nh) // 2, img.width, (img.height - nh) // 2 + nh)
    return img.crop(box).resize(size, Image.LANCZOS)


_BLOCKED: set[str] = set()


def main(only: list[str]) -> None:
    global _BLOCKED
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _BLOCKED = load_blocklist()
    if _BLOCKED:
        print(f"(已拉黑 {len(_BLOCKED)} 个条目)")
    manifest: dict = {}
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())

    cats = only or list(CATEGORY_TERMS)
    for cat in cats:
        terms = CATEGORY_TERMS.get(cat)
        if not terms:
            print(f"✗ 未知品类 {cat}")
            continue
        picked: list[dict] = []
        seen: set[str] = set()
        for term in terms:
            if len(picked) >= PER_CATEGORY:
                break
            try:
                pages = search(term)
            except Exception as e:
                print(f"  搜索失败 {term}: {e}")
                continue
            for p in pages:
                if len(picked) >= PER_CATEGORY:
                    break
                u = usable(p, cat)
                if u and u["title"] not in seen:
                    seen.add(u["title"])
                    picked.append(u)
            time.sleep(0.4)   # 对开放 API 客气一点

        if not picked:
            print(f"✗ {cat}:没有找到无署名义务的可用图")
            continue

        entries = []
        for i, u in enumerate(picked):
            name = f"{cat}_{i}.jpg"
            try:
                raw = _get(u["thumb"])
                img = Image.open(BytesIO(raw)).convert("RGB")
                crop_to(img, TARGET).save(
                    OUT_DIR / name, "JPEG", quality=82, optimize=True)
            except Exception as e:
                print(f"  下载/处理失败 {u['title']}: {e}")
                continue
            entries.append({
                "file": name, "title": u["title"],
                "source": u["descriptionurl"],
                "license": u["license"], "author": u["artist"],
            })
            time.sleep(0.3)
        manifest[cat] = entries
        print(f"✓ {cat}: {len(entries)} 张")

    # 对账:manifest 必须等于磁盘真实情况。人工删图后不对账的话,
    # 下次重抓会以为这一类还是满的,永远补不上
    for cat in list(manifest):
        manifest[cat] = [e for e in manifest[cat] if (OUT_DIR / e["file"]).exists()]
        if not manifest[cat]:
            del manifest[cat]
    known = {e["file"] for v in manifest.values() for e in v}
    for f in OUT_DIR.glob("*.jpg"):
        if f.name not in known:
            print(f"  (清理无主文件 {f.name})")
            f.unlink()

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    total = sum(len(v) for v in manifest.values())
    print(f"\n合计 {total} 张 → {OUT_DIR}")
    print(f"来源与许可见 {MANIFEST}")


if __name__ == "__main__":
    main(sys.argv[1:])
