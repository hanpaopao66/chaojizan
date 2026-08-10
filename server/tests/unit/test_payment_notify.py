"""微信支付回调加固(#201/#202)。

为什么这两条值得单测:它们错了**不会有人喊**,只会账不平 ——
金额不校验就入账,商家已经开始做菜而钱没收够;transaction_id 丢掉,
将来分账缺必传入参,而这个字段事后补不回来。
e2e 走不到这里(开发期 wxpay 未配置,回调根本进不来),所以只能在这一层守。

不起服务、不连库:用一个只实现回调路径真会调到的那几个方法的假会话,
把三条路径(拒绝、入账、重复回调)整个走完。
"""
import asyncio
from types import SimpleNamespace

from fastapi import HTTPException

from app.routers import payments
from app.state_machine import OrderStatus

TX_ID = "4200001234202608091234567890"


class FakeDB:
    """够用就好的假会话。scalar 按语句里的表名分流 ——
    回调路径上只有"查订单"和"查重复告警"两种查询。"""

    def __init__(self, order, existing_alert=None):
        self.order = order
        self.existing_alert = existing_alert
        self.added = []
        self.commits = 0

    async def scalar(self, stmt):
        if "audit_alerts" in str(stmt):
            return self.existing_alert
        return self.order

    async def get(self, model, pk):
        return SimpleNamespace(id=pk, owner_id=1, auto_accept=False, is_open=True)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


class FakeRequest:
    headers: dict = {}

    async def body(self):
        return b"{}"


def _order(**kw):
    base = dict(id=1, order_no="SZ20260809001", merchant_id=7,
                total_cents=4300, refund_cents=0, wx_transaction_id="",
                status=OrderStatus.PENDING_PAYMENT)
    base.update(kw)
    return SimpleNamespace(**base)


def _resource(total=4300, tx_id=TX_ID, drop_amount=False):
    res = {"trade_state": "SUCCESS", "out_trade_no": "SZ20260809001"}
    if not drop_amount:
        res["amount"] = {"total": total, "payer_total": total, "currency": "CNY"}
    if tx_id is not None:
        res["transaction_id"] = tx_id
    return res


def _run(monkeypatch, resource, order, existing_alert=None):
    """跑一次回调,返回 (结果或抛出的异常, 假会话, 入账过的订单列表)。"""
    marked = []
    db = FakeDB(order, existing_alert)
    monkeypatch.setattr(payments, "parse_notify",
                        lambda headers, body: ("TRANSACTION.SUCCESS", resource))

    async def _mark(db_, o, merchant, actor_role="system", actor_id=None):
        marked.append(o)
        if o.status == OrderStatus.PENDING_PAYMENT:  # 与真实实现同样幂等
            o.status = OrderStatus.PAID
        return o

    monkeypatch.setattr(payments, "mark_order_paid", _mark)
    try:
        out = asyncio.run(payments.wechat_notify(FakeRequest(), db))
    except HTTPException as exc:
        out = exc
    return out, db, marked


class Test金额不符一律拒绝入账:
    def test_金额对不上不入账并写告警(self, monkeypatch):
        """核心:验签只能证明"回调是微信发的",证明不了"钱收够了"。
        少收了还照常标已付,商家就白做一单菜。"""
        order = _order()
        out, db, marked = _run(monkeypatch, _resource(total=100), order)

        assert isinstance(out, HTTPException) and out.status_code == 400
        assert marked == [], "拒绝的回调绝不能走到入账"
        assert order.status == OrderStatus.PENDING_PAYMENT
        alerts = [a for a in db.added
                  if getattr(a, "check_name", "") == payments.AMOUNT_MISMATCH_CHECK]
        assert len(alerts) == 1
        assert order.order_no in alerts[0].detail
        assert "4300" in alerts[0].detail and "100" in alerts[0].detail
        assert db.commits >= 1, "告警必须落盘,否则拒绝入账就成了静默丢单"

    def test_拒绝的回调不在订单上留痕(self, monkeypatch):
        """金额不对时连 transaction_id 都不该落 —— 那笔交易我们没认。"""
        order = _order()
        _run(monkeypatch, _resource(total=99999), order)
        assert order.wx_transaction_id == ""

    def test_读不出金额也算校验不通过(self, monkeypatch):
        """amount 缺失 = 没验金额。"没验金额就入账"正是要堵的洞,
        所以宁可挡住(微信会重试),不能放过。"""
        order = _order()
        out, _, marked = _run(monkeypatch, _resource(drop_amount=True), order)
        assert isinstance(out, HTTPException) and out.status_code == 400
        assert marked == []

    def test_金额取的是total不是payer_total(self):
        """两者现在恒等(没接微信侧代金券),接了之后 payer_total 会更小。
        商家该收的、平台该抽佣的都是 total,比 payer_total 等于自己判错。"""
        res = {"amount": {"total": 4300, "payer_total": 3800}}
        assert payments._notify_amount_cents(res) == 4300

    def test_金额类型不对不当成数字(self):
        """字符串 "4300" 和布尔都不是合法金额;返回 None 让调用方拒绝,
        而不是悄悄转成 int 放行。"""
        assert payments._notify_amount_cents({"amount": {"total": "4300"}}) is None
        assert payments._notify_amount_cents({"amount": {"total": True}}) is None
        assert payments._notify_amount_cents({}) is None

    def test_重复告警按订单去重(self, monkeypatch):
        """微信 24 小时内会重试十几次。每次写一条会把后台红条刷满,
        反而盖掉别的账务问题 —— 告警的价值在被看见,不在条数。"""
        order = _order()
        _, db, _ = _run(monkeypatch, _resource(total=100), order,
                        existing_alert=123)
        assert not [a for a in db.added
                    if getattr(a, "check_name", "") == payments.AMOUNT_MISMATCH_CHECK]


