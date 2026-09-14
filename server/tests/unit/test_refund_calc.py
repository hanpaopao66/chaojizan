"""退给顾客多少钱(services/refund_calc)。

2026-09-14 合并时发现四条退款路径各算各的:「售后被拒」「按送达处理」改判把缺货部分退款减了两次
(菜价字段已经扣过、已退金额又累加过),顾客少拿;「取消分摊」改判把平台券抵掉的钱当现金退;
商家同意售后把小费也退给顾客、骑手照拿,那一截是平台出。这里钉住统一后的口径。
"""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.services import refund_calc

SERVER = Path(__file__).resolve().parents[2]


class _DB:
    """只回答「这单缺货退了多少」的假库"""

    def __init__(self, out_of_stock: int):
        self.out_of_stock = out_of_stock

    async def scalar(self, _stmt):
        return self.out_of_stock


def _order(**kw):
    base = dict(id=1, rider_id=7, total_cents=0, refund_cents=0,
                delivery_fee_cents=500, tip_cents=300)
    base.update(kw)
    return SimpleNamespace(**base)


def _run(coro):
    return asyncio.run(coro)


def test_rider_keeps_delivery_fee_and_tip_only_when_a_rider_delivered():
    assert refund_calc.rider_kept_cents(_order()) == 800
    # 商家自配送 / 到店自取没有骑手:配送费在商家入账里,冲回净额时一起冲回
    assert refund_calc.rider_kept_cents(_order(rider_id=None)) == 0


def test_out_of_stock_refund_is_not_subtracted_twice():
    # 下单:两份菜 2×2000,配送 500,小费 300,实付 4800;缺货退一份 2000 之后
    # 实付字段已经扣成 2800,已退金额累加成 2000 —— 这 2000 只能算一次
    o = _order(total_cents=2800, refund_cents=2000)
    assert _run(refund_calc.goods_unrefunded_cents(_DB(2000), o)) == 2000   # 2800 − 500 − 300
    assert _run(refund_calc.unrefunded_paid_cents(_DB(2000), o)) == 2800


def test_other_refunds_already_paid_are_not_paid_again():
    # 同一单之前还退过 600(不是缺货):那 600 已经给了顾客,这里要减掉
    o = _order(total_cents=2800, refund_cents=2600)
    assert _run(refund_calc.goods_unrefunded_cents(_DB(2000), o)) == 1400
    # 退到头也不会变成负数
    o = _order(total_cents=2800, refund_cents=9999)
    assert _run(refund_calc.goods_unrefunded_cents(_DB(0), o)) == 0


def test_cancel_split_overturn_refunds_what_the_customer_actually_bore():
    # 取消分摊时退了 1800,顾客承担 1200(实付 3000,平台券抵的钱不在实付里,也就不会被当现金退)
    o = _order(total_cents=3000, refund_cents=1800)
    assert _run(refund_calc.unrefunded_paid_cents(_DB(0), o)) == 1200


def test_old_formulas_do_not_come_back():
    """「− order.refund_cents」这种写法就是把缺货退款减两次的那个形状"""
    for rel in ("app/routers/appeals.py", "app/routers/after_sales.py"):
        src = (SERVER / rel).read_text(encoding="utf-8")
        assert "- order.refund_cents" not in src, f"{rel} 又自己算退款了,改用 services/refund_calc"
    after_sales = (SERVER / "app/routers/after_sales.py").read_text(encoding="utf-8")
    assert "goods_unrefunded_cents" in after_sales
    appeals = (SERVER / "app/routers/appeals.py").read_text(encoding="utf-8")
    assert appeals.count("goods_unrefunded_cents(db, order)") == 2
    assert "unrefunded_paid_cents(db, order)" in appeals


def test_out_of_stock_refunds_are_written_with_the_prefix_we_read():
    src = (SERVER / "app/routers/orders.py").read_text(encoding="utf-8")
    assert "{OUT_OF_STOCK_REFUND_PREFIX}{note_piece}" in src
