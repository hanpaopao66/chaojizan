"""公开账本:按日导出匿名化流水 → 哈希链锚点。

信任模型(见 witness/README.md):
  - payload 只含金额与订单号哈希(uuid 截断有 80 位熵,不可反推),零个人信息;
  - chain_hash = sha256(昨日 chain_hash + 今日 payload_hash),改历史即断链;
  - 社区见证节点各自留存见过的锚点并持续比对——平台自己也无法改写历史。
锚点只为北京时间已过完的日子生成,生成后永不重算(账本铁律的延伸)。
"""
import hashlib
import json
import logging
from datetime import date, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import LedgerAnchor

logger = logging.getLogger("superz.ledger")

GENESIS = "0" * 64
SCHEMA = 1
# 首次上线时不回补无穷多的空日子:最多回补到最早一条流水那天(再早没有意义)
MAX_BACKFILL_DAYS = 400


def canonical(obj) -> str:
    """规范化 JSON:键排序、无空格、保留中文——两端字节级一致才能对哈希。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def hash_no(no: str) -> str:
    """订单号/券号匿名化:sha256 截 24 位 hex。知道自己单号的人可以自行
    验证「我的订单在公开账本里」,别人无法反推(单号是 80 位熵的随机串)。"""
    return sha256(no)[:24]


async def build_day_payload(db: AsyncSession, day: str) -> dict:
    """导出某天(北京时间)的全部账务流水,行序按主键,保证可复算。"""
    span = {"d": day}
    where = ("created_at >= (:d || ' 00:00:00')::timestamp AT TIME ZONE 'Asia/Shanghai' "
             "AND created_at < ((:d)::date + 1 || ' 00:00:00')::timestamp AT TIME ZONE 'Asia/Shanghai'")

    merchant_rows = [
        {"o": hash_no(r[0]), "food": r[1], "commission": r[2],
         "net": r[3], "kind": r[4]}
        for r in await db.execute(text(
            f"SELECT order_no, food_cents, commission_cents, net_cents, kind "
            f"FROM merchant_earnings WHERE {where} ORDER BY id"), span)
    ]
    rider_rows = [
        {"o": hash_no(r[0]), "amount": r[1], "kind": r[2]}
        for r in await db.execute(text(
            f"SELECT order_no, amount_cents, kind "
            f"FROM rider_earnings WHERE {where} ORDER BY id"), span)
    ]
    voucher_where = where.replace("created_at", "redeemed_at")
    voucher_rows = [
        {"p": hash_no(r[0]), "gross": r[1], "fee": r[2], "net": r[3]}
        for r in await db.execute(text(
            f"SELECT purchase_no, sell_price_cents, commission_cents, net_cents "
            f"FROM voucher_purchases WHERE status = 'redeemed' AND {voucher_where} "
            f"ORDER BY id"), span)
    ]
    # 骑手保障金计提:每笔配送入账计提固定额,从平台佣金中拨出,
    # 用于骑手意外险与骑手责任先行赔付(不扣骑手工资的资金来源,公开可验)
    fund_orders = sum(1 for r in rider_rows if r["kind"] == "earning")
    return {
        "schema": SCHEMA,
        "day": day,
        "commission_rate_max": 0.05,   # 三原则之一:商家佣金上限(历史锚点各天冻结当天费率)
        "voucher_rate": settings.voucher_commission_rate,
        "merchant_rows": merchant_rows,
        "rider_rows": rider_rows,
        "voucher_rows": voucher_rows,
        "rider_fund": {
            "per_order_cents": settings.rider_fund_per_order_cents,
            "orders": fund_orders,
            "accrued_cents": fund_orders * settings.rider_fund_per_order_cents,
        },
        "totals": {
            "merchant_net": sum(r["net"] for r in merchant_rows),
            "platform_commission": sum(r["commission"] for r in merchant_rows),
            "rider_amount": sum(r["amount"] for r in rider_rows),
            "voucher_fee": sum(r["fee"] for r in voucher_rows),
            "rider_fund": fund_orders * settings.rider_fund_per_order_cents,
        },
    }


def _today_beijing() -> date:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


async def _first_activity_day(db: AsyncSession) -> date | None:
    row = await db.execute(text(
        "SELECT least(coalesce((SELECT min(created_at) FROM merchant_earnings), now()),"
        "             coalesce((SELECT min(created_at) FROM rider_earnings), now()))"
        " AT TIME ZONE 'Asia/Shanghai'"))
    v = row.scalar()
    return v.date() if v else None


async def build_missing_anchors(db: AsyncSession) -> int:
    """把锚点补到昨天为止(幂等,auto_flow 每轮调用,通常零工作量)。"""
    yesterday = _today_beijing() - timedelta(days=1)
    last = await db.scalar(
        select(LedgerAnchor).order_by(LedgerAnchor.day.desc()).limit(1))
    if last is None:
        start = await _first_activity_day(db) or yesterday
        start = max(start, yesterday - timedelta(days=MAX_BACKFILL_DAYS))
        prev_hash = GENESIS
    else:
        start = date.fromisoformat(last.day) + timedelta(days=1)
        prev_hash = last.chain_hash

    built = 0
    day = start
    while day <= yesterday:
        day_str = day.isoformat()
        payload = await build_day_payload(db, day_str)
        payload_text = canonical(payload)
        payload_hash = sha256(payload_text)
        chain_hash = sha256(prev_hash + payload_hash)
        db.add(LedgerAnchor(day=day_str, payload=payload_text,
                            payload_hash=payload_hash, chain_hash=chain_hash))
        await db.commit()
        prev_hash = chain_hash
        built += 1
        day += timedelta(days=1)
    if built:
        logger.info("公开账本锚点 +%s(至 %s)", built, yesterday)
    return built
