"""骑手在线时长验证:上下线写区间、重复上线防重、心跳断档补下线、
工时统计口径、admin 列聚合。

在 server/ 目录下运行:python -m tests.e2e_rider_worklog
"""
import asyncio
import time

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import sweep_once
from tests.util import call, login, register_fresh_rider


async def main():
    admin = login("13800000000")
    rider = await register_fresh_rider("考勤测试骑手")
    rid = call("GET", "/auth/me", rider)["id"]

    # 1) 上线写开区间;重复上线不重复开
    call("POST", "/riders/online", rider, {"is_online": True})
    call("POST", "/riders/online", rider, {"is_online": True})
    async with SessionLocal() as db:
        n_open = await db.scalar(text(
            "SELECT count(*) FROM rider_sessions WHERE rider_id = :r "
            "AND offline_at IS NULL"), {"r": rid})
    assert n_open == 1, f"开区间应唯一:{n_open}"
    print("✓ 上线写区间,重复上线防重")

    # 2) 下线闭区间;工时统计能拿到数据
    time.sleep(1)
    call("POST", "/riders/online", rider, {"is_online": False})
    async with SessionLocal() as db:
        n_open = await db.scalar(text(
            "SELECT count(*) FROM rider_sessions WHERE rider_id = :r "
            "AND offline_at IS NULL"), {"r": rid})
    assert n_open == 0
    log = call("GET", "/riders/me/worklog", rider)
    assert log["today_minutes"] >= 0 and "week_orders" in log
    print("✓ 下线闭区间,工时接口口径完整")

    # 3) 心跳断档补下线:上线但无位置心跳,区间做旧 6 分钟 → 清扫置离线
    call("POST", "/riders/online", rider, {"is_online": True})
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE rider_sessions SET online_at = now() - interval '6 minutes' "
            "WHERE rider_id = :r AND offline_at IS NULL"), {"r": rid})
        await db.commit()
    await sweep_once()
    async with SessionLocal() as db:
        row = (await db.execute(text(
            "SELECT u.is_online, (SELECT count(*) FROM rider_sessions s "
            "WHERE s.rider_id = u.id AND s.offline_at IS NULL) "
            "FROM users u WHERE u.id = :r"), {"r": rid})).first()
    assert row[0] is False and row[1] == 0, "断档应置离线并闭区间"
    print("✓ 心跳断档 5 分钟,清扫任务补写下线")

    # 4) admin 骑手列表带近7天在线时长
    profiles = call("GET", "/admin/rider-profiles?status=approved", admin)
    me = next((p for p in profiles if p["rider_id"] == rid), None)
    assert me is not None and me["online_7d_minutes"] >= 0
    print("✓ admin 骑手列表带近 7 天在线时长")

    print("\ne2e_rider_worklog 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
