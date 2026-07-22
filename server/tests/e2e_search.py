"""搜索深化(清单#58):关键词命中、排序切换、筛选(评分/优惠/起送/距离)、联想。"""
import time
from urllib.parse import quote

from tests.util import call, login


def q(s):
    """中文查询参数需 URL 编码。"""
    return quote(s)

customer = login("13800000001")
merchant = login("13800000002")

# 张记面馆(演示店,春熙路 30.6598,104.0810,有招牌菜)
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
zhang = next(m for m in shops if m["name"] == "张记面馆")
LAT, LNG = 30.6612, 104.0823
tag = int(time.time())
uniq = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"独特搜索菜{tag}", "price_cents": 2000, "stock": 50})

# 关键词命中(菜名)
r = call("GET", f"/merchants/search?q={q(f'独特搜索菜{tag}')}")
assert any(m["id"] == zhang["id"] for m in r), "菜名命中应搜到该店"
print("✓ 菜名命中搜到店")

# 关键词命中(店名)
r = call("GET", f"/merchants/search?q={q('张记')}")
assert any(m["id"] == zhang["id"] for m in r)
print("✓ 店名命中")

# 排序切换:各 sort 都返回且不报错
for sort in ("comprehensive", "distance", "rating", "sales"):
    r = call("GET", f"/merchants/search?q={q('张')}&sort={sort}&lat={LAT}&lng={LNG}")
    assert isinstance(r, list)
print("✓ 四种排序均正常(comprehensive/distance/rating/sales)")

# 无定位时综合/距离退化为评分(不报错)
r = call("GET", f"/merchants/search?q={q('张')}&sort=distance")
assert isinstance(r, list)
print("✓ 无定位时距离/综合排序自动退化,不报错")

# 非法 sort 422
err = call("GET", f"/merchants/search?q={q('张')}&sort=paid_rank", expect_error=True)
assert err["_error"] == 422
print("✓ 非法排序(如竞价)422——不存在花钱买排名")

# 筛选:起送价上限——设一个高起送价的店应被过滤掉
call("PATCH", "/merchants/me", merchant, {"min_order_cents": 5000})
r = call("GET", f"/merchants/search?q={q('张记')}&max_min_order_cents=1000")
assert all(m["id"] != zhang["id"] for m in r), "起送价 50 元 > 上限 10 元应被过滤"
r = call("GET", f"/merchants/search?q={q('张记')}&max_min_order_cents=6000")
assert any(m["id"] == zhang["id"] for m in r)
call("PATCH", "/merchants/me", merchant, {"min_order_cents": 0})
print("✓ 起送价上限筛选")

# 筛选:有优惠——先清空优惠应搜不到(在 has_promo 下),配了满减才出现
call("PATCH", "/merchants/me", merchant, {"promo_rules": [], "gift_rules": []})
r = call("GET", f"/merchants/search?q={q('张记')}&has_promo=true")
assert all(m["id"] != zhang["id"] for m in r), "无优惠时 has_promo 应过滤掉"
call("PATCH", "/merchants/me", merchant,
     {"promo_rules": [{"threshold_cents": 3000, "off_cents": 500}]})
r = call("GET", f"/merchants/search?q={q('张记')}&has_promo=true")
assert any(m["id"] == zhang["id"] for m in r), "配了满减应出现"
call("PATCH", "/merchants/me", merchant, {"promo_rules": []})
print("✓ 有优惠筛选")

# 筛选:距离上限——收货点很远的小半径应搜不到
r = call("GET", f"/merchants/search?q={q('张记')}&lat=31.5&lng=105.5&max_distance_m=1000")
assert all(m["id"] != zhang["id"] for m in r), "远在百公里外 1km 内应搜不到"
print("✓ 距离上限筛选")

# 联想:前缀命中店名/菜名
sug = call("GET", f"/merchants/suggest?q={q('张')}")
assert "张记面馆" in sug["shops"]
sug = call("GET", f"/merchants/suggest?q={q(f'独特搜索菜{tag}')}")
assert any(f"独特搜索菜{tag}" in d for d in sug["dishes"])
print("✓ 联想返回店名+菜名")

call("PATCH", f"/merchants/me/dishes/{uniq['id']}", merchant, {"is_on_sale": False})
print("\n搜索深化验证通过 🎉")
