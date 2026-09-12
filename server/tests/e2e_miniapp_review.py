"""审核与治理(#332)。每条硬规矩都有一个用例:

- 驳回没有原因代码或说明 → 422;通过时审核清单没逐项确认 → 422;
- 非法状态迁移(已驳回的再通过、没过审的发布、回滚到没发布过的版本)→ 409;
- 审核队列带与上一个通过版本的差异(文件、superz.json、服务器域名、展示信息);
- 上架后改名称,改动随下一个版本送审,发布时才生效;
- 自动发布;回滚到历史版本;
- 暂停 → 启动 423/4009、目录消失;恢复要写依据;
- 申诉:7 天内一次;**原结论人处理自己的申诉 → 403**;另一名审核员改判后状态真的回来;
- 投诉:7 天内 5 个不同的人投诉,自动进复审;举报人身份不给开发者;
- 精选:只收在线应用,理由公示;透明中心能看到下架记录与审核统计。
"""
import uuid
from urllib.parse import quote

from tests.miniapp_util import (CHECKLIST_ALL, HELLO, admin_token, customer, developer,
                                make_zip, new_app, publish, sql, upload)
from app.security import hash_password
from tests.util import DEMO_PASSWORD, call, fresh_phone, login

adm = admin_token()
dev, _ = developer()
appid = new_app(dev)["app"]["appid"]

v1 = upload(dev, appid, make_zip(HELLO))["version"]
r = call("POST", f"/dev/v1/apps/{appid}/versions/{v1['id']}/release", dev, expect_error=True)
assert r["_error"] == 409, "没过审的版本不能发布"
call("POST", f"/dev/v1/apps/{appid}/versions/{v1['id']}/submit", dev, {"review_note": "看首页"})
queue = call("GET", "/admin/mini-apps/reviews", adm)
assert any(x["version"]["id"] == v1["id"] for x in queue["items"])
r = call("POST", f"/admin/mini-apps/reviews/{v1['id']}/decide", adm,
         {"approve": False, "reason_code": "R101"}, expect_error=True)
assert r["_error"] == 422, "驳回没写说明要拒"
r = call("POST", f"/admin/mini-apps/reviews/{v1['id']}/decide", adm,
         {"approve": False, "note_public": "打不开"}, expect_error=True)
assert r["_error"] == 422, "驳回没选原因代码要拒"
r = call("POST", f"/admin/mini-apps/reviews/{v1['id']}/decide", adm,
         {"approve": True, "checklist": {**CHECKLIST_ALL, "privacy": False}}, expect_error=True)
assert r["_error"] == 422, "清单没逐项确认不能通过"
call("POST", f"/admin/mini-apps/reviews/{v1['id']}/decide", adm,
     {"approve": False, "reason_code": "R103", "note_public": "首页只有 hello,是测试页",
      "note_internal": "内部备注:不公开"})
r = call("POST", f"/admin/mini-apps/reviews/{v1['id']}/decide", adm,
         {"approve": True, "checklist": CHECKLIST_ALL}, expect_error=True)
assert r["_error"] == 409, "已驳回的不能再给通过(状态机)"
decisions = call("GET", f"/dev/v1/apps/{appid}/decisions", dev)["items"]
rej = next(d for d in decisions if d["action"] == "reject")
assert rej["reason_code"] == "R103" and rej["reason_label"] and rej["appealable"]
assert "内部备注" not in str(decisions), "内部备注绝不给开发者"
print("✓ 驳回必须带原因代码和说明;清单逐项确认;非法迁移 409;开发者看不到内部备注")

# ---- 申诉:原结论人不能处理 ----
appeal = call("POST", f"/dev/v1/decisions/{rej['id']}/appeal", dev,
              {"text": "首页之后还有完整功能,请点进去看看再判"})
r = call("POST", f"/dev/v1/decisions/{rej['id']}/appeal", dev,
         {"text": "再申诉一次试试看能不能行"}, expect_error=True)
assert r["_error"] == 409, "每个结论只能申诉一次"
r = call("POST", f"/admin/mini-apps/appeals/{appeal['id']}/resolve", adm,
         {"overturn": True, "note_public": "自己改判自己"}, expect_error=True)
assert r["_error"] == 403 and "另一名审核员" in r["detail"], "原结论人处理自己的申诉必须拒绝"
listing = call("GET", "/admin/mini-apps/appeals", adm)["items"]
mine = next(x for x in listing if x["appeal"]["id"] == appeal["id"])
assert mine["you_decided_original"] is True

# 第二名审核员(直连库建;演示库只有一个管理员)
phone2 = fresh_phone("135")
sql("INSERT INTO users (phone, name, role, password_hash, is_online, avatar_url) "
    "VALUES (:p, '审核员乙', 'admin', :h, false, '')",
    {"p": phone2, "h": hash_password(DEMO_PASSWORD)})
