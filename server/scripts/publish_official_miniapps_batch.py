"""批量发布官方小游戏(在 api 容器里跑;由 scripts/publish_miniapps.sh 调用)。

    python -m scripts.publish_official_miniapps_batch --dir /tmp/sz-publish            # 只看计划
    python -m scripts.publish_official_miniapps_batch --dir /tmp/sz-publish --apply    # 真写

目录约定:`<app>.zip` + `<app>-listing.json` 一一对应。审核人 = 数据库里第一个管理员
(服务端发布脚本要求一个管理员账号作审核人;这里不把手机号打到终端/日志里)。
走的是和开发者后台完全相同的函数:同一个包校验器、同一个状态机、同一条审核记录,
不放后门。**改生产数据,跑之前要征得运营方同意。**
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User, UserRole
from scripts.publish_official_miniapp import run


async def main() -> int:
    parser = argparse.ArgumentParser(description="批量发布官方小程序")
    parser.add_argument("--dir", type=Path, default=Path("/tmp/sz-publish"),
                        help="包含 <app>.zip 与 <app>-listing.json 的目录")
    parser.add_argument("--app", action="append", default=None, help="只发这些应用(默认全部)")
    parser.add_argument("--apply", action="store_true", help="真写库和上传对象;不带只看计划")
    args = parser.parse_args()

    if not args.dir.is_dir():
        print(f"✗ 目录不存在:{args.dir}")
        return 2
    zips = sorted(args.dir.glob("*.zip"))
    if args.app:
        wanted = set(args.app)
        zips = [z for z in zips if z.stem in wanted]
        missing = wanted - {z.stem for z in zips}
        if missing:
            print(f"✗ 目录里没有这些包:{'、'.join(sorted(missing))}")
            return 2
    if not zips:
        print(f"✗ {args.dir} 里没有 .zip")
        return 2

    async with SessionLocal() as db:
        admin = await db.scalar(select(User).where(User.role == UserRole.admin).order_by(User.id))
    if admin is None:
        print("✗ 数据库里没有管理员账号(发布需要审核人)")
        return 2

    print(f"== 共 {len(zips)} 个包,{'真发布' if args.apply else '只看计划'} ==")
    rc = 0
    for zip_path in zips:
        listing = args.dir / f"{zip_path.stem}-listing.json"
        if not listing.is_file():
            print(f"✗ {zip_path.name} 缺对应的 {listing.name}")
            rc = 2
            continue
        print(f"\n===== {zip_path.stem} =====")
        r = await run(zip_path, listing, admin.phone, apply=args.apply)
        rc = rc or r
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
