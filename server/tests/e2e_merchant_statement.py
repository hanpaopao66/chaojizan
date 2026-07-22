"""商家对账单导出验证:CSV 合计与 merchant_earnings 一致(含冲账行)、
月份格式 422、非商家 403、每日 10 次频控。

在 server/ 目录下运行:python -m tests.e2e_merchant_statement
"""
import asyncio
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.db import SessionLocal
from tests.util import BASE, call, login, register_fresh_customer

merchant = login("13800000002")
MONTH = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")


def fetch(token, month=MONTH):
    req = urllib.request.Request(
        f"{BASE}/merchants/me/statement.csv?month={month}",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


async def main():
    from app.redis_client import get_redis
    # 清频控键,保证可重复跑
    async with SessionLocal() as db:
        sid = (await db.execute(text(
            "SELECT id FROM merchants WHERE name = '张记面馆'"))).scalar()
    from datetime import date
    await get_redis().delete(f"stmt:{sid}:{MONTH}:{date.today()}")

    status, csv = fetch(merchant)
    assert status == 200, csv
    lines = csv.strip().splitlines()
    assert "对账单" in lines[0] or "对账单" in lines[1]
    total_line = lines[-1].split(",")
    csv_net = float(total_line[5])
    async with SessionLocal() as db:
        db_net = (await db.execute(text(
            """SELECT coalesce(sum(net_cents), 0) FROM merchant_earnings
               WHERE merchant_id = :m
                 AND created_at >= (date_trunc('month',
                     now() AT TIME ZONE 'Asia/Shanghai')
                     AT TIME ZONE 'Asia/Shanghai')"""), {"m": sid})).scalar()
        n_rows = (await db.execute(text(
            """SELECT count(*) FROM merchant_earnings
               WHERE merchant_id = :m
                 AND created_at >= (date_trunc('month',
                     now() AT TIME ZONE 'Asia/Shanghai')
                     AT TIME ZONE 'Asia/Shanghai')"""), {"m": sid})).scalar()
    assert abs(csv_net - db_net / 100) < 0.005, (csv_net, db_net)
    assert f"({n_rows} 行)" in lines[-1]
    reversal_rows = [x for x in lines if ",冲账," in x]
    print(f"✓ 合计与 merchant_earnings 一致({n_rows} 行,"
          f"含 {len(reversal_rows)} 笔冲账负数行)")

    status, _ = fetch(merchant, month="2026-13")
    assert status == 422
    status, _ = fetch(register_fresh_customer())
    assert status == 403
    print("✓ 月份校验 422,非商家 403")

    for _ in range(9):
        fetch(merchant)
    status, body = fetch(merchant)
    assert status == 429, (status, body[:80])
    await get_redis().delete(f"stmt:{sid}:{MONTH}:{date.today()}")
    print("✓ 每日 10 次频控")

    print("\ne2e_merchant_statement 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