adm2 = login(phone2)
call("POST", f"/admin/mini-apps/appeals/{appeal['id']}/resolve", adm2,
     {"overturn": True, "note_public": "复核后功能完整,撤销驳回", "note_internal": "乙复核"})
v = call("GET", f"/dev/v1/apps/{appid}/versions/{v1['id']}", dev)
assert v["status"] == "approved", f"申诉成立后版本要回到审核通过:{v['status']}"
r = call("POST", f"/admin/mini-apps/appeals/{appeal['id']}/resolve", adm2,
         {"overturn": False, "note_public": "重复处理"}, expect_error=True)
assert r["_error"] == 409
print("✓ 申诉:一次;原结论人 403;另一名审核员改判后版本真的回到「审核通过」")

# ---- 发布、上架后改名随版本送审、差异、回滚、自动发布 ----
call("POST", f"/dev/v1/apps/{appid}/versions/{v1['id']}/release", dev)
d = call("GET", f"/mini-apps/{appid}")
assert d["status"] == "online" and d["first_released_at"]
old_name = d["name"]
new_name = f"改名{uuid.uuid4().hex[:4]}"
call("PUT", f"/dev/v1/apps/{appid}", dev, {"name": new_name})
assert call("GET", f"/mini-apps/{appid}")["name"] == old_name, "上架后改名不能当场生效"
call("PUT", f"/dev/v1/apps/{appid}/domains", dev, {"request_domains": ["https://api.example.org"]})
v2 = upload(dev, appid, make_zip({**HELLO, "app.js": "console.log(2)", "new.js": "1"}),
            version="1.1.0")["version"]
call("POST", f"/dev/v1/apps/{appid}/versions/{v2['id']}/submit", dev, {})
detail = call("GET", f"/admin/mini-apps/reviews/{v2['id']}", adm)
diff = detail["diff"]
assert diff["baseline"]["id"] == v1["id"]
assert diff["files"]["added"] == ["new.js"] and diff["files"]["changed"] == ["app.js"]
assert diff["domains"]["added"] == ["https://api.example.org"]
assert diff["listing"]["name"] == {"before": old_name, "after": new_name}
assert detail["checklist_version"] == 1 and len(detail["checklist"]) == 10
call("POST", f"/admin/mini-apps/reviews/{v2['id']}/decide", adm,
     {"approve": True, "checklist": CHECKLIST_ALL})
call("POST", f"/dev/v1/apps/{appid}/versions/{v2['id']}/release", dev)
d = call("GET", f"/mini-apps/{appid}")
assert d["name"] == new_name and d["version"]["id"] == v2["id"], "发布时展示信息一起生效"
assert d["first_released_at"] == call("GET", f"/mini-apps/{appid}")["first_released_at"]
print("✓ 审核看得到文件、域名、展示信息的差异;改名随版本送审、发布才生效")

r = call("POST", f"/dev/v1/apps/{appid}/rollback", dev, {"version_id": v2["id"]},
         expect_error=True)
assert r["_error"] == 409, "已经是当前版本"
call("POST", f"/dev/v1/apps/{appid}/rollback", dev, {"version_id": v1["id"]})
assert call("GET", f"/mini-apps/{appid}")["version"]["id"] == v1["id"]
vs = {x["id"]: x["status"] for x in call("GET", f"/dev/v1/apps/{appid}/versions", dev)["items"]}
assert vs[v1["id"]] == "released" and vs[v2["id"]] == "superseded"
call("PUT", f"/dev/v1/apps/{appid}/auto-release", dev, {"enabled": True})
v3 = upload(dev, appid, make_zip({**HELLO, "app.js": "console.log(3)"}), version="1.2.0")["version"]
call("POST", f"/dev/v1/apps/{appid}/versions/{v3['id']}/submit", dev, {})
call("POST", f"/admin/mini-apps/reviews/{v3['id']}/decide", adm,
     {"approve": True, "checklist": CHECKLIST_ALL})
assert call("GET", f"/mini-apps/{appid}")["version"]["id"] == v3["id"], "打开了自动发布,过审即上线"
print("✓ 回滚到历史版本;自动发布")

# ---- 暂停 / 恢复 ----
user, _ = customer()
call("POST", f"/mini-apps/{appid}/launch", user, {})
r = call("POST", f"/admin/mini-apps/apps/{appid}/suspend", adm, {"reason_code": "R999",
         "note_public": "x" * 5}, expect_error=True)
assert r["_error"] == 422, "不存在的原因代码要拒"
call("POST", f"/admin/mini-apps/apps/{appid}/suspend", adm,
     {"reason_code": "R204", "note_public": "诱导分享才能继续使用"})
