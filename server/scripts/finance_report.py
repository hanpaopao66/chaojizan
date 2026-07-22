"""月度开源财报生成器(M6:收入自养 + 财报开源)。

收入侧直接从账本聚合(佣金/冲账/平台补贴),成本侧留模板手填
(服务器/短信/推送账单在各服务商后台)。生成 docs/finance/YYYY-MM.md,
审阅补全后随公开仓发布——钱的来路和去路全透明,这比众筹更"群众路线"。

用法(在 server/ 目录):
    python -m scripts.finance_report 2026-07
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func as sa_func
from sqlalchemy import select

sys.path.insert(0, ".")

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    EarningKind,
    MerchantEarning,
    Order,
    RiderEarning,
    VoucherPurchase,
    VoucherPurchaseStatus,
)
from app.state_machine import OrderStatus  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "finance"


def month_range(ym: str):
    start = datetime.strptime(ym, "%Y-%m").replace(tzinfo=timezone.utc)
    end = (start.replace(year=start.year + 1, month=1)
           if start.month == 12 else start.replace(month=start.month + 1))
    return start, end


async def build(ym: str) -> str:
    start, end = month_range(ym)
    async with SessionLocal() as db:
        def in_month(col):
            return (col >= start) & (col < end)

        orders_done = await db.scalar(
            select(sa_func.count(Order.id)).where(
                Order.status == OrderStatus.COMPLETED,
                in_month(Order.created_at)))
        gmv = await db.scalar(
            select(sa_func.coalesce(sa_func.sum(Order.total_cents), 0)).where(
                Order.status == OrderStatus.COMPLETED,
                in_month(Order.created_at)))
        # 佣金收入:入账 - 冲账(直接对账本求和,冲账负数行自动抵扣)
        commission = await db.scalar(
            select(sa_func.coalesce(
                sa_func.sum(MerchantEarning.commission_cents), 0)).where(
                in_month(MerchantEarning.created_at)))
        rider_fees = await db.scalar(
            select(sa_func.coalesce(
                sa_func.sum(RiderEarning.amount_cents), 0)).where(
                in_month(RiderEarning.created_at),
                RiderEarning.kind == EarningKind.earning))
        subsidies = await db.scalar(
            select(sa_func.coalesce(sa_func.sum(Order.subsidy_cents), 0)).where(
                Order.status == OrderStatus.COMPLETED,
                in_month(Order.created_at)))
        # 团购核销服务费(3%,只在核销时产生)
        voucher_commission = await db.scalar(
            select(sa_func.coalesce(
                sa_func.sum(VoucherPurchase.commission_cents), 0)).where(
                VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
                in_month(VoucherPurchase.redeemed_at)))
        voucher_redeemed = await db.scalar(
            select(sa_func.count(VoucherPurchase.id)).where(
                VoucherPurchase.status == VoucherPurchaseStatus.redeemed,
                in_month(VoucherPurchase.redeemed_at)))
        # 售后中平台承担的配送费(全额退款单的配送费损失,见 after_sales.py)
        aftersale_fee_loss = await db.scalar(
            select(sa_func.coalesce(
                sa_func.sum(Order.delivery_fee_cents), 0)).where(
                Order.status == OrderStatus.COMPLETED,
                Order.refund_cents >= Order.total_cents,
                Order.total_cents > 0,
                in_month(Order.created_at)))

    def y(cents):
        return f"{cents / 100:,.2f}"

    return f"""# Super-Z 财报 · {ym}

> 收入数字由账本自动聚合(`python -m scripts.finance_report {ym}`),
> 任何人可对照开源代码核验口径;成本为各服务商实际账单。

## 收入

| 项目 | 金额(元) | 说明 |
|---|---:|---|
| 外卖佣金 | {y(commission)} | 商家实收 × 6%,售后冲账已抵扣 |
| 团购核销服务费 | {y(voucher_commission)} | 券售价 × 3%,共 {voucher_redeemed} 张核销 |
| **收入合计** | **{y(commission + voucher_commission)}** | |

## 成本(手填,附账单截图)

| 项目 | 金额(元) | 说明 |
|---|---:|---|
| 服务器 | 待填 | |
| 短信 | 待填 | 腾讯云 |
| 推送 | 待填 | 极光 |
| 域名/证书 | 待填 | |
| 平台补贴(首单立减) | {y(subsidies)} | 自动聚合 |
| 售后承担的配送费 | {y(aftersale_fee_loss)} | 全额退款单,骑手照常拿钱 |
| **成本合计** | 待填 | |

## 结余

| | 金额(元) |
|---|---:|
| 本月结余 | 待填(收入-成本) |
| 累计结余 | 待填 |

## 规模参考(非资金项)

- 完成订单:{orders_done} 单,GMV ¥{y(gmv)}
- 骑手配送费(100% 归骑手,不经平台资金池):¥{y(rider_fees)}

## 赞助(如有,与运营资金分开记账)

| 渠道 | 金额(元) | 用途 |
|---|---:|---|
| - | - | - |

---
*Super-Z 收入自养,永不接受公众募资。对本财报有疑问,欢迎开 Issue。*
"""


if __name__ == "__main__":
    ym = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m")
    report = asyncio.run(build(ym))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{ym}.md"
    out.write_text(report)
    print(f"✓ 财报草稿已生成: {out}\n  补全成本项后即可随公开仓发布")
