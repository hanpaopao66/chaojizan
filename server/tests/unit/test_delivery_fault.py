"""配送异常裁决判谁的责任(services/delivery_fault.py)。

「到店未出餐」「餐品不齐」是商家那一环的问题:裁成退款判商家责任、商家承担退款,
扣商家的信用分、不扣骑手的。以前这两类也记成骑手责任 —— 骑手到店没拿到餐、拿到的餐不齐,
反倒算他的错。这类退化不报错,所以守着:

1. 判谁的责任只有一份,取值和骑手上报的种类(schemas 的 Literal)对得上;
2. 判商家责任时退多少:全款(含配送费和小费),商家这单净额冲回、骑手那份另出(services/merchant_fault);
3. 用到它的地方(裁决、申诉资格、信用分、出参)真的在用它,不各写一份。
"""
import inspect
from typing import get_args

import pytest

from app.services import delivery_fault as df


class Test判谁的责任:
    def test_两类交接异常是商家的(self):
        assert set(df.MERCHANT_KINDS) == {"not_ready", "items_missing"}
        for kind in df.MERCHANT_KINDS:
            assert df.refund_fault(kind) == "merchant", kind

    @pytest.mark.parametrize("kind", ["cannot_contact", "wrong_address", "food_damaged", "other"])
    def test_途中异常是骑手的(self, kind):
        assert df.refund_fault(kind) == "rider"

    def test_种类都是真的上报种类(self):
        """声称有的种类必须真的存在:对着骑手上报接口收的值。"""
        from app.schemas import DeliveryIssueIn
        allowed = set(get_args(DeliveryIssueIn.model_fields["kind"].annotation))
        assert set(df.MERCHANT_KINDS) <= allowed
        assert set(df.KIND_LABELS) == allowed, "有上报种类没有名字,推送里会露出英文"

    @pytest.mark.parametrize("kind,resolution,fault", [
        ("cannot_contact", "mark_delivered", "customer"),
        ("wrong_address", "mark_delivered", "customer"),
        ("food_damaged", "refund", "rider"),
        ("not_ready", "refund", "merchant"),
        ("items_missing", "refund", "merchant"),
        ("items_missing", "continue_delivery", ""),
        ("not_ready", "", ""),
    ])
    def test_裁决之后判的是谁(self, kind, resolution, fault):
        assert df.fault_of(kind, resolution) == fault

    def test_出参带着判谁(self):
        """后台、骑手端照着出参里的 fault / refund_fault 显示,不自己按 resolution 猜。"""
        from datetime import datetime, timezone

        from app.schemas import DeliveryIssueOut
        base = dict(id=1, order_no="x", rider_id=7, note="", photo_url="", status="resolved",
                    resolve_note="", created_at=datetime.now(timezone.utc), resolved_at=None)
        out = DeliveryIssueOut(**base, kind="not_ready", resolution="refund").model_dump()
        assert (out["fault"], out["refund_fault"]) == ("merchant", "merchant")
        out = DeliveryIssueOut(**base, kind="food_damaged", resolution="refund").model_dump()
        assert (out["fault"], out["refund_fault"]) == ("rider", "rider")
        out = DeliveryIssueOut(**base, kind="items_missing", resolution="").model_dump()
        assert (out["fault"], out["refund_fault"]) == ("", "merchant")


class Test判商家责任退多少:
    def test_退全款_商家另出骑手那份(self):
        """2026-09-15 定:判商家责任顾客拿回全款(含配送费和小费),钱由商家出 —— 不再在这里算「餐钱」"""
        assert not hasattr(df, "merchant_refund_cents"), "只退餐钱的老口径又回来了"
        from app.routers import admin
        src = inspect.getsource(admin.resolve_delivery_issue)
        assert "merchant_fault_refund_cents(db, order)" in src
        assert "merchant_fault_svc.apply(" in src, "判商家责任却没冲这单净额、没让商家另出骑手那份"


class Test真的在用它:
    """判谁的责任只有 delivery_fault 这一份 —— 用到的地方各写一份的话,迟早对不上。"""

    def test_裁决按它分支_商家责任冲净额(self):
        from app.routers import admin
        src = inspect.getsource(admin.resolve_delivery_issue)
        assert "delivery_fault.refund_fault(issue.kind)" in src
        assert "merchant_fault_svc.apply(" in src, "判商家责任却没冲这单的净额 —— 钱还是平台出的"

    def test_骑手申诉资格按它挡(self):
        from app.routers import appeals
        assert "refund_fault(issue.kind)" in inspect.getsource(appeals._validate_target)

    def test_信用分按它分两边(self):
        from app.services import credit
        assert "notin_(MERCHANT_KINDS)" in inspect.getsource(credit._delivery_query), \
            "骑手的扣分项没把到店未出餐、餐品不齐剔掉"
        assert "in_(MERCHANT_KINDS)" in inspect.getsource(credit._after_sale_query), \
            "商家的扣分项没接上判商家责任的那条配送异常"
        assert "in_(MERCHANT_KINDS)" in inspect.getsource(credit._order_rows), \
            "判商家责任提前结束的那一单还算商家完成一单"

    def test_公示写明了(self):
        from app.services import credit
        m = {x["key"]: x for x in credit.public_spec("merchant")["minus"]}
        assert "到店未出餐" in m[credit.KIND_AFTER_SALE]["counts"]
        r = credit.public_spec("rider")
        assert "不算你的" in {x["key"]: x for x in r["minus"]}[credit.KIND_DELIVERY]["counts"]
        assert any("到店未出餐" in x["what"] for x in r["not_counted"])
        assert any("到店未出餐" in line for line in credit.rules_lines("merchant"))
