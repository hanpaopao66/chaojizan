"""平台出钱的安抚和营销全部停掉(2026-09-14 拍板「平台没有钱」)。

1. 送达超时:只致歉不发券,开关和发券代码 2026-09-15 删了(拨不回来);晚了多少按送达那一刻算;
2. 平台券:平台批次一张不发,后台建批次、定向发券 410,平台批次不能再启用;
3. 邀请有礼:填码 410,结算不再发奖励,商家不能再建新客推荐券批次;
4. 地址难度反馈:不当场补钱(不写调整入账),规则写明以后的单顾客付;
5. 首单立减:开关和下单那段代码 2026-09-15 删了(拨不回来),下单时的平台补贴只可能来自
   已经发到用户手里的平台券;历史订单上的平台补贴照旧认;
6. 说法:各端不再说「超时自动赔安抚券」「这一单当场补钱(平台出)」「邀请好友各得券」「首单立减现在是 0」。

这类退化不报错(平台悄悄又开始出钱),一半按行为测,一半按源码守;e2e 在
e2e_eta_apology / e2e_coupon_ops / e2e_referral* / e2e_hardship_no_pay。
"""
import ast
import asyncio
import inspect
import re
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import Settings

REPO = Path(__file__).resolve().parents[3]


class _FakeDB:
    """apologize_if_late 用到的那几个方法:查询一律「没有」,写入记下来。"""

    def __init__(self):
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, *a, **k):
        return None

    async def scalar(self, *a, **k):
        return None

    async def scalars(self, *a, **k):
        return []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _order(**kw):
    now = datetime.now(timezone.utc)
    base = dict(id=1, order_no="T" * 20, customer_id=9, pickup=False, parent_order_no="",
                total_cents=3000, ready_late=False, status=SimpleNamespace(value="delivered"),
                eta_at=now - timedelta(minutes=30), delivered_at=now)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def quiet_eta(monkeypatch):
    """不碰 Redis、不真推送:天气窗口当成不在,推送记下来。"""
    from app.services import eta, push
    pushed = []

    async def _no_weather(db, at):
        return False

    async def _push(uid, title, content, extras=None, record_skip=False):
        pushed.append((title, content))
        return True

    monkeypatch.setattr(eta, "_weather_exempt", _no_weather)
    monkeypatch.setattr(push, "push_to_user", _push)
    return pushed


class Test送达超时只致歉:
    def test_开关和发券代码都删了_拨不回来(self):
        """跟等餐补偿一样:停了就不留一个能拨回来的开关(2026-09-15 定)"""
        from app.services import eta
        assert not hasattr(Settings(), "eta_compensation_enabled")
        assert not hasattr(eta, "compensate_if_late")
        for gone in ("COMP_AMOUNT_CENTS", "COMP_VALID_DAYS"):
            assert not hasattr(eta, gone), gone
        src = inspect.getsource(eta.apologize_if_late)
        code = "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())
        assert "Coupon(" not in code and "settings." not in code, "超时又能发券了"

    def test_停发之前的平台券照旧能抵扣(self):
        """发券删了,抵扣那一支不能跟着删:平台券(funder 不是 merchant)照旧走 subsidy"""
        from app.routers import orders
        src = inspect.getsource(orders.create_order)
        assert 'coupon.funder == "merchant"' in src and "subsidy += coupon_off" in src
        assert orders._coupon_label("eta:T123") == "超时安抚券"

    def test_超时了只记一条致歉_一张券都不发(self, quiet_eta):
        from app.models import Coupon, OrderEvent
        from app.services import eta
        db = _FakeDB()
        assert asyncio.run(eta.apologize_if_late(db, _order())) is True
        events = [o for o in db.added if isinstance(o, OrderEvent)]
        assert [e.to_status for e in events] == [eta.APOLOGY_EVENT], db.added
        assert not [o for o in db.added if isinstance(o, Coupon)], "超时了还在发券"
        assert "归因" in events[0].note and "不发券" in events[0].note
        (title, content), = quiet_eta
        assert "抱歉" in title and "券" not in content, content

    def test_晚了多少按送达那一刻算(self, quiet_eta):
        """准时送到、顾客迟迟不确认:现在早过了 ETA,但送达那一刻没晚 —— 不算超时。"""
        from app.services import eta
        now = datetime.now(timezone.utc)
        db = _FakeDB()
        order = _order(eta_at=now - timedelta(minutes=50),
                       delivered_at=now - timedelta(minutes=60))
        assert asyncio.run(eta.apologize_if_late(db, order)) is False
        assert db.added == [] and quiet_eta == []

    def test_豁免的单不回滚(self, quiet_eta, monkeypatch):
        """送达接口紧接着要拿这单推实时消息。rollback 会让会话里的 order 过期,
        异步里一碰就是 MissingGreenlet —— 改过地址的超时单送达直接 500(e2e 撞过)。"""
        from app.services import eta

        async def _in_weather(db, at):
            return True

        monkeypatch.setattr(eta, "_weather_exempt", _in_weather)
        db = _FakeDB()
        assert asyncio.run(eta.apologize_if_late(db, _order())) is False
        assert db.added == [] and db.committed and not db.rolled_back

    def test_兜底清扫只扫送达那一刻就晚了的单(self):
        from app.services import auto_flow
        src = inspect.getsource(auto_flow)
        assert re.search(r"Order\.delivered_at\s*>\s*Order\.eta_at \+ timedelta\(", src), \
            "兜底清扫按「现在」扫,会把准时送到、还没确认的单当成超时"
        assert "APOLOGY_EVENT" in src


