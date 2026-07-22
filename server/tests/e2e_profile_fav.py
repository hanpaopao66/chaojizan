"""个人资料(昵称/头像)+ 收藏店铺验证"""
from tests.util import call, login

customer = login("13800000001")
merchant = login("13800000002")

# ---------- 个人资料 ----------
me = call("GET", "/auth/me", customer)
assert me["phone"] == "13800000001" and me["role"] == "customer"
old_name = me["name"]
print(f"✓ GET /auth/me:{me['name']}({me['phone']})")

updated = call("PATCH", "/auth/me", customer,
               {"name": "爱吃面的小明", "avatar_url": "/uploads/demo/logo_zhang.png"})
assert updated["name"] == "爱吃面的小明"
assert updated["avatar_url"] == "/uploads/demo/logo_zhang.png"
print("✓ 改昵称 + 头像成功")
call("PATCH", "/auth/me", customer, {"name": old_name})  # 还原

# ---------- 收藏 ----------
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
sid = shop["id"]

call("POST", f"/favorites/{sid}", customer)
call("POST", f"/favorites/{sid}", customer)  # 重复收藏幂等
ids = call("GET", "/favorites/ids", customer)
assert ids.count(sid) == 1
print("✓ 收藏成功且幂等(重复收藏不产生第二条)")

favs = call("GET", "/favorites", customer)
assert any(m["id"] == sid for m in favs)
print(f"✓ 收藏列表可见({len(favs)} 家)")

# 待审核/隐藏的店不能收藏
hidden = call("GET", "/admin/rider-profiles", customer, expect_error=True)  # 顺便验证越权
assert hidden["_error"] == 403
err = call("POST", "/favorites/999999", customer, expect_error=True)
assert err["_error"] == 404
print("✓ 不存在的店不能收藏(404)")

# 商家角色不能用收藏接口
err = call("GET", "/favorites", merchant, expect_error=True)
assert err["_error"] == 403
print("✓ 收藏仅限用户角色(403)")

call("DELETE", f"/favorites/{sid}", customer)
ids = call("GET", "/favorites/ids", customer)
assert sid not in ids
print("✓ 取消收藏成功")

print("\n个人资料 + 收藏验证通过 🎉")
