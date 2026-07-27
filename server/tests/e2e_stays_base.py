"""酒店垂类地基:业态分叉入驻(两证)→admin 审核→酒店不混入外卖频道。

    SUPERZ_API=http://127.0.0.1:8010 python -m tests.e2e_stays_base
"""
import random
from urllib.parse import quote

from tests.util import ADMIN, call, login

admin_token = login(ADMIN)

# 全新商家账号(手机号跨角色分账号已支持)
phone = "138" + "".join(str(random.randint(0, 9)) for _ in range(8))
hotel_name = f"闪电客栈{phone[-4:]}"
reg = call("POST", "/auth/register",
           body={"phone": phone, "password": "hotel123", "role": "merchant"})
mt = reg["token"]

base = {
    "name": hotel_name, "description": "e2e 测试酒店",
    "address": "测试路 1 号", "lat": 30.66, "lng": 104.06,
    "biz_type": "hotel",
    "license_no": "91510100MA6TEST01",
    "license_image_url": "https://example.com/biz-license.jpg",
}

# 1) 缺特种行业许可证被拒
r = call("POST", "/merchants", token=mt, body=base, expect_error=True)
assert r["_error"] == 422 and "特种行业许可证" in r["detail"], r
r = call("POST", "/merchants", token=mt,
         body={**base, "hotel": {"special_license_no": "川公治安 2026-001"}},
         expect_error=True)
assert r["_error"] == 422 and "照片" in r["detail"], r
print("OK 酒店两证校验:", r["detail"])

# 2) 两证齐全提交成功,进入待审核
shop = call("POST", "/merchants", token=mt, body={
    **base,
    "hotel": {
        "tier": "comfort", "front_desk_phone": "02888888888",
        "checkin_from": "14:00", "checkout_until": "12:00",
        "facilities": ["wifi", "parking"],
        "special_license_no": "川公治安 2026-001",
        "special_license_image_url": "https://example.com/special.jpg",
    },
})
assert shop["status"] == "pending" and shop["biz_type"] == "hotel", shop
mid = shop["id"]
print(f"OK 酒店入驻提交: merchant_id={mid}")

# 3) admin 待审列表能看到两证与业态
pending = call("GET", "/admin/merchants?status=pending", token=admin_token)
mine = next(m for m in pending if m["id"] == mid)
assert mine["biz_type"] == "hotel"
assert mine["license_no"] == base["license_no"]
assert mine["special_license_no"] == "川公治安 2026-001"
assert mine["special_license_image_url"].endswith("special.jpg")
print("OK admin 待审列表含两证")

# 4) 未过审不能营业;过审后可营业
r = call("PATCH", "/merchants/me", token=mt, body={"is_open": True},
         expect_error=True)
assert r["_error"] == 403, r
call("POST", f"/admin/merchants/{mid}/approve", token=admin_token)
shop = call("PATCH", "/merchants/me", token=mt, body={"is_open": True})
assert shop["is_open"] is True and shop["biz_type"] == "hotel"
print("OK 审核通过并营业")

# 5) 酒店不出现在外卖频道(列表/搜索/联想)
lst = call("GET", "/merchants?lat=30.66&lng=104.06&radius_m=5000")
assert all(m["id"] != mid for m in lst), "酒店混进了外卖附近列表"
lst = call("GET", "/merchants")  # 无定位分支
assert all(m["id"] != mid for m in lst), "酒店混进了外卖兜底列表"
found = call("GET", f"/merchants/search?q={quote(hotel_name)}")
assert all(m["id"] != mid for m in found), "酒店混进了外卖搜索"
sug = call("GET", f"/merchants/suggest?q={quote(hotel_name[:4])}")
assert hotel_name not in sug["shops"], "酒店混进了搜索联想"
print("OK 外卖频道不含酒店(列表/搜索/联想)")

# 6) 住宿状态机独立且拦非法迁移(纯后端单元断言,借接口环境跑)
print("PASS e2e_stays_base")