class Test平台券停发:
    def test_平台批次一张不发(self):
        from app.services.coupons import issue_from_batch
        batch = SimpleNamespace(active=True, merchant_id=None, id=1)
        # db=None:平台批次在碰库之前就该被挡下来
        assert asyncio.run(issue_from_batch(None, batch, 1)) is None

    @pytest.mark.parametrize("fn", ["create_coupon_batch", "issue_coupon_directed"])
    def test_后台建批次和定向发券都是410(self, fn):
        from app.routers import admin
        with pytest.raises(HTTPException) as e:
            asyncio.run(getattr(admin, fn)({}, admin=None, db=None))
        assert e.value.status_code == 410

    def test_平台批次只能停不能开(self):
        from app.routers import admin
        src = inspect.getsource(admin.toggle_coupon_batch)
        assert "batch.merchant_id is None" in src and "410" in src


def _strip_comments(src: str) -> str:
    """只看代码:去掉文档串和 # 注释(讲历史的注释不该让测试判违规)"""
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    return "\n".join(ln.split("#", 1)[0] for ln in src.splitlines())


def _names(target) -> list[str]:
    """赋值目标里的变量名(a / a, b / *a 都算)"""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [n for t in target.elts for n in _names(t)]
    if isinstance(target, ast.Starred):
        return _names(target.value)
    return []


