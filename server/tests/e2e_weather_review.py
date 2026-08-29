"""恶劣天气加价:**自动判定只提请,人点头才生效**(#307)。

## 这条守什么

加价这笔钱是用户实付的。如果自动判定能直接加价,一次误报
(气象格点漂移、一阵过云雨)就让用户凭空多花钱 —— 而他看不到
那一刻的气象数据,也不知道该找谁申诉。

所以这里锁三件事:

1. **没有生效单时不加价**(哪怕天气真的恶劣);
2. 批准后**限时生效**,到期自动失效 —— 不能"批一次收一辈子";
3. 驳回后进冷静期,不反复提请刷屏。

在 server/ 目录下运行:python -m tests.e2e_weather_review
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from tests.util import ADMIN, call, login  # noqa: E402

admin = login(ADMIN)
CITY, DISTRICT = "测试市", "测试区"


async def clear():
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM weather_alerts WHERE city = :c"),
                         {"c": CITY})
        await db.commit()


async def seed(status="pending", expires_in_h=None):
    """直接造一张审核单 —— 真实天气不可控,不能靠"等下雨"来测。"""
    exp = (datetime.now(timezone.utc) + timedelta(hours=expires_in_h)
           if expires_in_h is not None else None)
    async with SessionLocal() as db:
        row = await db.execute(text(
            "INSERT INTO weather_alerts "
            "(city, district, status, weather_code, precip_mm, wind_kmh,"
            " lat, lng, expires_at) "
            "VALUES (:c, :d, :s, 65, 3.2, 12.0, 30.66, 104.08, :e) "
            "RETURNING id"),
            {"c": CITY, "d": DISTRICT, "s": status, "e": exp})
        rid = row.scalar()
        await db.commit()
    return rid


async def zone_on() -> bool:
    """当前该区县加价是否生效 —— 直接问被算价调用的那个函数。"""
    from app.services.weather_zone import active_alert
    async with SessionLocal() as db:
        return await active_alert(db, CITY, DISTRICT) is not None


async def main() -> None:
    await clear()

    # ---------- 1) 待审 ≠ 生效 ----------
    aid = await seed("pending")
    assert not await zone_on(), \
        "只是提请就加价了 —— 那整个审核设计就是摆设"
    print("✓ 待审状态不加价(自动判定只提请)")

    rows = call("GET", "/admin/weather-alerts?status=pending", admin)
    mine = next(r for r in rows["items"] if r["id"] == aid)
    # 审的是判据本身:管理员要看得到气象快照,而不是一句「系统说恶劣」
    assert mine["weather_code"] == 65 and mine["precip_mm"] > 0, mine
    assert rows["spec"]["approved_hours"] > 0
    print("✓ 审核队列可读,带气象快照与规则说明")

    # ---------- 2) 批准 → 生效且限时 ----------
    r = call("POST", f"/admin/weather-alerts/{aid}/decide", admin,
             {"approve": True, "note": "核对过,确实在下"})
    assert r["status"] == "approved" and r["expires_at"], r
    assert await zone_on(), "批准了却没生效"
    print("✓ 批准后生效,且带到期时间")

    # 重复处理要被拒:两个管理员同时点,第二下不该把有效期又续一遍
    err = call("POST", f"/admin/weather-alerts/{aid}/decide", admin,
               {"approve": False}, expect_error=True)
    assert err["_error"] == 409, err
    print("✓ 已处理的单不能重复处理")

    # ---------- 3) 到期自动失效 ----------
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE weather_alerts SET expires_at = now() - interval "
            "'1 minute' WHERE id = :i"), {"i": aid})
        await db.commit()
    assert not await zone_on(), \
        "到期了还在加价 —— 天气会停,批一次不能收一辈子"
    print("✓ 到期即失效(读的时候就判,不依赖清扫任务)")

    from app.services.weather_zone import expire_due
    async with SessionLocal() as db:
        n = await expire_due(db)
        await db.commit()
    assert n >= 0
    async with SessionLocal() as db:
        st = (await db.execute(text(
            "SELECT status FROM weather_alerts WHERE id = :i"),
            {"i": aid})).scalar()
    assert st == "expired", f"清扫没把它置成 expired:{st}"
    print("✓ 清扫任务把到期单落成 expired")

    # ---------- 4) 驳回后进冷静期,不反复提请 ----------
    await clear()
    bid = await seed("pending")
    call("POST", f"/admin/weather-alerts/{bid}/decide", admin,
         {"approve": False, "note": "云图看是过云雨,已停"})
    assert not await zone_on()
    from app.services.weather_zone import _recent_blocking
    async with SessionLocal() as db:
        blocked = await _recent_blocking(db, CITY, DISTRICT)
    assert blocked, \
        "驳回后不进冷静期 —— 天气缓存 30 分钟内不变,会立刻又提请一模一样的单"
    print("✓ 驳回后进冷静期,不反复提请刷屏")

    await clear()
    print("\ne2e_weather_review 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