class Test落库transaction_id:
    def test_金额一致才入账并落交易号(self, monkeypatch):
        """transaction_id 是分账接口的必传入参,以前回调里直接丢了。"""
        order = _order()
        out, db, marked = _run(monkeypatch, _resource(), order)

        assert out == {"code": "SUCCESS", "message": "成功"}
        assert marked == [order]
        assert order.wx_transaction_id == TX_ID
        assert not db.added, "正常入账不该产生告警"

    def test_重复回调不把交易号覆盖成空(self, monkeypatch):
        """微信重推的回调不保证带 transaction_id。覆盖回空值会让这一单
        永远分不了账,而且事后补不回来 —— 一旦落库就不再改写。"""
        order = _order(status=OrderStatus.PAID, wx_transaction_id=TX_ID)
        _run(monkeypatch, _resource(tx_id=None), order)
        assert order.wx_transaction_id == TX_ID

    def test_已落库的交易号不被新值改写(self, monkeypatch):
        order = _order(status=OrderStatus.PAID, wx_transaction_id=TX_ID)
        _run(monkeypatch, _resource(tx_id="4200009999202608099999999999"), order)
        assert order.wx_transaction_id == TX_ID

    def test_已支付订单的重复回调不再校验金额(self, monkeypatch):
        """支付之后 total_cents 会被加急小费、帮买按小票补收、改地址退差价
        改动,拿老回调去比新金额必然误报 —— 而误报多了这条检查就废了。
        重复回调没有资金动作要保护(入账本身幂等),跳过是安全的。"""
        order = _order(status=OrderStatus.PAID, total_cents=4800,
                       wx_transaction_id=TX_ID)
        out, db, _ = _run(monkeypatch, _resource(total=4300), order)
        assert out == {"code": "SUCCESS", "message": "成功"}
        assert not db.added

    def test_补落交易号时自己提交(self, monkeypatch):
        """存量已支付单收到重推:mark_order_paid 走幂等分支直接返回、不 commit,
        补落的交易号得自己提交,否则随会话一起丢掉。"""
        order = _order(status=OrderStatus.PAID, wx_transaction_id="")
        _, db, _ = _run(monkeypatch, _resource(), order)
        assert order.wx_transaction_id == TX_ID
        assert db.commits >= 1


class Test找不到订单:
    def test_返回404让微信重试(self, monkeypatch):
        """404 是**故意**的:回调常常跑在下单事务提交之前,
        微信重试一轮就对了。不能改成 200 悄悄咽掉。"""
        out, _, marked = _run(monkeypatch, _resource(), None)
        assert isinstance(out, HTTPException) and out.status_code == 404
        assert marked == []


class Test已取消订单收到付款:
    """钱收了、单没了 —— 这条路径以前是静默 ack。

    取消与支付并发、或超时清扫抢在回调前面,都会走到这里:
    微信那边显示付款成功,我们这边订单是已取消,钱躺在商户号里没人知道,
    直到用户来投诉。仍然 ack(已取消是终态,重试不会把它变回来),
    但必须留一条告警让人去退款。
    """

    def test_付款成功但订单已取消要告警(self, monkeypatch):
        order = _order(status=OrderStatus.CANCELLED)
        out, db, _ = _run(monkeypatch, _resource(), order)
        assert out == {"code": "SUCCESS", "message": "成功"}  # ack,不让微信重试
        alerts = [a for a in db.added
                  if getattr(a, "check_name", "") == payments.PAID_CANCELLED_CHECK]
        assert len(alerts) == 1, "已取消订单收到付款必须留告警"
        assert order.order_no in alerts[0].detail

    def test_同一单重复回调只告警一次(self, monkeypatch):
        order = _order(status=OrderStatus.CANCELLED)
        out, db, _ = _run(monkeypatch, _resource(), order, existing_alert=99)
        assert out == {"code": "SUCCESS", "message": "成功"}
        assert not [a for a in db.added
                    if getattr(a, "check_name", "") == payments.PAID_CANCELLED_CHECK]

    def test_正常待支付订单不产生这条告警(self, monkeypatch):
        _, db, _ = _run(monkeypatch, _resource(), _order())
        assert not [a for a in db.added
                    if getattr(a, "check_name", "") == payments.PAID_CANCELLED_CHECK]

    def test_已取消也要落交易号方便人工退款(self, monkeypatch):
        order = _order(status=OrderStatus.CANCELLED)
        _run(monkeypatch, _resource(), order)
        assert order.wx_transaction_id == TX_ID
