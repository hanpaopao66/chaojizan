"""商家入驻审核全流程验证"""
import time

from tests.util import call, login

admin = login("13800000000")
print("✓ 管理员登录")

# 新商家注册并申请开店
phone = "139" + str(int(time.time()))[-8:]
boss = call("POST", "/auth/register", body={"phone": phone, "password": "123456", "name": "王老板", "role": "merchant"})["token"]

err = call("POST", "/merchants", boss, {"name": "王记火锅", "address": "测试路 1 号", "lat": 30.66, "lng": 104.08, "license_no": "  ", "license_image_url": "/uploads/fake.jpg"}, expect_error=True)
assert err["_error"] == 422
print("✓ 缺许可证号被拒:" + err["detail"])
err = call("POST", "/merchants", boss, {"name": "王记火锅", "address": "测试路 1 号", "lat": 30.66, "lng": 104.08, "license_no": "JY99900011122233"}, expect_error=True)
assert err["_error"] == 422
print(f"✓ 缺证照照片被拒:{err['detail']}")

shop = call("POST", "/merchants", boss, {"name": "王记火锅", "description": "牛油锅底", "address": "测试路 1 号", "lat": 30.66, "lng": 104.08, "license_no": "JY99900011122233", "license_image_url": "/uploads/license-demo.jpg"})
assert shop["status"] == "pending" and shop["is_open"] is False
sid = shop["id"]
print("✓ 提交申请,状态 pending")

err = call("PATCH", "/merchants/me", boss, {"is_open": True}, expect_error=True)
assert err["_error"] == 403
print(f"✓ 未过审不能营业:{err['detail']}")

public = call("GET", "/merchants?lat=30.66&lng=104.08")
assert all(m["id"] != sid for m in public)
print("✓ 待审核商家不出现在用户端列表")

err = call("GET", "/admin/merchants", boss, expect_error=True)
assert err["_error"] == 403
print("✓ 非管理员访问审核接口被拒(403)")

pending = call("GET", "/admin/merchants?status=pending", admin)
mine = next(m for m in pending if m["id"] == sid)
assert mine["owner_phone"] == phone and mine["license_no"] == "JY99900011122233"
print(f"✓ 后台待审列表 {len(pending)} 家,证照/店主电话齐全")

rejected = call("POST", f"/admin/merchants/{sid}/reject", admin, {"reason": "许可证号查无此证"})
assert rejected["status"] == "rejected"
me = call("GET", "/merchants/me", boss)
assert me["status"] == "rejected" and me["reject_reason"] == "许可证号查无此证"
print("✓ 驳回后商家能看到原因")

me = call("PATCH", "/merchants/me", boss, {"license_no": "JY91510100MA6C8888"})
assert me["status"] == "pending" and me["reject_reason"] == ""
print("✓ 修改资料自动重新进入待审核")

approved = call("POST", f"/admin/merchants/{sid}/approve", admin)
assert approved["status"] == "approved"
me = call("PATCH", "/merchants/me", boss, {"is_open": True})
assert me["is_open"] is True
public = call("GET", "/merchants?lat=30.66&lng=104.08")
assert any(m["id"] == sid for m in public)
print("✓ 过审后可营业,出现在用户端列表")

print("\n入驻审核全流程验证通过 🎉")
