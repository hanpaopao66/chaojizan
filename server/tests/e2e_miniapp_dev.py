"""开发者入驻与开发者接口(#329、#330、#331)。

- 注册闸门:默认开放,没收到邀请也能注册 developer;临时收紧成「仅限邀请」/ 暂停时挡新号,已有开发者照常登录;
- 个人认证:证号只存密文、接口只回尾号;未满 18 岁拒;企业认证走人工(通过/驳回/重新提交);
- 未认证能建应用、传版本、加体验者、用模拟器,**不能提交审核**;规则没接受也不能提交;
- IDOR:A 开发者操作 B 的应用、版本、密钥、体验者 → 一律 404;
- 角色隔离:developer 调不了商家、管理接口;顾客调不了 /dev/v1;
- 体验版:体验者能打开,别人 403;名称防仿冒;配额(体验者 20 人)。
"""
import uuid

from tests.miniapp_util import (HELLO, admin_token, customer, developer, id_number, invite,
                                make_zip, new_app, sms_login, upload)
from tests.util import call, fresh_phone

adm = admin_token()

# ---- 注册闸门:默认开放;「仅限邀请」「暂停注册」只是临时收紧用的闸 ----
call("PUT", "/admin/mini-apps/signup-mode", adm, {"mode": "open"})
stranger = fresh_phone("139")
tok = sms_login(stranger, "developer")["token"]          # 没收到邀请也能注册
me = call("GET", "/dev/v1/me", tok)
assert me["status"] == "unverified" and me["phone_tail"] == stranger[-4:]
call("PUT", "/admin/mini-apps/signup-mode", adm, {"mode": "invite"})
outsider = fresh_phone("139")
r = sms_login(outsider, "developer", expect_error=True)
assert r["_error"] == 403 and "邀请" in r["detail"], r
invite(outsider)
assert sms_login(outsider, "developer")["token"]
invites = call("GET", "/admin/mini-apps/invites", adm)["items"]
assert any(i["phone_tail"] == outsider[-4:] and i["used_at"] for i in invites)
assert outsider not in str(invites), "邀请名单不存明文手机号"
call("PUT", "/admin/mini-apps/signup-mode", adm, {"mode": "closed"})
r = sms_login(fresh_phone("139"), "developer", expect_error=True)
assert r["_error"] == 403 and "关闭" in r["detail"]
assert sms_login(stranger, "developer")["token"], "关掉注册不影响已有开发者登录"
call("PUT", "/admin/mini-apps/signup-mode", adm, {"mode": "open"})
print("✓ 注册闸门:默认开放、没邀请也能注册;收紧成仅限邀请 / 暂停时挡新号;已有开发者照常登录;名单只存假名")

# ---- 个人认证 ----
r = call("POST", "/dev/v1/me/verify/individual", tok,
         {"real_name": "张三", "id_no": "610102199001011234"}, expect_error=True)
assert r["_error"] == 422, "校验位不对的证号要拒"
kid = id_number("20150101")
r = call("POST", "/dev/v1/me/verify/individual", tok, {"real_name": "张三", "id_no": kid},
         expect_error=True)
assert r["_error"] == 422 and "18" in r["detail"], r
good = id_number()
me = call("POST", "/dev/v1/me/verify/individual", tok, {"real_name": "张三丰", "id_no": good})
assert me["status"] == "verified" and me["id_no_tail"] == good[-4:]
assert good not in str(me) and "张三丰" not in str(me), "证号、真名不许明文回显"
assert me["real_name_masked"] == "张**" and me["public"]["label"] == "个人开发者 · 已实名"
assert "张三丰" not in str(call("GET", "/admin/mini-apps/developers", adm)), \
    "后台列表里也只有遮住的真名"
print("✓ 个人认证:校验位、18 岁、只存密文只回尾号;公开只显示「个人开发者 · 已实名」")

# ---- 企业认证:人工 驳回 → 重新提交 → 通过 ----
cdev, _ = developer(verified=False)
r = call("POST", "/dev/v1/me/verify/company", cdev,
         {"company_name": "西安测试科技有限公司", "uscc": "91610131MA6TXXXX0A",
          "license_key": "/files/dev_license/u1-" + "0" * 32 + ".jpg", "contact_name": "李四"},
         expect_error=True)
