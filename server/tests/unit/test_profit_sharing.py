"""分账桩的失败语义(#200)。

守的是一条原则:**渠道没接通之前,台账里不许出现 success。**

这条以前反着来:商户参数配齐就返回 True、台账直接置 success。
于是管理端一打开某商家的 ps_ready,系统就开始产出「分账成功」记录,
而实际一分钱没动 —— 而且它对得很自信,下游(商家钱包、审计恒等、
微信账单核对)全都以为这笔已经了结,对账在错误的地方停下来。

第二条同样重要:未接通的渠道**不许把台账烧成 failed**。
failed 是终态且清扫只捞 pending,烧掉就得人工一条条捞回来。
"""
import asyncio
from types import SimpleNamespace

from app.services import profit_sharing as ps


def _record(**kw):
    base = dict(order_no="SZ20260809001", net_cents=4085, commission_cents=215,
                sub_mchid="1900001109", status="pending", attempts=0, note="")
    base.update(kw)
    return SimpleNamespace(**base)


class FakeSweepDB:
    def __init__(self, rows):
        self.rows = rows

    async def scalars(self, stmt):
        return SimpleNamespace(all=lambda: self.rows)

    async def scalar(self, stmt):
        return self.rows[0] if self.rows else None


class Test渠道未接通时不许假成功:
    def test_未配置返回挂起(self, monkeypatch):
        monkeypatch.setattr(ps, "get_client", lambda: None)
        rec = _record()
        assert asyncio.run(ps._call_channel(rec, "请求")) == ps.CHANNEL_UNIMPLEMENTED

    def test_配置齐了也不返回成功(self, monkeypatch):
        """**这条是本次改动的全部要点。**配置齐 ≠ 分账接口写好了 ——
        真实调用要等类目答案(普通服务商 or 电商收付通,两套 API 不通用)。"""
        monkeypatch.setattr(ps, "get_client", lambda: object())
        rec = _record()
        assert asyncio.run(ps._call_channel(rec, "请求")) == ps.CHANNEL_UNIMPLEMENTED
        assert rec.status == "pending"

    def test_配置齐了却调不出去要吵(self, monkeypatch, caplog):
        """未配置是预期状态(info 就够);配置齐了还发不出去说明
        已经有人以为分账能用了,商家可能正等着货款 —— 必须 error 级。"""
        monkeypatch.setattr(ps, "get_client", lambda: object())
        with caplog.at_level("ERROR", logger="superz.profit_sharing"):
            asyncio.run(ps._call_channel(_record(), "请求"))
        assert any(r.levelname == "ERROR" for r in caplog.records)


class Test清扫不把挂起烧成终态:
    def test_渠道未实现时留在pending且不计次(self, monkeypatch):
        """attempts 是"真打到渠道几次",不是"被扫过几次"。
        混在一起的话,5 轮清扫就把全部台账烧成 failed,
        而清扫只捞 pending —— 分账真接上那天一条都不会自动重试。"""
        monkeypatch.setattr(ps, "get_client", lambda: object())
        rec = _record()
        db = FakeSweepDB([rec])
        for _ in range(ps.MAX_ATTEMPTS * 2):
            assert asyncio.run(ps.sweep_pending(db)) == 0
        assert rec.status == "pending", "未接通的渠道不该产生终态"
        assert rec.attempts == 0

    def test_单笔失败照常计次并烧到failed(self, monkeypatch):
        """另一半:真打到渠道又被拒的,仍要在上限后转人工 ——
        不能因为要保护"未实现"就把重试上限也一起废掉。"""
        monkeypatch.setattr(ps, "get_client", lambda: object())
        monkeypatch.setattr(
            ps, "_call_channel",
            lambda record, action: _async(ps.CHANNEL_ERROR))
        rec = _record()
        db = FakeSweepDB([rec])
        for _ in range(ps.MAX_ATTEMPTS):
            asyncio.run(ps.sweep_pending(db))
        assert rec.status == "failed" and rec.attempts == ps.MAX_ATTEMPTS
        assert "人工" in rec.note


class Test分账回退如实记账:
    def test_从未分账的单直接了结(self, monkeypatch):
        """钱从没离开过平台侧,没有可回退的东西,写 returned 是如实记账。"""
        monkeypatch.setattr(ps, "get_client", lambda: None)
        rec = _record(status="pending")
        asyncio.run(ps.request_return(FakeSweepDB([rec]),
                                      SimpleNamespace(id=1)))
        assert rec.status == "returned" and "从未实际分账" in rec.note

    def test_已分账但回退调不通不许改状态(self, monkeypatch):
        """钱已经在商家账户。改成 returned 等于账面宣称钱回来了,
        而商家余额照样是多的 —— 保持 success 并吵一声,留给人工。"""
        monkeypatch.setattr(ps, "get_client", lambda: object())
        rec = _record(status="success")
        asyncio.run(ps.request_return(FakeSweepDB([rec]),
                                      SimpleNamespace(id=1)))
        assert rec.status == "success"
        assert "需人工" in rec.note


def _async(value):
    async def _coro():
        return value
    return _coro()
