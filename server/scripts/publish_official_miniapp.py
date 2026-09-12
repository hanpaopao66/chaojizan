"""上传并发布一个官方小程序(记事本、2048……)。DEV-PROMPTS-39 #337 第 3 步。

M1 时开发者后台还没有,官方应用用这个脚本上传 —— **走的是和开发者后台同一套函数**
(services/miniapp_publish.py):同一个校验器、同一个状态机、同一条审核记录。
审核人写的是 --reviewer 指定的管理员,内部备注标「官方应用,脚本发布」;不开后门。

    # 先看会做什么(不写库、不传对象)
    python -m scripts.publish_official_miniapp miniapps/notepad/dist/notepad.zip \\
        --listing miniapps/notepad/listing.json --reviewer 13800000000
    # 真做
    ... --apply

应用按 listing.json 里的 name 认:没有就建(官方开发者名下、托管),有就发新版本。
发布后打印线上的 SHA-256 —— 和开源仓里 `scripts/build_miniapp.sh` 的产物对得上才算完。
**改生产数据,跑之前要先征得同意。**
"""
import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Developer, MiniApp, User, UserRole


async def run(zip_path: Path, listing_path: Path, reviewer_phone: str, apply: bool) -> int:
    from app.services import miniapp_publish as pub
    from app.services.mini_app_v2 import new_appid
    from app.services.miniapp_package import validate_package
    from app.services.miniapp_platform import CATEGORIES, issue_secret

    data = zip_path.read_bytes()
    listing = json.loads(listing_path.read_text("utf-8"))
    kind = listing.get("kind", "app")
    report = validate_package(data, kind=kind)
    print(f"包:{zip_path}  {len(data)} 字节  SHA-256 {hashlib.sha256(data).hexdigest()}")
    for w in report.warnings:
        print(f"  警告:{w}")
    if not report.ok:
        for e in report.errors:
            print(f"  错误:{e}")
        return 2
    if listing.get("category") not in CATEGORIES:
        print(f"  错误:category 必须是 {'/'.join(CATEGORIES)}")
        return 2
    problems = pub.listing_problems(listing, kind)
    if problems:
        print("  错误:展示信息不完整:" + "、".join(problems))
        return 2

    async with SessionLocal() as db:
        reviewer = await db.scalar(select(User).where(User.phone == reviewer_phone,
                                                      User.role == UserRole.admin))
        if reviewer is None:
            print(f"  错误:{reviewer_phone} 不是管理员")
            return 2
        dev = await db.scalar(select(Developer).where(Developer.is_official.is_(True))
                              .order_by(Developer.id).limit(1))
        if dev is None:
            print("  错误:没有官方开发者(先跑 scripts.seed_official_miniapps --apply)")
            return 2
        app = await db.scalar(select(MiniApp).where(MiniApp.name == listing["name"],
                                                    MiniApp.developer_id == dev.id))
        print(f"应用:{listing['name']}(" + (f"已有 {app.appid},发新版本" if app else "新建") + ")")
        if not apply:
            print("只看计划,加 --apply 才写库和传对象")
            return 0
        if app is None:
            app = MiniApp(appid=new_appid(), developer_id=dev.id, name=listing["name"],
                          icon=listing.get("icon", listing["name"][0]), kind=kind,
                          category=listing["category"], hosting="hosted", status="draft",
                          entry_url="", allowed_origins=[], perms=[], sort=0, is_official=True)
            issue_secret(app)  # 官方应用不接自己的后端,密钥没人用;照样生成,规则一致
            db.add(app)
            await db.commit()
            await db.refresh(app)
        if app.first_released_at is None:
            pub.apply_listing(app, {k: v for k, v in listing.items() if k in pub.LISTING_FIELDS})
        else:
            app.listing_draft = {**pub.effective_listing(app),
                                 **{k: v for k, v in listing.items() if k in pub.LISTING_FIELDS}}
        await db.commit()
        v, rep = await pub.create_version(db, app, data, version=listing.get("version", ""),
                                          changelog=listing.get("changelog", ""), actor=reviewer,
                                          check_rate=False)
        if v is None:
            print("  错误:" + ";".join(rep.errors))
            return 2
        app = await db.get(MiniApp, app.id)
        await pub.submit(db, app, v, dev, review_note="官方应用", required_revision=0)
        await pub.decide(db, app, v, reviewer, approve=True, reason_code="",
                         note_public="官方应用", note_internal="官方应用,脚本发布",
                         checklist={c["key"]: True for c in pub.CHECKLIST})
        app = await db.get(MiniApp, app.id)
        v = await db.get(type(v), v.id)
        if v.status == "approved":
            await pub.release(db, app, v, reviewer)
        await db.refresh(app)
        print(f"已发布:{app.appid} 版本 {v.version}(build {v.build},id {v.id})")
        print(f"线上 SHA-256:{v.sha256}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="上传并发布一个官方小程序")
    p.add_argument("zip", type=Path)
    p.add_argument("--listing", type=Path, required=True, help="listing.json:名称、图标、描述、隐私政策…")
    p.add_argument("--reviewer", required=True, help="审核人:一个管理员账号的手机号")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()
    sys.exit(asyncio.run(run(a.zip, a.listing, a.reviewer, a.apply)))


if __name__ == "__main__":
    main()