def _writes(tree, name: str) -> list[tuple[ast.AST, list[ast.AST]]]:
    """给变量 name 赋值的每一处:(赋值节点, 从外到里的祖先链)"""
    out = []

    def walk(node, parents):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Assign):
                targets = child.targets
            elif isinstance(child, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
                targets = [child.target]
            elif isinstance(child, (ast.For, ast.AsyncFor, ast.comprehension)):
                targets = [child.target]
            else:
                targets = []
            if any(name in _names(t) for t in targets):
                out.append((child, parents + [node]))
            walk(child, parents + [node])

    walk(tree, [])
    return out


def _in_branch(node, if_node: ast.If, *, orelse: bool) -> bool:
    """node 在 if_node 的 if 分支(orelse=False)或 else 分支(orelse=True)里"""
    return any(node is n for stmt in (if_node.orelse if orelse else if_node.body)
               for n in ast.walk(stmt))


class Test首单立减删了:
    """2026-09-15 定:平台首单立减(平台出钱)跟超时安抚券一样,开关和下单那段代码一起删了,拨不回来。
    停发之前发出去的平台券照旧能抵扣(走 subsidy);历史订单上的 subsidy_cents(以前的首单立减、平台券)
    核账、公开账本、退款口径照旧认。"""

    def test_开关删了_拨不回来(self):
        assert not hasattr(Settings(), "first_order_discount_cents")
        code = _strip_comments((REPO / "server/app/config.py").read_text(encoding="utf-8"))
        assert "first_order" not in code, "首单立减的开关又加回来了"

    def test_下单那段代码删了(self):
        from app.routers import orders
        code = _strip_comments(inspect.getsource(orders.create_order))
        for gone in ("首单", "first_order", "has_paid"):
            assert gone not in code, f"下单时又在判首单({gone})"

    def test_下单时平台补贴只来自已经发到用户手里的平台券(self):
        """create_order 里给 subsidy 赋值的只许三处:起始 0、平台券那一支加上券抵的钱、最后往下钳。
        再加一处(首单立减、新人红包……)就红 —— 平台出钱的口子不许从这里再开"""
        from app.routers import orders
        tree = ast.parse(textwrap.dedent(inspect.getsource(orders.create_order)))
        writes = _writes(tree, "subsidy")
        shapes = [ast.unparse(n) for n, _ in writes]
        assert len(writes) == 3, f"subsidy 的赋值多了或少了:{shapes}"
        (init, _), (add, add_parents), (clamp, _) = writes
        assert ast.unparse(init) == "subsidy = 0", shapes
        assert isinstance(add, ast.AugAssign) and isinstance(add.op, ast.Add) \
            and ast.unparse(add.value) == "coupon_off", shapes
        assert isinstance(clamp, ast.Assign) and ast.unparse(clamp.value).startswith(
            "min(subsidy, "), f"最后那一处只许往下钳:{shapes}"
        # 加的那一处:在「用了券」那一支里、在「不是店铺券」的 else 里
        ifs = [p for p in add_parents if isinstance(p, ast.If)]
        coupon_if = next((p for p in ifs if ast.unparse(p.test) == "payload.coupon_id"), None)
        assert coupon_if is not None and _in_branch(add, coupon_if, orelse=False), \
            "subsidy 只许在用了券的那一支里加"
        funder_if = next((p for p in ifs if ast.unparse(p.test) == "coupon.funder == 'merchant'"),
                         None)
        assert funder_if is not None and _in_branch(add, funder_if, orelse=True), \
            "subsidy 只许在平台券(不是店铺券)那一支里加"
        # 这张券是这个用户手里的、没用过、没过期的(发券停了,手里的券只可能是停发之前发的)
        branch = ast.unparse(coupon_if)
        for guard in ("db.get(Coupon, payload.coupon_id", "coupon.user_id != user.id",
                      "coupon.used_order_no", "expires < now_utc"):
            assert guard in branch, guard
        # 抵多少只看券面额和这单还能抵的钱
        offs = [ast.unparse(n) for n, _ in _writes(tree, "coupon_off")]
        assert offs == ["coupon_off = min(coupon.amount_cents, food_cents + packing - discount)"], \
            offs
        # 落库的就是它,别处不另写
        order_kw = [kw for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and ast.unparse(n.func) == "Order" for kw in n.keywords
                    if kw.arg == "subsidy_cents"]
        assert [ast.unparse(kw.value) for kw in order_kw] == ["subsidy"], order_kw
        assert ".subsidy_cents =" not in ast.unparse(tree), "下单时别处又改了订单上的平台补贴"

    def test_防薅首单立减的风控规则跟着删了(self):
        from app.services import risk
        code = _strip_comments(inspect.getsource(risk._assess))
        assert "subsidy" not in code, "新号拿不到平台补贴了,防薅补贴的那条规则不该还在"

    def test_历史订单上的平台补贴照旧认(self):
        from app.routers import transparency
        from app.services import audit, refund_calc
        assert "- Order.subsidy_cents" in inspect.getsource(audit.run_audit), \
            "核账规则 3:实付 = 菜 + 打包 − 满减 + 配送 + 小费 − 平台补贴"
        assert "sum(subsidy_cents)" in inspect.getsource(transparency.funds_public), \
            "透明中心「钱去哪了」照旧公示平台补贴"
        split = transparency.split_order_row({
            "total_cents": 2300, "food_cents": 2100, "packing_fee_cents": 0,
            "discount_cents": 0, "subsidy_cents": 300, "commission_cents": 105,
            "self_delivery": False, "pickup": False, "order_kind": "food"})
        assert split["platform"] == 105 - 300 and split["merchant"] == 1995, split

        class _DB:
            async def scalar(self, *a, **k):
                return 0

        o = SimpleNamespace(id=1, total_cents=2300, refund_cents=0, subsidy_cents=300,
                            rider_id=7, delivery_fee_cents=500, tip_cents=0)
        assert asyncio.run(refund_calc.merchant_fault_refund_cents(_DB(), o)) == 2300, \
            "退顾客实付的钱:平台券抵掉的那截不在实付里,不退现金"


class Test邀请有礼停了:
    def test_填码410(self):
        from app.routers import referrals
        with pytest.raises(HTTPException) as e:
            asyncio.run(referrals.claim_referral({"code": "123456"}, user=None))
        assert e.value.status_code == 410 and "停了" in e.value.detail

    def test_结算不再发奖励(self):
        from app.services import settlement
        src = inspect.getsource(settlement)
        assert "reward_referral" not in src and "referrals import" not in src

    def test_奖励配置删了_没有能拨回来的开关(self):
        s = Settings()
        assert not hasattr(s, "referral_reward_cents")
        assert not hasattr(s, "referral_monthly_cap")

    def test_商家不能再建新客推荐券批次(self):
        from app.routers import merchants
        src = inspect.getsource(merchants.create_shop_coupon_batch)
        assert 'payload.trigger == "referral"' in src and "410" in src


class Test难度反馈不当场补钱:
    def test_不写调整入账(self):
        from app.routers import orders
        src = inspect.getsource(orders.report_hardship)
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith(("#", "`")))
        assert "RiderEarning(" not in code and "EarningKind" not in code, \
            "反馈的这一单又开始当场补钱(平台出)"
        assert '"comp_cents": 0' in src and "comp_cents=0" in src

    def test_规则写明以后的单顾客付(self):
        from app.routers import orders
        r = asyncio.run(orders.hardship_rules(user=None))
        assert r["funder"] == "customer" and r["paid_now"] is False, r
        assert any("不当场补钱" in n for n in r["notes"]), r["notes"]
        assert not any("由平台出" in n for n in r["notes"]), r["notes"]


