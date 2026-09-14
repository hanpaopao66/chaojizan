"""平台出钱的安抚和营销全部停掉(2026-09-14 拍板「平台没有钱」)。

1. 送达超时:默认只致歉不发券;晚了多少按送达那一刻算,不按现在;
2. 平台券:平台批次一张不发,后台建批次、定向发券 410,平台批次不能再启用;
3. 邀请有礼:填码 410,结算不再发奖励,商家不能再建新客推荐券批次;
4. 地址难度反馈:不当场补钱(不写调整入账),规则写明以后的单顾客付;
5. 首单立减保持 0;
6. 说法:各端不再说「超时自动赔安抚券」「这一单当场补钱(平台出)」「邀请好友各得券」。

这类退化不报错(平台悄悄又开始出钱),一半按行为测,一半按源码守;e2e 在
e2e_eta_apology / e2e_coupon_ops / e2e_referral* / e2e_hardship_no_pay。
"""
import asyncio
import inspect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import Settings

REPO = Path(__file__).resolve().parents[3]


class _FakeDB:
    """compensate_if_late 用到的那几个方法:查询一律「没有」,写入记下来。"""

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
    def test_默认关(self):
        assert Settings().eta_compensation_enabled is False

    def test_超时了只记一条致歉_一张券都不发(self, quiet_eta):
        from app.models import Coupon, OrderEvent
        from app.services import eta
        db = _FakeDB()
        assert asyncio.run(eta.compensate_if_late(db, _order())) is True
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
        assert asyncio.run(eta.compensate_if_late(db, order)) is False
        assert db.added == [] and quiet_eta == []

    def test_豁免的单不回滚(self, quiet_eta, monkeypatch):
        """送达接口紧接着要拿这单推实时消息。rollback 会让会话里的 order 过期,
        异步里一碰就是 MissingGreenlet —— 改过地址的超时单送达直接 500(e2e 撞过)。"""
        from app.services import eta

        async def _in_weather(db, at):
            return True

        monkeypatch.setattr(eta, "_weather_exempt", _in_weather)
        db = _FakeDB()
        assert asyncio.run(eta.compensate_if_late(db, _order())) is False
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

    def test_首单立减保持0(self):
        assert Settings().first_order_discount_cents == 0


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
