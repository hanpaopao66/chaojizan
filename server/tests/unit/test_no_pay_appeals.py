"""改判、跑腿售后、食安投诉(2026-09-14 拍板「平台没有钱」,2026-09-15 定「平台判错了,平台自己认」)。

1. 商家售后判责改判成立:撤销判责和信用分那一条,**冲回的净额和另出的骑手那份都补回,钱由平台出**
   (services/merchant_fault.undo:adjustment + fault_refund 两行;判责方记 platform)。
   2026-09-14 那一版「只撤判责、不补钱、判责方记 cleared」没上过线,推翻了;
2. 跑腿单的售后:平台不再「同意 = 认赔」,是骑手的问题判骑手责任、不是就驳回;
   「售后被拒」改判成立判的也是骑手责任;
3. 食安投诉成立:商家承担全额退款(冲这单净额、另出骑手那份)、记商家责任、扣店主信用分、商家可以申诉;
4. 公示照实说:规则页、信用分公示、判责公示写明改判时平台补回、「平台判错了,平台自己认」;
   不再说「被冲的净额不补回」「钱不动」「先行赔付由平台垫付」。

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


class Test商家改判平台补回:
    def test_补回净额和另出的那行_判责记platform(self):
        import app.models as models
        from app.routers import appeals
        code = _code(appeals._overturn)
        after_sale_branch = code.split('elif appeal.target_type == "after_sale_rider"')[0]
        assert "merchant_fault.undo(" in after_sale_branch, "商家售后判责改判成立却没补回钱"
        assert 'a.fault = "platform"' in after_sale_branch
        assert not hasattr(models, "AFTER_SALE_FAULT_CLEARED"), "「改判不补钱」的 cleared 又回来了"

    def test_只有改判补回写正向调整行(self):
        """adjustment 行 = 平台补给商家的钱。只许商家售后判责改判成立那一处写(merchant_fault.undo);
        难度反馈当场补钱停了,别处不许再写。"""
        hits = []
        for p in (REPO / "server/app").rglob("*.py"):
            if p.name in ("models.py", "tax.py"):
                continue  # 定义和报税科目表
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                code = ln.split("#", 1)[0]
                if "kind=EarningKind.adjustment" in code.replace(" ", ""):
                    hits.append(str(p.relative_to(REPO)))
        assert hits == ["server/app/services/merchant_fault.py"], hits

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
        # 冲净额、另出骑手那份、没确认收货的先结算,都在 merchant_fault.apply 里(和别的判商家责任同一个写法)
        assert "merchant_fault.apply(" in code
        assert 'fault="merchant"' in code and 'fault="platform"' not in code
        assert "merchant_fault_refund_cents(" in code, "退多少和别的判商家责任同一个口径(全款)"
        assert "is_errand(order)" in code

    def test_店主信用分算这一条(self):
        from app.services import credit
        src = inspect.getsource(credit._after_sale_query)
        assert "FoodSafetyReport" in src and 'Violation.kind == "food_safety"' in src
        assert credit.FORMULA_VERSION >= 5, "扣分口径变了,缓存键版本要跟着升"
        m = {x["key"]: x for x in credit.public_spec("merchant")["minus"]}
        assert "食品安全" in m[credit.KIND_AFTER_SALE]["counts"]
        assert not any("食安" in x["what"] for x in credit.public_spec("merchant")["not_counted"])

    def test_自动停业不算改判成立的那几起(self):
        """按申诉记录认,不按判责方认:判责方 platform 里还有历史上「食安平台垫付」成立的单,那些照算"""
        from app.routers import admin
        src = inspect.getsource(admin.confirm_food_safety)
        assert 'Appeal.target_type == "after_sale"' in src and 'Appeal.status == "overturned"' in src
        assert 'AfterSale.fault == "platform"' not in src


class Test公示照实说:
    def test_申诉那一节(self):
        from app.services import rules
        r = asyncio.run(rules.rules_for("merchant", object()))
        items = "".join(next(s for s in r["sections"] if s["title"] == "申诉")["items"])
        assert "平台判错了,平台自己认" in items and "补回" in items, items
        assert "不补回" not in items, items

    def test_信用分申诉框(self):
        from app.services import credit
        text = credit._ORIGINAL_AFTER[("merchant", credit.KIND_AFTER_SALE)]
        assert "补回" in text and "不补回" not in text and "平台出" in text, text

    def test_判责公示(self):
        from app.services import liability
        what = liability.public_spec()["appeal"]["what_happens"]
        assert "平台判错了,平台自己认" in what and "不补回" not in what, what

    def test_顾客端取消分摊的申诉框照实说(self):
        """顾客对取消分摊申诉,改判的话他承担的那部分由平台原路退回(appeals 的 cancel_split 那一支)"""
        main = (REPO / "apps/user_app/lib/main.dart").read_text(encoding="utf-8")
        note = main.split("Future<void> _appealSplit(", 1)[1].split("if (reason == null)", 1)[0]
        assert "平台判错了,平台自己认" in note and "由平台原路退回" in note, note

    def test_商家端申诉框说售后恢复你的净额(self):
        """用户拍板:商家端申诉框「售后恢复你的净额」在新口径下是对的,保留(安卓、鸿蒙都说)"""
        for rel in ("apps/merchant_app/lib/appeal_page.dart",
                    "apps/merchant_app_harmony/entry/src/main/ets/pages/SupportPages.ets"):
            text = (REPO / rel).read_text(encoding="utf-8")
            assert "售后恢复你的净额" in text, rel

    def test_各端不再说改判平台认亏_食安平台垫付(self):
        stale = ["改判的钱平台认亏", "先行赔付由平台垫付", "平台先行全额退款",
                 "改判产生的钱由平台承担", "被冲的净额不补回", "被冲掉的净额不补回",
                 "被冲掉的那笔净额不补回", "判责撤销、钱不动", "商家无责(钱不动)",
                 "平台认赔(历史)",
                 # 2026-09-15 之后还剩的几句(顾客端取消分摊申诉框、鸿蒙商家端注释、共享包文档)
                 "改判的话由平台承担", "平台认亏,不追用户款", "只撤销判责、不补回净额"]
        hits = []
        for d in ("server/app", "apps/merchant_app/lib", "apps/user_app/lib",
                  "apps/rider_app/lib", "packages/shared/lib", "web/src", "admin-web/src",
                  "merchant-web/src", "apps/merchant_app_harmony/entry/src/main/ets",
                  "apps/user_app_harmony/entry/src/main/ets"):
            for p in (REPO / d).rglob("*"):
                if p.suffix not in {".py", ".dart", ".jsx", ".tsx", ".ts", ".ets"} \
                        or "node_modules" in p.parts:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
                hits += [f"{p.relative_to(REPO)}: {s}" for s in stale if s in text]
        assert not hits, "\n".join(hits)