r = call("POST", f"/mini-apps/{appid}/launch", user, {}, expect_error=True)
assert r["_error"] == 423 and r["detail"]["code"] == 4009
assert appid not in str(call("GET", "/mini-apps/catalog"))
r = call("POST", f"/dev/v1/apps/{appid}/online", dev, expect_error=True)
assert r["_error"] == 409, "被平台暂停的,开发者自己上不了架"
r = call("POST", f"/admin/mini-apps/apps/{appid}/restore", adm, {"note": ""}, expect_error=True)
assert r["_error"] == 422, "恢复要写依据"
call("POST", f"/admin/mini-apps/apps/{appid}/restore", adm, {"note": "1.2.0 已去掉诱导分享"})
assert call("POST", f"/mini-apps/{appid}/launch", user, {})["url"]
print("✓ 暂停:启动 4009、目录消失、开发者上不了架;恢复要写依据")

# ---- 投诉阈值 ----
for i in range(5):
    t, _ = customer()
    call("POST", f"/mini-apps/{appid}/report", t,
         {"reason_code": "R204", "detail": f"第 {i} 个人:要分享才能用"})
groups = call("GET", "/admin/mini-apps/reports", adm)["groups"]
g = next(x for x in groups if x["appid"] == appid)
assert g["distinct_reporters"] >= 5 and g["flagged"]
flags = [d for d in call("GET", f"/dev/v1/apps/{appid}/decisions", dev)["items"]
         if d["action"] == "flag_review"]
assert flags, "5 个不同的人投诉后要自动进复审(留一条记录)"
reps = call("GET", f"/dev/v1/apps/{appid}/reports", dev)["items"]
assert reps and all(set(x) == {"id", "reason_code", "reason_label", "status", "resolution",
                               "created_at"} for x in reps), "开发者看不到举报人和说明原文"
r = call("POST", f"/mini-apps/{appid}/report", user, {"reason_code": "R701", "detail": ""},
         expect_error=True)
assert r["_error"] == 422, "选「其他」要写明"
call("POST", f"/admin/mini-apps/reports/{g['items'][0]['id']}/handle", adm,
     {"resolution": "已要求开发者整改"})
print("✓ 投诉:5 人阈值自动进复审;开发者看不到举报人;「其他」必须写明")

# ---- 精选与透明中心 ----
call("POST", "/admin/mini-apps/curation", adm,
     {"appid": appid, "position": 1, "reason": "测试精选:功能完整、没有诱导"})
cat = call("GET", "/mini-apps/catalog")["items"]
top = [x["appid"] for x in cat[:len([c for c in cat if c["curated"]])]]
assert appid in top and all(x["curated"] for x in cat[:len(top)]), "精选位排在最前"
tp = call("GET", "/transparency/miniapps")
assert any(c["appid"] == appid for c in tp["curation"])
assert any(t["action"] == "暂停" and t["reason_category"] == "内容" for t in tp["takedowns"])
assert tp["month"]["submitted"] >= 3 and tp["month"]["approved"] >= 2
assert "内部备注" not in str(tp) and "乙复核" not in str(tp)
call("DELETE", f"/admin/mini-apps/curation/{appid}?reason={quote('测试结束移出精选')}", adm)
print("✓ 精选理由公示;透明中心有下架记录与审核统计,不含内部备注")

# ---- 移除(终态)与申诉改判 ----
call("POST", f"/admin/mini-apps/apps/{appid}/remove", adm,
     {"reason_code": "R601", "note_public": "使用了他人的商标"})
r = call("POST", f"/admin/mini-apps/apps/{appid}/restore", adm, {"note": "想把它恢复上线"},
         expect_error=True)
assert r["_error"] == 409, "移除是终态,常规恢复走不通"
rm = next(d for d in call("GET", f"/dev/v1/apps/{appid}/decisions", dev)["items"]
          if d["action"] == "remove")
ap = call("POST", f"/dev/v1/decisions/{rm['id']}/appeal", dev,
          {"text": "商标是我们自己注册的,附了注册证编号"})
call("POST", f"/admin/mini-apps/appeals/{ap['id']}/resolve", adm2,
     {"overturn": True, "note_public": "核实商标归属开发者,撤销移除"})
assert call("GET", f"/dev/v1/apps/{appid}", dev)["status"] == "offline", \
    "申诉成立是唯一从移除回来的路,回到下架由开发者决定何时上架"
print("✓ 移除是终态;申诉成立后回到「下架」")

# 第二名审核员用完就停用(审核记录里引用着它,不能删行)
sql("UPDATE users SET role = 'customer', deleted_at = now(), phone = 'del' || id::text "
    "WHERE phone = :p", {"p": phone2})
print("\n审核与治理验证通过 🎉")
