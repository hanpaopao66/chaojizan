"""点单页地基验证:店铺详情(月售/公告)、菜品分类、图片上传、搜索"""
import json
import time
import urllib.request
import uuid
from urllib.parse import quote

from tests.util import BASE, call, login

customer = login("13800000001")
merchant = login("13800000002")

# 店铺详情:月售 + 公告
shops = call("GET", "/merchants?lat=30.6612&lng=104.0823")
shop = next(m for m in shops if m["name"] == "张记面馆")
detail = call("GET", f"/merchants/{shop['id']}")
assert isinstance(detail["monthly_sales"], int) and detail["monthly_sales"] >= 1
assert detail["announcement"]
print(f"✓ 店铺详情:月售 {detail['monthly_sales']} 单,公告「{detail['announcement'][:12]}…」")

# 公告可编辑
call("PATCH", "/merchants/me", merchant, {"announcement": "今日特惠:酸辣粉第二份半价"})
detail = call("GET", f"/merchants/{shop['id']}")
assert detail["announcement"] == "今日特惠:酸辣粉第二份半价"
call("PATCH", "/merchants/me", merchant, {"announcement": "新店入驻 Super-Z,平台只抽 5%,让利全在菜价里"})
print("✓ 商家可编辑公告")

# 菜品分类
menu = call("GET", f"/merchants/{shop['id']}/dishes")
categories = {d["category"] for d in menu if d["name"] in ("红烧牛肉面", "酸辣粉", "冰豆浆")}
assert categories == {"招牌", "小吃", "饮品"}, categories
print(f"✓ 菜品带分类:{'、'.join(sorted(categories))}")

dish = call("POST", "/merchants/me/dishes", merchant,
            {"name": f"分类测试-{int(time.time())}", "category": "新品", "price_cents": 999})
assert dish["category"] == "新品"
call("PATCH", f"/merchants/me/dishes/{dish['id']}", merchant, {"is_on_sale": False})
print("✓ 建菜可指定分类")

# 商家管理视角:下架的菜自己能看到,用户端菜单里没有
mine = call("GET", "/merchants/me/dishes", merchant)
offsale = next(d for d in mine if d["id"] == dish["id"])
assert offsale["is_on_sale"] is False
public = call("GET", f"/merchants/{shop['id']}/dishes")
assert all(d["id"] != dish["id"] for d in public)
print("✓ 商家能看到已下架菜品,用户端菜单已隐藏")

err = call("GET", "/merchants/me/dishes", customer, expect_error=True)
assert err["_error"] == 403
print("✓ 非商家角色不能看菜品管理列表(403)")


# 图片上传(手工构造 multipart)
def upload(token, filename, content, expect_error=False):
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(BASE + "/upload", method="POST", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read()).get("detail")
        if expect_error:
            return {"_error": e.code, "detail": detail}
        raise SystemExit(f"FAIL upload: {e.code} {detail}")


PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d4944415478da63fcffff3f030005fe02fea7566d"
    "d70000000049454e44ae426082"
)

err = upload(merchant, "hack.exe", b"MZ...", expect_error=True)
assert err["_error"] == 422
print(f"✓ 非图片扩展名被拒:{err['detail']}")

# 批④起用户也能上传(头像),验证三角色均可用
avatar = upload(customer, "avatar.png", PNG_BYTES)
assert avatar["url"].startswith("/uploads/")
print("✓ 用户可上传头像图")

result = upload(merchant, "dish.png", PNG_BYTES)
assert result["url"].startswith("/uploads/")
with urllib.request.urlopen(BASE + result["url"]) as resp:
    served = resp.read()
assert served == PNG_BYTES
print(f"✓ 图片上传成功且可访问:{result['url']}")

# 门头照:上传的图挂到店铺 logo(测完恢复演示图,别拿 1px 测试图污染门面)
original_logo = detail["logo_url"]
call("PATCH", "/merchants/me", merchant, {"logo_url": result["url"]})
detail = call("GET", f"/merchants/{shop['id']}")
assert detail["logo_url"] == result["url"]
call("PATCH", "/merchants/me", merchant, {"logo_url": original_logo})
print("✓ 门头照可设置,用户端店铺详情可见(已还原演示图)")

# 图片挂到菜品上
dish2 = call("POST", "/merchants/me/dishes", merchant, {
    "name": f"带图菜-{int(time.time())}", "category": "新品",
    "price_cents": 1500, "image_url": result["url"],
})
menu = call("GET", f"/merchants/{shop['id']}/dishes")
assert next(d for d in menu if d["id"] == dish2["id"])["image_url"] == result["url"]
call("PATCH", f"/merchants/me/dishes/{dish2['id']}", merchant, {"is_on_sale": False})
print("✓ 菜品图片字段全链路可用")

# 菜品月售:张记面馆的招牌面历史完成单很多,月售必须 > 0
menu = call("GET", f"/merchants/{shop['id']}/dishes")
noodle = next(d for d in menu if d["name"] == "红烧牛肉面")
assert noodle["monthly_sales"] > 0, noodle
print(f"✓ 菜品月售统计:红烧牛肉面 月售 {noodle['monthly_sales']} 份")

# 搜索:店名命中 / 菜名命中 / 无结果
hits = call("GET", f"/merchants/search?q={quote('张记')}", customer)
assert any(m["id"] == shop["id"] for m in hits)
hits = call("GET", f"/merchants/search?q={quote('牛肉面')}", customer)
assert any(m["id"] == shop["id"] for m in hits)
hits = call("GET", f"/merchants/search?q={quote('不存在的东西xyz')}", customer)
assert hits == []
print("✓ 搜索:店名/在售菜名命中,无关词无结果")

print("\n点单页地基验证通过 🎉")
