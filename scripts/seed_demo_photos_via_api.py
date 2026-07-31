"""给演示商家配真实照片:以商家身份走公开 API 上传(#135)。

## 为什么走 API 而不是直接改库

- 图片经 `POST /upload` 才会落进对象存储的正确桶、拿到正确的 key 与 URL 形态。
  直接写库只改了指针,文件还在老地方,换存储后端就全断了;
- 走的是商家自己上传的同一条代码路径,顺带证明那条路径在生产真的通 ——
  一个只在 CI 里绿过的上传接口,不算验证过。

## 只动演示店(两道闸)

真实商家没传图时**绝不能**套用这些照片:给一家店配一张不属于它的诱人照片,
是平台替商家做虚假宣传,与「不杀熟、不虚标」的立场直接冲突
(`server/scripts/demo_seed.py` 里写着同一句)。所以:

1. 手机号必须在 demo_seed 的 SHOPS / HOTELS 名单里;
2. 现有图的存储 key 必须仍以 `demo/` 开头(即 seed 灌的占位图)——
   商家自己传过图的一律跳过,绝不覆盖。

两道闸是**与**关系。任何一道不过就跳过并计入 skipped,不是静默略过。

## 跑法

在部署机上、api 容器里跑(容器里才有 DB 连接与 JWT_SECRET):

    docker exec superz-api python -m scripts.seed_demo_photos_via_api --dry-run
    docker exec superz-api python -m scripts.seed_demo_photos_via_api

`--dry-run` 只打印计划、不发任何写请求,先看一遍再动手。
脚本可重复跑:已经换成非 demo 图的对象会被第二道闸挡掉。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.models import Dish, Merchant, RoomType, User  # noqa: E402
from app.security import create_token  # noqa: E402

API = os.environ.get("SEED_API", "http://127.0.0.1:8000")
ASSETS = Path(__file__).resolve().parent.parent / "seed_assets" / "demo_photos"

# 演示占位图的判据:**存储 key 以 `demo/` 开头**。
#
# 这个判据是精确的,不是启发式:demo_seed 的 `_put_public("demo/...")` 才会
# 产生 demo/ 前缀,而商家自己上传走 `_new_key()` = `{purpose}/{uuid}` ——
# 永远落在 dish/ shop/ gallery/ room/ 下,不可能撞进 demo/。
#
# 两种 URL 形态都要认:本地后端出 `/uploads/<key>`,MinIO 后端出 `/img/<key>`。
# 只认其中一种的话,换个后端这道闸就形同虚设(实测本地是 /img/demo/...,
# 生产是 /uploads/demo/... —— 两边不一样)。
DEMO_URL_PREFIXES = ("/uploads/demo/", "/img/demo/")


def is_demo_placeholder(url: str) -> bool:
    """这张图还是 seed 灌的占位图吗?空字符串算是(没图,可以配)。"""
    if not url:
        return True
    return str(url).startswith(DEMO_URL_PREFIXES)


# 餐饮店相册张数;房型图张数
GALLERY_N = 3
ROOM_N = 2


def load_pools() -> dict[str, list[Path]]:
    """按品类读图库。manifest 是唯一事实来源(记着来源与许可)。"""
    mf = ASSETS / "manifest.json"
    if not mf.exists():
        raise SystemExit(f"没有 {mf};先在开发机跑 scripts/fetch_demo_photos.py")
    pools: dict[str, list[Path]] = {}
    for cat, items in json.loads(mf.read_text()).items():
        files = [ASSETS / e["file"] for e in items
                 if (ASSETS / e["file"]).exists()]
        if files:
            pools[cat] = files
    return pools


def demo_phones() -> set[str]:
    """从 demo_seed 直接取名单,不另抄一份 —— 抄的那份迟早对不上。"""
    from scripts.demo_seed import HOTELS, SHOPS
    return {s["phone"] for s in SHOPS} | {h["phone"] for h in HOTELS}


class Picker:
    """按品类轮换取图,并尽量避免同一家店里出现重复。

    同品类只有 N 张而一家店有 N+ 个位置时,重复不可避免 ——
    那时**明确报出来**,而不是悄悄发两张一样的图上去。
    """

    def __init__(self, pools: dict[str, list[Path]]):
        self.pools = pools
        self.exhausted: list[str] = []

    def take(self, category: str, n: int, seed: int) -> list[Path]:
        # **住宿类不许回退到餐饮图**:给客房配一张川菜照片比留着色块更糟。
        # 拿不到就返回空,让调用方跳过这一项并报出来
        fallback = [] if category.startswith("stay_") else \
            self.pools.get("regional", [])
        pool = self.pools.get(category) or fallback
        if not pool:
            return []
        if n > len(pool):
            self.exhausted.append(f"{category}:要 {n} 张只有 {len(pool)} 张")
        start = seed % len(pool)
        return [pool[(start + i) % len(pool)] for i in range(n)]


async def upload(client: httpx.AsyncClient, token: str, path: Path,
                 purpose: str) -> str:
    r = await client.post(
        f"{API}/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (path.name, path.read_bytes(), "image/jpeg")},
        data={"purpose": purpose},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["url"]


async def patch(client: httpx.AsyncClient, token: str, url: str,
                body: dict) -> None:
    r = await client.patch(f"{API}{url}",
                           headers={"Authorization": f"Bearer {token}"},
                           json=body, timeout=60)
    r.raise_for_status()


async def main(dry: bool, force: bool = False,
               only: set[int] | None = None) -> None:
    pools = load_pools()
    picker = Picker(pools)
    allow = demo_phones()
    stat = {"logo": 0, "gallery": 0, "dish": 0, "room": 0}
    skipped: list[str] = []

    def placeholder(url) -> bool:
        # --force:图库换了图、要重配已经配过的对象时用。
        # 只在「确认所有商家都是演示店」的前提下用,否则会覆盖真实商家的图
        return True if force else is_demo_placeholder(url)

    async with SessionLocal() as db, httpx.AsyncClient() as client:
        merchants = (await db.execute(
            select(Merchant).order_by(Merchant.id))).scalars().all()

        for m in merchants:
            owner = await db.get(User, m.owner_id)
            phone = owner.phone if owner else ""
            if only and m.id not in only:
                continue
            if phone not in allow:
                skipped.append(f"商家 {m.id} {m.name}:不在演示名单(真实商家)")
                continue

            token = create_token(owner)
            cat = m.category or ("stay_room" if m.biz_type == "hotel"
                                 else "regional")
            if m.biz_type == "hotel":
                cat = "stay_lobby"

            # ---- 门头照 ----
            if placeholder(m.logo_url):
                pick = picker.take(cat, 1, m.id)
                if pick:
                    print(f"  [{m.id}] {m.name} 门头 <- {pick[0].name}")
                    if not dry:
                        u = await upload(client, token, pick[0], "shop")
                        await patch(client, token, "/merchants/me",
                                    {"logo_url": u})
                    stat["logo"] += 1
            elif m.logo_url:
                skipped.append(f"商家 {m.id} {m.name}:门头已是自传图,不覆盖")

            # ---- 门店相册 ----
            cur = list(m.photo_urls or [])
            if all(placeholder(u) for u in cur):
                gcat = "stay_room" if m.biz_type == "hotel" else cat
                pick = picker.take(gcat, GALLERY_N, m.id + 1)
                if pick:
                    print(f"  [{m.id}] {m.name} 相册 <- "
                          f"{', '.join(p.name for p in pick)}")
                    if not dry:
                        urls = [await upload(client, token, p, "gallery")
                                for p in pick]
                        await patch(client, token, "/merchants/me",
                                    {"photo_urls": urls})
                    stat["gallery"] += len(pick)
            else:
                skipped.append(f"商家 {m.id} {m.name}:相册有自传图,不覆盖")

            # ---- 菜品图 ----
            dishes = (await db.execute(
                select(Dish).where(Dish.merchant_id == m.id)
                .order_by(Dish.id))).scalars().all()
            picks = picker.take(cat, len(dishes), m.id + 2) if dishes else []
            for i, d in enumerate(dishes):
                if not placeholder(d.image_url):
                    skipped.append(f"菜品 {d.id} {d.name}:已是自传图,不覆盖")
                    continue
                p = picks[i]
                print(f"  [{m.id}] 菜品「{d.name}」<- {p.name}")
                if not dry:
                    u = await upload(client, token, p, "dish")
                    await patch(client, token,
                                f"/merchants/me/dishes/{d.id}",
                                {"image_url": u})
                stat["dish"] += 1

            # ---- 房型图 ----
            rooms = (await db.execute(
                select(RoomType).where(RoomType.merchant_id == m.id)
                .order_by(RoomType.id))).scalars().all()
            for j, rt in enumerate(rooms):
                cur_r = list(rt.image_urls or [])
                if not all(placeholder(u) for u in cur_r):
                    skipped.append(f"房型 {rt.id} {rt.name}:有自传图,不覆盖")
                    continue
                pick = picker.take("stay_room", ROOM_N, rt.id + j)
                if not pick:
                    continue
                print(f"  [{m.id}] 房型「{rt.name}」<- "
                      f"{', '.join(p.name for p in pick)}")
                if not dry:
                    urls = [await upload(client, token, p, "room")
                            for p in pick]
                    await patch(client, token,
                                f"/stays/me/room-types/{rt.id}",
                                {"image_urls": urls})
                stat["room"] += len(pick)

    print()
    print("== 计划 ==" if dry else "== 完成 ==")
    print(f"门头 {stat['logo']} / 相册 {stat['gallery']} / "
          f"菜品 {stat['dish']} / 房型 {stat['room']} "
          f"= 共 {sum(stat.values())} 张")
    if picker.exhausted:
        print("\n图库不够用(会出现重复图,建议先补图库):")
        for e in sorted(set(picker.exhausted)):
            print("  ·", e)
    if skipped:
        print(f"\n跳过 {len(skipped)} 项:")
        for s in skipped[:20]:
            print("  ·", s)
        if len(skipped) > 20:
            print(f"  ...另有 {len(skipped) - 20} 项")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印计划,不发任何写请求")
    ap.add_argument("--force", action="store_true",
                    help="连已经配过的也重配(图库换图后用;"
                         "前提是确认所有商家都是演示店)")
    ap.add_argument("--only", default="",
                    help="只处理这些商家 id,逗号分隔")
    args = ap.parse_args()
    ids = {int(x) for x in args.only.split(",") if x.strip()} or None
    asyncio.run(main(args.dry_run, args.force, ids))
