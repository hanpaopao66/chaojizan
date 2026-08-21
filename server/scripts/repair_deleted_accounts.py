"""存量墓碑行修复:把注销当初漏清的字段补清干净。

在 server/ 目录下运行(先跑 alembic upgrade head 建出 users.deleted_at):

    python -m scripts.repair_deleted_accounts          # 只报告,不改
    python -m scripts.repair_deleted_accounts --apply  # 真改

## 为什么需要它

0108 之前的注销只改 4 列(phone/name/avatar_url/password_hash),
剩下的留在原地继续参与业务:

  - `rider_profiles` 的 real_name / id_no_encrypted / 紧急联系人一个字没删,
    而注销页的原话是"实名信息一并删除" —— 这条最要紧,是对用户的承诺;
  - `addresses` 里的联系人姓名 + 电话 + 门牌 + 经纬度整本留着;
  - `ref_code` 还在,邀请码仍能被解析,继续给已注销账号发券;
  - `is_online` 还是 true,8 处在线骑手查询把它算进去(含派单广播);
  - `merchant_staff` 行还在,人永远挂在店员名单上;
  - 生日/收工方向这些个人字段也都留着。

新代码只管新注销的账号。存量行得靠这个脚本。

## 幂等

按 `deleted_at IS NOT NULL OR phone LIKE 'del%'` 选行,清的都是
"置空/置 false/删行"这类幂等操作。跑第二遍会报告 0 处待修。

## 风控标记

存量墓碑行的手机号**已经被抹掉了**,没有办法反推出假名 ——
`risk_carryovers` 只能对 0108 之后的注销生效。存量行里带着
after_sale_banned / risk_level 的,脚本会单独列出来提醒人工处理:
这些人可能已经用"注销再注册"洗过一次白了。
"""
import argparse
import asyncio

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select, update

from app.db import SessionLocal
from app.models import (
    Address,
    AppEvent,
    MerchantStaff,
    RiderProfile,
    User,
    UserIdentity,
)

#: 墓碑判据:新列优先,手机号前缀兜住迁移没盖到的行
_TOMBSTONE = or_(User.deleted_at.is_not(None), User.phone.like("del%"))


async def main(apply: bool) -> None:
    async with SessionLocal() as db:
        ids = list((await db.scalars(select(User.id).where(_TOMBSTONE))).all())
        print(f"墓碑行:{len(ids)} 个")
        if not ids:
            print("没有需要修的行。")
            return

        # ① deleted_at 回填。迁移里已经按手机号前缀刷过一遍,
        #    这里兜住"迁移之后、新代码上线之前"注销的那些行。
        missing_ts = await db.scalar(select(func.count(User.id)).where(
            _TOMBSTONE, User.deleted_at.is_(None)))
        print(f"  deleted_at 为空:{missing_ts}")

        # ② 墓碑行上还留着的业务字段
        leaks = {
            "ref_code 未清": await db.scalar(select(func.count(User.id)).where(
                _TOMBSTONE, User.ref_code.is_not(None))),
            "is_online 仍为 true": await db.scalar(
                select(func.count(User.id)).where(
                    _TOMBSTONE, User.is_online.is_(True))),
            "birthday 未清": await db.scalar(select(func.count(User.id)).where(
                _TOMBSTONE, User.birthday != "")),
            "收工方向未清": await db.scalar(select(func.count(User.id)).where(
                _TOMBSTONE, User.go_home_lat.is_not(None))),
        }
        # ③ 本该随注销一起删掉的行
        rows = {
            "rider_profiles(实名!)": await db.scalar(
                select(func.count(RiderProfile.id))
                .where(RiderProfile.rider_id.in_(ids))),
            "addresses": await db.scalar(select(func.count(Address.id))
                                         .where(Address.user_id.in_(ids))),
            "merchant_staff": await db.scalar(
                select(func.count(MerchantStaff.id))
                .where(MerchantStaff.user_id.in_(ids))),
            "app_events": await db.scalar(select(func.count(AppEvent.id))
                                          .where(AppEvent.user_id.in_(ids))),
            "user_identities": await db.scalar(
                select(func.count(UserIdentity.id))
                .where(UserIdentity.user_id.in_(ids))),
        }
        for label, n in {**leaks, **rows}.items():
            print(f"  {label}:{n}")

        # ④ 洗白提醒:存量行的手机号已抹,没法建假名,只能人工看
        washed = (await db.execute(
            select(User.id, User.after_sale_banned, User.risk_level)
            .where(_TOMBSTONE,
                   or_(User.after_sale_banned.is_(True),
                       User.risk_level != "")))).all()
        if washed:
            print(f"\n⚠️ {len(washed)} 个墓碑行**还带着**风控标记。")
            print("   新代码注销时会把标记寄存进 risk_carryovers 再从行上抹掉,"
                  "所以带着标记 = 这是 0108 之前注销的存量行。")
            print("   它们的手机号已经抹掉了,反推不出假名,回填不了 ——")
            print("   如果本人用同一手机号重新注册过,标记已经清零,请人工核对:")
            for uid, banned, level in washed:
                print(f"   user_id={uid} after_sale_banned={banned} "
                      f"risk_level={level or '-'}")
        else:
            print("\n没有带着风控标记的墓碑行(注销 ≠ 洗白 这条成立)")

        if not apply:
            print("\n(试运行。加 --apply 真正执行)")
            return

        await db.execute(update(User).where(
            _TOMBSTONE, User.deleted_at.is_(None)).values(deleted_at=func.now()))
        await db.execute(update(User).where(_TOMBSTONE).values(
            ref_code=None, is_online=False, birthday="", marketing_push=False,
            go_home_lat=None, go_home_lng=None, go_home_on=False,
            avatar_url=""))
        # device_id **不清**:它是设备风控指纹,不是账号资料。
        # 清掉等于让"注销→再注册"绕过同设备多账号判定
        # (见 services/coupons.py 的 _device_has_other_account)。
        for model, col in ((RiderProfile, RiderProfile.rider_id),
                           (Address, Address.user_id),
                           (MerchantStaff, MerchantStaff.user_id),
                           (AppEvent, AppEvent.user_id),
                           (UserIdentity, UserIdentity.user_id)):
            await db.execute(sa_delete(model).where(col.in_(ids)))
        await db.commit()
        print("\n已修复。再跑一次(不带 --apply)应当全部为 0。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正执行(默认只报告)")
    asyncio.run(main(ap.parse_args().apply))
