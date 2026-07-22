"""阶梯佣金验证:上月单量定档降费率、手工优惠店不上调、演示店不动、
重算幂等、商家端档位接口。

手法:直连 DB 给新建商家灌上个自然月的完成单(订单+完成事件+入账行,
入账行同步造好避免审计回填搅今天的账本),手动调月度重算函数断言。
在 server/ 目录下运行:python -m tests.e2e_tier_commission
"""
import asyncio
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.db import SessionLocal
from app.services.auto_flow import (
    BEIJING,
    maybe_recalc_commission_tiers,
    recalc_commission_tiers,
)
from tests.util import call, login

tag = str(int(time.time()))
admin = login("13800000000")
customer_id_sql = "SELECT id FROM users WHERE phone = '13800000001'"


def fresh_shop(suffix):
    """注册商家 → 申请 → 过审,返回 (token, shop_id)。"""
    phone = "137" + str(int(time.time() * 1000))[-8:]
    boss = call("POST", "/auth/register", body={
        "phone": phone, "password": "123456",
        "name": f"阶梯老板{suffix}", "role": "merchant"})["token"]
    shop = call("POST", "/merchants", boss, {
        "name": f"阶梯测试店{suffix}-{tag}", "address": "测试路 9 号",
        "lat": 30.6612, "lng": 104.0823,
        "license_no": "JY99900011188888",
        "license_image_url": "/uploads/license-demo.jpg"})
    call("POST", f"/admin/merchants/{shop['id']}/approve", admin)
    return boss, shop["id"]


async def seed_completed(mid: int, count: int, prefix: str):
    """灌上个自然月的完成单:订单 + completed 事件 + 商家入账行。"""
    now_bj = datetime.now(BEIJING)
    created = (now_bj.replace(day=1, hour=12, minute=0, second=0,
                              microsecond=0) - timedelta(days=15))
    async with SessionLocal() as db:
        await db.execute(text(f"""
            INSERT INTO orders (order_no, customer_id, merchant_id, status,
                items, food_cents, packing_fee_cents, discount_cents,
                subsidy_cents, promo_note, delivery_fee_cents, total_cents,
                commission_cents, address, lat, lng, contact_name,
                contact_phone, remark, parent_order_no, pickup, pickup_code,
                cancel_reason, ready_alert_stage, ready_late, privacy_phone,
                refund_cents, refund_note, created_at, updated_at)
            SELECT :prefix || lpad(g::text, 6, '0'), ({customer_id_sql}), :mid,
                'completed', '[]'::jsonb, 2000, 0, 0, 0, '', 0, 2000, 100,
                '阶梯测试', 0, 0, '', '', '', '', true, '', '', 0, false, '',
                0, '', :created, :created
            FROM generate_series(1, :n) g
        """), {"prefix": prefix, "mid": mid, "n": count, "created": created})
        await db.execute(text("""
            INSERT INTO order_events (order_id, from_status, to_status,
                actor_role, actor_id, note, created_at)
            SELECT id, 'delivered', 'completed', 'system', NULL, '', :created
            FROM orders WHERE order_no LIKE :pat
        """), {"pat": f"{prefix}%", "created": created})
        await db.execute(text("""
            INSERT INTO merchant_earnings (merchant_id, order_id, order_no,
                food_cents, commission_cents, net_cents, kind, note, created_at)
            SELECT merchant_id, id, order_no, 2000, 100, 1900, 'earning',
                '阶梯测试入账', :created
            FROM orders WHERE order_no LIKE :pat
        """), {"pat": f"{prefix}%", "created": created})
        await db.commit()


async def get_rate(mid: int) -> str:
    async with SessionLocal() as db:
        rate = await db.scalar(text(
            "SELECT commission_rate FROM merchants WHERE id = :id"),
            {"id": mid})
        return f"{rate:.3f}"


async def main():
    boss_a, sid_a = fresh_shop("A")   # 600 单 → 4.5%
    _, sid_b = fresh_shop("B")        # 600 单但手工 4% → 不上调
    _, sid_c = fresh_shop("C")        # 1050 单 → 4%
    await seed_completed(sid_a, 600, f"tierA{tag}")
    await seed_completed(sid_b, 600, f"tierB{tag}")
    await seed_completed(sid_c, 1050, f"tierC{tag}")
    async with SessionLocal() as db:
        await db.execute(text(
            "UPDATE merchants SET commission_rate = 0.040 WHERE id = :id"),
            {"id": sid_b})
        zhang_rate = await db.scalar(text(
            "SELECT commission_rate FROM merchants WHERE name = '张记面馆'"))
        await db.commit()
    assert f"{zhang_rate:.3f}" == "0.050"

    # 1) 月度重算:降档、不上调手工优惠店、单量不足的店不动
    async with SessionLocal() as db:
        changes = await recalc_commission_tiers(db, datetime.now(BEIJING))
    changed_ids = {c["merchant_id"] for c in changes}
    assert sid_a in changed_ids and sid_c in changed_ids, changes
    assert sid_b not in changed_ids, "手工 4% 的店不该出现在变更里"
    assert await get_rate(sid_a) == "0.045"
    assert await get_rate(sid_b) == "0.040"
    assert await get_rate(sid_c) == "0.040"
    async with SessionLocal() as db:
        zhang_after = await db.scalar(text(
            "SELECT commission_rate FROM merchants WHERE name = '张记面馆'"))
    assert f"{zhang_after:.3f}" == "0.050", "单量不足的演示店费率不动"
    print("✓ 月度重算:600 单降 4.5%、1050 单降 4%、手工 4% 不上调、演示店 5% 不动")

    # 2) 重算幂等:再跑一遍无变更
    async with SessionLocal() as db:
        changes2 = await recalc_commission_tiers(db, datetime.now(BEIJING))
    assert not changes2, changes2
    print("✓ 重算幂等,二次运行零变更")

    # 3) 非每月 1 日不触发(防重窗口逻辑)
    fake = datetime(2026, 6, 15, 4, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert await maybe_recalc_commission_tiers(fake) is False
    print("✓ 非每月 1 日 04:10 窗口不触发")

    # 4) 商家端档位接口:当前费率/上月单量/距下一档
    tier = call("GET", "/merchants/me/commission-tier", boss_a)
    assert tier["commission_rate"] == 0.045, tier
    assert tier["last_month_completed"] == 600, tier
    assert tier["next_tier_from"] == 500 and tier["orders_to_next"] == 500, tier
    assert tier["tiers"][0]["rate"] == 0.05
    print("✓ 商家端档位接口:费率/上月单量/距下一档口径正确")

    print("\ne2e_tier_commission 全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
