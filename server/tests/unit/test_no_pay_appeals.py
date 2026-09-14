"""改判、跑腿售后、食安投诉:平台不出钱(2026-09-14 拍板「平台没有钱」)。

1. 商家售后判责改判成立:只撤销判责和信用分那一条,**不补回被冲的净额**(不再写 adjustment 行,
   判责方记 cleared 而不是 platform —— 平台这一单一分没出);
2. 跑腿单的售后:平台不再「同意 = 认赔」,是骑手的问题判骑手责任、不是就驳回;
   「售后被拒」改判成立判的也是骑手责任;
3. 食安投诉成立:商家承担餐费退款(冲这单净额)、记商家责任、扣店主信用分、商家可以申诉;
4. 公示照实说:规则页、信用分公示、判责公示不再说「改判的钱平台认亏」「被冲的净额补回来」
   「先行赔付由平台垫付」。

这类退化不报错(平台悄悄又开始出钱),一半按源码守,行为由 e2e_appeal / e2e_errand_aftersale /
e2e_food_safety 核。
"""
import asyncio
import inspect
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _code(fn) -> str:
    """只看代码不看注释和文档串:把「原来是平台认亏」写清楚的注释不该让测试判违规。"""
    src = inspect.getsource(fn)
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    return "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())


class Test商家改判不补钱:
    def test_不写调整行_判责记cleared(self):
        from app.models import AFTER_SALE_FAULT_CLEARED
        from app.routers import appeals
        code = _code(appeals._overturn)
        after_sale_branch = code.split('elif appeal.target_type == "after_sale_rider"')[0]
        assert "MerchantEarning(" not in after_sale_branch and "adjustment" not in after_sale_branch, \
            "商家售后判责改判又开始补净额(平台出钱)"
        assert "AFTER_SALE_FAULT_CLEARED" in after_sale_branch
        assert AFTER_SALE_FAULT_CLEARED not in ("platform", "merchant", "rider", "")

    def test_没有任何代码路径再写正向调整行(self):
        """adjustment 行 = 平台认亏补的钱。商家改判、难度反馈停了之后,不该再有代码写它。"""
        hits = []
        for p in (REPO / "server/app").rglob("*.py"):
            if p.name in ("models.py", "tax.py"):
                continue  # 定义和报税科目表
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                code = ln.split("#", 1)[0]
                if "kind=EarningKind.adjustment" in code.replace(" ", ""):
                    hits.append(f"{p.relative_to(REPO)}:{i}")
        assert not hits, f"又有代码在写平台认亏的调整行:{hits}"

    def test_只有判商家责任的售后能申诉(self):
        from app.routers import appeals
        src = inspect.getsource(appeals._validate_target)
        assert 'a.fault != "merchant"' in src


class Test跑腿售后不认赔:
    def test_平台同意跑腿售后是409(self):
        from app.routers import after_sales
        code = _code(after_sales.accept_after_sale)
        assert "is_errand(order)" in code and "409" in code
        assert '"platform"' not in code, "跑腿售后又记成平台认赔"

    def test_售后被拒改判_跑腿单判骑手责任(self):
        from app.routers import appeals
        code = _code(appeals._overturn)
        assert "_overturn_errand_rejected(" in code
        assert "AfterSaleStatus.rejected" in code, "被拒之后按别的路径处理过的,再改判一次就是退第二遍"


class Test食安投诉商家承担:
    def test_冲商家净额_判商家责任(self):
        from app.routers import admin
        code = _code(admin.confirm_food_safety)
        assert "reverse_merchant_earning(" in code
        assert 'fault="merchant"' in code and 'fault="platform"' not in code
        assert "merchant_refund_cents(" in code, "退多少和配送异常判商家责任同一个口径(不含配送费、小费)"
        assert "is_errand(order)" in code
        assert "settle_order(" in code, "还没确认收货的单先结算再冲,不然之后入账就成了平台出的钱"

    def test_店主信用分算这一条(self):
        from app.services import credit
        src = inspect.getsource(credit._after_sale_query)
        assert "FoodSafetyReport" in src and 'Violation.kind == "food_safety"' in src
        assert credit.FORMULA_VERSION >= 5, "扣分口径变了,缓存键版本要跟着升"
        m = {x["key"]: x for x in credit.public_spec("merchant")["minus"]}
        assert "食品安全" in m[credit.KIND_AFTER_SALE]["counts"]
        assert not any("食安" in x["what"] for x in credit.public_spec("merchant")["not_counted"])

    def test_自动停业不算改判成立的那几起(self):
        from app.routers import admin
        assert "AFTER_SALE_FAULT_CLEARED" in inspect.getsource(admin.confirm_food_safety)


class Test公示照实说:
    def test_申诉那一节(self):
        from app.services import rules
        r = asyncio.run(rules.rules_for("merchant", object()))
        items = "".join(next(s for s in r["sections"] if s["title"] == "申诉")["items"])
        assert "不补回" in items and "平台承担" not in items, items

    def test_信用分申诉框(self):
        from app.services import credit
        text = credit._ORIGINAL_AFTER[("merchant", credit.KIND_AFTER_SALE)]
        assert "不补回" in text and "补回来" not in text, text

    def test_判责公示(self):
        from app.services import liability
        what = liability.public_spec()["appeal"]["what_happens"]
        assert "平台认亏" not in what and "不补回" in what, what

    def test_各端不再说改判平台认亏_食安平台垫付(self):
        stale = ["改判的钱平台认亏", "被冲的净额补回来", "被冲掉的那笔净额补回来",
                 "先行赔付由平台垫付", "售后恢复你的净额", "平台先行全额退款",
                 "改判产生的钱由平台承担"]
        hits = []
        for d in ("server/app", "apps/merchant_app/lib", "apps/user_app/lib",
                  "apps/rider_app/lib", "packages/shared/lib", "web/src", "admin-web/src"):
            for p in (REPO / d).rglob("*"):
                if p.suffix not in {".py", ".dart", ".jsx", ".tsx", ".ts"} \
                        or "node_modules" in p.parts:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
                hits += [f"{p.relative_to(REPO)}: {s}" for s in stale if s in text]
        assert not hits, "\n".join(hits)
