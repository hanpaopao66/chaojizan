"""外卖品类体系验证:清单/筛选/商家改品类/白名单校验。"""
from tests.util import MERCHANT, call, login

cats = call("GET", "/merchants/categories")
assert len(cats) == 23 and cats["fast_food"] == "快餐便当"
assert "noodles" in cats and cats["pastry"] == "糕点甜点"
print(f"✓ 品类清单 {len(cats)} 个,前后端同口径")

merchant = login(MERCHANT)
me = call("GET", "/merchants/me", merchant)
original = me["category"]
assert original in cats, "存量商家必须有合法默认品类"
print(f"✓ 存量商家默认品类:{cats[original]}({original})")

# 改品类即时生效
call("PATCH", "/merchants/me", merchant, {"category": "noodles"})
assert call("GET", "/merchants/me", merchant)["category"] == "noodles"

# 品类筛选:命中/不命中(带坐标走 PostGIS 路径,不带走兜底路径,都验)
lat, lng = 30.6612, 104.0823
hits = call("GET", f"/merchants?lat={lat}&lng={lng}&category=noodles")
assert any(m["id"] == me["id"] for m in hits), "改成米粉面馆后应能按品类筛到"
misses = call("GET", f"/merchants?lat={lat}&lng={lng}&category=pastry")
assert all(m["id"] != me["id"] for m in misses), "糕点甜点品类不该出现这家店"
hits_nogeo = call("GET", "/merchants?category=noodles")
assert any(m["id"] == me["id"] for m in hits_nogeo)
print("✓ 品类筛选命中/不命中(含无坐标兜底路径)")

# 白名单:非法品类一律 422
err = call("PATCH", "/merchants/me", merchant, {"category": "hotel"},
           expect_error=True)
assert err["_error"] == 422
err = call("GET", "/merchants?category=hotel", expect_error=True)
assert err["_error"] == 422
print("✓ 非法品类被拒(422,改/筛都拦)")

# 恢复原品类,不影响其他测试
call("PATCH", "/merchants/me", merchant, {"category": original})
assert call("GET", "/merchants/me", merchant)["category"] == original
print("✓ 品类恢复原值")

print("\ne2e_category 全部通过 ✅")
