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

# 待办口径必须和各审核列表一致(同一套数据,不许两套账)。
#
# ⚠️ **不能拿列表长度当计数。** 这几个列表接口都带 LIMIT(商家那条是 200),
# 而看板数的是全部 —— 待审商家一超过 200,`count == len(list)` 就必红,
# 报出来的是「口径不一致」,实际是列表被截断了。
# 实测撞到过:看板 208、列表 200。
#
# 改成断言**方向**:看板的数不能比列表少(列表是被截断的那一份),
# 而且列表没被截断时必须严格相等 —— 那才是「不许两套账」真正要守的。
def consistent(label: str, counted: int, rows: list, cap: int) -> None:
    assert counted >= len(rows), (
        f"{label}:看板报 {counted},而列表就有 {len(rows)} 条 —— "
        f"看板漏数了,两套账")
    if len(rows) < cap:          # 没到上限 = 列表是全量,必须严格相等
        assert counted == len(rows), (
            f"{label}:看板报 {counted},列表全量是 {len(rows)} 条,对不上")


consistent("待审商家", d["pending"]["merchants"],
           call("GET", "/admin/merchants?status=pending", admin), 200)
consistent("待审骑手", d["pending"]["riders"],
           call("GET", "/admin/rider-profiles?status=pending", admin), 200)
consistent("待打款提现", d["pending"]["withdrawals"],
           call("GET", "/admin/withdrawals?status=pending", admin), 200)
print(f"✓ 待办口径与列表一致:商家 {d['pending']['merchants']} / "
      f"骑手 {d['pending']['riders']} / 提现 {d['pending']['withdrawals']} / "
      f"售后 {d['pending']['after_sales']}")

print("\n平台数据看板验证通过 🎉")