assert r["_error"] == 422, "营业执照必须是自己上传的"
cme = call("GET", "/auth/me", cdev)
key = f"/files/dev_license/u{cme['id']}-{uuid.uuid4().hex}.jpg"
body = {"company_name": "西安测试科技有限公司", "uscc": "91610131MA6TXXXX0A",
        "license_key": key, "contact_name": "李四"}
me = call("POST", "/dev/v1/me/verify/company", cdev, body)
assert me["status"] == "pending"
did = me["id"]
r = call("POST", f"/admin/mini-apps/developers/{did}/verify", adm, {"approve": False},
         expect_error=True)
assert r["_error"] == 422, "驳回必须写原因"
call("POST", f"/admin/mini-apps/developers/{did}/verify", adm,
     {"approve": False, "reason": "营业执照照片看不清"})
me = call("GET", "/dev/v1/me", cdev)
assert me["status"] == "rejected" and me["reject_reason"] == "营业执照照片看不清"
assert call("POST", "/dev/v1/me/verify/company", cdev, body)["status"] == "pending"
call("POST", f"/admin/mini-apps/developers/{did}/verify", adm, {"approve": True})
me = call("GET", "/dev/v1/me", cdev)
assert me["status"] == "verified" and me["public"]["label"] == "企业 · 已认证"
assert me["public"]["name"] == "西安测试科技有限公司", "企业名公开"
assert me["limits"]["max_apps"] == 50
r = call("POST", f"/admin/mini-apps/developers/{did}/verify", adm, {"approve": True},
         expect_error=True)
assert r["_error"] == 409, "已认证的不能再认证一次(状态机)"
print("✓ 企业认证:驳回(必须写原因)→ 重新提交 → 通过;非法迁移 409")

# ---- 未认证能做什么、不能做什么 ----
udev, _ = developer(verified=False, accept_rules=False)
app = new_app(udev)
appid = app["app"]["appid"]
v = upload(udev, appid, make_zip(HELLO))["version"]
call("POST", f"/dev/v1/apps/{appid}/versions/{v['id']}/trial", udev)
tester_tok, tester_phone = customer()
call("POST", f"/dev/v1/apps/{appid}/testers", udev, {"phone": tester_phone})
sim = call("POST", f"/dev/v1/apps/{appid}/sim/launch?version_id={v['id']}", udev, {})
assert "env=sim" in sim["init_data"]
r = call("POST", f"/dev/v1/apps/{appid}/versions/{v['id']}/submit", udev, {}, expect_error=True)
assert r["_error"] == 403 and "认证" in r["detail"], r
call("POST", "/dev/v1/me/verify/individual", udev, {"real_name": "王五", "id_no": id_number()})
r = call("POST", f"/dev/v1/apps/{appid}/versions/{v['id']}/submit", udev, {}, expect_error=True)
assert r["_error"] == 403 and "规则" in r["detail"], "没接受开发者规则也不能提交"
rules = call("GET", "/rules/developer")
assert rules["draft"] is True and any(s["title"] == "配额与限流" for s in rules["sections"])
rev = call("GET", "/dev/v1/me", udev)["agreement"]["required"]
r = call("POST", "/dev/v1/me/agreement", udev, {"revision": rev + 5}, expect_error=True)
assert r["_error"] == 409
call("POST", "/dev/v1/me/agreement", udev, {"revision": rev})
assert call("POST", f"/dev/v1/apps/{appid}/versions/{v['id']}/submit", udev,
            {"review_note": "看首页"})["status"] == "reviewing"
print("✓ 未认证:能建应用、传版本、设体验版、加体验者、用模拟器;认证 + 接受规则后才能提交")

# ---- 体验版 ----
r = call("POST", f"/mini-apps/{appid}/launch", tester_tok, {"trial": True})
assert r["trial"] is True and f"/v/{v['id']}/" in r["url"]
outsider, _ = customer()
r = call("POST", f"/mini-apps/{appid}/launch", outsider, {"trial": True}, expect_error=True)
assert r["_error"] == 403
r = call("POST", f"/mini-apps/{appid}/launch", tester_tok, {}, expect_error=True)
assert r["_error"] == 404, "没上架的应用不能按正式版打开"
r = call("GET", f"/mini-apps/{appid}", outsider, expect_error=True)
assert r["_error"] == 404, "草稿应用对外不可见"
assert call("GET", f"/mini-apps/{appid}", tester_tok)["me"]["tester"] is True
testers = call("GET", f"/dev/v1/apps/{appid}/testers", udev)["items"]
assert testers[0]["phone_tail"] == tester_phone[-4:] and tester_phone not in str(testers)
print("✓ 体验版:体验者能开、别人 403;草稿对外 404;体验者名单只有尾号")

