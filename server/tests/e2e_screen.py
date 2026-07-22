"""公开经营大屏(/screen/*)验证:无鉴权可读、脱敏、GMV 开关后端强制。

注意:stats 有 10s、订单流水有 5s 进程内缓存,开关切换后要等缓存过期再断言。
"""
import time

from tests.util import ADMIN, call, login

# ---- 无鉴权即可读,基本形状 ----
stats = call("GET", "/screen/stats")
reg = stats["registrations"]
for k in ("users", "merchants", "riders", "drivers"):
    assert reg[k]["total"] >= 0 and reg[k]["today"] >= 0
assert reg["drivers"]["coming"] is True  # 打车预留位
assert stats["orders"]["total"] > 0
assert len(stats["trend"]) == 7
assert len(stats["hourly"]["today"]) == 24 and len(stats["hourly"]["yesterday"]) == 24
assert {d["status"] for d in stats["status_dist"]} == {
    "paid", "accepted", "ready", "picked_up", "delivered", "completed"}
print(f"✓ /screen/stats 公开可读:累计 {stats['orders']['total']} 单,"
      f"用户 {reg['users']['total']} / 商家 {reg['merchants']['total']}"
      f" / 骑手 {reg['riders']['total']}")

# ---- 最新订单流水:手机号打码、订单号只露尾巴、坐标只到两位小数 ----
latest = call("GET", "/screen/orders/latest?limit=10")
assert latest["items"], "开发库应有订单流水"
for o in latest["items"]:
    assert "****" in o["phone"], f"手机号必须打码: {o['phone']}"
    assert len(o["order_no_tail"]) == 6
    assert round(o["lat"], 2) == o["lat"] and round(o["lng"], 2) == o["lng"]
    assert o["status"] not in ("pending_payment", "cancelled")
print(f"✓ 订单播报 {len(latest['items'])} 条,手机号打码/坐标城市级")

# ---- 运营拓展:覆盖 / 省钱账 / 环保 / 时效 ----
assert stats["coverage"]["cities"] >= 1
assert stats["coverage"]["merchants"] == stats["registrations"]["merchants"]["total"]
sav = stats["merchant_savings"]
assert sav is not None and sav["saved_cents"] >= 0 and sav["industry_rate"] == 0.20
assert stats["eco"]["no_tableware_orders"] >= 0
assert len(stats["delivery"]["duration_buckets"]) == 4
assert all(b >= 0 for b in stats["delivery"]["duration_buckets"])
ratio = stats["delivery"]["ready_late_ratio"]
assert ratio is None or 0 <= ratio <= 1
print(f"✓ 运营拓展:覆盖 {stats['coverage']['cities']} 城,为商家省下"
      f" {sav['saved_cents']} 分,环保单 {stats['eco']['no_tableware_orders']},"
      f" 时长分布 {stats['delivery']['duration_buckets']}")

# ---- GMV 开关:off 后所有金额字段后端直接不下发(不是前端隐藏) ----
admin = login(ADMIN)
assert call("GET", "/admin/flags", admin)["screen_show_gmv"] in ("on", "off")
call("POST", "/admin/flags/screen_show_gmv", admin, {"value": "off"})
time.sleep(11)  # 等 stats 缓存(10s)过期
s = call("GET", "/screen/stats")
o = call("GET", "/screen/orders/latest?limit=5")
assert s["show_gmv"] is False and s["orders"]["gmv_cents"] is None
assert s["orders"]["today_gmv_cents"] is None
assert s["merchant_savings"] is None, "开关 off 时省钱账(金额)也不下发"
assert all(c["gmv_cents"] is None for c in s["cities"])
assert all(t["gmv_cents"] is None for t in s["trend"])
assert all(i["amount_cents"] is None for i in o["items"])
print("✓ 开关 off:stats/城市/趋势/播报的金额字段全部不下发")

err = call("POST", "/admin/flags/screen_show_gmv", admin,
           {"value": "maybe"}, expect_error=True)
assert err["_error"] == 422
print("✓ 非法开关值被拒(422)")

call("POST", "/admin/flags/screen_show_gmv", admin, {"value": "on"})
time.sleep(11)
s = call("GET", "/screen/stats")
assert s["show_gmv"] is True and s["orders"]["gmv_cents"] is not None
print("✓ 开关 on:金额恢复下发")

print("\ne2e_screen 全部通过 ✅")
