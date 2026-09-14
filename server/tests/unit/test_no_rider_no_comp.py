"""没人接单被取消的餐损不再赔(2026-09-15 定),出餐前提醒商家。

1. 无人接单兜底取消:顾客全额退款,**不再给已出餐的商家记赔付入账**(原来平台按应收全额赔、
   佣金不收 —— 平台没有钱);
2. 推送照实说:提醒线告诉商家「还没出餐的话,建议骑手接单后再出餐,或改为自己配送」,
   取消时说餐损不赔;
3. 商家端(安卓 App、鸿蒙、网页工作台)在「已接单、平台配送、还没骑手」的单上提醒同一句话;
4. 规则页、判责公示、透明中心照实写;之前赔出去的历史行,核账和透明中心照认。

这类退化不报错(平台悄悄又开始赔),一半按源码守,行为由 e2e_no_rider 核。
"""
import asyncio
import inspect
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HINT = "建议骑手接单后再出餐,或改为自己配送"


def _code(fn) -> str:
    """只看代码不看注释和文档串"""
    src = inspect.getsource(fn)
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    return "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())


class Test取消不赔:
    def test_兜底取消不写商家入账(self):
        from app.services import auto_flow
        code = _code(auto_flow._sweep_no_rider)
        assert "MerchantEarning(" not in code and "NO_RIDER_COMP_NOTE" not in code, \
            "无人接单取消又开始给商家记赔付(平台出钱)"
        assert "request_refund(" in code, "顾客照旧全额退款"
        assert "release_coupon(" in code, "抵扣过的券照旧放回券包"

    def test_历史赔付行核账照认(self):
        """之前赔出去的行还在库里:规则 12 认得出它是历史合规赔付,透明中心照算"""
        from app.routers import transparency
        from app.services import audit
        assert "note.startswith(NO_RIDER_COMP_NOTE)" in inspect.getsource(audit.run_audit)
        assert audit.NO_RIDER_COMP_NOTE in inspect.getsource(transparency.funds_public)


class Test提醒商家:
    def test_推送说餐损不赔和怎么避免(self):
        from app.services import auto_flow
        assert HINT in auto_flow.NO_RIDER_COOK_HINT
        src = inspect.getsource(auto_flow._notify_no_rider)
        assert "NO_RIDER_COOK_HINT" in src and "餐损平台不赔" in src
        assert "平台赔付" not in src

    def test_三个商家端都提醒同一句(self):
        for rel in ("apps/merchant_app/lib/merchant_ui.dart",
                    "apps/merchant_app_harmony/entry/src/main/ets/pages/OrdersPage.ets",
                    "apps/merchant_app_harmony/entry/src/main/ets/pages/OrderDetailPage.ets",
                    "merchant-web/src/api.ts"):
            text = (REPO / rel).read_text(encoding="utf-8")
            assert "还没有骑手接单:" + HINT in text, rel
        web = (REPO / "merchant-web/src/pages/food/FoodOrdersPage.tsx").read_text(encoding="utf-8")
        assert "showNoRiderCookHint(order)" in web and "NO_RIDER_COOK_HINT" in web
        api = (REPO / "merchant-web/src/api.ts").read_text(encoding="utf-8")
        cond = api.split("export function showNoRiderCookHint")[1].split("}")[0]
        for part in ("'accepted'", "!o.pickup", "!o.self_delivery", "o.rider_id == null",
                     "!o.parent_order_no"):
            assert part in cond, part


class Test公示照实说:
    def test_规则页商家那一节(self):
        from app.services import rules
        r = asyncio.run(rules.rules_for("merchant", object()))
        sec = next(s for s in r["sections"] if s["title"] == "还没有骑手接单的单")
        blob = "".join(sec["items"])
        assert "餐损平台不赔" in blob and HINT in blob and "全额退款" in blob, blob

    def test_商家规则中心同一份(self):
        from app.routers import merchants
        assert "_no_rider_rules_section()" in inspect.getsource(merchants.my_rules)

    def test_判责公示不再说平台赔商家餐损(self):
        from app.services import liability
        bears = liability.public_spec()["what_platform_bears"]
        blob = "".join(bears["examples"]) + bears["rule"]
        assert "已出餐的餐损平台不赔" in blob and "平台判错了,平台自己认" in bears["rule"], blob
        assert "由平台按应收全额赔" not in blob

    def test_各端不再说无人接单平台赔餐损(self):
        stale = ["已出餐部分平台赔付", "平台按应收赔付餐损", "商家由平台按应收全额赔",
                 "替商家兜餐损", "无人接单,平台背锅"]
        hits = []
        for d in ("server/app", "apps/merchant_app/lib", "apps/user_app/lib",
                  "apps/rider_app/lib", "packages/shared/lib", "web/src", "admin-web/src",
                  "merchant-web/src"):
            for p in (REPO / d).rglob("*"):
                if p.suffix not in {".py", ".dart", ".jsx", ".tsx", ".ts"} \
                        or "node_modules" in p.parts:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
                hits += [f"{p.relative_to(REPO)}: {s}" for s in stale if s in text]
        assert not hits, "\n".join(hits)