# ---- IDOR:别人的应用一律 404 ----
other, _ = developer()
for method, path, body in (
        ("GET", f"/dev/v1/apps/{appid}", None),
        ("PUT", f"/dev/v1/apps/{appid}", {"tagline": "被改了"}),
        ("GET", f"/dev/v1/apps/{appid}/versions", None),
        ("GET", f"/dev/v1/apps/{appid}/versions/{v['id']}", None),
        ("POST", f"/dev/v1/apps/{appid}/versions/{v['id']}/withdraw", {}),
        ("POST", f"/dev/v1/apps/{appid}/secret/rotate", {}),
        ("GET", f"/dev/v1/apps/{appid}/testers", None),
        ("POST", f"/dev/v1/apps/{appid}/testers", {"phone": fresh_phone()}),
        ("PUT", f"/dev/v1/apps/{appid}/domains", {"request_domains": []}),
        ("GET", f"/dev/v1/apps/{appid}/stats", None),
        ("POST", f"/dev/v1/apps/{appid}/sim/launch?version_id={v['id']}", {}),
        ("POST", f"/dev/v1/apps/{appid}/sim/storage/usage", {})):
    r = call(method, path, other, body, expect_error=True)
    assert r.get("_error") == 404, f"别人的应用 {method} {path} 应 404,得到 {r}"
mine = new_app(other)["app"]["appid"]
r = call("POST", f"/dev/v1/apps/{mine}/versions/{v['id']}/trial", other, {}, expect_error=True)
assert r["_error"] == 404, "拿别人应用的版本号挂到自己应用下也不行"
print("✓ IDOR:别人的应用、版本、密钥、体验者、模拟器 一律 404")

# ---- 角色隔离 ----
for path in ("/merchants/me", "/admin/mini-apps/overview", "/admin/merchants"):
    r = call("GET", path, other, expect_error=True)
    assert r["_error"] in (403, 404), f"developer 不该能调 {path}:{r}"
r = call("GET", "/dev/v1/me", tester_tok, expect_error=True)
assert r["_error"] == 403, "顾客调不了 /dev/v1"
r = call("GET", "/dev/v1/apps", adm, expect_error=True)
assert r["_error"] == 403, "管理员也不走开发者接口"
print("✓ 角色隔离:developer ↛ 商家/管理接口,顾客/管理员 ↛ /dev/v1")

# ---- 名称防仿冒、重名 ----
for bad in ("超级赞外卖", "官方客服", "SuperZ Pay"):
    r = call("POST", "/dev/v1/apps", other, {"name": bad, "kind": "app"}, expect_error=True)
    assert r["_error"] == 422, f"{bad} 应被拒"
dup = call("GET", f"/dev/v1/apps/{mine}", other)["name"]
r = call("POST", "/dev/v1/apps", other, {"name": dup, "kind": "app"}, expect_error=True)
assert r["_error"] == 409, "重名要拒"
print("✓ 名称防仿冒(超级赞/官方/客服/支付)与重名")

# ---- 体验者上限 ----
lim_app = new_app(other)["app"]["appid"]
for i in range(20):
    call("POST", f"/dev/v1/apps/{lim_app}/testers", other, {"phone": fresh_phone("136")})
r = call("POST", f"/dev/v1/apps/{lim_app}/testers", other, {"phone": fresh_phone("136")},
         expect_error=True)
assert r["_error"] == 409 and "20" in r["detail"]
print("✓ 每个应用最多 20 个体验者")

# ---- 能力申请:profile 可申请,M3 能力暂未开放 ----
r = call("POST", f"/dev/v1/apps/{mine}/capabilities", other,
         {"capability": "location", "justification": "要显示附近的东西给用户看"}, expect_error=True)
assert r["_error"] == 422 and "暂未开放" in r["detail"]
cap = call("POST", f"/dev/v1/apps/{mine}/capabilities", other,
           {"capability": "profile", "justification": "在记录旁边显示用户的昵称"})
assert cap["status"] == "requested"
print("✓ 能力申请:profile 进审批队列;定位等 M3 能力暂未开放")

print("\n开发者入驻与接口验证通过 🎉")
