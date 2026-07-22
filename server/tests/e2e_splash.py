"""开屏运营位(/splash + /admin/splash)验证:端定向、时间窗、启停、管理员传图。"""
import io
import json
import urllib.request
import uuid

from tests.util import ADMIN, BASE, call, login

admin = login(ADMIN)

# ---- 管理员上传开屏图(multipart,验证 admin 角色已获上传权限) ----
png = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
       b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
boundary = uuid.uuid4().hex
body = io.BytesIO()
body.write(f"--{boundary}\r\n".encode())
body.write(b'Content-Disposition: form-data; name="file"; filename="s.png"\r\n')
body.write(b"Content-Type: image/png\r\n\r\n")
body.write(png)
body.write(f"\r\n--{boundary}--\r\n".encode())
req = urllib.request.Request(BASE + "/upload", data=body.getvalue(), method="POST")
req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
req.add_header("Authorization", f"Bearer {admin}")
with urllib.request.urlopen(req) as resp:
    image_url = json.loads(resp.read())["url"]
assert image_url.startswith("/uploads/")
print(f"✓ 管理员传图成功:{image_url}")

# ---- 发布(定向用户端)→ 端定向命中/不命中 ----
cfg = call("POST", "/admin/splash", admin, {
    "audience": "user", "title": "e2e 开屏", "subtitle": "运营位验证",
    "image_url": image_url, "countdown_seconds": 3,
})
try:
    got = call("GET", "/splash?app=user")
    assert got and got["id"] == cfg["id"] and got["countdown_seconds"] == 3
    assert call("GET", "/splash?app=rider") is None, "定向 user 不该下发给骑手端"
    print("✓ 端定向:user 命中,rider 不命中")

    err = call("POST", "/admin/splash", admin, {
        "audience": "user", "image_url": image_url, "countdown_seconds": 99,
    }, expect_error=True)
    assert err["_error"] == 422
    print("✓ 倒计时越界被拒(422)")

    # 过期配置不下发(建一条已结束的,不影响生效判断)
    old = call("POST", "/admin/splash", admin, {
        "audience": "rider", "image_url": image_url,
        "ends_at": "2020-01-01T00:00:00Z",
    })
    assert call("GET", "/splash?app=rider") is None
    call("POST", f"/admin/splash/{old['id']}/toggle", admin)
    print("✓ 已过期配置不下发")

    # 停用即下线
    call("POST", f"/admin/splash/{cfg['id']}/toggle", admin)
    assert call("GET", "/splash?app=user") is None
    print("✓ 停用后立即不下发,App 回落品牌开屏")
finally:
    # 兜底清场:本测试创建的配置全部停用,不影响后续测试与真实配置
    for row in call("GET", "/admin/splash", admin):
        if row["is_active"] and row["image_url"] == image_url:
            call("POST", f"/admin/splash/{row['id']}/toggle", admin)

print("\ne2e_splash 全部通过 ✅")
