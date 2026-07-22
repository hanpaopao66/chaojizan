"""税务报表导出(管理员):财务报税用,口径与公开账本/钱包完全同源。

三份月度 CSV:
  1. platform-income.csv    平台收入明细(外卖佣金/团购服务费,逐笔含冲账与调整)
  2. rider-income.csv       骑手所得汇总(按人:配送费收入 + 当月已打款)
  3. merchant-settlement.csv 商家结算汇总(按店:外卖净额 + 团购净额 + 当月已打款)

冲账/调整负数行直接求和 = 净口径;导出带 BOM,Excel 直接打开不乱码。
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models import (
    EarningKind,
    Merchant,
    MerchantEarning,
    RiderEarning,
    User,
    Voucher,
    VoucherPurchase,
    VoucherPurchaseStatus,
    Withdrawal,
    WithdrawalStatus,
)
from ..security import require_role
from .invoices import CN_TZ, _period_bounds_utc

router = APIRouter(prefix="/admin/tax", tags=["税务导出"])

_KIND_LABELS = {
    EarningKind.earning: "外卖佣金",
    EarningKind.reversal: "售后冲账",
    EarningKind.adjustment: "申诉调整",
}


def _yuan(cents: int) -> str:
    return f"{cents / 100:.2f}"


def _check_period(period: str) -> None:
    if not (len(period) == 7 and period[4] == "-"
            and period[:4].isdigit() and period[5:7].isdigit()
            and 1 <= int(period[5:7]) <= 12):
        raise HTTPException(422, "月份格式应为 YYYY-MM")


def _csv_response(generate, filename: str) -> StreamingResponse:
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/platform-income.csv")
async def platform_income_csv(
    period: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """平台收入明细:佣金逐笔(含冲账/调整负项)+ 团购服务费逐笔。"""
    _check_period(period)
    start, end = _period_bounds_utc(period)
    earnings = (await db.scalars(
        select(MerchantEarning).where(
            MerchantEarning.created_at >= start,
            MerchantEarning.created_at < end))).all()
    shops = {m.id: m.name for m in await db.scalars(select(Merchant))}
    redeems = (await db.execute(
        select(VoucherPurchase, Voucher.title)
        .join(Voucher, Voucher.id == VoucherPurchase.voucher_id)
        .where(VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
               VoucherPurchase.redeemed_at >= start,
               VoucherPurchase.redeemed_at < end))).all()

    rows = [
        (e.created_at, _KIND_LABELS.get(e.kind, e.kind.value), e.order_no,
         shops.get(e.merchant_id, str(e.merchant_id)), e.commission_cents,
         e.note.replace(",", ";").replace("\n", " "))
        for e in earnings
    ] + [
        (p.redeemed_at, "团购服务费", p.purchase_no,
         shops.get(p.merchant_id, str(p.merchant_id)), p.commission_cents,
         title.replace(",", ";"))
        for p, title in redeems
    ]
    rows.sort(key=lambda x: x[0])

    def generate():
        yield "﻿"
        yield "日期,类型,单号,商家,平台收入(元),备注\n"
        for at, kind, no, shop_name, cents, note in rows:
            day = at.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M")
            yield f"{day},{kind},{no},{shop_name},{_yuan(cents)},{note}\n"
        total = sum(x[4] for x in rows)
        reversal_count = sum(1 for x in rows if x[1] != "外卖佣金"
                             and x[1] != "团购服务费")
        yield (f"合计,,,,{_yuan(total)},"
               f"{period} 平台收入(净口径,含 {reversal_count} 笔冲账/调整)\n")

    return _csv_response(generate, f"platform-income-{period}.csv")


@router.get("/rider-income.csv")
async def rider_income_csv(
    period: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """骑手所得汇总(按人):劳务所得申报的底表。打款按处理时间归月。"""
    _check_period(period)
    start, end = _period_bounds_utc(period)
    earnings = (await db.scalars(
        select(RiderEarning).where(
            RiderEarning.created_at >= start,
            RiderEarning.created_at < end))).all()
    paid = (await db.scalars(
        select(Withdrawal).where(
            Withdrawal.role == "rider",
            Withdrawal.status == WithdrawalStatus.paid,
            Withdrawal.processed_at >= start,
            Withdrawal.processed_at < end))).all()
    by_rider: dict[int, dict] = {}
    for e in earnings:
        r = by_rider.setdefault(e.rider_id, {"earn": 0, "orders": 0, "paid": 0})
        r["earn"] += e.amount_cents
        if e.kind == EarningKind.earning:
            r["orders"] += 1
    for w in paid:
        r = by_rider.setdefault(w.user_id, {"earn": 0, "orders": 0, "paid": 0})
        r["paid"] += w.amount_cents
    users = {u.id: u for u in await db.scalars(
        select(User).where(User.id.in_(list(by_rider) or [0])))}

    def generate():
        yield "﻿"
        yield "骑手,手机号,当月配送费收入(元),完成单数,当月已打款(元)\n"
        for rider_id, r in sorted(by_rider.items()):
            u = users.get(rider_id)
            name = u.name if u else str(rider_id)
            phone = u.phone if u else ""
            yield (f"{name},{phone},{_yuan(r['earn'])},"
                   f"{r['orders']},{_yuan(r['paid'])}\n")
        yield (f"合计,,{_yuan(sum(r['earn'] for r in by_rider.values()))},"
               f"{sum(r['orders'] for r in by_rider.values())},"
               f"{_yuan(sum(r['paid'] for r in by_rider.values()))}\n")

    return _csv_response(generate, f"rider-income-{period}.csv")


@router.get("/merchant-settlement.csv")
async def merchant_settlement_csv(
    period: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """商家结算汇总(按店):外卖净额(含冲账/调整)+团购净额+当月已打款提现。"""
    _check_period(period)
    start, end = _period_bounds_utc(period)
    earnings = (await db.scalars(
        select(MerchantEarning).where(
            MerchantEarning.created_at >= start,
            MerchantEarning.created_at < end))).all()
    redeems = (await db.scalars(
        select(VoucherPurchase).where(
            VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
            VoucherPurchase.redeemed_at >= start,
            VoucherPurchase.redeemed_at < end))).all()
    shops = {m.id: m for m in await db.scalars(select(Merchant))}
    owners = {u.id: u for u in await db.scalars(select(User))}
    paid = (await db.scalars(
        select(Withdrawal).where(
            Withdrawal.role == "merchant",
            Withdrawal.status == WithdrawalStatus.paid,
            Withdrawal.processed_at >= start,
            Withdrawal.processed_at < end))).all()
    paid_by_owner: dict[int, int] = {}
    for w in paid:
        paid_by_owner[w.user_id] = paid_by_owner.get(w.user_id, 0) + w.amount_cents

    by_shop: dict[int, dict] = {}
    for e in earnings:
        r = by_shop.setdefault(e.merchant_id, {"food_net": 0, "voucher_net": 0})
        r["food_net"] += e.net_cents
    for p in redeems:
        r = by_shop.setdefault(p.merchant_id, {"food_net": 0, "voucher_net": 0})
        r["voucher_net"] += p.net_cents

    def generate():
        yield "﻿"
        yield "商家,店主手机号,外卖净额(元),团购净额(元),当月已打款提现(元)\n"
        for shop_id, r in sorted(by_shop.items()):
            shop = shops.get(shop_id)
            owner = owners.get(shop.owner_id) if shop else None
            name = shop.name if shop else str(shop_id)
            phone = owner.phone if owner else ""
            paid_cents = paid_by_owner.get(shop.owner_id, 0) if shop else 0
            yield (f"{name},{phone},{_yuan(r['food_net'])},"
                   f"{_yuan(r['voucher_net'])},{_yuan(paid_cents)}\n")
        yield (f"合计,,{_yuan(sum(r['food_net'] for r in by_shop.values()))},"
               f"{_yuan(sum(r['voucher_net'] for r in by_shop.values()))},"
               f"{_yuan(sum(paid_by_owner.values()))}\n")

    return _csv_response(generate, f"merchant-settlement-{period}.csv")


@router.get("/commission-invoice.csv")
async def commission_invoice_csv(
    period: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """佣金开票依据:按商家汇总当月平台服务费(外卖佣金净额+团购服务费),
    口径与 InvoiceRequest 申请金额、platform-income.csv 完全同源。
    向商家开具「平台服务费」发票时按这份对数。"""
    from sqlalchemy import func as sa_func
    _check_period(period)
    start, end = _period_bounds_utc(period)
    commission_rows = (await db.execute(
        select(MerchantEarning.merchant_id,
               sa_func.sum(MerchantEarning.commission_cents))
        .where(MerchantEarning.created_at >= start,
               MerchantEarning.created_at < end)
        .group_by(MerchantEarning.merchant_id))).all()
    voucher_rows = (await db.execute(
        select(VoucherPurchase.merchant_id,
               sa_func.sum(VoucherPurchase.commission_cents))
        .where(VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
               VoucherPurchase.redeemed_at >= start,
               VoucherPurchase.redeemed_at < end)
        .group_by(VoucherPurchase.merchant_id))).all()
    voucher_map = dict(voucher_rows)
    shops = {m.id: m for m in await db.scalars(select(Merchant))}
    merged = {mid: [cents, voucher_map.pop(mid, 0) or 0]
              for mid, cents in commission_rows}
    for mid, cents in voucher_map.items():
        merged[mid] = [0, cents or 0]

    def generate():
        yield "﻿"
        yield "商家,外卖佣金(元),团购服务费(元),合计(元),发票抬头,税号\n"
        total = 0
        for mid, (food_c, voucher_c) in sorted(merged.items()):
            shop = shops.get(mid)
            name = shop.name if shop else str(mid)
            title = (shop.invoice_title if shop else "").replace(",", ";")
            tax_no = shop.invoice_tax_no if shop else ""
            subtotal = (food_c or 0) + voucher_c
            total += subtotal
            yield (f"{name},{_yuan(food_c or 0)},{_yuan(voucher_c)},"
                   f"{_yuan(subtotal)},{title or '(未填)'},{tax_no}\n")
        yield f"合计,,,{_yuan(total)},{period} 平台服务费(开票依据),\n"

    return _csv_response(generate, f"commission-invoice-{period}.csv")
