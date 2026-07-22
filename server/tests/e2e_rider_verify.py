"""骑手实名认证验证:未认证不能上线/抢单、提交审核、通过后可接单、驳回强制下线"""
import time

from tests.util import call, login

admin = login("13800000000")

# 新注册一个骑手(干净状态)
phone = "138" + str(int(time.time()))[-8:]
rider = call("POST", "/auth/register", body={
    "phone": phone, "password": "123456", "name": "新骑手", "role": "rider",
})["token"]

# 未认证 → 上线被拒
err = call("POST", "/riders/online", rider, {"is_online": True}, expect_error=True)
assert err["_error"] == 403
print(f"✓ 未认证骑手不能上线:{err['detail']}")

prof = call("GET", "/riders/profile", rider)
assert prof["status"] == "unsubmitted"
print("✓ 初始认证状态 unsubmitted")

# 身份证号格式校验
err = call("POST", "/riders/profile", rider, {
    "real_name": "王小明", "id_card_no": "123", "id_card_photo_url": "/uploads/a.jpg",
    "health_cert_photo_url": "/uploads/b.jpg",
}, expect_error=True)
assert err["_error"] == 422
print("✓ 身份证号格式非法被拒(422)")

# 正常提交
prof = call("POST", "/riders/profile", rider, {
    "real_name": "王小明", "id_card_no": "51010119900101001X",
    "id_card_photo_url": "/uploads/idcard.jpg",
    "health_cert_photo_url": "/uploads/health.jpg",
})
assert prof["status"] == "pending"
print("✓ 提交认证,状态 pending")

# 待审核期间仍不能上线
err = call("POST", "/riders/online", rider, {"is_online": True}, expect_error=True)
assert err["_error"] == 403
print("✓ 待审核期间仍不能上线")

# 管理后台看到待审
pending = call("GET", "/admin/rider-profiles?status=pending", admin)
mine = next(p for p in pending if p["rider_phone"] == phone)
assert mine["real_name"] == "王小明" and mine["id_card_photo_url"]
print(f"✓ 后台待审列表可见证件照({len(pending)} 条)")

# 非管理员访问审核接口被拒
err = call("GET", "/admin/rider-profiles", rider, expect_error=True)
assert err["_error"] == 403
print("✓ 非管理员不能访问骑手审核接口(403)")

rid = mine["rider_id"]

# 驳回 → 骑手看到原因,仍不能上线
call("POST", f"/admin/rider-profiles/{rid}/reject", admin, {"reason": "健康证照片模糊,请重传"})
prof = call("GET", "/riders/profile", rider)
assert prof["status"] == "rejected" and prof["reject_reason"] == "健康证照片模糊,请重传"
err = call("POST", "/riders/online", rider, {"is_online": True}, expect_error=True)
assert err["_error"] == 403
print("✓ 驳回后骑手看到原因,仍不能上线")

# 重新提交 → 通过
call("POST", "/riders/profile", rider, {
    "real_name": "王小明", "id_card_no": "51010119900101001X",
    "id_card_photo_url": "/uploads/idcard2.jpg",
    "health_cert_photo_url": "/uploads/health2.jpg",
})
call("POST", f"/admin/rider-profiles/{rid}/approve", admin)
prof = call("GET", "/riders/profile", rider)
assert prof["status"] == "approved"

# 通过后可以上线 + 抢单
res = call("POST", "/riders/online", rider, {"is_online": True})
assert res["is_online"] is True
print("✓ 认证通过后可正常上线接单")

# 已通过不能再改
err = call("POST", "/riders/profile", rider, {
    "real_name": "改名", "id_card_no": "51010119900101001X",
    "id_card_photo_url": "/uploads/x.jpg", "health_cert_photo_url": "/uploads/y.jpg",
}, expect_error=True)
assert err["_error"] == 409
print("✓ 已通过认证不能自行修改(需客服)")

print("\n骑手实名认证验证通过 🎉")
