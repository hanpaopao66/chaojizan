"""机器人管家 @guanjia_bot(services/bot_manager.py):建出来、把设置对齐。幂等,重复跑只对齐不重建。

**改生产数据,跑之前要先征得同意。** 默认只打印要做什么,加 --apply 才写:

    docker compose exec api python -m scripts.seed_bot_manager            # 看计划
    docker compose exec api python -m scripts.seed_bot_manager --apply    # 真写

挂在官方开发者名下(和官方小程序同一个,Developer.is_official)。机器人的主人是一个用户账号(bots.owner_id),
而官方开发者当初是脚本建的、没有账号 —— 没有的话这里补一个**系统账号**:role=developer,
手机号写 `sys-official-dev`(不是号码,发不了验证码)、密码谁都不知道,和机器人账号一样登不了。

token 建出来就扔掉:管家不走 Bot API(投递循环在进程里直接调它),没有人需要它的 token;
真要用就在开发者后台重置。webhook 地址 `internal:guanjia` 只有这里写得进去(Bot API 和后台都只收 https)。
"""
import argparse
import asyncio
import secrets

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Bot, Developer, User, UserRole, Username
from app.services import bot_manager as mgr
from app.services import bots

SYSTEM_PHONE = "sys-official-dev"


async def run(apply: bool) -> int:
    from app.security import hash_password

    async with SessionLocal() as db:
        dev = await db.scalar(select(Developer).where(Developer.is_official.is_(True))
                              .order_by(Developer.id).limit(1))
        if dev is None:
            print("✗ 没有官方开发者:先跑 python -m scripts.seed_official_miniapps --apply")
            return 1
        owner = await db.get(User, dev.user_id) if dev.user_id else None
        if owner is None:
            print(f"  + 官方开发者(id={dev.id})没有账号:补一个系统账号({SYSTEM_PHONE},登不了)")
            if apply:
                owner = await db.scalar(select(User).where(User.phone == SYSTEM_PHONE,
                                                           User.role == UserRole.developer))
                if owner is None:
                    owner = User(phone=SYSTEM_PHONE, role=UserRole.developer, name=dev.display_name or "超级赞官方",
                                 password_hash=await asyncio.to_thread(hash_password, secrets.token_urlsafe(32)))
                    db.add(owner)
                    await db.flush()
                dev.user_id = owner.id
        else:
            print(f"  官方开发者账号已有(user {owner.id})")

        name_row = await db.get(Username, mgr.USERNAME)
        bot = await db.get(Bot, name_row.owner_id) if name_row is not None else None
        if name_row is not None and bot is None:
            print(f"✗ @{mgr.USERNAME} 被一个不是机器人的账号占着(user {name_row.owner_id}),先查清楚")
            return 1
        if bot is not None and owner is not None and bot.owner_id != owner.id:
            print(f"✗ @{mgr.USERNAME} 在别人名下(user {bot.owner_id}),先查清楚")
            return 1
        if bot is None:
            print(f"  + 新建 {mgr.NAME} @{mgr.USERNAME}")
        else:
            print(f"  {mgr.NAME} @{mgr.USERNAME} 已有(机器人 {bot.user_id}),对齐设置")
        want = {"webhook_url": mgr.WEBHOOK, "commands": mgr.COMMANDS, "about": mgr.ABOUT,
                "description": mgr.DESCRIPTION, "menu_type": "commands", "privacy_mode": True}
        if bot is not None:
            for k, v in want.items():
                if getattr(bot, k) != v:
                    print(f"    · {k} 改成 {v if k != 'commands' else f'{len(v)} 条命令'}")
        if not apply:
            print("只看计划,加 --apply 才写库")
            await db.rollback()
            return 0

        if bot is None:
            bot, _token = await bots.create_bot(db, owner, mgr.NAME, mgr.USERNAME, system=True)
        for k, v in want.items():
            setattr(bot, k, v)
        await db.commit()
        print(f"✓ {mgr.NAME} @{mgr.USERNAME}(机器人 {bot.user_id})就绪:消息由投递循环在进程里处理")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="真写库(默认只看计划)")
    raise SystemExit(asyncio.run(run(ap.parse_args().apply)))


if __name__ == "__main__":
    main()
