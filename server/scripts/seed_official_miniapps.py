"""官方开发者 + 两条自家外部地址条目(透明中心、公开账本)。幂等(DEV-PROMPTS-39 #337 第 1 步)。

生产上 mini_apps 表是空的 —— 下拉抽屉的规则是「清单为空时手势不生效」,所以老版本 App
下拉只会刷新。这个脚本补上两条自家条目,老 App 立刻就能下拉出小程序。

**改生产数据,跑之前要先征得同意。** 默认只打印要做什么,加 --apply 才写:

    docker compose exec api python -m scripts.seed_official_miniapps            # 看计划
    docker compose exec api python -m scripts.seed_official_miniapps --apply    # 真写

已经存在的条目(按名称认)一个字段都不改 —— 运营在后台改过的图标、文案都保留。
"""
import argparse
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Developer, MiniApp

OFFICIAL_COMPANY = "陕西爱卡斯科技有限公司"
ENTRIES = [
    # name, icon, tagline, path, sort
    ("透明中心", "透", "每天核账,差一分都亮红灯", "/transparency", 0),
    ("公开账本", "账", "哈希链锚点,人人可复算", "/nodes", 1),
]


async def ensure_official_developer(db, *, apply: bool) -> Developer | None:
    dev = await db.scalar(select(Developer).where(Developer.is_official.is_(True))
                          .order_by(Developer.id).limit(1))
    if dev is not None:
        print(f"  官方开发者已存在(id={dev.id})")
        return dev
    print(f"  + 新建官方开发者:{OFFICIAL_COMPANY}")
    if not apply:
        return None
    dev = Developer(kind="company", display_name="超级赞官方", status="verified",
                    company_name=OFFICIAL_COMPANY, is_official=True,
                    verified_at=datetime.now(timezone.utc))
    db.add(dev)
    await db.flush()
    return dev


async def ensure_entries(db, dev: Developer | None, *, apply: bool) -> int:
    from app.services.mini_app_v2 import new_appid
    from app.services.miniapp_platform import issue_secret

    base = settings.public_base_url.rstrip("/")
    added = 0
    for name, icon, tagline, path, sort in ENTRIES:
        row = await db.scalar(select(MiniApp).where(MiniApp.name == name))
        if row is not None:
            print(f"  = {name} 已存在(appid={row.appid},状态 {row.status}),不改")
            continue
        print(f"  + {name} → {base}{path}")
        added += 1
        if not apply:
            continue
        app = MiniApp(name=name, icon=icon, tagline=tagline, entry_url=f"{base}{path}",
                      allowed_origins=[base], perms=["initData"], sort=sort,
                      appid=new_appid(), developer_id=dev.id if dev else None,
                      hosting="external", is_official=True, status="online",
                      first_released_at=datetime.now(timezone.utc))
        issue_secret(app)
        db.add(app)
    return added


async def run(apply: bool) -> None:
    async with SessionLocal() as db:
        print("官方小程序条目" + ("(写入)" if apply else "(只看计划,加 --apply 才写)"))
        dev = await ensure_official_developer(db, apply=apply)
        added = await ensure_entries(db, dev, apply=apply)
        if apply:
            await db.commit()
        print(f"完成:新增 {added} 条" + ("" if apply else "(未写入)"))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true", help="真的写库(默认只打印计划)")
    asyncio.run(run(p.parse_args().apply))


if __name__ == "__main__":
    main()
