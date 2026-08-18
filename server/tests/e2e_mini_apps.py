"""小程序清单与 initData 签发(#277)。

- 未登录拿不到清单;
- 登录后清单只含上架条目、不下发运营字段;
- initData 结构完整(四字段 payload + 64 位 hex 签名),不含任何 token;
- 下架后清单消失、initData 404;跑完把状态还原,不留脏数据。
"""
from tests.util import ADMIN, CUSTOMER, call, login

r = call("GET", "/mini-apps", expect_error=True)
assert r["_error"] == 401, f"未登录应 401,得到 {r}"
print("✓ 未登录拿不到清单")

token = login(CUSTOMER)
apps = call("GET", "/mini-apps", token=token)
assert isinstance(apps, list) and apps, "清单不该为空(seed 有两条自家小程序)"
names = {a["name"] for a in apps}
assert "透明中心" in names, f"缺透明中心:{names}"
for a in apps:
    assert a["entry_url"].startswith("http"), a
    assert isinstance(a["allowed_origins"], list) and a["allowed_origins"], \
        "allowed_origins 是桥的安全边界,不许为空"
    assert "status" not in a and "created_at" not in a, "运营字段不该下发"
sorts = [a["sort"] for a in apps]
assert sorts == sorted(sorts), "清单必须按 sort 升序 —— 顺序是运营拍的"
print(f"✓ 清单 {len(apps)} 条,字段与顺序合规")

app_id = next(a["id"] for a in apps if a["name"] == "透明中心")
pack = call("POST", f"/mini-apps/{app_id}/init-data", token=token)
p = pack["payload"]
assert set(pack) == {"payload", "sign"}, pack
assert set(p) == {"app_id", "auth_date", "name", "user_id"}, p
assert p["app_id"] == app_id and isinstance(p["user_id"], int)
assert len(pack["sign"]) == 64
int(pack["sign"], 16)  # 非 hex 会抛
pack2 = call("POST", f"/mini-apps/{app_id}/init-data", token=token)
assert pack2["payload"]["auth_date"] >= p["auth_date"]
print("✓ initData:四字段 payload + 64 位 hex 签名")

admin = login(ADMIN)
toggled = call("POST", f"/mini-apps/admin/{app_id}/toggle", token=admin)
assert toggled["status"] == "off"
try:
    names_off = {a["name"] for a in call("GET", "/mini-apps", token=token)}
    assert "透明中心" not in names_off, "下架后不该出现在清单里"
    r = call("POST", f"/mini-apps/{app_id}/init-data", token=token, expect_error=True)
    assert r["_error"] == 404, f"下架后 initData 应 404,得到 {r}"
finally:
    # 还原上架:e2e 不给下一个用例留脏状态
    restored = call("POST", f"/mini-apps/admin/{app_id}/toggle", token=admin)
    assert restored["status"] == "on"
assert "透明中心" in {a["name"] for a in call("GET", "/mini-apps", token=token)}
print("✓ 下架/上架闭环,状态已还原")

r = call("GET", "/mini-apps/admin", token=token, expect_error=True)
assert r["_error"] == 403, "普通用户不该看到管理清单"
print("✓ 管理接口对普通用户 403")

print("\n小程序清单与 initData 验证通过 🎉")