class Test规则页:
    def _money(self, audience):
        from app.services import rules
        r = asyncio.run(rules.rules_for(audience, object()))
        return next(s for s in r["sections"] if s["title"] == "钱")["items"]

    def test_顾客那一节说清楚超时只致歉(self):
        items = self._money("customer")
        assert any("致歉" in i and "照旧能用" in i for i in items), items

    def test_骑手那一节说清楚难度反馈不当场补钱(self):
        items = self._money("rider")
        assert any("不当场补钱" in i and "配送费" in i for i in items), items


#: 停了之后各端不许再出现的说法(界面文案,不含注释里讲历史的句子)
_STALE = [
    "平台自动赔安抚券",
    "超时安抚券由平台承担",
    "超时的安抚券由平台",
    "订单超时赔付由平台承担",
    "超时赔付、新客活动都会发到这里",
    "说了这一单当场补钱",
    "邀请好友完成首单,你俩各得券",
    "这笔钱由平台出,不向顾客或商家追收",
    # 首单立减 2026-09-15 连开关带代码删了:「现在是 0」的说法、下单备注里那一条都不许再出现
    "首单立减(现在是 0)",
    "首单立减，现在是 0",
    "首单立减-",
]
_SCAN = ["server/app", "apps/user_app/lib", "apps/rider_app/lib", "apps/merchant_app/lib",
         "packages/shared/lib", "web/src", "admin-web/src", "merchant-web/src"]


def test_各端不再说平台出钱的安抚和营销():
    hits = []
    for d in _SCAN:
        for p in (REPO / d).rglob("*"):
            if p.suffix not in {".py", ".dart", ".jsx", ".tsx", ".ts", ".js"} \
                    or "node_modules" in p.parts:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for phrase in _STALE:
                if phrase in text:
                    hits.append(f"{p.relative_to(REPO)}: {phrase}")
    assert not hits, "停了的平台出钱说法还在:\n" + "\n".join(hits)


def test_用户端没有邀请有礼入口():
    main = (REPO / "apps/user_app/lib/main.dart").read_text(encoding="utf-8")
    assert not re.search(r"label:\s*'邀请有礼'", main), "用户端「我的」里还有邀请有礼入口"
    assert not (REPO / "apps/user_app/lib/invite_page.dart").exists()
    api = (REPO / "packages/shared/lib/src/api_client.dart").read_text(encoding="utf-8")
    assert "/referrals/claim" not in api and "/referrals/me" not in api
