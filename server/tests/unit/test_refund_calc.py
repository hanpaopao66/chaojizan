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
    """只回答「这单退的同时已经扣了实付的退款(缺货、改地址)有多少」的假库"""

    def __init__(self, deducted: int):
        self.deducted = deducted

    async def scalar(self, _stmt):
        return self.deducted


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


def test_address_change_refund_is_not_subtracted_twice():
    # 下单实付 3000(配送 500);改地址退配送费差价 100:实付字段扣成 2900、已退累加 100 ——
    # 这 100 和缺货退款一样,只能算一次(原来只认缺货退款,改过地址的单全额退款时少退 100)
    o = _order(total_cents=2900, refund_cents=100, delivery_fee_cents=400)
    assert _run(refund_calc.unrefunded_paid_cents(_DB(100), o)) == 2900


def test_refunds_that_did_not_touch_total_are_subtracted():
    # 帮买按小票退差价 200:只记已退、不扣实付 —— 全额退款要把它减掉,不然差价退两遍
    o = _order(total_cents=3000, refund_cents=200)
    assert _run(refund_calc.unrefunded_paid_cents(_DB(0), o)) == 2800


def test_both_deducting_refunds_are_recognised_by_reason():
    """退的同时扣实付的两种退款,都按写入时用的那个原因认 —— 字符串各写一份的话改一处就静默对不上"""
    import inspect
    src = inspect.getsource(refund_calc.deducted_refunds_cents)
    assert "OUT_OF_STOCK_REFUND_PREFIX" in src and "ADDRESS_CHANGE_REFUND_REASON" in src
    orders_src = (SERVER / "app/routers/orders.py").read_text(encoding="utf-8")
    assert "request_refund(db, order, refunded, ADDRESS_CHANGE_REFUND_REASON)" in orders_src
    assert '"改地址,配送费差价退还")' not in orders_src


def test_rider_fault_refunds_what_is_left_not_total():
    """判骑手责任的「全额退款」退还没退回去的实付,不直接退 total_cents"""
    import inspect

    from app.routers import admin
    from app.services import rider_fault
    assert "unrefunded_paid_cents(db, order)" in inspect.getsource(rider_fault.judge_after_sale)
    assert "refund_amount = order.total_cents" not in inspect.getsource(rider_fault.judge_after_sale)
    assert "unrefunded_paid_cents(db, order)" in inspect.getsource(admin.resolve_delivery_issue)


def test_old_formulas_do_not_come_back():
    """「− order.refund_cents」这种写法就是把缺货退款减两次的那个形状"""
    for rel in ("app/routers/appeals.py", "app/routers/after_sales.py"):
        src = (SERVER / rel).read_text(encoding="utf-8")
        assert "- order.refund_cents" not in src, f"{rel} 又自己算退款了,改用 services/refund_calc"
    after_sales = (SERVER / "app/routers/after_sales.py").read_text(encoding="utf-8")
    assert "merchant_fault_refund_cents(db, order)" in after_sales
    appeals = (SERVER / "app/routers/appeals.py").read_text(encoding="utf-8")
    # 「餐钱」口径只剩顾客对「按送达处理」申诉改判那一处(平台退、不是商家责任);
    # 商家有责任的路退全款(2026-09-15 定)
    assert appeals.count("goods_unrefunded_cents(db, order)") == 1
    assert "merchant_fault_refund_cents(db, order)" in appeals
    assert "unrefunded_paid_cents(db, order)" in appeals


def test_merchant_fault_refunds_everything_left():
    """商家有责任:顾客拿回全款(含配送费和小费),不再只退「餐钱」"""
    o = _order(total_cents=2800, refund_cents=0)
    assert _run(refund_calc.merchant_fault_refund_cents(_DB(0), o)) == 2800
    # 缺货退过一份:剩下的全退,缺货那笔只算一次
    o = _order(total_cents=2800, refund_cents=2000)
    assert _run(refund_calc.merchant_fault_refund_cents(_DB(2000), o)) == 2800


def test_goods_only_is_not_used_on_merchant_paths():
    """「顾客为餐付的钱」这个口径不许再出现在商家有责任的四条路上(名不副实的函数不留在那儿)"""
    import inspect

    from app.routers import admin, after_sales, appeals
    for fn in (after_sales.accept_after_sale, admin.resolve_delivery_issue,
               admin.confirm_food_safety):
        src = inspect.getsource(fn)
        assert "goods_unrefunded_cents" not in src, fn.__name__
        assert "merchant_fault_refund_cents" in src, fn.__name__
    rejected = inspect.getsource(appeals._overturn).split(
        'elif appeal.target_type == "after_sale_rejected":')[1].split("elif appeal.target_type")[0]
    assert "merchant_fault_refund_cents(db, order)" in rejected
    assert "goods_unrefunded_cents" not in rejected


def test_out_of_stock_refunds_are_written_with_the_prefix_we_read():
    src = (SERVER / "app/routers/orders.py").read_text(encoding="utf-8")
    assert "{OUT_OF_STOCK_REFUND_PREFIX}{note_piece}" in src
