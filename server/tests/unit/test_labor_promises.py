"""透明中心公开的劳动保护承诺(labor_guard.LABOR_PROMISES),代码里得真是这样。

这几条写在 /transparency/dispatch 上给骑手看,改代码时最容易悄悄违背,而且不报错:
- 「预计送达时间只会因路况、天气变宽,不会因为你跑得快而变紧」:动态重估以前偏差满 5 分钟就双向改写,
  骑手接单快、出餐快时时限会往前收,而刷新后的 eta_at 是超时赔付的新基准;
- 「恶劣天气加价的同时一定放宽时限」:加价一直在收,放宽用的 severe_weather 生产代码却从没传过。
"""
import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import eta as eta_mod
from app.services import labor_guard, payment_core
from app.state_machine import OrderStatus

SHOP = SimpleNamespace(lat=34.34, lng=108.94)


def _order(eta_in_minutes: float, status=OrderStatus.PICKED_UP, lat=34.35, lng=108.95):
    return SimpleNamespace(
        pickup=False, parent_order_no="", scheduled_at=None, status=status,
        eta_at=datetime.now(timezone.utc) + timedelta(minutes=eta_in_minutes),
        lat=lat, lng=lng, customer_id=1, order_no="SZTEST000001")


def test_承诺原文还在():
    text_ = "".join(labor_guard.LABOR_PROMISES)
    assert "不会因为你跑得快而变紧" in text_ and "放宽时限" in text_


def test_跑得快不会让时限变紧():
    o = _order(40)
    before = o.eta_at
    # 骑手已经取餐、就在收货点旁边:重估只剩一两分钟,比原来的承诺早了半个多小时
    changed = asyncio.run(eta_mod.recompute_eta(None, o, SHOP, rider_pos=(o.lat, o.lng)))
    assert changed is False
    assert o.eta_at == before, "重估更早时必须照旧用原来的时限"


def test_真堵了照样往后放宽(monkeypatch):
    pushed = []

    async def fake_push(*args, **kwargs):
        pushed.append(args)

    monkeypatch.setattr("app.services.push.push_to_user", fake_push)
    o = _order(1)
    before = o.eta_at
    # 骑手还在 20 多公里外:原来说 1 分钟后到已经不可能了
    changed = asyncio.run(eta_mod.recompute_eta(None, o, SHOP, rider_pos=(34.55, 109.15)))
    assert changed and o.eta_at > before
    assert pushed, "延后要告诉顾客"


def test_恶劣天气时限更宽():
    far = SimpleNamespace(pickup=False, parent_order_no="", scheduled_at=None,
                          lat=34.42, lng=109.03, floor=None, has_elevator=None)
    normal = eta_mod.compute_eta(far, SHOP)
    severe = eta_mod.compute_eta(far, SHOP, severe_weather=True)
    assert severe > normal


def test_收了恶劣天气加价的单按恶劣天气算时限():
    """下单那条路径(payment_core)和结算页预估都得按这一单有没有收天气加价来放宽。"""
    src = inspect.getsource(payment_core.mark_order_paid)
    assert "severe_weather=" in src and '"weather"' in src, (
        "支付时算 ETA 没按天气放宽 —— 加价在收、时限不放宽,正是公开承诺里说的「用钱买你冒险」")
    from app.routers import orders
    preview = inspect.getsource(orders.preview_delivery_fee)
    assert "severe_weather=" in preview, "结算页预估和下单后的 ETA 又要对不上了"
