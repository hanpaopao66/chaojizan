"""邀请有礼停了之后,商家那一侧(2026-09-14):

#115 起邀请有礼的券由商家出(「新客推荐券」批次);2026-09-14 活动整个停了。

1. 商家不能再建「新客推荐券」批次:410,说清楚停了;
2. 平台侧从来不能建营销类批次,现在连平台批次都不能建(410);
3. 商家自己出钱的其他批次(店铺券)照旧能建 —— 停的只是邀请有礼,不是商家的营销;
4. 商家批次列表里,停之前建的新客推荐券批次照旧看得到(历史不动)。

用户那一侧(我的邀请、填码、pending 的邀请不发)在 e2e_referral。

在 server/ 目录下运行:python -m tests.e2e_referral_funding
"""
import asyncio
import time

from app.db import SessionLocal
from app.models import CouponBatch
from tests.util import call, login

admin = login("13800000000")
merchant = login("13800000002")
ts = int(time.time())


async def main() -> None:
    shop = call("GET", "/merchants/me", merchant)

    # 1) 商家不能再建新客推荐券批次
    err = call("POST", "/merchants/me/coupon-batches", merchant, {
        "name": f"新客推荐券{ts}", "trigger": "referral",
        "threshold_cents": 0, "off_cents": 300,
        "total": 2, "per_user_limit": 1, "valid_days": 7}, expect_error=True)
    assert err["_error"] == 410 and "停了" in err["detail"], err
    print("✓ 商家建新客推荐券批次:410,说清楚邀请有礼停了")

    # 2) 平台侧:营销类批次、平台批次一律建不了
    for trigger in ("referral", "birthday", "winback", "newcomer", "manual"):
        err = call("POST", "/admin/coupon-batches", admin, {
            "name": f"平台{trigger}", "trigger": trigger,
            "amount_cents": 300, "total": 10}, expect_error=True)
        assert err["_error"] == 410, (trigger, err)
    print("✓ 平台侧一个批次都建不了(营销的钱该商家出,平台不出钱发券)")

    # 3) 商家自己出钱的店铺券照旧能建
    b = call("POST", "/merchants/me/coupon-batches", merchant, {
        "name": f"店铺券{ts}", "trigger": "shop",
        "threshold_cents": 3000, "off_cents": 300,
        "total": 5, "per_user_limit": 1, "valid_days": 7})
    assert b["trigger"] == "shop" and b["active"] is True, b
    call("POST", f"/merchants/me/coupon-batches/{b['id']}/toggle", merchant)
    print("✓ 商家自己出钱的店铺券照旧能建(停的只是邀请有礼)")

    # 4) 停之前建的新客推荐券批次:列表里照旧看得到
    async with SessionLocal() as db:
        old = CouponBatch(name=f"停前的新客推荐券{ts}", trigger="referral",
                          merchant_id=shop["id"], amount_cents=300, min_spend_cents=0,
                          valid_days=7, total=10, active=False)
        db.add(old)
        await db.commit()
        old_id = old.id
    rows = call("GET", "/merchants/me/coupon-batches", merchant)
    assert any(r["id"] == old_id and r["trigger"] == "referral" for r in rows), rows[:3]
    print("✓ 停之前建的新客推荐券批次照旧列着(历史不动)")
    print("\ne2e_referral_funding 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
