"""平台数据看板验证:字段完整、口径与待办列表一致、权限"""
from tests.util import call, login

admin = login("13800000000")
customer = login("13800000001")

# 非管理员 403
err = call("GET", "/admin/dashboard", customer, expect_error=True)
assert err["_error"] == 403
print("✓ 非管理员不能看数据看板(403)")

d = call("GET", "/admin/dashboard", admin)

# 字段完整性
for key in ("orders", "gmv_cents", "commission_cents",
            "active_merchants", "active_riders", "new_users"):
    assert isinstance(d["today"][key], int), key
assert isinstance(d["trend_7d"], list)
for row in d["trend_7d"]:
    assert set(row) == {"day", "orders", "gmv"}
print(f"✓ 今日指标完整:{d['today']['orders']} 单 / GMV ¥{d['today']['gmv_cents']/100:.2f}")
print(f"✓ 7 日趋势 {len(d['trend_7d'])} 天数据")

# 累计规模:种子数据保底
assert d["totals"]["merchants"] >= 4  # 张记 + 3 家演示店
assert d["totals"]["riders"] >= 2
assert d["totals"]["orders"] > 100  # 演示订单 + 历次测试
print(f"✓ 累计:用户 {d['totals']['users']} / 商家 {d['totals']['merchants']} / "
      f"骑手 {d['totals']['riders']} / 订单 {d['totals']['orders']}")

# 待办口径必须和各审核列表一致(同一套数据,不许两套账)
pending_merchants = call("GET", "/admin/merchants?status=pending", admin)
assert d["pending"]["merchants"] == len(pending_merchants)
pending_riders = call("GET", "/admin/rider-profiles?status=pending", admin)
assert d["pending"]["riders"] == len(pending_riders)
pending_wd = call("GET", "/admin/withdrawals?status=pending", admin)
assert d["pending"]["withdrawals"] == len(pending_wd)
print(f"✓ 待办口径与列表一致:商家 {d['pending']['merchants']} / "
      f"骑手 {d['pending']['riders']} / 提现 {d['pending']['withdrawals']} / "
      f"售后 {d['pending']['after_sales']}")

print("\n平台数据看板验证通过 🎉")
